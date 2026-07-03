"""
Unit tests for SignalComputer (VT-183).
"""

import json
from pathlib import Path

from vibe_tracing.domain.gate.baseline import BaselineManager, compute_fingerprint
from vibe_tracing.domain.gate.signal_computer import SignalComputer, parse_human_decisions
from vibe_tracing.domain.gate.types import DetectedIssue, Severity


def _make_issue(
    issue_type="no_claim",
    severity=Severity.BLOCK,
    related_task_id="",
    gap_targets=None,
    item_id="ITEM-001",
):
    if gap_targets is None:
        gap_targets = ["TARGET-001"]
    return DetectedIssue(
        issue_id=f"{issue_type}:{item_id}",
        issue_type=issue_type,
        severity=severity,
        reason="test reason",
        related_task_id=related_task_id,
        gap_targets=gap_targets,
        item_id=item_id,
    )


class TestParseHumanDecisions:
    """Tests for parse_human_decisions function."""

    def test_none_input(self):
        result = parse_human_decisions(None)
        assert result == (set(), set(), set(), set())

    def test_accept_risk(self):
        decisions = {"decisions": [{"action": "accept_risk", "targetId": "R-001"}]}
        accepted, resolved, _, _ = parse_human_decisions(decisions)
        assert "R-001" in accepted

    def test_mark_complete(self):
        decisions = {"decisions": [{"action": "mark_complete", "targetId": "AC-001"}]}
        _, resolved, _, _ = parse_human_decisions(decisions)
        assert "AC-001" in resolved

    def test_accepted_rule_reconfirm(self):
        decisions = {"decisions": [{"category": "accepted_rule", "targetId": "RULE-001", "action": "reconfirm"}]}
        _, _, accepted_rules, _ = parse_human_decisions(decisions)
        assert "RULE-001" in accepted_rules

    def test_accepted_rule_reject(self):
        decisions = {"decisions": [{"category": "accepted_rule", "targetId": "RULE-001", "action": "reject"}]}
        _, _, _, rejected_rules = parse_human_decisions(decisions)
        assert "RULE-001" in rejected_rules

    def test_empty_decisions(self):
        result = parse_human_decisions({"decisions": []})
        assert result == (set(), set(), set(), set())

    def test_list_input(self):
        decisions = [{"action": "accept_risk", "targetId": "R-001"}]
        accepted, _, _, _ = parse_human_decisions(decisions)
        assert "R-001" in accepted


class TestSignalComputerObserved:
    """Tests for the observed signal."""

    def test_observed_when_in_baseline(self, tmp_path):
        issue = _make_issue()
        fp = compute_fingerprint(issue.issue_type, issue.gap_targets)
        baseline = BaselineManager(tmp_path)
        baseline.generate_snapshot([fp])

        computer = SignalComputer(baseline, set())
        signals = computer.compute_signals([issue])
        assert signals[0][0].observed is True

    def test_not_observed_when_not_in_baseline(self, tmp_path):
        issue = _make_issue()
        baseline = BaselineManager(tmp_path)
        baseline.generate_snapshot(["other_fingerprint"])

        computer = SignalComputer(baseline, set())
        signals = computer.compute_signals([issue])
        assert signals[0][0].observed is False


class TestSignalComputerActivated:
    """Tests for the activated signal."""

    def test_activated_when_task_in_commit_set(self, tmp_path):
        issue = _make_issue(related_task_id="TASK-001")
        baseline = BaselineManager(tmp_path)
        computer = SignalComputer(baseline, {"TASK-001"})
        signals = computer.compute_signals([issue])
        assert signals[0][0].activated is True

    def test_not_activated_when_task_not_in_commit_set(self, tmp_path):
        issue = _make_issue(related_task_id="TASK-001")
        baseline = BaselineManager(tmp_path)
        computer = SignalComputer(baseline, {"TASK-999"})
        signals = computer.compute_signals([issue])
        assert signals[0][0].activated is False

    def test_not_activated_when_empty_task_id(self, tmp_path):
        issue = _make_issue(related_task_id="")
        baseline = BaselineManager(tmp_path)
        computer = SignalComputer(baseline, {"TASK-001"})
        signals = computer.compute_signals([issue])
        assert signals[0][0].activated is False


