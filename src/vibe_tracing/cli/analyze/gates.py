"""
Integrity gate functions for the analyze pipeline.

Gate 2 (ghost code) is the ONLY gate in analyze, runs as 前置条件。
公共入口：_check_claim_coverage（与 refactoring_design.md §3 阶段 2 对齐）
"""

import sys
from pathlib import Path
from typing import Optional

from vibe_tracing.domain.context import UnifiedContext


def _gate2_code_claim_alignment(
    ctx: UnifiedContext,
    project_root: Path,
    is_pre_commit: bool,
    conn=None,
) -> Optional[int]:
    """Gate 2: Code-Claim Alignment (pre-commit only).

    Runs ghost code detection, task coverage check, and AC freshness check
    via GhostCodeReconciler.  Only executes when *is_pre_commit* is True.

    Returns:
        None if the gate passes or is skipped (not pre-commit).
        1 (exit code) if the gate fails.
    """
    if not is_pre_commit:
        return None

    from vibe_tracing.infra.db import init_in_memory_db
    from vibe_tracing.domain.governance.ghost_code import GhostCodeReconciler

    if conn is None:
        conn = init_in_memory_db()
    reconciler = GhostCodeReconciler(project_root, conn, config_data=ctx.config)
    success, error_msg = reconciler.reconcile()
    if error_msg:
        print(error_msg, file=sys.stderr)
    if not success:
        return 1

    return None


def _check_claim_coverage(
    ctx: UnifiedContext,
    project_root: Path,
    is_pre_commit: bool,
    config_prefix: str,
    conn=None,
) -> Optional[int]:
    """Claim 覆盖前置检查（阶段 2 入口，与设计文档 §3 对齐）。

    重构后 analyze 阶段仅保留 Gate 2（幽灵代码检查）。
    Gate 1/1b/1c（哈希、PRD 漂移、架构映射）属于 finalize，已删除。

    Args:
        ctx:           统一上下文
        project_root:  项目根目录
        is_pre_commit: 是否为 pre-commit 模式
        config_prefix: 配置前缀
        conn:          可选 DB 连接（供测试注入；None 时内部自建）

    Returns:
        None  — 门禁通过
        int   — 门禁失败，返回退出码
    """
    # Gate 2: Code-Claim 对齐（仅 pre-commit 模式执行）
    result = _gate2_code_claim_alignment(ctx, project_root, is_pre_commit, conn=conn)
    if result is not None:
        return result

    return None
