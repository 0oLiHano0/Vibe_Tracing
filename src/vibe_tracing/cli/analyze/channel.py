"""Channel renderer — stdout vs Dashboard 分流调度（T197）。

基于 docs/design_channel_separation.md §2.2 / §3.1。

stdout 结构（Agent 通道）：
    1. Agent 指令段（含 GATE DECISION + actions）
    2. 验收摘要段（仅 gate=PASS 且 current_commit_task_set 非空）

Dashboard 通道（人类通道）：
    - 由 _render_dashboard 生成 HTML，本模块不做任何处理。

本模块仅做 stdout 分流调度；Agent 指令段仍由 output._print_agent_actions 输出，
本模块只负责"何时调用谁"以及验收摘要段。
"""

from __future__ import annotations

from typing import List, Optional


def print_section_separator() -> None:
    """Agent 指令段与验收摘要段之间的分隔线。"""
    print("=" * 64)


def print_acceptance_summary(summaries: List[dict]) -> None:
    """按 task 输出多份验收摘要段（每 task 一个独立 section）。

    格式（每 task 约 5-8 行）：
        ═══ 任务验收摘要 ═══
        任务：<task_id>
        建议：[接受] / [驳回]
        交付：<delivery>
        已解决：BLOCK X 项 / WARNING Y 项（共 Z 项）
        遗留：WARNING N 项
        严重风险：无 / 列表
        迭代次数：K
        ═══ 验收结束 ═══

    若 summaries 为空则不输出。
    """
    if not summaries:
        return

    print_section_separator()
    for summary in summaries:
        task_id = summary.get("task_id", "")
        recommendation = summary.get("recommendation", "accept")
        delivery = summary.get("delivery", "") or "-"
        resolved_block = int(summary.get("resolved_block", 0))
        resolved_warning = int(summary.get("resolved_warning", 0))
        remaining_warning = int(summary.get("remaining_warning", 0))
        severe_risks = summary.get("severe_risks", []) or []
        iterations = summary.get("iterations")
        resolved_total = resolved_block + resolved_warning

        rec_text = "[接受] accept" if recommendation == "accept" else "[驳回] reject"
        severe_text = "无" if not severe_risks else ", ".join(severe_risks)

        print("═══ 任务验收摘要 ═══")
        print(f"任务：{task_id}")
        print(f"建议：{rec_text}")
        print(f"交付：{delivery}")
        print(
            f"已解决：BLOCK {resolved_block} 项 / WARNING {resolved_warning} 项"
            f"（共 {resolved_total} 项）"
        )
        print(f"遗留：WARNING {remaining_warning} 项")
        print(f"严重风险：{severe_text}")
        if iterations is not None:
            print(f"迭代次数：{iterations}")
        print("═══ 验收结束 ═══")


class ChannelRenderer:
    """stdout 与 Dashboard 的渲染分流调度。

    一期 MVP 仅实现 stdout 编排；Dashboard 渲染仍由 reports._render_dashboard 负责，
    本类在 render_dashboard() 中转调用以保持接口统一、为二期 Phase 反思预留扩展点。
    """

    @staticmethod
    def render_stdout(
        print_agent_actions,
        gate_decision: str,
        current_commit_task_set,
        acceptance_summaries: Optional[List[dict]] = None,
    ) -> None:
        """stdout 通道编排。

        Args:
            print_agent_actions: 可调用对象，输出 Agent 指令段（已含 GATE DECISION）。
            gate_decision: 'pass' 或其他；决定是否输出验收摘要段。
            current_commit_task_set: 当前 commit 引用的 task 集合；为空时不输出摘要。
            acceptance_summaries: AcceptanceSummaryBuilder.build_list 返回的摘要列表。
        """
        print_agent_actions()

        if (
            gate_decision == "pass"
            and current_commit_task_set
            and acceptance_summaries
        ):
            print_acceptance_summary(acceptance_summaries)

    @staticmethod
    def render_dashboard(render_fn) -> None:
        """Dashboard 通道编排：直接调用传入的渲染函数。"""
        render_fn()
