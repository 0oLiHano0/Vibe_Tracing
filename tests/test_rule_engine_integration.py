"""
End-to-end integration tests for the rule engine four-layer pipeline (VT-185).

Pipeline: detect_all_issues → SignalComputer → F() → aggregate_gate_decision
"""

from pathlib import Path

from vibe_tracing.domain.gate.baseline import BaselineManager, compute_fingerprint
from vibe_tracing.domain.gate.engine import MergeGateEngine
from vibe_tracing.domain.gate.signal_computer import SignalComputer
from vibe_tracing.domain.gate.types import (
    F, Severity, OutputState, aggregate_gate_decision,
)


def _run_pipeline(
    engine: MergeGateEngine,
    baseline: BaselineManager,
    current_commit_task_set: set,
    human_decisions=None,
    **detect_kwargs,
):
    """Run the full four-layer pipeline and return (gate_decision, historical, per_issue)."""
    issues = engine.detect_all_issues(**detect_kwargs)
    computer = SignalComputer(baseline, current_commit_task_set, human_decisions)
    signals = computer.compute_signals(issues)
    states_and_signals = [
        (F(s.observed, s.activated, s.resolved, s.accepted, s.severity), s, issue)
        for s, issue in signals
    ]
    return aggregate_gate_decision(states_and_signals)


class TestPipelinePass:
    """Pipeline produces 'pass' when no issues."""

    def test_no_issues_pass(self, tmp_path):
        engine = MergeGateEngine(tmp_path)
        baseline = BaselineManager(tmp_path)
        gate, hist, per = _run_pipeline(engine, baseline, set())
        assert gate == "pass"
        assert len(hist) == 0
        assert len(per) == 0

    def test_only_warnings_fail(self, tmp_path):
        engine = MergeGateEngine(tmp_path)
        baseline = BaselineManager(tmp_path)
        gate, _, per = _run_pipeline(
            engine, baseline, set(),
            lint_violations=[{"source_path": "src/foo.py", "violations_count": 2}],
        )
        assert gate == "fail"
        assert per[0]["state"] == "CURRENT_WARNING"

    def test_block_overrides_warning(self, tmp_path):
        engine = MergeGateEngine(tmp_path)
        baseline = BaselineManager(tmp_path)
        gate, _, _ = _run_pipeline(
            engine, baseline, set(),
            ghost_files=["src/orphan.py"],
            lint_violations=[{"source_path": "src/foo.py", "violations_count": 2}],
        )
        assert gate == "blocked"


class TestPipelineHistorical:
    """Pipeline produces HISTORICAL for observed + not-activated issues."""

    def test_historical_issue_does_not_block(self, tmp_path):
        engine = MergeGateEngine(tmp_path)
        baseline = BaselineManager(tmp_path)

        ghost_files = ["src/old.py"]
        issues = engine.detect_all_issues(ghost_files=ghost_files)
        fps = [compute_fingerprint(i.issue_type, i.gap_targets) for i in issues]
        baseline.generate_snapshot(fps)

        gate, hist, per = _run_pipeline(
            engine, baseline, set(),
            ghost_files=ghost_files,
        )
        assert gate == "pass"
        assert len(hist) == 1
        assert hist[0]["issue_id"].startswith("no_claim")

    def test_historical_with_severity_block_still_passes(self, tmp_path):
        """HISTORICAL overrides severity — BLOCK issues that are observed+not-activated don't block."""
        engine = MergeGateEngine(tmp_path)
        baseline = BaselineManager(tmp_path)

        ghost_files = ["src/legacy.py"]
        issues = engine.detect_all_issues(ghost_files=ghost_files)
        fps = [compute_fingerprint(i.issue_type, i.gap_targets) for i in issues]
        baseline.generate_snapshot(fps)

        gate, hist, _ = _run_pipeline(
            engine, baseline, set(),
            ghost_files=ghost_files,
        )
        assert gate == "pass"
        assert len(hist) == 1


