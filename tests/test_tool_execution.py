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