class TestSignalComputerResolved:
    """Tests for the resolved signal."""

    def test_resolved_when_gap_target_matches(self, tmp_path):
        issue = _make_issue(gap_targets=["AC-001"])
        baseline = BaselineManager(tmp_path)
        human_decisions = {
            "decisions": [{"action": "mark_complete", "targetId": "AC-001"}]
        }
        computer = SignalComputer(baseline, set(), human_decisions)
        signals = computer.compute_signals([issue])
        assert signals[0][0].resolved is True

    def test_not_resolved_when_no_match(self, tmp_path):
        issue = _make_issue(gap_targets=["AC-001"])
        baseline = BaselineManager(tmp_path)
        human_decisions = {
            "decisions": [{"action": "mark_complete", "targetId": "AC-999"}]
        }
        computer = SignalComputer(baseline, set(), human_decisions)
        signals = computer.compute_signals([issue])
        assert signals[0][0].resolved is False

    def test_auto_resolved_when_claim_covers_all_gap_targets(self, tmp_path):
        """覆盖即核销：Claim 的 code_refs 覆盖了全部 gap_targets → resolved=true."""
        from types import SimpleNamespace
        issue = _make_issue(gap_targets=["src/old.py"])
        baseline = BaselineManager(tmp_path)
        claims = [SimpleNamespace(
            claim_id="CLAIM-010", related_task="TASK-010",
            code_refs=["src/old.py", "src/new.py"], test_refs=[],
        )]
        computer = SignalComputer(baseline, set(), claims_list=claims)
        signals = computer.compute_signals([issue])
        assert signals[0][0].resolved is True

    def test_auto_resolved_partial_coverage_not_resolved(self, tmp_path):
        """部分覆盖不核销：only some gap_targets covered → resolved=false."""
        from types import SimpleNamespace
        issue = _make_issue(gap_targets=["src/a.py", "src/b.py"])
        baseline = BaselineManager(tmp_path)
        claims = [SimpleNamespace(
            claim_id="CLAIM-010", related_task="TASK-010",
            code_refs=["src/a.py"], test_refs=[],
        )]
        computer = SignalComputer(baseline, set(), claims_list=claims)
        signals = computer.compute_signals([issue])
        assert signals[0][0].resolved is False

    def test_auto_resolved_via_related_task(self, tmp_path):
        """Claim 的 related_task 覆盖 gap_target → resolved=true."""
        from types import SimpleNamespace
        issue = _make_issue(gap_targets=["TASK-001"])
        baseline = BaselineManager(tmp_path)
        claims = [SimpleNamespace(
            claim_id="CLAIM-010", related_task="TASK-001",
            code_refs=[], test_refs=[],
        )]
        computer = SignalComputer(baseline, set(), claims_list=claims)
        signals = computer.compute_signals([issue])
        assert signals[0][0].resolved is True

    def test_auto_resolved_via_claim_id(self, tmp_path):
        """Claim 的 claim_id 覆盖 gap_target → resolved=true."""
        from types import SimpleNamespace
        issue = _make_issue(gap_targets=["CLAIM-005"])
        baseline = BaselineManager(tmp_path)
        claims = [SimpleNamespace(
            claim_id="CLAIM-005", related_task="TASK-005",
            code_refs=[], test_refs=[],
        )]
        computer = SignalComputer(baseline, set(), claims_list=claims)
        signals = computer.compute_signals([issue])
        assert signals[0][0].resolved is True

    def test_no_claims_falls_back_to_manual(self, tmp_path):
        """无 claims 时退化为仅人工标记."""
        issue = _make_issue(gap_targets=["AC-001"])
        baseline = BaselineManager(tmp_path)
        computer = SignalComputer(baseline, set(), claims_list=None)
        signals = computer.compute_signals([issue])
        assert signals[0][0].resolved is False

    def test_auto_resolve_or_manual_both_work(self, tmp_path):
        """自动核销和人工标记是 OR 关系——任一为 true 即 resolved."""
        from types import SimpleNamespace
        issue_manual = _make_issue(gap_targets=["AC-001"], item_id="ITEM-M")
        issue_auto = _make_issue(gap_targets=["src/foo.py"], item_id="ITEM-A")
        baseline = BaselineManager(tmp_path)
        claims = [SimpleNamespace(
            claim_id="CLAIM-010", related_task="TASK-010",
            code_refs=["src/foo.py"], test_refs=[],
        )]
        human_decisions = {
            "decisions": [{"action": "mark_complete", "targetId": "AC-001"}]
        }
        computer = SignalComputer(baseline, set(), human_decisions, claims_list=claims)
        signals = computer.compute_signals([issue_manual, issue_auto])
        assert signals[0][0].resolved is True
        assert signals[1][0].resolved is True

    def test_auto_resolved_via_test_refs(self, tmp_path):
        """Claim 的 test_refs 覆盖 gap_target → resolved=true."""
        from types import SimpleNamespace
        issue = _make_issue(gap_targets=["tests/test_ac001.py"])
        baseline = BaselineManager(tmp_path)
        claims = [SimpleNamespace(
            claim_id="CLAIM-010", related_task="TASK-010",
            code_refs=[], test_refs=["tests/test_ac001.py"],
        )]
        computer = SignalComputer(baseline, set(), claims_list=claims)
        signals = computer.compute_signals([issue])
        assert signals[0][0].resolved is True


