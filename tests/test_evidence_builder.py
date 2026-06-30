"""
Unit tests for EvidenceBuilder (refactored).

EvidenceBuilder uses three phases:
  - merge():  Pure data processing, no DB dependency
  - apply():  Purge + upsert routing into SQLite
  - persist(): Export JSON files
"""

import json
import sqlite3
import pytest
from pathlib import Path
from vibe_tracing.domain.evidence.builder import EvidenceBuilder
from vibe_tracing.domain.evidence.merge_result import EvidenceMergeResult
from vibe_tracing.infra.db import init_in_memory_db


@pytest.fixture
def conn() -> sqlite3.Connection:
    """Fixture returning a fresh in-memory SQLite connection."""
    return init_in_memory_db()


class TestEvidenceBuilderInit:
    """Tests for EvidenceBuilder initialization."""

    def test_init_stores_project_root_only(self, tmp_path):
        builder = EvidenceBuilder(tmp_path)
        assert builder.project_root == tmp_path
        assert not hasattr(builder, "conn")


class TestEvidenceBuilderMerge:
    """Tests for EvidenceBuilder.merge() - pure data processing."""

    def test_merge_with_no_tool_evidence(self, tmp_path):
        """merge() with no tool evidence returns empty result."""
        builder = EvidenceBuilder(tmp_path)
        result = builder.merge([])

        assert isinstance(result, EvidenceMergeResult)
        assert result.test_results_to_upsert == []
        assert result.coverage_reports_to_upsert == []
        assert result.files_to_purge == []
        assert result.stats["test_count"] == 0
        assert result.stats["coverage_count"] == 0

    def test_merge_test_results(self, tmp_path):
        """merge() correctly processes test-type tool evidence."""
        from vibe_tracing.domain.evidence.candidate import ToolEvidenceCandidate

        test_ev = ToolEvidenceCandidate(
            source_type="test",
            source_path="tests/test_example.py::test_foo",
            covers=["AC-VT-001-01"],
            status="passed",
            tool_category="test",
            command="pytest tests/test_example.py",
            exit_code=0,
        )

        builder = EvidenceBuilder(tmp_path)
        result = builder.merge([test_ev])

        assert len(result.test_results_to_upsert) == 1
        assert result.test_results_to_upsert[0]["nodeid"] == "tests/test_example.py::test_foo"
        assert result.test_results_to_upsert[0]["outcome"] == "passed"
        assert result.test_results_to_upsert[0]["exit_code"] == 0
        assert "tests/test_example.py" in result.files_to_purge
        assert result.stats["test_count"] == 1

    def test_merge_coverage_reports(self, tmp_path):
        """merge() correctly processes coverage-type tool evidence."""
        from vibe_tracing.domain.evidence.candidate import ToolEvidenceCandidate

        cov_ev = ToolEvidenceCandidate(
            source_type="tool",
            source_path="src/vibe_tracing/core/ids.py",
            covers=["REQ-VT-001"],
            status="compliant",
            tool_category="coverage",
            details={"percent_covered": 85.5, "num_statements": 100},
        )

        builder = EvidenceBuilder(tmp_path)
        result = builder.merge([cov_ev])

        assert len(result.coverage_reports_to_upsert) == 1
        assert result.coverage_reports_to_upsert[0]["source_path"] == "src/vibe_tracing/core/ids.py"
        assert result.coverage_reports_to_upsert[0]["percent_covered"] == 85.5
        assert result.stats["coverage_count"] == 1

    def test_merge_skips_unknown_source_type(self, tmp_path):
        """merge() skips evidence with unknown source_type."""
        from vibe_tracing.domain.evidence.candidate import ToolEvidenceCandidate

        unknown_ev = ToolEvidenceCandidate(
            source_type="unknown_type",
            source_path="some/path",
            covers=[],
            status="passed",
        )

        builder = EvidenceBuilder(tmp_path)
        result = builder.merge([unknown_ev])

        assert len(result.skipped_evidence) == 1
        assert result.stats["skipped_count"] == 1

    def test_merge_deduplicates_purge_files(self, tmp_path):
        """merge() deduplicates files_to_purge."""
        from vibe_tracing.domain.evidence.candidate import ToolEvidenceCandidate

        ev1 = ToolEvidenceCandidate(
            source_type="test",
            source_path="tests/test_foo.py::test_a",
            covers=[],
            status="passed",
            tool_category="test",
            exit_code=0,
        )
        ev2 = ToolEvidenceCandidate(
            source_type="test",
            source_path="tests/test_foo.py::test_b",
            covers=[],
            status="passed",
            tool_category="test",
            exit_code=0,
        )

        builder = EvidenceBuilder(tmp_path)
        result = builder.merge([ev1, ev2])

        # Both tests in same file, should only purge once
        assert result.files_to_purge.count("tests/test_foo.py") == 1


