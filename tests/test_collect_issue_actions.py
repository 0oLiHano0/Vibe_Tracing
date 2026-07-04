"""Tests for _collect_issue_actions (TASK-VT-189)."""

import pytest
from unittest.mock import MagicMock

from vibe_tracing.domain.gate.types import (
    DetectedIssue,
    IssueSignal,
    OutputState,
    Severity,
)
from vibe_tracing.cli.analyze.actions import (
    _collect_issue_actions,
    _compute_issue_urgency,
    _is_human_decision,
    URGENCY_BLOCK_OBSERVED,
    URGENCY_BLOCK_NEW,
    URGENCY_WARNING,
)


def make_signal(observed=False, severity=Severity.BLOCK, issue_id="x:1",
                task_id="", gap_targets=None):
    return IssueSignal(
        observed=observed, activated=False, resolved=False, accepted=False,
        severity=severity, issue_id=issue_id, task_id=task_id,
        gap_targets=gap_targets or [],
    )


def make_issue(issue_id="x:1", issue_type="no_claim", severity=Severity.BLOCK,
               reason="test", related_task_id="", gap_targets=None, item_id=""):
    return DetectedIssue(
        issue_id=issue_id, issue_type=issue_type, severity=severity,
        reason=reason, related_task_id=related_task_id,
        gap_targets=gap_targets or [], item_id=item_id,
    )


def triple(state, issue_id, issue_type, severity=Severity.BLOCK, reason="test",
           related_task_id="", gap_targets=None, item_id="", observed=False):
    issue = make_issue(issue_id, issue_type, severity, reason,
                       related_task_id, gap_targets, item_id)
    signal = make_signal(observed, severity, issue_id, related_task_id,
                         gap_targets)
    return (state, signal, issue)


class TestFiltering:
    def test_ignore_historical(self):
        items = [triple(OutputState.HISTORICAL, "h:1", "no_claim",
                        reason="historical")]
        assert _collect_issue_actions(items) == []

    def test_ignore_accepted(self):
        items = [triple(OutputState.ACCEPTED, "a:1", "no_claim",
                        reason="accepted")]
        assert _collect_issue_actions(items) == []

    def test_ignore_resolved(self):
        items = [triple(OutputState.RESOLVED, "r:1", "no_claim",
                        reason="resolved")]
        assert _collect_issue_actions(items) == []

    def test_empty_input(self):
        assert _collect_issue_actions([]) == []

    def test_mixed_states_only_current(self):
        items = [
            triple(OutputState.CURRENT_BLOCK, "cb:1", "chain_broken",
                   reason="current block", item_id="T1"),
            triple(OutputState.HISTORICAL, "h:1", "no_claim",
                   reason="historical", item_id="f.py"),
            triple(OutputState.CURRENT_WARNING, "cw:1", "substandard",
                   severity=Severity.WARNING, reason="warning", item_id="s1"),
        ]
        actions = _collect_issue_actions(items)
        assert len(actions) == 2


class TestUrgency:
    def test_block_observed_90(self):
        items = [triple(OutputState.CURRENT_BLOCK, "b:1", "chain_broken",
                        reason="block", observed=True, item_id="T1")]
        actions = _collect_issue_actions(items)
        assert actions[0]["urgency"] == URGENCY_BLOCK_OBSERVED  # 90

    def test_block_new_70(self):
        items = [triple(OutputState.CURRENT_BLOCK, "b:1", "chain_broken",
                        reason="block", observed=False, item_id="T1")]
        actions = _collect_issue_actions(items)
        assert actions[0]["urgency"] == URGENCY_BLOCK_NEW  # 70

    def test_warning_50(self):
        items = [triple(OutputState.CURRENT_WARNING, "w:1", "substandard",
                        severity=Severity.WARNING, reason="warn",
                        observed=True, item_id="s1")]
        actions = _collect_issue_actions(items)
        assert actions[0]["urgency"] == URGENCY_WARNING  # 50