class TestSignalComputerAccepted:
    """Tests for the accepted signal."""

    def test_accepted_when_item_id_matches(self, tmp_path):
        issue = _make_issue(item_id="CLAIM-001")
        baseline = BaselineManager(tmp_path)
        human_decisions = {
            "decisions": [{"action": "accept_risk", "targetId": "CLAIM-001"}]
        }
        computer = SignalComputer(baseline, set(), human_decisions)
        signals = computer.compute_signals([issue])
        assert signals[0][0].accepted is True

    def test_accepted_when_task_id_matches(self, tmp_path):
        issue = _make_issue(item_id="CLAIM-001", related_task_id="TASK-001")
        baseline = BaselineManager(tmp_path)
        human_decisions = {
            "decisions": [{"action": "accept_risk", "targetId": "TASK-001"}]
        }
        computer = SignalComputer(baseline, set(), human_decisions)
        signals = computer.compute_signals([issue])
        assert signals[0][0].accepted is True

    def test_not_accepted_when_no_match(self, tmp_path):
        issue = _make_issue(item_id="CLAIM-001")
        baseline = BaselineManager(tmp_path)
        human_decisions = {
            "decisions": [{"action": "accept_risk", "targetId": "CLAIM-999"}]
        }
        computer = SignalComputer(baseline, set(), human_decisions)
        signals = computer.compute_signals([issue])
        assert signals[0][0].accepted is False


class TestSignalComputerSeverity:
    """Tests for severity passthrough."""

    def test_block_severity_passthrough(self, tmp_path):
        issue = _make_issue(severity=Severity.BLOCK)
        baseline = BaselineManager(tmp_path)
        computer = SignalComputer(baseline, set())
        signals = computer.compute_signals([issue])
        assert signals[0][0].severity == Severity.BLOCK

    def test_warning_severity_passthrough(self, tmp_path):
        issue = _make_issue(severity=Severity.WARNING)
        baseline = BaselineManager(tmp_path)
        computer = SignalComputer(baseline, set())
        signals = computer.compute_signals([issue])
        assert signals[0][0].severity == Severity.WARNING


class TestSignalComputerProperties:
    """Tests for SignalComputer properties."""

    def test_human_decisions_applied_count(self, tmp_path):
        baseline = BaselineManager(tmp_path)
        human_decisions = {
            "decisions": [
                {"action": "accept_risk", "targetId": "R-001"},
                {"action": "mark_complete", "targetId": "AC-001"},
                {"category": "accepted_rule", "targetId": "RULE-001", "action": "reconfirm"},
            ]
        }
        computer = SignalComputer(baseline, set(), human_decisions)
        assert computer.human_decisions_applied == 3

    def test_accepted_rule_ids_property(self, tmp_path):
        baseline = BaselineManager(tmp_path)
        human_decisions = {
            "decisions": [
                {"category": "accepted_rule", "targetId": "RULE-001", "action": "reconfirm"},
            ]
        }
        computer = SignalComputer(baseline, set(), human_decisions)
        assert "RULE-001" in computer.accepted_rule_ids

    def test_rejected_rule_ids_property(self, tmp_path):
        baseline = BaselineManager(tmp_path)
        human_decisions = {
            "decisions": [
                {"category": "accepted_rule", "targetId": "RULE-001", "action": "reject"},
            ]
        }
        computer = SignalComputer(baseline, set(), human_decisions)
        assert "RULE-001" in computer.rejected_rule_ids
