"""
阶段二业务逻辑：Claim 覆盖前置检查。

纯内存规则判定，无 I/O，无副作用，不做日志记录（日志由调用方 pipeline.py 负责）。

检查项：
1. 幽灵代码检测：暂存区业务文件是否被 Claim 的 code_refs 覆盖
2. 任务覆盖检查：Claim 引用的任务是否存在于 task_list 中
3. AC 新鲜度检查：任务引用的 AC 是否在 PRD 中定义（仅警告）

数据来源：UnifiedContext（阶段一已加载的内存数据），不创建 DB，不读磁盘。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set

from vibe_tracing.domain.context import UnifiedContext
from vibe_tracing.infra.config.boundary import load_boundary, is_in_scope
from vibe_tracing.infra.loader.config import resolve_path


@dataclass
class ClaimCoverageResult:
    """阶段二检查结果。"""

    ghost_files: Set[str] = field(default_factory=set)
    task_coverage_blocked: List[str] = field(default_factory=list)
    ac_freshness_warnings: List[str] = field(default_factory=list)

    @property
    def is_pass(self) -> bool:
        return not self.ghost_files and not self.task_coverage_blocked


def check_claim_coverage(
    ctx: UnifiedContext,
    staged_files: Set[str],
    project_root: Path,
) -> ClaimCoverageResult:
    """阶段二核心逻辑：幽灵代码检测 + 任务覆盖检查 + AC 新鲜度检查。

    Args:
        ctx:           统一上下文（阶段一加载）
        staged_files:  暂存区文件集合
        project_root:  项目根目录

    Returns:
        ClaimCoverageResult，包含幽灵文件、任务覆盖阻断项、AC 新鲜度警告。
    """
    business_files = _filter_business_files(staged_files, project_root, ctx)

    ghost_files = _detect_ghost_files(business_files, ctx) if business_files else set()
    task_blocked = _check_task_coverage(business_files, ctx) if business_files else []
    ac_warnings = _check_ac_freshness(ctx)

    return ClaimCoverageResult(
        ghost_files=ghost_files,
        task_coverage_blocked=task_blocked,
        ac_freshness_warnings=ac_warnings,
    )


def _filter_business_files(
    staged_files: Set[str],
    project_root: Path,
    ctx: UnifiedContext,
) -> Set[str]:
    """过滤白名单和治理边界，返回业务代码文件集合。"""
    whitelist = _build_whitelist(project_root, ctx.config)
    whitelist_prefixes = (".git/", "output/", ".vibetracing/claims/")

    business_files = {
        f for f in staged_files
        if f not in whitelist and not any(f.startswith(p) for p in whitelist_prefixes)
    }

    boundary = load_boundary(project_root, constraints_data=ctx.constraints)
    return {f for f in business_files if is_in_scope(f, boundary)}


def _build_whitelist(project_root: Path, config: dict) -> Set[str]:
    """从 config 构建白名单路径集合（纯路径构建，不读文件）。"""
    whitelist = {".vibetracing/config.json"}
    governance_keys = ["prd", "architecture_constraints", "task_list", "human_decisions"]
    for key in governance_keys:
        try:
            resolved = resolve_path(project_root, config, key)
            whitelist.add(str(resolved.relative_to(project_root)))
        except ValueError:
            pass
    return whitelist


def _detect_ghost_files(business_files: Set[str], ctx: UnifiedContext) -> Set[str]:
    """幽灵代码检测：暂存区业务文件 - 所有 Claim 的 code_refs。"""
    all_claimed: Set[str] = set()
    for claim in ctx.claims_list:
        for code_ref in claim.code_refs:
            clean_ref = code_ref.split("#")[0]
            if clean_ref:
                all_claimed.add(clean_ref)
    return business_files - all_claimed


def _check_task_coverage(
    business_files: Set[str],
    ctx: UnifiedContext,
) -> List[str]:
    """任务覆盖检查：Claim 引用的任务是否存在于 task_list 中。

    Returns:
        阻断消息列表（空 = 通过）。
    """
    if ctx.task_result is None:
        return []

    all_task_ids = {task.task_id for task in ctx.task_result.tasks}

    file_to_tasks: Dict[str, Set[str]] = {}
    for claim in ctx.claims_list:
        if not claim.related_task:
            continue
        for code_ref in claim.code_refs:
            clean_ref = code_ref.split("#")[0]
            if clean_ref:
                file_to_tasks.setdefault(clean_ref, set()).add(claim.related_task)

    blocked: List[str] = []
    for code_file in sorted(business_files):
        if code_file not in file_to_tasks:
            continue
        for task_id in sorted(file_to_tasks[code_file]):
            if task_id not in all_task_ids:
                blocked.append(
                    f"  - 代码文件 {code_file} 关联的 Claim 引用任务 {task_id}，"
                    f"但该任务不存在于 task_list.json 中。"
                )

    if blocked:
        return [
            "反向覆盖检查阻断："
            "以下代码文件的覆盖任务不存在于 task_list.json 中：\n"
            + "\n".join(blocked)
            + "\n请确保 task_list.json 中包含对应的 Task 定义。"
        ]
    return []


def _check_ac_freshness(ctx: UnifiedContext) -> List[str]:
    """AC 新鲜度检查：任务引用的 AC 是否在 PRD 中定义（仅警告，不阻断）。

    Returns:
        警告消息列表（空 = 无警告）。
    """
    if ctx.task_result is None:
        return []

    task_acs: Dict[str, Set[str]] = {}
    for task in ctx.task_result.tasks:
        if task.task_id and task.related_acceptance_criteria:
            task_acs[task.task_id] = set(task.related_acceptance_criteria)

    if not task_acs:
        return []

    prd_ac_ids: Set[str] = {
        ac.ac_id
        for req in ctx.prd.requirements
        for ac in req.acceptance_criteria
    }

    warnings: List[str] = []
    for task_id, ac_ids in task_acs.items():
        for ac_id in ac_ids:
            if ac_id not in prd_ac_ids:
                warnings.append(
                    f"  - 任务 {task_id} 引用 AC {ac_id}，"
                    f"但该 AC 不在 PRD 中。"
                )

    if warnings:
        return [
            "AC 新鲜度提醒："
            "以下任务引用的 AC 未在 PRD 中找到：\n"
            + "\n".join(warnings)
            + "\n如果这是有意为之"
            "（例如复用已有 AC），可忽略此警告。"
        ]
    return []