class TestAgentFixable:
    def test_chain_broken(self):
        items = [triple(OutputState.CURRENT_BLOCK,
                        "chain_broken:TASK-001:REQ-999",
                        "chain_broken", reason="Task references nonexistent REQ",
                        related_task_id="TASK-001",
                        gap_targets=["REQ-999"], item_id="TASK-001")]
        actions = _collect_issue_actions(items)
        assert len(actions) == 1
        a = actions[0]
        assert a["type"] == "fix_chain_broken"
        assert a["priority"] == "HIGH"
        assert a["context"]["reason"] == "Task references nonexistent REQ"

    def test_chain_misaligned(self):
        items = [triple(OutputState.CURRENT_BLOCK,
                        "chain_misaligned:TASK-001:AC-001",
                        "chain_misaligned",
                        reason="AC parent req mismatch",
                        related_task_id="TASK-001",
                        item_id="TASK-001")]
        actions = _collect_issue_actions(items)
        a = actions[0]
        assert a["type"] == "fix_chain_misaligned"

    def test_no_claim_ghost_code(self):
        items = [triple(OutputState.CURRENT_BLOCK, "no_claim:src/foo.py",
                        "no_claim", reason="File not covered",
                        item_id="src/foo.py", gap_targets=["src/foo.py"])]
        actions = _collect_issue_actions(items)
        a = actions[0]
        assert a["type"] == "fix_no_claim"
        assert "ac_description" not in a["context"]

    def test_no_claim_ac_coverage(self):
        items = [triple(OutputState.CURRENT_BLOCK, "no_claim:AC-VT-001-01",
                        "no_claim", reason="AC not covered",
                        item_id="AC-VT-001-01",
                        gap_targets=["AC-VT-001-01"])]
        actions = _collect_issue_actions(items)
        a = actions[0]
        assert a["type"] == "fix_no_claim"
        assert "reason" in a["context"]

    def test_task_failed(self):
        items = [triple(OutputState.CURRENT_BLOCK,
                        "task_failed:CLAIM-VT-001", "task_failed",
                        reason="Claim evidence failed",
                        item_id="CLAIM-VT-001")]
        actions = _collect_issue_actions(items)
        a = actions[0]
        assert a["type"] == "fix_task_failed"
        assert a["priority"] == "HIGH"

    def test_substandard_warning(self):
        items = [triple(OutputState.CURRENT_WARNING,
                        "substandard:coverage:src/foo.py",
                        "substandard", severity=Severity.WARNING,
                        reason="Coverage 70%", item_id="src/foo.py")]
        actions = _collect_issue_actions(items)
        a = actions[0]
        assert a["type"] == "fix_substandard"
        assert a["priority"] == "MEDIUM"


class TestHumanDecision:
    def test_proposal_governance(self):
        items = [triple(OutputState.CURRENT_BLOCK,
                        "chain_broken:proposal:RISK-001",
                        "chain_broken", reason="[架构变更提案风险] RISK-001",
                        item_id="RISK-001")]
        actions = _collect_issue_actions(items)
        a = actions[0]
        assert a["type"] == "human_decision_required"
        assert a["priority"] == "INFO"

    def test_proposal_gap(self):
        items = [triple(OutputState.CURRENT_BLOCK,
                        "chain_broken:proposal_gap:GAP-001",
                        "chain_broken", reason="[架构变更治理缺口]",
                        item_id="GAP-001")]
        actions = _collect_issue_actions(items)
        assert actions[0]["type"] == "human_decision_required"

    def test_unclear_constraint(self):
        items = [triple(OutputState.CURRENT_WARNING,
                        "substandard:unclear:A-001",
                        "substandard", severity=Severity.WARNING,
                        reason="Unclear constraint", item_id="A-001")]
        actions = _collect_issue_actions(items)
        assert actions[0]["type"] == "human_decision_required"

    def test_unclear_status(self):
        items = [triple(OutputState.CURRENT_WARNING,
                        "substandard:unclear_status:A-002",
                        "substandard", severity=Severity.WARNING,
                        reason="Unclear status", item_id="A-002")]
        actions = _collect_issue_actions(items)
        assert actions[0]["type"] == "human_decision_required"

    def test_isolated_task(self):
        items = [triple(OutputState.CURRENT_WARNING,
                        "isolated_task:TASK-001", "isolated_task",
                        severity=Severity.WARNING,
                        reason="[告警] 孤立任务 TASK-001",
                        related_task_id="TASK-001", item_id="TASK-001")]
        actions = _collect_issue_actions(items)
        a = actions[0]
        assert a["type"] == "human_decision_required"
        assert a["urgency"] == URGENCY_WARNING


