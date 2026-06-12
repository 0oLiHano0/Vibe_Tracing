"""Tests for vibe_tracing.operational_logger."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from vibe_tracing.operational_logger import OperationalLogger, _JsonLinesFormatter


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure singleton is reset before and after each test."""
    OperationalLogger.reset()
    yield
    OperationalLogger.reset()


class TestJsonLinesFormatter:
    """Tests for _JsonLinesFormatter."""

    def test_produces_valid_json_with_required_fields(self):
        """Formatter output must be valid JSON with all required fields."""
        import logging

        formatter = _JsonLinesFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        record.event = "test_event"
        record.run_id = "RUN-001"
        record.elapsed_ms = 42
        record.extra_fields = {}

        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "INFO"
        assert data["event"] == "test_event"
        assert data["run_id"] == "RUN-001"
        assert data["elapsed_ms"] == 42
        assert data["message"] == "hello"
        assert "timestamp" in data
        # ISO 8601 with ms
        assert data["timestamp"].endswith("Z")
        assert "T" in data["timestamp"]

    def test_extra_fields_included(self):
        """Extra fields from record.extra_fields must appear in output."""
        import logging

        formatter = _JsonLinesFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="msg",
            args=(),
            exc_info=None,
        )
        record.event = "e"
        record.run_id = "R"
        record.elapsed_ms = 0
        record.extra_fields = {"tool": "pytest", "duration_ms": 150}

        output = formatter.format(record)
        data = json.loads(output)

        assert data["tool"] == "pytest"
        assert data["duration_ms"] == 150

    def test_exception_includes_traceback(self):
        """Exception info must be rendered as a traceback string."""
        import logging

        formatter = _JsonLinesFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="failed",
            args=(),
            exc_info=exc_info,
        )
        record.event = "error"
        record.run_id = "R"
        record.elapsed_ms = 0
        record.extra_fields = {}

        output = formatter.format(record)
        data = json.loads(output)

        assert "exception" in data
        assert "ValueError: boom" in data["exception"]


