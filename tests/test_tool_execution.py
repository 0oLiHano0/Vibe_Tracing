"""
Unit tests for the Tool Execution Engine (MOD-VT-012).

Covers:
- Whitelist enforcement: tools not in language_tool_matrix are rejected.
- Command template substitution: placeholders correctly replaced.
- Timeout handling: timeout produces proper error evidence.
- Missing tool: proper error when tool binary not found.
- Path validation: paths outside project root are rejected.
- Output parsing: each output format handled correctly.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vibe_tracing.core.enums import CoverageStatus, ErrorCode
from vibe_tracing.tool_evidence_adapter import ToolEvidenceCandidate, ToolExecutionEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a minimal project root for testing."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / ".vibetracing").mkdir()
    return tmp_path


@pytest.fixture
def python_matrix() -> dict:
    """A realistic language_tool_matrix for Python."""
    return {
        "python": {
            "test": {
                "tool": "pytest",
                "default_command": "pytest {test_path} --tb=short -q --json-report --json-report-file={output_path}",
                "output_format": "pytest_json",
                "pass_condition": "exit_code == 0",
            },
            "lint": {
                "tool": "ruff",
                "default_command": "ruff check {source_path} --output-format=json",
                "output_format": "ruff_json",
                "pass_condition": "violations == 0",
            },
            "type_check": {
                "tool": "mypy",
                "default_command": "mypy {source_path} --json-report {output_path}",
                "output_format": "mypy_json",
                "pass_condition": "exit_code == 0",
            },
            "security": {
                "tool": "bandit",
                "default_command": "bandit -r {source_path} -f json -o {output_path}",
                "output_format": "bandit_json",
                "pass_condition": "results == 0",
            },
        }
    }


@pytest.fixture
def engine(project_root: Path, python_matrix: dict) -> ToolExecutionEngine:
    """Fixture returning a ToolExecutionEngine with all Python tools enabled."""
    return ToolExecutionEngine(
        language_tool_matrix=python_matrix,
        language="python",
        validation_tools=["test", "lint", "type_check", "security"],
        project_root=project_root,
    )


# ---------------------------------------------------------------------------
# Test: Whitelist enforcement
# ---------------------------------------------------------------------------

class TestWhitelistEnforcement:
    """Verify that only whitelisted tools may be executed."""

    def test_allowed_tool_returns_true(self, engine: ToolExecutionEngine) -> None:
        """covers: AC-VT-008-01"""
        assert engine.is_allowed_tool("test") is True
        assert engine.is_allowed_tool("lint") is True
        assert engine.is_allowed_tool("security") is True

    def test_disallowed_tool_returns_false(self, engine: ToolExecutionEngine) -> None:
        """covers: AC-VT-008-01"""
        assert engine.is_allowed_tool("deploy") is False
        assert engine.is_allowed_tool("unknown_category") is False

    def test_execute_disallowed_tool_returns_blocked(self, engine: ToolExecutionEngine) -> None:
        """covers: AC-VT-008-01"""
        candidates = engine.execute_tool(tool_category="deploy", path="tests/")
        assert len(candidates) == 1
        c = candidates[0]
        assert c.status == CoverageStatus.BLOCKED.value
        assert c.error_code == ErrorCode.TOOL_EXECUTION_FAILED.value
        assert "白名单" in c.stderr or "not in the whitelist" in c.stderr

    def test_partial_whitelist(self, project_root: Path, python_matrix: dict) -> None:
        """covers: AC-VT-008-01"""
        # Only enable "lint", not "test"
        engine = ToolExecutionEngine(
            language_tool_matrix=python_matrix,
            language="python",
            validation_tools=["lint"],
            project_root=project_root,
        )
        assert engine.is_allowed_tool("lint") is True
        assert engine.is_allowed_tool("test") is False
        assert engine.is_allowed_tool("security") is False

    def test_wrong_language_has_no_tools(
        self, project_root: Path, python_matrix: dict
    ) -> None:
        """covers: AC-VT-008-01"""
        engine = ToolExecutionEngine(
            language_tool_matrix=python_matrix,
            language="javascript",
            validation_tools=["test"],
            project_root=project_root,
        )
        assert engine.is_allowed_tool("test") is False


# ---------------------------------------------------------------------------
# Test: Command template substitution
# ---------------------------------------------------------------------------

class TestCommandTemplateSubstitution:
    """Verify that placeholders in command templates are correctly replaced."""

    def test_placeholder_replacement(self, engine: ToolExecutionEngine) -> None:
        """covers: AC-VT-008-01"""
        template = "pytest {test_path} --json-report --json-report-file={output_path}"
        cmd = engine._build_command(
            template, test_path="tests/test_foo.py", output_path="/tmp/out.json"
        )
        # shlex.quote wraps paths if necessary, otherwise keeps them safe
        assert "tests/test_foo.py" in cmd
        assert "/tmp/out.json" in cmd
        assert "{test_path}" not in cmd
        assert "{output_path}" not in cmd

    def test_source_path_placeholder(self, engine: ToolExecutionEngine) -> None:
        """covers: AC-VT-008-01"""
        template = "ruff check {source_path} --output-format=json"
        cmd = engine._build_command(template, source_path="src/")
        assert "src/" in cmd

    def test_multiple_placeholders(self, engine: ToolExecutionEngine) -> None:
        """covers: AC-VT-008-01"""
        template = (
            "coverage run -m pytest {test_path} && coverage json -o {output_path}"
        )
        cmd = engine._build_command(
            template, test_path="tests/", output_path="/tmp/cov.json"
        )
        assert "tests/" in cmd
        assert "/tmp/cov.json" in cmd

    def test_unresolved_placeholder_raises(self, engine: ToolExecutionEngine) -> None:
        """covers: AC-VT-008-01"""
        template = "pytest {test_path} --config={config_path}"
        with pytest.raises(ValueError, match="未解析|Unresolved"):
            engine._build_command(template, test_path="tests/")

    def test_no_placeholders(self, engine: ToolExecutionEngine) -> None:
        """covers: AC-VT-008-01"""
        template = "pytest tests/ -q"
        cmd = engine._build_command(template)
        assert cmd == "pytest tests/ -q"


# ---------------------------------------------------------------------------
# Test: Shell injection prevention
# ---------------------------------------------------------------------------

class TestShellInjectionPrevention:
    """Verify that path values with shell metacharacters are rejected."""

    def test_semicolon_in_path_rejected(self, engine: ToolExecutionEngine) -> None:
        template = "pytest {test_path} -q"
        with pytest.raises(ValueError, match="不安全|unsafe"):
            engine._build_command(template, test_path="tests/; rm -rf /")

    def test_pipe_in_path_rejected(self, engine: ToolExecutionEngine) -> None:
        template = "pytest {test_path} -q"
        with pytest.raises(ValueError, match="不安全|unsafe"):
            engine._build_command(template, test_path="tests/ | cat /etc/passwd")

    def test_backtick_in_path_rejected(self, engine: ToolExecutionEngine) -> None:
        template = "pytest {test_path} -q"
        with pytest.raises(ValueError, match="不安全|unsafe"):
            engine._build_command(template, test_path="tests/`whoami`")

    def test_dollar_substitution_rejected(self, engine: ToolExecutionEngine) -> None:
        template = "pytest {test_path} -q"
        with pytest.raises(ValueError, match="不安全|unsafe"):
            engine._build_command(template, test_path="tests/$(id)")

    def test_redirect_in_path_rejected(self, engine: ToolExecutionEngine) -> None:
        template = "pytest {test_path} -q"
        with pytest.raises(ValueError, match="不安全|unsafe"):
            engine._build_command(template, test_path="tests/> /tmp/evil")

    def test_valid_path_accepted(self, engine: ToolExecutionEngine) -> None:
        template = "pytest {test_path} -q"
        cmd = engine._build_command(template, test_path="tests/test_valid.py")
        assert "tests/test_valid.py" in cmd


# ---------------------------------------------------------------------------
# Test: Timeout handling
# ---------------------------------------------------------------------------

class TestTimeoutHandling:
    """Verify that subprocess timeout produces structured error evidence."""

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_timeout_returns_blocked_evidence(
        self, mock_run: MagicMock, engine: ToolExecutionEngine
    ) -> None:
        """covers: AC-VT-007-01, AC-VT-008-01"""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="pytest", timeout=120
        )

        # Temporarily override the tool config to use a simple command
        engine._tool_configs["test"] = {
            "tool": "pytest",
            "default_command": "pytest {test_path}",
            "output_format": "pytest_json",
            "pass_condition": "exit_code == 0",
        }

        candidates = engine.execute_tool(tool_category="test", path="tests/test_foo.py")
        assert len(candidates) == 1
        c = candidates[0]
        assert c.status == CoverageStatus.BLOCKED.value
        assert c.error_code == ErrorCode.TOOL_EXECUTION_FAILED.value
        assert "超时" in c.stderr or "timed out" in c.stderr
        assert c.details.get("error_type") == "timeout"
        assert c.details.get("timeout_seconds") == 120

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_custom_timeout(
        self, mock_run: MagicMock, project_root: Path, python_matrix: dict
    ) -> None:
        """covers: AC-VT-007-01"""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="pytest", timeout=30)

        engine = ToolExecutionEngine(
            language_tool_matrix=python_matrix,
            language="python",
            validation_tools=["test"],
            project_root=project_root,
            timeout=30,
        )

        candidates = engine.execute_tool(tool_category="test", path="tests/test_foo.py")
        assert len(candidates) == 1
        assert candidates[0].details.get("timeout_seconds") == 30


# ---------------------------------------------------------------------------
# Test: Missing tool binary
# ---------------------------------------------------------------------------

class TestMissingTool:
    """Verify proper error when tool binary is not found."""

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_file_not_found_returns_blocked(
        self, mock_run: MagicMock, engine: ToolExecutionEngine
    ) -> None:
        """covers: AC-VT-007-01, AC-VT-008-01"""
        mock_run.side_effect = FileNotFoundError("No such file or directory: ruff")

        candidates = engine.execute_tool(tool_category="lint", path="src/")
        assert len(candidates) == 1
        c = candidates[0]
        assert c.status == CoverageStatus.BLOCKED.value
        assert c.error_code == ErrorCode.TOOL_EXECUTION_FAILED.value
        assert "未找到" in c.stderr or "not found" in c.stderr.lower()
        assert c.details.get("error_type") == "tool_not_found"


# ---------------------------------------------------------------------------
# Test: Path validation
# ---------------------------------------------------------------------------

class TestPathValidation:
    """Verify that paths outside project root are rejected."""

    def test_relative_path_inside_root_is_valid(
        self, engine: ToolExecutionEngine
    ) -> None:
        """covers: AC-VT-008-01"""
        ok, err = engine._validate_path("tests/test_foo.py")
        assert ok is True
        assert err == ""

    def test_path_outside_root_is_rejected(
        self, engine: ToolExecutionEngine
    ) -> None:
        """covers: AC-VT-008-01"""
        ok, err = engine._validate_path("../../etc/passwd")
        assert ok is False
        assert "之外" in err or "outside project root" in err

    def test_absolute_path_outside_root_is_rejected(
        self, engine: ToolExecutionEngine
    ) -> None:
        """covers: AC-VT-008-01"""
        ok, err = engine._validate_path("/etc/passwd")
        assert ok is False
        assert "之外" in err or "outside project root" in err

    def test_execute_with_invalid_path_returns_blocked(
        self, engine: ToolExecutionEngine
    ) -> None:
        """covers: AC-VT-008-01"""
        candidates = engine.execute_tool(
            tool_category="lint", path="../../etc/passwd"
        )
        assert len(candidates) == 1
        c = candidates[0]
        assert c.status == CoverageStatus.BLOCKED.value
        assert c.error_code == ErrorCode.TOOL_EXECUTION_FAILED.value
        assert "之外" in c.stderr or "outside project root" in c.stderr

    def test_dot_dot_path_resolved_safely(self, engine: ToolExecutionEngine) -> None:
        """covers: AC-VT-008-01"""
        # tests/../tests/test_foo.py should resolve inside root
        ok, err = engine._validate_path("tests/../tests/test_foo.py")
        assert ok is True


# ---------------------------------------------------------------------------
# Test: Output parsing (pytest_json)
# ---------------------------------------------------------------------------

class TestPytestOutputParsing:
    """Verify pytest JSON output is correctly parsed."""

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_pytest_passing_tests(
        self, mock_run: MagicMock, engine: ToolExecutionEngine, tmp_path: Path
    ) -> None:
        """covers: AC-VT-001-02"""
        report_data = {
            "tests": [
                {
                    "nodeid": "tests/test_foo.py::test_bar",
                    "outcome": "passed",
                    "docstring": "covers: AC-VT-001-01",
                }
            ]
        }
        report_path = tmp_path / "pytest_report.json"
        report_path.write_text(json.dumps(report_data), encoding="utf-8")

        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr=""
        )

        engine._tool_configs["test"] = {
            "tool": "pytest",
            "default_command": f"pytest {{test_path}} --json-report --json-report-file={report_path}",
            "output_format": "pytest_json",
            "pass_condition": "exit_code == 0",
        }

        candidates = engine.execute_tool(tool_category="test", path="tests/test_foo.py")
        assert len(candidates) == 1
        c = candidates[0]
        assert c.status == CoverageStatus.COVERED.value
        assert c.covers == ["AC-VT-001-01"]
        assert c.source_type == "test"

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_pytest_failing_tests(
        self, mock_run: MagicMock, engine: ToolExecutionEngine, tmp_path: Path
    ) -> None:
        """covers: AC-VT-001-02"""
        report_data = {
            "tests": [
                {
                    "nodeid": "tests/test_foo.py::test_bar",
                    "outcome": "failed",
                }
            ]
        }
        report_path = tmp_path / "pytest_report.json"
        report_path.write_text(json.dumps(report_data), encoding="utf-8")

        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr=""
        )

        engine._tool_configs["test"] = {
            "tool": "pytest",
            "default_command": f"pytest {{test_path}} --json-report --json-report-file={report_path}",
            "output_format": "pytest_json",
            "pass_condition": "exit_code == 0",
        }

        candidates = engine.execute_tool(tool_category="test", path="tests/test_foo.py")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.VIOLATED.value

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_pytest_exit5_no_tests_collected_returns_skipped(
        self, mock_run: MagicMock, engine: ToolExecutionEngine
    ) -> None:
        """covers: EVO-TASK-017 — pytest exit 5 (no tests collected) produces skipped evidence."""
        mock_run.return_value = MagicMock(
            returncode=5, stdout="", stderr="no tests ran"
        )

        candidates = engine.execute_tool(tool_category="test", path="tests/test_foo.py")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.SKIPPED.value
        assert candidates[0].error_code == ErrorCode.TOOL_NO_TESTS_COLLECTED.value
        assert candidates[0].details["skip_reason"] == "no tests collected"

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_pytest_exit2_usage_error_returns_skipped(
        self, mock_run: MagicMock, engine: ToolExecutionEngine
    ) -> None:
        """covers: EVO-TASK-017 — pytest exit 2 (usage error) produces skipped evidence."""
        mock_run.return_value = MagicMock(
            returncode=2, stdout="", stderr="unrecognized arguments: --invalid"
        )

        candidates = engine.execute_tool(tool_category="test", path="tests/test_foo.py")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.SKIPPED.value
        assert candidates[0].error_code == ErrorCode.TOOL_USAGE_ERROR.value
        assert candidates[0].details["skip_reason"] == "usage error"


# ---------------------------------------------------------------------------
# Test: Output parsing (ruff_json)
# ---------------------------------------------------------------------------

class TestRuffOutputParsing:
    """Verify ruff JSON output is correctly parsed."""

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_ruff_clean(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: AC-VT-001-02"""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="[]", stderr=""
        )

        candidates = engine.execute_tool(tool_category="lint", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.COMPLIANT.value

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_ruff_violations(
        self, mock_run: MagicMock, engine: ToolExecutionEngine
    ) -> None:
        """covers: AC-VT-001-02"""
        violations = [{"code": "F401", "message": "unused import"}]
        mock_run.return_value = MagicMock(
            returncode=1, stdout=json.dumps(violations), stderr=""
        )

        candidates = engine.execute_tool(tool_category="lint", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.VIOLATED.value
        assert candidates[0].details["violations_count"] == 1


# ---------------------------------------------------------------------------
# Test: Source-file coverage measurement from baseline
# ---------------------------------------------------------------------------

class TestSourceCoverageMeasurement:
    """Verify per-source-file coverage from baseline JSON."""

    def test_compliant_file(
        self, engine: ToolExecutionEngine, project_root: Path
    ) -> None:
        """covers: AC-VT-001-02 — file at or above 80% is compliant."""
        baseline = {
            "files": {
                "src/vibe_tracing/foo.py": {
                    "percent_covered": 85.5,
                    "num_statements": 100,
                    "missing_lines": [10, 20],
                    "last_measured": "2026-06-09T00:00:00Z",
                }
            }
        }
        baseline_path = project_root / ".vibetracing" / "coverage_baseline.json"
        baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

        candidates = engine._measure_source_coverage()
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.COMPLIANT.value
        assert candidates[0].source_path == "src/vibe_tracing/foo.py"
        assert candidates[0].details["percent_covered"] == 85.5
        assert candidates[0].details["num_statements"] == 100
        assert candidates[0].details["measurement"] == "baseline"
        assert candidates[0].tool_category == "coverage"

    def test_violated_file(
        self, engine: ToolExecutionEngine, project_root: Path
    ) -> None:
        """covers: AC-VT-001-02 — file below 80% is violated."""
        baseline = {
            "files": {
                "src/vibe_tracing/bar.py": {
                    "percent_covered": 55.0,
                    "num_statements": 200,
                    "missing_lines": [1, 2, 3],
                    "last_measured": "2026-06-09T00:00:00Z",
                }
            }
        }
        baseline_path = project_root / ".vibetracing" / "coverage_baseline.json"
        baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

        candidates = engine._measure_source_coverage()
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.VIOLATED.value
        assert candidates[0].details["percent_covered"] == 55.0

    def test_multiple_files(
        self, engine: ToolExecutionEngine, project_root: Path
    ) -> None:
        """covers: AC-VT-001-02 — one candidate per source file."""
        baseline = {
            "files": {
                "src/a.py": {"percent_covered": 100.0, "num_statements": 10},
                "src/b.py": {"percent_covered": 70.0, "num_statements": 50},
                "src/c.py": {"percent_covered": 80.0, "num_statements": 30},
            }
        }
        baseline_path = project_root / ".vibetracing" / "coverage_baseline.json"
        baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

        candidates = engine._measure_source_coverage()
        assert len(candidates) == 3
        statuses = {c.source_path: c.status for c in candidates}
        assert statuses["src/a.py"] == CoverageStatus.COMPLIANT.value
        assert statuses["src/b.py"] == CoverageStatus.VIOLATED.value
        assert statuses["src/c.py"] == CoverageStatus.COMPLIANT.value

    def test_missing_baseline_returns_empty(
        self, engine: ToolExecutionEngine
    ) -> None:
        """covers: AC-VT-001-02 — no crash when baseline file missing."""
        candidates = engine._measure_source_coverage()
        assert candidates == []

    def test_custom_baseline_path(
        self, engine: ToolExecutionEngine, tmp_path: Path
    ) -> None:
        """covers: AC-VT-001-02 — override baseline path works."""
        baseline = {
            "files": {
                "src/x.py": {"percent_covered": 90.0, "num_statements": 20}
            }
        }
        custom_path = tmp_path / "custom_baseline.json"
        custom_path.write_text(json.dumps(baseline), encoding="utf-8")

        candidates = engine._measure_source_coverage(str(custom_path))
        assert len(candidates) == 1
        assert candidates[0].source_path == "src/x.py"
        assert candidates[0].status == CoverageStatus.COMPLIANT.value

    def test_custom_threshold(
        self, engine: ToolExecutionEngine, project_root: Path
    ) -> None:
        """covers: AC-VT-001-02 — custom pass_threshold is respected."""
        baseline = {
            "files": {
                "src/y.py": {"percent_covered": 85.0, "num_statements": 40}
            }
        }
        baseline_path = project_root / ".vibetracing" / "coverage_baseline.json"
        baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

        # With threshold 90, 85% should be violated
        candidates = engine._measure_source_coverage(pass_threshold=90.0)
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.VIOLATED.value


# ---------------------------------------------------------------------------
# Test: Output parsing (bandit_json)
# ---------------------------------------------------------------------------

class TestBanditOutputParsing:
    """Verify bandit JSON output is correctly parsed."""

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_bandit_clean(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: AC-VT-001-02"""
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"results": []}', stderr=""
        )

        candidates = engine.execute_tool(tool_category="security", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.COMPLIANT.value

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_bandit_findings(
        self, mock_run: MagicMock, engine: ToolExecutionEngine
    ) -> None:
        """covers: AC-VT-001-02"""
        bandit_data = {
            "results": [
                {"issue_severity": "HIGH", "issue_text": "Use of assert detected"}
            ]
        }
        mock_run.return_value = MagicMock(
            returncode=1, stdout=json.dumps(bandit_data), stderr=""
        )

        candidates = engine.execute_tool(tool_category="security", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.VIOLATED.value
        assert candidates[0].details["results_count"] == 1


# ---------------------------------------------------------------------------
# Test: Output parsing (mypy_json)
# ---------------------------------------------------------------------------

class TestMypyOutputParsing:
    """Verify mypy output is correctly parsed."""

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_mypy_clean(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: AC-VT-001-02"""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Success: no issues found", stderr=""
        )

        candidates = engine.execute_tool(tool_category="type_check", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.COMPLIANT.value

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_mypy_errors(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: AC-VT-001-02"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="src/foo.py:10: error: Incompatible types\nsrc/bar.py:5: error: Missing return",
            stderr="",
        )

        candidates = engine.execute_tool(tool_category="type_check", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.VIOLATED.value
        assert candidates[0].details["errors_count"] == 2

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_mypy_exit2_usage_error_returns_skipped(
        self, mock_run: MagicMock, engine: ToolExecutionEngine
    ) -> None:
        """covers: EVO-TASK-017 — mypy exit 2 (usage error) produces skipped evidence."""
        mock_run.return_value = MagicMock(
            returncode=2, stdout="", stderr="error: invalid configuration"
        )

        candidates = engine.execute_tool(tool_category="type_check", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.SKIPPED.value
        assert candidates[0].error_code == ErrorCode.TOOL_USAGE_ERROR.value
        assert candidates[0].details["skip_reason"] == "usage error"


# ---------------------------------------------------------------------------
# Test: execute_all
# ---------------------------------------------------------------------------

class TestExecuteAll:
    """Verify execute_all runs all whitelisted tools for all paths."""

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_execute_all_runs_all_tools(
        self, mock_run: MagicMock, engine: ToolExecutionEngine
    ) -> None:
        """covers: AC-VT-008-01"""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="[]", stderr=""
        )

        # Only use "lint" for a simpler test
        engine._tool_configs = {
            "lint": engine._tool_configs["lint"]
        }

        candidates = engine.execute_all(["src/vibe_tracing/foo.py"])
        assert len(candidates) >= 1
        # Should have run at least once
        mock_run.assert_called()

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_execute_all_skips_non_python_for_lint(
        self, mock_run: MagicMock, engine: ToolExecutionEngine
    ) -> None:
        """covers: AC-VT-015a — .md files are skipped by lint tool."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="[]", stderr=""
        )

        engine._tool_configs = {
            "lint": engine._tool_configs["lint"]
        }

        candidates = engine.execute_all(["docs/README.md"])
        assert len(candidates) == 0
        mock_run.assert_not_called()

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_execute_all_skips_non_python_for_test(
        self, mock_run: MagicMock, engine: ToolExecutionEngine
    ) -> None:
        """covers: AC-VT-015a — .md files are skipped by test tool."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="[]", stderr=""
        )

        engine._tool_configs = {
            "test": engine._tool_configs["test"]
        }

        candidates = engine.execute_all(["docs/README.md"])
        assert len(candidates) == 0
        mock_run.assert_not_called()

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_execute_all_skips_non_python_for_all_categories(
        self, mock_run: MagicMock, engine: ToolExecutionEngine
    ) -> None:
        """covers: AC-VT-015a — .json file skipped by all python-only tools."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="[]", stderr=""
        )

        # Keep all tool configs
        candidates = engine.execute_all(["config/settings.json"])
        assert len(candidates) == 0
        mock_run.assert_not_called()

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_execute_all_runs_python_files_for_all_categories(
        self, mock_run: MagicMock, engine: ToolExecutionEngine
    ) -> None:
        """covers: AC-VT-015a — .py files run on all tool categories."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="[]", stderr=""
        )

        candidates = engine.execute_all(["src/module.py"])
        # 4 subprocess-based tool categories execute (test, lint, type_check,
        # security).  Coverage is measured from baseline, not via subprocess.
        assert mock_run.call_count == 4
        # Each category produces at least one candidate (lint,
        # type_check, security return 1 each; test returns 0 from empty parse)
        assert len(candidates) >= 3

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_execute_all_mixed_paths_filters_correctly(
        self, mock_run: MagicMock, engine: ToolExecutionEngine
    ) -> None:
        """covers: AC-VT-015a — mixed .py and .md paths filter per category."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="[]", stderr=""
        )

        # Only lint is active
        engine._tool_configs = {
            "lint": engine._tool_configs["lint"]
        }

        candidates = engine.execute_all(["src/module.py", "docs/README.md"])
        # Only the .py path should be linted
        assert len(candidates) == 1
        assert mock_run.call_count == 1

    def test_tool_file_type_map_default_values(self) -> None:
        """covers: AC-VT-015a — TOOL_FILE_TYPE_MAP has expected structure."""
        expected = {
            "test": {".py"},
            "lint": {".py"},
            "type_check": {".py"},
            "security": {".py"},
        }
        assert ToolExecutionEngine.TOOL_FILE_TYPE_MAP == expected


# ---------------------------------------------------------------------------
# Test: ToolEvidenceCandidate dataclass
# ---------------------------------------------------------------------------

def test_tool_evidence_candidate_unchanged() -> None:
    """covers: AC-VT-008-01"""
    c = ToolEvidenceCandidate(
        source_type="test",
        source_path="tests/test_foo.py",
        covers=["AC-VT-001-01"],
        status=CoverageStatus.COVERED.value,
    )
    assert c.source_type == "test"
    assert c.command == ""
    assert c.exit_code == 0
    assert c.stderr == ""
    assert c.error_code is None
    assert c.details == {}


# ---------------------------------------------------------------------------
# Test: _resolve_hint helper
# ---------------------------------------------------------------------------

class TestResolveHint:
    """Verify _resolve_hint handles different hint value types."""

    def test_string_hint_returns_string(self) -> None:
        """covers: _resolve_hint string branch"""
        from vibe_tracing.tool_evidence_adapter import _resolve_hint
        assert _resolve_hint("some hint") == "some hint"

    def test_dict_hint_returns_level1(self) -> None:
        """covers: _resolve_hint dict branch (line 37-39)"""
        from vibe_tracing.tool_evidence_adapter import _resolve_hint
        hint = {"level1": "L1 text", "level2": "L2 text", "level3": "L3 text"}
        assert _resolve_hint(hint, "level1") == "L1 text"

    def test_dict_hint_falls_back_to_level3(self) -> None:
        """covers: _resolve_hint dict branch with level3 fallback (line 40)"""
        from vibe_tracing.tool_evidence_adapter import _resolve_hint
        hint = {"level3": "L3 only"}
        assert _resolve_hint(hint, "level1") == "L3 only"

    def test_other_type_returns_empty(self) -> None:
        """covers: _resolve_hint non-string/non-dict branch"""
        from vibe_tracing.tool_evidence_adapter import _resolve_hint
        assert _resolve_hint(123) == ""
        assert _resolve_hint(None) == ""
        assert _resolve_hint(["list"]) == ""


# ---------------------------------------------------------------------------
# Test: _load_hints error handling
# ---------------------------------------------------------------------------

class TestLoadHints:
    """Verify _load_hints gracefully handles missing/corrupt files."""

    def test_missing_file_returns_empty_dict(self) -> None:
        """covers: _load_hints FileNotFoundError branch (lines 31-32)"""
        from vibe_tracing.tool_evidence_adapter import _load_hints
        with patch("vibe_tracing.tool_evidence_adapter._HINTS_PATH", Path("/nonexistent/path.json")):
            result = _load_hints("tool")
            assert result == {}

    def test_corrupt_json_returns_empty_dict(self) -> None:
        """covers: _load_hints JSONDecodeError branch (lines 31-32)"""
        from vibe_tracing.tool_evidence_adapter import _load_hints, _HINTS_PATH
        with patch.object(type(_HINTS_PATH), "read_text", side_effect=json.JSONDecodeError("", "", 0)):
            result = _load_hints("tool")
            assert result == {}


# ---------------------------------------------------------------------------
# Test: _validate_path error handling
# ---------------------------------------------------------------------------

class TestValidatePathErrors:
    """Verify _validate_path handles exceptions during path resolution."""

    def test_invalid_path_returns_false(self, engine: ToolExecutionEngine) -> None:
        """covers: _validate_path ValueError/OSError branch (lines 166-167)"""
        with patch("vibe_tracing.tool_evidence_adapter.Path.resolve", side_effect=ValueError("bad path")):
            ok, err = engine._validate_path("some/path")
            assert ok is False
            assert "Invalid path" in err

    def test_path_equals_root_is_valid(self, engine: ToolExecutionEngine, project_root: Path) -> None:
        """covers: _validate_path path == project_root branch (line 162)"""
        # "." resolves to the project root itself
        ok, err = engine._validate_path(".")
        assert ok is True


# ---------------------------------------------------------------------------
# Test: _run_subprocess error handling
# ---------------------------------------------------------------------------

class TestRunSubprocessErrors:
    """Verify _run_subprocess handles various OS-level exceptions."""

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_permission_error(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: _run_subprocess PermissionError branch (lines 263-266)"""
        mock_run.side_effect = PermissionError("Permission denied")
        exit_code, stdout, stderr, error = engine._run_subprocess("some_tool --arg")
        assert exit_code == -1
        assert error == "permission"
        assert "权限" in stderr or "Permission denied" in stderr

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_os_error(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: _run_subprocess OSError branch (lines 267-270)"""
        mock_run.side_effect = OSError("OS boom")
        exit_code, stdout, stderr, error = engine._run_subprocess("some_tool")
        assert exit_code == -1
        assert error == "os_error"
        assert "OS error" in stderr or "操作系统" in stderr

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_permission_error_execute_tool(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: execute_tool generic exec_error branch (lines 770-783)"""
        mock_run.side_effect = PermissionError("no access")
        candidates = engine.execute_tool(tool_category="lint", path="src/")
        assert len(candidates) == 1
        c = candidates[0]
        assert c.status == CoverageStatus.BLOCKED.value
        assert c.error_code == ErrorCode.TOOL_EXECUTION_FAILED.value
        assert c.details.get("error_type") == "permission"

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_os_error_execute_tool(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: execute_tool generic exec_error branch (lines 770-783)"""
        mock_run.side_effect = OSError("os boom")
        candidates = engine.execute_tool(tool_category="lint", path="src/")
        assert len(candidates) == 1
        c = candidates[0]
        assert c.status == CoverageStatus.BLOCKED.value
        assert c.details.get("error_type") == "os_error"


# ---------------------------------------------------------------------------
# Test: Pytest edge cases
# ---------------------------------------------------------------------------

class TestPytestEdgeCases:
    """Verify pytest parser handles non-standard exit codes and fallback paths."""

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_pytest_exit3_returns_blocked(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: pytest exit code not in (0,1,2,5) → blocked (line 316)"""
        mock_run.return_value = MagicMock(returncode=3, stdout="", stderr="internal error")
        candidates = engine.execute_tool(tool_category="test", path="tests/test_foo.py")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.BLOCKED.value
        assert candidates[0].error_code == ErrorCode.TOOL_EXECUTION_FAILED.value

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_pytest_json_report_file_with_relative_path(
        self, mock_run: MagicMock, engine: ToolExecutionEngine, project_root: Path
    ) -> None:
        """covers: pytest JSON report file reading with relative path (lines 331-342)"""
        report_data = {"tests": [{"nodeid": "tests/test_foo.py::test_bar", "outcome": "passed"}]}
        report_path = project_root / "pytest_report.json"
        report_path.write_text(json.dumps(report_data), encoding="utf-8")

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        engine._tool_configs["test"] = {
            "tool": "pytest",
            "default_command": f"pytest {{test_path}} --json-report --json-report-file=pytest_report.json",
            "output_format": "pytest_json",
            "pass_condition": "exit_code == 0",
        }
        candidates = engine.execute_tool(tool_category="test", path="tests/test_foo.py")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.COVERED.value

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_pytest_json_report_file_parse_error_falls_back(
        self, mock_run: MagicMock, engine: ToolExecutionEngine, project_root: Path
    ) -> None:
        """covers: pytest JSON report file JSONDecodeError fallback (lines 341-342)"""
        report_path = project_root / "bad_report.json"
        report_path.write_text("NOT JSON", encoding="utf-8")

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        engine._tool_configs["test"] = {
            "tool": "pytest",
            "default_command": f"pytest {{test_path}} --json-report --json-report-file={report_path}",
            "output_format": "pytest_json",
            "pass_condition": "exit_code == 0",
        }
        candidates = engine.execute_tool(tool_category="test", path="tests/test_foo.py")
        assert len(candidates) == 1
        # Falls through to last resort (exit_code 0 = covered)
        assert candidates[0].status == CoverageStatus.COVERED.value

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_pytest_stdout_json_fallback(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: pytest stdout JSON fallback (lines 345-349)"""
        report_data = {"tests": [{"nodeid": "tests/test_foo.py::test_baz", "outcome": "passed"}]}
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(report_data), stderr="")
        engine._tool_configs["test"] = {
            "tool": "pytest",
            "default_command": "pytest {test_path} -q",
            "output_format": "pytest_json",
            "pass_condition": "exit_code == 0",
        }
        candidates = engine.execute_tool(tool_category="test", path="tests/test_foo.py")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.COVERED.value

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_pytest_last_resort_exit0(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: pytest last resort fallback exit_code=0 (lines 352-366)"""
        mock_run.return_value = MagicMock(returncode=0, stdout="no json here", stderr="")
        engine._tool_configs["test"] = {
            "tool": "pytest",
            "default_command": "pytest {test_path} -q",
            "output_format": "pytest_json",
            "pass_condition": "exit_code == 0",
        }
        candidates = engine.execute_tool(tool_category="test", path="tests/test_foo.py")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.COVERED.value
        assert candidates[0].details["outcome"] == "passed"

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_pytest_last_resort_exit1(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: pytest last resort fallback exit_code=1 (lines 352-366)"""
        mock_run.return_value = MagicMock(returncode=1, stdout="no json here", stderr="")
        engine._tool_configs["test"] = {
            "tool": "pytest",
            "default_command": "pytest {test_path} -q",
            "output_format": "pytest_json",
            "pass_condition": "exit_code == 0",
        }
        candidates = engine.execute_tool(tool_category="test", path="tests/test_foo.py")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.VIOLATED.value
        assert candidates[0].details["outcome"] == "failed"


# ---------------------------------------------------------------------------
# Test: Pytest JSON parsing edge cases
# ---------------------------------------------------------------------------

class TestPytestJsonParsingEdgeCases:
    """Verify _parse_pytest_json handles edge cases in JSON structure."""

    def test_tests_data_not_a_list(self, engine: ToolExecutionEngine) -> None:
        """covers: _parse_pytest_json tests_data not list (line 378)"""
        data = {"tests": "not_a_list"}
        result = engine._parse_pytest_json(data, "cmd", "path")
        assert result == []

    def test_test_entry_not_a_dict(self, engine: ToolExecutionEngine) -> None:
        """covers: _parse_pytest_json test not dict (line 382)"""
        data = {"tests": ["string", 123]}
        result = engine._parse_pytest_json(data, "cmd", "path")
        assert len(result) == 0

    def test_metadata_docstring_fallback(self, engine: ToolExecutionEngine) -> None:
        """covers: _parse_pytest_json metadata docstring (lines 388-392)"""
        data = {
            "tests": [{
                "nodeid": "tests/test_foo.py::test_bar",
                "outcome": "passed",
                "metadata": {"docstring": "covers: AC-VT-999-01"},
            }]
        }
        result = engine._parse_pytest_json(data, "cmd", "path")
        assert len(result) == 1
        assert result[0].covers == ["AC-VT-999-01"]

    def test_unclear_outcome(self, engine: ToolExecutionEngine) -> None:
        """covers: _parse_pytest_json unclear outcome (line 404)"""
        data = {
            "tests": [{
                "nodeid": "tests/test_foo.py::test_skipped",
                "outcome": "skipped",
            }]
        }
        result = engine._parse_pytest_json(data, "cmd", "path")
        assert len(result) == 1
        assert result[0].status == CoverageStatus.UNCLEAR.value

    def test_non_dict_data_returns_empty(self, engine: ToolExecutionEngine) -> None:
        """covers: _parse_pytest_json data not dict (line 373)"""
        result = engine._parse_pytest_json("not_a_dict", "cmd", "path")
        assert result == []


# ---------------------------------------------------------------------------
# Test: Ruff edge cases
# ---------------------------------------------------------------------------

class TestRuffEdgeCases:
    """Verify ruff parser handles edge cases."""

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_ruff_exit3_returns_blocked(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: ruff exit code not in (0,1) → blocked (line 426)"""
        mock_run.return_value = MagicMock(returncode=3, stdout="", stderr="ruff crashed")
        candidates = engine.execute_tool(tool_category="lint", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.BLOCKED.value
        assert candidates[0].error_code == ErrorCode.TOOL_EXECUTION_FAILED.value

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_ruff_dict_output_with_violations_key(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: ruff dict output parsing (lines 444-450)"""
        data = {"violations": [{"code": "F401", "message": "unused import"}]}
        mock_run.return_value = MagicMock(returncode=1, stdout=json.dumps(data), stderr="")
        candidates = engine.execute_tool(tool_category="lint", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.VIOLATED.value
        assert candidates[0].details["violations_count"] == 1

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_ruff_dict_output_with_results_key(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: ruff dict output with 'results' key (line 446)"""
        data = {"results": []}
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(data), stderr="")
        candidates = engine.execute_tool(tool_category="lint", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.COMPLIANT.value

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_ruff_dict_output_with_issues_key(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: ruff dict output with 'issues' key (line 446)"""
        data = {"issues": [{"code": "E501"}]}
        mock_run.return_value = MagicMock(returncode=1, stdout=json.dumps(data), stderr="")
        candidates = engine.execute_tool(tool_category="lint", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.VIOLATED.value

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_ruff_invalid_json_returns_compliant(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: ruff JSONDecodeError branch (line 449-450)"""
        mock_run.return_value = MagicMock(returncode=0, stdout="not json", stderr="")
        candidates = engine.execute_tool(tool_category="lint", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.COMPLIANT.value


# ---------------------------------------------------------------------------
# Test: Mypy edge cases
# ---------------------------------------------------------------------------

class TestMypyEdgeCases:
    """Verify mypy parser handles edge cases."""

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_mypy_exit3_returns_blocked(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: mypy exit code not in (0,1,2) → blocked (line 498)"""
        mock_run.return_value = MagicMock(returncode=3, stdout="", stderr="mypy crashed")
        candidates = engine.execute_tool(tool_category="type_check", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.BLOCKED.value
        assert candidates[0].error_code == ErrorCode.TOOL_EXECUTION_FAILED.value

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_mypy_json_report_file(
        self, mock_run: MagicMock, engine: ToolExecutionEngine, project_root: Path
    ) -> None:
        """covers: mypy JSON report file reading (lines 513-525)"""
        report = {"summary": {"error_count": 3}}
        report_path = project_root / "mypy_report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")

        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        engine._tool_configs["type_check"] = {
            "tool": "mypy",
            "default_command": f"mypy {{source_path}} --json-report {report_path}",
            "output_format": "mypy_json",
            "pass_condition": "exit_code == 0",
        }
        candidates = engine.execute_tool(tool_category="type_check", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.VIOLATED.value
        assert candidates[0].details["errors_count"] == 3

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_mypy_json_report_bad_json_falls_back(
        self, mock_run: MagicMock, engine: ToolExecutionEngine, project_root: Path
    ) -> None:
        """covers: mypy JSON report JSONDecodeError fallback (line 524-525)"""
        report_path = project_root / "bad_mypy.json"
        report_path.write_text("NOT JSON", encoding="utf-8")

        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="src/foo.py:10: error: Something wrong",
            stderr="",
        )
        engine._tool_configs["type_check"] = {
            "tool": "mypy",
            "default_command": f"mypy {{source_path}} --json-report {report_path}",
            "output_format": "mypy_json",
            "pass_condition": "exit_code == 0",
        }
        candidates = engine.execute_tool(tool_category="type_check", path="src/")
        assert len(candidates) == 1
        assert candidates[0].details["errors_count"] == 1


# ---------------------------------------------------------------------------
# Test: Bandit edge cases
# ---------------------------------------------------------------------------

class TestBanditEdgeCases:
    """Verify bandit parser handles edge cases."""

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_bandit_exit3_returns_blocked(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: bandit exit code not in (0,1) → blocked (line 556)"""
        mock_run.return_value = MagicMock(returncode=3, stdout="", stderr="bandit crashed")
        candidates = engine.execute_tool(tool_category="security", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.BLOCKED.value
        assert candidates[0].error_code == ErrorCode.TOOL_EXECUTION_FAILED.value

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_bandit_output_file(
        self, mock_run: MagicMock, engine: ToolExecutionEngine, project_root: Path
    ) -> None:
        """covers: bandit output file reading (lines 572-586)"""
        report = {"results": [{"issue_severity": "LOW", "issue_text": "test"}]}
        report_path = project_root / "bandit_report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")

        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        engine._tool_configs["security"] = {
            "tool": "bandit",
            "default_command": f"bandit -r {{source_path}} -f json -o {report_path}",
            "output_format": "bandit_json",
            "pass_condition": "results == 0",
        }
        candidates = engine.execute_tool(tool_category="security", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.VIOLATED.value
        assert candidates[0].details["results_count"] == 1

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_bandit_output_file_bad_json_falls_back(
        self, mock_run: MagicMock, engine: ToolExecutionEngine, project_root: Path
    ) -> None:
        """covers: bandit output file JSONDecodeError fallback (line 585-586)"""
        report_path = project_root / "bad_bandit.json"
        report_path.write_text("NOT JSON", encoding="utf-8")

        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"results": []}', stderr=""
        )
        engine._tool_configs["security"] = {
            "tool": "bandit",
            "default_command": f"bandit -r {{source_path}} -f json -o {report_path}",
            "output_format": "bandit_json",
            "pass_condition": "results == 0",
        }
        candidates = engine.execute_tool(tool_category="security", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.COMPLIANT.value

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_bandit_output_file_results_not_list(
        self, mock_run: MagicMock, engine: ToolExecutionEngine, project_root: Path
    ) -> None:
        """covers: bandit results not list fallback (line 595)"""
        report = {"results": "not_a_list"}
        report_path = project_root / "bandit_bad_results.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        engine._tool_configs["security"] = {
            "tool": "bandit",
            "default_command": f"bandit -r {{source_path}} -f json -o {report_path}",
            "output_format": "bandit_json",
            "pass_condition": "results == 0",
        }
        candidates = engine.execute_tool(tool_category="security", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.COMPLIANT.value

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_bandit_stdout_list_fallback(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: bandit stdout list fallback (lines 596-599)"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=json.dumps([{"issue_severity": "HIGH"}]),
            stderr="",
        )
        candidates = engine.execute_tool(tool_category="security", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.VIOLATED.value
        assert candidates[0].details["results_count"] == 1

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_bandit_stdout_bad_json(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: bandit stdout JSONDecodeError branch (line 598-599)"""
        mock_run.return_value = MagicMock(returncode=0, stdout="not json", stderr="")
        candidates = engine.execute_tool(tool_category="security", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.COMPLIANT.value

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_bandit_output_file_no_output_path_match(
        self, mock_run: MagicMock, engine: ToolExecutionEngine, project_root: Path
    ) -> None:
        """covers: bandit no -o match, falls back to stdout (lines 588-599)"""
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"results": []}', stderr=""
        )
        engine._tool_configs["security"] = {
            "tool": "bandit",
            "default_command": "bandit -r {source_path} -f json",
            "output_format": "bandit_json",
            "pass_condition": "results == 0",
        }
        candidates = engine.execute_tool(tool_category="security", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.COMPLIANT.value


# ---------------------------------------------------------------------------
# Test: execute_tool build_command ValueError
# ---------------------------------------------------------------------------

class TestExecuteToolBuildCommandError:
    """Verify execute_tool handles _build_command ValueError."""

    def test_build_command_value_error_returns_blocked(
        self, engine: ToolExecutionEngine
    ) -> None:
        """covers: execute_tool build_command ValueError (lines 718-729)"""
        engine._tool_configs["test"] = {
            "tool": "pytest",
            "default_command": "pytest {test_path} --config={unknown_var}",
            "output_format": "pytest_json",
            "pass_condition": "exit_code == 0",
        }
        candidates = engine.execute_tool(tool_category="test", path="tests/test_foo.py")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.BLOCKED.value
        assert candidates[0].error_code == ErrorCode.TOOL_EXECUTION_FAILED.value


# ---------------------------------------------------------------------------
# Test: Unsupported output format
# ---------------------------------------------------------------------------

class TestUnsupportedOutputFormat:
    """Verify execute_tool handles unsupported output_format."""

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_unsupported_format_returns_blocked(
        self, mock_run: MagicMock, engine: ToolExecutionEngine
    ) -> None:
        """covers: execute_tool unsupported output format (lines 797-810)"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        engine._tool_configs["lint"] = {
            "tool": "ruff",
            "default_command": "ruff check {source_path}",
            "output_format": "xml_format",
            "pass_condition": "exit_code == 0",
        }
        candidates = engine.execute_tool(tool_category="lint", path="src/")
        assert len(candidates) == 1
        assert candidates[0].status == CoverageStatus.BLOCKED.value
        assert candidates[0].error_code == ErrorCode.TOOL_EXECUTION_FAILED.value
        assert "不支持" in candidates[0].stderr or "Unsupported" in candidates[0].stderr


# ---------------------------------------------------------------------------
# Test: _measure_source_coverage edge cases
# ---------------------------------------------------------------------------

class TestMeasureSourceCoverageEdgeCases:
    """Verify _measure_source_coverage handles malformed baseline data."""

    def test_corrupt_baseline_json(self, engine: ToolExecutionEngine, project_root: Path) -> None:
        """covers: _measure_source_coverage JSONDecodeError (line 847-848)"""
        baseline_path = project_root / ".vibetracing" / "coverage_baseline.json"
        baseline_path.write_text("NOT JSON", encoding="utf-8")
        candidates = engine._measure_source_coverage(baseline_path=str(baseline_path))
        assert candidates == []

    def test_baseline_files_not_dict(self, engine: ToolExecutionEngine, project_root: Path) -> None:
        """covers: _measure_source_coverage files not dict (line 852)"""
        baseline = {"files": "not_a_dict"}
        baseline_path = project_root / ".vibetracing" / "coverage_baseline.json"
        baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
        candidates = engine._measure_source_coverage(baseline_path=str(baseline_path))
        assert candidates == []

    def test_file_data_not_dict_skipped(self, engine: ToolExecutionEngine, project_root: Path) -> None:
        """covers: _measure_source_coverage file_data not dict (line 857)"""
        baseline = {"files": {"src/a.py": "not_a_dict", "src/b.py": {"percent_covered": 90, "num_statements": 10}}}
        baseline_path = project_root / ".vibetracing" / "coverage_baseline.json"
        baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
        candidates = engine._measure_source_coverage(baseline_path=str(baseline_path))
        assert len(candidates) == 1
        assert candidates[0].source_path == "src/b.py"

    def test_percent_none_skipped(self, engine: ToolExecutionEngine, project_root: Path) -> None:
        """covers: _measure_source_coverage percent is None (line 862)"""
        baseline = {"files": {"src/a.py": {"num_statements": 10}}}
        baseline_path = project_root / ".vibetracing" / "coverage_baseline.json"
        baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
        candidates = engine._measure_source_coverage(baseline_path=str(baseline_path))
        assert candidates == []


# ---------------------------------------------------------------------------
# Test: execute_all with typed paths (dict)
# ---------------------------------------------------------------------------

class TestExecuteAllTypedPaths:
    """Verify execute_all with dict-style typed paths."""

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_dict_paths_test_type(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: execute_all dict paths branch (lines 913-924)"""
        mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
        engine._tool_configs = {"test": engine._tool_configs["test"]}
        candidates = engine.execute_all({"test": ["tests/test_foo.py"]})
        assert mock_run.call_count == 1

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_dict_paths_source_type(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: execute_all dict paths source type (lines 913-924)"""
        mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
        engine._tool_configs = {"lint": engine._tool_configs["lint"]}
        candidates = engine.execute_all({"source": ["src/module.py"]})
        assert mock_run.call_count == 1

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_dict_paths_unknown_type_skipped(self, mock_run: MagicMock, engine: ToolExecutionEngine) -> None:
        """covers: execute_all dict paths unknown type (line 919-920)"""
        mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
        candidates = engine.execute_all({"unknown_type": ["src/module.py"]})
        assert mock_run.call_count == 0

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_dict_paths_category_not_in_config_skipped(
        self, mock_run: MagicMock, engine: ToolExecutionEngine
    ) -> None:
        """covers: execute_all dict paths category not in config (line 923)"""
        mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
        # "test" is in PATH_TYPE_TOOL_MAP["test"], but not in _tool_configs
        engine._tool_configs = {"lint": engine._tool_configs["lint"]}
        candidates = engine.execute_all({"test": ["tests/test_foo.py"]})
        assert mock_run.call_count == 0


# ---------------------------------------------------------------------------
# Test: _get_test_docstring
# ---------------------------------------------------------------------------

class TestGetTestDocstring:
    """Verify _get_test_docstring extracts docstrings via AST."""

    def test_extracts_function_docstring(self, engine: ToolExecutionEngine, project_root: Path) -> None:
        """covers: _get_test_docstring AST parsing (lines 955-990)"""
        test_file = project_root / "tests" / "test_sample.py"
        test_file.write_text(
            'def test_hello():\n    """covers: AC-VT-001-01"""\n    pass\n',
            encoding="utf-8",
        )
        result = engine._get_test_docstring("tests/test_sample.py::test_hello")
        assert result == "covers: AC-VT-001-01"

    def test_extracts_class_method_docstring(self, engine: ToolExecutionEngine, project_root: Path) -> None:
        """covers: _get_test_docstring class method (lines 970-987)"""
        test_file = project_root / "tests" / "test_sample.py"
        test_file.write_text(
            'class TestFoo:\n    def test_bar(self):\n        """Test doc"""\n        pass\n',
            encoding="utf-8",
        )
        result = engine._get_test_docstring("tests/test_sample.py::TestFoo::test_bar")
        assert result == "Test doc"

    def test_file_not_found_returns_none(self, engine: ToolExecutionEngine) -> None:
        """covers: _get_test_docstring file not found (line 963)"""
        result = engine._get_test_docstring("tests/nonexistent.py::test_foo")
        assert result is None

    def test_function_not_found_returns_none(self, engine: ToolExecutionEngine, project_root: Path) -> None:
        """covers: _get_test_docstring function not found (line 984)"""
        test_file = project_root / "tests" / "test_sample.py"
        test_file.write_text('def test_hello():\n    pass\n', encoding="utf-8")
        result = engine._get_test_docstring("tests/test_sample.py::test_nonexistent")
        assert result is None

    def test_no_docstring_returns_none(self, engine: ToolExecutionEngine, project_root: Path) -> None:
        """covers: _get_test_docstring no docstring (line 987)"""
        test_file = project_root / "tests" / "test_sample.py"
        test_file.write_text('def test_no_doc():\n    pass\n', encoding="utf-8")
        result = engine._get_test_docstring("tests/test_sample.py::test_no_doc")
        assert result is None

    def test_parametrized_test_name(self, engine: ToolExecutionEngine, project_root: Path) -> None:
        """covers: _get_test_docstring parametrized name split (line 971)"""
        test_file = project_root / "tests" / "test_sample.py"
        test_file.write_text(
            'def test_param():\n    """Parametrized doc"""\n    pass\n',
            encoding="utf-8",
        )
        result = engine._get_test_docstring("tests/test_sample.py::test_param[case1]")
        assert result == "Parametrized doc"

    def test_async_function_docstring(self, engine: ToolExecutionEngine, project_root: Path) -> None:
        """covers: _get_test_docstring async function (line 976)"""
        test_file = project_root / "tests" / "test_sample.py"
        test_file.write_text(
            'async def test_async():\n    """Async doc"""\n    pass\n',
            encoding="utf-8",
        )
        result = engine._get_test_docstring("tests/test_sample.py::test_async")
        assert result == "Async doc"


# ---------------------------------------------------------------------------
# Test: _extract_covers_from_docstring
# ---------------------------------------------------------------------------

class TestExtractCoversFromDocstring:
    """Verify _extract_covers_from_docstring handles various docstring formats."""

    def test_none_docstring(self, engine: ToolExecutionEngine) -> None:
        """covers: _extract_covers_from_docstring None input"""
        assert engine._extract_covers_from_docstring(None) == []

    def test_empty_docstring(self, engine: ToolExecutionEngine) -> None:
        """covers: _extract_covers_from_docstring empty string"""
        assert engine._extract_covers_from_docstring("") == []

    def test_no_covers_line(self, engine: ToolExecutionEngine) -> None:
        """covers: _extract_covers_from_docstring no covers keyword"""
        assert engine._extract_covers_from_docstring("This is a test doc") == []

    def test_covers_ac_id(self, engine: ToolExecutionEngine) -> None:
        """covers: _extract_covers_from_docstring AC ID extraction"""
        result = engine._extract_covers_from_docstring("covers: AC-VT-001-01")
        assert result == ["AC-VT-001-01"]

    def test_covers_req_id(self, engine: ToolExecutionEngine) -> None:
        """covers: _extract_covers_from_docstring REQ ID extraction"""
        result = engine._extract_covers_from_docstring("covers: REQ-VT-003")
        assert result == ["REQ-VT-003"]

    def test_duplicate_ids_deduplicated(self, engine: ToolExecutionEngine) -> None:
        """covers: _extract_covers_from_docstring dedup"""
        result = engine._extract_covers_from_docstring("covers: AC-VT-001-01\ncovers: AC-VT-001-01")
        assert result == ["AC-VT-001-01"]


# ---------------------------------------------------------------------------
# Test: _stamp_category
# ---------------------------------------------------------------------------

class TestStampCategory:
    """Verify _stamp_category stamps tool_category on candidates."""

    def test_stamps_category(self) -> None:
        """covers: _stamp_category (lines 623-630)"""
        c1 = ToolEvidenceCandidate(
            source_type="tool", source_path="src/", covers=[], status=CoverageStatus.COVERED.value
        )
        c2 = ToolEvidenceCandidate(
            source_type="tool", source_path="src/b.py", covers=[], status=CoverageStatus.COVERED.value
        )
        result = ToolExecutionEngine._stamp_category([c1, c2], "lint")
        assert all(c.tool_category == "lint" for c in result)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Test: get_tool_config
# ---------------------------------------------------------------------------

class TestGetToolConfig:
    """Verify get_tool_config returns correct configs."""

    def test_returns_config_for_whitelisted_tool(self, engine: ToolExecutionEngine) -> None:
        """covers: get_tool_config (line 146)"""
        config = engine.get_tool_config("lint")
        assert config is not None
        assert config["tool"] == "ruff"

    def test_returns_none_for_unknown_tool(self, engine: ToolExecutionEngine) -> None:
        """covers: get_tool_config (line 146)"""
        config = engine.get_tool_config("deploy")
        assert config is None


# ---------------------------------------------------------------------------
# Test: execute_tool auto-generates output_path
# ---------------------------------------------------------------------------

class TestAutoGenerateOutputPath:
    """Verify execute_tool auto-generates output_path when template needs it."""

    @patch("vibe_tracing.tool_evidence_adapter.subprocess.run")
    def test_auto_generates_output_path(
        self, mock_run: MagicMock, engine: ToolExecutionEngine, project_root: Path
    ) -> None:
        """covers: execute_tool auto-generate output_path (lines 702-707)"""
        mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
        engine._tool_configs["lint"] = {
            "tool": "ruff",
            "default_command": "ruff check {source_path} --output-file={output_path}",
            "output_format": "ruff_json",
            "pass_condition": "violations == 0",
        }
        candidates = engine.execute_tool(tool_category="lint", path="src/")
        # Check that the command was built (subprocess was called)
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        # output_path should have been auto-generated
        assert ".vibetracing/tmp/vt_lint_" in cmd
