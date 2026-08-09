"""Unit tests for ChannelRenderer + print_acceptance_summary (T197).

覆盖 docs/design/phase_channel_separation.md §2.2 / §2.3.2：
  - print_acceptance_summary：空输入不输出；每 task 一个 section；
    accept / reject 文本正确；迭代次数可选；无 emoji。
  - ChannelRenderer.render_stdout：gate=pass 且有 commit set 时输出摘要；
    其他情况仅输出 Agent 指令段。
  - ChannelRenderer.render_dashboard：调用传入的渲染函数。
"""

from __future__ import annotations

import re
from typing import List

import pytest

from vibe_tracing.cli.analyze.channel import (
    ChannelRenderer,
    print_acceptance_summary,
    print_section_separator,
)


_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F600-\U0001F64F\U0001F900-\U0001F9FF\U00002702-\U000027B0✅⚠️📋]")


# -------------------------------------------------------------------- #
# print_section_separator
# -------------------------------------------------------------------- #
def test_print_section_separator(capsys):
    print_section_separator()
    captured = capsys.readouterr().out
    assert "=" * 64 in captured


# -------------------------------------------------------------------- #
# print_acceptance_summary
# -------------------------------------------------------------------- #
class TestPrintAcceptanceSummary:
    def test_empty_does_not_print(self, capsys):
        print_acceptance_summary([])
        print_acceptance_summary(None)  # type: ignore[arg-type]
        captured = capsys.readouterr().out
        assert captured == ""

    def test_single_accept_summary(self, capsys):
        summary = {
            "task_id": "TASK-VT-190",
            "recommendation": "accept",
            "delivery": "统一 Agent Action 消费路径",
            "resolved_block": 2,
            "resolved_warning": 3,
            "remaining_warning": 1,
            "severe_risks": [],
            "iterations": 4,
        }
        print_acceptance_summary([summary])
        out = capsys.readouterr().out
        assert "═══ 任务验收摘要 ═══" in out
        assert "═══ 验收结束 ═══" in out
        assert "任务：TASK-VT-190" in out
        assert "[接受] accept" in out
        assert "交付：统一 Agent Action 消费路径" in out
        assert "已解决：BLOCK 2 项 / WARNING 3 项（共 5 项）" in out
        assert "遗留：WARNING 1 项" in out
        assert "严重风险：无" in out
        assert "迭代次数：4" in out
        assert not _EMOJI_RE.search(out)

    def test_reject_summary_lists_severe_risks(self, capsys):
        summary = {
            "task_id": "TASK-VT-191",
            "recommendation": "reject",
            "delivery": "",
            "resolved_block": 0,
            "resolved_warning": 0,
            "remaining_warning": 2,
            "severe_risks": ["no_claim:TASK-001", "task_failed:test_1"],
            "iterations": 2,
        }
        print_acceptance_summary([summary])
        out = capsys.readouterr().out
        assert "[驳回] reject" in out
        assert "no_claim:TASK-001" in out
        assert "task_failed:test_1" in out
        assert "交付：-" in out

    def test_multiple_summaries_emit_multiple_sections(self, capsys):
        summaries = [
            {
                "task_id": "TASK-VT-001",
                "recommendation": "accept",
                "delivery": "d1",
                "resolved_block": 1,
                "resolved_warning": 0,
                "remaining_warning": 0,
                "severe_risks": [],
                "iterations": 1,
            },
            {
                "task_id": "TASK-VT-002",
                "recommendation": "reject",
                "delivery": "d2",
                "resolved_block": 0,
                "resolved_warning": 0,
                "remaining_warning": 1,
                "severe_risks": ["risk_a"],
                "iterations": 3,
            },
        ]
        print_acceptance_summary(summaries)
        out = capsys.readouterr().out
        assert out.count("═══ 任务验收摘要 ═══") == 2
        assert out.count("═══ 验收结束 ═══") == 2
        assert "TASK-VT-001" in out
        assert "TASK-VT-002" in out

    def test_iterations_omitted_when_missing(self, capsys):
        summary = {
            "task_id": "TASK-VT-193",
            "recommendation": "accept",
            "delivery": "d",
            "resolved_block": 0,
            "resolved_warning": 0,
            "remaining_warning": 0,
            "severe_risks": [],
        }
        print_acceptance_summary([summary])
        out = capsys.readouterr().out
        assert "迭代次数" not in out

    def test_section_separator_printed_before_summary(self, capsys):
        summary = {
            "task_id": "TASK-VT-194",
            "recommendation": "accept",
            "delivery": "d",
            "resolved_block": 0,
            "resolved_warning": 0,
            "remaining_warning": 0,
            "severe_risks": [],
            "iterations": 1,
        }
        print_acceptance_summary([summary])
        out = capsys.readouterr().out
        sep_pos = out.find("=" * 64)
        summary_pos = out.find("═══ 任务验收摘要 ═══")
        assert sep_pos >= 0
        assert summary_pos > sep_pos


