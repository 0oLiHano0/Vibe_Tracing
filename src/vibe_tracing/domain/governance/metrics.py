"""Governance metrics aggregator — 5 分类验收链条汇总 / 衍生比例 / 平均迭代。

基于 docs/design/phase_channel_separation.md §2.3.4 / §3.1。

三类指标：
    1. 5 分类验收链条汇总（aggregate_category_summary）：
        按人类验收思维路径分 5 个节点：链路完整性 / 交付凭证 / 证据验证 / 交付质量 / 过程合规。
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

from vibe_tracing.domain.governance.category_mapper import (
    CATEGORIES,
    categorize,
)
from vibe_tracing.domain.task.session import TaskSession


_DERIVED_TITLE_RE = re.compile(r"(修复|优化|调整)\s*TASK-[A-Z]+-\d+")


class GovernanceMetricsAggregator:
    """从 task_sessions 聚合治理演进三类指标。"""

    # ------------------------------------------------------------------ #
    # 1. 5 分类验收链条汇总
    # ------------------------------------------------------------------ #
    @staticmethod
    def aggregate_category_summary(
        sessions: Dict[str, TaskSession],
        *,
        phase_filter: Optional[str] = None,
        task_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """返回 5 个验收节点汇总，每个节点含状态、计数、明细。

        返回字段：category / status / gate_level / block_count / warning_count / details
        status: "passed" (无 issue) / "warning" (仅 WARNING) / "failed" (有 BLOCK)
        details: [{rule_id, block_count, warning_count}] 该分类下的具体条目
        """
        cat_gate: Dict[str, str] = {c["id"]: c["gate"] for c in CATEGORIES}
        cat_desc: Dict[str, str] = {c["id"]: c["description"] for c in CATEGORIES}

        cat_counts: Dict[str, Dict[str, int]] = {
            c["id"]: {"block": 0, "warning": 0} for c in CATEGORIES
        }
        detail_map: Dict[str, Dict[str, Dict[str, int]]] = {
            c["id"]: {} for c in CATEGORIES
        }

        for session in sessions.values():
            if phase_filter and session.phase_id != phase_filter:
                continue
            if task_filter and session.task_id != task_filter:
                continue
            for key, bucket in session.issue_counts.items():
                cat = categorize(key)
                b = int(bucket.get("BLOCK", 0))
                w = int(bucket.get("WARNING", 0))
                cat_counts[cat]["block"] += b
                cat_counts[cat]["warning"] += w
                if key not in detail_map[cat]:
                    detail_map[cat][key] = {"block": 0, "warning": 0}
                detail_map[cat][key]["block"] += b
                detail_map[cat][key]["warning"] += w

        result: List[Dict[str, Any]] = []
        for c in CATEGORIES:
            cid = c["id"]
            bc = cat_counts[cid]["block"]
            wc = cat_counts[cid]["warning"]
            if bc > 0:
                status = "failed"
            elif wc > 0:
                status = "warning"
            else:
                status = "passed"

            details = [
                {"rule_id": k, "block_count": v["block"], "warning_count": v["warning"]}
                for k, v in detail_map[cid].items()
            ]
            details.sort(key=lambda d: (-d["block_count"], d["rule_id"]))

            result.append({
                "category": cid,
                "description": cat_desc[cid],
                "status": status,
                "gate_level": cat_gate[cid],
                "block_count": bc,
                "warning_count": wc,
                "details": details,
            })
        return result

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
