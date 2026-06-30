"""
VT 分析流水线编排模块

为什么需要这个模块：
  vt analyze 是 VT 的核心命令，需要按严格顺序串联多个模块完成分析。
  本模块是唯一的编排入口，决定"什么时候调用谁"。

核心设计（与 refactoring_design.md §3 对齐）：
  1. 加载输入 (_load_context)
  2. Claim 覆盖前置检查（domain/gate/claim_coverage.py）
  3. 执行工具 (ToolExecutionEngine.execute_from_claims)
  4. 创建数据库 (init_in_memory_db)
  5. 灌入基础数据 (load_prd + load_tasks + load_claims)
  6. 构建证据 (EvidenceBuilder.merge/apply/persist)
  7. 运行分析 (db.check_*)
  8. 门禁判定 + 输出

依赖关系：
  被 cli/main.py 通过 _dispatch() 调用。
  调用以下模块：tools（工具执行）、
  reports（报告）、output（渲染）、domain/evidence（证据构建）、
  domain/gate（门禁判定 + claim_coverage）、infra/db（数据库）
"""

import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Optional, Set

from vibe_tracing.domain.gate.engine import MergeGateEngine
from vibe_tracing.domain.evidence.builder import EvidenceBuilder
from vibe_tracing.domain.context import UnifiedContext

from vibe_tracing.cli.analyze.exceptions import _GateBlocked
from vibe_tracing.infra.loader.config import load_config, resolve_path
from vibe_tracing.infra.loader.raw_input import RawInputLoader, STATUS_OK, STATUS_MISSING
from vibe_tracing.infra.loader.prd_parser import PrdParser
from vibe_tracing.infra.loader.task_loader import TaskLoader
from vibe_tracing.infra.loader.claim_loader import ClaimLoader
from vibe_tracing.domain.gate.staleness import determine_affected_items as _determine_affected_items

from vibe_tracing.infra.tools.executor import ToolExecutionEngine
from vibe_tracing.cli.analyze.reports import _build_report_document
from vibe_tracing.cli.analyze.output import _render_output


def _load_context(
    project_root: Path,
) -> UnifiedContext:
    """Load all input files, validate schemas, and build UnifiedContext.

    Raises _GateBlocked with exit_code=1 on any validation failure.
    """
    try:
        config = load_config(project_root)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise _GateBlocked(1)

    raw_loader = RawInputLoader(project_root, config_data=config)
    manifest = raw_loader.load()

    config_prefix = config.get("project_prefix", "VT")

    # Check for missing required files
    if manifest.has_required_errors:
        for record in manifest.inputs_used:
            if record.is_required and record.status != STATUS_OK:
                print(
                    f"Error loading required file {record.file_key} ({record.file_path}): {record.error_message}",
                    file=sys.stderr,
                )
        raise _GateBlocked(1)

    # Check for malformed files
    for record in manifest.inputs_used:
        if record.status not in (STATUS_OK, STATUS_MISSING):
            print(
                f"Error loading file {record.file_key} ({record.file_path}): {record.error_message}",
                file=sys.stderr,
            )
            raise _GateBlocked(1)

    # 统一格式校验
    from vibe_tracing.infra.validation import validate_inputs
    schemas_dir = project_root / "schemas"
    if not schemas_dir.is_dir():
        schemas_dir = Path(__file__).parents[2] / "infra" / "validation" / "schemas"
    validation_result = validate_inputs(manifest, config_prefix, schemas_dir=schemas_dir)
    if not validation_result.is_valid:
        print(validation_result.format_errors(), file=sys.stderr)
        raise _GateBlocked(1)

    records_dict = {r.file_key: r for r in manifest.inputs_used}
    prd_record = records_dict.get("prd")
    task_list_record = records_dict.get("task_list")
    constraints_record = records_dict.get("architecture_constraints")
    claims_record = records_dict.get("agent_claims")

    if not prd_record or prd_record.status != STATUS_OK:
        print("Error: PRD file missing or failed to load.", file=sys.stderr)
        raise _GateBlocked(1)

    # Parse PRD — use already-loaded content to avoid re-reading from disk
    prd_parser = PrdParser()
    prd_res = prd_parser.parse_text(prd_record.content)
    if not prd_res.is_valid:
        print(f"PRD parsing error: {'; '.join(prd_res.errors)}", file=sys.stderr)
        raise _GateBlocked(1)

    # Verify required files exist (draft PRD already rejected by finalize)
    if not task_list_record or task_list_record.status != STATUS_OK:
        task_list_path = resolve_path(project_root, config, "task_list")
        print(
            f"Error loading required file task_list ({task_list_path}): File not found",
            file=sys.stderr,
        )
        raise _GateBlocked(1)

    # Load tasks
    task_res = None
    if task_list_record and task_list_record.status == STATUS_OK:
        task_list_path = Path(task_list_record.file_path)
        task_loader = TaskLoader()
        task_res = task_loader.deserialize(task_list_record.content)

    # Load claims
    claims_list = []
    if claims_record and claims_record.status == STATUS_OK:
        claims_path = Path(claims_record.file_path)
        claim_loader = ClaimLoader()
        claim_res_loader = claim_loader.deserialize(claims_record.content)
        claims_list = claim_res_loader.claims

    # 加载 human_decisions
    hd_record = records_dict.get("human_decisions")
    human_decisions_data = hd_record.content if hd_record and hd_record.status == STATUS_OK else None

    # 预计算治理文件白名单（业务逻辑在 claim_coverage.py，此处仅调用）
    from vibe_tracing.domain.gate.claim_coverage import build_governance_whitelist
    from vibe_tracing.infra.config.boundary import load_boundary
    governance_whitelist = build_governance_whitelist(manifest, project_root)
    constraints_data = constraints_record.content
    governance_boundary = load_boundary(project_root, constraints_data=constraints_data)

    ctx = UnifiedContext(
        config=config,
        prd=prd_res,
        constraints=constraints_data,
        task_result=task_res,
        claims_list=claims_list,
        manifest=manifest,
        human_decisions=human_decisions_data,
        config_prefix=config_prefix,
        governance_whitelist=governance_whitelist,
        governance_boundary=governance_boundary,
    )
    return ctx


