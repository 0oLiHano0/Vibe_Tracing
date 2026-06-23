"""Config package for Vibe Tracing."""

from vibe_tracing.infra.config.enums import CoverageStatus, ErrorCode
from vibe_tracing.infra.config.hint_loader import load_hints, resolve_hint

__all__ = ["CoverageStatus", "ErrorCode", "load_hints", "resolve_hint"]
