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

# Each entry: (prefix, compiled_pattern)
# Order matters: more specific patterns (two-segment digits) before simpler ones.
_ID_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AC", re.compile(r"^AC-VT-\d+-\d+$")),
    ("DOD", re.compile(r"^DOD-VT-\d+-\d+$")),
    ("REQ", re.compile(r"^REQ-VT-\d+$")),
    ("TASK", re.compile(r"^TASK-VT-\d+$")),
    ("MOD", re.compile(r"^MOD-VT-\d+$")),
    ("GATE", re.compile(r"^GATE-VT-\d+$")),
    ("FORBID", re.compile(r"^FORBID-VT-\d+$")),
    ("PRINCIPLE", re.compile(r"^PRINCIPLE-VT-\d+$")),
    ("PHASE", re.compile(r"^PHASE-VT-\d+$")),
    ("PROJECT", re.compile(r"^PROJECT-VT$")),
    ("EVIDENCE", re.compile(r"^EVIDENCE-VT-\d+$")),
    ("RISK", re.compile(r"^RISK-VT-\d+$")),
    ("CLAIM", re.compile(r"^CLAIM-VT-\d+$")),
]

_VALID_PREFIXES = [prefix for prefix, _ in _ID_PATTERNS]


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
