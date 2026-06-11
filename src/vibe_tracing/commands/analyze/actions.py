"""
Agent action collectors and urgency scoring.
"""

from typing import Any, Dict, List, Optional, Set

from vibe_tracing.commands.analyze.helpers import (
    _hint_title,
    _hint_context,
    _derive_test_scenarios,
    _get_ac_description,
    _get_req_description,
    _get_related_code,
    _get_existing_tests,
)


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
        return 85

    # Check if the gap has evidence in the evidence index
    if evidence_index:
        for ev in evidence_index.get("evidences", []):
            covers = ev.get("covers", [])
            if item_id in covers:
                return 60

    # Default: pre-existing debt
    return 30


def _collect_gap_actions(
    merged_gaps: list,
    prd_result: Any,
    task_result: Any,
    claims_list: list,
    staged_items: Optional[Set[str]] = None,
    evidence_index: Optional[dict] = None,
) -> list:
    """Collect gap-related actions for MUST-level gaps."""
    actions = []
    for gap in merged_gaps:
        if gap.get("severity") != "must" or gap.get("human_accepted"):
            continue
        ac_id = gap.get("item_id", "")
        ac_text = _get_ac_description(ac_id, prd_result) or gap.get("title", "")
        related_code = _get_related_code(ac_id, task_result, claims_list)
        existing_tests = _get_existing_tests(ac_id, task_result, claims_list)
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
        return 85

    # Check if the risk has evidence in the evidence index
    if evidence_index and claim_id:
        for ev in evidence_index.get("evidences", []):
            covers = ev.get("covers", [])
            if claim_id in covers:
                return 60

    # Stale debt gets lower urgency
    if risk.get("stale"):
        return 25

    # Default
    return 30


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
