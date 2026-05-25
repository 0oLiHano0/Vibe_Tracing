"""
Merge Gate Engine for Vibe Tracing.

Evaluates quality gate conditions to produce a machine gate decision:
- 'blocked': if there are critical/MUST-level issues.
- 'fail' (conditional): if there are non-blocking issues or unclear constraints.
- 'pass': if there are no issues.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional


class MergeGateEngine:
    """Deterministic rules engine to evaluate merge gate criteria."""

    def __init__(self, project_root: Path) -> None:
        """Initialize the engine with project root."""
        self.project_root = project_root

    def evaluate(
        self,
        gaps: List[Dict[str, Any]],
        risks: List[Dict[str, Any]],
        compliance_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate merge gate criteria based on gaps, risks, and compliance checker results.

        Args:
            gaps: Identified gaps from analyzers.
            risks: Enriched risks from RiskAdvisor.
            compliance_result: Result from ArchitectureComplianceChecker.

        Returns:
            A dict containing:
                "gate_decision": "pass", "fail", or "blocked"
                "reasons": list of strings explaining the decision
                "blocked_items": list of blocking item descriptions
        """
        gate_decision = "pass"
        reasons: List[str] = []
        blocked_items: List[str] = []

        # ----------------------------------------------------
        # 1. Evaluate 'blocked' conditions (MUST/critical issues)
        # ----------------------------------------------------

        # 1.1 Check Must AC gaps
        for gap in gaps:
            item_type = gap.get("item_type")
            item_id = gap.get("item_id", "")
            reason = gap.get("reason", "")
            if item_type == "ac":
                msg = f"验收标准缺失测试证据 ({item_id}): {reason}"
                blocked_items.append(msg)
                reasons.append(msg)
                gate_decision = "blocked"

        # 1.2 Check Must severity risks, completed claims without external evidence,
        # or High risks lacking suggested actions/business impact
        for risk in risks:
            severity = risk.get("severity")
            desc = risk.get("description", "")
            risk_id = risk.get("risk_id", "")
            suggested_action = risk.get("suggested_action", "")
            business_impact = risk.get("business_impact", "")

            # Check if it is a completed claim without external evidence (often MUST severity)
            is_self_ref = "only self-referential" in desc or "self-referential" in desc

            # High risk means MUST severity
            is_high_risk = severity == "must"

            if is_high_risk or is_self_ref:
                msg = f"高风险或不自证违规 ({risk_id}): {desc}"
                blocked_items.append(msg)
                reasons.append(msg)
                gate_decision = "blocked"

                # Check if high risk is lacking action or business impact
                if is_high_risk and (not suggested_action or not business_impact):
                    msg_missing = f"高风险项 ({risk_id}) 缺失处理建议或业务影响描述"
                    blocked_items.append(msg_missing)
                    reasons.append(msg_missing)

        # 1.3 Check Must architecture violations
        if compliance_result:
            violations = compliance_result.get("architecture_violations", [])
            for v in violations:
                rule_id = v.get("rule_id", "")
                msg_violation = v.get("message", "")
                msg = f"违反 MUST 级别架构约束 ({rule_id}): {msg_violation}"
                blocked_items.append(msg)
                reasons.append(msg)
                gate_decision = "blocked"

            # Check status list for any MUST violated
            status_list = compliance_result.get("architecture_compliance_status", [])
            for status_item in status_list:
                rule_id = status_item.get("rule_id", "")
                status = status_item.get("status")
                severity = status_item.get("severity", "must")
                if status == "violated" and severity == "must":
                    msg = f"架构规则被违规触发 ({rule_id})"
                    # Avoid duplicate warnings if already caught in violations
                    if not any(rule_id in item for item in blocked_items):
                        blocked_items.append(msg)
                        reasons.append(msg)
                        gate_decision = "blocked"

        # ----------------------------------------------------
        # 2. Evaluate 'fail' conditions (conditional / SHOULD issues)
        # ----------------------------------------------------
        if gate_decision != "blocked":
            # 2.1 Check unclear architecture constraints
            if compliance_result:
                unclear_constraints = compliance_result.get("unclear_constraints", [])
                for uc in unclear_constraints:
                    rule_id = uc.get("rule_id", "")
                    reason = uc.get("reason", "")
                    msg = f"存在不明确的架构约束规则 ({rule_id}): {reason}"
                    reasons.append(msg)
                    gate_decision = "fail"

                # Check status list for any MUST/SHOULD unclear
                status_list = compliance_result.get(
                    "architecture_compliance_status", []
                )
                for status_item in status_list:
                    rule_id = status_item.get("rule_id", "")
                    status = status_item.get("status")
                    if status == "unclear":
                        msg = f"架构规则状态不明确 ({rule_id})"
                        if not any(msg in item for item in reasons):
                            reasons.append(msg)
                            gate_decision = "fail"

            # 2.2 Check Should-level gaps (e.g. requirement or task gaps, which are non-blocking)
            for gap in gaps:
                item_type = gap.get("item_type")
                item_id = gap.get("item_id", "")
                reason = gap.get("reason", "")
                if item_type != "ac":
                    msg = f"非阻塞缺口 ({item_type} {item_id}): {reason}"
                    reasons.append(msg)
                    gate_decision = "fail"

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
                    msg = f"低/中风险或推测性风险 ({risk_id}): {desc}"
                    reasons.append(msg)
                    gate_decision = "fail"

        # ----------------------------------------------------
        # 3. Handle 'pass'
        # ----------------------------------------------------
        if gate_decision == "pass" and not reasons:
            reasons.append("所有质量门禁规则均已通过，无阻塞项或风险项。")

        return {
            "gate_decision": gate_decision,
            "reasons": reasons,
            "blocked_items": blocked_items,
        }
