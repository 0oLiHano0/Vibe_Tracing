"""
Merge Gate Engine for Vibe Tracing.

Evaluates quality gate conditions to produce a machine gate decision:
- 'blocked': if there are critical/MUST-level issues.
- 'fail' (conditional): if there are non-blocking issues or unclear constraints.
- 'pass': if there are no issues.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_HINTS_PATH = Path(__file__).parent / "templates" / "field_hints.json"


def _load_hints(category: str) -> Dict[str, Any]:
    try:
        data = json.loads(_HINTS_PATH.read_text(encoding="utf-8"))
        return data.get(category, {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _resolve_hint(hint_value: Any, level: str = "level1") -> str:
    if isinstance(hint_value, str):
        return hint_value
    if isinstance(hint_value, dict):
        return hint_value.get(level, hint_value.get("level3", ""))
    return ""


_gate_hints = _load_hints("gate_decision")


class MergeGateEngine:
    """Deterministic rules engine to evaluate merge gate criteria."""

    def __init__(self, project_root: Path) -> None:
        """Initialize the engine with project root."""
        self.project_root = project_root

    @staticmethod
    def _is_current(
        related_ids: Optional[Set[str]],
        staged_items: Optional[Set[str]],
    ) -> bool:
        """Check if an item is related to current staged changes.

        Returns ``True`` when:
        - *staged_items* is ``None`` (full-analysis mode, backward-compatible).
        - *related_ids* overlaps with *staged_items*.

        Returns ``False`` when:
        - *staged_items* is provided but *related_ids* is empty/None
          (cannot prove relation to staged changes).
        - *related_ids* does not overlap with *staged_items*.
        """
        if staged_items is None:
            return True  # full-analysis mode
        if not related_ids:
            return False  # no provable relation → pre-existing
        return bool(related_ids & staged_items)

    @staticmethod
    def _tag_reason(
        msg: str,
        related_ids: Optional[Set[str]] = None,
        staged_items: Optional[Set[str]] = None,
    ) -> str:
        """Prefix *msg* with a source tag based on staged_items.

        If *staged_items* is ``None``, the message is returned unchanged
        (backward-compatible).  Otherwise:
        - If any of *related_ids* is in *staged_items* → ``[当前]``
        - If none of *related_ids* is in *staged_items* → ``[预存]``
        - If *related_ids* is empty/None → ``[预存]`` (cannot prove relation)
        """
        if staged_items is None:
            return msg
        if related_ids and related_ids & staged_items:
            return f"[当前] {msg}"
        return f"[预存] {msg}"

    def evaluate(
        self,
        gaps: List[Dict[str, Any]],
        risks: List[Dict[str, Any]],
        compliance_result: Optional[Dict[str, Any]] = None,
        prd_status: str = "active",
        staged_items: Optional[Set[str]] = None,
        directly_staged_items: Optional[Set[str]] = None,
        evidence_index: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate merge gate criteria based on gaps, risks, and compliance checker results.

        Args:
            gaps: Identified gaps from analyzers.
            risks: Enriched risks from RiskAdvisor.
            compliance_result: Result from ArchitectureComplianceChecker.
            prd_status: Current PRD status ('draft', 'active', 'frozen', 'deprecated').
            staged_items: Set of claim/task/AC/requirement IDs affected by the
                current commit (superset including indirectly affected items).
                Used for gap evaluation and architecture violation tagging.
            directly_staged_items: Set of claim/task/AC/requirement IDs whose
                definitions were **directly** modified in this commit.  When
                provided, risk evaluation uses this set instead of
                *staged_items* so that old claims merely referencing modified
                files are tagged ``[预存]`` and do not block the gate.
            evidence_index: Evidence index dict containing tool execution
                results.  When provided, coverage violations (source files
                with < 80% coverage) are extracted from evidences with
                tool_category ``coverage`` and status ``violated``.

        Returns:
            A dict containing:
                "gate_decision": "pass", "fail", or "blocked"
                "reasons": list of strings explaining the decision
                "blocked_items": list of blocking item descriptions
        """
        # For risk evaluation, prefer directly_staged_items to distinguish
        # claims that were directly modified from claims that merely reference
        # modified files (indirectly affected).
        risk_staged = directly_staged_items if directly_staged_items is not None else staged_items
        gate_decision = "pass"
        reasons: List[str] = []
        blocked_items: List[str] = []

        if prd_status == "draft":
            draft_hint = _resolve_hint(_gate_hints.get("draft_approved", {}), "level1")
            return {
                "gate_decision": "draft_approved",
                "reasons": [draft_hint if draft_hint else "项目处于需求草稿阶段（draft），跳过强阻塞门禁规则校验。"],
                "blocked_items": [],
            }

        # ----------------------------------------------------
        # 1. Evaluate 'blocked' conditions (MUST/critical issues)
        # ----------------------------------------------------

        # 1.1 Check Must AC gaps
        for gap in gaps:
            item_type = gap.get("item_type")
            item_id = gap.get("item_id", "")
            reason = gap.get("reason", "")
            if item_type == "ac":
                hint = _resolve_hint(_gate_hints.get("ac_missing_evidence", {}), "level1")
                msg = hint.format(item_id=item_id, reason=reason) if hint else f"验收标准缺失测试证据 ({item_id}): {reason}"
                related = {item_id} if item_id else None
                reasons.append(self._tag_reason(msg, related, staged_items))
                if self._is_current(related, staged_items):
                    blocked_items.append(msg)
                    gate_decision = "blocked"

        # 1.2 Check Must severity risks, completed claims without external evidence,
        # or High risks lacking suggested actions/business impact
        for risk in risks:
            severity = risk.get("severity")
            desc = risk.get("description", "")
            risk_id = risk.get("risk_id", "")
            suggested_action = risk.get("suggested_action", "")
            business_impact = risk.get("business_impact", "")
            item_type = risk.get("item_type", "")

            # Check if it is a completed claim without external evidence (often MUST severity)
            is_self_ref = "only self-referential" in desc or "self-referential" in desc

            # High risk means MUST severity
            is_high_risk = severity == "must"

            if is_high_risk or is_self_ref:
                risk_related: Set[str] = set()
                if risk_id:
                    risk_related.add(risk_id)
                claim_id = risk.get("claim_id")
                if claim_id:
                    risk_related.add(claim_id)
                hint = _resolve_hint(_gate_hints.get("high_risk_or_self_ref", {}), "level1")
                msg = hint.format(risk_id=risk_id, desc=desc) if hint else f"高风险或不自证违规 ({risk_id}): {desc}"
                reasons.append(self._tag_reason(msg, risk_related or None, risk_staged))
                if self._is_current(risk_related or None, risk_staged):
                    blocked_items.append(msg)
                    gate_decision = "blocked"

                    # Check if high risk is lacking action or business impact
                    if is_high_risk and (not suggested_action or not business_impact):
                        hint_missing = _resolve_hint(_gate_hints.get("high_risk_missing_action", {}), "level1")
                        msg_missing = hint_missing.format(risk_id=risk_id) if hint_missing else f"高风险项 ({risk_id}) 缺失处理建议或业务影响描述"
                        blocked_items.append(msg_missing)
                        reasons.append(self._tag_reason(msg_missing, risk_related or None, risk_staged))

                    # Add specific reason for low-confidence claims
                    if item_type == "claim_credibility":
                        hint_credibility = _resolve_hint(_gate_hints.get("low_confidence_claim", {}), "level1")
                        msg_credibility = hint_credibility if hint_credibility else "存在低可信度 Claim（无工具验证证据）"
                        if msg_credibility not in blocked_items:
                            blocked_items.append(msg_credibility)
                            reasons.append(self._tag_reason(msg_credibility, risk_related or None, risk_staged))

        # 1.3 Check Must architecture violations
        if compliance_result:
            violations = compliance_result.get("architecture_violations", [])
            for v in violations:
                rule_id = v.get("rule_id", "")
                msg_violation = v.get("message", "")
                hint = _resolve_hint(_gate_hints.get("must_arch_violation", {}), "level1")
                msg = hint.format(rule_id=rule_id, msg_violation=msg_violation) if hint else f"违反 MUST 级别架构约束 ({rule_id}): {msg_violation}"
                reasons.append(self._tag_reason(msg, None, staged_items))
                # Architecture violations have no claim/task mapping;
                # only block when staged_items is None (full-analysis mode).
                if staged_items is None:
                    blocked_items.append(msg)
                    gate_decision = "blocked"

            # Check status list for any MUST violated
            status_list = compliance_result.get("architecture_compliance_status", [])
            for status_item in status_list:
                rule_id = status_item.get("rule_id", "")
                status = status_item.get("status")
                severity = status_item.get("severity", "must")
                if status == "violated" and severity == "must":
                    hint = _resolve_hint(_gate_hints.get("arch_rule_violated", {}), "level1")
                    msg = hint.format(rule_id=rule_id) if hint else f"架构规则被违规触发 ({rule_id})"
                    # Avoid duplicate warnings if already caught in violations
                    if not any(rule_id in item for item in blocked_items):
                        reasons.append(self._tag_reason(msg, None, staged_items))
                        if staged_items is None:
                            blocked_items.append(msg)
                            gate_decision = "blocked"

        # ----------------------------------------------------
        # 2. Evaluate 'fail' conditions (conditional / SHOULD issues)
        # NOTE: Fail reasons are ALWAYS recorded regardless of gate_decision,
        # so users see all issues in a single run. Only upgrade the decision
        # to "fail" when gate_decision is still "pass" AND at least one
        # fail item is related to current staged changes (or in full-analysis
        # mode).
        # ----------------------------------------------------
        current_fail_detected = False
        any_fail_detected = False

        # 2.1 Check unclear architecture constraints
        if compliance_result:
            unclear_constraints = compliance_result.get("unclear_constraints", [])
            for uc in unclear_constraints:
                rule_id = uc.get("rule_id", "")
                reason = uc.get("reason", "")
                hint = _resolve_hint(_gate_hints.get("unclear_constraint_rule", {}), "level1")
                msg = hint.format(rule_id=rule_id, reason=reason) if hint else f"存在不明确的架构约束规则 ({rule_id}): {reason}"
                reasons.append(self._tag_reason(msg, None, staged_items))
                any_fail_detected = True
                if staged_items is None:
                    current_fail_detected = True

            # Check status list for any MUST/SHOULD unclear
            status_list = compliance_result.get(
                "architecture_compliance_status", []
            )
            for status_item in status_list:
                rule_id = status_item.get("rule_id", "")
                status = status_item.get("status")
                if status == "unclear":
                    hint = _resolve_hint(_gate_hints.get("arch_rule_unclear", {}), "level1")
                    msg = hint.format(rule_id=rule_id) if hint else f"架构规则状态不明确 ({rule_id})"
                    if not any(msg in item for item in reasons):
                        reasons.append(self._tag_reason(msg, None, staged_items))
                        any_fail_detected = True
                        if staged_items is None:
                            current_fail_detected = True

        # 2.2 Check Should-level gaps (e.g. requirement or task gaps, which are non-blocking)
        for gap in gaps:
            item_type = gap.get("item_type")
            item_id = gap.get("item_id", "")
            reason = gap.get("reason", "")
            if item_type != "ac":
                hint = _resolve_hint(_gate_hints.get("non_blocking_gap", {}), "level1")
                msg = hint.format(item_type=item_type, item_id=item_id, reason=reason) if hint else f"非阻塞缺口 ({item_type} {item_id}): {reason}"
                related = {item_id} if item_id else None
                reasons.append(self._tag_reason(msg, related, staged_items))
                any_fail_detected = True
                if self._is_current(related, staged_items):
                    current_fail_detected = True

        # 2.3 Check Should/Could severity risks or speculative risks
        for risk in risks:
            severity = risk.get("severity")
            desc = risk.get("description", "")
            risk_id = risk.get("risk_id", "")
            confidence = risk.get("confidence")
            risk_type = risk.get("type")

            is_speculative = (
                confidence == "low_confidence" or risk_type == "suggestion"
            )
            is_should_could = severity in ("should", "could")

            if is_should_could or is_speculative:
                risk_related_fs: Set[str] = set()
                if risk_id:
                    risk_related_fs.add(risk_id)
                claim_id = risk.get("claim_id")
                if claim_id:
                    risk_related_fs.add(claim_id)
                hint = _resolve_hint(_gate_hints.get("low_medium_risk", {}), "level1")
                msg = hint.format(risk_id=risk_id, desc=desc) if hint else f"低/中风险或推测性风险 ({risk_id}): {desc}"
                reasons.append(self._tag_reason(msg, risk_related_fs or None, risk_staged))
                any_fail_detected = True
                if self._is_current(risk_related_fs or None, risk_staged):
                    current_fail_detected = True

        # Only upgrade to "fail" if not already "blocked" and at least one
        # fail item is related to current changes.
        if current_fail_detected and gate_decision == "pass":
            gate_decision = "fail"

        # ----------------------------------------------------
        # 2.5 Check coverage violations (always [当前] — fresh measurement)
        # ----------------------------------------------------
        coverage_violations = []
        if evidence_index:
            for ev in evidence_index.get("evidences", []):
                if (ev.get("details", {}).get("tool_category") == "coverage" and
                        ev.get("status") == "violated"):
                    coverage_violations.append({
                        "file": ev.get("source_path", ""),
                        "percent": ev.get("details", {}).get("percent_covered", 0),
                    })
        if coverage_violations:
            for cv in coverage_violations:
                # Coverage violations are always [当前] — they come from
                # fresh tool measurements, not from staged changes.
                tag = "[当前] " if staged_items is not None else ""
                reasons.append(
                    f"{tag}Coverage below 80%: {cv['file']} ({cv['percent']}%)"
                )
            # Coverage violations are always current (based on fresh measurement)
            if gate_decision not in ("blocked",):
                gate_decision = "blocked"

        # ----------------------------------------------------
        # 3. Handle 'pass'
        # ----------------------------------------------------
        if gate_decision == "pass" and not reasons:
            hint = _resolve_hint(_gate_hints.get("all_gates_passed", {}), "level1")
            reasons.append(hint if hint else "所有质量门禁规则均已通过，无阻塞项或风险项。")

        return {
            "gate_decision": gate_decision,
            "reasons": reasons,
            "blocked_items": blocked_items,
        }
