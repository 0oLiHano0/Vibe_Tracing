"""
AC/requirement description helpers and hint resolution for action formatting.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from vibe_tracing.hint_loader import load_hints, resolve_hint

# Module-level cache for action hints (loaded via centralized hint_loader)
_action_hints: Dict[str, Any] = load_hints("action")


def _hint_title(action_type: str, **kwargs: Any) -> str:
    """Extract the title portion from the first sentence of a level1 hint."""
    hint = _action_hints.get(action_type, {})
    template = resolve_hint(hint, "level1")
    # Extract first sentence (before Chinese period 。)
    idx = template.find("。")
    if idx > 0:
        template = template[:idx]
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def _hint_context(action_type: str, key: str, **kwargs: Any) -> str:
    """Get a context value from action hints and format with variables."""
    hint = _action_hints.get(action_type, {})
    template = hint.get(key, "")
    if not template:
        return ""
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def _derive_test_scenarios(ac_text: str) -> list:
    """Derive test scenarios from AC title text using hints."""
    hints = _action_hints.get("test_scenarios", {})
    default = hints.get("default", "")
    if not ac_text:
        return [default]
    scenarios = []
    if any(kw in ac_text for kw in ["无效", "错误", "invalid", "error"]):
        scenarios.append(hints.get("invalid_input", ""))
    if any(kw in ac_text for kw in ["空", "empty"]):
        scenarios.append(hints.get("empty_input", ""))
    if any(kw in ac_text for kw in ["正常", "valid", "正确"]):
        scenarios.append(hints.get("valid_input", ""))
    if not scenarios:
        scenarios.append(default)
    return scenarios


def _get_ac_description(ac_id: str, prd_result) -> str:
    """Extract AC title from PrdParseResult."""
    if not prd_result or not hasattr(prd_result, "requirements"):
        return ""
    for req in prd_result.requirements:
        for ac in req.acceptance_criteria:
            if ac.ac_id == ac_id:
                return ac.title
    return ""


def _get_req_description(req_id: str, prd_result) -> str:
    """Extract requirement title from PrdParseResult."""
    if not prd_result or not hasattr(prd_result, "requirements") or not req_id:
        return ""
    for req in prd_result.requirements:
        if req.req_id == req_id:
            return req.title
    return ""


def _get_related_code(ac_id: str, task_result, claims_list=None) -> list:
    """Extract code file paths related to an AC from claims (not tasks).

    Returns a list of path strings (up to 3).
    """
    code_refs = []
    if not claims_list:
        return code_refs

    # Collect task IDs that reference this AC
    task_ids = set()
    if task_result and hasattr(task_result, "tasks"):
        for task in task_result.tasks:
            if ac_id in (task.related_acceptance_criteria or []):
                task_ids.add(task.task_id)

    # Find claims referencing those tasks and collect their code_refs
    for claim in claims_list:
        related = getattr(claim, "related_task", None)
        if related in task_ids:
            for ref in (getattr(claim, "code_refs", None) or []):
                path_only = ref.split("#")[0]
                if path_only and Path(path_only).exists():
                    code_refs.append(path_only)
                    if len(code_refs) >= 3:
                        break
    return code_refs


def _get_existing_tests(ac_id: str, task_result, claims_list=None) -> list:
    """Get test file paths related to an AC from claims (not tasks)."""
    test_refs = []
    if not claims_list:
        return test_refs

    # Collect task IDs that reference this AC
    task_ids = set()
    if task_result and hasattr(task_result, "tasks"):
        for task in task_result.tasks:
            if ac_id in (task.related_acceptance_criteria or []):
                task_ids.add(task.task_id)

    # Find claims referencing those tasks and collect their test_refs
    for claim in claims_list:
        related = getattr(claim, "related_task", None)
        if related in task_ids:
            for ref in (getattr(claim, "test_refs", None) or []):
                test_refs.append(ref)
                if len(test_refs) >= 2:
                    break
    return test_refs
