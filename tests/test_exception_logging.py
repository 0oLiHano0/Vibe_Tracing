"""Tests for structured exception logging in silently-swallowed except blocks.

Verifies that OperationalLogger is called when exceptions are caught in:
- git_utils.py
- commands/analyze/analysis.py
- hint_loader.py
- ghost_code_reconciler.py
- tool_evidence_adapter.py
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from vibe_tracing.infra.db import init_in_memory_db

import pytest

from vibe_tracing.infra.operational_logger import OperationalLogger


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure singleton is reset before and after each test."""
    OperationalLogger.reset()
    yield
    OperationalLogger.reset()


@pytest.fixture
def mock_logger():
    """Provide a mock OperationalLogger.get() that records calls."""
    mock = MagicMock()
    with patch.object(OperationalLogger, "get", return_value=mock):
        yield mock


@pytest.fixture
def conn():
    """Create an in-memory SQLite connection for GhostCodeReconciler."""
    return init_in_memory_db()


# --------------------------------------------------------------------------
# git_utils.py
# --------------------------------------------------------------------------

class TestGitUtilsExceptionLogging:
    """git_utils functions must log exceptions before returning None/False."""

    def test_git_show_logs_on_subprocess_error(self, mock_logger, tmp_path):
        from vibe_tracing.infra.git_utils import git_show

        with patch("vibe_tracing.infra.git_utils.subprocess.run", side_effect=OSError("no git")):
            result = git_show("HEAD", "file.txt", tmp_path)

        assert result is None
        mock_logger.exception.assert_called_once()
        call_kwargs = mock_logger.exception.call_args
        assert call_kwargs[0][0] == "git_utils_error"
        assert "git_show" in call_kwargs[0][1]

    def test_git_last_commit_touching_logs_on_error(self, mock_logger, tmp_path):
        from vibe_tracing.infra.git_utils import git_last_commit_touching

        with patch("vibe_tracing.infra.git_utils.subprocess.run", side_effect=OSError("no git")):
            result = git_last_commit_touching("file.txt", tmp_path)

        assert result is None
        mock_logger.exception.assert_called_once()
        assert "git_last_commit_touching" in mock_logger.exception.call_args[0][1]

    def test_git_file_modified_after_logs_on_error(self, mock_logger, tmp_path):
        from vibe_tracing.infra.git_utils import git_file_modified_after

        with patch("vibe_tracing.infra.git_utils.subprocess.run", side_effect=OSError("no git")):
            result = git_file_modified_after("file.txt", "abc123", tmp_path)

        assert result is False
        mock_logger.exception.assert_called_once()
        assert "git_file_modified_after" in mock_logger.exception.call_args[0][1]

    def test_git_has_uncommitted_changes_logs_on_error(self, mock_logger, tmp_path):
        from vibe_tracing.infra.git_utils import git_has_uncommitted_changes

        with patch("vibe_tracing.infra.git_utils.subprocess.run", side_effect=OSError("no git")):
            result = git_has_uncommitted_changes("file.txt", tmp_path)

        assert result is False
        mock_logger.exception.assert_called_once()
        assert "git_has_uncommitted_changes" in mock_logger.exception.call_args[0][1]


# --------------------------------------------------------------------------
# commands/analyze/analysis.py
# --------------------------------------------------------------------------

class TestAnalysisExceptionLogging:
    """_load_human_decisions must log when the decisions file is corrupt."""

    def test_load_human_decisions_logs_on_corrupt_file(self, mock_logger, tmp_path):
        from vibe_tracing.cli.analyze.analysis import _load_human_decisions

        hd_dir = tmp_path / ".vibetracing"
        hd_dir.mkdir()
        (hd_dir / "human_decisions.json").write_text("NOT JSON", encoding="utf-8")

        result = _load_human_decisions(tmp_path)

        assert result == {"version": "1.0", "decisions": []}
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args[0]
        assert call_args[0] == "human_decisions_load_failed"
        assert "human_decisions.json" in mock_logger.warning.call_args[1]["path"]


# --------------------------------------------------------------------------
# hint_loader.py
# --------------------------------------------------------------------------

