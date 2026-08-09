"""Unit tests for AgentCapabilityMetricsAggregator (T196).

覆盖 docs/design/phase_channel_separation.md §3.2.4 agent_capability_metrics：
  - first_time_right_rate
  - avg_iterations
  - same_category_repeat_tasks
  - block_concentration (Top 3)
  - capability_warnings（3 类阈值触发）
  - compute_all 整合
"""

from __future__ import annotations

import pytest

from vibe_tracing.domain.capability.metrics import AgentCapabilityMetricsAggregator
from vibe_tracing.domain.task.session import TaskSession


def _session(
    task_id: str,
    status: str = "CLOSED",
    iterations: int = 1,
    issue_counts: dict | None = None,
    phase_id: str = "PHASE-VT-001",
) -> TaskSession:
    return TaskSession(
        task_id=task_id,
        phase_id=phase_id,
        status=status,
        first_seen="2026-07-04T08:00:00Z",
        closed_at="2026-07-04T10:00:00Z" if status == "CLOSED" else "",
        iterations=iterations,
        issue_counts=issue_counts or {},
        model="claude-opus-4-8",
    )


# -------------------------------------------------------------------- #
# first_time_right_rate
# -------------------------------------------------------------------- #
class TestFirstTimeRightRate:
    def test_empty(self):
        assert AgentCapabilityMetricsAggregator.first_time_right_rate([]) == 0.0

    def test_all_ftr(self):
        sessions = [_session("A", iterations=1), _session("B", iterations=1)]
        assert AgentCapabilityMetricsAggregator.first_time_right_rate(sessions) == 1.0

    def test_none_ftr(self):
        sessions = [_session("A", iterations=3), _session("B", iterations=2)]
        assert AgentCapabilityMetricsAggregator.first_time_right_rate(sessions) == 0.0

    def test_half_ftr(self):
        sessions = [_session("A", iterations=1), _session("B", iterations=3)]
        assert AgentCapabilityMetricsAggregator.first_time_right_rate(sessions) == 0.5


# -------------------------------------------------------------------- #
# avg_iterations
# -------------------------------------------------------------------- #
class TestAvgIterations:
    def test_empty(self):
        assert AgentCapabilityMetricsAggregator.avg_iterations([]) == 0.0

    def test_simple(self):
        sessions = [_session("A", iterations=1), _session("B", iterations=3)]
        assert AgentCapabilityMetricsAggregator.avg_iterations(sessions) == 2.0

    def test_rounded(self):
        sessions = [
            _session("A", iterations=1),
            _session("B", iterations=2),
            _session("C", iterations=3),
        ]
        assert AgentCapabilityMetricsAggregator.avg_iterations(sessions) == 2.0


# -------------------------------------------------------------------- #
# same_category_repeat_tasks
# -------------------------------------------------------------------- #
class TestSameCategoryRepeatTasks:
    def test_empty(self):
        assert AgentCapabilityMetricsAggregator.same_category_repeat_tasks([]) == 0

    def test_no_repeats(self):
        sessions = [
            _session("A", issue_counts={"no_claim": {"BLOCK": 1, "WARNING": 0}}),
            _session("B", issue_counts={"no_claim": {"BLOCK": 2, "WARNING": 0}}),
        ]
        assert AgentCapabilityMetricsAggregator.same_category_repeat_tasks(sessions) == 0

    def test_single_repeat_task(self):
        sessions = [
            _session(
                "A",
                issue_counts={"no_claim": {"BLOCK": 3, "WARNING": 0}},
            ),
            _session("B", issue_counts={"no_claim": {"BLOCK": 2, "WARNING": 0}}),
        ]
        assert AgentCapabilityMetricsAggregator.same_category_repeat_tasks(sessions) == 1

    def test_warning_plus_block_cumulative(self):
        sessions = [
            _session(
                "A",
                issue_counts={"chain_broken:GATE-VT-006": {"BLOCK": 1, "WARNING": 2}},
            ),
        ]
        assert AgentCapabilityMetricsAggregator.same_category_repeat_tasks(sessions) == 1

    def test_multiple_repeat_tasks(self):
        sessions = [
            _session("A", issue_counts={"no_claim": {"BLOCK": 5, "WARNING": 0}}),
            _session("B", issue_counts={"substandard:coverage": {"BLOCK": 0, "WARNING": 4}}),
            _session("C", issue_counts={"chain_broken:G1": {"BLOCK": 1, "WARNING": 0}}),
        ]
        assert AgentCapabilityMetricsAggregator.same_category_repeat_tasks(sessions) == 2


