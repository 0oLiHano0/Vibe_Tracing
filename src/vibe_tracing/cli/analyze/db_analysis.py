"""
VT 分析流水线 — 数据库分析模块

从 pipeline.py 提取的数据库查询分析函数：
  - gap adapter（_GAP_MESSAGES / _db_result_to_gaps / _gap）
  - _check_module_code_path_mismatch（模块边界校验）
  - run_db_analysis（阶段 7 全部 DB 分析编排）

依赖：infra/db/queries（13 个 check_* 函数）、domain/compliance、domain/risk
"""

from pathlib import Path
from typing import Optional, Set

from vibe_tracing.domain.context import UnifiedContext
from vibe_tracing.infra.loader.config import resolve_path
from vibe_tracing.infra.db.queries import (
    check_requirement_coverage,
    check_ac_coverage,
    check_claim_evidence,
    check_dangling_claims,
    check_coverage_violations,
    check_lint_violations,
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


def _check_module_code_path_mismatch(conn, constraints):
    """检查 Task 声明的模块归属与 Claim 代码路径是否错位。

    从 DB 查询 (task_id, module_id, code_path) 三元组，与
    architecture_constraints.json 中 module_boundaries.owned_files 交叉验证。
    如果 code_path 属于另一个模块，记录为错位。

    Returns:
        list[dict]: 错位记录列表，每项含 task_id, module_id, code_path, actual_module。
        无约束数据时返回空列表。
    """
    if not constraints:
        return []

    # 构建 {module_id → set(owned_files)} 索引
    module_files = {}
    for mod in constraints.get("module_boundaries", []):
        mid = mod.get("module_id")
        files = mod.get("owned_files", [])
        if mid and files:
            module_files[mid] = set(files)

    if not module_files:
        return []

    # 查询所有 task→module→code_path 三元组
    rows = conn.execute("""
        SELECT tm.task_id, tm.module_id, ccr.code_path
        FROM task_modules tm
        JOIN claims c ON tm.task_id = c.related_task
        JOIN claim_code_refs ccr ON c.claim_id = ccr.claim_id
    """).fetchall()

    mismatches = []
    for task_id, module_id, code_path in rows:
        actual_module = None
        for mid, files in module_files.items():
            if code_path in files:
                actual_module = mid
                break

        if actual_module is not None and actual_module != module_id:
            mismatches.append({
                "task_id": task_id,
                "module_id": module_id,
                "code_path": code_path,
                "actual_module": actual_module,
            })

    return mismatches


def run_db_analysis(
    conn,
    ctx: UnifiedContext,
    project_root: Path,
    staged_files: Optional[Set[str]] = None,
    human_decisions: Optional[dict] = None,
    affected_claim_ids: Optional[Set[str]] = None,
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
    ghost_files: list = []  # ponytail: 阶段2已做幽灵代码前置阻断，阶段7无需再查
    dangling_claims_list = check_dangling_claims(conn)
    cov_violations = check_coverage_violations(conn)
    lint_violations = check_lint_violations(conn)

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

    # Staleness tracking
    task_list_data = None
    if ctx.task_result and ctx.task_result.tasks:
        task_list_data = [t.__dict__ for t in ctx.task_result.tasks]
    merged_gaps, final_risks = mark_staleness(
        merged_gaps, final_risks, staged_files,
        ctx.claims_list, task_list_data,
        affected_claim_ids=affected_claim_ids,
    )

    # Analysis details for MergeGateEngine
    analysis_details = {
        "ghost_files": ghost_files,
        "ac_gaps": ac_coverage,
        "dangling_claims": dangling_claims_list,
        "claim_evidence_gaps": claim_evidence,
        "cov_violations": cov_violations,
        "lint_violations": lint_violations,
        "isolated_tasks": isolated_tasks,
        "arch_orphans": arch_orphans,
        "invalid_task_references": {

            "invalid_requirements": invalid_task_reqs,
            "invalid_acs": invalid_task_acs_list,
            "invalid_modules": invalid_task_mods,
            "invalid_constraints": invalid_task_consts,
            "invalid_ac_parents": invalid_ac_parents,
            "invalid_module_code_paths": _check_module_code_path_mismatch(conn, ctx.constraints),
        },
    }

    return merged_gaps, final_risks, compliance_res, analysis_details
