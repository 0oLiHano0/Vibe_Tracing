"""
ID validation utilities for Vibe Tracing.

Supports the following ID formats:
  REQ-VT-\\d+         e.g. REQ-VT-001
  AC-VT-\\d+-\\d+     e.g. AC-VT-001-01
  TASK-VT-\\d+        e.g. TASK-VT-001
  DOD-VT-\\d+-\\d+    e.g. DOD-VT-001-01
  MOD-VT-\\d+         e.g. MOD-VT-001
  GATE-VT-\\d+        e.g. GATE-VT-001
  FORBID-VT-\\d+      e.g. FORBID-VT-001
  PRINCIPLE-VT-\\d+   e.g. PRINCIPLE-VT-001
  PHASE-VT-\\d+       e.g. PHASE-VT-001
  PROJECT-VT          exact match
  EVIDENCE-VT-\\d+    e.g. EVIDENCE-VT-001
  RISK-VT-\\d+        e.g. RISK-VT-001
  CLAIM-VT-\\d+       e.g. CLAIM-VT-001
"""

import re
from typing import Tuple

active_prefix = "VT"

# Each entry: (prefix, compiled_pattern)
# Order matters: more specific patterns (two-segment digits) before simpler ones.
_ID_PATTERNS: list[tuple[str, re.Pattern[str]]] = []
_VALID_PREFIXES: list[str] = []

def _rebuild_patterns(prefix: str):
    global _ID_PATTERNS, _VALID_PREFIXES
    _ID_PATTERNS.clear()
    _ID_PATTERNS.extend([
        ("AC", re.compile(rf"^AC-{prefix}-\d+-\d+$")),
        ("DOD", re.compile(rf"^DOD-{prefix}-\d+-\d+$")),
        ("REQ", re.compile(rf"^REQ-{prefix}-\d+$")),
        ("TASK", re.compile(rf"^TASK-{prefix}-\d+$")),
        ("MOD", re.compile(rf"^MOD-{prefix}-\d+$")),
        ("GATE", re.compile(rf"^GATE-{prefix}-\d+$")),
        ("FORBID", re.compile(rf"^FORBID-{prefix}-\d+$")),
        ("PRINCIPLE", re.compile(rf"^PRINCIPLE-{prefix}-\d+$")),
        ("PHASE", re.compile(rf"^PHASE-{prefix}-\d+$")),
        ("PROJECT", re.compile(rf"^PROJECT-{prefix}$")),
        ("EVIDENCE", re.compile(rf"^EVIDENCE-{prefix}-\d+$")),
        ("RISK", re.compile(rf"^RISK-{prefix}-\d+$")),
        ("CLAIM", re.compile(rf"^CLAIM-{prefix}-\d+$")),
    ])
    _VALID_PREFIXES.clear()
    _VALID_PREFIXES.extend([prefix for prefix, _ in _ID_PATTERNS])

_rebuild_patterns(active_prefix)

def set_project_prefix(prefix: str):
    """Set the active project prefix and rebuild regex patterns."""
    global active_prefix
    active_prefix = prefix
    _rebuild_patterns(prefix)


def get_project_prefix() -> str:
    """Return the active project prefix."""
    return active_prefix


def make_risk_id(counter: int) -> str:
    """Generate a risk ID using the active prefix."""
    return f"RISK-{get_project_prefix()}-{counter:03d}"


def make_evidence_id(counter: int) -> str:
    """Generate an evidence ID using the active prefix."""
    return f"EVIDENCE-{get_project_prefix()}-{counter:03d}"


def sentinel_evidence_id() -> str:
    """Return the sentinel evidence ID for 'no real evidence' cases."""
    return f"EVIDENCE-{get_project_prefix()}-999"


def validate_id(id_str: str) -> Tuple[bool, str]:
    """Validate a Vibe Tracing ID string.

    Args:
        id_str: The ID string to validate.

    Returns:
        A tuple (is_valid, error_message).
        On success: (True, "")
        On failure: (False, "<clear error message>")
    """
    if not isinstance(id_str, str):
        return (False, f"ID must be a string, got {type(id_str).__name__!r}")

    stripped = id_str.strip()
    if not stripped:
        return (False, "ID must not be empty or blank")

    for _prefix, pattern in _ID_PATTERNS:
        if pattern.match(stripped):
            return (True, "")

    # Produce a helpful error message based on partial prefix match
    prefix_part = stripped.split("-")[0] if "-" in stripped else stripped
    if prefix_part in _VALID_PREFIXES or stripped.startswith("PROJECT"):
        return (
            False,
            f"ID {stripped!r} has a recognised prefix but does not match the "
            f"expected format for that type. "
            f"Valid prefixes: {', '.join(_VALID_PREFIXES)}",
        )

    return (
        False,
        f"ID {stripped!r} does not match any known Vibe Tracing ID format. "
        f"Valid prefixes: {', '.join(_VALID_PREFIXES)}",
    )


def get_id_type(id_str: str) -> str:
    """Return the type prefix of a valid Vibe Tracing ID.

    Args:
        id_str: The ID string to inspect.

    Returns:
        The type prefix string, e.g. "REQ", "AC", "TASK", etc.

    Raises:
        ValueError: If the ID does not match any known format.
    """
    if not isinstance(id_str, str):
        raise ValueError(f"ID must be a string, got {type(id_str).__name__!r}")

    stripped = id_str.strip()
    for prefix, pattern in _ID_PATTERNS:
        if pattern.match(stripped):
            return prefix

    raise ValueError(
        f"Unknown ID format: {stripped!r}. Valid prefixes: {', '.join(_VALID_PREFIXES)}"
    )