# -------------------------------------------------------------------- #
# block_concentration
# -------------------------------------------------------------------- #
class TestBlockConcentration:
    def test_empty(self):
        assert AgentCapabilityMetricsAggregator.block_concentration([]) == []

    def test_no_blocks(self):
        sessions = [
            _session("A", issue_counts={"no_claim": {"BLOCK": 0, "WARNING": 5}}),
        ]
        assert AgentCapabilityMetricsAggregator.block_concentration(sessions) == []

    def test_top3_ordering(self):
        sessions = [
            _session(
                "A",
                issue_counts={
                    "no_claim": {"BLOCK": 10, "WARNING": 0},
                    "chain_broken:G1": {"BLOCK": 5, "WARNING": 0},
                    "task_failed": {"BLOCK": 1, "WARNING": 0},
                    "substandard:linter": {"BLOCK": 20, "WARNING": 0},
                },
            ),
        ]
        result = AgentCapabilityMetricsAggregator.block_concentration(sessions)
        assert [r["rule_id"] for r in result] == [
            "substandard:linter",
            "no_claim",
            "chain_broken:G1",
        ]

    def test_top3_ratio_sums_to_total(self):
        sessions = [
            _session(
                "A",
                issue_counts={
                    "no_claim": {"BLOCK": 5, "WARNING": 0},
                    "task_failed": {"BLOCK": 5, "WARNING": 0},
                },
            ),
        ]
        result = AgentCapabilityMetricsAggregator.block_concentration(sessions)
        assert len(result) == 2
        assert all(r["ratio"] == 0.5 for r in result)

    def test_respects_top_n(self):
        sessions = [
            _session(
                "A",
                issue_counts={
                    f"rule_{i}": {"BLOCK": i + 1, "WARNING": 0} for i in range(5)
                },
            ),
        ]
        result = AgentCapabilityMetricsAggregator.block_concentration(sessions, top_n=2)
        assert len(result) == 2
        assert result[0]["rule_id"] == "rule_4"
        assert result[1]["rule_id"] == "rule_3"


# -------------------------------------------------------------------- #
# capability_warnings（阈值触发）
# -------------------------------------------------------------------- #
class TestCapabilityWarnings:
    def test_no_warnings_when_empty(self):
        result = AgentCapabilityMetricsAggregator.compute_all({})
        assert result["capability_warnings"] == []

    def test_low_ftr_warning(self):
        sessions = {
            "A": _session("A", iterations=5),
            "B": _session("B", iterations=4),
            "C": _session("C", iterations=3),
        }
        result = AgentCapabilityMetricsAggregator.compute_all(sessions)
        assert any("首次通过率偏低" in w for w in result["capability_warnings"])
        assert result["first_time_right_rate"] == 0.0

    def test_high_avg_iterations_warning(self):
        sessions = {
            "A": _session("A", iterations=10),
            "B": _session("B", iterations=8),
        }
        result = AgentCapabilityMetricsAggregator.compute_all(sessions)
        assert any("平均迭代次数偏高" in w for w in result["capability_warnings"])
        assert result["avg_iterations"] == 9.0

    def test_repeat_tasks_warning(self):
        sessions = {
            "A": _session("A", issue_counts={"no_claim": {"BLOCK": 3, "WARNING": 0}}),
            "B": _session("B", issue_counts={"task_failed": {"BLOCK": 5, "WARNING": 0}}),
        }
        result = AgentCapabilityMetricsAggregator.compute_all(sessions)
        assert any("同类重复" in w for w in result["capability_warnings"])
        assert result["same_category_repeat_tasks"] == 2

    def test_no_warning_when_below_threshold(self):
        sessions = {
            "A": _session("A", iterations=1),
            "B": _session("B", iterations=1),
            "C": _session("C", iterations=2),
        }
        result = AgentCapabilityMetricsAggregator.compute_all(sessions)
        assert result["capability_warnings"] == []
        assert result["first_time_right_rate"] > 0.3


# -------------------------------------------------------------------- #
# compute_all 整合
# -------------------------------------------------------------------- #
class TestComputeAll:
    def test_compute_all_keys(self):
        sessions = {"A": _session("A", iterations=1)}
        result = AgentCapabilityMetricsAggregator.compute_all(sessions)
        assert set(result.keys()) == {
            "first_time_right_rate",
            "avg_iterations",
            "same_category_repeat_tasks",
            "block_concentration",
            "capability_warnings",
            "closed_task_count",
        }

    def test_compute_all_closed_count_excludes_in_progress(self):
        sessions = {
            "A": _session("A", status="CLOSED", iterations=1),
            "B": _session("B", status="IN_PROGRESS", iterations=2),
        }
        result = AgentCapabilityMetricsAggregator.compute_all(sessions)
        assert result["closed_task_count"] == 1
        assert result["avg_iterations"] == 1.0
        assert result["first_time_right_rate"] == 1.0

    def test_compute_all_empty(self):
        result = AgentCapabilityMetricsAggregator.compute_all({})
        assert result["closed_task_count"] == 0
        assert result["first_time_right_rate"] == 0.0
        assert result["avg_iterations"] == 0.0
        assert result["same_category_repeat_tasks"] == 0
        assert result["block_concentration"] == []
        assert result["capability_warnings"] == []
