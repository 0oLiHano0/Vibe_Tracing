"""
Output rendering: agent actions, empty-claims hint, and dashboard dispatch.

Channel separation (T197)：
  - stdout 仅输出 Agent 指令段（含 GATE DECISION 单行）+ 验收摘要段。
  - 反思提示不再直出 stdout，迁移至 Dashboard（二期 PhaseReflectionEngine）。
  - _render_output 内部使用 ChannelRenderer 调度 stdout 与 Dashboard。
"""

from typing import Optional, Set

from vibe_tracing.domain.context import UnifiedContext
from vibe_tracing.infra.loader.raw_input import STATUS_OK
from vibe_tracing.cli.analyze.formatting import _format_agent_actions
from vibe_tracing.cli.analyze.reports import (
    _build_report_document,
    _build_metadata,
    _render_dashboard,
)
from vibe_tracing.cli.analyze.channel import ChannelRenderer


def _print_agent_actions(
    ctx: UnifiedContext,
    gate_res: dict,
    report_doc: dict,
    project_root,
    conn=None,
    states_and_signals=None,
) -> None:
    """Format and print the Agent action list."""
    gate_decision = gate_res["gate_decision"]

    agent_output = _format_agent_actions(
        gate_decision=gate_decision,
        states_and_signals=states_and_signals or [],
        prd_result=ctx.prd,
        task_result=ctx.task_result,
        claims_list=ctx.claims_list,
        coverage_summary=report_doc.get("coverage_summary"),
        conn=conn,
    )
    print(agent_output)

    if ctx.prd.status == "draft":
        task_res = ctx.task_result
        claims_list = ctx.claims_list
        if (not task_res or not task_res.tasks) and not claims_list:
            print("\n【零提示词引导】当前项目处于 PRD 草稿阶段（draft），且未发现任何开发任务。请让 AI Agent 读取项目内的 .vibetracing/prompts/prd_analysis.md 并按照其中的 7 步分析法对 PRD 进行分析与补充，逐步生成对应的架构约束和任务列表。")


def _print_empty_claims_hint(ctx: UnifiedContext, staged_files: Optional[Set[str]]) -> None:
    """Print a warning when claims are empty and no files are staged."""
    if not ctx.claims_list and not staged_files:
        print("\n[WARNING] 当前无 claims 且无 staged 文件。")
        print("请先 git add 变更文件（VT 会自动生成 claim），")
        print("或在 .vibetracing/claims/ 中创建 Claim 文件（CLAIM-*.json）。")


def _render_output(
    ctx: UnifiedContext,
    gate_res: dict,
    report_doc: dict,
    evidence_meta: dict,
    active_gaps: list,
    active_risks: list,
    merged_gaps: list,
    final_risks: list,
    compliance_res: Optional[dict],
    current_commit_task_set: Set[str],
    output_dir,
    project_root,
    staged_files: Optional[Set[str]] = None,
    conn=None,
    states_and_signals=None,
    acceptance_summaries=None,
) -> None:
    """Render dashboard, print agent actions, and (when applicable) acceptance summary.

    Channel separation (T197)：
      - stdout：Agent 指令段 + 验收摘要段（gate=PASS 且 commit set 非空）。
      - Dashboard：独立 HTML 通道，由 ChannelRenderer.render_dashboard 调度。
    """
    gate_decision = gate_res["gate_decision"]

    # 1. Dashboard 通道（先渲染，避免 stdout 与文件 IO 交叉）
    ChannelRenderer.render_dashboard(
        lambda: _render_dashboard(ctx, report_doc, evidence_meta, output_dir, project_root)
    )

    # 2. stdout 通道
    def _agent_actions_block():
        _print_empty_claims_hint(ctx, staged_files)
        _print_agent_actions(
            ctx, gate_res, report_doc, project_root,
            conn=conn, states_and_signals=states_and_signals,
        )

    ChannelRenderer.render_stdout(
        print_agent_actions=_agent_actions_block,
        gate_decision=gate_decision,
        current_commit_task_set=current_commit_task_set,
        acceptance_summaries=acceptance_summaries,
    )
