"""
阶段二业务逻辑：幽灵代码检测。

纯内存规则判定，无 I/O，无副作用，不做日志记录（日志由调用方 pipeline.py 负责）。

检查项：
  暂存区业务文件是否被 Claim 的 code_refs 覆盖。

数据来源：UnifiedContext（阶段一已加载的内存数据），不创建 DB，不读磁盘。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Set, Tuple

from vibe_tracing.domain.context import UnifiedContext
from vibe_tracing.infra.config.boundary import is_in_scope
from vibe_tracing.infra.loader.raw_input import STATUS_OK


@dataclass
class GhostCodeResult:
    """幽灵代码检测结果。"""

    ghost_files: Set[str] = field(default_factory=set)

    @property
    def is_pass(self) -> bool:
        return not self.ghost_files


def build_governance_whitelist(manifest, project_root: Path) -> Set[str]:
    """从 manifest 记录中构建治理文件白名单路径集合。

    白名单基于 manifest 实际加载的路径（what was loaded），
    而非 config 声明的路径（what was configured）。
    record.file_path 是绝对路径，需转换为相对路径。

    由 pipeline.py 在阶段一调用，结果存入 ctx.governance_whitelist。
    """
    whitelist = {".vibetracing/config.json"}
    for record in manifest.inputs_used:
        if record.status == STATUS_OK:
            try:
                rel = Path(record.file_path).relative_to(project_root)
                whitelist.add(str(rel))
            except (ValueError, OSError):
                pass
    return whitelist


def find_claimed_and_affected(
    claims_list: list,
    staged_files: Set[str],
) -> Tuple[Set[str], Set[str]]:
    """一次遍历 claims_list，同时产出 Stage 2 和 Stage 7 所需的数据。

    Returns:
        all_claimed:         所有被 Claim 覆盖的文件路径（code_refs + test_refs）
        affected_claim_ids:  refs 命中 staged_files 的 Claim ID 集合
    """
    all_claimed: Set[str] = set()
    affected_claim_ids: Set[str] = set()

    for claim in claims_list:
        cid = claim.claim_id
        for ref in (claim.code_refs or []) + (claim.test_refs or []):
            path = ref.split("#")[0].split("::")[0]
            if not path:
                continue
            all_claimed.add(path)
            if path in staged_files:
                affected_claim_ids.add(cid)

    return all_claimed, affected_claim_ids


def detect_ghost_code(
    ctx: UnifiedContext,
    staged_files: Set[str],
    all_claimed: Optional[Set[str]] = None,
) -> GhostCodeResult:
    """幽灵代码检测：暂存区业务文件是否被 Claim 的 code_refs/test_refs 覆盖。

    Args:
        ctx:           统一上下文（阶段一加载）
        staged_files:  暂存区文件集合
        all_claimed:   预计算的 Claim 覆盖文件集合（含 code_refs + test_refs），
                       若为 None 则内联计算。由 pipeline 层传入以消除重复遍历。

    Returns:
        GhostCodeResult，包含未被 Claim 覆盖的幽灵文件集合。
    """
    if not staged_files:
        return GhostCodeResult()

    business_files = _filter_business_files(staged_files, ctx)
    if not business_files:
        return GhostCodeResult()

    if all_claimed is None:
        all_claimed, _ = find_claimed_and_affected(ctx.claims_list, staged_files)
        # ponytail: _ 是 affected_claim_ids，幽灵代码检测不需要
    return GhostCodeResult(ghost_files=business_files - all_claimed)


def _filter_business_files(
    staged_files: Set[str],
    ctx: UnifiedContext,
) -> Set[str]:
    """白名单 + 治理边界过滤，使用阶段一预计算的 ctx 数据。"""
    whitelist_prefixes = (".git/", "output/", ".vibetracing/claims/")
    business_files = {
        f for f in staged_files
        if f not in ctx.governance_whitelist
        and not any(f.startswith(p) for p in whitelist_prefixes)
    }
    return {f for f in business_files if is_in_scope(f, ctx.governance_boundary)}