class TestHintLoaderExceptionLogging:
    """load_hints must log when hints file is missing or corrupt."""

    def test_load_hints_logs_on_missing_file(self, mock_logger, tmp_path):
        from vibe_tracing.infra import hint_loader

        # Clear module cache
        hint_loader._cache.clear()

        with patch.object(hint_loader, "_HINTS_PATH", tmp_path / "nonexistent.json"):
            result = hint_loader.load_hints("gate_decision")

        assert result == {}
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args[0]
        assert call_args[0] == "hints_load_failed"
        assert "gate_decision" in call_args[1]

    def test_load_hints_logs_on_corrupt_json(self, mock_logger, tmp_path):
        from vibe_tracing.infra import hint_loader

        hint_loader._cache.clear()
        bad_file = tmp_path / "field_hints.json"
        bad_file.write_text("NOT JSON", encoding="utf-8")

        with patch.object(hint_loader, "_HINTS_PATH", bad_file):
            result = hint_loader.load_hints("risk")

        assert result == {}
        mock_logger.warning.assert_called_once()
        assert "risk" in mock_logger.warning.call_args[0][1]


# --------------------------------------------------------------------------
# ghost_code_reconciler.py
# --------------------------------------------------------------------------

class TestGhostCodeReconcilerExceptionLogging:
    """GhostCodeReconciler must log filesystem read failures."""

    def test_get_staged_files_logs_on_subprocess_error(self, mock_logger, tmp_path, conn):
        from vibe_tracing.domain.ghost_code_reconciler import GhostCodeReconciler

        reconciler = GhostCodeReconciler(tmp_path, conn)
        with patch("vibe_tracing.domain.ghost_code_reconciler.subprocess.run", side_effect=FileNotFoundError("no git")):
            result = reconciler._get_staged_files()

        assert result == set()
        mock_logger.warning.assert_called()
        assert mock_logger.warning.call_args[0][0] == "git_subprocess_failed"

    def test_get_staged_tasks_logs_on_error(self, mock_logger, tmp_path, conn):
        """When task_list.json doesn't exist, _get_staged_tasks logs and returns None."""
        from vibe_tracing.domain.ghost_code_reconciler import GhostCodeReconciler

        reconciler = GhostCodeReconciler(tmp_path, conn)
        # task_list.json doesn't exist -> OSError
        result = reconciler._get_staged_tasks()
        assert result is None
        mock_logger.warning.assert_called()
        assert mock_logger.warning.call_args[0][0] == "task_list_load_failed"

    def test_prd_not_found_no_warning(self, mock_logger, tmp_path, conn):
        """When PRD doesn't exist, _check_ac_freshness returns empty list."""
        from vibe_tracing.domain.ghost_code_reconciler import GhostCodeReconciler

        reconciler = GhostCodeReconciler(tmp_path, conn)
        # No task_list.json -> returns []
        result = reconciler._check_ac_freshness()
        assert result == []

    def test_get_staged_prd_ac_ids_logs_on_error(self, mock_logger, tmp_path, conn):
        """When PRD file doesn't exist, _get_staged_prd_ac_ids logs and returns empty set."""
        from vibe_tracing.domain.ghost_code_reconciler import GhostCodeReconciler

        reconciler = GhostCodeReconciler(tmp_path, conn)
        # No PRD file -> OSError -> empty set
        result = reconciler._get_staged_prd_ac_ids()
        assert result == set()
        mock_logger.warning.assert_called()
        assert mock_logger.warning.call_args[0][0] == "prd_ac_parse_failed"


# --------------------------------------------------------------------------
# tool_evidence_adapter.py
# --------------------------------------------------------------------------