def run_analyze(
    project_root: Path,
    output_dir: Optional[Path] = None,
    incremental_only: bool = False,
    show_historical_debt: bool = True,
) -> int:
    """执行完整的 VT 分析流水线。

    输入：
        project_root: 项目根目录（由 cli/main.py 传入）
        output_dir:   输出目录（可选，默认从 config.json 读取）
        incremental_only: 是否只检查增量问题（历史债务不阻塞门禁）
        show_historical_debt: 是否在终端显示历史债务详情
    前置条件：
        项目已完成 vt finalize（config.json 存在且有效）
    处理逻辑（8 个阶段）：
        1. _load_context：加载 PRD、Tasks、Claims、Config
        2. 幽灵代码检测（domain/gate/claim_coverage.py）
        3. execute_from_claims：执行 pytest/ruff/bandit/coverage
        4. init_in_memory_db：创建内存数据库
        5. load_prd + load_tasks + load_claims：将数据灌入数据库
        6. EvidenceBuilder.merge/apply/persist：构建证据
        7. _run_db_analysis：运行分析（db.check_*）
        8. _evaluate_and_output：门禁判定 + 报告生成 + Dashboard 渲染
    输出：
        退出码：0=通过, 1=执行错误, 2=门禁 blocked
    """
    conn = None
    try:
        # 获取 main() 已初始化的日志实例；若直接调用（非 main 路径），则自动初始化
        from vibe_tracing.infra.logging.logger import OperationalLogger
        from vibe_tracing.infra.db import init_in_memory_db, load_tasks, load_claims, load_prd, load_architecture_constraints, load_staged_files
        _run_start_t = time.perf_counter()

        # ── 阶段 1：加载输入 ──────────────────────────────────────────────
        _t_ctx = time.perf_counter()
        ctx = _load_context(project_root)

        log_level = ctx.config.get("logging", {}).get("level", "DEBUG")
        try:
            vt_logger = OperationalLogger.get_or_init(
                run_id=f"ANALYZE-{uuid.uuid4()}", project_root=project_root,
                level=log_level,
            )
        except Exception:
            vt_logger = OperationalLogger.get()
        vt_logger.info("run_start", "Analysis pipeline started")
        vt_logger.info("phase_end", "Load context completed",
                       phase="load_context",
                       duration_ms=int((time.perf_counter() - _t_ctx) * 1000),
                       config_prefix=ctx.config_prefix,
                       claims_count=len(ctx.claims_list),
                       )

        # 解析输出目录（未指定时从 config 读取）
        if output_dir is None:
            output_dir = resolve_path(project_root, ctx.config, "output_dir")

        # ── 阶段 2：幽灵代码检测（Gate 2）────────────────────────────
        _t_gates = time.perf_counter()

        # staged_files 获取（一次 subprocess，阶段 2/3/7 共用）
        try:
            _git_result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=project_root, capture_output=True, text=True, timeout=10,
            )
            staged_files = (
                {f for f in _git_result.stdout.splitlines() if f.strip()}
                if _git_result.returncode == 0 and _git_result.stdout.strip()
                else set()
            )
        except Exception as exc:
            vt_logger.warning("staged_files_unavailable",
                              "Could not get staged files from git", exc=exc)
            staged_files = set()

        from vibe_tracing.domain.gate.claim_coverage import detect_ghost_code
        result = detect_ghost_code(ctx, staged_files)
        exit_code = None
        if not result.is_pass:
            vt_logger.warning("ghost_code_blocked",
                              "Ghost code detected, commit blocked",
                              ghost_files=sorted(result.ghost_files),
                              ghost_count=len(result.ghost_files))
            files_str = "\n".join(f"  - {f}" for f in sorted(result.ghost_files))
            print(
                "发现未经报备的幽灵代码！\n"
                f"{files_str}\n"
                "上述文件在本次提交中没有对应的【活跃发票】（Claim）。\n"
                "如果它是合法代码，请在 .vibetracing/claims/ 中创建或更新对应的 Claim 文件，"
                "并将其与代码一同提交。",
                file=sys.stderr,
            )
            exit_code = 1

        vt_logger.info("phase_end", "Integrity gates completed",
                       phase="integrity_gates",
                       duration_ms=int((time.perf_counter() - _t_gates) * 1000),
                       gate_result="pass" if exit_code is None else "blocked",
                       exit_code=exit_code if exit_code is not None else 0,
                       staged_files_count=len(staged_files),
                       )
        if exit_code is not None:
            return exit_code

        # ── 阶段 3：执行验证工具 ──────────────────────────────────
        _t_tools = time.perf_counter()
        config_data = ctx.config
        config_language = config_data["language"]
        ltm = config_data["language_tool_matrix"]
        config_validation_tools = [
            k for k, v in ltm.get(config_language, {}).items() if isinstance(v, dict)
        ]
        engine = ToolExecutionEngine(
            language_tool_matrix=ltm,
            language=config_language,
            validation_tools=config_validation_tools,
            project_root=project_root,
            coverage_baseline_path=str(project_root / "coverage.json"),
        )
        result = engine.execute_from_claims(ctx.claims_list, project_root)
        tool_evidence = result.candidates

        # Agent repair guide (CLI layer: user-facing output only)
        if result.skipped:
            if result.skip_reason == "precheck_failed":
                print("\n[AI Agent Repair Guide]", file=sys.stderr)
                print(f"VT depends on tools that are missing: {', '.join(result.missing_tools)}", file=sys.stderr)
                print(f"Action Required: pip install {' '.join(result.missing_tools)}", file=sys.stderr)
            elif result.skip_reason in ("no_code_files", "no_extensions"):
                print(f"Skipping tool execution: {result.skip_reason}.", file=sys.stderr)
        else:
            for c in tool_evidence:
                if c.error_code is not None:
                    details = c.details or {}
                    error_type = details.get("error_type", "unknown")
                    if error_type == "timeout":
                        print(f"Error: {c.source_path} timed out after {details.get('timeout_seconds', '?')}s.", file=sys.stderr)
                    elif error_type == "tool_not_found":
                        print(f"Error: tool not found for {c.source_path}.", file=sys.stderr)
                    else:
                        print(f"Error: {c.source_path} failed (exit code {c.exit_code}). {c.stderr}", file=sys.stderr)

        # tool_evidence is a pipeline-local variable, NOT stored in ctx
        vt_logger.info("phase_end", "Tool execution completed",
                       phase="execute_tools",
                       duration_ms=int((time.perf_counter() - _t_tools) * 1000),
                       tools_executed=len(tool_evidence),
                       )

        # ── 阶段 4：创建内存数据库 ──────────────────────────────────
        _t_db = time.perf_counter()
        conn = init_in_memory_db()

        # ── 阶段 5：灌入基础数据（load_prd 必须先于 load_tasks/load_claims）──
        # load_prd 将 requirements + acceptance_criteria 写入 DB，
        # 是 check_requirement_coverage 和 check_ac_coverage 新模式的前置依赖。
        load_prd(conn, ctx.prd)
        if ctx.task_result and ctx.task_result.tasks:
            load_tasks(conn, [t.__dict__ for t in ctx.task_result.tasks])
        if ctx.claims_list:
            load_claims(conn, [c.__dict__ for c in ctx.claims_list])
        if ctx.constraints:
            load_architecture_constraints(conn, ctx.constraints)
        if staged_files:
            load_staged_files(conn, staged_files)
        vt_logger.info("phase_end", "Database init and data load completed",
                       phase="init_database",
                       duration_ms=int((time.perf_counter() - _t_db) * 1000),
                       tasks_count=len(ctx.task_result.tasks) if ctx.task_result and ctx.task_result.tasks else 0,
                       claims_count=len(ctx.claims_list),
                       staged_files_count=len(staged_files),
                       )

        # ── 阶段 6：构建证据（EvidenceBuilder）────────────────────────────
        _t_build = time.perf_counter()
        try:
            # EvidenceBuilder：合并历史缓存 + 本次结果，导出拆分 JSON
            evidence_builder = EvidenceBuilder(project_root)
            merge_result = evidence_builder.merge(tool_evidence)
            evidence_builder.apply(conn, merge_result, output_dir / "evidences")
            evidence_builder.persist(output_dir / "evidences", merge_result)

            evidence_meta = evidence_builder.build_evidence_meta(conn, ctx.config_prefix)
        except Exception as exc:
            print(f"Error building evidence: {exc}", file=sys.stderr)
            try:
                vt_logger.exception("evidence_build_failed",
                                   "Error building evidence in stage 6",
                                   exc=exc)
            except Exception:
                pass  # logger 自身异常不应影响退出码
            return 1
        vt_logger.info("phase_end", "Evidence built",
                       phase="build_evidence",
                       duration_ms=int((time.perf_counter() - _t_build) * 1000),
                       full_chain_count=len(evidence_meta.get("full_chain", [])),
                       )

        human_decisions = ctx.human_decisions or {"version": "1.0", "decisions": []}

        # ── 阶段 7：运行分析（直接查 DB）────────────────────────────────
        _t_analyzers = time.perf_counter()
        merged_gaps, final_risks, compliance_res, analysis_details = _run_db_analysis(
            conn, ctx, project_root,
            staged_files=staged_files,
            human_decisions=human_decisions,
        )
        vt_logger.info("phase_end", "Analysis completed (db.check_*)",
                       phase="run_analyzers",
                       duration_ms=int((time.perf_counter() - _t_analyzers) * 1000),
                       gaps_count=len(merged_gaps),
                       risks_count=len(final_risks),
                       has_compliance=compliance_res is not None,
                       )

        # ── 阶段 8：门禁判定 + 输出 ──────────────────────────────────────
        _t_eval = time.perf_counter()
        exit_code = _evaluate_and_output(
            ctx, merged_gaps, final_risks, compliance_res,
            output_dir, evidence_meta,
            project_root, staged_files=staged_files,
            human_decisions=human_decisions,
            conn=conn,
            analysis_details=analysis_details,
            incremental_only=incremental_only,
            show_historical_debt=show_historical_debt,
        )
        gate_decision = "blocked" if exit_code == 2 else "pass"
        vt_logger.info("phase_end", "Evaluate and output completed",
                       phase="evaluate_and_output",
                       duration_ms=int((time.perf_counter() - _t_eval) * 1000),
                       gate_decision=gate_decision,
                       )

        # ── 阶段 9：返回退出码 ──────────────────────────────────────────
        total_duration_ms = int((time.perf_counter() - _run_start_t) * 1000)
        vt_logger.info("run_end", "Analysis pipeline completed",
                       total_duration_ms=total_duration_ms,
                       gate_decision=gate_decision,
                       exit_code=exit_code,
                       )
        return exit_code

    except _GateBlocked as exc:
        return exc.exit_code
    except Exception as exc:
        print(f"Unexpected error running analyze command: {exc}", file=sys.stderr)
        try:
            vt_logger.exception("run_analyze_failed",
                               "Unexpected error in analyze pipeline",
                               exc=exc)
        except Exception:
            pass  # logger 自身异常不应影响退出码
        return 1
    finally:
        if conn is not None:
            conn.close()


