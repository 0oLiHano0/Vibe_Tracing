"""
Merge Gate Engine for Vibe Tracing.

Evaluates quality gate conditions to produce a machine gate decision:
- 'blocked': if there are critical/MUST-level issues.
- 'fail' (conditional): if there are non-blocking issues or unclear constraints.
- 'pass': if there are no issues.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from vibe_tracing.governance import is_in_scope
from vibe_tracing.hint_loader import load_hints, resolve_hint

_gate_hints = load_hints("gate_decision")


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

    @staticmethod
    def check_claim_exists(
        staged_files: Set[str],
        claims: List[Dict[str, Any]],
        boundary: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        """Check whether staged business files are covered by at least one Claim.

        Args:
            staged_files: Set of file paths that are staged in the current commit.
            claims: List of claim dicts, each having ``code_refs`` and/or
                ``test_refs`` keys (lists of file paths).
            boundary: Optional governance boundary dict with
                ``included_patterns`` / ``excluded_patterns``.  When
                provided, only files matching the boundary are considered
                business files; non-matching files are ignored.

        Returns:
            ``(passed, unclaimed_files)`` where *passed* is ``True`` when
            every business file is covered by at least one claim.
        """
        if not staged_files:
            return (True, set())

        # Filter to business files within the governance boundary.
        if boundary is not None:
            business_files = {f for f in staged_files if is_in_scope(f, boundary)}
        else:
            business_files = set(staged_files)

        if not business_files:
            return (True, set())

        # Collect all files referenced by any claim.
        all_claimed_files: Set[str] = set()
        for claim in claims:
            for ref in claim.get("code_refs", []):
                all_claimed_files.add(ref)
            for ref in claim.get("test_refs", []):
                all_claimed_files.add(ref)

        unclaimed = business_files - all_claimed_files
        if unclaimed:
            return (False, unclaimed)
        return (True, set())

    @staticmethod
    def check_ac_coverage(
        claims: List[Dict[str, Any]],
        tasks: List[Dict[str, Any]],
        evidence_index: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Derive AC coverage status from claims, tasks, and test evidence.

        For each MUST-level task (priority == "must"), this method checks
        whether its acceptance criteria are covered by passing tests via
        the claim chain: Task -> Claim -> test_refs -> evidence.

        Args:
            claims: List of Claim dicts.  Each should have
                ``related_task``, ``test_refs``, and optionally
                ``claim_id`` keys.
            tasks: List of Task dicts from ``task_list.json``.  Each should
                have ``task_id``, ``priority``, and
                ``related_acceptance_criteria`` keys.
            evidence_index: Optional evidence index dict.  When provided
                and it contains test results (entries with
                ``details.test_category`` == ``"test"``), the method
                checks whether referenced tests actually passed.

        Returns:
            A list of dicts ``[{ac_id, task_id, reason}]`` for each
            uncovered MUST AC.  Empty list means all MUST ACs are covered.
        """
        uncovered: List[Dict[str, Any]] = []

        # Build task_id -> claims lookup
        task_claims: Dict[str, List[Dict[str, Any]]] = {}
        for claim in claims:
            task_id = claim.get("related_task", "")
            if task_id:
                task_claims.setdefault(task_id, []).append(claim)

        # Build test file -> result lookup from evidence_index
        test_results: Dict[str, bool] = {}
        if evidence_index:
            for ev in evidence_index.get("evidences", []):
                details = ev.get("details", {})
                if details.get("test_category") == "test":
                    source = ev.get("source_path", "")
                    if source:
                        test_results[source] = ev.get("status") == "passed"

        for task in tasks:
            if task.get("priority") != "must":
                continue

            task_id = task.get("task_id", "")
            related_acs = task.get("related_acceptance_criteria", [])

            related_claims = task_claims.get(task_id, [])
            if not related_claims:
                for ac_id in related_acs:
                    uncovered.append({
                        "ac_id": ac_id,
                        "task_id": task_id,
                        "reason": "no_claim_for_task",
                    })
                continue

            for ac_id in related_acs:
                has_passing_test = False
                for claim in related_claims:
                    test_refs = claim.get("test_refs", [])
                    if not test_refs:
                        continue
                    if not test_results:
                        # No test evidence available; declare presence
                        has_passing_test = True
                        break
                    for ref in test_refs:
                        if test_results.get(ref, False):
                            has_passing_test = True
                            break
                    if has_passing_test:
                        break

                if not has_passing_test:
                    any_claim_has_tests = any(
                        c.get("test_refs") for c in related_claims
                    )
                    reason = (
                        "test_failed"
                        if (any_claim_has_tests and test_results)
                        else "no_tests_declared"
                    )
                    uncovered.append({
                        "ac_id": ac_id,
                        "task_id": task_id,
                        "reason": reason,
                    })

        return uncovered

    def evaluate(
        self,
        gaps: List[Dict[str, Any]],
        risks: List[Dict[str, Any]],
        compliance_result: Optional[Dict[str, Any]] = None,
        prd_status: str = "active",
        staged_items: Optional[Set[str]] = None,
        directly_staged_items: Optional[Set[str]] = None,
        evidence_index: Optional[Dict[str, Any]] = None,
        human_decisions: Optional[Any] = None,
        claims: Optional[List[Dict[str, Any]]] = None,
        boundary: Optional[Dict[str, Any]] = None,
        tasks: Optional[List[Dict[str, Any]]] = None,
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
            human_decisions: Optional list of human decisions.  Each element is a
                dict with keys ``decision_id``, ``category``, ``targetId``,
                ``action``, ``reason``, ``decidedBy``, ``timestamp``.
                Also accepts a wrapper dict ``{"decisions": [...]}``.
                Supported actions: ``accept_risk`` (downgrades matching risk
                severity to ``"accepted"``), ``mark_complete`` (marks matching
                gap as ``"human_resolved"``).
            claims: Optional list of Claim dicts for Claim existence check.
                Each dict should have ``code_refs`` and/or ``test_refs``
                keys.  When provided together with *staged_items*, the
                engine verifies that every staged business file (within the
                governance boundary) is referenced by at least one Claim.
                Unclaimed files produce a ``must``-severity gap with
                category ``missing_claim``, which blocks the gate.  When
                ``None``, the check is skipped (backward compatible).
            boundary: Optional governance boundary dict (with
                ``included_patterns`` / ``excluded_patterns``) used to
                filter staged files to business files during Claim
                existence check.  When ``None``, all staged files are
                treated as business files.
            tasks: Optional list of Task dicts from ``task_list.json``.
                When provided together with *claims*, the engine derives
                AC coverage status for each MUST-level task's acceptance
                criteria via the claim chain (Task -> Claim -> test_refs
                -> evidence).  Uncovered MUST ACs produce ``must``-severity
                gaps with category ``ac_not_covered``, which block the
                gate.  When ``None``, the check is skipped (backward
                compatible).

        Returns:
            A dict containing:
                "gate_decision": "pass", "fail", or "blocked"
                "reasons": list of strings explaining the decision
                "blocked_items": list of blocking item descriptions
                "human_decisions_applied": int, number of human decisions applied
        """
        # ----------------------------------------------------
        # 0. Normalize human_decisions and build lookup sets
        # ----------------------------------------------------
        decisions_list: List[Dict[str, Any]] = []
        if human_decisions is not None:
            if isinstance(human_decisions, dict) and "decisions" in human_decisions:
                decisions_list = human_decisions["decisions"] or []
            elif isinstance(human_decisions, list):
                decisions_list = human_decisions

        # targetIds whose risks should be accepted (severity → "accepted")
        accepted_risk_target_ids: Set[str] = set()
        # targetIds whose gaps should be marked human_resolved
        resolved_gap_target_ids: Set[str] = set()

        for d in decisions_list:
            action = d.get("action", "")
            target_id = d.get("targetId", "")
            if action == "accept_risk" and target_id:
                accepted_risk_target_ids.add(target_id)
            elif action == "mark_complete" and target_id:
                resolved_gap_target_ids.add(target_id)

        human_decisions_applied = len(accepted_risk_target_ids) + len(resolved_gap_target_ids)

        # For risk evaluation, prefer directly_staged_items to distinguish
        # claims that were directly modified from claims that merely reference
        # modified files (indirectly affected).
        risk_staged = directly_staged_items if directly_staged_items is not None else staged_items
        gate_decision = "pass"
        reasons: List[str] = []
        blocked_items: List[str] = []

        if prd_status == "draft":
            draft_hint = resolve_hint(_gate_hints.get("draft_approved", {}), "level1")
            return {
                "gate_decision": "draft_approved",
                "reasons": [draft_hint if draft_hint else "项目处于需求草稿阶段（draft），跳过强阻塞门禁规则校验。"],
                "blocked_items": [],
                "human_decisions_applied": human_decisions_applied,
            }

        # ----------------------------------------------------
        # 0.5 Claim existence check (when claims are provided)
        # ----------------------------------------------------
        if claims is not None and staged_items is not None:
            passed, unclaimed = self.check_claim_exists(
                staged_files=staged_items,
                claims=claims,
                boundary=boundary,
            )
            if not passed and unclaimed:
                for f in sorted(unclaimed):
                    hint = resolve_hint(
                        _gate_hints.get("missing_claim", {}), "level1"
                    )
                    msg = (
                        hint.format(file=f)
                        if hint
                        else f"业务文件 {f} 未被任何 Claim 覆盖，需要创建 Claim 声明该文件的变更。"
                    )
                    gap_entry = {
                        "item_id": f,
                        "item_type": "missing_claim",
                        "target_id": f,
                        "reason": msg,
                    }
                    gaps.append(gap_entry)
                    reasons.append(self._tag_reason(msg, {f}, staged_items))
                    blocked_items.append(msg)
                    gate_decision = "blocked"

        # ----------------------------------------------------
        # 0.6 AC coverage derivation (when claims + tasks are provided)
        # ----------------------------------------------------
        if claims is not None and tasks is not None:
            ac_gaps = self.check_ac_coverage(claims, tasks, evidence_index)
            for gap in ac_gaps:
                ac_id = gap["ac_id"]
                task_id = gap["task_id"]
                reason = gap["reason"]
                hint = resolve_hint(
                    _gate_hints.get("ac_not_covered", {}), "level1"
                )
                msg = (
                    hint.format(ac_id=ac_id, task_id=task_id, reason=reason)
                    if hint
                    else f"MUST AC {ac_id} (task {task_id}) 未被测试覆盖: {reason}"
                )
                gap_entry = {
                    "item_id": ac_id,
                    "item_type": "ac",
                    "category": "ac_not_covered",
                    "target_id": ac_id,
                    "reason": msg,
                    "task_id": task_id,
                }
                gaps.append(gap_entry)
                reasons.append(self._tag_reason(msg, {ac_id}, staged_items))
                blocked_items.append(msg)
                gate_decision = "blocked"

        # ----------------------------------------------------
        # 1. Evaluate 'blocked' conditions (MUST/critical issues)
        # ----------------------------------------------------

        # 1.1 Check Must AC gaps
        for gap in gaps:
            item_type = gap.get("item_type")
            item_id = gap.get("item_id", "")
            reason = gap.get("reason", "")
            target_id = gap.get("target_id", "")
            human_resolved = target_id in resolved_gap_target_ids

            if item_type == "ac":
                hint = resolve_hint(_gate_hints.get("ac_missing_evidence", {}), "level1")
                msg = hint.format(item_id=item_id, reason=reason) if hint else f"验收标准缺失测试证据 ({item_id}): {reason}"
                related = {item_id} if item_id else None
                if human_resolved:
                    reasons.append(self._tag_reason(f"[已人工完成] {msg}", related, staged_items))
                else:
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
            risk_target_id = risk.get("target_id", "")
            human_accepted = risk_target_id in accepted_risk_target_ids

            # If human accepted, override severity
            effective_severity = "accepted" if human_accepted else severity

            # Check if it is a completed claim without external evidence (often MUST severity)
            is_self_ref = "only self-referential" in desc or "self-referential" in desc

            # High risk means MUST severity (but not if human accepted)
            is_high_risk = effective_severity == "must"

            if is_high_risk or is_self_ref or human_accepted:
                risk_related: Set[str] = set()
                if risk_id:
                    risk_related.add(risk_id)
                claim_id = risk.get("claim_id")
                if claim_id:
                    risk_related.add(claim_id)
                hint = resolve_hint(_gate_hints.get("high_risk_or_self_ref", {}), "level1")
                msg = hint.format(risk_id=risk_id, desc=desc) if hint else f"高风险或不自证违规 ({risk_id}): {desc}"
                if human_accepted:
                    reasons.append(self._tag_reason(f"[已接受风险] {msg}", risk_related or None, risk_staged))
                else:
                    reasons.append(self._tag_reason(msg, risk_related or None, risk_staged))
                    if self._is_current(risk_related or None, risk_staged):
                        blocked_items.append(msg)
                        gate_decision = "blocked"

                        # Check if high risk is lacking action or business impact
                        if is_high_risk and (not suggested_action or not business_impact):
                            hint_missing = resolve_hint(_gate_hints.get("high_risk_missing_action", {}), "level1")
                            msg_missing = hint_missing.format(risk_id=risk_id) if hint_missing else f"高风险项 ({risk_id}) 缺失处理建议或业务影响描述"
                            blocked_items.append(msg_missing)
                            reasons.append(self._tag_reason(msg_missing, risk_related or None, risk_staged))

        # 1.3 Check Must architecture violations
        if compliance_result:
            violations = compliance_result.get("architecture_violations", [])
            for v in violations:
                rule_id = v.get("rule_id", "")
                msg_violation = v.get("message", "")
                hint = resolve_hint(_gate_hints.get("must_arch_violation", {}), "level1")
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
                    hint = resolve_hint(_gate_hints.get("arch_rule_violated", {}), "level1")
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
                hint = resolve_hint(_gate_hints.get("unclear_constraint_rule", {}), "level1")
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
                    hint = resolve_hint(_gate_hints.get("arch_rule_unclear", {}), "level1")
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
            target_id = gap.get("target_id", "")
            human_resolved = target_id in resolved_gap_target_ids

            if item_type != "ac":
                hint = resolve_hint(_gate_hints.get("non_blocking_gap", {}), "level1")
                msg = hint.format(item_type=item_type, item_id=item_id, reason=reason) if hint else f"非阻塞缺口 ({item_type} {item_id}): {reason}"
                related = {item_id} if item_id else None
                if human_resolved:
                    reasons.append(self._tag_reason(f"[已人工完成] {msg}", related, staged_items))
                else:
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
            risk_target_id = risk.get("target_id", "")
            human_accepted = risk_target_id in accepted_risk_target_ids

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
                hint = resolve_hint(_gate_hints.get("low_medium_risk", {}), "level1")
                msg = hint.format(risk_id=risk_id, desc=desc) if hint else f"低/中风险或推测性风险 ({risk_id}): {desc}"
                if human_accepted:
                    reasons.append(self._tag_reason(f"[已接受风险] {msg}", risk_related_fs or None, risk_staged))
                else:
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
            hint = resolve_hint(_gate_hints.get("all_gates_passed", {}), "level1")
            reasons.append(hint if hint else "所有质量门禁规则均已通过，无阻塞项或风险项。")

        return {
            "gate_decision": gate_decision,
            "reasons": reasons,
            "blocked_items": blocked_items,
            "human_decisions_applied": human_decisions_applied,
        }
