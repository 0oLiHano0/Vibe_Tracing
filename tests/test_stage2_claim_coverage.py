"""Tests for domain/gate/claim_coverage.py — Stage 2 claim coverage checks."""

from pathlib import Path

import pytest

from vibe_tracing.domain.context import UnifiedContext
from vibe_tracing.domain.gate.claim_coverage import (
    ClaimCoverageResult,
    check_claim_coverage,
)
from vibe_tracing.infra.loader.claim_loader import Claim
from vibe_tracing.infra.loader.prd_parser import (
    AcceptanceCriteria,
    PrdParseResult,
    Requirement,
)
from vibe_tracing.infra.loader.task_loader import Task, TaskListLoadResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(
    claims=None,
    task_result=None,
    prd=None,
    constraints=None,
    config=None,
):
    """Build a minimal UnifiedContext for testing."""
    if prd is None:
        prd = PrdParseResult(requirements=[])
    if config is None:
        config = {}
    return UnifiedContext(
        config=config,
        prd=prd,
        constraints=constraints,
        task_result=task_result,
        claims_list=claims or [],
    )


def _make_task(task_id, ac_ids=None):
    return Task(
        task_id=task_id,
        title=f"Task {task_id}",
        phase_id="PHASE-1",
        priority="must",
        status="done",
        owner_role="AI",
        objective="test",
        related_acceptance_criteria=ac_ids or [],
    )


def _make_prd(ac_ids):
    return PrdParseResult(
        requirements=[
            Requirement(
                req_id="REQ-1",
                title="Test req",
                priority="must",
                category="functional",
                acceptance_criteria=[
                    AcceptanceCriteria(ac_id=ac_id, title=f"AC {ac_id}", is_testing_required=True)
                    for ac_id in ac_ids
                ],
            )
        ]
    )


# ---------------------------------------------------------------------------
# ClaimCoverageResult
# ---------------------------------------------------------------------------


class TestClaimCoverageResult:
    def test_is_pass_when_empty(self):
        r = ClaimCoverageResult()
        assert r.is_pass is True

    def test_is_fail_when_ghost_files(self):
        r = ClaimCoverageResult(ghost_files={"a.py"})
        assert r.is_pass is False

    def test_is_fail_when_task_blocked(self):
        r = ClaimCoverageResult(task_coverage_blocked=["blocked"])
        assert r.is_pass is False

    def test_is_pass_when_only_ac_warnings(self):
        r = ClaimCoverageResult(ac_freshness_warnings=["warning"])
        assert r.is_pass is True


# ---------------------------------------------------------------------------
# Ghost code detection
# ---------------------------------------------------------------------------


class TestGhostCodeDetection:
    def test_no_staged_files_passes(self):
        ctx = _make_ctx(claims=[Claim(claim_id="C1", related_task="T1", code_refs=["a.py"])])
        r = check_claim_coverage(ctx, set(), Path("/fake"))
        assert r.is_pass is True
        assert r.ghost_files == set()

    def test_claims_cover_all_files(self):
        ctx = _make_ctx(claims=[Claim(claim_id="C1", related_task="T1", code_refs=["a.py", "b.py"])])
        r = check_claim_coverage(ctx, {"a.py", "b.py"}, Path("/fake"))
        assert r.is_pass is True
        assert r.ghost_files == set()

    def test_ghost_file_detected(self):
        ctx = _make_ctx(claims=[Claim(claim_id="C1", related_task="T1", code_refs=["a.py"])])
        r = check_claim_coverage(ctx, {"a.py", "b.py"}, Path("/fake"))
        assert r.is_pass is False
        assert r.ghost_files == {"b.py"}

    def test_empty_claims_all_ghost(self):
        ctx = _make_ctx(claims=[])
        r = check_claim_coverage(ctx, {"a.py"}, Path("/fake"))
        assert r.is_pass is False
        assert r.ghost_files == {"a.py"}

    def test_code_refs_with_line_anchor(self):
        """code_refs like 'src/foo.py#L42' should match 'src/foo.py'."""
        ctx = _make_ctx(claims=[Claim(claim_id="C1", related_task="T1", code_refs=["src/foo.py#L42"])])
        r = check_claim_coverage(ctx, {"src/foo.py"}, Path("/fake"))
        assert r.is_pass is True
        assert r.ghost_files == set()

    def test_code_refs_with_line_anchor_ghost(self):
        """Unmatched file should still be detected as ghost."""
        ctx = _make_ctx(claims=[Claim(claim_id="C1", related_task="T1", code_refs=["src/foo.py#L42"])])
        r = check_claim_coverage(ctx, {"src/foo.py", "src/bar.py"}, Path("/fake"))
        assert r.is_pass is False
        assert r.ghost_files == {"src/bar.py"}