class TestDeepEnhancement:
    def _mock_prd(self):
        ac = MagicMock()
        ac.ac_id = "AC-VT-001-01"
        ac.title = "AC title"
        req = MagicMock()
        req.req_id = "REQ-VT-001"
        req.title = "Req title"
        req.acceptance_criteria = [ac]
        prd = MagicMock()
        prd.requirements = [req]
        return prd

    def test_ac_coverage_prd(self):
        prd = self._mock_prd()
        items = [triple(OutputState.CURRENT_BLOCK,
                        "no_claim:AC-VT-001-01", "no_claim",
                        reason="AC not covered",
                        item_id="AC-VT-001-01")]
        actions = _collect_issue_actions(items, prd_result=prd)
        ctx = actions[0]["context"]
        assert ctx["ac_description"] == "AC title"
        assert ctx["requirement_id"] == "REQ-VT-001"
        assert ctx["requirement_text"] == "Req title"

    def test_ac_coverage_no_prd(self):
        items = [triple(OutputState.CURRENT_BLOCK,
                        "no_claim:AC-VT-001-01", "no_claim",
                        reason="AC not covered",
                        item_id="AC-VT-001-01")]
        actions = _collect_issue_actions(items, prd_result=None)
        ctx = actions[0]["context"]
        assert "reason" in ctx
        assert "ac_description" not in ctx

    def test_task_failed_deep(self):
        items = [triple(OutputState.CURRENT_BLOCK,
                        "task_failed:CLAIM-VT-001", "task_failed",
                        reason="Evidence failed",
                        item_id="CLAIM-VT-001")]
        actions = _collect_issue_actions(items)
        ctx = actions[0]["context"]
        assert "reason" in ctx


class TestHelpers:
    def test_compute_urgency_block_observed(self):
        s = make_signal(observed=True)
        assert _compute_issue_urgency(OutputState.CURRENT_BLOCK, s) == 90

    def test_compute_urgency_block_new(self):
        s = make_signal(observed=False)
        assert _compute_issue_urgency(OutputState.CURRENT_BLOCK, s) == 70

    def test_compute_urgency_warning(self):
        s = make_signal(observed=True)
        assert _compute_issue_urgency(OutputState.CURRENT_WARNING, s) == 50

    def test_is_human_decision_isolated(self):
        issue = make_issue(issue_id="isolated_task:T1",
                           issue_type="isolated_task")
        assert _is_human_decision(issue) is True

    def test_is_human_decision_proposal(self):
        issue = make_issue(issue_id="chain_broken:proposal:R1")
        assert _is_human_decision(issue) is True

    def test_is_human_decision_unclear(self):
        issue = make_issue(issue_id="substandard:unclear:A1")
        assert _is_human_decision(issue) is True

    def test_is_not_human_decision(self):
        issue = make_issue(issue_id="chain_broken:T1:R1",
                           issue_type="chain_broken")
        assert _is_human_decision(issue) is False

    def test_unknown_issue_type_ignored(self):
        items = [triple(OutputState.CURRENT_BLOCK, "unknown:1",
                        "unknown_type", reason="unknown", item_id="x")]
        actions = _collect_issue_actions(items)
        assert actions == []