class TestOperationalLogger:
    """Tests for OperationalLogger class."""

    def test_init_creates_log_directory_and_file(self, tmp_path):
        """init() must create .vibetracing/logs/ and a .jsonl file."""
        logger = OperationalLogger.init("RUN-001", tmp_path)
        logs_dir = tmp_path / ".vibetracing" / "logs"
        assert logs_dir.is_dir()
        assert logger._log_path.exists()
        assert logger._log_path.suffix == ".jsonl"
        assert logger._log_path.name.startswith("vt-")

    def test_log_level_filtering_debug_shows_all(self, tmp_path):
        """DEBUG level must capture all messages including debug."""
        logger = OperationalLogger.init("RUN-001", tmp_path, level="DEBUG")
        logger.debug("d_event", "debug msg")
        logger.info("i_event", "info msg")
        logger.warning("w_event", "warn msg")
        logger.error("e_event", "error msg")

        lines = logger._log_path.read_text().strip().splitlines()
        events = [json.loads(line)["event"] for line in lines]
        assert events == ["d_event", "i_event", "w_event", "e_event"]

    def test_log_level_filtering_info_hides_debug(self, tmp_path):
        """INFO level must suppress DEBUG messages."""
        logger = OperationalLogger.init("RUN-001", tmp_path, level="INFO")
        logger.debug("d_event", "debug msg")
        logger.info("i_event", "info msg")
        logger.error("e_event", "error msg")

        lines = logger._log_path.read_text().strip().splitlines()
        events = [json.loads(line)["event"] for line in lines]
        assert "d_event" not in events
        assert "i_event" in events
        assert "e_event" in events

    def test_elapsed_ms_increases(self, tmp_path):
        """elapsed_ms should be non-negative and later entries >= earlier."""
        import time

        logger = OperationalLogger.init("RUN-001", tmp_path)
        logger.info("first", "first msg")
        time.sleep(0.01)
        logger.info("second", "second msg")

        lines = logger._log_path.read_text().strip().splitlines()
        first = json.loads(lines[0])["elapsed_ms"]
        second = json.loads(lines[1])["elapsed_ms"]
        assert first >= 0
        assert second >= first

    def test_extra_fields_in_log_output(self, tmp_path):
        """Extra kwargs must appear in the JSON output."""
        logger = OperationalLogger.init("RUN-001", tmp_path)
        logger.info("tool_run", "executed pytest", tool="pytest", returncode=0)

        line = logger._log_path.read_text().strip()
        data = json.loads(line)
        assert data["tool"] == "pytest"
        assert data["returncode"] == 0

    def test_exception_logging_includes_traceback(self, tmp_path):
        """exception() must write traceback to log file."""
        logger = OperationalLogger.init("RUN-001", tmp_path)
        try:
            raise RuntimeError("test error")
        except RuntimeError as e:
            logger.exception("caught", "An error occurred", exc=e)

        line = logger._log_path.read_text().strip()
        data = json.loads(line)
        assert "exception" in data
        assert "RuntimeError: test error" in data["exception"]

    def test_exception_logging_no_exc_uses_sys(self, tmp_path):
        """exception() with no exc arg uses current sys.exc_info()."""
        logger = OperationalLogger.init("RUN-001", tmp_path)
        try:
            raise KeyError("missing")
        except KeyError:
            logger.exception("auto_exc", "Auto exception")

        line = logger._log_path.read_text().strip()
        data = json.loads(line)
        assert "exception" in data
        assert "KeyError" in data["exception"]

    def test_get_returns_same_instance(self, tmp_path):
        """get() must return the instance created by init()."""
        inst = OperationalLogger.init("RUN-001", tmp_path)
        assert OperationalLogger.get() is inst

    def test_get_without_init_returns_null_logger(self):
        """get() before init() must return a null logger (no crash)."""
        logger = OperationalLogger.get()
        # These must not raise
        logger.info("e", "m")
        logger.debug("e", "m")
        logger.warning("e", "m")
        logger.error("e", "m")
        logger.exception("e", "m")

    def test_init_failure_does_not_block(self, tmp_path, monkeypatch):
        """If log directory creation fails, init() must return a null logger."""
        # Make the tmp_path read-only for directory creation
        monkeypatch.setattr(
            "vibe_tracing.operational_logger.Path.mkdir",
            lambda *a, **kw: (_ for _ in ()).throw(PermissionError("no")),
        )
        logger = OperationalLogger.init("RUN-001", tmp_path)
        # Must not raise
        logger.info("e", "m")

    def test_json_output_is_valid_jsonl(self, tmp_path):
        """Every line in the log file must be independently parseable JSON."""
        logger = OperationalLogger.init("RUN-001", tmp_path)
        logger.info("a", "msg a")
        logger.warning("b", "msg b")
        logger.error("c", "msg c")

        lines = logger._log_path.read_text().strip().splitlines()
        assert len(lines) == 3
        for line in lines:
            data = json.loads(line)  # must not raise
            assert "timestamp" in data
            assert "level" in data
            assert "event" in data
            assert "run_id" in data
            assert "elapsed_ms" in data
            assert "message" in data

    def test_run_id_in_every_entry(self, tmp_path):
        """Every log entry must contain the run_id."""
        logger = OperationalLogger.init("MY-RUN-42", tmp_path)
        logger.info("e", "m")
        logger.debug("e2", "m2")

        lines = logger._log_path.read_text().strip().splitlines()
        for line in lines:
            assert json.loads(line)["run_id"] == "MY-RUN-42"

    def test_init_with_config_level(self, tmp_path):
        """Level from config.json should be respected."""
        # Simulate config-driven init
        logger = OperationalLogger.init("RUN-001", tmp_path, level="WARNING")
        logger.debug("d", "debug")
        logger.info("i", "info")
        logger.warning("w", "warn")

        lines = logger._log_path.read_text().strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["event"] == "w"
