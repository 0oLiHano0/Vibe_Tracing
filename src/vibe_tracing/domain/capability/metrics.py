"""Agent capability metrics aggregator — 4 类指标 + 能力警告。

基于 docs/design_channel_separation.md §3.2.4（agent_capability_metrics）与
§2.3.4（决策 5：Agent 能力警告不阻断主流程、不在 stdout 提示、仅 Dashboard 徽章）。

四类指标：
    1. first_time_right_rate：CLOSED task 中 iterations==1 的比例（0.0-1.0）。
    2. avg_iterations：CLOSED task 平均迭代次数。
    3. same_category_repeat_tasks：issue_counts 中同一 rule_id 累计触发 >= 3 次的 task 数。
    4. block_concentration：BLOCK 总数 Top-3 rule_id 及其占比。

能力警告（capability_warnings）：纯展示，不阻断。
    - first_time_right_rate < 0.3 → warning: "首次通过率偏低"
    - avg_iterations > 5 → warning: "平均迭代次数偏高"
    - same_category_repeat_tasks >= 2 → warning: "多个任务出现同类重复问题"

数据来源：TaskSessionManager.sessions（dict[str: TaskSession]）。
"""

from __future__ import annotations

from typing import Any, Dict, List

from vibe_tracing.domain.task.session import TaskSession


class AgentCapabilityMetricsAggregator:
    """从 task_sessions 聚合 Agent 能力 4 类指标 + 警告。"""

    FTR_LOW_THRESHOLD = 0.3
    AVG_ITER_HIGH_THRESHOLD = 5
    REPEAT_TRIGGER_THRESHOLD = 3
    REPEAT_TASKS_WARNING_THRESHOLD = 2

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    @staticmethod
    def compute_all(
        sessions: Dict[str, TaskSession],
    ) -> Dict[str, Any]:
        """返回包含 4 类指标 + capability_warnings 的 dict。"""
        closed = [s for s in sessions.values() if s.status == "CLOSED"]
        ftr = AgentCapabilityMetricsAggregator.first_time_right_rate(closed)
        avg = AgentCapabilityMetricsAggregator.avg_iterations(closed)
        repeat = AgentCapabilityMetricsAggregator.same_category_repeat_tasks(closed)
        concentration = AgentCapabilityMetricsAggregator.block_concentration(closed)

        warnings: List[str] = []
        if closed and ftr < AgentCapabilityMetricsAggregator.FTR_LOW_THRESHOLD:
            warnings.append(
                f"首次通过率偏低（{ftr:.0%}），建议检查任务分解粒度"
            )
        if closed and avg > AgentCapabilityMetricsAggregator.AVG_ITER_HIGH_THRESHOLD:
            warnings.append(
                f"平均迭代次数偏高（{avg:.1f}），建议加强 PRD / 架构约束"
            )
        if repeat >= AgentCapabilityMetricsAggregator.REPEAT_TASKS_WARNING_THRESHOLD:
            warnings.append(
                f"{repeat} 个任务出现同类重复问题（同一 rule 触发 ≥ {AgentCapabilityMetricsAggregator.REPEAT_TRIGGER_THRESHOLD} 次）"
            )

        return {
            "first_time_right_rate": ftr,
            "avg_iterations": avg,
            "same_category_repeat_tasks": repeat,
            "block_concentration": concentration,
            "capability_warnings": warnings,
            "closed_task_count": len(closed),
        }

    # ------------------------------------------------------------------ #
    # 4 类指标
    # ------------------------------------------------------------------ #
    @staticmethod
    def first_time_right_rate(closed_sessions: List[TaskSession]) -> float:
        """CLOSED task 中 iterations == 1 的比例；无 CLOSED task 时返回 0.0。"""
        if not closed_sessions:
            return 0.0
        ftr = sum(1 for s in closed_sessions if s.iterations == 1)
        return round(ftr / len(closed_sessions), 4)

    @staticmethod
    def avg_iterations(closed_sessions: List[TaskSession]) -> float:
        """CLOSED task 平均迭代次数；无 CLOSED task 时返回 0.0。"""
        if not closed_sessions:
            return 0.0
        total = sum(s.iterations for s in closed_sessions)
        return round(total / len(closed_sessions), 2)

    @staticmethod
    def same_category_repeat_tasks(closed_sessions: List[TaskSession]) -> int:
        """issue_counts 中同一 rule_id 累计触发（BLOCK+WARNING）>= 阈值的 task 数。"""
        threshold = AgentCapabilityMetricsAggregator.REPEAT_TRIGGER_THRESHOLD
        count = 0
        for s in closed_sessions:
            for bucket in s.issue_counts.values():
                total = int(bucket.get("BLOCK", 0)) + int(bucket.get("WARNING", 0))
                if total >= threshold:
                    count += 1
                    break
        return count

    @staticmethod
    def block_concentration(
        closed_sessions: List[TaskSession],
        top_n: int = 3,
    ) -> List[Dict[str, Any]]:
        """BLOCK 总数 Top-N rule_id 及其占比。

        返回 list[{rule_id, block_count, ratio}]，按 block_count 降序。
        ratio 保留 4 位小数，无 BLOCK 时返回 []。
        """
        totals: Dict[str, int] = {}
        for s in closed_sessions:
            for rule_id, bucket in s.issue_counts.items():
                blk = int(bucket.get("BLOCK", 0))
                if blk > 0:
                    totals[rule_id] = totals.get(rule_id, 0) + blk

        if not totals:
            return []

        grand_total = sum(totals.values())
        rows = [
            {
                "rule_id": rule_id,
                "block_count": count,
                "ratio": round(count / grand_total, 4) if grand_total else 0.0,
            }
            for rule_id, count in totals.items()
        ]
        rows.sort(key=lambda r: (-r["block_count"], r["rule_id"]))
        return rows[:top_n]