class TestEvidenceBuilderApply:
    """Tests for EvidenceBuilder.apply() - DB operations."""

    def test_apply_upserts_test_results(self, tmp_path, conn):
        """apply() upserts test results into SQLite."""
        merge_result = EvidenceMergeResult(
            test_results_to_upsert=[{
                "nodeid": "tests/test_example.py::test_foo",
                "outcome": "passed",
                "exit_code": 0,
                "command": "pytest tests/test_example.py",
                "carried_over": False,
            }],
        )

        builder = EvidenceBuilder(tmp_path)
        builder.apply(conn, merge_result)

        rows = conn.execute("SELECT nodeid, outcome, carried_over FROM test_results").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "tests/test_example.py::test_foo"
        assert rows[0][1] == "passed"
        assert rows[0][2] == 0

    def test_apply_upserts_coverage_reports(self, tmp_path, conn):
        """apply() upserts coverage reports into SQLite."""
        merge_result = EvidenceMergeResult(
            coverage_reports_to_upsert=[{
                "source_path": "src/vibe_tracing/core/ids.py",
                "percent_covered": 85.5,
                "num_statements": 100,
                "status": "compliant",
                "carried_over": False,
            }],
        )

        builder = EvidenceBuilder(tmp_path)
        builder.apply(conn, merge_result)

        rows = conn.execute("SELECT source_path, percent_covered FROM coverage_reports").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "src/vibe_tracing/core/ids.py"
        assert rows[0][1] == 85.5


class TestEvidenceBuilderPersist:
    """Tests for EvidenceBuilder.persist() - JSON export."""

    def test_persist_creates_json_files(self, tmp_path):
        """persist() creates test_results.json and coverage_reports.json."""
        merge_result = EvidenceMergeResult(
            test_results_to_upsert=[{
                "nodeid": "tests/test_foo.py::test_bar",
                "outcome": "passed",
                "exit_code": 0,
                "command": "",
                "carried_over": False,
            }],
            coverage_reports_to_upsert=[{
                "source_path": "src/module.py",
                "percent_covered": 80.0,
                "num_statements": 50,
                "status": "compliant",
                "carried_over": False,
            }],
        )

        output_dir = tmp_path / "evidences"
        builder = EvidenceBuilder(tmp_path)
        result = builder.persist(output_dir, merge_result)

        assert Path(result["test_results_file"]).exists()
        assert Path(result["coverage_reports_file"]).exists()

        test_data = json.loads(Path(result["test_results_file"]).read_text())
        assert len(test_data) == 1
        assert test_data[0]["nodeid"] == "tests/test_foo.py::test_bar"

        cov_data = json.loads(Path(result["coverage_reports_file"]).read_text())
        assert len(cov_data) == 1
        assert cov_data[0]["source_path"] == "src/module.py"

    def test_persist_empty_merge_result(self, tmp_path):
        """persist() with empty merge result creates empty JSON arrays."""
        merge_result = EvidenceMergeResult()

        output_dir = tmp_path / "evidences"
        builder = EvidenceBuilder(tmp_path)
        result = builder.persist(output_dir, merge_result)

        test_data = json.loads(Path(result["test_results_file"]).read_text())
        assert test_data == []

        cov_data = json.loads(Path(result["coverage_reports_file"]).read_text())
        assert cov_data == []


class TestEvidenceBuilderFullPipeline:
    """Integration tests for merge + apply + persist pipeline."""

    def test_full_pipeline_test_and_coverage(self, tmp_path, conn):
        """Full pipeline: merge -> apply -> persist for test and coverage evidence."""
        from vibe_tracing.domain.evidence.candidate import ToolEvidenceCandidate

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

        builder = EvidenceBuilder(tmp_path)

        # Phase 1: merge
        merge_result = builder.merge([test_ev, cov_ev])
        assert merge_result.stats["test_count"] == 1
        assert merge_result.stats["coverage_count"] == 1

        # Phase 2: apply
        builder.apply(conn, merge_result)
        test_rows = conn.execute("SELECT nodeid FROM test_results").fetchall()
        cov_rows = conn.execute("SELECT source_path FROM coverage_reports").fetchall()
        assert len(test_rows) == 1
        assert len(cov_rows) == 1

        # Phase 3: persist
        output_dir = tmp_path / "evidences"
        result = builder.persist(output_dir, merge_result)
        test_data = json.loads(Path(result["test_results_file"]).read_text())
        assert len(test_data) == 1
        assert test_data[0]["nodeid"] == "tests/test_foo.py::test_bar"

    def test_full_pipeline_purges_stale_cache(self, tmp_path, conn):
        """Full pipeline: stale cache entries are purged after apply."""
        from vibe_tracing.domain.evidence.candidate import ToolEvidenceCandidate
        from vibe_tracing.infra.db import load_initial_cache

        evidences_dir = tmp_path / "output" / "evidences"
        evidences_dir.mkdir(parents=True, exist_ok=True)

        # Set up cache with carried-over entry
        cached_test = [{"nodeid": "tests/test_target.py::test_old", "outcome": "passed", "exit_code": 0}]
        (evidences_dir / "test_results.json").write_text(json.dumps(cached_test))
        load_initial_cache(conn, evidences_dir)

        rows = conn.execute("SELECT carried_over FROM test_results").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 1

        # Run full pipeline with new test
        new_test_ev = ToolEvidenceCandidate(
            source_type="test",
            source_path="tests/test_target.py::test_new",
            covers=[],
            status="passed",
            tool_category="test",
            exit_code=0,
        )

        builder = EvidenceBuilder(tmp_path)
        merge_result = builder.merge([new_test_ev])
        builder.apply(conn, merge_result)

        # Old carried_over entry should be purged
        rows = conn.execute("SELECT nodeid FROM test_results").fetchall()
        nodeids = {r[0] for r in rows}
        assert "tests/test_target.py::test_old" not in nodeids
        assert "tests/test_target.py::test_new" in nodeids
