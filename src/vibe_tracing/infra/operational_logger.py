"""
Operational logging for Vibe Tracing internals.

Records runtime telemetry (timing, exceptions, cache stats, subprocess
execution) in JSON Lines format for VT developers to debug and optimize
VT itself.  This is NOT user-facing output -- it never affects analysis
logic, gate decisions, or CLI output.

Constraints (LOG-VT-010 .. LOG-VT-015):
- Zero external dependencies (stdlib only).
- Must not change any existing print() output.
- Must not affect analysis logic or gate decisions.
- If logging init fails, analysis must continue without logging.
- Log files go to .vibetracing/logs/ (excluded from governance boundary).
"""

import json
import logging
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


class _JsonLinesFormatter(logging.Formatter):
    """Custom formatter that emits one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(record.msecs):03d}Z",
            "level": record.levelname,
            "event": getattr(record, "event", record.getMessage()),
            "run_id": getattr(record, "run_id", ""),
            "elapsed_ms": getattr(record, "elapsed_ms", 0),
            "message": record.getMessage(),
        }
        # Merge any extra fields stored on the record
        for key, value in getattr(record, "extra_fields", {}).items():
            entry[key] = value
        # Include exception info if present
        if record.exc_info and record.exc_info[1] is not None:
            entry["exception"] = "".join(traceback.format_exception(*record.exc_info))
        return json.dumps(entry, ensure_ascii=False, default=str)


class OperationalLogger:
    """Singleton operational logger for VT internals.

    Usage::

        OperationalLogger.init(run_id="RUN-001", project_root=Path("."))
        logger = OperationalLogger.get()
        logger.info("run_start", "Analysis pipeline started")
    """

    _instance: Optional["OperationalLogger"] = None

    def __init__(
        self,
        run_id: str,
        project_root: Path,
        level: str = "DEBUG",
    ) -> None:
        self._run_id = run_id
        self._start_time = time.monotonic()
        self._logger = logging.getLogger("vibe_tracing.operational")
        self._logger.setLevel(_LEVEL_MAP.get(level.upper(), logging.DEBUG))
        # Prevent propagation to root logger (never affect stderr/stdout)
        self._logger.propagate = False

        # Set up file handler
        logs_dir = project_root / ".vibetracing" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_path = logs_dir / f"vt-{ts}.jsonl"

        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(_JsonLinesFormatter())
        # Remove any existing handlers to avoid duplicates on re-init
        self._logger.handlers.clear()
        self._logger.addHandler(handler)
        self._log_path = log_path

    @classmethod
    def init(
        cls,
        run_id: str,
        project_root: Path,
        level: str = "DEBUG",
    ) -> "OperationalLogger":
        """Initialize (or re-initialize) the singleton logger.

        Returns the new instance.  Any failure is swallowed so analysis
        can continue without logging (LOG-VT-011).
        """
        try:
            instance = cls(run_id, project_root, level)
            cls._instance = instance
            return instance
        except Exception:
            # Never block analysis if logging fails
            class _NullLogger:
                """Fallback logger that silently discards everything."""
                _log_path = None
                def debug(self, event: str, message: str, **extra: Any) -> None: ...
                def info(self, event: str, message: str, **extra: Any) -> None: ...
                def warning(self, event: str, message: str, **extra: Any) -> None: ...
                def error(self, event: str, message: str, **extra: Any) -> None: ...
                def exception(self, event: str, message: str, exc: Exception = None, **extra: Any) -> None: ...
            cls._instance = _NullLogger()  # type: ignore[assignment]
            return cls._instance  # type: ignore[return-value]

    @classmethod
    def get(cls) -> "OperationalLogger":
        """Get the current logger instance.

        Returns a null logger if ``init()`` was never called.
        """
        if cls._instance is None:
            class _NullLogger:
                _log_path = None
                def debug(self, event: str, message: str, **extra: Any) -> None: ...
                def info(self, event: str, message: str, **extra: Any) -> None: ...
                def warning(self, event: str, message: str, **extra: Any) -> None: ...
                def error(self, event: str, message: str, **extra: Any) -> None: ...
                def exception(self, event: str, message: str, exc: Exception = None, **extra: Any) -> None: ...
            cls._instance = _NullLogger()  # type: ignore[assignment]
        return cls._instance  # type: ignore[return-value]

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing)."""
        cls._instance = None

    def _elapsed_ms(self) -> int:
        return int((time.monotonic() - self._start_time) * 1000)

    def _log(self, level: int, event: str, message: str, **extra: Any) -> None:
        if level < self._logger.getEffectiveLevel():
            return
        record = self._logger.makeRecord(
            name="vibe_tracing.operational",
            level=level,
            fn="",
            lno=0,
            msg=message,
            args=(),
            exc_info=None,
        )
        record.event = event  # type: ignore[attr-defined]
        record.run_id = self._run_id  # type: ignore[attr-defined]
        record.elapsed_ms = self._elapsed_ms()  # type: ignore[attr-defined]
        record.extra_fields = extra  # type: ignore[attr-defined]
        self._logger.handle(record)

    def debug(self, event: str, message: str, **extra: Any) -> None:
        """Log at DEBUG level."""
        self._log(logging.DEBUG, event, message, **extra)

    def info(self, event: str, message: str, **extra: Any) -> None:
        """Log at INFO level."""
        self._log(logging.INFO, event, message, **extra)

    def warning(self, event: str, message: str, **extra: Any) -> None:
        """Log at WARNING level."""
        self._log(logging.WARNING, event, message, **extra)

    def error(self, event: str, message: str, **extra: Any) -> None:
        """Log at ERROR level."""
        self._log(logging.ERROR, event, message, **extra)

    def exception(
        self, event: str, message: str, exc: Optional[Exception] = None, **extra: Any
    ) -> None:
        """Log an exception with traceback at ERROR level."""
        if logging.ERROR < self._logger.getEffectiveLevel():
            return
        if exc is None:
            import sys
            exc_info = sys.exc_info()
        else:
            exc_info = (type(exc), exc, exc.__traceback__)
        record = self._logger.makeRecord(
            name="vibe_tracing.operational",
            level=logging.ERROR,
            fn="",
            lno=0,
            msg=message,
            args=(),
            exc_info=exc_info,
        )
        record.event = event  # type: ignore[attr-defined]
        record.run_id = self._run_id  # type: ignore[attr-defined]
        record.elapsed_ms = self._elapsed_ms()  # type: ignore[attr-defined]
        record.extra_fields = extra  # type: ignore[attr-defined]
        self._logger.handle(record)
