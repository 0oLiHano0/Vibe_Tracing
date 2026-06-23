"""
VT 分析流水线编排模块

为什么需要这个模块：
  vt analyze 是 VT 的核心命令，需要按严格顺序串联多个模块完成分析。
  本模块是唯一的编排入口，决定"什么时候调用谁"。

核心设计：
  流水线分 9 个阶段，每个阶段有明确的输入→输出：
  1. 加载输入 → 2. 门禁检查 → 3. 创建数据库
  → 4. 执行工具 → 5. 灌入数据 → 6. 构建证据 → 7. 运行分析器
  → 8. 门禁判定 + 输出 → 9. 返回退出码

依赖关系：
  被 cli/main.py 通过 _dispatch() 调用。
  调用以下模块：common（上下文加载）、gates（门禁）、tools（工具执行）、
  analysis（分析器）、reports（报告）、output（渲染）、
  domain/evidence_builder（证据构建）、domain/merge_gate_engine（门禁判定）、
  infra/db（数据库）
"""

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Optional, Set

from vibe_tracing.domain.gate.engine import MergeGateEngine
from vibe_tracing.domain.evidence.builder import EvidenceBuilder
from vibe_tracing.domain.context import UnifiedContext

from vibe_tracing.cli.common import (
    _GateBlocked,
    _load_context,
    _get_staged_files,
    _determine_affected_items,
)
from vibe_tracing.cli.analyze.gates import _run_integrity_gates
from vibe_tracing.cli.analyze.tools import _execute_tools
from vibe_tracing.cli.analyze.reports import _build_report_document
from vibe_tracing.cli.analyze.output import _render_output


def _db_result_to_gaps(
    req_coverage: list,
    ac_coverage: list,
    claim_evidence: list,
) -> list:
    """Convert db.check_* results to gap format for MergeGateEngine.

    Args:
        req_coverage: Result from db.check_requirement_coverage()
        ac_coverage: Result from db.check_ac_coverage()
        claim_evidence: Result from db.check_claim_evidence()

    Returns:
        List of gap dicts with item_id, item_type, reason.
    """
    gaps = []

    # Requirement coverage gaps
    for row in req_coverage:
        req_id = row["req_id"]
        status = row["coverage_status"]
        if status == "no_task_for_requirement":
            gaps.append({
                "item_id": req_id,
                "item_type": "requirement",
                "reason": f"Requirement {req_id} has no task coverage.",
            })
        elif status == "no_claim_for_task":
            gaps.append({
                "item_id": req_id,
                "item_type": "requirement",
                "reason": f"Requirement {req_id} tasks have no claims.",
            })
        elif status == "no_tests_declared":
            gaps.append({
                "item_id": req_id,
                "item_type": "requirement",
                "reason": f"Requirement {req_id} claims declare no tests.",
            })
        elif status == "test_not_run":
            gaps.append({
                "item_id": req_id,
                "item_type": "requirement",
                "reason": f"Requirement {req_id} has tests that were not run.",
            })
        elif status == "test_failed":
            gaps.append({
                "item_id": req_id,
                "item_type": "requirement",
                "reason": f"Requirement {req_id} has failed tests.",
            })

    # AC coverage gaps
    for row in ac_coverage:
        ac_id = row["ac_id"]
        task_id = row.get("task_id", "unknown")
        status = row["coverage_status"]
        if status == "no_task_for_ac":
            gaps.append({
                "item_id": ac_id,
                "item_type": "ac",
                "reason": f"AC {ac_id} has no task coverage.",
            })
        elif status == "no_claim_for_task":
            gaps.append({
                "item_id": ac_id,
                "item_type": "ac",
                "reason": f"AC {ac_id} (task {task_id}) has no claims.",
            })
        elif status == "no_tests_declared":
            gaps.append({
                "item_id": ac_id,
                "item_type": "ac",
                "reason": f"AC {ac_id} (task {task_id}) declares no tests.",
            })
        elif status == "test_not_run":
            gaps.append({
                "item_id": ac_id,
                "item_type": "ac",
                "reason": f"AC {ac_id} (task {task_id}) has tests that were not run.",
            })
        elif status == "test_failed":
            gaps.append({
                "item_id": ac_id,
                "item_type": "ac",
                "reason": f"AC {ac_id} (task {task_id}) has failed tests.",
            })

    # Claim evidence gaps
    for row in claim_evidence:
        claim_id = row["claim_id"]
        status = row["verification_status"]
        if status == "task_missing":
            gaps.append({
                "item_id": claim_id,
                "item_type": "claim",
                "reason": f"Claim {claim_id} references missing task.",
            })
        elif status == "task_not_done":
            gaps.append({
                "item_id": claim_id,
                "item_type": "claim",
                "reason": f"Claim {claim_id} task is not done.",
            })
        elif status == "no_tests":
            gaps.append({
                "item_id": claim_id,
                "item_type": "claim",
                "reason": f"Claim {claim_id} declares no tests.",
            })
        elif status == "test_missing":
            gaps.append({
                "item_id": claim_id,
                "item_type": "claim",
                "reason": f"Claim {claim_id} has missing tests.",
            })
        elif status == "test_failed":
            gaps.append({
                "item_id": claim_id,
                "item_type": "claim",
                "reason": f"Claim {claim_id} has failed tests.",
            })

    return gaps


