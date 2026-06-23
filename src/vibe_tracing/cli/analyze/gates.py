"""
Integrity gate functions for the analyze pipeline.

After refactoring (TASK-VT-072):
  - Gate 1/1b/1c are DELETED (belong to finalize, not analyze)
  - Gate 2 (ghost code) is the ONLY gate in analyze, runs as前置条件
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
    reconciler = GhostCodeReconciler(project_root, conn)
    success, error_msg = reconciler.reconcile()
    if error_msg:
        print(error_msg, file=sys.stderr)
    if not success:
        return 1

    return None


def _run_integrity_gates(
    ctx: UnifiedContext,
    project_root: Path,
    is_pre_commit: bool,
    config_prefix: str,
    conn=None,
) -> Optional[int]:
    """Run integrity gates for analyze pipeline.

    After refactoring, only Gate 2 (ghost code) remains in analyze.
    Gate 1/1b/1c (hash, drift, mapping) belong to finalize.

    Returns exit code if any gate fails, or None if all pass.
    """
    # Gate 2: Code-claim alignment (pre-commit only)
    result = _gate2_code_claim_alignment(ctx, project_root, is_pre_commit, conn=conn)
    if result is not None:
        return result

    return None