# ── _db_result_to_gaps 消息模板表 ──────────────────────────────────────────
# 映射 (item_type, status) → 消息模板。模板中 {item_id} 必含，{task_id} 可选。
_GAP_MESSAGES = {
    ("requirement", "no_task_for_requirement"): "Requirement {item_id} has no task coverage.",
    ("requirement", "no_claim_for_task"):       "Requirement {item_id} tasks have no claims.",
    ("requirement", "no_tests_declared"):        "Requirement {item_id} claims declare no tests.",
    ("requirement", "test_not_run"):             "Requirement {item_id} has tests that were not run.",
    ("requirement", "test_failed"):              "Requirement {item_id} has failed tests.",
    ("ac",         "no_task_for_ac"):            "AC {item_id} has no task coverage.",
    ("ac",         "no_claim_for_task"):         "AC {item_id} (task {task_id}) has no claims.",
    ("ac",         "no_tests_declared"):         "AC {item_id} (task {task_id}) declares no tests.",
    ("ac",         "test_not_run"):              "AC {item_id} (task {task_id}) has tests that were not run.",
    ("ac",         "test_failed"):               "AC {item_id} (task {task_id}) has failed tests.",
    ("claim",      "task_missing"):              "Claim {item_id} references missing task.",
    ("claim",      "task_not_done"):             "Claim {item_id} task is not done.",
    ("claim",      "no_tests"):                  "Claim {item_id} declares no tests.",
    ("claim",      "test_missing"):              "Claim {item_id} has missing tests.",
    ("claim",      "test_failed"):               "Claim {item_id} has failed tests.",
}