def _run_db_analysis(
    conn,
    ctx: UnifiedContext,
    project_root: Path,
    staged_files: Optional[Set[str]] = None,
    human_decisions: Optional[dict] = None,
) -> tuple:
    """Run analysis using db.check_* functions directly.

    Replaces the old _run_analyzers that used Python-based analyzers.
    Returns (merged_gaps, final_risks, compliance_res, analysis_details).
    """
    from vibe_tracing.infra.db.queries import (
        check_requirement_coverage,
        check_ac_coverage,
        check_claim_evidence,
        check_ghost_code,
        check_dangling_claims,
        check_coverage_violations,
    )
    from vibe_tracing.domain.compliance.checker import ArchitectureComplianceChecker
    from vibe_tracing.domain.risk.advisor import RiskAdvisor
    from vibe_tracing.domain.gate.staleness import mark_staleness

    # Run db.check_* queries
    req_coverage = check_requirement_coverage(conn)
    ac_coverage = check_ac_coverage(conn)
    claim_evidence = check_claim_evidence(conn)

    # Additional queries for MergeGateEngine
    ghost_files = check_ghost_code(conn)
    dangling_claims_list = check_dangling_claims(conn)
    cov_violations = check_coverage_violations(conn)

    # Convert db results to gap format
    merged_gaps = _db_result_to_gaps(req_coverage, ac_coverage, claim_evidence)

    # Architecture compliance check
    compliance_res = None
    constraints_path = project_root / "docs" / "architecture_constraints.json"
    if constraints_path.exists() and ctx.constraints is not None:
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
    """过滤 stale 项并构建 staged_items（用于门禁判定的债务感知）。

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
    conn=None,
    human_decisions: Optional[dict] = None,
    ghost_files: Optional[list] = None,
    ac_gaps: Optional[list] = None,
    dangling_claims: Optional[list] = None,
    claim_evidence_gaps: Optional[list] = None,
    cov_violations: Optional[list] = None,
) -> dict:
    """调用 MergeGateEngine 执行门禁判定。

    输入：
        project_root:          项目根目录
        active_gaps:           活跃的 gaps（已过滤 stale）
        active_risks:          活跃的 risks（已过滤 stale）
        compliance_res:        架构合规检查结果
        ctx:                   统一上下文
        staged_items:          受暂存文件影响的 items
        directly_staged_items: 直接被 staged 的 claim
        conn:                  数据库连接（保留用于兼容，不再传递给 MergeGateEngine）
        human_decisions:       人类决策记录
        ghost_files:           幽灵代码文件列表
        ac_gaps:               AC 覆盖缺口列表
        dangling_claims:       悬空 Claim 列表
        claim_evidence_gaps:   Claim 证据缺口列表
        cov_violations:        覆盖率违规列表
    输出：
        返回门禁结果字典（含 gate_decision、gaps、risks 等）
    """
    if human_decisions is None:
        human_decisions = ctx.human_decisions or {"version": "1.0", "decisions": []}
    gate_engine = MergeGateEngine(project_root)
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
    claim_res: dict,
    req_res: dict,
    project_root: Path,
    is_draft: bool,
    staged_files: Optional[Set[str]] = None,
    is_pre_commit: bool = False,
    human_decisions: Optional[dict] = None,
    conn=None,
    analysis_details: Optional[dict] = None,
) -> int:
    """执行门禁判定并生成所有输出（报告、Dashboard、终端摘要）。

    输入：
        ctx:              统一上下文
        merged_gaps:      全部 gaps（含 stale）
        final_risks:      全部 risks（含 stale）
        compliance_res:   架构合规检查结果
        output_dir:       输出目录
        evidence_meta:    证据元数据
        claim_res:        Claim 分析结果
        req_res:          需求分析结果
        project_root:     项目根目录
        is_draft:         是否草稿模式
        staged_files:     暂存区文件集合
        is_pre_commit:    是否预提交模式
        human_decisions:  人类决策记录
        conn:             数据库连接
        analysis_details: 分析详情（ghost_files, ac_gaps, dangling_claims 等）
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
        ctx, staged_items, directly_staged_items, conn,
        human_decisions=human_decisions,
        ghost_files=analysis_details.get("ghost_files"),
        ac_gaps=analysis_details.get("ac_gaps"),
        dangling_claims=analysis_details.get("dangling_claims"),
        claim_evidence_gaps=analysis_details.get("claim_evidence_gaps"),
        cov_violations=analysis_details.get("cov_violations"),
    )

    # 阶段 3：生成追溯报告
    report_doc = _build_report_document(
        ctx, gate_res, evidence_meta, merged_gaps, final_risks,
        compliance_res, req_res, output_dir, project_root,
    )

    # 阶段 4：渲染输出（Dashboard + 终端摘要 + Agent 行动建议 + 反思提示）
    _render_output(
        ctx, gate_res, report_doc, evidence_meta,
        active_gaps, active_risks, merged_gaps, final_risks, compliance_res,
        staged_items, output_dir, project_root, is_draft,
        is_pre_commit=is_pre_commit, staged_files=staged_files,
    )

    # 计算退出码
    exit_code = 2 if gate_res["gate_decision"] == "blocked" else 0

    return exit_code


