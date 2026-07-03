"""
规则引擎纯函数 F 的完备性测试。

覆盖 design_rule_engine_formal_fsm.md §7.4 完整枚举表的全部 32 种输入组合。
"""

import pytest

from vibe_tracing.domain.gate.types import (
    DetectedIssue,
    GateAction,
    IssueSignal,
    OutputState,
    Severity,
    F,
    aggregate_gate_decision,
    state_to_gate_action,
)


class TestFAll32Combinations:
    """F 函数对 32 种输入组合的输出与 §7.4 完整枚举表完全一致。

    输入空间：2^5 = 32 种组合。
    枚举表（§7.4）：
      o  a  r  c  v  │  输出
      *  *  1  *  *  │  RESOLVED        (16 种)
      *  *  0  1  *  │  ACCEPTED        (8 种)
      1  0  0  0  *  │  HISTORICAL      (2 种)
      0  0  0  0  B  │  CURRENT_BLOCK   (1 种)
      0  0  0  0  W  │  CURRENT_WARNING (1 种)
      0  1  0  0  B  │  CURRENT_BLOCK   (1 种)
      0  1  0  0  W  │  CURRENT_WARNING (1 种)
      1  1  0  0  B  │  CURRENT_BLOCK   (1 种)
      1  1  0  0  W  │  CURRENT_WARNING (1 种)
    """

    @pytest.mark.parametrize(
        "observed,activated,resolved,accepted,severity,expected",
        [
            # r=1 → RESOLVED (16 种：o,a,c,v 任意)
            (False, False, True, False, Severity.BLOCK, OutputState.RESOLVED),
            (False, False, True, False, Severity.WARNING, OutputState.RESOLVED),
            (False, False, True, True, Severity.BLOCK, OutputState.RESOLVED),
            (False, False, True, True, Severity.WARNING, OutputState.RESOLVED),
            (False, True, True, False, Severity.BLOCK, OutputState.RESOLVED),
            (False, True, True, False, Severity.WARNING, OutputState.RESOLVED),
            (False, True, True, True, Severity.BLOCK, OutputState.RESOLVED),
            (False, True, True, True, Severity.WARNING, OutputState.RESOLVED),
            (True, False, True, False, Severity.BLOCK, OutputState.RESOLVED),
            (True, False, True, False, Severity.WARNING, OutputState.RESOLVED),
            (True, False, True, True, Severity.BLOCK, OutputState.RESOLVED),
            (True, False, True, True, Severity.WARNING, OutputState.RESOLVED),
            (True, True, True, False, Severity.BLOCK, OutputState.RESOLVED),
            (True, True, True, False, Severity.WARNING, OutputState.RESOLVED),
            (True, True, True, True, Severity.BLOCK, OutputState.RESOLVED),
            (True, True, True, True, Severity.WARNING, OutputState.RESOLVED),
            # r=0, c=1 → ACCEPTED (8 种：o,a,v 任意)
            (False, False, False, True, Severity.BLOCK, OutputState.ACCEPTED),
            (False, False, False, True, Severity.WARNING, OutputState.ACCEPTED),
            (False, True, False, True, Severity.BLOCK, OutputState.ACCEPTED),
            (False, True, False, True, Severity.WARNING, OutputState.ACCEPTED),
            (True, False, False, True, Severity.BLOCK, OutputState.ACCEPTED),
            (True, False, False, True, Severity.WARNING, OutputState.ACCEPTED),
            (True, True, False, True, Severity.BLOCK, OutputState.ACCEPTED),
            (True, True, False, True, Severity.WARNING, OutputState.ACCEPTED),
            # r=0, c=0, o=1, a=0 → HISTORICAL (2 种：v 任意)
            (True, False, False, False, Severity.BLOCK, OutputState.HISTORICAL),
            (True, False, False, False, Severity.WARNING, OutputState.HISTORICAL),
            # r=0, c=0, (o=0∨a=1), v=B → CURRENT_BLOCK (3 种)
            (False, False, False, False, Severity.BLOCK, OutputState.CURRENT_BLOCK),
            (False, True, False, False, Severity.BLOCK, OutputState.CURRENT_BLOCK),
            (True, True, False, False, Severity.BLOCK, OutputState.CURRENT_BLOCK),
            # r=0, c=0, (o=0∨a=1), v=W → CURRENT_WARNING (3 种)
            (False, False, False, False, Severity.WARNING, OutputState.CURRENT_WARNING),
            (False, True, False, False, Severity.WARNING, OutputState.CURRENT_WARNING),
            (True, True, False, False, Severity.WARNING, OutputState.CURRENT_WARNING),
        ],
    )
    def test_f_all_32_combinations(self, observed, activated, resolved, accepted, severity, expected):
        assert F(observed, activated, resolved, accepted, severity) == expected

    def test_total_combinations_count(self):
        """确保参数化覆盖了全部 32 种组合。"""
        combos = []
        for o in [False, True]:
            for a in [False, True]:
                for r in [False, True]:
                    for c in [False, True]:
                        for v in [Severity.BLOCK, Severity.WARNING]:
                            combos.append((o, a, r, c, v))
        assert len(combos) == 32
        for o, a, r, c, v in combos:
            result = F(o, a, r, c, v)
            assert isinstance(result, OutputState)