def _db_result_to_gaps(
    req_coverage: list,
    ac_coverage: list,
    claim_evidence: list,
) -> list:
    """[阶段 7 辅助] 将数据库查询结果转换为 MergeGateEngine 所需的缺口格式。

    输入：
        req_coverage:   需求覆盖查询结果（由 infra/db/queries.check_requirement_coverage() 返回）
        ac_coverage:    AC 覆盖查询结果（由 infra/db/queries.check_ac_coverage() 返回）
        claim_evidence: Claim 证据查询结果（由 infra/db/queries.check_claim_evidence() 返回）
    前置条件：
        三个参数均为数据库查询的原始结果，格式为 list[dict]
    处理逻辑：
        查表法：_GAP_MESSAGES 映射 (item_type, status) → 消息模板，
        辅助函数 _gap() 负责格式化。未知状态（如 "covered"）被静默跳过。
    输出：
        返回缺口列表，每个缺口包含 item_id、item_type、reason 三个字段
    """
    gaps = []

    for row in req_coverage:
        g = _gap(row["req_id"], "requirement", row["coverage_status"])
        if g: gaps.append(g)

    for row in ac_coverage:
        g = _gap(row["ac_id"], "ac", row["coverage_status"],
                 task_id=row.get("task_id", "unknown"))
        if g: gaps.append(g)

    for row in claim_evidence:
        g = _gap(row["claim_id"], "claim", row["verification_status"])
        if g: gaps.append(g)

    return gaps


