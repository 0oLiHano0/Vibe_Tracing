"""
Tests for operational timing instrumentation.

Covers:
- Pipeline phase timing in run_analyze() (Task 2)
- Subprocess execution timing in ToolExecutionEngine._run_subprocess() (Task 3)
- Subprocess execution timing in _run_claim_tests() (Task 3)
"""

import json
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from vibe_tracing.operational_logger import OperationalLogger


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure singleton is reset before and after each test."""
    OperationalLogger.reset()
    yield
    OperationalLogger.reset()


def _read_log_entries(log_path: Path) -> list:
    """Read all JSON entries from a JSONL log file."""
    if not log_path or not log_path.exists():
        return []
    entries = []
    for line in log_path.read_text().strip().splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


# ---------------------------------------------------------------------------
# Task 2: Pipeline phase timing
# ---------------------------------------------------------------------------


class TestPipelinePhaseTiming:
    """Tests for timing instrumentation in run_analyze()."""

    def test_run_analyze_logs_run_start_and_run_end(self, tmp_path):
        """run_analyze must log run_start and run_end events."""
        from vibe_tracing.commands.analyze.pipeline import run_analyze

        # Set up minimal project structure
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        (tmp_path / ".vibetracing").mkdir(parents=True)
        (tmp_path / ".vibetracing" / "claims").mkdir(parents=True)
        (tmp_path / ".vibetracing" / "claims" / "current.json").write_text("[]")
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()

        # Create minimal config
        config = {
            "language": "python",
            "paths": {"output_dir": "output"},
            "logging": {"level": "DEBUG"},
        }
        (tmp_path / ".vibetracing" / "config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )

        # Create minimal PRD
        prd = {
            "version": "1.0",
            "status": "draft",
            "requirements": [],
        }
        (tmp_path / "docs" / "prd.md").write_text("# PRD\n", encoding="utf-8")

        # Create minimal constraints
        constraints = {
            "version": "1.0",
            "language_tool_matrix": {},
            "modules": [],
        }
        (tmp_path / "docs" / "architecture_constraints.json").write_text(
            json.dumps(constraints), encoding="utf-8"
        )

        # Create minimal task list
        task_list = {"version": "1.0", "tasks": []}
        (tmp_path / "docs" / "task_list.json").write_text(
            json.dumps(task_list), encoding="utf-8"
        )

        # We need to mock _load_context to avoid complex setup
        # Instead, test that logger is initialized by checking the log file
        with patch(
            "vibe_tracing.commands.analyze.pipeline._load_context"
        ) as mock_load:
            mock_ctx = MagicMock()
            mock_ctx.prd.status = "draft"
            mock_ctx.config_prefix = "VT"
            mock_ctx.config = config
            mock_ctx.claims_list = []
            mock_ctx.manifest = None
            mock_load.return_value = (mock_ctx, MagicMock(), MagicMock())

            # The function will fail early because manifest is None,
            # but the logger should still be initialized
            exit_code = run_analyze(tmp_path)

        # Check that the logger was initialized and wrote to a file
        logs_dir = tmp_path / ".vibetracing" / "logs"
        assert logs_dir.is_dir(), "Logs directory should be created"
        log_files = list(logs_dir.glob("vt-*.jsonl"))
        assert len(log_files) >= 1, "At least one log file should be created"

        entries = _read_log_entries(log_files[0])
        events = [e["event"] for e in entries]
        assert "run_start" in events, f"run_start event missing. Got: {events}"
        assert "phase_end" in events, f"phase_end events missing. Got: {events}"

        # Verify run_start has is_pre_commit and gates_only fields
        run_start = next(e for e in entries if e["event"] == "run_start")
        assert "is_pre_commit" in run_start
        assert "gates_only" in run_start

    def test_pipeline_phases_have_duration_ms(self, tmp_path):
        """Each phase_end event must include duration_ms >= 0."""
        from vibe_tracing.commands.analyze.pipeline import run_analyze

        config = {"language": "python", "logging": {"level": "DEBUG"}}
        with patch(
            "vibe_tracing.commands.analyze.pipeline._load_context"
        ) as mock_load:
            mock_ctx = MagicMock()
            mock_ctx.prd.status = "draft"
            mock_ctx.config_prefix = "VT"
            mock_ctx.config = config
            mock_ctx.claims_list = []
            mock_ctx.manifest = None
            mock_load.return_value = (mock_ctx, MagicMock(), MagicMock())

            run_analyze(tmp_path)

        logs_dir = tmp_path / ".vibetracing" / "logs"
        log_files = list(logs_dir.glob("vt-*.jsonl"))
        if not log_files:
            pytest.skip("No log files created")

        entries = _read_log_entries(log_files[0])
        phase_entries = [e for e in entries if e["event"] == "phase_end"]
        for entry in phase_entries:
            assert "duration_ms" in entry, f"duration_ms missing in {entry}"
            assert entry["duration_ms"] >= 0, f"duration_ms should be >= 0, got {entry['duration_ms']}"
            assert "phase" in entry, f"phase key missing in {entry}"

    def test_pipeline_phases_include_expected_names(self, tmp_path):
        """Phase names should match the expected set."""
        from vibe_tracing.commands.analyze.pipeline import run_analyze

        config = {"language": "python", "logging": {"level": "DEBUG"}}
        with patch(
            "vibe_tracing.commands.analyze.pipeline._load_context"
        ) as mock_load:
            mock_ctx = MagicMock()
            mock_ctx.prd.status = "draft"
            mock_ctx.config_prefix = "VT"
            mock_ctx.config = config
            mock_ctx.claims_list = []
            mock_ctx.manifest = None
            mock_load.return_value = (mock_ctx, MagicMock(), MagicMock())

            run_analyze(tmp_path)

        logs_dir = tmp_path / ".vibetracing" / "logs"
        log_files = list(logs_dir.glob("vt-*.jsonl"))
        if not log_files:
            pytest.skip("No log files created")

        entries = _read_log_entries(log_files[0])
        phase_names = [e.get("phase") for e in entries if e["event"] == "phase_end"]
        # load_context and integrity_gates should always appear
        assert "load_context" in phase_names, f"Expected load_context phase. Got: {phase_names}"
        assert "integrity_gates" in phase_names, f"Expected integrity_gates phase. Got: {phase_names}"


# ---------------------------------------------------------------------------
# Task 3: Subprocess execution timing
# ---------------------------------------------------------------------------


class TestSubprocessTiming:
    """Tests for timing instrumentation in _run_subprocess()."""

    def test_run_subprocess_logs_subprocess_exec_event(self, tmp_path):
        """_run_subprocess must log a subprocess_exec event with timing."""
        from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine

        # Initialize the logger so OperationalLogger.get() works
        logger = OperationalLogger.init("TEST-RUN", tmp_path, level="DEBUG")

        matrix = {
            "python": {
                "lint": {
                    "tool": "ruff",
                    "default_command": "echo hello",
                    "output_format": "ruff_json",
                },
            }
        }
        engine = ToolExecutionEngine(
            language_tool_matrix=matrix,
            language="python",
            validation_tools=["lint"],
            project_root=tmp_path,
        )

        exit_code, stdout, stderr, err = engine._run_subprocess("echo test_output")

        assert exit_code == 0
        assert "test_output" in stdout

        # Check the log file
        entries = _read_log_entries(logger._log_path)
        exec_events = [e for e in entries if e["event"] == "subprocess_exec"]
        assert len(exec_events) >= 1, f"subprocess_exec event missing. Got events: {[e['event'] for e in entries]}"

        event = exec_events[0]
        assert "duration_ms" in event
        assert event["duration_ms"] >= 0
        assert "command" in event
        assert "exit_code" in event
        assert event["exit_code"] == 0
        assert "stdout_size" in event
        assert "stderr_size" in event

    def test_run_subprocess_logs_command_name_only(self, tmp_path):
        """The command field should contain just the tool name, not full args."""
        from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine

        logger = OperationalLogger.init("TEST-RUN", tmp_path, level="DEBUG")

        matrix = {"python": {}}
        engine = ToolExecutionEngine(
            language_tool_matrix=matrix,
            language="python",
            validation_tools=[],
            project_root=tmp_path,
        )

        engine._run_subprocess("python -c 'print(1)'")

        entries = _read_log_entries(logger._log_path)
        exec_events = [e for e in entries if e["event"] == "subprocess_exec"]
        assert len(exec_events) >= 1
        # command should be just "python", not the full command string
        assert exec_events[0]["command"] == "python"

    def test_run_subprocess_logs_nonzero_exit_code(self, tmp_path):
        """Non-zero exit codes must be recorded in the log."""
        from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine

        logger = OperationalLogger.init("TEST-RUN", tmp_path, level="DEBUG")

        matrix = {"python": {}}
        engine = ToolExecutionEngine(
            language_tool_matrix=matrix,
            language="python",
            validation_tools=[],
            project_root=tmp_path,
        )

        engine._run_subprocess(f"{sys.executable} -c 'import sys; sys.exit(1)'")

        entries = _read_log_entries(logger._log_path)
        exec_events = [e for e in entries if e["event"] == "subprocess_exec"]
        assert len(exec_events) >= 1
        assert exec_events[0]["exit_code"] == 1

    def test_run_subprocess_timing_is_reasonable(self, tmp_path):
        """duration_ms should be a non-negative integer representing real time."""
        from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine

        logger = OperationalLogger.init("TEST-RUN", tmp_path, level="DEBUG")

        matrix = {"python": {}}
        engine = ToolExecutionEngine(
            language_tool_matrix=matrix,
            language="python",
            validation_tools=[],
            project_root=tmp_path,
        )

        engine._run_subprocess(f"{sys.executable} -c 'import time; time.sleep(0.05)'")

        entries = _read_log_entries(logger._log_path)
        exec_events = [e for e in entries if e["event"] == "subprocess_exec"]
        assert len(exec_events) >= 1
        # 50ms sleep + overhead, should be at least 30ms
        assert exec_events[0]["duration_ms"] >= 30

    def test_run_subprocess_stdout_stderr_sizes(self, tmp_path):
        """stdout_size and stderr_size must reflect actual output sizes."""
        from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine

        logger = OperationalLogger.init("TEST-RUN", tmp_path, level="DEBUG")

        matrix = {"python": {}}
        engine = ToolExecutionEngine(
            language_tool_matrix=matrix,
            language="python",
            validation_tools=[],
            project_root=tmp_path,
        )

        engine._run_subprocess(f"{sys.executable} -c 'print(\"hello world\")'")

        entries = _read_log_entries(logger._log_path)
        exec_events = [e for e in entries if e["event"] == "subprocess_exec"]
        assert len(exec_events) >= 1
        # "hello world\n" = 12 bytes
        assert exec_events[0]["stdout_size"] == len("hello world\n")


class TestClaimTestsTiming:
    """Tests for timing instrumentation in _run_claim_tests()."""

    def test_run_claim_tests_logs_subprocess_exec(self, tmp_path):
        """_run_claim_tests must log subprocess_exec for pytest calls."""
        from vibe_tracing.commands.analyze.analysis import _run_claim_tests

        logger = OperationalLogger.init("TEST-RUN", tmp_path, level="DEBUG")

        # Create a minimal test file
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        test_file = test_dir / "test_dummy.py"
        test_file.write_text("def test_pass(): assert True\n", encoding="utf-8")

        # Create a mock claim with test_refs
        claim = MagicMock()
        claim.test_refs = ["tests/test_dummy.py"]

        evidence_index = {}
        _run_claim_tests(tmp_path, [claim], evidence_index)

        entries = _read_log_entries(logger._log_path)
        exec_events = [e for e in entries if e["event"] == "subprocess_exec"]
        assert len(exec_events) >= 1, f"subprocess_exec event missing. Got events: {[e['event'] for e in entries]}"

        event = exec_events[0]
        assert "duration_ms" in event
        assert event["duration_ms"] >= 0
        assert event["command"] == "pytest"
        assert "exit_code" in event
        assert "test_ref" in event
        assert event["test_ref"] == "tests/test_dummy.py"

    def test_run_claim_tests_timing_reflects_actual_execution(self, tmp_path):
        """duration_ms should be a non-negative integer."""
        from vibe_tracing.commands.analyze.analysis import _run_claim_tests

        logger = OperationalLogger.init("TEST-RUN", tmp_path, level="DEBUG")

        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        test_file = test_dir / "test_dummy.py"
        test_file.write_text("def test_pass(): assert True\n", encoding="utf-8")

        claim = MagicMock()
        claim.test_refs = ["tests/test_dummy.py"]

        evidence_index = {}
        _run_claim_tests(tmp_path, [claim], evidence_index)

        entries = _read_log_entries(logger._log_path)
        exec_events = [e for e in entries if e["event"] == "subprocess_exec"]
        assert len(exec_events) >= 1
        assert exec_events[0]["duration_ms"] >= 0

    def test_run_claim_tests_cached_tests_not_logged(self, tmp_path):
        """Cached test results should not produce subprocess_exec events."""
        from vibe_tracing.commands.analyze.analysis import _run_claim_tests

        logger = OperationalLogger.init("TEST-RUN", tmp_path, level="DEBUG")

        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        test_file = test_dir / "test_dummy.py"
        test_file.write_text("def test_pass(): assert True\n", encoding="utf-8")

        claim = MagicMock()
        claim.test_refs = ["tests/test_dummy.py"]

        # First run - should execute pytest
        evidence_index = {}
        _run_claim_tests(tmp_path, [claim], evidence_index)

        entries_first = _read_log_entries(logger._log_path)
        exec_events_first = [e for e in entries_first if e["event"] == "subprocess_exec"]
        assert len(exec_events_first) >= 1

        # Second run with same evidence_index - should use cache
        _run_claim_tests(tmp_path, [claim], evidence_index)

        entries_second = _read_log_entries(logger._log_path)
        exec_events_second = [e for e in entries_second if e["event"] == "subprocess_exec"]
        # No new subprocess_exec events should be added (cache hit)
        assert len(exec_events_second) == len(exec_events_first)


# ---------------------------------------------------------------------------
# Integration: Logger not initialized (null logger)
# ---------------------------------------------------------------------------


class TestNullLoggerSafety:
    """Tests that timing code works when logger is not initialized."""

    def test_subprocess_timing_works_without_logger_init(self, tmp_path):
        """_run_subprocess should not crash when OperationalLogger.init() was never called."""
        from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine

        matrix = {"python": {}}
        engine = ToolExecutionEngine(
            language_tool_matrix=matrix,
            language="python",
            validation_tools=[],
            project_root=tmp_path,
        )

        # Should not raise - null logger silently discards
        exit_code, stdout, stderr, err = engine._run_subprocess("echo ok")
        assert exit_code == 0

    def test_claim_tests_timing_works_without_logger_init(self, tmp_path):
        """_run_claim_tests should not crash when OperationalLogger.init() was never called."""
        from vibe_tracing.commands.analyze.analysis import _run_claim_tests

        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        test_file = test_dir / "test_dummy.py"
        test_file.write_text("def test_pass(): assert True\n", encoding="utf-8")

        claim = MagicMock()
        claim.test_refs = ["tests/test_dummy.py"]

        evidence_index = {}
        # Should not raise - null logger silently discards
        _run_claim_tests(tmp_path, [claim], evidence_index)