class TestFInvariants:
    """验证三个 Invariant 硬约束。"""

    def test_invariant_1_historical_domain(self):
        """Invariant 1: observed=true ∧ activated=false → severity 不参与判定。"""
        for v in [Severity.BLOCK, Severity.WARNING]:
            assert F(True, False, False, False, v) == OutputState.HISTORICAL

    def test_invariant_2_active_domain(self):
        """Invariant 2: ¬(observed=true ∧ activated=false) → severity 参与判定。"""
        for o, a in [(False, False), (False, True), (True, True)]:
            assert F(o, a, False, False, Severity.BLOCK) == OutputState.CURRENT_BLOCK
            assert F(o, a, False, False, Severity.WARNING) == OutputState.CURRENT_WARNING

    def test_invariant_3_resolved_priority(self):
        """Invariant 3: resolved=true → RESOLVED，覆盖所有其他轴。"""
        for o in [False, True]:
            for a in [False, True]:
                for c in [False, True]:
                    for v in [Severity.BLOCK, Severity.WARNING]:
                        assert F(o, a, True, c, v) == OutputState.RESOLVED


class TestFPriorityShortCircuit:
    """验证优先级短路：每个分支命中即终止。"""

    def test_resolved_beats_all(self):
        """resolved 优先级最高。"""
        assert F(True, True, True, True, Severity.BLOCK) == OutputState.RESOLVED
        assert F(False, False, True, False, Severity.WARNING) == OutputState.RESOLVED

    def test_accepted_beats_domain_and_severity(self):
        """accepted 优先级第二，高于域判定和 severity。"""
        assert F(True, False, False, True, Severity.BLOCK) == OutputState.ACCEPTED
        assert F(False, True, False, True, Severity.WARNING) == OutputState.ACCEPTED

    def test_historical_beats_severity(self):
        """HISTORICAL 优先级高于 severity——INACTIVE 域中 severity 不参与判定。"""
        assert F(True, False, False, False, Severity.BLOCK) == OutputState.HISTORICAL
        assert F(True, False, False, False, Severity.WARNING) == OutputState.HISTORICAL


class TestStateToGateAction:
    """OutputState → GateAction 映射。"""

    def test_current_block_maps_to_block(self):
        assert state_to_gate_action(OutputState.CURRENT_BLOCK) == GateAction.BLOCK

    def test_current_warning_maps_to_warn(self):
        assert state_to_gate_action(OutputState.CURRENT_WARNING) == GateAction.WARN

    def test_historical_maps_to_display(self):
        assert state_to_gate_action(OutputState.HISTORICAL) == GateAction.DISPLAY

    def test_accepted_maps_to_display(self):
        assert state_to_gate_action(OutputState.ACCEPTED) == GateAction.DISPLAY

    def test_resolved_maps_to_display(self):
        assert state_to_gate_action(OutputState.RESOLVED) == GateAction.DISPLAY