def run_analyze(project_root: Path, output_dir: Optional[Path] = None, is_pre_commit: bool = False, gates_only: bool = False) -> int:
    """执行完整的 VT 分析流水线。

    输入：
        project_root: 项目根目录（由 cli/main.py 传入）
        output_dir:   输出目录（可选，默认从 config.json 读取）
        is_pre_commit: 是否为 Git pre-commit hook 模式
        gates_only:   是否仅运行门禁（快速模式，跳过工具执行和分析）
    前置条件：
        项目已完成 vt finalize（config.json 存在且有效）
    处理逻辑（9 个阶段）：
        1. _load_context：加载 PRD、Tasks、Claims、Config
        2. _run_integrity_gates：门禁 1/2/2.5（哈希、幽灵代码、AC 新鲜度）
        3. init_in_memory_db：创建内存数据库
        4. _execute_tools：执行 pytest/ruff/bandit/coverage
        5. load_tasks + load_claims：将数据灌入数据库
        6. EvidenceBuilder.build：合并新旧证据，导出拆分 JSON
        7. _run_analyzers：运行 3 个分析器（REQ→Task、AC→Test、Claim→Evidence）
        8. _evaluate_and_output：门禁判定 + 报告生成 + Dashboard 渲染
        9. return exit_code
    输出：
        退出码：0=通过, 1=执行错误, 2=门禁 blocked
    """
    conn = None
    try:
        # 获取 main() 已初始化的日志实例；若直接调用（非 main 路径），则自动初始化
        from vibe_tracing.infra.logging.logger import OperationalLogger
        from vibe_tracing.infra.db import init_in_memory_db, load_tasks, load_claims
        _run_start_t = time.perf_counter()

        # ── 阶段 1：加载输入 ──────────────────────────────────────────────
        _t_ctx = time.perf_counter()
        ctx, raw_loader = _load_context(project_root)
        prd_res = ctx.prd
        is_draft = (prd_res.status == "draft")
        config_prefix = ctx.config_prefix

        log_level = ctx.config.get("logging", {}).get("level", "DEBUG")
        try:
            vt_logger = OperationalLogger.get_or_init(
                run_id=f"ANALYZE-{uuid.uuid4()}", project_root=project_root,
                level=log_level,
            )
        except Exception:
            vt_logger = OperationalLogger.get()
        vt_logger.info("run_start", "Analysis pipeline started",
                       is_pre_commit=is_pre_commit, gates_only=gates_only)
        vt_logger.info("phase_end", "Load context completed",
                       phase="load_context",
                       duration_ms=int((time.perf_counter() - _t_ctx) * 1000),
                       config_prefix=config_prefix,
                       has_prd=prd_res is not None,
                       claims_count=len(ctx.claims_list),
                       )

        # 解析输出目录（未指定时从 config 读取）
        if output_dir is None:
            _out_rel = ctx.config.get("paths", {}).get("output_dir", "output")
            output_dir = (project_root / _out_rel).resolve()

        # ── 阶段 2：门禁检查（Gate 1/2/2.5）─────────────────────────────
        _t_gates = time.perf_counter()
        exit_code = _run_integrity_gates(
            ctx, project_root, is_pre_commit, config_prefix,
        )
        vt_logger.info("phase_end", "Integrity gates completed",
                       phase="integrity_gates",
                       duration_ms=int((time.perf_counter() - _t_gates) * 1000),
                       gate_result="pass" if exit_code is None else "blocked",
                       exit_code=exit_code if exit_code is not None else 0,
                       )
        if exit_code is not None:
            return exit_code

        # gates_only 模式：门禁通过后直接返回，跳过后续阶段
        if gates_only:
            print("Gates-only mode: integrity gates passed. Skipping analysis.")
            return 0

        # ── 阶段 4：创建内存数据库 ────────────────────────────────────────
        conn = init_in_memory_db()

        # ── 阶段 5：执行验证工具 ──────────────────────────────────────────
        _t_tools = time.perf_counter()
        tool_evidence = _execute_tools(ctx, project_root, is_draft)
        # tool_evidence is a pipeline-local variable, NOT stored in ctx
        vt_logger.info("phase_end", "Tool execution completed",
                       phase="execute_tools",
                       duration_ms=int((time.perf_counter() - _t_tools) * 1000),
                       tools_executed=len(tool_evidence),
                       )

        # ── 阶段 6：将数据灌入数据库 ──────────────────────────────────────
        if ctx.task_result and ctx.task_result.tasks:
            load_tasks(conn, [t.__dict__ for t in ctx.task_result.tasks])
        if ctx.claims_list:
            load_claims(conn, [c.__dict__ for c in ctx.claims_list])

        # ── 阶段 7：构建证据（EvidenceBuilder）────────────────────────────
        _t_build = time.perf_counter()

        # TODO: 过度设计待优化 —— evidence_dicts 构建逻辑（~100 行）应迁移到 domain 层
        # 原因：状态映射、数据翻译、顺序编号均为业务逻辑，不属于调度层。
        # 优化方向：分析器直接查询数据库，消除 evidence_dicts 中间层。
        # 见 docs/over_engineering_backlog.md #1-5
        # 构建 evidence_dicts（供分析器和报告使用的证据元数据）
        try:
            evidence_dicts = []

            # Task 证据条目
            from vibe_tracing.infra.config.enums import CoverageStatus
            task_covers_map = {}
            if ctx.task_result and ctx.task_result.tasks:
                for task in ctx.task_result.tasks:
                    covers = sorted(list(set(
                        task.related_requirements + task.related_acceptance_criteria
                    )))
                    task_covers_map[task.task_id] = covers
                    status_map = {
                        "todo": CoverageStatus.MISSING.value,
                        "in_progress": CoverageStatus.PARTIAL.value,
                        "blocked": CoverageStatus.BLOCKED.value,
                        "done": CoverageStatus.COVERED.value,
                    }
                    status = status_map.get(task.status, CoverageStatus.UNCLEAR.value)
                    evidence_dicts.append({
                        "source_type": "task",
                        "source_path": "docs/task_list.json",
                        "covers": covers,
                        "status": status,
                        "details": {
                            "task_id": task.task_id,
                            "title": task.title,
                            "phase_id": task.phase_id,
                            "priority": task.priority,
                        },
                    })

            # Claim 证据条目
            for claim in (ctx.claims_list or []):
                covers = task_covers_map.get(claim.related_task, [])
                evidence_dicts.append({
                    "source_type": "claim",
                    "source_path": ".vibetracing/claims/",
                    "covers": covers,
                    "status": CoverageStatus.UNCLEAR.value,
                    "details": {
                        "claim_id": claim.claim_id,
                        "related_task": claim.related_task,
                        "timestamp": claim.timestamp,
                        "notes": getattr(claim, "notes", ""),
                    },
                })

            # Code 证据条目（从 Claim 的 code_refs 提取）
            for claim in (ctx.claims_list or []):
                covers = task_covers_map.get(claim.related_task, [])
                for code_ref in (claim.code_refs or []):
                    evidence_dicts.append({
                        "source_type": "code",
                        "source_path": code_ref,
                        "covers": covers,
                        "status": CoverageStatus.COMPLIANT.value,
                        "details": {
                            "claim_id": claim.claim_id,
                            "related_task": claim.related_task,
                        },
                    })

            # 工具执行证据条目
            for tc in (tool_evidence or []):
                d = {
                    "source_type": tc.source_type,
                    "source_path": tc.source_path,
                    "covers": tc.covers,
                    "status": tc.status,
                    "details": dict(tc.details) if tc.details else {},
                }
                if tc.tool_category:
                    d["details"]["tool_category"] = tc.tool_category
                if tc.command:
                    d["details"]["command"] = tc.command
                if tc.exit_code != 0 or tc.command:
                    d["details"]["exit_code"] = tc.exit_code
                if tc.stderr:
                    d["details"]["stderr"] = tc.stderr
                if tc.error_code:
                    d["error_code"] = tc.error_code
                evidence_dicts.append(d)

            # TODO: 过度设计待优化 —— 顺序编号无意义，应用 source_path/nodeid 替代
            # 原因：增删测试会导致编号漂移，产生 Git 冲突。source_path 是天然唯一标识。
            # 见 docs/over_engineering_backlog.md #5
            # 分配顺序证据 ID
            for idx, ev in enumerate(evidence_dicts):
                ev["evidence_id"] = f"EVIDENCE-VT-{idx + 1:03d}"

            # EvidenceBuilder：合并历史缓存 + 本次结果，导出拆分 JSON
            evidence_builder = EvidenceBuilder(project_root)
            merge_result = evidence_builder.merge(tool_evidence)
            evidence_builder.apply(conn, merge_result)
            evidence_builder.persist(output_dir / "evidences", merge_result)

            # 证据元数据（供分析器和报告使用）
            evidence_meta = {
                "run_id": f"RUN-{uuid.uuid4()}",
                "project_id": f"PROJECT-{config_prefix}",
                "scan_time": "",
                "evidences": evidence_dicts,
            }
        except Exception as exc:
            print(f"Error building evidence: {exc}", file=sys.stderr)
            return 1
        vt_logger.info("phase_end", "Evidence built",
                       phase="build_evidence",
                       duration_ms=int((time.perf_counter() - _t_build) * 1000),
                       evidences_count=len(evidence_meta.get("evidences", [])),
                       )

        evidence_list = evidence_meta.get("evidences", [])

        staged_files = _get_staged_files(project_root)

        human_decisions = ctx.human_decisions or {"version": "1.0", "decisions": []}

        # ── 阶段 8：运行分析（直接查 DB）────────────────────────────────
        _t_analyzers = time.perf_counter()
        merged_gaps, final_risks, compliance_res, analysis_details = _run_db_analysis(
            conn, ctx, project_root,
            staged_files=staged_files,
            human_decisions=human_decisions,
        )
        claim_res = {}  # Legacy format, kept for report compatibility
        req_res = {}    # Legacy format, kept for report compatibility
        vt_logger.info("phase_end", "Analysis completed (db.check_*)",
                       phase="run_analyzers",
                       duration_ms=int((time.perf_counter() - _t_analyzers) * 1000),
                       gaps_count=len(merged_gaps),
                       risks_count=len(final_risks),
                       has_compliance=compliance_res is not None,
                       )

        # ── 阶段 9：门禁判定 + 输出 ──────────────────────────────────────
        _t_eval = time.perf_counter()
        exit_code = _evaluate_and_output(
            ctx, merged_gaps, final_risks, compliance_res,
            output_dir, evidence_meta, claim_res, req_res,
            project_root, is_draft, staged_files=staged_files,
            is_pre_commit=is_pre_commit,
            human_decisions=human_decisions,
            conn=conn,
            analysis_details=analysis_details,
        )
        gate_decision = "blocked" if exit_code == 2 else "pass"
        vt_logger.info("phase_end", "Evaluate and output completed",
                       phase="evaluate_and_output",
                       duration_ms=int((time.perf_counter() - _t_eval) * 1000),
                       gate_decision=gate_decision,
                       )

        # ── 阶段 10：返回退出码 ──────────────────────────────────────────
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
        return 1
    finally:
        if conn is not None:
            conn.close()