# ---------------------------------------------------------------------------
# Task coverage check
# ---------------------------------------------------------------------------


class TestTaskCoverage:
    def test_task_result_none_skips(self):
        ctx = _make_ctx(
            claims=[Claim(claim_id="C1", related_task="T1", code_refs=["a.py"])],
            task_result=None,
        )
        r = check_claim_coverage(ctx, {"a.py"}, Path("/fake"))
        assert r.is_pass is True
        assert r.task_coverage_blocked == []

    def test_task_exists_passes(self):
        ctx = _make_ctx(
            claims=[Claim(claim_id="C1", related_task="T1", code_refs=["a.py"])],
            task_result=TaskListLoadResult(tasks=[_make_task("T1")]),
        )
        r = check_claim_coverage(ctx, {"a.py"}, Path("/fake"))
        assert r.is_pass is True
        assert r.task_coverage_blocked == []

    def test_task_missing_blocks(self):
        ctx = _make_ctx(
            claims=[Claim(claim_id="C1", related_task="T1", code_refs=["a.py"])],
            task_result=TaskListLoadResult(tasks=[]),
        )
        r = check_claim_coverage(ctx, {"a.py"}, Path("/fake"))
        assert r.is_pass is False
        assert len(r.task_coverage_blocked) > 0
        assert "T1" in r.task_coverage_blocked[0]


# ---------------------------------------------------------------------------
# AC freshness check
# ---------------------------------------------------------------------------


class TestACFreshness:
    def test_task_result_none_skips(self):
        ctx = _make_ctx(task_result=None)
        r = check_claim_coverage(ctx, set(), Path("/fake"))
        assert r.ac_freshness_warnings == []

    def test_ac_in_prd_no_warning(self):
        ctx = _make_ctx(
            task_result=TaskListLoadResult(tasks=[_make_task("T1", ac_ids=["AC-1"])]),
            prd=_make_prd(["AC-1"]),
        )
        r = check_claim_coverage(ctx, set(), Path("/fake"))
        assert r.ac_freshness_warnings == []

    def test_ac_not_in_prd_warns(self):
        ctx = _make_ctx(
            task_result=TaskListLoadResult(tasks=[_make_task("T1", ac_ids=["AC-1"])]),
            prd=_make_prd([]),
        )
        r = check_claim_coverage(ctx, set(), Path("/fake"))
        assert len(r.ac_freshness_warnings) > 0
        assert "AC-1" in r.ac_freshness_warnings[0]


# ---------------------------------------------------------------------------
# Boundary filtering
# ---------------------------------------------------------------------------


class TestBoundaryFiltering:
    def test_constraints_none_no_filter(self):
        ctx = _make_ctx(constraints=None)
        r = check_claim_coverage(ctx, {"a.py"}, Path("/fake"))
        # Should proceed normally (no crash)
        assert r.is_pass is False  # ghost because no claims

    def test_git_dir_filtered(self):
        ctx = _make_ctx()
        r = check_claim_coverage(ctx, {".git/config", "a.py"}, Path("/fake"))
        assert r.ghost_files == {"a.py"}

    def test_output_dir_filtered(self):
        ctx = _make_ctx()
        r = check_claim_coverage(ctx, {"output/report.html", "a.py"}, Path("/fake"))
        assert r.ghost_files == {"a.py"}

    def test_claims_dir_filtered(self):
        ctx = _make_ctx()
        r = check_claim_coverage(ctx, {".vibetracing/claims/C1.json", "a.py"}, Path("/fake"))
        assert r.ghost_files == {"a.py"}
