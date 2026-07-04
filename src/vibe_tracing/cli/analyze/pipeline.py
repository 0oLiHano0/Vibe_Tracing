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

import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Optional, Set

from vibe_tracing.domain.gate.engine import MergeGateEngine
from vibe_tracing.domain.gate.baseline import BaselineManager
from vibe_tracing.domain.gate.signal_computer import SignalComputer
from vibe_tracing.domain.gate.types import F, aggregate_gate_decision
from vibe_tracing.domain.evidence.builder import EvidenceBuilder
from vibe_tracing.domain.context import UnifiedContext

from vibe_tracing.cli.analyze.exceptions import _GateBlocked
from vibe_tracing.domain.task.session import TaskSessionManager
from vibe_tracing.domain.task.acceptance import AcceptanceSummaryBuilder
from vibe_tracing.infra.loader.config import load_config, resolve_path
from vibe_tracing.infra.loader.raw_input import RawInputLoader, STATUS_OK, STATUS_MISSING
from vibe_tracing.infra.loader.prd_parser import PrdParser
from vibe_tracing.infra.loader.task_loader import TaskLoader
from vibe_tracing.infra.loader.claim_loader import ClaimLoader

from vibe_tracing.infra.tools.executor import ToolExecutionEngine
from vibe_tracing.cli.analyze.reports import _build_report_document
from vibe_tracing.cli.analyze.output import _render_output
from vibe_tracing.cli.analyze.db_analysis import run_db_analysis


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
    task_status: Optional[str] = None,
) -> int:
    """执行完整的 VT 分析流水线。

    输入：
        project_root: 项目根目录（由 cli/main.py 传入）
        output_dir:   输出目录（可选，默认从 config.json 读取）
        task_status:  可选 task_id；提供时仅查询并打印 session 状态后返回（不触发分析）
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
        8. _evaluate_and_output：4 步编排（closed task 预检查 → gate 检测 → session 更新 → 报告 + 渲染）
    输出：
        退出码：0=通过, 1=执行错误, 2=门禁 blocked, 3=closed task 引用
    """
    # ── --task-status 短路路径（不触发分析）────────────────────────
    if task_status:
        return _print_task_status(project_root, task_status)

    conn = None
    try:
        # 获取 main() 已初始化的日志实例；若直接调用（非 main 路径），则自动初始化
        from vibe_tracing.infra.logging.logger import OperationalLogger
        from vibe_tracing.infra.db import init_in_memory_db, load_tasks, load_claims, load_prd, load_architecture_constraints
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

        from vibe_tracing.domain.gate.claim_coverage import detect_ghost_code, find_claimed_and_affected
        all_claimed, _ = find_claimed_and_affected(
            ctx.claims_list, staged_files,
        )
        result = detect_ghost_code(ctx, staged_files, all_claimed=all_claimed)
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
            exit_code = 2

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
        merged_gaps, final_risks, compliance_res, analysis_details = run_db_analysis(
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

        # ── 阶段 7.5：解析 commit message 获取 Task 承诺 ─────────────────
        task_list_data = {}
        if ctx.task_result and ctx.task_result.tasks:
            task_list_data = {t.task_id: t for t in ctx.task_result.tasks}
        current_commit_task_set = _parse_commit_tasks(project_root, task_list_data)

        # ── 阶段 8：门禁判定 + 输出 ──────────────────────────────────────
        _t_eval = time.perf_counter()
        session_mgr = TaskSessionManager(project_root)
        task_name_lookup = {tid: t.title for tid, t in task_list_data.items()}
        phase_id_lookup = {tid: t.phase_id for tid, t in task_list_data.items()}
        model = _read_config_model(project_root)
        exit_code = _evaluate_and_output(
            ctx, merged_gaps, final_risks, compliance_res,
            output_dir, evidence_meta,
            project_root, staged_files=staged_files,
            human_decisions=human_decisions,
            conn=conn,
            analysis_details=analysis_details,
            current_commit_task_set=current_commit_task_set,
            session_mgr=session_mgr,
            task_name_lookup=task_name_lookup,
            phase_id_lookup=phase_id_lookup,
            model=model,
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



def _parse_commit_tasks(project_root: Path, task_list_data: dict) -> Set[str]:
    """从 git commit message 解析 TASK-VT-XXX ID，验证存在于 task_list 中。"""
    from vibe_tracing.infra.logging.logger import OperationalLogger
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%B"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        message = result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        message = ""

    if not message:
        return set()

    raw_ids = set(re.findall(r"TASK-[A-Z]+-\d+", message))
    valid_ids: Set[str] = set()
    for tid in raw_ids:
        if tid in task_list_data:
            valid_ids.add(tid)
        else:
            OperationalLogger.get().warning(
                "commit_task_not_found",
                "TASK ID in commit message not found in task_list",
                task_id=tid,
            )
    return valid_ids


def _read_config_model(project_root: Path) -> str:
    """读取 .vibetracing/config.json 的 'model' 字段；缺失 / 损坏 / 无字段时返回 'unknown'。

    用于 TaskSessionManager 写入 TaskSession.model。人类手动维护该字段；
    VT 不校验其与实际执行模型的一致性（design_channel_separation.md 决策 10）。
    """
    config_path = Path(project_root) / ".vibetracing" / "config.json"
    try:
        text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "unknown"
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        from vibe_tracing.infra.logging.logger import OperationalLogger
        OperationalLogger.get().warning(
            "config_model_parse_failed",
            f"config.json 解析失败，model 降级为 'unknown'：{config_path}",
            path=str(config_path),
        )
        return "unknown"
    if not isinstance(data, dict):
        return "unknown"
    model = data.get("model")
    return model if isinstance(model, str) and model else "unknown"


def _print_task_status(project_root: Path, task_id: str) -> int:
    """--task-status 实现：仅查询并打印 task session 状态，不触发分析。

    输出字段：task_id / phase_id / status / iterations / closed_at / model。
    不存在时返回 1；成功返回 0。
    """
    session_mgr = TaskSessionManager(project_root)
    session = session_mgr.get_session(task_id)
    if session is None:
        print(f"task {task_id} 在 task_sessions.json 中不存在。", file=sys.stderr)
        return 1
    print(f"task_id:    {session.task_id}")
    print(f"phase_id:   {session.phase_id}")
    print(f"status:     {session.status}")
    print(f"iterations: {session.iterations}")
    print(f"first_seen: {session.first_seen}")
    print(f"closed_at:  {session.closed_at or '-'}")
    print(f"model:      {session.model}")
    return 0


def _run_analysis_phase(
    merged_gaps: list,
    final_risks: list,
) -> tuple:
    """过滤 stale 项，返回活跃 gaps 和 risks。"""
    active_gaps = [g for g in merged_gaps if not g.get("stale")]
    active_risks = [r for r in final_risks if not r.get("stale")]
    return active_gaps, active_risks


def _run_gate_evaluation(
    project_root: Path,
    active_gaps: list,
    active_risks: list,
    compliance_res: Optional[dict],
    ctx: UnifiedContext,
    current_commit_task_set: Set[str],
    human_decisions: Optional[dict] = None,
    ghost_files: Optional[list] = None,
    ac_gaps: Optional[list] = None,
    dangling_claims: Optional[list] = None,
    claim_evidence_gaps: Optional[list] = None,
    cov_violations: Optional[list] = None,
    lint_violations: Optional[list] = None,
    analysis_details: Optional[dict] = None,
    isolated_tasks: Optional[list] = None,
) -> dict:
    """四层流水线：检测 → 信号 → 状态 → 门禁聚合。"""
    if human_decisions is None:
        human_decisions = ctx.human_decisions or {"version": "1.0", "decisions": []}

    # 1. 检测
    engine = MergeGateEngine(project_root)
    issues = engine.detect_all_issues(
        ghost_files=ghost_files,
        ac_gaps=ac_gaps,
        dangling_claims=dangling_claims,
        claim_evidence_gaps=claim_evidence_gaps,
        invalid_task_references=analysis_details.get("invalid_task_references") if analysis_details else None,
        isolated_tasks=isolated_tasks,
        cov_violations=cov_violations,
        lint_violations=lint_violations,
        gaps=active_gaps,
        risks=active_risks,
        compliance_res=compliance_res,
    )

    # 2. 信号计算
    baseline = BaselineManager(project_root)
    fingerprints = []
    for issue in issues:
        from vibe_tracing.domain.gate.baseline import compute_fingerprint
        fingerprints.append(compute_fingerprint(issue.issue_type, issue.gap_targets))
    baseline.generate_snapshot(fingerprints)

    computer = SignalComputer(baseline, current_commit_task_set, human_decisions, claims_list=ctx.claims_list)
    signals = computer.compute_signals(issues)

    # 3. 状态判定
    states_and_signals = [
        (F(s.observed, s.activated, s.resolved, s.accepted, s.severity), s, issue)
        for s, issue in signals
    ]

    # 4. 门禁聚合
    gate_decision, historical_issues, per_issue_states = aggregate_gate_decision(states_and_signals)

    gate_res = {
        "gate_decision": gate_decision,
        "historical_issues": historical_issues,
        "per_issue_states": per_issue_states,
        "human_decisions_applied": computer.human_decisions_applied,
    }
    if computer.accepted_rule_ids:
        gate_res["accepted_rule_target_ids"] = list(computer.accepted_rule_ids)
    if computer.rejected_rule_ids:
        gate_res["rejected_rule_target_ids"] = list(computer.rejected_rule_ids)

    hd_applied = gate_res["human_decisions_applied"]
    if hd_applied > 0:
        print(f"  Applied {hd_applied} human decision(s).", file=sys.stderr)
    return gate_res, states_and_signals


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
    current_commit_task_set: Optional[Set[str]] = None,
    session_mgr: Optional[TaskSessionManager] = None,
    task_name_lookup: Optional[dict] = None,
    phase_id_lookup: Optional[dict] = None,
    model: str = "unknown",
) -> int:
    """[阶段 8] 4 步编排：closed task 预检查 → gate 检测 → session 更新 + 验收摘要 → 报告 + 渲染。

    新增参数（T194）：
        session_mgr: TaskSessionManager 实例；为 None 时跳过 closed task 预检查与 session 更新（保留旧行为）。
        task_name_lookup: task_id → task title 映射，供 CLOSED 时写入 acceptance_summary.delivery。
        phase_id_lookup: task_id → phase_id 映射，供首次 seen 时写入 TaskSession.phase_id。
        model: 来自 config.json 的模型字符串，缺失时 'unknown'。

    返回：
        int: 退出码（0=通过, 2=gate blocked, 3=closed task 引用）。
    """
    if not ctx.manifest:
        return 1

    if analysis_details is None:
        analysis_details = {}
    if current_commit_task_set is None:
        current_commit_task_set = set()
    if task_name_lookup is None:
        task_name_lookup = {}
    if phase_id_lookup is None:
        phase_id_lookup = {}

    # ── 步骤 1：closed task 预检查 → exit 3 短路 ─────────────────────
    if session_mgr is not None and current_commit_task_set:
        closed_refs = session_mgr.find_closed_references(current_commit_task_set)
        if closed_refs:
            refs_str = ", ".join(closed_refs)
            print(
                f"Error: commit 引用了已 CLOSED 的 task：{refs_str}。\n"
                "CLOSED task 为终态，不可复活。请为新工作创建新的 task_id。",
                file=sys.stderr,
            )
            return 3

    # ── 步骤 2：gate 检测（行为不变）─────────────────────────────────
    active_gaps, active_risks = _run_analysis_phase(merged_gaps, final_risks)

    gate_res, states_and_signals = _run_gate_evaluation(
        project_root, active_gaps, active_risks, compliance_res,
        ctx, current_commit_task_set,
        human_decisions=human_decisions,
        ghost_files=analysis_details.get("ghost_files"),
        ac_gaps=analysis_details.get("ac_gaps"),
        dangling_claims=analysis_details.get("dangling_claims"),
        claim_evidence_gaps=analysis_details.get("claim_evidence_gaps"),
        cov_violations=analysis_details.get("cov_violations"),
        lint_violations=analysis_details.get("lint_violations"),
        analysis_details=analysis_details,
        isolated_tasks=analysis_details.get("isolated_tasks"),
    )
    gate_decision = gate_res["gate_decision"]

    # ── 步骤 3：session 更新 + 验收摘要（gate=PASS 时生成）────────────
    if session_mgr is not None:
        session_mgr.update_sessions(
            current_commit_task_set,
            states_and_signals,
            gate_decision,
            task_name_lookup,
            phase_id_lookup,
            model,
        )

    acceptance_summaries: Optional[list] = None
    if (
        session_mgr is not None
        and gate_decision == "pass"
        and current_commit_task_set
    ):
        acceptance_summaries = AcceptanceSummaryBuilder.build_list(
            current_commit_task_set,
            session_mgr.sessions,
            states_and_signals,
            project_root=project_root,
        )

    # ── 步骤 4：报告 + 渲染（签名不变，T197 统一负责变更）────────────
    report_doc = _build_report_document(
        ctx, gate_res, evidence_meta, merged_gaps, final_risks,
        compliance_res, output_dir, project_root,
        isolated_tasks=analysis_details.get("isolated_tasks"),
        sessions=session_mgr.sessions if session_mgr is not None else None,
        task_list_for_governance=(
            ctx.task_result.tasks
            if ctx.task_result and ctx.task_result.tasks
            else []
        ),
    )

    _render_output(
        ctx, gate_res, report_doc, evidence_meta,
        active_gaps, active_risks, merged_gaps, final_risks, compliance_res,
        current_commit_task_set, output_dir, project_root,
        staged_files=staged_files,
        conn=conn,
        states_and_signals=states_and_signals,
        acceptance_summaries=acceptance_summaries,
    )

    exit_code = 2 if gate_decision == "blocked" else 0
    return exit_code