def _gap(item_id: str, item_type: str, status: str, **kwargs) -> Optional[dict]:
    """Build a gap dict from the message template lookup table.

    返回 None 表示该 status 不需要生成缺口（如 "covered" 等正常状态），
    调用方应跳过 None。
    """
    template = _GAP_MESSAGES.get((item_type, status))
    if template is None:
        return None
    return {
        "item_id": item_id,
        "item_type": item_type,
        "reason": template.format(item_id=item_id, **kwargs),
    }


def _run_db_analysis(
    conn,
    ctx: UnifiedContext,
    project_root: Path,
    staged_files: Optional[Set[str]] = None,
    human_decisions: Optional[dict] = None,
) -> tuple:
    """[阶段 7] 使用数据库查询直接执行分析。

    输入：
        conn:            内存数据库连接（由 infra/db.init_in_memory_db() 创建）
        ctx:             统一上下文（由 cli/common._load_context() 加载）
        project_root:    项目根目录
        staged_files:    暂存区文件集合（可选，由 _get_staged_files() 获取）
        human_decisions: 人类决策记录（可选，来自 ctx.human_decisions）
    前置条件：
        conn 已通过 init_in_memory_db() 创建并已通过 load_tasks/load_claims 灌入数据
    处理逻辑：
        1. 执行 6 个 db.check_* 查询：需求覆盖、AC 覆盖、Claim 证据、幽灵代码、悬空 Claim、覆盖率违规
        2. 将查询结果转换为缺口格式（调用 _db_result_to_gaps）
        3. 执行架构合规检查（如果存在 architecture_constraints.json）
        4. 生成风险建议（RiskAdvisor）
        5. 合并合规检查产生的额外缺口和风险
        6. 执行陈旧项标记（mark_staleness）
    输出：
        返回元组 (merged_gaps, final_risks, compliance_res, analysis_details)
        - merged_gaps: 全部缺口列表（含 stale 标记）
        - final_risks: 全部风险列表（含 stale 标记）
        - compliance_res: 架构合规检查结果（可能为 None）
        - analysis_details: 分析详情字典（供 MergeGateEngine 使用）
    """
    from vibe_tracing.infra.db.queries import (
        check_requirement_coverage,
        check_ac_coverage,
        check_claim_evidence,
        check_ghost_code,
        check_dangling_claims,
        check_coverage_violations,
        check_invalid_task_requirements,
        check_invalid_task_acs,
        check_invalid_task_modules,
        check_invalid_task_constraints,
        check_invalid_ac_parent,
        check_isolated_tasks,
        check_architectural_orphans,
    )
    from vibe_tracing.domain.compliance.checker import ArchitectureComplianceChecker
    from vibe_tracing.domain.risk.advisor import RiskAdvisor
    from vibe_tracing.domain.gate.staleness import mark_staleness

    # Run db.check_* queries
    req_coverage = check_requirement_coverage(conn)
    ac_coverage = check_ac_coverage(conn)
    claim_evidence = check_claim_evidence(conn)
    
    strict_link = ctx.config.get("id_rules", {}).get(
        "all_tasks_must_link_requirements_and_acceptance_criteria", False
    )
    isolated_tasks = check_isolated_tasks(conn, strict_link)
    arch_orphans = check_architectural_orphans(conn)


    # Additional queries for MergeGateEngine
    ghost_files = check_ghost_code(conn)
    dangling_claims_list = check_dangling_claims(conn)
    cov_violations = check_coverage_violations(conn)

    # Invalid task reference queries
    invalid_task_reqs = check_invalid_task_requirements(conn)
    invalid_task_acs_list = check_invalid_task_acs(conn)
    invalid_task_mods = check_invalid_task_modules(conn)
    invalid_task_consts = check_invalid_task_constraints(conn)
    invalid_ac_parents = check_invalid_ac_parent(conn)


    # Convert db results to gap format
    merged_gaps = _db_result_to_gaps(req_coverage, ac_coverage, claim_evidence)

    for task in arch_orphans:
        merged_gaps.append({
            "item_id": task["task_id"],
            "item_type": "task",
            "reason": f"Architectural orphan: Task {task['task_id']} is not linked to any module.",
        })


    # Architecture compliance check
    compliance_res = None
    if ctx.constraints is not None:
        constraints_path = resolve_path(project_root, ctx.config, "architecture_constraints")
        _constraints_hash = None
        if ctx.manifest:
            for _r in ctx.manifest.inputs_used:
                if _r.file_key == "architecture_constraints" and _r.sha256_hash:
                    _constraints_hash = _r.sha256_hash
                    break
        compliance_checker = ArchitectureComplianceChecker(
            project_root,
            constraints_path=constraints_path,
            constraints_hash=_constraints_hash,
            config_data=ctx.config,
        )
        compliance_res = compliance_checker.check(
            [],  # evidence_list no longer needed for compliance check
            constraints_data=ctx.constraints,
            human_decisions=human_decisions,
        )

    # Risk Advisor
    risk_advisor = RiskAdvisor(project_root)
    final_risks = risk_advisor.generate_risks(
        gaps=merged_gaps,
        claims_analysis=[],
        claim_risks=[],
        compliance_result=compliance_res,
    )

    if compliance_res:
        final_risks.extend(compliance_res.get("proposal_risks", []))
        seen_gaps = {(g.get("item_id"), g.get("item_type")) for g in merged_gaps}
        for gap in compliance_res.get("proposal_gaps", []):
            key = (gap.get("item_id"), gap.get("item_type"))
            if key not in seen_gaps:
                seen_gaps.add(key)
                merged_gaps.append(gap)

    # Staleness tracking
    task_list_data = None
    if ctx.task_result and ctx.task_result.tasks:
        task_list_data = [t.__dict__ for t in ctx.task_result.tasks]
    merged_gaps, final_risks = mark_staleness(
        merged_gaps, final_risks, staged_files,
        ctx.claims_list, task_list_data,
    )

    # Analysis details for MergeGateEngine
    analysis_details = {
        "ghost_files": ghost_files,
        "ac_gaps": ac_coverage,
        "dangling_claims": dangling_claims_list,
        "claim_evidence_gaps": claim_evidence,
        "cov_violations": cov_violations,
        "isolated_tasks": isolated_tasks,
        "arch_orphans": arch_orphans,
        "invalid_task_references": {

            "invalid_requirements": invalid_task_reqs,
            "invalid_acs": invalid_task_acs_list,
            "invalid_modules": invalid_task_mods,
            "invalid_constraints": invalid_task_consts,
            "invalid_ac_parents": invalid_ac_parents,
        },
    }

    return merged_gaps, final_risks, compliance_res, analysis_details


