"""
规则引擎核心类型定义和纯状态变换函数 F。

基于 design_rule_engine.md v3 和 design_rule_engine_formal_fsm.md v2。
规则引擎是纯函数：f(五元信号) → 状态。相同输入永远产生相同输出。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Tuple


class Severity(Enum):
    """Issue 严重级别。

    BLOCK: 阻拦——存在客观可验证的错误，不需要人类判断。
    WARNING: 告警——需要主观判断，人类做最终决定。
    """

    BLOCK = "BLOCK"
    WARNING = "WARNING"


class OutputState(Enum):
    """规则引擎输出状态。

    五种状态，由纯函数 F 产出：
    - RESOLVED: 已修复，从活跃列表移除。
    - ACCEPTED: 人类已接受，展示但不阻拦。
    - HISTORICAL: 历史债务（observed + ¬activated），展示但不阻拦。
    - CURRENT_BLOCK: 当前阻拦——新 issue 或已激活 Task 的 BLOCK 级问题。
    - CURRENT_WARNING: 当前告警——新 issue 或已激活 Task 的 WARNING 级问题。
    """

    RESOLVED = "RESOLVED"
    ACCEPTED = "ACCEPTED"
    HISTORICAL = "HISTORICAL"
    CURRENT_BLOCK = "CURRENT_BLOCK"
    CURRENT_WARNING = "CURRENT_WARNING"


class GateAction(Enum):
    """门禁行为。

    由 OutputState 映射而来，供 pipeline 层聚合使用：
    - BLOCK: 阻拦（对应 CURRENT_BLOCK）。
    - WARN: 告警（对应 CURRENT_WARNING）。
    - DISPLAY: 仅展示（对应 RESOLVED/ACCEPTED/HISTORICAL）。
    """

    BLOCK = "BLOCK"
    WARN = "WARN"
    DISPLAY = "DISPLAY"


@dataclass(frozen=True)
class DetectedIssue:
    """检测到的 issue 结构化表示。

    由 engine._check_* 方法产出，是解释层的输出。
    字段说明：
    - issue_id: issue 唯一标识（如 "chain_broken:TASK-001:REQ-999"）。
    - issue_type: 六类之一（chain_broken/chain_misaligned/isolated_task/no_claim/task_failed/substandard）。
    - severity: BLOCK 或 WARNING，由 issue_type 决定。
    - reason: 人类可读的问题描述。
    - related_task_id: 关联的 Task ID（如 "TASK-001"）。
    - gap_targets: 缺口目标列表（核销用匹配键，如 ["AC-003", "AC-004"]）。
    - item_id: 直接关联的实体 ID（claim_id/task_id/AC_id 等）。
    """

    issue_id: str
    issue_type: str
    severity: Severity
    reason: str
    related_task_id: str
    gap_targets: List[str]
    item_id: str


@dataclass(frozen=True)
class IssueSignal:
    """Issue 的五元信号表示。

    由 SignalComputer 从 DetectedIssue + Baseline + human_decisions 计算而来。
    规则引擎 F 消费五元信号 (observed, activated, resolved, accepted, severity)，
    产出 OutputState。

    额外字段（issue_id, task_id, gap_targets）用于 fingerprint 计算和下游追踪，
    不参与 F 的求值。
    """

    observed: bool
    activated: bool
    resolved: bool
    accepted: bool
    severity: Severity
    issue_id: str
    task_id: str
    gap_targets: List[str]

    def fingerprint(self) -> str:
        from vibe_tracing.domain.gate.baseline import compute_fingerprint

        issue_type = self.issue_id.split(":")[0] if ":" in self.issue_id else self.issue_id
        return compute_fingerprint(issue_type, self.gap_targets)


def F(observed: bool, activated: bool, resolved: bool, accepted: bool, severity: Severity) -> OutputState:
    """规则引擎纯函数：五元信号 → 输出状态。

    优先级短路求值（design_rule_engine.md §3.1）：
    Step 1: resolved=true → RESOLVED（终止）
    Step 2: accepted=true → ACCEPTED（终止）
    Step 3: observed=true ∧ activated=false → HISTORICAL（终止）
    Step 4: severity=BLOCK → CURRENT_BLOCK（终止）
    Step 5: 剩余 → CURRENT_WARNING（终止）

    三个 Invariant：
    - Invariant 1 (HISTORICAL 域): observed=true ∧ activated=false → INACTIVE 域，severity 不参与判定。
    - Invariant 2 (ACTIVE 域): ¬(observed=true ∧ activated=false) → ACTIVE 域，severity 参与判定。
    - Invariant 3 (RESOLVED 优先): resolved=true → RESOLVED，覆盖所有其他轴。

    完备性：32 种输入组合全部覆盖（design_rule_engine_formal_fsm.md §7.2）。
    互斥性：每种组合命中且仅命中一条规则（§7.3）。
    """
    if resolved:
        return OutputState.RESOLVED
    if accepted:
        return OutputState.ACCEPTED
    if observed and not activated:
        return OutputState.HISTORICAL
    if severity == Severity.BLOCK:
        return OutputState.CURRENT_BLOCK
    return OutputState.CURRENT_WARNING


def state_to_gate_action(state: OutputState) -> GateAction:
    """OutputState → GateAction 映射。

    CURRENT_BLOCK → BLOCK（阻拦）
    CURRENT_WARNING → WARN（告警）
    其余 → DISPLAY（仅展示）
    """
    if state == OutputState.CURRENT_BLOCK:
        return GateAction.BLOCK
    if state == OutputState.CURRENT_WARNING:
        return GateAction.WARN
    return GateAction.DISPLAY


def aggregate_gate_decision(
    states_and_signals: List[Tuple[OutputState, IssueSignal, "DetectedIssue"]],
) -> Tuple[str, List[Dict], List[Dict]]:
    """聚合所有 issue 的状态，产出 gate_decision + 结构化列表。

    输入：F 函数输出的 (OutputState, IssueSignal, DetectedIssue) 三元组列表。
    输出：(gate_decision, historical_issues, per_issue_states)

    gate_decision 逻辑：
    - 存在 CURRENT_BLOCK → 'blocked'
    - 存在 CURRENT_WARNING（且无 BLOCK）→ 'fail'
    - 否则 → 'pass'

    historical_issues：OutputState==HISTORICAL 的 issue 列表（含 severity 和 reason）。
    per_issue_states：全部 issue 的状态明细（含 issue_id, state, severity, reason）。
    """
    has_block = False
    has_warning = False
    historical_issues = []
    per_issue_states = []

    for state, signal, issue in states_and_signals:
        action = state_to_gate_action(state)

        if action == GateAction.BLOCK:
            has_block = True
        elif action == GateAction.WARN:
            has_warning = True

        per_issue_states.append(
            {
                "issue_id": signal.issue_id,
                "issue_type": issue.issue_type,
                "state": state.value,
                "severity": signal.severity.value,
                "task_id": signal.task_id,
                "reason": issue.reason,
                "observed": signal.observed,
                "activated": signal.activated,
                "resolved": signal.resolved,
                "accepted": signal.accepted,
            }
        )

        if state == OutputState.HISTORICAL:
            historical_issues.append(
                {
                    "issue_id": signal.issue_id,
                    "issue_type": issue.issue_type,
                    "severity": signal.severity.value,
                    "task_id": signal.task_id,
                    "reason": issue.reason,
                }
            )

    if has_block:
        gate_decision = "blocked"
    elif has_warning:
        gate_decision = "fail"
    else:
        gate_decision = "pass"

    return gate_decision, historical_issues, per_issue_states
