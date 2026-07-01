"""
Merge Gate Engine for Vibe Tracing.

Evaluates quality gate conditions to produce a machine gate decision:
- 'blocked': if there are critical/MUST-level issues.
- 'fail' (conditional): if there are non-blocking issues or unclear constraints.
- 'pass': if there are no issues.

Refactored (TASK-VT-073): No longer holds conn. Receives analysis results
as parameters from the pipeline.

Enhanced (TASK-VT-096): Supports incremental_only mode for AI Agent efficiency.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from vibe_tracing.infra.config.hint_loader import load_hints, resolve_hint
from vibe_tracing.infra.logging.logger import OperationalLogger

_gate_hints = load_hints("gate_decision")


class MergeGateEngine:
    """Deterministic rules engine to evaluate merge gate criteria."""

    def __init__(
        self,
        project_root: Path,
        incremental_only: bool = False,
        show_historical_debt: bool = True,
    ) -> None:
        """Initialize the engine with project root.

        Args:
            project_root: Path to the project root directory.
            incremental_only: If True, only check incremental issues related to current commit.
                Historical debt will not block the gate.
            show_historical_debt: If True, show historical debt in terminal output.
                If False, only show a summary count.

        Note: No conn parameter. Analysis results are passed to evaluate().
        """
        self.project_root = project_root
        self.coverage_threshold = 80
        self._ghost_code_exclusions: List[str] = []
        self._load_exclusions()

        # Load gate configuration from config.json
        self._load_gate_config()

        # Priority: parameter > environment variable > config.json > default
        self.incremental_only = (
            incremental_only
            or os.environ.get("VT_INCREMENTAL_ONLY") == "1"
            or self._config_incremental_only
        )

        self.show_historical_debt = (
            show_historical_debt
            and os.environ.get("VT_SHOW_HISTORICAL_DEBT") != "0"
            and self._config_show_historical_debt
        )

        # Track historical debt count for summary
        self._historical_debt_count = 0

    def _load_exclusions(self) -> None:
        """Load ghost code exclusions from config.json."""
        import json
        config_path = self.project_root / ".vibetracing" / "config.json"
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                self._ghost_code_exclusions = config.get("ghost_code_exclusions", [])
            except (json.JSONDecodeError, OSError):
                pass

    def _load_gate_config(self) -> None:
        """Load gate configuration from config.json."""
        import json
        config_path = self.project_root / ".vibetracing" / "config.json"
        self._config_incremental_only = False
        self._config_show_historical_debt = True

        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                gate_config = config.get("gate", {})
                self._config_incremental_only = gate_config.get("incremental_only", False)
                self._config_show_historical_debt = gate_config.get("show_historical_debt", True)
            except (json.JSONDecodeError, OSError):
                pass

    @staticmethod
    def _is_current(
        related_ids: Optional[Set[str]],
        staged_items: Optional[Set[str]],
    ) -> bool:
        """Check if an item is related to current staged changes."""
        if staged_items is None:
            return True
        if not related_ids:
            return False
        return bool(related_ids & staged_items)

    @staticmethod
    def _tag_reason(
        msg: str,
        related_ids: Optional[Set[str]] = None,
        staged_items: Optional[Set[str]] = None,
    ) -> str:
        """Prefix *msg* with a source tag based on staged_items."""
        if staged_items is None:
            return msg
        if related_ids and related_ids & staged_items:
            return f"[当前] {msg}"
        return f"[预存] {msg}"

    def _check_claim_existence(
        self,
        ghost_files: List[str],
        staged_items: Optional[Set[str]],
        gaps: List[Dict[str, Any]],
        reasons: List[str],
        blocked_items: List[str],
    ) -> bool:
        """Rule 2: Ghost code detection.

        Returns ``True`` if the gate should be set to ``blocked``.
        Mutates *gaps*, *reasons*, and *blocked_items* in-place.
        """
        # Apply exclusions
        filtered_files = [
            f for f in ghost_files
            if not any(excl in f for excl in self._ghost_code_exclusions)
        ]

        OperationalLogger.get().debug("gate_claim_existence", "Claim existence check",
            ghost_count=len(filtered_files),
            excluded_count=len(ghost_files) - len(filtered_files))
        has_blocked = False
        if filtered_files:
            for f in sorted(filtered_files):
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

                # Incremental mode: only block if current commit related
                if not self.incremental_only or self._is_current({f}, staged_items):
                    blocked_items.append(msg)
                    has_blocked = True
                else:
                    self._historical_debt_count += 1
        return has_blocked

    def _check_dangling_claims(
        self,
        dangling_claims: List[Dict[str, Any]],
        staged_items: Optional[Set[str]],
        gaps: List[Dict[str, Any]],
        reasons: List[str],
        blocked_items: List[str],
    ) -> bool:
        """Rule 3: Dangling claims detection.

        Claims referencing non-existent tasks are blocked.
        Returns ``True`` if the gate should be set to ``blocked``.
        """
        OperationalLogger.get().debug("gate_dangling_claims", "Dangling claims check",
            dangling_count=len(dangling_claims))
        has_blocked = False
        for dc in dangling_claims:
            claim_id = dc.get("claim_id", "")
            related_task = dc.get("related_task", "")
            hint = resolve_hint(_gate_hints.get("dangling_claim", {}), "level1")
            msg = (
                hint.format(claim_id=claim_id, related_task=related_task)
                if hint
                else f"Claim {claim_id} 引用不存在的任务 {related_task}。"
            )
            gap_entry = {
                "item_id": claim_id,
                "item_type": "dangling_claim",
                "target_id": claim_id,
                "reason": msg,
            }
            gaps.append(gap_entry)
            reasons.append(self._tag_reason(msg, {claim_id}, staged_items))

            # Incremental mode: only block if current commit related
            if not self.incremental_only or self._is_current({claim_id}, staged_items):
                blocked_items.append(msg)
                has_blocked = True
            else:
                self._historical_debt_count += 1
        return has_blocked

    def _check_claim_evidence_gaps(
        self,
        claim_evidence_gaps: List[Dict[str, Any]],
        staged_items: Optional[Set[str]],
        gaps: List[Dict[str, Any]],
        reasons: List[str],
        blocked_items: List[str],
    ) -> bool:
        """Rule 4: Claim evidence gaps detection.

        Claims with failed or missing tests are blocked.
        Returns ``True`` if the gate should be set to ``blocked``.
        """
        has_blocked = False
        for ceg in claim_evidence_gaps:
            claim_id = ceg.get("claim_id", "")
            verification_status = ceg.get("verification_status", "")
            hint = resolve_hint(_gate_hints.get("claim_evidence_gap", {}), "level1")
            msg = (
                hint.format(claim_id=claim_id, status=verification_status)
                if hint
                else f"Claim {claim_id} 证据验证失败: {verification_status}"
            )
            gap_entry = {
                "item_id": claim_id,
                "item_type": "claim_evidence_gap",
                "target_id": claim_id,
                "reason": msg,
            }
            gaps.append(gap_entry)
            reasons.append(self._tag_reason(msg, {claim_id}, staged_items))

            # Only block for test failures, not for missing tests (warning)
            if verification_status in ("test_failed",):
                # Incremental mode: only block if current commit related
                if not self.incremental_only or self._is_current({claim_id}, staged_items):
                    blocked_items.append(msg)
                    has_blocked = True
                else:
                    self._historical_debt_count += 1

        return has_blocked

    def _check_ac_coverage(
        self,
        ac_gaps: List[Dict[str, Any]],
        staged_items: Optional[Set[str]],
        gaps: List[Dict[str, Any]],
        reasons: List[str],
        blocked_items: List[str],
    ) -> bool:
        """Rule 5: AC coverage check.

        Returns ``True`` if the gate should be set to ``blocked``.
        Mutates *gaps*, *reasons*, and *blocked_items* in-place.
        """
        OperationalLogger.get().debug("gate_ac_coverage", "AC coverage check",
            uncovered=len(ac_gaps))
        has_blocked = False
        for gap in ac_gaps:
            ac_id = gap.get("ac_id", gap.get("item_id", ""))
            task_id = gap.get("task_id", "")
            reason = gap.get("reason", gap.get("coverage_status", "no_test_coverage"))
            hint = resolve_hint(
                _gate_hints.get("ac_not_covered", {}), "level1"
            )
            msg = (
                hint.format(ac_id=ac_id, task_id=task_id, reason=reason)
                if hint
                else f"AC {ac_id} (task {task_id}) 未被测试覆盖: {reason}"
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
            related_ids = {task_id} if (task_id and gap.get("coverage_status") == "no_claim_for_task") else {ac_id}
            reasons.append(self._tag_reason(msg, related_ids, staged_items))

            if not self.incremental_only or self._is_current(related_ids, staged_items):
                blocked_items.append(msg)
                has_blocked = True
            else:
                self._historical_debt_count += 1
        return has_blocked

    def _check_invalid_task_references(
        self,
        invalid_task_references: Dict[str, List[Dict[str, Any]]],
        staged_items: Optional[Set[str]],
        reasons: List[str],
        blocked_items: List[str],
    ) -> bool:
        """Rule 9: Invalid task references detection.

        Tasks referencing non-existent requirements, ACs, modules, or constraints are blocked.
        Returns ``True`` if the gate should be set to ``blocked``.
        """
        OperationalLogger.get().debug("gate_invalid_task_refs", "Invalid task references check")
        has_blocked = False

        # Check invalid requirements
        for ref in invalid_task_references.get("invalid_requirements", []):
            task_id = ref.get("task_id", "")
            req_id = ref.get("req_id", "")
            msg = f"Task {task_id} 引用不存在的需求 {req_id}。"
            reasons.append(self._tag_reason(msg, {task_id}, staged_items))
            if not self.incremental_only or self._is_current({task_id}, staged_items):
                blocked_items.append(msg)
                has_blocked = True
            else:
                self._historical_debt_count += 1

        # Check invalid ACs
        for ref in invalid_task_references.get("invalid_acs", []):
            task_id = ref.get("task_id", "")
            ac_id = ref.get("ac_id", "")
            msg = f"Task {task_id} 引用不存在的验收标准 {ac_id}。"
            reasons.append(self._tag_reason(msg, {task_id}, staged_items))
            if not self.incremental_only or self._is_current({task_id}, staged_items):
                blocked_items.append(msg)
                has_blocked = True
            else:
                self._historical_debt_count += 1

        # Check invalid modules
        for ref in invalid_task_references.get("invalid_modules", []):
            task_id = ref.get("task_id", "")
            module_id = ref.get("module_id", "")
            msg = f"Task {task_id} 引用不存在的模块 {module_id}。"
            reasons.append(self._tag_reason(msg, {task_id}, staged_items))
            if not self.incremental_only or self._is_current({task_id}, staged_items):
                blocked_items.append(msg)
                has_blocked = True
            else:
                self._historical_debt_count += 1

        # Check invalid constraints
        for ref in invalid_task_references.get("invalid_constraints", []):
            task_id = ref.get("task_id", "")
            constraint_id = ref.get("constraint_id", "")
            msg = f"Task {task_id} 引用不存在的约束 {constraint_id}。"
            reasons.append(self._tag_reason(msg, {task_id}, staged_items))
            if not self.incremental_only or self._is_current({task_id}, staged_items):
                blocked_items.append(msg)
                has_blocked = True
            else:
                self._historical_debt_count += 1

        # Check invalid AC parents
        for ref in invalid_task_references.get("invalid_ac_parents", []):
            task_id = ref.get("task_id", "")
            ac_id = ref.get("ac_id", "")
            parent_req_id = ref.get("parent_req_id", "")
            msg = f"Task {task_id} 引用验收标准 {ac_id}，但其父需求 {parent_req_id} 未在关联需求中。"
            reasons.append(self._tag_reason(msg, {task_id}, staged_items))
            if not self.incremental_only or self._is_current({task_id}, staged_items):
                blocked_items.append(msg)
                has_blocked = True
            else:
                self._historical_debt_count += 1

        # Check invalid module code paths
        for ref in invalid_task_references.get("invalid_module_code_paths", []):
            task_id = ref.get("task_id", "")
            module_id = ref.get("module_id", "")
            code_path = ref.get("code_path", "")
            actual_module = ref.get("actual_module", "")
            msg = f"Task {task_id} 的代码路径 {code_path} 属于模块 {actual_module}，"
            msg += f"但 Task 声明归属模块 {module_id}（链条错位）。"
            reasons.append(self._tag_reason(msg, {task_id}, staged_items))
            if not self.incremental_only or self._is_current({task_id}, staged_items):
                blocked_items.append(msg)
                has_blocked = True
            else:
                self._historical_debt_count += 1

        return has_blocked

    def _process_must_gaps(
        self,
        gaps: List[Dict[str, Any]],
        resolved_gap_target_ids: Set[str],
        staged_items: Optional[Set[str]],
        reasons: List[str],
        blocked_items: List[str],
    ) -> bool:
        """Section 1.1: Must AC gaps processing."""
        has_blocked = False
        for gap in gaps:
            item_type = gap.get("item_type")
            item_id = gap.get("item_id", "")
            reason = gap.get("reason", "")
            target_id = gap.get("target_id", "")
            human_resolved = target_id in resolved_gap_target_ids
            is_stale = gap.get("stale", False)

            if item_type == "ac":
                hint = resolve_hint(_gate_hints.get("ac_missing_evidence", {}), "level1")
                msg = hint.format(item_id=item_id, reason=reason) if hint else f"验收标准缺失测试证据 ({item_id}): {reason}"
                related = {item_id} if item_id else None
                if human_resolved:
                    reasons.append(self._tag_reason(f"[已人工完成] {msg}", related, staged_items))
                    final_status = "human_resolved"
                else:
                    reasons.append(self._tag_reason(msg, related, staged_items))
                    if self._is_current(related, staged_items):
                        blocked_items.append(msg)
                        has_blocked = True
                        final_status = "blocked"
                    else:
                        final_status = "passed"
                if is_stale:
                    final_status = "skipped_stale"

                OperationalLogger.get().debug("gate_gap_eval", "Gap item evaluated",
                    item_id=item_id,
                    item_type=item_type,
                    is_stale=is_stale,
                    is_human_resolved=human_resolved,
                    final_status=final_status,
                    reason=reason[:200])
            elif not is_stale:
                OperationalLogger.get().debug(
                    "gate_gap_routed_to_should",
                    "Non-AC gap in _process_must_gaps — routed to should_gaps or Rules 3/4/9",
                    item_type=item_type, item_id=item_id,
                )
        return has_blocked

    def _process_must_risks(
        self,
        risks: List[Dict[str, Any]],
        accepted_risk_target_ids: Set[str],
        risk_staged: Optional[Set[str]],
        reasons: List[str],
        blocked_items: List[str],
    ) -> bool:
        """Section 1.2: Must risks processing."""
        has_blocked = False
        for risk in risks:
            severity = risk.get("severity")
            desc = risk.get("description", "")
            risk_id = risk.get("risk_id", "")
            suggested_action = risk.get("suggested_action", "")
            business_impact = risk.get("business_impact", "")
            risk_target_id = risk.get("target_id", "")
            human_accepted = risk_target_id in accepted_risk_target_ids

            effective_severity = "accepted" if human_accepted else severity
            risk_category = risk.get("risk_category", "")
            is_self_ref = risk_category == "self_referential_claim"
            if not is_self_ref:
                desc = risk.get("description", "")
                is_self_ref = "self-referential" in desc
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
                        has_blocked = True

                        if is_high_risk and (not suggested_action or not business_impact):
                            hint_missing = resolve_hint(_gate_hints.get("high_risk_missing_action", {}), "level1")
                            msg_missing = hint_missing.format(risk_id=risk_id) if hint_missing else f"高风险项 ({risk_id}) 缺失处理建议或业务影响描述"
                            blocked_items.append(msg_missing)
                            reasons.append(self._tag_reason(msg_missing, risk_related or None, risk_staged))
        return has_blocked

    def _process_should_gaps(
        self,
        gaps: List[Dict[str, Any]],
        resolved_gap_target_ids: Set[str],
        staged_items: Optional[Set[str]],
        reasons: List[str],
    ) -> tuple:
        """Section 2.2: Should-level gaps processing."""
        any_fail = False
        current_fail = False
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
                    any_fail = True
                    if self._is_current(related, staged_items):
                        current_fail = True
        return any_fail, current_fail

    def _process_should_risks(
        self,
        risks: List[Dict[str, Any]],
        accepted_risk_target_ids: Set[str],
        risk_staged: Optional[Set[str]],
        reasons: List[str],
    ) -> tuple:
        """Section 2.3: Should/Could severity risks processing."""
        any_fail = False
        current_fail = False
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
                    any_fail = True
                    if self._is_current(risk_related_fs or None, risk_staged):
                        current_fail = True
        return any_fail, current_fail

    def _compute_gate_decision(
        self,
        gate_decision: str,
        blocked_items: List[str],
        current_fail_detected: bool,
        any_fail_detected: bool,
        human_decisions_applied: int,
        staged_items: Optional[Set[str]],
        reasons: List[str],
        cov_violations: List[Dict[str, Any]],
        lint_violations: List[Dict[str, Any]],
        accepted_rule_target_ids: Optional[Set[str]] = None,
        rejected_rule_target_ids: Optional[Set[str]] = None,
        isolated_tasks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Sections 2.5 + 3: Final gate decision computation."""
        if current_fail_detected and gate_decision == "pass":
            gate_decision = "fail"

        # 2.5 Check coverage violations (warning-level, not blocking)
        if cov_violations:
            threshold = getattr(self, 'coverage_threshold', 80)
            active_violations = [
                cv for cv in cov_violations
                if not self.incremental_only or not cv.get("carried_over", False)
            ]
            if active_violations:
                for cv in active_violations:
                    tag = "[当前] " if staged_items else ""
                    reasons.append(
                        f"{tag}Coverage below {threshold}%: {cv.get('source_path', cv.get('file', ''))} ({cv.get('percent_covered', cv.get('percent', 0))}%)"
                    )
                if gate_decision not in ("blocked",):
                    gate_decision = "fail"
            historical_violations = len(cov_violations) - len(active_violations)
            if historical_violations > 0:
                self._historical_debt_count += historical_violations

        # 2.6 Check lint violations (warning-level, not blocking)
        if lint_violations:
            active_lint_violations = [
                lv for lv in lint_violations
                if not self.incremental_only or not lv.get("carried_over", False)
            ]
            if active_lint_violations:
                for lv in active_lint_violations:
                    tag = "[当前] " if staged_items else ""
                    reasons.append(
                        f"{tag}Lint violations: {lv['source_path']} "
                        f"({lv['violations_count']} issues)"
                    )
                if gate_decision not in ("blocked",):
                    gate_decision = "fail"
            historical_lint = len(lint_violations) - len(active_lint_violations)
            if historical_lint > 0:
                self._historical_debt_count += historical_lint

        # 2.7 Isolated tasks (warning-level, not blocking)
        if isolated_tasks:
            for t in isolated_tasks:
                tag = "[当前] " if staged_items else ""
                reasons.append(
                    f"{tag}[告警] 孤立任务 {t['task_id']}: {t.get('reason', '无关联需求/AC')}"
                )

        # 3. Handle 'pass'
        if gate_decision == "pass" and not reasons:
            hint = resolve_hint(_gate_hints.get("all_gates_passed", {}), "level1")
            reasons.append(hint if hint else "所有质量门禁规则均已通过，无阻塞项或风险项。")

        # Add historical debt summary in incremental mode
        if self.incremental_only and self._historical_debt_count > 0:
            if not self.show_historical_debt:
                # Show summary and suggest how to view details
                reasons.append(f"📊 {self._historical_debt_count} historical debts exist (use --show-debt to view details)")
            else:
                # Show summary only without prompt since details are already shown
                reasons.append(f"📊 {self._historical_debt_count} historical debts exist")

        result: Dict[str, Any] = {
            "gate_decision": gate_decision,
            "reasons": reasons,
            "blocked_items": blocked_items,
            "human_decisions_applied": human_decisions_applied,
            "incremental_mode": self.incremental_only,
            "show_historical_debt": self.show_historical_debt,
            "historical_debt_count": self._historical_debt_count,
        }
        if accepted_rule_target_ids:
            result["accepted_rule_target_ids"] = list(accepted_rule_target_ids)
        if rejected_rule_target_ids:
            result["rejected_rule_target_ids"] = list(rejected_rule_target_ids)
        return result

    def evaluate(
        self,
        gaps: List[Dict[str, Any]],
        risks: List[Dict[str, Any]],
        compliance_res: Optional[Dict[str, Any]] = None,
        staged_items: Optional[Set[str]] = None,
        directly_staged_items: Optional[Set[str]] = None,
        human_decisions: Optional[Any] = None,
        ghost_files: Optional[List[str]] = None,
        ac_gaps: Optional[List[Dict[str, Any]]] = None,
        dangling_claims: Optional[List[Dict[str, Any]]] = None,
        claim_evidence_gaps: Optional[List[Dict[str, Any]]] = None,
        cov_violations: Optional[List[Dict[str, Any]]] = None,
        lint_violations: Optional[List[Dict[str, Any]]] = None,
        invalid_task_references: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        isolated_tasks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate merge gate criteria.

        Args:
            gaps: Identified gaps from analyzers.
            risks: Enriched risks from RiskAdvisor.
            compliance_res: Result from ArchitectureComplianceChecker.
            staged_items: Set of claim/task/AC/requirement IDs affected by current commit.
            directly_staged_items: Set of directly modified claim/task/AC/requirement IDs.
            human_decisions: Optional human decisions.
            ghost_files: List of ghost files (not covered by any claim).
            ac_gaps: List of AC coverage gaps.
            dangling_claims: List of claims referencing non-existent tasks.
            claim_evidence_gaps: List of claim evidence verification failures.
            cov_violations: List of coverage violations.

        Returns:
            A dict containing gate_decision, reasons, blocked_items, human_decisions_applied.
        """
        # Normalize human_decisions
        decisions_list: List[Dict[str, Any]] = []
        if human_decisions is not None:
            if isinstance(human_decisions, dict) and "decisions" in human_decisions:
                decisions_list = human_decisions["decisions"] or []
            elif isinstance(human_decisions, list):
                decisions_list = human_decisions

        accepted_risk_target_ids: Set[str] = set()
        resolved_gap_target_ids: Set[str] = set()
        accepted_rule_target_ids: Set[str] = set()
        rejected_rule_target_ids: Set[str] = set()

        for d in decisions_list:
            action = d.get("action", "")
            target_id = d.get("targetId", "")
            category = d.get("category", "")
            if action == "accept_risk" and target_id:
                accepted_risk_target_ids.add(target_id)
            elif action == "mark_complete" and target_id:
                resolved_gap_target_ids.add(target_id)
            elif category == "accepted_rule" and target_id:
                if action == "reconfirm":
                    accepted_rule_target_ids.add(target_id)
                elif action == "reject":
                    rejected_rule_target_ids.add(target_id)

        human_decisions_applied = len(accepted_risk_target_ids) + len(resolved_gap_target_ids) + len(accepted_rule_target_ids) + len(rejected_rule_target_ids)

        risk_staged = directly_staged_items if directly_staged_items is not None else staged_items
        gate_decision = "pass"
        reasons: List[str] = []
        blocked_items: List[str] = []

        # ----------------------------------------------------
        # Rule 2: Ghost code detection
        # ----------------------------------------------------
        if ghost_files is not None and staged_items is not None:
            if self._check_claim_existence(
                ghost_files, staged_items, gaps, reasons, blocked_items
            ):
                gate_decision = "blocked"

        # ----------------------------------------------------
        # Rule 3: Dangling claims
        # ----------------------------------------------------
        if dangling_claims is not None:
            if self._check_dangling_claims(
                dangling_claims, staged_items, gaps, reasons, blocked_items
            ):
                gate_decision = "blocked"

        # ----------------------------------------------------
        # Rule 4: Claim evidence gaps
        # ----------------------------------------------------
        if claim_evidence_gaps is not None:
            if self._check_claim_evidence_gaps(
                claim_evidence_gaps, staged_items, gaps, reasons, blocked_items
            ):
                gate_decision = "blocked"

        # ----------------------------------------------------
        # Rule 5: AC coverage
        # ----------------------------------------------------
        if ac_gaps is not None:
            if self._check_ac_coverage(
                ac_gaps, staged_items, gaps, reasons, blocked_items,
            ):
                gate_decision = "blocked"

        # ----------------------------------------------------
        # Rule 9: Invalid task references
        # ----------------------------------------------------
        if invalid_task_references is not None:
            if self._check_invalid_task_references(
                invalid_task_references, staged_items, reasons, blocked_items
            ):
                gate_decision = "blocked"

        # ----------------------------------------------------
        # Section 1: Evaluate 'blocked' conditions (MUST/critical)
        # ----------------------------------------------------
        if self._process_must_gaps(
            gaps, resolved_gap_target_ids, staged_items, reasons, blocked_items
        ):
            gate_decision = "blocked"

        if self._process_must_risks(
            risks, accepted_risk_target_ids, risk_staged, reasons, blocked_items
        ):
            gate_decision = "blocked"

        # 1.3 Check Must architecture violations
        if compliance_res:
            violations = compliance_res.get("architecture_violations", [])
            for v in violations:
                rule_id = v.get("rule_id", "")
                msg_violation = v.get("message", "")
                hint = resolve_hint(_gate_hints.get("must_arch_violation", {}), "level1")
                msg = hint.format(rule_id=rule_id, msg_violation=msg_violation) if hint else f"违反 MUST 级别架构约束 ({rule_id}): {msg_violation}"
                reasons.append(self._tag_reason(msg, None, staged_items))
                blocked_items.append(msg)
                gate_decision = "blocked"

            status_list = compliance_res.get("architecture_compliance_status", [])
            for status_item in status_list:
                rule_id = status_item.get("rule_id", "")
                status = status_item.get("status")
                severity = status_item.get("severity", "must")
                if status == "violated" and severity == "must":
                    hint = resolve_hint(_gate_hints.get("arch_rule_violated", {}), "level1")
                    msg = hint.format(rule_id=rule_id) if hint else f"架构规则被违规触发 ({rule_id})"
                    if not any(rule_id in item for item in blocked_items):
                        reasons.append(self._tag_reason(msg, None, staged_items))
                        blocked_items.append(msg)
                        gate_decision = "blocked"

        # 1.4 Process proposal risks/gaps from architecture change governance
        if compliance_res:
            for risk in compliance_res.get("proposal_risks", []):
                risk_id = risk.get("risk_id", "")
                desc = risk.get("description", "")
                msg = f"[架构变更提案风险] {risk_id}: {desc}"
                reasons.append(self._tag_reason(msg, None, staged_items))
                if staged_items is None:
                    blocked_items.append(msg)
                    gate_decision = "blocked"

            for gap in compliance_res.get("proposal_gaps", []):
                gap_id = gap.get("item_id", "")
                reason_text = gap.get("reason", "")
                msg = f"[架构变更治理缺口] {gap_id}: {reason_text}"
                reasons.append(self._tag_reason(msg, None, staged_items))
                if staged_items is None:
                    blocked_items.append(msg)
                    gate_decision = "blocked"

        # ----------------------------------------------------
        # Section 2: Evaluate 'fail' conditions (SHOULD issues)
        # ----------------------------------------------------
        any_fail_detected = False
        current_fail_detected = False

        # 2.1 Check unclear architecture constraints
        if compliance_res:
            unclear_constraints = compliance_res.get("unclear_constraints", [])
            for uc in unclear_constraints:
                rule_id = uc.get("rule_id", "")
                reason = uc.get("reason", "")
                hint = resolve_hint(_gate_hints.get("unclear_constraint_rule", {}), "level1")
                msg = hint.format(rule_id=rule_id, reason=reason) if hint else f"存在不明确的架构约束规则 ({rule_id}): {reason}"
                reasons.append(self._tag_reason(msg, None, staged_items))
                any_fail_detected = True
                if staged_items is None:
                    current_fail_detected = True

            status_list = compliance_res.get("architecture_compliance_status", [])
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

        # Section 2.2 + 2.3
        g_any, g_cur = self._process_should_gaps(
            gaps, resolved_gap_target_ids, staged_items, reasons
        )
        any_fail_detected = any_fail_detected or g_any
        current_fail_detected = current_fail_detected or g_cur

        r_any, r_cur = self._process_should_risks(
            risks, accepted_risk_target_ids, risk_staged, reasons
        )
        any_fail_detected = any_fail_detected or r_any
        current_fail_detected = current_fail_detected or r_cur

        # ----------------------------------------------------
        # Final decision
        # ----------------------------------------------------
        return self._compute_gate_decision(
            gate_decision, blocked_items,
            current_fail_detected, any_fail_detected,
            human_decisions_applied, staged_items,
            reasons,
            cov_violations or [],
            lint_violations or [],
            accepted_rule_target_ids, rejected_rule_target_ids,
            isolated_tasks or [],
        )