def _run_analysis_phase(
    ctx: UnifiedContext,
    merged_gaps: list,
    final_risks: list,
    evidence_meta: dict,
    project_root: Path,
    staged_files: Optional[Set[str]] = None,
):
    """[阶段 8 辅助] 过滤 stale 项并构建 staged_items（用于门禁判定的债务感知）。

    输入：
        ctx:            统一上下文
        merged_gaps:    分析器输出的全部 gaps（含 stale）
        final_risks:    分析器输出的全部 risks（含 stale）
        evidence_meta:  证据元数据
        project_root:   项目根目录
        staged_files:   暂存区文件集合
    前置条件：
        分析器已完成（_run_analyzers 已执行）
    处理逻辑：
        1. 过滤掉 stale 标记的 gaps 和 risks（仅保留在完整报告中）
        2. 根据 staged 文件确定受影响的 claims/tasks/acs/reqs
        3. 从 staged 的 CLAIM-*.json 文件中提取 directly_staged_claims
    输出：
        返回 (active_gaps, active_risks, evidence_meta, staged_items, directly_staged_items)
    """
    claims_list = ctx.claims_list

    # 过滤 stale 项：stale 项仍保留在完整报告中，但不参与门禁判定
    active_gaps = [g for g in merged_gaps if not g.get("stale")]
    active_risks = [r for r in final_risks if not r.get("stale")]

    # TODO: 过度设计待优化 —— staged_items 构建逻辑（Claim→Task 关联查询）可用 SQL JOIN 替代
    # 原因：Python 循环匹配 Claim 和 staged 文件是典型的关联查询场景，SQL 更简洁可靠。
    # 见 docs/over_engineering_backlog.md #3
    # 构建 staged_items（用于门禁的债务感知判定）
    staged_items: Optional[Set[str]] = None
    directly_staged_items: Optional[Set[str]] = None
    if staged_files:
        affected_claims, affected_reqs, affected_acs = _determine_affected_items(
            staged_files, claims_list, ctx,
        )
        staged_items = set(affected_claims)
        if ctx.task_result and ctx.task_result.tasks:
            affected_task_ids = {
                claim.related_task
                for claim in claims_list
                if claim.claim_id in affected_claims
            }
            staged_items.update(affected_task_ids)
        staged_items.update(affected_acs)
        staged_items.update(affected_reqs)

        # 从 staged 的 CLAIM-*.json 文件中提取被直接修改的 claim
        # 一任务一文件模式下，staged 的 CLAIM-*.json 文件即为被修改的 claim
        directly_staged_claims = set()
        for f in staged_files:
            if f.startswith(".vibetracing/claims/CLAIM-") and f.endswith(".json"):
                # 从文件名提取 claim_id（去掉路径前缀和 .json 后缀）
                claim_id = f.replace(".vibetracing/claims/", "").replace(".json", "")
                directly_staged_claims.add(claim_id)
        directly_staged_items = set(directly_staged_claims)

    return active_gaps, active_risks, evidence_meta, staged_items, directly_staged_items


