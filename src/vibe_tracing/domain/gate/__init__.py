"""Gate package for Vibe Tracing."""

from vibe_tracing.domain.gate.engine import MergeGateEngine
from vibe_tracing.domain.gate.staleness import mark_staleness

__all__ = ["MergeGateEngine", "mark_staleness"]
