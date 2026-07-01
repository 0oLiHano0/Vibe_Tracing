"""Tests for domain/gate/claim_coverage.py — Stage 2 ghost code detection."""

from pathlib import Path

import pytest

from vibe_tracing.domain.context import UnifiedContext
from vibe_tracing.domain.gate.claim_coverage import (
    GhostCodeResult,
    detect_ghost_code,
    find_claimed_and_affected,
    build_governance_whitelist,
)
from vibe_tracing.infra.loader.claim_loader import Claim
from vibe_tracing.infra.loader.prd_parser import PrdParseResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(
    claims=None,
    task_result=None,
    prd=None,
    constraints=None,
    config=None,
    governance_whitelist=None,
    governance_boundary=None,
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
        governance_whitelist=governance_whitelist or set(),
        governance_boundary=governance_boundary or {},
    )


# ---------------------------------------------------------------------------
# GhostCodeResult
# ---------------------------------------------------------------------------


class TestGhostCodeResult:
    def test_is_pass_when_empty(self):
        r = GhostCodeResult()
        assert r.is_pass is True

    def test_is_fail_when_ghost_files(self):
        r = GhostCodeResult(ghost_files={"a.py"})
        assert r.is_pass is False


# ---------------------------------------------------------------------------
# Ghost code detection
# ---------------------------------------------------------------------------


class TestGhostCodeDetection:
    def test_no_staged_files_passes(self):
        ctx = _make_ctx(claims=[Claim(claim_id="C1", related_task="T1", code_refs=["a.py"])])
        r = detect_ghost_code(ctx, set())
        assert r.is_pass is True
        assert r.ghost_files == set()

    def test_claims_cover_all_files(self):
        ctx = _make_ctx(claims=[Claim(claim_id="C1", related_task="T1", code_refs=["a.py", "b.py"])])
        r = detect_ghost_code(ctx, {"a.py", "b.py"})
        assert r.is_pass is True
        assert r.ghost_files == set()

    def test_ghost_file_detected(self):
        ctx = _make_ctx(claims=[Claim(claim_id="C1", related_task="T1", code_refs=["a.py"])])
        r = detect_ghost_code(ctx, {"a.py", "b.py"})
        assert r.is_pass is False
        assert r.ghost_files == {"b.py"}

    def test_empty_claims_all_ghost(self):
        ctx = _make_ctx(claims=[])
        r = detect_ghost_code(ctx, {"a.py"})
        assert r.is_pass is False
        assert r.ghost_files == {"a.py"}

    def test_code_refs_with_line_anchor(self):
        """code_refs like 'src/foo.py#L42' should match 'src/foo.py'."""
        ctx = _make_ctx(claims=[Claim(claim_id="C1", related_task="T1", code_refs=["src/foo.py#L42"])])
        r = detect_ghost_code(ctx, {"src/foo.py"})
        assert r.is_pass is True
        assert r.ghost_files == set()

    def test_code_refs_with_line_anchor_ghost(self):
        """Unmatched file should still be detected as ghost."""
        ctx = _make_ctx(claims=[Claim(claim_id="C1", related_task="T1", code_refs=["src/foo.py#L42"])])
        r = detect_ghost_code(ctx, {"src/foo.py", "src/bar.py"})
        assert r.is_pass is False
        assert r.ghost_files == {"src/bar.py"}

    def test_staged_test_refs_not_ghost(self):
        """仅 staged test_refs 文件不触发幽灵代码阻断。

        CLAIM-VT-042 有 code_refs=["src/foo.py"], test_refs=["tests/test_foo.py"]，
        仅 git add tests/test_foo.py → 不应报幽灵代码。
        """
        ctx = _make_ctx(claims=[
            Claim(claim_id="C1", related_task="T1",
                  code_refs=["src/foo.py"],
                  test_refs=["tests/test_foo.py"]),
        ])
        r = detect_ghost_code(ctx, {"tests/test_foo.py"})
        assert r.is_pass is True
        assert r.ghost_files == set()

    def test_unclaimed_test_file_is_ghost(self):
        """未在任何 Claim 的 refs 中声明的测试文件仍为幽灵代码。"""
        ctx = _make_ctx(claims=[
            Claim(claim_id="C1", related_task="T1",
                  code_refs=["src/foo.py"],
                  test_refs=["tests/test_foo.py"]),
        ])
        r = detect_ghost_code(ctx, {"tests/test_bar.py"})
        assert r.is_pass is False
        assert r.ghost_files == {"tests/test_bar.py"}


# ---------------------------------------------------------------------------
# Boundary filtering
# ---------------------------------------------------------------------------