def _run_gate_evaluation(
    project_root: Path,
    active_gaps: list,
    active_risks: list,
    compliance_res: Optional[dict],
    ctx: UnifiedContext,
    staged_items: Optional[Set[str]],
    directly_staged_items: Optional[Set[str]],
    human_decisions: Optional[dict] = None,
    ghost_files: Optional[list] = None,
    ac_gaps: Optional[list] = None,
    dangling_claims: Optional[list] = None,
    claim_evidence_gaps: Optional[list] = None,
    cov_violations: Optional[list] = None,
    analysis_details: Optional[dict] = None,
    incremental_only: bool = False,
    show_historical_debt: bool = True,
) -> dict:
    """[阶段 8 辅助] 调用 MergeGateEngine 执行门禁判定。

    输入：
        project_root:          项目根目录
        active_gaps:           活跃的 gaps（已过滤 stale）
        active_risks:          活跃的 risks（已过滤 stale）
        compliance_res:        架构合规检查结果
        ctx:                   统一上下文
        staged_items:          受暂存文件影响的 items
        directly_staged_items: 直接被 staged 的 claim
        human_decisions:       人类决策记录
        ghost_files:           幽灵代码文件列表
        ac_gaps:               AC 覆盖缺口列表
        dangling_claims:       悬空 Claim 列表
        claim_evidence_gaps:   Claim 证据缺口列表
        cov_violations:        覆盖率违规列表
        incremental_only:      是否只检查增量问题
        show_historical_debt:  是否显示历史债务详情
    输出：
        返回门禁结果字典（含 gate_decision、gaps、risks 等）
    """
    if human_decisions is None:
        human_decisions = ctx.human_decisions or {"version": "1.0", "decisions": []}
    gate_engine = MergeGateEngine(
        project_root,
        incremental_only=incremental_only,
        show_historical_debt=show_historical_debt,
    )
    gate_res = gate_engine.evaluate(
        active_gaps, active_risks,
        compliance_res=compliance_res,
        staged_items=staged_items,
        directly_staged_items=directly_staged_items,
        human_decisions=human_decisions,
        ghost_files=ghost_files,
        ac_gaps=ac_gaps,
        dangling_claims=dangling_claims,
        claim_evidence_gaps=claim_evidence_gaps,
        cov_violations=cov_violations,
        invalid_task_references=analysis_details.get("invalid_task_references") if analysis_details else None,
    )
    hd_applied = gate_res.get("human_decisions_applied", 0)
    if hd_applied > 0:
        print(f"  Applied {hd_applied} human decision(s).", file=sys.stderr)
    return gate_res


