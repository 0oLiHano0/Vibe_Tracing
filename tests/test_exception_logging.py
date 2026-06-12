"""Tests for structured exception logging in silently-swallowed except blocks.

Verifies that OperationalLogger is called when exceptions are caught in:
- git_utils.py
- evidence_index_builder.py
- commands/analyze/analysis.py
- hint_loader.py
- ghost_code_reconciler.py
- tool_evidence_adapter.py
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vibe_tracing.operational_logger import OperationalLogger


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


# --------------------------------------------------------------------------
# git_utils.py
# --------------------------------------------------------------------------

class TestGitUtilsExceptionLogging:
    """git_utils functions must log exceptions before returning None/False."""

    def test_git_show_logs_on_subprocess_error(self, mock_logger, tmp_path):
        from vibe_tracing.git_utils import git_show

        with patch("vibe_tracing.git_utils.subprocess.run", side_effect=OSError("no git")):
            result = git_show("HEAD", "file.txt", tmp_path)

        assert result is None
        mock_logger.exception.assert_called_once()
        call_kwargs = mock_logger.exception.call_args
        assert call_kwargs[0][0] == "git_utils_error"
        assert "git_show" in call_kwargs[0][1]

    def test_git_last_commit_touching_logs_on_error(self, mock_logger, tmp_path):
        from vibe_tracing.git_utils import git_last_commit_touching

        with patch("vibe_tracing.git_utils.subprocess.run", side_effect=OSError("no git")):
            result = git_last_commit_touching("file.txt", tmp_path)

        assert result is None
        mock_logger.exception.assert_called_once()
        assert "git_last_commit_touching" in mock_logger.exception.call_args[0][1]

    def test_git_file_modified_after_logs_on_error(self, mock_logger, tmp_path):
        from vibe_tracing.git_utils import git_file_modified_after

        with patch("vibe_tracing.git_utils.subprocess.run", side_effect=OSError("no git")):
            result = git_file_modified_after("file.txt", "abc123", tmp_path)

        assert result is False
        mock_logger.exception.assert_called_once()
        assert "git_file_modified_after" in mock_logger.exception.call_args[0][1]

    def test_git_has_uncommitted_changes_logs_on_error(self, mock_logger, tmp_path):
        from vibe_tracing.git_utils import git_has_uncommitted_changes

        with patch("vibe_tracing.git_utils.subprocess.run", side_effect=OSError("no git")):
            result = git_has_uncommitted_changes("file.txt", tmp_path)

        assert result is False
        mock_logger.exception.assert_called_once()
        assert "git_has_uncommitted_changes" in mock_logger.exception.call_args[0][1]


# --------------------------------------------------------------------------
# evidence_index_builder.py
# --------------------------------------------------------------------------

class TestEvidenceIndexBuilderExceptionLogging:
    """EvidenceIndexBuilder must log when loading old evidence index fails."""

    def test_build_logs_on_corrupt_evidence_index(self, mock_logger, tmp_path):
        from vibe_tracing.evidence_index_builder import EvidenceIndexBuilder

        # Create a corrupt evidence_index.json
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "evidence_index.json").write_text("NOT JSON", encoding="utf-8")

        builder = EvidenceIndexBuilder(tmp_path)
        # We need to mock ctx to avoid full pipeline; just verify the warning was called
        # by patching at a lower level
        mock_ctx = MagicMock()
        mock_ctx.prd.is_valid = True
        mock_ctx.prd.status = "draft"
        mock_ctx.prd.requirements = []
        mock_ctx.task_result = None
        mock_ctx.claims_list = []
        mock_ctx.manifest.inputs_used = []
        mock_ctx.config_prefix = "TEST"
        mock_ctx.tool_evidence = []
        mock_ctx.config = {}

        # Patch schema validator to avoid validation
        with patch.object(builder.schema_validator, "validate_file") as mock_val:
            mock_val.return_value = MagicMock(is_valid=True, message="", field_path="")
            try:
                builder.build(output_dir / "new_index.json", mock_ctx)
            except Exception:
                pass  # May fail for other reasons; we only care about the warning

        mock_logger.warning.assert_any_call(
            "evidence_index_load_failed",
            "Could not load previous evidence index for incremental build",
            path=str(output_dir / "new_index.json"),
        )


# --------------------------------------------------------------------------
# commands/analyze/analysis.py
# --------------------------------------------------------------------------

class TestAnalysisExceptionLogging:
    """_load_human_decisions must log when the decisions file is corrupt."""

    def test_load_human_decisions_logs_on_corrupt_file(self, mock_logger, tmp_path):
        from vibe_tracing.commands.analyze.analysis import _load_human_decisions

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
        from vibe_tracing import hint_loader

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
        from vibe_tracing import hint_loader

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
    """GhostCodeReconciler must log git subprocess failures."""

    def test_get_staged_files_logs_on_subprocess_error(self, mock_logger, tmp_path):
        from vibe_tracing.ghost_code_reconciler import GhostCodeReconciler

        reconciler = GhostCodeReconciler(tmp_path)
        with patch("vibe_tracing.ghost_code_reconciler.subprocess.run", side_effect=FileNotFoundError("no git")):
            result = reconciler._get_staged_files()

        assert result == set()
        mock_logger.warning.assert_called()
        assert mock_logger.warning.call_args[0][0] == "git_subprocess_failed"

    def test_get_staged_claims_logs_on_subprocess_error(self, mock_logger, tmp_path):
        from vibe_tracing.ghost_code_reconciler import GhostCodeReconciler

        # Create claims dir
        claims_dir = tmp_path / ".vibetracing" / "claims"
        claims_dir.mkdir(parents=True)
        (claims_dir / "current.json").write_text("[]", encoding="utf-8")

        reconciler = GhostCodeReconciler(tmp_path)
        with patch("vibe_tracing.ghost_code_reconciler.subprocess.run", side_effect=FileNotFoundError("no git")):
            result = reconciler._get_staged_claims()

        assert result == []
        mock_logger.warning.assert_called()

    def test_get_staged_claims_logs_on_json_error(self, mock_logger, tmp_path):
        from vibe_tracing.ghost_code_reconciler import GhostCodeReconciler

        claims_dir = tmp_path / ".vibetracing" / "claims"
        claims_dir.mkdir(parents=True)
        (claims_dir / "current.json").write_text("[]", encoding="utf-8")

        reconciler = GhostCodeReconciler(tmp_path)
        mock_result = MagicMock()
        mock_result.stdout = "NOT JSON"
        with patch("vibe_tracing.ghost_code_reconciler.subprocess.run", return_value=mock_result):
            result = reconciler._get_staged_claims()

        assert result == []
        mock_logger.exception.assert_called()
        assert mock_logger.exception.call_args[0][0] == "claims_parse_failed"

    def test_get_staged_tasks_logs_on_error(self, mock_logger, tmp_path):
        from vibe_tracing.ghost_code_reconciler import GhostCodeReconciler

        reconciler = GhostCodeReconciler(tmp_path)
        with patch("vibe_tracing.ghost_code_reconciler.subprocess.run", side_effect=FileNotFoundError("no git")):
            result = reconciler._get_staged_tasks()

        assert result is None
        mock_logger.warning.assert_called()
        assert mock_logger.warning.call_args[0][0] == "task_list_load_failed"

    def test_get_head_tasks_logs_on_error(self, mock_logger, tmp_path):
        from vibe_tracing.ghost_code_reconciler import GhostCodeReconciler

        reconciler = GhostCodeReconciler(tmp_path)
        with patch("vibe_tracing.ghost_code_reconciler.subprocess.run", side_effect=FileNotFoundError("no git")):
            result = reconciler._get_head_tasks()

        assert result is None
        mock_logger.warning.assert_called()
        assert mock_logger.warning.call_args[0][0] == "task_list_load_failed"

    def test_prd_staging_check_logs_debug(self, mock_logger, tmp_path):
        from vibe_tracing.ghost_code_reconciler import GhostCodeReconciler

        reconciler = GhostCodeReconciler(tmp_path)
        with patch("vibe_tracing.ghost_code_reconciler.subprocess.run", side_effect=subprocess.CalledProcessError(1, "git")):
            # _check_ac_freshness calls subprocess.run to check if PRD is staged
            # We need to mock _get_staged_tasks and _get_head_tasks too
            with patch.object(reconciler, "_get_staged_tasks", return_value={"tasks": [{"task_id": "T1", "related_acceptance_criteria": ["AC-VT-1-1"]}]}), \
                 patch.object(reconciler, "_get_head_tasks", return_value={"tasks": []}):
                reconciler._check_ac_freshness()

        mock_logger.debug.assert_called()
        debug_calls = [c[0][0] for c in mock_logger.debug.call_args_list]
        assert "prd_not_staged" in debug_calls

    def test_get_staged_prd_ac_ids_logs_on_error(self, mock_logger, tmp_path):
        from vibe_tracing.ghost_code_reconciler import GhostCodeReconciler

        reconciler = GhostCodeReconciler(tmp_path)
        with patch("vibe_tracing.ghost_code_reconciler.subprocess.run", side_effect=FileNotFoundError("no git")):
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
        from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine

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
        from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine

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
        from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine

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
        from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine

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
        from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine

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
        from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine

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
        from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine

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
