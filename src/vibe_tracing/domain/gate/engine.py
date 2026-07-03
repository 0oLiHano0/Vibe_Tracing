"""
Merge Gate Engine — 纯 issue 检测器。

职责：检测所有门禁问题，返回 List[DetectedIssue]。
不计算信号、不判定状态、不决策门禁——由 pipeline 层调度。

spec_stage7_business_logic_v2.md 六类问题 + 架构合规检测。
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from vibe_tracing.domain.gate.types import DetectedIssue, Severity
from vibe_tracing.infra.config.hint_loader import load_hints, resolve_hint
from vibe_tracing.infra.logging.logger import OperationalLogger

_gate_hints = load_hints("gate_decision")


class MergeGateEngine:

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self._ghost_code_exclusions: List[str] = []
        self._load_exclusions()

    def _load_exclusions(self) -> None:
        import json
        config_path = self.project_root / ".vibetracing" / "config.json"
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                self._ghost_code_exclusions = config.get("ghost_code_exclusions", [])
            except (json.JSONDecodeError, OSError):
                pass

    def detect_all_issues(
        self,
        ghost_files: Optional[List[str]] = None,
        ac_gaps: Optional[List[Dict[str, Any]]] = None,
        dangling_claims: Optional[List[Dict[str, Any]]] = None,
        claim_evidence_gaps: Optional[List[Dict[str, Any]]] = None,
        invalid_task_references: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        isolated_tasks: Optional[List[Dict[str, Any]]] = None,
        cov_violations: Optional[List[Dict[str, Any]]] = None,
        lint_violations: Optional[List[Dict[str, Any]]] = None,
        gaps: Optional[List[Dict[str, Any]]] = None,
        risks: Optional[List[Dict[str, Any]]] = None,
        compliance_res: Optional[Dict[str, Any]] = None,
    ) -> List[DetectedIssue]:
        issues: List[DetectedIssue] = []

        if ghost_files is not None:
            issues.extend(self._check_claim_existence(ghost_files))
        if dangling_claims is not None:
            issues.extend(self._check_dangling_claims(dangling_claims))
        if claim_evidence_gaps is not None:
            issues.extend(self._check_claim_evidence_gaps(claim_evidence_gaps))
        if ac_gaps is not None:
            issues.extend(self._check_ac_coverage(ac_gaps))
        if invalid_task_references is not None:
            issues.extend(self._check_invalid_task_references(invalid_task_references))
        if gaps is not None:
            issues.extend(self._check_must_gaps(gaps))
            issues.extend(self._check_should_gaps(gaps))
        if risks is not None:
            issues.extend(self._check_must_risks(risks))
            issues.extend(self._check_should_risks(risks))
        if compliance_res is not None:
            issues.extend(self._check_architecture_violations(compliance_res))
            issues.extend(self._check_proposal_governance(compliance_res))
            issues.extend(self._check_unclear_constraints(compliance_res))
        if cov_violations is not None:
            issues.extend(self._check_coverage_violations(cov_violations))
        if lint_violations is not None:
            issues.extend(self._check_lint_violations(lint_violations))
        if isolated_tasks is not None:
            issues.extend(self._check_isolated_tasks(isolated_tasks))

        return issues

    # ── Rule 2: Ghost code ──────────────────────────────────────────

    def _check_claim_existence(self, ghost_files: List[str]) -> List[DetectedIssue]:
        filtered = [
            f for f in ghost_files
            if not any(excl in f for excl in self._ghost_code_exclusions)
        ]
        OperationalLogger.get().debug(
            "gate_claim_existence", "Claim existence check",
            ghost_count=len(filtered),
            excluded_count=len(ghost_files) - len(filtered),
        )
        issues: List[DetectedIssue] = []
        for f in sorted(filtered):
            hint = resolve_hint(_gate_hints.get("missing_claim", {}), "level1")
            reason = (
                hint.format(file=f) if hint
                else f"业务文件 {f} 未被任何 Claim 覆盖，需要创建 Claim 声明该文件的变更。"
            )
            issues.append(DetectedIssue(
                issue_id=f"no_claim:{f}",
                issue_type="no_claim",
                severity=Severity.BLOCK,
                reason=reason,
                related_task_id="",
                gap_targets=[f],
                item_id=f,
            ))
        return issues

    # ── Rule 3: Dangling claims ─────────────────────────────────────

    def _check_dangling_claims(self, dangling_claims: List[Dict[str, Any]]) -> List[DetectedIssue]:
        OperationalLogger.get().debug(
            "gate_dangling_claims", "Dangling claims check",
            dangling_count=len(dangling_claims),
        )
        issues: List[DetectedIssue] = []
        for dc in dangling_claims:
            claim_id = dc.get("claim_id", "")
            related_task = dc.get("related_task", "")
            hint = resolve_hint(_gate_hints.get("dangling_claim", {}), "level1")
            reason = (
                hint.format(claim_id=claim_id, related_task=related_task) if hint
                else f"Claim {claim_id} 引用不存在的任务 {related_task}。"
            )
            issues.append(DetectedIssue(
                issue_id=f"chain_broken:{claim_id}",
                issue_type="chain_broken",
                severity=Severity.BLOCK,
                reason=reason,
                related_task_id=related_task,
                gap_targets=[related_task] if related_task else [claim_id],
                item_id=claim_id,
            ))
        return issues

    # ── Rule 4: Claim evidence gaps ─────────────────────────────────

    def _check_claim_evidence_gaps(self, claim_evidence_gaps: List[Dict[str, Any]]) -> List[DetectedIssue]:
        issues: List[DetectedIssue] = []
        for ceg in claim_evidence_gaps:
            claim_id = ceg.get("claim_id", "")
            status = ceg.get("verification_status", "")
            hint = resolve_hint(_gate_hints.get("claim_evidence_gap", {}), "level1")
            reason = (
                hint.format(claim_id=claim_id, status=status) if hint
                else f"Claim {claim_id} 证据验证失败: {status}"
            )
            severity = Severity.BLOCK if status == "test_failed" else Severity.WARNING
            issues.append(DetectedIssue(
                issue_id=f"task_failed:{claim_id}",
                issue_type="task_failed",
                severity=severity,
                reason=reason,
                related_task_id=ceg.get("related_task", ""),
                gap_targets=[claim_id],
                item_id=claim_id,
            ))
        return issues

    # ── Rule 5: AC coverage ─────────────────────────────────────────

    def _check_ac_coverage(self, ac_gaps: List[Dict[str, Any]]) -> List[DetectedIssue]:
        OperationalLogger.get().debug(
            "gate_ac_coverage", "AC coverage check", uncovered=len(ac_gaps),
        )
        issues: List[DetectedIssue] = []
        for gap in ac_gaps:
            ac_id = gap.get("ac_id", gap.get("item_id", ""))
            task_id = gap.get("task_id", "")
            raw_reason = gap.get("reason", gap.get("coverage_status", "no_test_coverage"))
            hint = resolve_hint(_gate_hints.get("ac_not_covered", {}), "level1")
            reason = (
                hint.format(ac_id=ac_id, task_id=task_id, reason=raw_reason) if hint
                else f"AC {ac_id} (task {task_id}) 未被测试覆盖: {raw_reason}"
            )
            related_task = task_id if (task_id and gap.get("coverage_status") == "no_claim_for_task") else ""
            issues.append(DetectedIssue(
                issue_id=f"no_claim:{ac_id}",
                issue_type="no_claim",
                severity=Severity.BLOCK,
                reason=reason,
                related_task_id=related_task,
                gap_targets=[task_id] if related_task else [ac_id],
                item_id=ac_id,
            ))
        return issues

    # ── Rule 9: Invalid task references ─────────────────────────────

    def _check_invalid_task_references(
        self, invalid_refs: Dict[str, List[Dict[str, Any]]]
    ) -> List[DetectedIssue]:
        OperationalLogger.get().debug("gate_invalid_task_refs", "Invalid task references check")
        issues: List[DetectedIssue] = []

        for ref in invalid_refs.get("invalid_requirements", []):
            task_id = ref.get("task_id", "")
            req_id = ref.get("req_id", "")
            issues.append(DetectedIssue(
                issue_id=f"chain_broken:{task_id}:{req_id}",
                issue_type="chain_broken",
                severity=Severity.BLOCK,
                reason=f"Task {task_id} 引用不存在的需求 {req_id}。",
                related_task_id=task_id,
                gap_targets=[req_id],
                item_id=task_id,
            ))

        for ref in invalid_refs.get("invalid_acs", []):
            task_id = ref.get("task_id", "")
            ac_id = ref.get("ac_id", "")
            issues.append(DetectedIssue(
                issue_id=f"chain_broken:{task_id}:{ac_id}",
                issue_type="chain_broken",
                severity=Severity.BLOCK,
                reason=f"Task {task_id} 引用不存在的验收标准 {ac_id}。",
                related_task_id=task_id,
                gap_targets=[ac_id],
                item_id=task_id,
            ))

        for ref in invalid_refs.get("invalid_modules", []):
            task_id = ref.get("task_id", "")
            module_id = ref.get("module_id", "")
            issues.append(DetectedIssue(
                issue_id=f"chain_broken:{task_id}:{module_id}",
                issue_type="chain_broken",
                severity=Severity.BLOCK,
                reason=f"Task {task_id} 引用不存在的模块 {module_id}。",
                related_task_id=task_id,
                gap_targets=[module_id],
                item_id=task_id,
            ))

        for ref in invalid_refs.get("invalid_constraints", []):
            task_id = ref.get("task_id", "")
            cid = ref.get("constraint_id", "")
            issues.append(DetectedIssue(
                issue_id=f"chain_broken:{task_id}:{cid}",
                issue_type="chain_broken",
                severity=Severity.BLOCK,
                reason=f"Task {task_id} 引用不存在的约束 {cid}。",
                related_task_id=task_id,
                gap_targets=[cid],
                item_id=task_id,
            ))

        for ref in invalid_refs.get("invalid_ac_parents", []):
            task_id = ref.get("task_id", "")
            ac_id = ref.get("ac_id", "")
            parent_req_id = ref.get("parent_req_id", "")
            issues.append(DetectedIssue(
                issue_id=f"chain_misaligned:{task_id}:{ac_id}",
                issue_type="chain_misaligned",
                severity=Severity.BLOCK,
                reason=f"Task {task_id} 引用验收标准 {ac_id}，但其父需求 {parent_req_id} 未在关联需求中。",
                related_task_id=task_id,
                gap_targets=[ac_id],
                item_id=task_id,
            ))

        for ref in invalid_refs.get("invalid_module_code_paths", []):
            task_id = ref.get("task_id", "")
            module_id = ref.get("module_id", "")
            code_path = ref.get("code_path", "")
            actual_module = ref.get("actual_module", "")
            issues.append(DetectedIssue(
                issue_id=f"chain_misaligned:{task_id}:{code_path}",
                issue_type="chain_misaligned",
                severity=Severity.BLOCK,
                reason=(
                    f"Task {task_id} 的代码路径 {code_path} 属于模块 {actual_module}，"
                    f"但 Task 声明归属模块 {module_id}（链条错位）。"
                ),
                related_task_id=task_id,
                gap_targets=[module_id],
                item_id=task_id,
            ))

        return issues

    # ── Architecture compliance: must gaps ───────────────────────────

    def _check_must_gaps(self, gaps: List[Dict[str, Any]]) -> List[DetectedIssue]:
        issues: List[DetectedIssue] = []
        for gap in gaps:
            if gap.get("item_type") != "ac":
                continue
            if gap.get("stale", False):
                continue
            item_id = gap.get("item_id", "")
            reason = gap.get("reason", "")
            hint = resolve_hint(_gate_hints.get("ac_missing_evidence", {}), "level1")
            msg = hint.format(item_id=item_id, reason=reason) if hint else f"验收标准缺失测试证据 ({item_id}): {reason}"
            issues.append(DetectedIssue(
                issue_id=f"task_failed:{item_id}",
                issue_type="task_failed",
                severity=Severity.BLOCK,
                reason=msg,
                related_task_id="",
                gap_targets=[item_id] if item_id else [],
                item_id=item_id,
            ))
        return issues

    # ── Architecture compliance: must risks ──────────────────────────

    def _check_must_risks(self, risks: List[Dict[str, Any]]) -> List[DetectedIssue]:
        issues: List[DetectedIssue] = []
        for risk in risks:
            severity = risk.get("severity")
            risk_id = risk.get("risk_id", "")
            desc = risk.get("description", "")
            risk_category = risk.get("risk_category", "")
            is_self_ref = risk_category == "self_referential_claim" or "self-referential" in desc
            is_high_risk = severity == "must"

            if not (is_high_risk or is_self_ref):
                continue

            hint = resolve_hint(_gate_hints.get("high_risk_or_self_ref", {}), "level1")
            msg = hint.format(risk_id=risk_id, desc=desc) if hint else f"高风险或不自证违规 ({risk_id}): {desc}"
            gap_targets = [risk_id] if risk_id else []
            claim_id = risk.get("claim_id", "")
            if claim_id:
                gap_targets.append(claim_id)

            issues.append(DetectedIssue(
                issue_id=f"chain_broken:{risk_id}",
                issue_type="chain_broken",
                severity=Severity.BLOCK,
                reason=msg,
                related_task_id="",
                gap_targets=gap_targets,
                item_id=risk_id,
            ))

            suggested_action = risk.get("suggested_action", "")
            business_impact = risk.get("business_impact", "")
            if is_high_risk and (not suggested_action or not business_impact):
                hint_missing = resolve_hint(_gate_hints.get("high_risk_missing_action", {}), "level1")
                msg_missing = hint_missing.format(risk_id=risk_id) if hint_missing else f"高风险项 ({risk_id}) 缺失处理建议或业务影响描述"
                issues.append(DetectedIssue(
                    issue_id=f"chain_broken:{risk_id}:missing_action",
                    issue_type="chain_broken",
                    severity=Severity.BLOCK,
                    reason=msg_missing,
                    related_task_id="",
                    gap_targets=gap_targets,
                    item_id=risk_id,
                ))
        return issues

    # ── Architecture compliance: violations ──────────────────────────

    def _check_architecture_violations(self, compliance_res: Dict[str, Any]) -> List[DetectedIssue]:
        issues: List[DetectedIssue] = []
        seen_rule_ids: set = set()

        for v in compliance_res.get("architecture_violations", []):
            rule_id = v.get("rule_id", "")
            msg_violation = v.get("message", "")
            hint = resolve_hint(_gate_hints.get("must_arch_violation", {}), "level1")
            msg = hint.format(rule_id=rule_id, msg_violation=msg_violation) if hint else f"违反 MUST 级别架构约束 ({rule_id}): {msg_violation}"
            issues.append(DetectedIssue(
                issue_id=f"chain_broken:{rule_id}",
                issue_type="chain_broken",
                severity=Severity.BLOCK,
                reason=msg,
                related_task_id="",
                gap_targets=[rule_id] if rule_id else [],
                item_id=rule_id,
            ))
            seen_rule_ids.add(rule_id)

        for status_item in compliance_res.get("architecture_compliance_status", []):
            rule_id = status_item.get("rule_id", "")
            status = status_item.get("status")
            sev = status_item.get("severity", "must")
            if status == "violated" and sev == "must" and rule_id not in seen_rule_ids:
                hint = resolve_hint(_gate_hints.get("arch_rule_violated", {}), "level1")
                msg = hint.format(rule_id=rule_id) if hint else f"架构规则被违规触发 ({rule_id})"
                issues.append(DetectedIssue(
                    issue_id=f"chain_broken:{rule_id}",
                    issue_type="chain_broken",
                    severity=Severity.BLOCK,
                    reason=msg,
                    related_task_id="",
                    gap_targets=[rule_id] if rule_id else [],
                    item_id=rule_id,
                ))
        return issues

    # ── Architecture compliance: proposal governance ─────────────────

    def _check_proposal_governance(self, compliance_res: Dict[str, Any]) -> List[DetectedIssue]:
        issues: List[DetectedIssue] = []

        for risk in compliance_res.get("proposal_risks", []):
            risk_id = risk.get("risk_id", "")
            desc = risk.get("description", "")
            issues.append(DetectedIssue(
                issue_id=f"chain_broken:proposal:{risk_id}",
                issue_type="chain_broken",
                severity=Severity.BLOCK,
                reason=f"[架构变更提案风险] {risk_id}: {desc}",
                related_task_id="",
                gap_targets=[risk_id] if risk_id else [],
                item_id=risk_id,
            ))

        for gap in compliance_res.get("proposal_gaps", []):
            gap_id = gap.get("item_id", "")
            reason_text = gap.get("reason", "")
            issues.append(DetectedIssue(
                issue_id=f"chain_broken:proposal_gap:{gap_id}",
                issue_type="chain_broken",
                severity=Severity.BLOCK,
                reason=f"[架构变更治理缺口] {gap_id}: {reason_text}",
                related_task_id="",
                gap_targets=[gap_id] if gap_id else [],
                item_id=gap_id,
            ))

        return issues

    # ── Architecture compliance: should gaps ────────────────────────

    def _check_should_gaps(self, gaps: List[Dict[str, Any]]) -> List[DetectedIssue]:
        issues: List[DetectedIssue] = []
        for gap in gaps:
            if gap.get("item_type") == "ac":
                continue
            item_type = gap.get("item_type", "")
            item_id = gap.get("item_id", "")
            reason = gap.get("reason", "")
            hint = resolve_hint(_gate_hints.get("non_blocking_gap", {}), "level1")
            msg = hint.format(item_type=item_type, item_id=item_id, reason=reason) if hint else f"非阻塞缺口 ({item_type} {item_id}): {reason}"
            issues.append(DetectedIssue(
                issue_id=f"substandard:{item_id}",
                issue_type="substandard",
                severity=Severity.WARNING,
                reason=msg,
                related_task_id="",
                gap_targets=[item_id] if item_id else [],
                item_id=item_id,
            ))
        return issues

    # ── Architecture compliance: should risks ────────────────────────

    def _check_should_risks(self, risks: List[Dict[str, Any]]) -> List[DetectedIssue]:
        issues: List[DetectedIssue] = []
        for risk in risks:
            severity = risk.get("severity")
            confidence = risk.get("confidence")
            risk_type = risk.get("type")
            is_speculative = confidence == "low_confidence" or risk_type == "suggestion"
            is_should_could = severity in ("should", "could")
            if not (is_should_could or is_speculative):
                continue

            risk_id = risk.get("risk_id", "")
            desc = risk.get("description", "")
            hint = resolve_hint(_gate_hints.get("low_medium_risk", {}), "level1")
            msg = hint.format(risk_id=risk_id, desc=desc) if hint else f"低/中风险或推测性风险 ({risk_id}): {desc}"
            gap_targets = [risk_id] if risk_id else []
            claim_id = risk.get("claim_id", "")
            if claim_id:
                gap_targets.append(claim_id)
            issues.append(DetectedIssue(
                issue_id=f"substandard:{risk_id}",
                issue_type="substandard",
                severity=Severity.WARNING,
                reason=msg,
                related_task_id="",
                gap_targets=gap_targets,
                item_id=risk_id,
            ))
        return issues

    # ── Architecture compliance: unclear constraints ─────────────────

    def _check_unclear_constraints(self, compliance_res: Dict[str, Any]) -> List[DetectedIssue]:
        issues: List[DetectedIssue] = []
        seen_msgs: set = set()

        for uc in compliance_res.get("unclear_constraints", []):
            rule_id = uc.get("rule_id", "")
            reason = uc.get("reason", "")
            hint = resolve_hint(_gate_hints.get("unclear_constraint_rule", {}), "level1")
            msg = hint.format(rule_id=rule_id, reason=reason) if hint else f"存在不明确的架构约束规则 ({rule_id}): {reason}"
            issues.append(DetectedIssue(
                issue_id=f"substandard:unclear:{rule_id}",
                issue_type="substandard",
                severity=Severity.WARNING,
                reason=msg,
                related_task_id="",
                gap_targets=[rule_id] if rule_id else [],
                item_id=rule_id,
            ))

        for status_item in compliance_res.get("architecture_compliance_status", []):
            if status_item.get("status") != "unclear":
                continue
            rule_id = status_item.get("rule_id", "")
            hint = resolve_hint(_gate_hints.get("arch_rule_unclear", {}), "level1")
            msg = hint.format(rule_id=rule_id) if hint else f"架构规则状态不明确 ({rule_id})"
            if msg not in seen_msgs:
                seen_msgs.add(msg)
                issues.append(DetectedIssue(
                    issue_id=f"substandard:unclear_status:{rule_id}",
                    issue_type="substandard",
                    severity=Severity.WARNING,
                    reason=msg,
                    related_task_id="",
                    gap_targets=[rule_id] if rule_id else [],
                    item_id=rule_id,
                ))
        return issues

    # ── Coverage violations ─────────────────────────────────────────

    def _check_coverage_violations(self, cov_violations: List[Dict[str, Any]]) -> List[DetectedIssue]:
        threshold = 80
        issues: List[DetectedIssue] = []
        for cv in cov_violations:
            source = cv.get("source_path", cv.get("file", ""))
            pct = cv.get("percent_covered", cv.get("percent", 0))
            issues.append(DetectedIssue(
                issue_id=f"substandard:coverage:{source}",
                issue_type="substandard",
                severity=Severity.WARNING,
                reason=f"Coverage below {threshold}%: {source} ({pct}%)",
                related_task_id="",
                gap_targets=[source] if source else [],
                item_id=source,
            ))
        return issues

    # ── Lint violations ─────────────────────────────────────────────

    def _check_lint_violations(self, lint_violations: List[Dict[str, Any]]) -> List[DetectedIssue]:
        issues: List[DetectedIssue] = []
        for lv in lint_violations:
            source = lv.get("source_path", "")
            count = lv.get("violations_count", 0)
            issues.append(DetectedIssue(
                issue_id=f"substandard:lint:{source}",
                issue_type="substandard",
                severity=Severity.WARNING,
                reason=f"Lint violation: {source} ({count} issues)",
                related_task_id="",
                gap_targets=[source] if source else [],
                item_id=source,
            ))
        return issues

    # ── Isolated tasks ──────────────────────────────────────────────

    def _check_isolated_tasks(self, isolated_tasks: List[Dict[str, Any]]) -> List[DetectedIssue]:
        issues: List[DetectedIssue] = []
        for t in isolated_tasks:
            task_id = t.get("task_id", "")
            reason = t.get("reason", "无关联需求/AC")
            issues.append(DetectedIssue(
                issue_id=f"isolated_task:{task_id}",
                issue_type="isolated_task",
                severity=Severity.WARNING,
                reason=f"[告警] 孤立任务 {task_id}: {reason}",
                related_task_id=task_id,
                gap_targets=[task_id] if task_id else [],
                item_id=task_id,
            ))
        return issues
