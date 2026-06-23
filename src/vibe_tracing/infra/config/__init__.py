"""Config package for Vibe Tracing."""

from vibe_tracing.infra.config.enums import CoverageStatus, ErrorCode
from vibe_tracing.infra.config.hint_loader import load_hints, resolve_hint
from vibe_tracing.infra.config.boundary import load_boundary, is_in_scope, partition_by_scope

__all__ = [
    "CoverageStatus",
    "ErrorCode",
    "load_hints",
    "resolve_hint",
    "load_boundary",
    "is_in_scope",
    "partition_by_scope",
]
