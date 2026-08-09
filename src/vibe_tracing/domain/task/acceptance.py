"""Acceptance summary builder — 每 task 一份验收摘要 + 建议行判定。

基于 docs/design/phase_channel_separation.md §2.3.2 / §3.2.1。

触发条件：gate=PASS 且 current_commit_task_set 非空。
多 task 处理：按 task 独立输出多份摘要，不合并。

summary dict 字段：
    recommendation: 'accept' | 'reject'（由 severe_risks 是否为空决定）
    delivery: task 标题（来自 TaskSession.acceptance_summary.delivery）
    severe_risks: business_impact == 'high' 的 remaining WARNING 描述列表
    resolved_block: RESOLVED 且 severity==BLOCK 的 issue 数
    resolved_warning: RESOLVED 且 severity==WARNING 的 issue 数
    remaining_warning: CURRENT_WARNING 的 issue 数
    iterations: 该 task 的累计迭代次数（来自 TaskSession.iterations；session 缺失时为 0）

task 归属策略：
    优先 DetectedIssue.related_task_id 匹配 current_commit_task_set；
    为空或不在 set 中时，归入 sorted(current_commit_task_set) 的首个 task。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from vibe_tracing.domain.gate.types import (
    DetectedIssue,
    IssueSignal,
    OutputState,
    Severity,
)
from vibe_tracing.domain.task.business_impact import BusinessImpactResolver
from vibe_tracing.domain.task.session import TaskSession


_ARCH_ISSUE_TYPES = {"chain_broken", "chain_misaligned", "substandard"}


class AcceptanceSummaryBuilder:
    """构造每 task 一份的验收摘要。"""

    @staticmethod
    def build_list(
        current_commit_task_set: Set[str],
        sessions: Dict[str, TaskSession],
        states_and_signals: List[Tuple[OutputState, IssueSignal, DetectedIssue]],
        project_root: Optional[Path] = None,
    ) -> List[Dict]:
        """为 current_commit_task_set 中的每个 task 构造一份 summary dict。

        Args:
            current_commit_task_set: 当前 commit 引用的 task_id 集合。
            sessions: task_id → TaskSession 映射（来自 TaskSessionManager.sessions）。
            states_and_signals: F() 输出的 (OutputState, IssueSignal, DetectedIssue) 三元组列表。
            project_root: 项目根目录，用于初始化 BusinessImpactResolver；缺省使用 cwd。

        Returns:
            list[dict]，长度 = len(current_commit_task_set)，按 task_id 升序。
        """
        if not current_commit_task_set:
            return []

        resolver = BusinessImpactResolver(
            project_root if project_root is not None else Path.cwd()
        )
        sorted_tasks = sorted(current_commit_task_set)
        default_task = sorted_tasks[0]

        per_task: Dict[str, List[Tuple[OutputState, IssueSignal, DetectedIssue]]] = {
            tid: [] for tid in sorted_tasks
        }
        for triple in states_and_signals:
            _state, _signal, issue = triple
            target = issue.related_task_id
            if not target or target not in per_task:
                target = default_task
            per_task[target].append(triple)

        results: List[Dict] = []
        for task_id in sorted_tasks:
            results.append(
                AcceptanceSummaryBuilder._build_one(
                    task_id, sessions.get(task_id), per_task[task_id], resolver
                )
            )
        return results

    # ------------------------------------------------------------------ #
    # 私有
    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_one(
        task_id: str,
        session: Optional[TaskSession],
        triples: List[Tuple[OutputState, IssueSignal, DetectedIssue]],
        resolver: BusinessImpactResolver,
    ) -> Dict:
        resolved_block = 0
        resolved_warning = 0
        remaining_warning = 0
        severe_risks: List[str] = []

        for state, _signal, issue in triples:
            if state == OutputState.RESOLVED:
                if issue.severity == Severity.BLOCK:
                    resolved_block += 1
                elif issue.severity == Severity.WARNING:
                    resolved_warning += 1
            elif state == OutputState.CURRENT_WARNING:
                remaining_warning += 1
                subtype = AcceptanceSummaryBuilder._derive_subtype(issue)
                impact = resolver.resolve(issue.issue_type, subtype)
                if impact == "high":
                    severe_risks.append(issue.reason or issue.issue_id)

        recommendation = "accept" if not severe_risks else "reject"
        delivery = (
            session.acceptance_summary.delivery
            if session and session.acceptance_summary
            else ""
        )

        return {
            "task_id": task_id,
            "recommendation": recommendation,
            "delivery": delivery,
            "severe_risks": severe_risks,
            "resolved_block": resolved_block,
            "resolved_warning": resolved_warning,
            "remaining_warning": remaining_warning,
            "iterations": session.iterations if session else 0,
        }

    @staticmethod
    def _derive_subtype(issue: DetectedIssue) -> Optional[str]:
        """从 DetectedIssue 推导 business_impact 查找的 subtype。

        - 架构合规类（chain_broken / chain_misaligned / substandard）：item_id 即 rule_id
        - 其他 issue 的子分类（如 substandard:coverage）：从 issue_id 的第二段提取
        - 其余：None
        """
        if issue.issue_type in _ARCH_ISSUE_TYPES and issue.item_id:
            return issue.item_id
        if ":" in issue.issue_id:
            parts = issue.issue_id.split(":")
            if len(parts) >= 2 and parts[0] == issue.issue_type and parts[1]:
                return parts[1]
        return None
