"""
Agent action collectors, urgency scoring, and hint resolution.

Absorbs former helpers.py: AC/requirement description helpers and hint resolution.
"""

from typing import Any, Dict, Optional, Set

from vibe_tracing.infra.config.hint_loader import load_hints, resolve_hint

URGENCY_STAGED = 85
URGENCY_IN_EVIDENCE = 60
URGENCY_DEFAULT = 30
URGENCY_STALE = 25

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


def _compute_gap_urgency(
    gap: dict,
    staged_items: Optional[Set[str]],
    evidence_index: Optional[dict],
) -> int:
    """Compute urgency score (0-100) for a gap action.

    - 80-100: gap relates to current staged changes
    - 50-70: gap has evidence in the evidence index (known historical issue)
    - 20-40: other (pre-existing debt, non-current change)
    """
    item_id = gap.get("item_id", "")
    item_type = gap.get("item_type", "")

    # Check if the gap's item is in the staged change set
    if staged_items is not None and item_id in staged_items:
        return URGENCY_STAGED

    # Check if the gap has evidence in the evidence index
    if evidence_index:
        for ev in evidence_index.get("evidences", []):
            covers = ev.get("covers", [])
            if item_id in covers:
                return URGENCY_IN_EVIDENCE

    # Default: pre-existing debt
    return URGENCY_DEFAULT


def _collect_gap_actions(
    merged_gaps: list,
    prd_result: Any,
    task_result: Any,
    claims_list: list,
    staged_items: Optional[Set[str]] = None,
    evidence_index: Optional[dict] = None,
    conn=None,
) -> list:
    """Collect gap-related actions for MUST-level gaps."""
    actions = []
    for gap in merged_gaps:
        if gap.get("severity") != "must" or gap.get("human_accepted"):
            continue
        ac_id = gap.get("item_id", "")
        ac_text = _get_ac_description(ac_id, prd_result) or gap.get("title", "")
        related_code = _get_related_code(conn, ac_id) if conn else []
        existing_tests = _get_existing_tests(conn, ac_id) if conn else []
        test_scenarios = _derive_test_scenarios(ac_text)

        ctx: Dict[str, Any] = {
            "ac_description": ac_text,
            "severity": gap.get("severity", "MUST"),
            "requirement_id": gap.get("requirement_id", ""),
            "requirement_text": _get_req_description(
                gap.get("requirement_id"), prd_result,
            ),
            "test_scenarios": test_scenarios,
            "verification": _hint_context("cover_gap", "verification", ac_id=ac_id),
        }
        if gap.get("stale"):
            ctx["note"] = _hint_context("cover_gap", "stale_note")
        if related_code:
            ctx["implementation_files"] = related_code
        if existing_tests:
            ctx["existing_tests"] = existing_tests

        urgency = _compute_gap_urgency(gap, staged_items, evidence_index)

        actions.append({
            "priority": "HIGH",
            "type": "cover_gap",
            "title": _hint_title("cover_gap", ac_id=ac_id, ac_text=ac_text),
            "context": ctx,
            "urgency": urgency,
        })
    return actions


def _compute_risk_urgency(
    risk: dict,
    staged_items: Optional[Set[str]],
    evidence_index: Optional[dict],
) -> int:
    """Compute urgency score (0-100) for a risk action.

    - 80-100: risk relates to current staged changes (claim_id in staged_items)
    - 50-70: risk has evidence in the evidence index (known historical issue)
    - 20-40: other (pre-existing debt)
    """
    claim_id = risk.get("claim_id", "")

    # Check if the risk's claim is in the staged change set
    if staged_items is not None and claim_id and claim_id in staged_items:
        return URGENCY_STAGED

    # Check if the risk has evidence in the evidence index
    if evidence_index and claim_id:
        for ev in evidence_index.get("evidences", []):
            covers = ev.get("covers", [])
            if claim_id in covers:
                return URGENCY_IN_EVIDENCE

    # Stale debt gets lower urgency
    if risk.get("stale"):
        return URGENCY_STALE

    # Default
    return URGENCY_DEFAULT


def _collect_risk_actions(
    active_risks: list,
    merged_gaps: list,
    staged_items: Optional[Set[str]] = None,
    evidence_index: Optional[dict] = None,
) -> list:
    """Collect risk-related actions (MUST risks and stale debts)."""
    actions = []
    for risk in active_risks:
        severity = risk.get("severity")
        desc = risk.get("description", "")
        is_self_ref = "only self-referential" in desc or "self-referential" in desc
        if severity == "must" or is_self_ref:
            urgency = _compute_risk_urgency(risk, staged_items, evidence_index)
            actions.append({
                "priority": "HIGH",
                "type": "high_risk",
                "title": _hint_title(
                    "high_risk",
                    risk_id=risk.get("risk_id", ""),
                    title=risk.get("title", ""),
                ),
                "context": {
                    "risk_id": risk.get("risk_id", ""),
                    "severity": severity,
                    "description": desc,
                    "claim_id": risk.get("claim_id", ""),
                    "suggested_action": risk.get("suggested_action", ""),
                    "fix_via": _hint_context("high_risk", "fix_via"),
                },
                "urgency": urgency,
            })

    for risk in active_risks:
        if risk.get("stale") and not risk.get("deferred"):
            age_val = risk.get("age_iterations", "多个")
            urgency = _compute_risk_urgency(risk, staged_items, evidence_index)
            actions.append({
                "priority": "LOW",
                "type": "stale_debt",
                "title": _hint_title("stale_debt", title=risk.get("title", "")),
                "context": {
                    "description": risk.get("description", ""),
                    "age": _hint_context(
                        "stale_debt", "age_format", age_iterations=age_val,
                    ),
                },
                "urgency": urgency,
            })
    return actions


def _collect_violation_actions(violations: list, compliance_status: list) -> list:
    """Collect architecture violation actions."""
    actions = []
    for v in violations:
        actions.append({
            "priority": "HIGH",
            "type": "fix_violation",
            "title": _hint_title("fix_violation", rule_id=v.get("rule_id", "")),
            "context": {
                "rule_text": v.get("description", ""),
                "violation_reason": v.get("reason", ""),
                "fix_via": _hint_context("fix_violation", "fix_via"),
            },
            "urgency": 90,
        })

    for status_item in compliance_status:
        rule_id = status_item.get("rule_id", "")
        status = status_item.get("status")
        item_severity = status_item.get("severity", "must")
        if status == "violated" and item_severity == "must":
            if not any(v.get("rule_id") == rule_id for v in violations):
                actions.append({
                    "priority": "HIGH",
                    "type": "arch_status_violation",
                    "title": _hint_title(
                        "arch_status_violation", rule_id=rule_id,
                    ),
                    "context": {
                        "rule_id": rule_id,
                        "severity": item_severity,
                        "fix_via": _hint_context("arch_status_violation", "fix_via"),
                    },
                    "urgency": 90,
                })
    return actions


def _collect_gate_reason_actions(
    gate_decision: str,
    gate_reasons: list,
    existing_actions: list,
) -> list:
    """Generate fallback actions from gate reasons when no HIGH actions exist."""
    has_high = any(a["priority"] == "HIGH" for a in existing_actions)
    if gate_decision not in ("blocked", "fail") or has_high or not gate_reasons:
        return []
    actions = []
    for reason in gate_reasons:
        actions.append({
            "priority": "HIGH",
            "type": "gate_blocked",
            "title": _hint_title("gate_blocked", reason=reason[:80]),
            "context": {
                "reason": reason,
                "fix_via": _hint_context("gate_blocked", "fix_via"),
            },
            "urgency": 80,
        })
    return actions
