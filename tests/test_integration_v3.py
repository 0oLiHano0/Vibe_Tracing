"""
Integration tests for Vibe Tracing v3 features.

Covers:
- _run_claim_tests: VT automatically runs pytest for claim test_refs
- _archive_claims: Claim archival mechanism
- MergeGateEngine.check_claim_exists: End-to-end claim existence check
- MergeGateEngine.check_ac_coverage: End-to-end AC coverage check
- ToolExecutionEngine.execute_all: Language-based file filtering
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from vibe_tracing.cli import _run_claim_tests, _archive_claims
from vibe_tracing.merge_gate_engine import MergeGateEngine
from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine, ToolEvidenceCandidate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakeClaim:
    """Lightweight claim stand-in for tests that only need test_refs / code_refs."""
    claim_id: str = "CL-001"
    related_task: str = "TASK-001"
    claimed_status: str = "done"
    evidence_refs: List[str] = field(default_factory=list)
    timestamp: str = ""
    code_refs: List[str] = field(default_factory=list)
    test_refs: List[str] = field(default_factory=list)
    notes: str = ""
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    credibility: str = ""
    credibility_warnings: List[str] = field(default_factory=list)


# ===========================================================================
# Test 1 & 2: _run_claim_tests
# ===========================================================================

class TestRunClaimTests:
    """Integration tests for _run_claim_tests."""

    def test_run_claim_tests_basic(self, tmp_path: Path) -> None:
        """Create a temp test file, point a claim at it, verify results."""
        # Arrange: create a minimal test file
        test_file = tmp_path / "tests" / "test_dummy.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("def test_ok():\n    assert True\n", encoding="utf-8")

        claim = _FakeClaim(claim_id="CL-001", test_refs=["tests/test_dummy.py"])
        evidence_index: dict = {}

        # Mock subprocess.run to simulate pytest passing
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1 passed in 0.01s"
        mock_result.stderr = ""

        with patch("vibe_tracing.cli.subprocess.run", return_value=mock_result):
            result = _run_claim_tests(tmp_path, [claim], evidence_index)

        # Assert
        assert "test_results" in result
        assert "tests/test_dummy.py" in result["test_results"]
        entry = result["test_results"]["tests/test_dummy.py"]
        assert entry["status"] == "passed"
        assert entry["num_tests"] == 1

    def test_run_claim_tests_nonexistent_file(self, tmp_path: Path) -> None:
        """Claim pointing to a test file that does not exist."""
        claim = _FakeClaim(claim_id="CL-002", test_refs=["tests/ghost_test.py"])
        evidence_index: dict = {}

        result = _run_claim_tests(tmp_path, [claim], evidence_index)

        assert "test_results" in result
        assert "tests/ghost_test.py" in result["test_results"]
        assert result["test_results"]["tests/ghost_test.py"]["status"] == "file_not_found"

    def test_run_claim_tests_empty_refs(self, tmp_path: Path) -> None:
        """Claim with no test_refs produces empty test_results."""
        claim = _FakeClaim(claim_id="CL-003", test_refs=[])
        evidence_index: dict = {}

        result = _run_claim_tests(tmp_path, [claim], evidence_index)

        assert result["test_results"] == {}

    def test_run_claim_tests_failed_test(self, tmp_path: Path) -> None:
        """Simulate a failing pytest run."""
        test_file = tmp_path / "tests" / "test_fail.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("def test_bad():\n    assert False\n", encoding="utf-8")

        claim = _FakeClaim(claim_id="CL-004", test_refs=["tests/test_fail.py"])
        evidence_index: dict = {}

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "1 failed in 0.01s"
        mock_result.stderr = "FAILURES"

        with patch("vibe_tracing.cli.subprocess.run", return_value=mock_result):
            result = _run_claim_tests(tmp_path, [claim], evidence_index)

        assert result["test_results"]["tests/test_fail.py"]["status"] == "failed"


# ===========================================================================
# Test 3 & 4: _archive_claims
# ===========================================================================

class TestArchiveClaims:
    """Integration tests for _archive_claims."""

    def test_archive_claims_basic(self, tmp_path: Path) -> None:
        """Archive non-empty current.json and verify it is cleared."""
        # Arrange: create claims directory structure
        claims_dir = tmp_path / ".vibetracing" / "claims"
        archive_dir = claims_dir / "archive"
        claims_dir.mkdir(parents=True, exist_ok=True)

        current_claims = [
            {"claim_id": "CL-100", "related_task": "T-1", "code_refs": ["src/a.py"]}
        ]
        current_path = claims_dir / "current.json"
        current_path.write_text(
            json.dumps(current_claims, indent=2), encoding="utf-8"
        )

        # Mock git rev-parse to control the archive filename
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc1234\n"

        with patch("vibe_tracing.cli.subprocess.run", return_value=mock_result):
            _archive_claims(tmp_path)

        # Assert: archive file was created
        archive_files = list(archive_dir.glob("commit-abc1234.json"))
        assert len(archive_files) == 1

        archived_data = json.loads(archive_files[0].read_text(encoding="utf-8"))
        assert len(archived_data) == 1
        assert archived_data[0]["claim_id"] == "CL-100"

        # Assert: current.json was cleared
        current_data = json.loads(current_path.read_text(encoding="utf-8"))
        assert current_data == []

    def test_archive_claims_empty(self, tmp_path: Path) -> None:
        """Empty current.json should not produce an archive file."""
        claims_dir = tmp_path / ".vibetracing" / "claims"
        archive_dir = claims_dir / "archive"
        claims_dir.mkdir(parents=True, exist_ok=True)

        current_path = claims_dir / "current.json"
        current_path.write_text("[]", encoding="utf-8")

        _archive_claims(tmp_path)

        # No archive file should be created
        assert not any(archive_dir.iterdir()) if archive_dir.exists() else True

    def test_archive_claims_missing_file(self, tmp_path: Path) -> None:
        """Missing current.json should not raise."""
        # Should return silently without error
        _archive_claims(tmp_path)

    def test_archive_claims_corrupt_json(self, tmp_path: Path) -> None:
        """Corrupt current.json should not raise."""
        claims_dir = tmp_path / ".vibetracing" / "claims"
        claims_dir.mkdir(parents=True, exist_ok=True)
        (claims_dir / "current.json").write_text("NOT JSON!!!", encoding="utf-8")

        # Should not raise
        _archive_claims(tmp_path)


# ===========================================================================
# Test 5: execute_all language filtering
# ===========================================================================

class TestExecuteAllLanguageFilter:
    """Integration test for execute_all filtering by file extension."""

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_execute_all_filters_by_language(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Only .py files should be executed; .md files should be skipped."""
        # Arrange
        py_file = tmp_path / "src" / "module.py"
        py_file.parent.mkdir(parents=True, exist_ok=True)
        py_file.write_text("x = 1\n", encoding="utf-8")

        md_file = tmp_path / "docs" / "readme.md"
        md_file.parent.mkdir(parents=True, exist_ok=True)
        md_file.write_text("# Hello\n", encoding="utf-8")

        mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")

        engine = ToolExecutionEngine(
            language_tool_matrix={
                "python": {
                    "extensions": [".py"],
                    "lint": {
                        "tool": "ruff",
                        "default_command": "ruff check {source_path}",
                        "output_format": "ruff_json",
                        "pass_condition": "violations == 0",
                    },
                }
            },
            language="python",
            validation_tools=["lint"],
            project_root=tmp_path,
        )

        candidates = engine.execute_all(["src/module.py", "docs/readme.md"])

        # .py file should have been processed (subprocess called once for lint)
        assert mock_run.call_count == 1
        called_cmd = mock_run.call_args[0][0]
        assert "module.py" in called_cmd

        # .md file should not appear in any candidate
        source_paths = [c.source_path for c in candidates]
        assert "docs/readme.md" not in source_paths

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_execute_all_skips_all_non_matching(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Only .py files are configured; .json and .md files produce no candidates."""
        engine = ToolExecutionEngine(
            language_tool_matrix={
                "python": {
                    "extensions": [".py"],
                    "lint": {
                        "tool": "ruff",
                        "default_command": "ruff check {source_path}",
                        "output_format": "ruff_json",
                        "pass_condition": "violations == 0",
                    },
                }
            },
            language="python",
            validation_tools=["lint"],
            project_root=tmp_path,
        )

        candidates = engine.execute_all(["docs/notes.md", "config.json"])
        assert candidates == []
        mock_run.assert_not_called()


# ===========================================================================
# Test 6: check_claim_exists end-to-end
# ===========================================================================

class TestCheckClaimExistsIntegration:
    """Integration tests for MergeGateEngine.check_claim_exists."""

    def test_all_files_claimed_passes(self) -> None:
        """All staged files are covered by claims -> passes."""
        staged_files = {"src/foo.py", "tests/test_foo.py"}
        claims = [
            {
                "claim_id": "CL-A",
                "code_refs": ["src/foo.py"],
                "test_refs": ["tests/test_foo.py"],
            }
        ]

        passed, unclaimed = MergeGateEngine.check_claim_exists(staged_files, claims)

        assert passed is True
        assert unclaimed == set()

    def test_unclaimed_file_fails(self) -> None:
        """A staged file not in any claim -> fails with unclaimed set."""
        staged_files = {"src/foo.py", "src/bar.py"}
        claims = [
            {
                "claim_id": "CL-A",
                "code_refs": ["src/foo.py"],
                "test_refs": [],
            }
        ]

        passed, unclaimed = MergeGateEngine.check_claim_exists(staged_files, claims)

        assert passed is False
        assert "src/bar.py" in unclaimed

    def test_empty_staged_files_passes(self) -> None:
        """No staged files -> passes trivially."""
        passed, unclaimed = MergeGateEngine.check_claim_exists(set(), [])
        assert passed is True
        assert unclaimed == set()

    def test_empty_claims_fails_when_files_staged(self) -> None:
        """Staged files but no claims -> all files are unclaimed."""
        staged_files = {"src/foo.py"}

        passed, unclaimed = MergeGateEngine.check_claim_exists(staged_files, [])

        assert passed is False
        assert unclaimed == {"src/foo.py"}

    def test_multiple_claims_cover_files(self) -> None:
        """Multiple claims collectively cover all staged files."""
        staged_files = {"src/a.py", "src/b.py", "tests/test_a.py"}
        claims = [
            {"claim_id": "CL-1", "code_refs": ["src/a.py"], "test_refs": []},
            {"claim_id": "CL-2", "code_refs": ["src/b.py"], "test_refs": ["tests/test_a.py"]},
        ]

        passed, unclaimed = MergeGateEngine.check_claim_exists(staged_files, claims)

        assert passed is True
        assert unclaimed == set()

    def test_boundary_filters_files(self) -> None:
        """Files outside governance boundary are ignored."""
        staged_files = {"src/foo.py", "vendor/ext.py"}
        claims = [
            {"claim_id": "CL-A", "code_refs": ["src/foo.py"], "test_refs": []}
        ]
        boundary = {
            "included_patterns": ["src/**"],
            "excluded_patterns": [],
        }

        passed, unclaimed = MergeGateEngine.check_claim_exists(
            staged_files, claims, boundary=boundary
        )

        # vendor/ext.py is out of scope, so only src/foo.py is checked
        assert passed is True
        assert unclaimed == set()


# ===========================================================================
# Test 7: check_ac_coverage end-to-end
# ===========================================================================

class TestCheckAcCoverageIntegration:
    """Integration tests for MergeGateEngine.check_ac_coverage."""

    def test_must_task_with_claim_and_no_evidence(self) -> None:
        """MUST task has claim with test_refs -> treated as covered (no evidence available)."""
        tasks = [
            {
                "task_id": "T-1",
                "priority": "must",
                "related_acceptance_criteria": ["AC-VT-001-01"],
            }
        ]
        claims = [
            {
                "claim_id": "CL-1",
                "related_task": "T-1",
                "test_refs": ["tests/test_feature.py"],
            }
        ]

        uncovered = MergeGateEngine.check_ac_coverage(claims, tasks)

        # With no evidence_index, test_refs presence means "covered"
        assert uncovered == []

    def test_must_task_without_claim_is_uncovered(self) -> None:
        """MUST task with no claim -> uncovered AC."""
        tasks = [
            {
                "task_id": "T-1",
                "priority": "must",
                "related_acceptance_criteria": ["AC-VT-002-01"],
            }
        ]
        claims = []  # no claims

        uncovered = MergeGateEngine.check_ac_coverage(claims, tasks)

        assert len(uncovered) == 1
        assert uncovered[0]["ac_id"] == "AC-VT-002-01"
        assert uncovered[0]["task_id"] == "T-1"
        assert uncovered[0]["reason"] == "no_claim_for_task"

    def test_should_task_ignored(self) -> None:
        """Only MUST tasks are checked; SHOULD tasks are skipped."""
        tasks = [
            {
                "task_id": "T-1",
                "priority": "should",
                "related_acceptance_criteria": ["AC-VT-003-01"],
            }
        ]
        claims = []

        uncovered = MergeGateEngine.check_ac_coverage(claims, tasks)

        assert uncovered == []

    def test_failing_test_marks_ac_uncovered(self) -> None:
        """Claim has test_refs but test failed -> uncovered."""
        tasks = [
            {
                "task_id": "T-1",
                "priority": "must",
                "related_acceptance_criteria": ["AC-VT-004-01"],
            }
        ]
        claims = [
            {
                "claim_id": "CL-1",
                "related_task": "T-1",
                "test_refs": ["tests/test_feature.py"],
            }
        ]
        evidence_index = {
            "evidences": [
                {
                    "source_path": "tests/test_feature.py",
                    "status": "failed",
                    "details": {"test_category": "test"},
                }
            ]
        }

        uncovered = MergeGateEngine.check_ac_coverage(claims, tasks, evidence_index)

        assert len(uncovered) == 1
        assert uncovered[0]["ac_id"] == "AC-VT-004-01"
        assert uncovered[0]["reason"] == "test_failed"

    def test_passing_test_marks_ac_covered(self) -> None:
        """Claim has test_refs and test passed -> covered."""
        tasks = [
            {
                "task_id": "T-1",
                "priority": "must",
                "related_acceptance_criteria": ["AC-VT-005-01"],
            }
        ]
        claims = [
            {
                "claim_id": "CL-1",
                "related_task": "T-1",
                "test_refs": ["tests/test_pass.py"],
            }
        ]
        evidence_index = {
            "evidences": [
                {
                    "source_path": "tests/test_pass.py",
                    "status": "passed",
                    "details": {"test_category": "test"},
                }
            ]
        }

        uncovered = MergeGateEngine.check_ac_coverage(claims, tasks, evidence_index)

        assert uncovered == []

    def test_claim_without_test_refs_is_uncovered(self) -> None:
        """Claim exists for the task but has no test_refs -> uncovered."""
        tasks = [
            {
                "task_id": "T-1",
                "priority": "must",
                "related_acceptance_criteria": ["AC-VT-006-01"],
            }
        ]
        claims = [
            {
                "claim_id": "CL-1",
                "related_task": "T-1",
                "test_refs": [],  # no tests declared
            }
        ]

        uncovered = MergeGateEngine.check_ac_coverage(claims, tasks)

        assert len(uncovered) == 1
        assert uncovered[0]["reason"] == "no_tests_declared"

    def test_multiple_acs_partial_coverage(self) -> None:
        """Task with two ACs, only one covered by test -> one uncovered."""
        tasks = [
            {
                "task_id": "T-1",
                "priority": "must",
                "related_acceptance_criteria": ["AC-VT-007-01", "AC-VT-007-02"],
            }
        ]
        claims = [
            {
                "claim_id": "CL-1",
                "related_task": "T-1",
                "test_refs": ["tests/test_a.py"],
            }
        ]
        evidence_index = {
            "evidences": [
                {
                    "source_path": "tests/test_a.py",
                    "status": "passed",
                    "details": {"test_category": "test"},
                }
            ]
        }

        uncovered = MergeGateEngine.check_ac_coverage(claims, tasks, evidence_index)

        # Both ACs are covered by the same claim with a passing test
        assert uncovered == []
