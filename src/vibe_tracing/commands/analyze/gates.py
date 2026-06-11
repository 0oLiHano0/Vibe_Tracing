"""
Integrity gate functions for the analyze pipeline.
"""

import sys
from pathlib import Path
from typing import Optional

from vibe_tracing.context import UnifiedContext


def _gate1_constraints_hash(ctx: UnifiedContext, project_root: Path) -> Optional[int]:
    """Gate 1: Anti-Tampering (Architecture Baseline Check).

    Verifies that the architecture constraints file has not been modified
    since the baseline was finalized.  Compares the SHA-256 hash of the
    current file against the stored hash in the project config.

    Returns:
        None if the gate passes (hash matches or no baseline stored).
        1 (exit code) if the hash has been tampered with.
    """
    if not ctx.manifest:
        return None
    records_dict = {r.file_key: r for r in ctx.manifest.inputs_used}
    constraints_record = records_dict.get("architecture_constraints")
    if not (constraints_record and constraints_record.status == "ok"):
        return None

    # Use hash computed during loading instead of re-reading from disk
    computed_hash = constraints_record.sha256_hash
    if not computed_hash:
        return None
    stored_hash = ctx.config.get("architecture_constraints_hash")
    if stored_hash and stored_hash != computed_hash:
        print(
            "FATAL: 架构基线已被篡改！\n"
            f"预期 Hash: {stored_hash[:12]}...\n"
            f"实际 Hash: {computed_hash[:12]}...\n"
            "请恢复文件，或通过 `vt finalize` 提交合法的架构变更。",
            file=sys.stderr,
        )
        return 1

    return None


def _gate1b_prd_drift(ctx: UnifiedContext) -> None:
    """Gate 1b: PRD drift detection (WARNING only, never blocks).

    Compares the current PRD file hash against the baseline stored in config.
    If they differ, prints a warning to stderr but does not block the pipeline.
    """
    if not ctx.manifest:
        return

    # Resolve PRD record from manifest
    prd_record = None
    for r in ctx.manifest.inputs_used:
        if r.file_key == "prd":
            prd_record = r
            break

    if prd_record is None or prd_record.status != "ok":
        return

    # Use hash computed during loading instead of re-reading from disk
    computed_p_hash = prd_record.sha256_hash
    if not computed_p_hash:
        return
    stored_p_hash = ctx.config.get("prd_hash")
    if stored_p_hash and stored_p_hash != computed_p_hash:
        print(
            "WARNING: PRD 已从基线漂移！\n"
            f"预期 Hash: {stored_p_hash[:12]}...\n"
            f"实际 Hash: {computed_p_hash[:12]}...\n"
            "将重新验证 PRD ↔ Architecture 映射关系。",
            file=sys.stderr
        )


def _gate1c_mapping(ctx: UnifiedContext, config_prefix: str) -> Optional[int]:
    """Gate 1c: PRD <-> Architecture mapping validation.

    Returns 1 if dead links or MUST-uncovered requirements are found (blocks).
    Returns None if validation passes (including SHOULD-level warnings).
    """
    constraints_record_content = ctx.constraints
    prd_res = ctx.prd

    if not constraints_record_content or not prd_res or not prd_res.is_valid:
        return None

    from vibe_tracing.prd_arch_validator import validate_prd_architecture_mapping
    mapping_result = validate_prd_architecture_mapping(
        prd_res.requirements,
        constraints_record_content,
        config_prefix,
    )
    if mapping_result.has_dead_links:
        for link in mapping_result.dead_links:
            print(
                f"BLOCKED: 架构约束引用的 {link} 不存在于 PRD。\n"
                "请更新 architecture_constraints.json 或 PRD 以修复死链。",
                file=sys.stderr
            )
        return 1
    if mapping_result.has_must_uncovered:
        for req_id in mapping_result.must_uncovered:
            print(
                f"BLOCKED: MUST 级需求 {req_id} 无架构支撑。\n"
                "请在 architecture_constraints.json 中为该需求规划架构模块。",
                file=sys.stderr
            )
        return 1
    for req_id in mapping_result.should_uncovered:
        print(
            f"WARNING: SHOULD/COULD 级需求 {req_id} 缺失架构映射。",
            file=sys.stderr
        )
    return None


def _gate2_code_claim_alignment(
    ctx: UnifiedContext,
    project_root: Path,
    is_pre_commit: bool,
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

    from vibe_tracing.ghost_code_reconciler import GhostCodeReconciler
    reconciler = GhostCodeReconciler(project_root)
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
) -> Optional[int]:
    """Run integrity gates 1, 1b, 1c, 2, and 3.

    Returns exit code if any gate fails, or None if all pass.
    """
    # Gate 1: Anti-tampering
    result = _gate1_constraints_hash(ctx, project_root)
    if result is not None:
        return result

    # Gate 1b: PRD drift (warning only)
    _gate1b_prd_drift(ctx)

    # Gate 1c: PRD-Architecture mapping
    result = _gate1c_mapping(ctx, config_prefix)
    if result is not None:
        return result

    # Gate 2: Code-claim alignment (pre-commit only)
    result = _gate2_code_claim_alignment(ctx, project_root, is_pre_commit)
    if result is not None:
        return result

    return None