def _evaluate_and_output(
    ctx: UnifiedContext,
    merged_gaps: list,
    final_risks: list,
    compliance_res: Optional[dict],
    output_dir: Path,
    evidence_meta: dict,
    project_root: Path,
    staged_files: Optional[Set[str]] = None,
    human_decisions: Optional[dict] = None,
    conn=None,
    analysis_details: Optional[dict] = None,
    incremental_only: bool = False,
    show_historical_debt: bool = True,
) -> int:
    """[阶段 8] 执行门禁判定并生成所有输出（报告、Dashboard、终端摘要）。

    输入：
        ctx:              统一上下文
        merged_gaps:      全部 gaps（含 stale）
        final_risks:      全部 risks（含 stale）
        compliance_res:   架构合规检查结果
        output_dir:       输出目录
        evidence_meta:    证据元数据
        project_root:     项目根目录
        staged_files:     暂存区文件集合
        human_decisions:  人类决策记录
        conn:             数据库连接
        analysis_details: 分析详情（ghost_files, ac_gaps, dangling_claims 等）
        incremental_only: 是否只检查增量问题
        show_historical_debt: 是否显示历史债务详情
    输出：
        返回退出码（0=通过, 2=blocked）
    """
    if not ctx.manifest:
        return 1

    if analysis_details is None:
        analysis_details = {}

    # 阶段 1：分析（过滤 stale 项，构建 staged_items）
    active_gaps, active_risks, evidence_meta, staged_items, directly_staged_items = \
        _run_analysis_phase(ctx, merged_gaps, final_risks, evidence_meta, project_root, staged_files)

    # 阶段 2：门禁判定
    gate_res = _run_gate_evaluation(
        project_root, active_gaps, active_risks, compliance_res,
        ctx, staged_items, directly_staged_items,
        human_decisions=human_decisions,
        ghost_files=analysis_details.get("ghost_files"),
        ac_gaps=analysis_details.get("ac_gaps"),
        dangling_claims=analysis_details.get("dangling_claims"),
        claim_evidence_gaps=analysis_details.get("claim_evidence_gaps"),
        cov_violations=analysis_details.get("cov_violations"),
        analysis_details=analysis_details,
        incremental_only=incremental_only,
        show_historical_debt=show_historical_debt,
    )

    # 阶段 3：生成追溯报告
    report_doc = _build_report_document(
        ctx, gate_res, evidence_meta, merged_gaps, final_risks,
        compliance_res, output_dir, project_root,
        isolated_tasks=analysis_details.get("isolated_tasks"),
    )

    # 阶段 4：渲染输出（Dashboard + 终端摘要 + Agent 行动建议 + 反思提示）
    _render_output(
        ctx, gate_res, report_doc, evidence_meta,
        active_gaps, active_risks, merged_gaps, final_risks, compliance_res,
        staged_items, output_dir, project_root,
        staged_files=staged_files,
        conn=conn,
    )

    # 计算退出码
    exit_code = 2 if gate_res["gate_decision"] == "blocked" else 0

    return exit_code


