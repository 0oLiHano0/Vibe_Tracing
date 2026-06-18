"""
Integration tests for Vibe Tracing v3 features.

Covers:
- _run_claim_tests: VT automatically runs pytest for claim test_refs
- _archive_claims: Claim archival mechanism
- ToolExecutionEngine.execute_all: Language-based file filtering
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from vibe_tracing.cli import _run_claim_tests, _archive_claims
from vibe_tracing.domain.tool_evidence_adapter import ToolExecutionEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakeClaim:
    """Lightweight claim stand-in for tests that only need test_refs / code_refs."""
    claim_id: str = "CL-001"
    related_task: str = "TASK-001"
    timestamp: str = ""
    code_refs: List[str] = field(default_factory=list)
    test_refs: List[str] = field(default_factory=list)
    notes: str = ""
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)


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
        """Archive non-empty CLAIM-*.json files and verify they are removed."""
        # Arrange: create claims directory structure with CLAIM-*.json files
        claims_dir = tmp_path / ".vibetracing" / "claims"
        archive_dir = claims_dir / "archive"
        claims_dir.mkdir(parents=True, exist_ok=True)

        claim = {"claim_id": "CLAIM-CL-100", "related_task": "T-1", "code_refs": ["src/a.py"]}
        (claims_dir / "CLAIM-CL-100.json").write_text(
            json.dumps(claim, indent=2), encoding="utf-8"
        )

        # Mock git rev-parse to control the archive filename
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc1234\n"

        with patch("vibe_tracing.cli.analyze.tools.subprocess.run", return_value=mock_result):
            _archive_claims(tmp_path)

        # Assert: archive file was created
        archive_files = list(archive_dir.glob("commit-abc1234.json"))
        assert len(archive_files) == 1

        archived_data = json.loads(archive_files[0].read_text(encoding="utf-8"))
        assert len(archived_data) == 1
        assert archived_data[0]["claim_id"] == "CLAIM-CL-100"

        # Assert: CLAIM-*.json files were removed
        remaining_claims = list(claims_dir.glob("CLAIM-*.json"))
        assert len(remaining_claims) == 0

    def test_archive_claims_empty(self, tmp_path: Path) -> None:
        """Empty claims directory should not produce an archive file."""
        claims_dir = tmp_path / ".vibetracing" / "claims"
        archive_dir = claims_dir / "archive"
        claims_dir.mkdir(parents=True, exist_ok=True)

        _archive_claims(tmp_path)

        # No archive file should be created
        assert not any(archive_dir.iterdir()) if archive_dir.exists() else True

    def test_archive_claims_missing_dir(self, tmp_path: Path) -> None:
        """Missing claims directory should not raise."""
        # Should return silently without error
        _archive_claims(tmp_path)

    def test_archive_claims_corrupt_json(self, tmp_path: Path) -> None:
        """Corrupt CLAIM-*.json should not raise."""
        claims_dir = tmp_path / ".vibetracing" / "claims"
        claims_dir.mkdir(parents=True, exist_ok=True)
        (claims_dir / "CLAIM-VT-001.json").write_text("NOT JSON!!!", encoding="utf-8")

        # Should not raise
        _archive_claims(tmp_path)


# ===========================================================================
# Test 5: execute_all language filtering
# ===========================================================================

class TestExecuteAllLanguageFilter:
    """Integration test for execute_all filtering by file extension."""

    @patch("vibe_tracing.domain.tool_evidence_adapter.subprocess.run")
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

    @patch("vibe_tracing.domain.tool_evidence_adapter.subprocess.run")
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
