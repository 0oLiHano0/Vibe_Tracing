"""
Agent action collectors, urgency scoring, and hint resolution.

Absorbs former helpers.py: AC/requirement description helpers and hint resolution.
"""

from typing import Any, Dict, List, Optional, Tuple

from vibe_tracing.domain.gate.types import DetectedIssue, IssueSignal, OutputState
from vibe_tracing.infra.config.hint_loader import load_hints, resolve_hint

URGENCY_BLOCK_OBSERVED = 90
URGENCY_BLOCK_NEW = 70
URGENCY_WARNING = 50

# --- Hint resolution (from former helpers.py) ---

# Module-level cache for action hints (loaded via centralized hint_loader)
_action_hints: Dict[str, Any] = load_hints("action")


def _hint_title(action_type: str, **kwargs: Any) -> str:
    """Extract the title portion from the first sentence of a level1 hint."""
    hint = _action_hints.get(action_type, {})
    template = resolve_hint(hint, "level1")
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


def _get_related_code(conn, ac_id: str) -> list:
    """Extract code file paths related to an AC via DB query.

    Delegates to infra/db/queries.query_related_code.
    """
    from vibe_tracing.infra.db.queries import query_related_code
    return query_related_code(conn, ac_id)


def _get_existing_tests(conn, ac_id: str) -> list:
    """Get test nodeids related to an AC via DB query.

    Delegates to infra/db/queries.query_existing_tests.
    """
    from vibe_tracing.infra.db.queries import query_existing_tests
    return query_existing_tests(conn, ac_id)


# ---------------------------------------------------------------------------
# Unified issue action collector (PHASE-VT-015 / TASK-VT-189)
# ---------------------------------------------------------------------------

def _compute_issue_urgency(state: OutputState, signal: IssueSignal) -> int:
    """3-level urgency from OutputState + IssueSignal.observed."""
    if state == OutputState.CURRENT_BLOCK:
        return URGENCY_BLOCK_OBSERVED if signal.observed else URGENCY_BLOCK_NEW
    return URGENCY_WARNING


def _is_human_decision(issue: DetectedIssue) -> bool:
    """Identify human-decision issues by issue_id prefix / issue_type."""
    if issue.issue_type == "isolated_task":
        return True
    if issue.issue_id.startswith("chain_broken:proposal"):
        return True
    if ":unclear" in issue.issue_id:
        return True
    return False


def _build_issue_action(
    issue: DetectedIssue,
    urgency: int,
    ctx: Dict[str, Any],
    action_type: str,
    priority: str = "HIGH",
) -> Dict[str, Any]:
    """Construct a single action dict for an Agent-fixable issue."""
    return {
        "priority": priority,
        "type": action_type,
        "title": issue.reason,
        "context": ctx,
        "urgency": urgency,
    }


def _build_deep_context(
    issue: DetectedIssue,
    prd_result: Any,
    conn: Any,
) -> Dict[str, Any]:
    """Deep enhancement: PRD + DB + reason for AC-coverage / task_failed."""
    ctx: Dict[str, Any] = {"reason": issue.reason}
    ac_id = issue.item_id

    if ac_id.startswith("AC-"):
        ac_text = _get_ac_description(ac_id, prd_result)
        if ac_text:
            ctx["ac_description"] = ac_text
        req_id = ""
        if prd_result and hasattr(prd_result, "requirements"):
            for req in prd_result.requirements:
                for ac in req.acceptance_criteria:
                    if ac.ac_id == ac_id:
                        req_id = req.req_id
                        break
                if req_id:
                    break
        if req_id:
            ctx["requirement_id"] = req_id
            req_text = _get_req_description(req_id, prd_result)
            if req_text:
                ctx["requirement_text"] = req_text

    if conn:
        related_code = _get_related_code(conn, ac_id)
        if related_code:
            ctx["implementation_files"] = related_code
        existing_tests = _get_existing_tests(conn, ac_id)
        if existing_tests:
            ctx["existing_tests"] = existing_tests

    return ctx


def _build_reason_context(issue: DetectedIssue) -> Dict[str, Any]:
    """Light/mid enhancement: reason + identifiers."""
    ctx: Dict[str, Any] = {"reason": issue.reason}
    if issue.item_id:
        ctx["item_id"] = issue.item_id
    if issue.related_task_id:
        ctx["related_task_id"] = issue.related_task_id
    if issue.gap_targets:
        ctx["gap_targets"] = issue.gap_targets
    return ctx


def _collect_issue_actions(
    items: List[Tuple[OutputState, IssueSignal, DetectedIssue]],
    prd_result: Any = None,
    task_result: Any = None,
    claims_list: list = None,
    coverage_summary: Any = None,
    conn: Any = None,
) -> list:
    """Unified Agent action collector from (OutputState, IssueSignal, DetectedIssue) triples.

    Filters to CURRENT_BLOCK / CURRENT_WARNING only. Human-decision issues
    produce type='human_decision_required' prompts; the rest produce fix actions.
    """
    actions = []

    for state, signal, issue in items:
        if state not in (OutputState.CURRENT_BLOCK, OutputState.CURRENT_WARNING):
            continue

        urgency = _compute_issue_urgency(state, signal)

        if _is_human_decision(issue):
            actions.append({
                "priority": "INFO",
                "type": "human_decision_required",
                "title": issue.reason,
                "context": {
                    "reason": issue.reason,
                    "issue_id": issue.issue_id,
                    "instruction": "此问题需要人类决策，请通知人类查看 Dashboard。",
                },
                "urgency": urgency,
            })
            continue

        it = issue.issue_type

        if it == "no_claim":
            if issue.item_id.startswith("AC-"):
                ctx = _build_deep_context(issue, prd_result, conn)
            else:
                ctx = _build_reason_context(issue)
            actions.append(_build_issue_action(issue, urgency, ctx, "fix_no_claim"))

        elif it == "chain_broken":
            ctx = _build_reason_context(issue)
            actions.append(_build_issue_action(issue, urgency, ctx, "fix_chain_broken"))

        elif it == "chain_misaligned":
            ctx = _build_reason_context(issue)
            actions.append(_build_issue_action(issue, urgency, ctx, "fix_chain_misaligned"))

        elif it == "task_failed":
            ctx = _build_deep_context(issue, prd_result, conn)
            actions.append(_build_issue_action(issue, urgency, ctx, "fix_task_failed"))

        elif it == "substandard":
            ctx = _build_reason_context(issue)
            priority = "MEDIUM" if state == OutputState.CURRENT_WARNING else "HIGH"
            actions.append(_build_issue_action(issue, urgency, ctx, "fix_substandard", priority))

    return actions
