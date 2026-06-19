"""
Unit tests for EvidenceBuilder (refactored from EvidenceIndexBuilder).

EvidenceBuilder upserts tool results (tests, coverage) into SQLite
and exports split JSON files (test_results.json, coverage_reports.json).
"""

import json
import sqlite3
import pytest
from pathlib import Path
from vibe_tracing.domain.evidence_builder import EvidenceBuilder
from vibe_tracing.infra.db import init_in_memory_db, export_test_results, export_coverage_reports


@pytest.fixture
def conn() -> sqlite3.Connection:
    """Fixture returning a fresh in-memory SQLite connection."""
    return init_in_memory_db()


def _make_ctx(tool_evidence=None):
    """Create a minimal mock context with the given tool_evidence."""
    from unittest.mock import MagicMock
    ctx = MagicMock()
    ctx.tool_evidence = tool_evidence or []
    return ctx


class TestEvidenceBuilderInit:
    """Tests for EvidenceBuilder initialization."""

    def test_init_stores_project_root_and_conn(self, tmp_path, conn):
        builder = EvidenceBuilder(tmp_path, conn)
        assert builder.project_root == tmp_path
        assert builder.conn is conn


class TestEvidenceBuilderBuild:
    """Tests for EvidenceBuilder.build()."""

    def test_build_with_no_tool_evidence(self, tmp_path, conn):
        """build() with no tool evidence should produce empty output files."""
        evidences_dir = tmp_path / "output" / "evidences"
        builder = EvidenceBuilder(tmp_path, conn)
        ctx = _make_ctx(tool_evidence=[])

        result = builder.build(ctx)

        assert result["evidences_dir"] == str(evidences_dir)
        assert result["test_results_file"] == str(evidences_dir / "test_results.json")
        assert result["coverage_reports_file"] == str(evidences_dir / "coverage_reports.json")

        # Output files should exist but be empty arrays
        test_file = evidences_dir / "test_results.json"
        cov_file = evidences_dir / "coverage_reports.json"
        assert test_file.exists()
        assert cov_file.exists()
        assert json.loads(test_file.read_text()) == []
        assert json.loads(cov_file.read_text()) == []

    def test_build_upserts_test_results(self, tmp_path, conn):
        """build() should upsert test-type tool evidence into test_results."""
        from vibe_tracing.domain.tool_evidence_adapter import ToolEvidenceCandidate

        test_ev = ToolEvidenceCandidate(
            source_type="test",
            source_path="tests/test_example.py::test_foo",
            covers=["AC-VT-001-01"],
            status="passed",
            tool_category="test",
            command="pytest tests/test_example.py",
            exit_code=0,
        )

        builder = EvidenceBuilder(tmp_path, conn)
        ctx = _make_ctx(tool_evidence=[test_ev])
        result = builder.build(ctx)

        # Verify DB contents
        rows = export_test_results(conn)
        assert len(rows) == 1
        assert rows[0]["nodeid"] == "tests/test_example.py::test_foo"
        assert rows[0]["outcome"] == "passed"
        assert rows[0]["exit_code"] == 0
        assert rows[0]["command"] == "pytest tests/test_example.py"
        assert rows[0]["carried_over"] == 0

        # Verify exported JSON
        test_data = json.loads(Path(result["test_results_file"]).read_text())
        assert len(test_data) == 1
        assert test_data[0]["nodeid"] == "tests/test_example.py::test_foo"

    def test_build_upserts_coverage_reports(self, tmp_path, conn):
        """build() should upsert coverage-type tool evidence into coverage_reports."""
        from vibe_tracing.domain.tool_evidence_adapter import ToolEvidenceCandidate

        cov_ev = ToolEvidenceCandidate(
            source_type="tool",
            source_path="src/vibe_tracing/core/ids.py",
            covers=["REQ-VT-001"],
            status="compliant",
            tool_category="coverage",
            details={"percent_covered": 85.5, "num_statements": 100},
        )

        builder = EvidenceBuilder(tmp_path, conn)
        ctx = _make_ctx(tool_evidence=[cov_ev])
        result = builder.build(ctx)

        # Verify DB contents
        rows = export_coverage_reports(conn)
        assert len(rows) == 1
        assert rows[0]["source_path"] == "src/vibe_tracing/core/ids.py"
        assert rows[0]["percent_covered"] == 85.5
        assert rows[0]["num_statements"] == 100
        assert rows[0]["status"] == "compliant"
        assert rows[0]["carried_over"] == 0

        # Verify exported JSON
        cov_data = json.loads(Path(result["coverage_reports_file"]).read_text())
        assert len(cov_data) == 1
        assert cov_data[0]["source_path"] == "src/vibe_tracing/core/ids.py"

    def test_build_preserves_cached_data(self, tmp_path, conn):
        """build() should load initial cache and preserve carried-over records."""
        from vibe_tracing.domain.tool_evidence_adapter import ToolEvidenceCandidate

        # Set up cached evidences dir with previous test result
        evidences_dir = tmp_path / "output" / "evidences"
        evidences_dir.mkdir(parents=True, exist_ok=True)
        cached_test = [{"nodeid": "tests/test_cached.py::test_old", "outcome": "passed", "exit_code": 0}]
        (evidences_dir / "test_results.json").write_text(json.dumps(cached_test))

        # Now run build with a new test evidence
        new_test_ev = ToolEvidenceCandidate(
            source_type="test",
            source_path="tests/test_new.py::test_fresh",
            covers=[],
            status="passed",
            tool_category="test",
            exit_code=0,
        )
        builder = EvidenceBuilder(tmp_path, conn)
        ctx = _make_ctx(tool_evidence=[new_test_ev])
        builder.build(ctx)

        # Both old (cached) and new test results should be in the DB
        rows = export_test_results(conn)
        nodeids = {r["nodeid"] for r in rows}
        assert "tests/test_cached.py::test_old" in nodeids
        assert "tests/test_new.py::test_fresh" in nodeids

    def test_build_purges_stale_cache(self, tmp_path, conn):
        """build() should purge carried-over cache entries for files being re-run."""
        from vibe_tracing.domain.tool_evidence_adapter import ToolEvidenceCandidate

        evidences_dir = tmp_path / "output" / "evidences"
        evidences_dir.mkdir(parents=True, exist_ok=True)

        # Set up cache with carried-over entries
        cached_test = [{"nodeid": "tests/test_target.py::test_a", "outcome": "passed", "exit_code": 0}]
        (evidences_dir / "test_results.json").write_text(json.dumps(cached_test))

        # Load the cache first (simulating historical data)
        from vibe_tracing.infra.db import load_initial_cache
        load_initial_cache(conn, evidences_dir)

        # Verify cache was loaded as carried_over
        rows = export_test_results(conn)
        assert len(rows) == 1
        assert rows[0]["carried_over"] == 1

        # Now run build with a fresh test for the same file -- should purge the old carried_over
        new_test_ev = ToolEvidenceCandidate(
            source_type="test",
            source_path="tests/test_target.py::test_a",
            covers=[],
            status="passed",
            tool_category="test",
            exit_code=0,
        )
        builder = EvidenceBuilder(tmp_path, conn)
        ctx = _make_ctx(tool_evidence=[new_test_ev])
        builder.build(ctx)

        # The old carried_over entry should be purged, replaced by the fresh one
        rows = export_test_results(conn)
        target_rows = [r for r in rows if r["nodeid"] == "tests/test_target.py::test_a"]
        assert len(target_rows) == 1
        assert target_rows[0]["carried_over"] == 0  # fresh, not carried over

    def test_build_returns_summary_dict(self, tmp_path, conn):
        """build() should return a dict with evidences_dir and file paths."""
        builder = EvidenceBuilder(tmp_path, conn)
        ctx = _make_ctx()
        result = builder.build(ctx)

        assert isinstance(result, dict)
        assert "evidences_dir" in result
        assert "test_results_file" in result
        assert "coverage_reports_file" in result
        assert Path(result["evidences_dir"]).is_dir()

    def test_build_processes_test_and_coverage_evidence(self, tmp_path, conn):
        """build() correctly upserts test and coverage evidence into split JSON."""
        from vibe_tracing.domain.tool_evidence_adapter import ToolEvidenceCandidate

        test_ev = ToolEvidenceCandidate(
            source_type="test",
            source_path="tests/test_foo.py::test_bar",
            covers=["AC-VT-001-01"],
            status="passed",
            tool_category="test",
            exit_code=0,
        )
        cov_ev = ToolEvidenceCandidate(
            source_type="tool",
            source_path="src/vibe_tracing/module.py",
            covers=["AC-VT-001-02"],
            status="compliant",
            tool_category="coverage",
            details={"percent_covered": 85.0, "num_statements": 42},
        )

        builder = EvidenceBuilder(tmp_path, conn)
        ctx = _make_ctx(tool_evidence=[test_ev, cov_ev])
        result = builder.build(ctx)

        assert isinstance(result, dict)
        assert "test_results_file" in result
        assert "coverage_reports_file" in result

        test_data = json.loads(Path(result["test_results_file"]).read_text())
        assert len(test_data) == 1
        assert test_data[0]["nodeid"] == "tests/test_foo.py::test_bar"
        assert test_data[0]["outcome"] == "passed"

        cov_data = json.loads(Path(result["coverage_reports_file"]).read_text())
        assert len(cov_data) == 1
        assert cov_data[0]["source_path"] == "src/vibe_tracing/module.py"
        assert cov_data[0]["percent_covered"] == 85.0
