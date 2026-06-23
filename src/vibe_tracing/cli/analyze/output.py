"""
Output rendering: gate summary, agent actions, and reflection prompts.
"""

from typing import List, Optional, Set

from vibe_tracing.domain.context import UnifiedContext
from vibe_tracing.cli.analyze.formatting import _format_agent_actions
from vibe_tracing.cli.analyze.reports import (
    _build_report_document,
    _build_metadata,
    _render_dashboard,
)


def _print_gate_summary(gate_res: dict, staged_items: Optional[Set[str]]) -> None:
    """Print gate decision summary, separating current issues from pre-existing debt."""
    gate_decision = gate_res["gate_decision"]
    print(f"Analysis complete. Gate decision: {gate_decision.upper()}")
    if staged_items is not None:
        current_reasons = [r for r in gate_res["reasons"] if r.startswith("[当前]")]
        pre_existing_reasons = [r for r in gate_res["reasons"] if r.startswith("[预存]")]
        unprefixed = [r for r in gate_res["reasons"] if not r.startswith("[当前]") and not r.startswith("[预存]")]
        if current_reasons:
            print("\nCURRENT ISSUES (blocks commit):")
            for reason in current_reasons:
                print(f"- {reason}")
        if pre_existing_reasons:
            print("\nPRE-EXISTING DEBT (does not block):")
            for reason in pre_existing_reasons:
                print(f"- {reason}")
        if unprefixed:
            for reason in unprefixed:
                print(f"- {reason}")
    else:
        for reason in gate_res["reasons"]:
            print(f"- {reason}")


def _print_agent_actions(
    ctx: UnifiedContext,
    gate_res: dict,
    report_doc: dict,
    evidence_meta: dict,
    active_gaps: list,
    active_risks: list,
    merged_gaps: list,
    compliance_res: Optional[dict],
    staged_items: Optional[Set[str]],
    project_root,
) -> None:
    """Format and print the Agent action list."""
    gate_decision = gate_res["gate_decision"]
    violations = compliance_res.get("architecture_violations", []) if compliance_res else []
    accepted_rules = compliance_res.get("accepted_rules", []) if compliance_res else []
    compliance_status = compliance_res.get("architecture_compliance_status", []) if compliance_res else []

    agent_output = _format_agent_actions(
        gate_decision=gate_decision,
        active_gaps=active_gaps,
        active_risks=active_risks,
        violations=violations,
        accepted_rules=accepted_rules,
        prd_result=ctx.prd,
        task_result=ctx.task_result,
        claims_list=ctx.claims_list,
        gate_reasons=gate_res["reasons"],
        merged_gaps=merged_gaps,
        compliance_status=compliance_status,
        coverage_summary=report_doc.get("coverage_summary"),
        staged_items=staged_items,
        evidence_meta=evidence_meta,
    )
    print(agent_output)

    if ctx.prd.status == "draft":
        task_res = ctx.task_result
        claims_list = ctx.claims_list
        if (not task_res or not task_res.tasks) and not claims_list:
            print("\n【零提示词引导】当前项目处于 PRD 草稿阶段（draft），且未发现任何开发任务。请让 AI Agent 读取项目内的 .vibetracing/prompts/prd_analysis.md 并按照其中的 7 步分析法对 PRD 进行分析与补充，逐步生成对应的架构约束和任务列表。")


def _print_reflection_prompts(
    ctx: UnifiedContext,
    gate_res: dict,
    merged_gaps: list,
    final_risks: list,
    compliance_res: Optional[dict],
    project_root,
) -> None:
    """Print reflection prompts based on analysis results."""
    from vibe_tracing.infra.report.reflection import render_reflection_prompts
    from vibe_tracing.infra.governance import load_boundary, partition_by_scope

    claims_list = ctx.claims_list
    manifest = ctx.manifest
    gate_decision = gate_res["gate_decision"]

    affected_files: List[str] = []
    for claim in claims_list:
        for ref in claim.code_refs:
            path = ref.split("#")[0]
            if path and path not in affected_files:
                affected_files.append(path)
        for ref in claim.test_refs:
            path = ref.split("#")[0]
            if path and path not in affected_files:
                affected_files.append(path)

    boundary = load_boundary(project_root, constraints_data=ctx.constraints)
    _scope = partition_by_scope(affected_files, boundary)
    in_scope_files = _scope["in_scope"]
    out_of_scope_files = _scope["out_of_scope"]

    records_dict_all = {r.file_key: r for r in manifest.inputs_used}
    task_list_record = records_dict_all.get("task_list")
    task_list_raw = task_list_record.content if task_list_record and task_list_record.status == "ok" else {"tasks": []}

    print(render_reflection_prompts(
        gate_decision=gate_decision,
        gaps=merged_gaps,
        risks=final_risks,
        task_list=task_list_raw,
        affected_files=sorted(in_scope_files),
        compliance_result=compliance_res,
        governance_in_scope_count=len(in_scope_files),
        governance_out_of_scope_count=len(out_of_scope_files),
    ))


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
    staged_items: Optional[Set[str]],
    output_dir,
    project_root,
    is_draft: bool,
    is_pre_commit: bool = False,
    staged_files: Optional[Set[str]] = None,
) -> None:
    """Render dashboard, print gate summary, agent actions, and reflection prompts."""
    _render_dashboard(ctx, report_doc, evidence_meta, output_dir, project_root)
    _print_gate_summary(gate_res, staged_items)
    if not is_pre_commit:
        _print_empty_claims_hint(ctx, staged_files)
    _print_agent_actions(
        ctx, gate_res, report_doc, evidence_meta,
        active_gaps, active_risks, merged_gaps, compliance_res,
        staged_items, project_root,
    )
    _print_reflection_prompts(ctx, gate_res, merged_gaps, final_risks, compliance_res, project_root)