class TestPipelineActivated:
    """Pipeline produces CURRENT_BLOCK for activated BLOCK issues."""

    def test_activated_task_blocks(self, tmp_path):
        engine = MergeGateEngine(tmp_path)
        baseline = BaselineManager(tmp_path)

        ac_gaps = [{"ac_id": "AC-001", "task_id": "TASK-001", "coverage_status": "no_claim_for_task"}]
        issues = engine.detect_all_issues(ac_gaps=ac_gaps)
        fps = [compute_fingerprint(i.issue_type, i.gap_targets) for i in issues]
        baseline.generate_snapshot(fps)

        gate, hist, per = _run_pipeline(
            engine, baseline, {"TASK-001"},
            ac_gaps=ac_gaps,
        )
        assert gate == "blocked"
        assert len(hist) == 0
        block_states = [p for p in per if p["state"] == "CURRENT_BLOCK"]
        assert len(block_states) >= 1

    def test_new_issue_not_in_baseline_blocks(self, tmp_path):
        """New BLOCK issue not in baseline → CURRENT_BLOCK (not HISTORICAL)."""
        engine = MergeGateEngine(tmp_path)
        baseline = BaselineManager(tmp_path)
        baseline.generate_snapshot([])

        gate, hist, per = _run_pipeline(
            engine, baseline, set(),
            ghost_files=["src/new_file.py"],
        )
        assert gate == "blocked"
        assert len(hist) == 0
        assert per[0]["state"] == "CURRENT_BLOCK"


class TestPipelineResolved:
    """Pipeline produces RESOLVED for mark_complete issues."""

    def test_resolved_gap_passes(self, tmp_path):
        engine = MergeGateEngine(tmp_path)
        baseline = BaselineManager(tmp_path)

        gaps = [{"item_id": "AC-001", "item_type": "ac", "reason": "missing test"}]
        human_decisions = {
            "decisions": [{"action": "mark_complete", "targetId": "AC-001"}]
        }
        gate, _, per = _run_pipeline(
            engine, baseline, set(), human_decisions,
            gaps=gaps,
        )
        assert gate == "pass"
        resolved = [p for p in per if p["state"] == "RESOLVED"]
        assert len(resolved) >= 1


class TestPipelineAccepted:
    """Pipeline produces ACCEPTED for accept_risk issues."""

    def test_accepted_risk_passes(self, tmp_path):
        engine = MergeGateEngine(tmp_path)
        baseline = BaselineManager(tmp_path)

        risks = [{"risk_id": "R-001", "severity": "must", "description": "known risk", "claim_id": "C-001"}]
        human_decisions = {
            "decisions": [{"action": "accept_risk", "targetId": "R-001"}]
        }
        gate, _, per = _run_pipeline(
            engine, baseline, set(), human_decisions,
            risks=risks,
        )
        assert gate == "pass"
        accepted = [p for p in per if p["state"] == "ACCEPTED"]
        assert len(accepted) >= 1


class TestPipelineMixed:
    """Pipeline handles mixed scenarios correctly."""

    def test_historical_plus_new_block(self, tmp_path):
        """One historical + one new BLOCK → blocked."""
        engine = MergeGateEngine(tmp_path)
        baseline = BaselineManager(tmp_path)

        old_ghosts = ["src/old.py"]
        old_issues = engine.detect_all_issues(ghost_files=old_ghosts)
        fps = [compute_fingerprint(i.issue_type, i.gap_targets) for i in old_issues]
        baseline.generate_snapshot(fps)

        gate, hist, per = _run_pipeline(
            engine, baseline, set(),
            ghost_files=["src/old.py", "src/new.py"],
        )
        assert gate == "blocked"
        assert len(hist) == 1
        block_states = [p for p in per if p["state"] == "CURRENT_BLOCK"]
        assert len(block_states) == 1

    def test_resolved_plus_warning(self, tmp_path):
        """Resolved BLOCK + new WARNING → fail."""
        engine = MergeGateEngine(tmp_path)
        baseline = BaselineManager(tmp_path)

        gaps = [{"item_id": "AC-001", "item_type": "ac", "reason": "test"}]
        human_decisions = {
            "decisions": [{"action": "mark_complete", "targetId": "AC-001"}]
        }
        gate, _, per = _run_pipeline(
            engine, baseline, set(), human_decisions,
            gaps=gaps,
            lint_violations=[{"source_path": "src/foo.py", "violations_count": 1}],
        )
        assert gate == "fail"
        resolved = [p for p in per if p["state"] == "RESOLVED"]
        warning = [p for p in per if p["state"] == "CURRENT_WARNING"]
        assert len(resolved) >= 1
        assert len(warning) >= 1

    def test_isolated_tasks_always_warning(self, tmp_path):
        engine = MergeGateEngine(tmp_path)
        baseline = BaselineManager(tmp_path)
        gate, _, per = _run_pipeline(
            engine, baseline, set(),
            isolated_tasks=[{"task_id": "TASK-005", "reason": "no req"}],
        )
        assert gate == "fail"
        assert per[0]["state"] == "CURRENT_WARNING"
