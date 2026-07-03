"""Gate package for Vibe Tracing."""

from vibe_tracing.domain.gate.engine import MergeGateEngine
from vibe_tracing.domain.gate.baseline import BaselineManager, compute_fingerprint
from vibe_tracing.domain.gate.signal_computer import SignalComputer
from vibe_tracing.domain.gate.types import (
    DetectedIssue, IssueSignal, Severity, OutputState, GateAction,
    F, state_to_gate_action, aggregate_gate_decision,
)
from vibe_tracing.domain.gate.staleness import mark_staleness, determine_affected_items

__all__ = [
    "MergeGateEngine", "BaselineManager", "compute_fingerprint", "SignalComputer",
    "DetectedIssue", "IssueSignal", "Severity", "OutputState", "GateAction",
    "F", "state_to_gate_action", "aggregate_gate_decision",
    "mark_staleness", "determine_affected_items",
]
