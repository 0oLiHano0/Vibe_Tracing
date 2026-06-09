"""
Unified hint loading module for Vibe Tracing.

Provides a single source of truth for loading and resolving field hints
from ``templates/field_hints.json``, eliminating duplicated logic across
multiple modules.
"""

import json
from pathlib import Path
from typing import Any, Dict

_HINTS_PATH = Path(__file__).parent / "templates" / "field_hints.json"

_cache: Dict[str, Dict[str, Any]] = {}


def load_hints(category: str) -> Dict[str, Any]:
    """Load hints for *category* from ``templates/field_hints.json``.

    Results are cached at module level so repeated calls for the same
    category do not re-read the file.

    Args:
        category: Top-level key in the JSON file (e.g. ``"gate_decision"``,
            ``"risk"``, ``"compliance"``, ``"input"``).

    Returns:
        A dict of hint entries for the requested category, or an empty
        dict if the file or category cannot be found.
    """
    if category in _cache:
        return _cache[category]
    try:
        data = json.loads(_HINTS_PATH.read_text(encoding="utf-8"))
        result = data.get(category, {})
    except (FileNotFoundError, json.JSONDecodeError):
        result = {}
    _cache[category] = result
    return result


def resolve_hint(hint_value: Any, level: str = "level1") -> str:
    """Resolve a hint value to a human-readable string at the given level.

    Backward compatible: if *hint_value* is a plain string, it is returned
    directly.  If it is a dict (multi-level hint), the entry for *level* is
    returned, falling back to ``"level1"`` if the requested level is absent.

    Args:
        hint_value: Either a plain string or a dict with level keys.
        level: The verbosity level to resolve (default ``"level1"``).

    Returns:
        The resolved hint string, or ``""`` if resolution fails.
    """
    if isinstance(hint_value, str):
        return hint_value
    if isinstance(hint_value, dict):
        return hint_value.get(level, hint_value.get("level1", ""))
    return ""
