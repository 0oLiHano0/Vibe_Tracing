"""Governance boundary module.

Pure-function module for determining which files fall within the project's
governance scope.  Reads ``governance_boundary`` from
``docs/architecture_constraints.json`` and applies glob-based include/exclude
matching using :func:`fnmatch.fnmatch`.

This module has no dependency on CLI, ghost-code reconciler, or any other VT
core module.
"""

import fnmatch
import json
from pathlib import Path
from typing import Dict, List, Optional


_DEFAULT_BOUNDARY: Dict[str, list] = {
    "included_patterns": [],
    "excluded_patterns": [],
}


def load_boundary(
    project_root: Path,
    constraints_data: Optional[dict] = None,
) -> dict:
    """Load ``governance_boundary`` from architecture_constraints.json.

    If *constraints_data* is provided (the already-parsed dict), the file is
    **not** re-read from disk.  Returns a dict with ``included_patterns`` and
    ``excluded_patterns`` keys (both defaulting to empty lists on any error).
    """
    if constraints_data is not None:
        return constraints_data.get("governance_boundary", dict(_DEFAULT_BOUNDARY))

    constraints_path = project_root / "docs" / "architecture_constraints.json"
    if not constraints_path.exists():
        return dict(_DEFAULT_BOUNDARY)
    try:
        data = json.loads(constraints_path.read_text(encoding="utf-8"))
        return data.get("governance_boundary", dict(_DEFAULT_BOUNDARY))
    except Exception:
        return dict(_DEFAULT_BOUNDARY)


def is_in_scope(filepath: str, boundary: dict) -> bool:
    """Check whether *filepath* is within the governance boundary.

    A file is **in scope** when:

    1. ``included_patterns`` is empty (meaning "include everything") **or**
       the file matches at least one included pattern.
    2. The file does **not** match any ``excluded_patterns`` entry.

    Both included and excluded patterns use :mod:`fnmatch` glob syntax and are
    tested against the path as-is **and** with a ``*/`` prefix so that
    bare patterns like ``vendor/**`` also match paths such as
    ``src/vendor/lib.js``.
    """
    included = boundary.get("included_patterns", [])
    excluded = boundary.get("excluded_patterns", [])

    # Inclusion check: if the list is non-empty the file must match at least one.
    if included:
        matched_any = False
        for pattern in included:
            if fnmatch.fnmatch(filepath, pattern) or fnmatch.fnmatch(filepath, f"*/{pattern}"):
                matched_any = True
                break
        if not matched_any:
            return False

    # Exclusion check: any match means out of scope.
    for pattern in excluded:
        if fnmatch.fnmatch(filepath, pattern) or fnmatch.fnmatch(filepath, f"*/{pattern}"):
            return False

    return True


def partition_by_scope(
    files: List[str],
    boundary: dict,
) -> Dict[str, List[str]]:
    """Partition *files* into in-scope and out-of-scope lists.

    Returns::

        {"in_scope": [...], "out_of_scope": [...]}
    """
    in_scope: List[str] = []
    out_of_scope: List[str] = []
    for f in files:
        if is_in_scope(f, boundary):
            in_scope.append(f)
        else:
            out_of_scope.append(f)
    return {"in_scope": in_scope, "out_of_scope": out_of_scope}