class TestToolEvidenceAdapterExceptionLogging:
    """ToolExecutionEngine must log JSON parse failures from tool outputs."""

    def test_parse_pytest_output_logs_on_json_report_failure(self, mock_logger, tmp_path):
        from vibe_tracing.domain.tool_evidence_adapter import ToolExecutionEngine

        engine = ToolExecutionEngine(
            language_tool_matrix={"python": {"test": {"default_command": "pytest {test_path} --json-report-file={output_path}", "output_format": "pytest_json"}}},
            language="python",
            validation_tools=["test"],
            project_root=tmp_path,
        )

        # Create a corrupt JSON report file
        report_file = tmp_path / "report.json"
        report_file.write_text("NOT JSON", encoding="utf-8")

        cmd = f"pytest test.py --json-report-file={report_file}"
        engine._parse_pytest_output("", "", 1, cmd, "test.py")

        debug_calls = [c[0][0] for c in mock_logger.debug.call_args_list]
        assert "tool_output_parse_failed" in debug_calls

    def test_parse_pytest_output_logs_on_stdout_parse_failure(self, mock_logger, tmp_path):
        from vibe_tracing.domain.tool_evidence_adapter import ToolExecutionEngine

        engine = ToolExecutionEngine(
            language_tool_matrix={"python": {"test": {"default_command": "pytest {test_path}", "output_format": "pytest_json"}}},
            language="python",
            validation_tools=["test"],
            project_root=tmp_path,
        )

        engine._parse_pytest_output("NOT JSON", "", 1, "pytest test.py", "test.py")

        debug_calls = [c[0][0] for c in mock_logger.debug.call_args_list]
        assert "tool_output_parse_failed" in debug_calls

    def test_parse_ruff_output_logs_on_json_failure(self, mock_logger, tmp_path):
        from vibe_tracing.domain.tool_evidence_adapter import ToolExecutionEngine

        engine = ToolExecutionEngine(
            language_tool_matrix={"python": {"lint": {"default_command": "ruff check", "output_format": "ruff_json"}}},
            language="python",
            validation_tools=["lint"],
            project_root=tmp_path,
        )

        engine._parse_ruff_output("NOT JSON", "", 1, "ruff check", "src/main.py")

        debug_calls = [c[0][0] for c in mock_logger.debug.call_args_list]
        assert "tool_output_parse_failed" in debug_calls

    def test_parse_mypy_output_logs_on_json_failure(self, mock_logger, tmp_path):
        from vibe_tracing.domain.tool_evidence_adapter import ToolExecutionEngine

        engine = ToolExecutionEngine(
            language_tool_matrix={"python": {"type_check": {"default_command": "mypy --json-report report.json", "output_format": "mypy_json"}}},
            language="python",
            validation_tools=["type_check"],
            project_root=tmp_path,
        )

        # Create a corrupt JSON report
        report_file = tmp_path / "report.json"
        report_file.write_text("NOT JSON", encoding="utf-8")

        cmd = f"mypy --json-report {report_file}"
        engine._parse_mypy_output("", "", 1, cmd, "src/main.py")

        debug_calls = [c[0][0] for c in mock_logger.debug.call_args_list]
        assert "tool_output_parse_failed" in debug_calls

    def test_parse_bandit_output_logs_on_file_failure(self, mock_logger, tmp_path):
        from vibe_tracing.domain.tool_evidence_adapter import ToolExecutionEngine

        engine = ToolExecutionEngine(
            language_tool_matrix={"python": {"security": {"default_command": "bandit -o output.json", "output_format": "bandit_json"}}},
            language="python",
            validation_tools=["security"],
            project_root=tmp_path,
        )

        # Create a corrupt JSON report
        output_file = tmp_path / "output.json"
        output_file.write_text("NOT JSON", encoding="utf-8")

        cmd = f"bandit -o {output_file}"
        engine._parse_bandit_output("", "", 1, cmd, "src/main.py")

        debug_calls = [c[0][0] for c in mock_logger.debug.call_args_list]
        assert "tool_output_parse_failed" in debug_calls

    def test_parse_bandit_output_logs_on_stdout_failure(self, mock_logger, tmp_path):
        from vibe_tracing.domain.tool_evidence_adapter import ToolExecutionEngine

        engine = ToolExecutionEngine(
            language_tool_matrix={"python": {"security": {"default_command": "bandit", "output_format": "bandit_json"}}},
            language="python",
            validation_tools=["security"],
            project_root=tmp_path,
        )

        engine._parse_bandit_output("NOT JSON", "", 1, "bandit", "src/main.py")

        debug_calls = [c[0][0] for c in mock_logger.debug.call_args_list]
        assert "tool_output_parse_failed" in debug_calls

    def test_measure_source_coverage_logs_on_baseline_failure(self, mock_logger, tmp_path):
        from vibe_tracing.domain.tool_evidence_adapter import ToolExecutionEngine

        engine = ToolExecutionEngine(
            language_tool_matrix={"python": {}},
            language="python",
            validation_tools=[],
            project_root=tmp_path,
        )

        # Create a corrupt baseline file
        baseline = tmp_path / "baseline.json"
        baseline.write_text("NOT JSON", encoding="utf-8")

        result = engine._measure_source_coverage(baseline_path=str(baseline))

        assert result == []
        debug_calls = [c[0][0] for c in mock_logger.debug.call_args_list]
        assert "tool_output_parse_failed" in debug_calls