class TestBoundaryFiltering:
    def test_empty_whitelist_no_crash(self):
        ctx = _make_ctx(governance_whitelist=set())
        r = detect_ghost_code(ctx, {"a.py"})
        assert r.is_pass is False  # ghost because no claims

    def test_git_dir_filtered(self):
        ctx = _make_ctx()
        r = detect_ghost_code(ctx, {".git/config", "a.py"})
        assert r.ghost_files == {"a.py"}

    def test_output_dir_filtered(self):
        ctx = _make_ctx()
        r = detect_ghost_code(ctx, {"output/report.html", "a.py"})
        assert r.ghost_files == {"a.py"}

    def test_claims_dir_filtered(self):
        ctx = _make_ctx()
        r = detect_ghost_code(ctx, {".vibetracing/claims/C1.json", "a.py"})
        assert r.ghost_files == {"a.py"}

    def test_whitelist_file_filtered(self):
        """Files in governance_whitelist are excluded from ghost detection."""
        ctx = _make_ctx(
            governance_whitelist={"docs/prd.md", ".vibetracing/config.json"},
        )
        r = detect_ghost_code(ctx, {"docs/prd.md", "a.py"})
        assert r.ghost_files == {"a.py"}


# ---------------------------------------------------------------------------
# build_governance_whitelist
# ---------------------------------------------------------------------------


class TestBuildGovernanceWhitelist:
    def test_includes_config_json(self):
        """Always includes .vibetracing/config.json."""
        from unittest.mock import MagicMock
        manifest = MagicMock()
        manifest.inputs_used = []
        wl = build_governance_whitelist(manifest, Path("/project"))
        assert ".vibetracing/config.json" in wl

    def test_includes_ok_records(self):
        """STATUS_OK records with valid paths are included."""
        from unittest.mock import MagicMock
        from vibe_tracing.infra.loader.raw_input import STATUS_OK
        record = MagicMock()
        record.status = STATUS_OK
        record.file_path = "/project/docs/prd.md"
        manifest = MagicMock()
        manifest.inputs_used = [record]
        wl = build_governance_whitelist(manifest, Path("/project"))
        assert "docs/prd.md" in wl

    def test_skips_non_ok_records(self):
        """Non-STATUS_OK records are excluded."""
        from unittest.mock import MagicMock
        record = MagicMock()
        record.status = "missing"
        record.file_path = "/project/docs/missing.json"
        manifest = MagicMock()
        manifest.inputs_used = [record]
        wl = build_governance_whitelist(manifest, Path("/project"))
        assert "docs/missing.json" not in wl

    def test_handles_path_outside_project(self):
        """Paths outside project_root are silently skipped."""
        from unittest.mock import MagicMock
        from vibe_tracing.infra.loader.raw_input import STATUS_OK
        record = MagicMock()
        record.status = STATUS_OK
        record.file_path = "/other/project/file.txt"
        manifest = MagicMock()
        manifest.inputs_used = [record]
        wl = build_governance_whitelist(manifest, Path("/project"))
        assert "file.txt" not in wl


# ---------------------------------------------------------------------------
# find_claimed_and_affected
# ---------------------------------------------------------------------------


class TestFindClaimedAndAffected:
    def test_empty_claims_empty_staged(self):
        all_claimed, affected = find_claimed_and_affected([], set())
        assert all_claimed == set()
        assert affected == set()

    def test_code_refs_collected_into_all_claimed(self):
        claims = [Claim(claim_id="C1", related_task="T1", code_refs=["src/a.py"])]
        all_claimed, affected = find_claimed_and_affected(claims, set())
        assert "src/a.py" in all_claimed
        assert affected == set()

    def test_test_refs_collected_into_all_claimed(self):
        claims = [Claim(claim_id="C1", related_task="T1",
                        code_refs=["src/a.py"], test_refs=["tests/test_a.py"])]
        all_claimed, _ = find_claimed_and_affected(claims, set())
        assert "src/a.py" in all_claimed
        assert "tests/test_a.py" in all_claimed

    def test_affected_when_code_ref_staged(self):
        claims = [Claim(claim_id="C1", related_task="T1", code_refs=["src/a.py"])]
        _, affected = find_claimed_and_affected(claims, {"src/a.py"})
        assert affected == {"C1"}

    def test_affected_when_test_ref_staged(self):
        claims = [Claim(claim_id="C1", related_task="T1",
                        code_refs=["src/a.py"], test_refs=["tests/test_a.py"])]
        _, affected = find_claimed_and_affected(claims, {"tests/test_a.py"})
        assert affected == {"C1"}

    def test_line_anchor_stripped(self):
        claims = [Claim(claim_id="C1", related_task="T1", code_refs=["src/a.py#L10"])]
        all_claimed, affected = find_claimed_and_affected(claims, {"src/a.py"})
        assert "src/a.py" in all_claimed
        assert affected == {"C1"}

    def test_multiple_claims_mixed(self):
        claims = [
            Claim(claim_id="C1", related_task="T1", code_refs=["src/a.py"]),
            Claim(claim_id="C2", related_task="T2", code_refs=["src/b.py"]),
        ]
        _, affected = find_claimed_and_affected(claims, {"src/a.py"})
        assert affected == {"C1"}

    def test_none_refs_handled(self):
        claims = [Claim(claim_id="C1", related_task="T1", code_refs=None, test_refs=None)]
        all_claimed, affected = find_claimed_and_affected(claims, {"src/a.py"})
        assert all_claimed == set()
        assert affected == set()