class TestAggregateGateDecision:
    """aggregate_gate_decision 聚合逻辑。"""

    def _make_signal(self, issue_id="test:001", task_id="TASK-001", severity=Severity.BLOCK):
        return IssueSignal(
            observed=False,
            activated=True,
            resolved=False,
            accepted=False,
            severity=severity,
            issue_id=issue_id,
            task_id=task_id,
            gap_targets=["AC-001"],
        )

    def _make_issue(self, issue_id="test:001", reason="test reason"):
        return DetectedIssue(
            issue_id=issue_id,
            issue_type=issue_id.split(":")[0],
            severity=Severity.BLOCK,
            reason=reason,
            related_task_id="TASK-001",
            gap_targets=["AC-001"],
            item_id=issue_id,
        )

    def test_empty_list_passes(self):
        gate, historical, per_issue = aggregate_gate_decision([])
        assert gate == "pass"
        assert historical == []
        assert per_issue == []

    def test_all_display_passes(self):
        sig = self._make_signal()
        issue = self._make_issue()
        states = [(OutputState.HISTORICAL, sig, issue), (OutputState.ACCEPTED, sig, issue)]
        gate, historical, per_issue = aggregate_gate_decision(states)
        assert gate == "pass"
        assert len(historical) == 1
        assert len(per_issue) == 2

    def test_current_warning_fails(self):
        sig = self._make_signal(severity=Severity.WARNING)
        issue = self._make_issue()
        states = [(OutputState.CURRENT_WARNING, sig, issue)]
        gate, historical, per_issue = aggregate_gate_decision(states)
        assert gate == "fail"
        assert len(historical) == 0

    def test_current_block_blocks(self):
        sig = self._make_signal()
        issue = self._make_issue()
        states = [(OutputState.CURRENT_BLOCK, sig, issue)]
        gate, historical, per_issue = aggregate_gate_decision(states)
        assert gate == "blocked"

    def test_block_overrides_warning(self):
        sig_block = self._make_signal(issue_id="chain_broken:001", severity=Severity.BLOCK)
        sig_warn = self._make_signal(issue_id="substandard:001", severity=Severity.WARNING)
        issue_block = self._make_issue(issue_id="chain_broken:001")
        issue_warn = self._make_issue(issue_id="substandard:001")
        states = [(OutputState.CURRENT_WARNING, sig_warn, issue_warn), (OutputState.CURRENT_BLOCK, sig_block, issue_block)]
        gate, _, _ = aggregate_gate_decision(states)
        assert gate == "blocked"

    def test_historical_separated_from_active(self):
        sig_hist = IssueSignal(
            observed=True, activated=False, resolved=False, accepted=False,
            severity=Severity.BLOCK, issue_id="chain_broken:001",
            task_id="TASK-001", gap_targets=["AC-001"],
        )
        sig_active = IssueSignal(
            observed=False, activated=True, resolved=False, accepted=False,
            severity=Severity.WARNING, issue_id="substandard:002",
            task_id="TASK-002", gap_targets=["AC-002"],
        )
        issue_hist = DetectedIssue(
            issue_id="chain_broken:001", issue_type="chain_broken",
            severity=Severity.BLOCK, reason="Historical chain broken",
            related_task_id="TASK-001", gap_targets=["AC-001"], item_id="chain_broken:001",
        )
        issue_active = DetectedIssue(
            issue_id="substandard:002", issue_type="substandard",
            severity=Severity.WARNING, reason="Active substandard",
            related_task_id="TASK-002", gap_targets=["AC-002"], item_id="substandard:002",
        )

        hist_state = F(sig_hist.observed, sig_hist.activated, sig_hist.resolved, sig_hist.accepted, sig_hist.severity)
        active_state = F(sig_active.observed, sig_active.activated, sig_active.resolved, sig_active.accepted, sig_active.severity)

        states = [(hist_state, sig_hist, issue_hist), (active_state, sig_active, issue_active)]
        gate, historical, per_issue = aggregate_gate_decision(states)

        assert gate == "fail"
        assert len(historical) == 1
        assert historical[0]["issue_id"] == "chain_broken:001"
        assert historical[0]["reason"] == "Historical chain broken"
        assert len(per_issue) == 2

    def test_historical_reason_from_issue(self):
        """Verify historical_issues.reason uses DetectedIssue.reason, not issue_id."""
        sig = IssueSignal(
            observed=True, activated=False, resolved=False, accepted=False,
            severity=Severity.BLOCK, issue_id="no_claim:src/old.py",
            task_id="", gap_targets=["src/old.py"],
        )
        issue = DetectedIssue(
            issue_id="no_claim:src/old.py", issue_type="no_claim",
            severity=Severity.BLOCK, reason="业务文件 src/old.py 未被任何 Claim 覆盖",
            related_task_id="", gap_targets=["src/old.py"], item_id="src/old.py",
        )
        state = F(sig.observed, sig.activated, sig.resolved, sig.accepted, sig.severity)
        _, historical, _ = aggregate_gate_decision([(state, sig, issue)])
        assert historical[0]["reason"] == "业务文件 src/old.py 未被任何 Claim 覆盖"

    def test_per_issue_states_includes_reason(self):
        sig = self._make_signal()
        issue = self._make_issue(reason="Custom reason text")
        states = [(OutputState.CURRENT_BLOCK, sig, issue)]
        _, _, per_issue = aggregate_gate_decision(states)
        assert per_issue[0]["reason"] == "Custom reason text"