# -------------------------------------------------------------------- #
# ChannelRenderer.render_stdout
# -------------------------------------------------------------------- #
class TestRenderStdout:
    def test_pass_with_commit_set_emits_summary(self, capsys):
        calls: List[str] = []

        def actions():
            calls.append("actions")
            print("GATE DECISION: PASS")

        summaries = [
            {
                "task_id": "TASK-VT-200",
                "recommendation": "accept",
                "delivery": "d",
                "resolved_block": 0,
                "resolved_warning": 0,
                "remaining_warning": 0,
                "severe_risks": [],
                "iterations": 1,
            }
        ]
        ChannelRenderer.render_stdout(
            print_agent_actions=actions,
            gate_decision="pass",
            current_commit_task_set={"TASK-VT-200"},
            acceptance_summaries=summaries,
        )
        out = capsys.readouterr().out
        assert calls == ["actions"]
        assert "GATE DECISION: PASS" in out
        assert "TASK-VT-200" in out
        assert "═══ 任务验收摘要 ═══" in out

    def test_blocked_does_not_emit_summary(self, capsys):
        def actions():
            print("GATE DECISION: BLOCKED")

        summaries = [
            {
                "task_id": "TASK-VT-201",
                "recommendation": "accept",
                "delivery": "d",
                "resolved_block": 0,
                "resolved_warning": 0,
                "remaining_warning": 0,
                "severe_risks": [],
                "iterations": 1,
            }
        ]
        ChannelRenderer.render_stdout(
            print_agent_actions=actions,
            gate_decision="blocked",
            current_commit_task_set={"TASK-VT-201"},
            acceptance_summaries=summaries,
        )
        out = capsys.readouterr().out
        assert "GATE DECISION: BLOCKED" in out
        assert "═══ 任务验收摘要 ═══" not in out

    def test_pass_without_commit_set_does_not_emit_summary(self, capsys):
        def actions():
            print("GATE DECISION: PASS")

        summaries = [
            {
                "task_id": "TASK-VT-202",
                "recommendation": "accept",
                "delivery": "d",
                "resolved_block": 0,
                "resolved_warning": 0,
                "remaining_warning": 0,
                "severe_risks": [],
                "iterations": 1,
            }
        ]
        ChannelRenderer.render_stdout(
            print_agent_actions=actions,
            gate_decision="pass",
            current_commit_task_set=set(),
            acceptance_summaries=summaries,
        )
        out = capsys.readouterr().out
        assert "GATE DECISION: PASS" in out
        assert "═══ 任务验收摘要 ═══" not in out

    def test_pass_without_summaries_does_not_emit_summary(self, capsys):
        def actions():
            print("GATE DECISION: PASS")

        ChannelRenderer.render_stdout(
            print_agent_actions=actions,
            gate_decision="pass",
            current_commit_task_set={"TASK-VT-203"},
            acceptance_summaries=None,
        )
        out = capsys.readouterr().out
        assert "GATE DECISION: PASS" in out
        assert "═══ 任务验收摘要 ═══" not in out


# -------------------------------------------------------------------- #
# ChannelRenderer.render_dashboard
# -------------------------------------------------------------------- #
class TestRenderDashboard:
    def test_calls_passed_render_function(self):
        calls: List[str] = []

        def _render():
            calls.append("dashboard")

        ChannelRenderer.render_dashboard(_render)
        assert calls == ["dashboard"]
