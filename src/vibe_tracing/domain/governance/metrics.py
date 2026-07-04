"""Governance metrics aggregator — 规则触发表 / 衍生比例 / 平均迭代。

基于 docs/design_channel_separation.md §2.3.4 / §3.1。

三类指标：
    1. 全量规则触发统计表（aggregate_rule_stats_table）：
        按 BLOCK 次数降序；从未触发（block_count=0 且 warning_count=0）沉底。
    2. 衍生 task 比例（aggregate_derived_task_ratio）：
        标题关键词匹配（'修复/优化/调整 TASK-VT-XXX'），近似指标。
    3. 任务平均迭代次数（aggregate_avg_iterations_by_phase）：
        按 phase_id 分组，仅统计 CLOSED task。

数据来源：TaskSessionManager.sessions（dict[str, TaskSession]）。
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from vibe_tracing.domain.task.session import TaskSession


_DERIVED_TITLE_RE = re.compile(r"(修复|优化|调整)\s*TASK-[A-Z]+-\d+")

_ISSUE_TYPE_DESCRIPTIONS: Dict[str, str] = {
    "no_claim": "任务缺少 Agent Claim 声明",
    "chain_broken": "需求 → 任务 → Claim → 证据链断裂",
    "chain_misaligned": "需求 → 任务 → Claim 对齐偏差",
    "task_failed": "任务执行失败（测试未通过 / 工具报错）",
    "isolated_task": "孤立任务（未关联需求 / 验收标准）",
    "substandard": "质量不达标（测试覆盖 / Linter 违规）",
}


class GovernanceMetricsAggregator:
    """从 task_sessions 聚合治理演进三类指标。"""

    # ------------------------------------------------------------------ #
    # 1. 全量规则触发表
    # ------------------------------------------------------------------ #
    @staticmethod
    def aggregate_rule_stats_table(
        sessions: Dict[str, TaskSession],
    ) -> List[Dict[str, Any]]:
        """返回 list[dict]，按 block_count 降序；block=0 且 warning=0 的条目沉底。

        条目字段：rule_id / description / block_count / warning_count / last_triggered
        """
        counts: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"block": 0, "warning": 0}
        )
        last_triggered: Dict[str, str] = {}

        for session in sessions.values():
            triggered_at = session.closed_at or session.first_seen
            for rule_id, bucket in session.issue_counts.items():
                counts[rule_id]["block"] += int(bucket.get("BLOCK", 0))
                counts[rule_id]["warning"] += int(bucket.get("WARNING", 0))
                prev = last_triggered.get(rule_id, "")
                if triggered_at and triggered_at > prev:
                    last_triggered[rule_id] = triggered_at

        rows: List[Dict[str, Any]] = []
        for rule_id, c in counts.items():
            rows.append(
                {
                    "rule_id": rule_id,
                    "description": GovernanceMetricsAggregator._describe_rule(rule_id),
                    "block_count": c["block"],
                    "warning_count": c["warning"],
                    "last_triggered": last_triggered.get(rule_id, ""),
                }
            )

        def sort_key(row: Dict[str, Any]):
            is_never = row["block_count"] == 0 and row["warning_count"] == 0
            return (1 if is_never else 0, -row["block_count"])

        rows.sort(key=sort_key)
        return rows

    @staticmethod
    def _describe_rule(rule_id: str) -> str:
        base_type = rule_id.split(":")[0] if ":" in rule_id else rule_id
        desc = _ISSUE_TYPE_DESCRIPTIONS.get(base_type)
        if desc and ":" in rule_id:
            return f"{desc} [{rule_id.split(':', 1)[1]}]"
        return desc or rule_id

    # ------------------------------------------------------------------ #
    # 2. 衍生 task 比例
    # ------------------------------------------------------------------ #
    @staticmethod
    def aggregate_derived_task_ratio(
        tasks: List[Any],
        sessions: Optional[Dict[str, TaskSession]] = None,
    ) -> float:
        """标题关键词匹配（'修复/优化/调整 TASK-VT-XXX'）；返回 0.0-1.0 之间比例。

        tasks: TaskLoader 解析后的 Task 列表（有 title 属性或 'title' key）；
        sessions: 未使用（保留签名，便于二期扩展）。

        注意：该指标为基于标题匹配的近似值（§2.3.4）。
        """
        if not tasks:
            return 0.0
        total = 0
        derived = 0
        for t in tasks:
            title = t.title if hasattr(t, "title") else (t.get("title", "") if isinstance(t, dict) else "")
            if not title:
                continue
            total += 1
            if _DERIVED_TITLE_RE.search(title):
                derived += 1
        if total == 0:
            return 0.0
        return round(derived / total, 4)

    # ------------------------------------------------------------------ #
    # 3. 平均迭代次数（按 PHASE 分组）
    # ------------------------------------------------------------------ #
    @staticmethod
    def aggregate_avg_iterations_by_phase(
        sessions: Dict[str, TaskSession],
    ) -> Dict[str, float]:
        """按 phase_id 分组计算平均迭代次数；仅统计 CLOSED task。"""
        groups: Dict[str, List[int]] = defaultdict(list)
        for session in sessions.values():
            if session.status != "CLOSED":
                continue
            if session.phase_id:
                groups[session.phase_id].append(session.iterations)

        result: Dict[str, float] = {}
        for phase_id, iters in groups.items():
            if iters:
                result[phase_id] = round(sum(iters) / len(iters), 2)
        return result