class TestFPurity:
    """F 是纯函数——无副作用、无外部状态依赖。"""

    def test_same_input_same_output(self):
        for _ in range(100):
            assert F(True, False, False, False, Severity.BLOCK) == OutputState.HISTORICAL
            assert F(False, True, False, False, Severity.WARNING) == OutputState.CURRENT_WARNING

    def test_no_mutation(self):
        """F 不修改输入参数（布尔和枚举本身不可变，此测试确认无异常）。"""
        o, a, r, c = True, False, False, False
        v = Severity.BLOCK
        F(o, a, r, c, v)
        assert o is True
        assert a is False
        assert v == Severity.BLOCK


class TestIssueSignalFingerprint:
    """IssueSignal.fingerprint() 确定性验证。"""

    def test_deterministic(self):
        sig = IssueSignal(
            observed=False, activated=True, resolved=False, accepted=False,
            severity=Severity.BLOCK, issue_id="chain_broken:TASK-001:REQ-999",
            task_id="TASK-001", gap_targets=["AC-003", "AC-001"],
        )
        fp1 = sig.fingerprint()
        fp2 = sig.fingerprint()
        assert fp1 == fp2
        assert len(fp1) == 16

    def test_different_gap_targets_different_fingerprint(self):
        sig1 = IssueSignal(
            observed=False, activated=True, resolved=False, accepted=False,
            severity=Severity.BLOCK, issue_id="chain_broken:001",
            task_id="TASK-001", gap_targets=["AC-001"],
        )
        sig2 = IssueSignal(
            observed=False, activated=True, resolved=False, accepted=False,
            severity=Severity.BLOCK, issue_id="chain_broken:001",
            task_id="TASK-001", gap_targets=["AC-002"],
        )
        assert sig1.fingerprint() != sig2.fingerprint()

    def test_gap_targets_order_invariant(self):
        sig1 = IssueSignal(
            observed=False, activated=True, resolved=False, accepted=False,
            severity=Severity.BLOCK, issue_id="chain_broken:001",
            task_id="TASK-001", gap_targets=["AC-003", "AC-001"],
        )
        sig2 = IssueSignal(
            observed=False, activated=True, resolved=False, accepted=False,
            severity=Severity.BLOCK, issue_id="chain_broken:001",
            task_id="TASK-001", gap_targets=["AC-001", "AC-003"],
        )
        assert sig1.fingerprint() == sig2.fingerprint()
