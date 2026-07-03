"""
信号计算器 — 将 DetectedIssue 转化为 IssueSignal 五元信号。

解释层的核心：为每个 issue 计算 (observed, activated, resolved, accepted, severity)，
规则引擎 F 消费这些信号产出 OutputState。

design_rule_engine.md §11.2 信号构造规则。
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from vibe_tracing.domain.gate.baseline import BaselineManager, compute_fingerprint
from vibe_tracing.domain.gate.types import DetectedIssue, IssueSignal, Severity


def parse_human_decisions(human_decisions: Optional[Dict[str, Any]]) -> Tuple[
    Set[str], Set[str], Set[str], Set[str]
]:
    """解析 human_decisions，返回四个集合。

    (accepted_risk_ids, resolved_gap_ids, accepted_rule_ids, rejected_rule_ids)
    """
    accepted_risk_ids: Set[str] = set()
    resolved_gap_ids: Set[str] = set()
    accepted_rule_ids: Set[str] = set()
    rejected_rule_ids: Set[str] = set()

    if human_decisions is None:
        return accepted_risk_ids, resolved_gap_ids, accepted_rule_ids, rejected_rule_ids

    decisions_list: List[Dict[str, Any]] = []
    if isinstance(human_decisions, dict) and "decisions" in human_decisions:
        decisions_list = human_decisions["decisions"] or []
    elif isinstance(human_decisions, list):
        decisions_list = human_decisions

    for d in decisions_list:
        action = d.get("action", "")
        target_id = d.get("targetId", "")
        category = d.get("category", "")
        if action == "accept_risk" and target_id:
            accepted_risk_ids.add(target_id)
        elif action == "mark_complete" and target_id:
            resolved_gap_ids.add(target_id)
        elif category == "accepted_rule" and target_id:
            if action == "reconfirm":
                accepted_rule_ids.add(target_id)
            elif action == "reject":
                rejected_rule_ids.add(target_id)

    return accepted_risk_ids, resolved_gap_ids, accepted_rule_ids, rejected_rule_ids


class SignalComputer:
    """信号计算器：DetectedIssue → IssueSignal。"""

    def __init__(
        self,
        baseline: BaselineManager,
        current_commit_task_set: Set[str],
        human_decisions: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._baseline = baseline
        self._current_commit_task_set = current_commit_task_set
        (
            self._accepted_risk_ids,
            self._resolved_gap_ids,
            self._accepted_rule_ids,
            self._rejected_rule_ids,
        ) = parse_human_decisions(human_decisions)

    @property
    def accepted_rule_ids(self) -> Set[str]:
        return self._accepted_rule_ids

    @property
    def rejected_rule_ids(self) -> Set[str]:
        return self._rejected_rule_ids

    @property
    def human_decisions_applied(self) -> int:
        return (
            len(self._accepted_risk_ids)
            + len(self._resolved_gap_ids)
            + len(self._accepted_rule_ids)
            + len(self._rejected_rule_ids)
        )

    def compute_signals(
        self, issues: List[DetectedIssue]
    ) -> List[Tuple[IssueSignal, DetectedIssue]]:
        """对每个 issue 计算五元信号，返回 (signal, issue) 列表。"""
        results: List[Tuple[IssueSignal, DetectedIssue]] = []
        for issue in issues:
            signal = self._compute_one(issue)
            results.append((signal, issue))
        return results

    def _compute_one(self, issue: DetectedIssue) -> IssueSignal:
        fp = compute_fingerprint(issue.issue_type, issue.gap_targets)
        observed = self._baseline.is_observed(fp)
        activated = (
            bool(issue.related_task_id)
            and issue.related_task_id in self._current_commit_task_set
        )
        resolved = any(t in self._resolved_gap_ids for t in issue.gap_targets)
        accepted = (
            issue.item_id in self._accepted_risk_ids
            or issue.related_task_id in self._accepted_risk_ids
        )
        return IssueSignal(
            observed=observed,
            activated=activated,
            resolved=resolved,
            accepted=accepted,
            severity=issue.severity,
            issue_id=issue.issue_id,
            task_id=issue.related_task_id,
            gap_targets=issue.gap_targets,
        )
