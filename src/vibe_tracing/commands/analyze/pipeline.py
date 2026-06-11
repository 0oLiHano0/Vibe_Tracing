"""
Main analyze pipeline orchestration.
"""

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional, Set

from vibe_tracing.schema_validator import SchemaValidator
from vibe_tracing.evidence_index_builder import EvidenceIndexBuilder
from vibe_tracing.merge_gate_engine import MergeGateEngine
from vibe_tracing.context import UnifiedContext

from vibe_tracing.commands.common import (
    _GateBlocked,
    _load_context,
    _get_staged_files,
    _determine_affected_items,
    _get_directly_modified_claims,
)
from vibe_tracing.commands.analyze.gates import _run_integrity_gates
from vibe_tracing.commands.analyze.tools import _execute_tools, _archive_claims
from vibe_tracing.commands.analyze.analysis import (
    _run_analyzers,
    _run_claim_tests,
    _load_human_decisions,
)
from vibe_tracing.commands.analyze.reports import _build_report_document
from vibe_tracing.commands.analyze.output import _render_output


def _run_analysis_phase(
    ctx: UnifiedContext,
    merged_gaps: list,
    final_risks: list,
    evidence_index: dict,
    project_root: Path,
    staged_files: Optional[Set[str]] = None,
):
    """Run claim tests, compute active issues, and build staged_items.

    Returns (active_gaps, active_risks, evidence_index,
             staged_items, directly_staged_items).
    """
    claims_list = ctx.claims_list

    # Run pytest for claim test_refs and record results in evidence_index
    evidence_index = _run_claim_tests(project_root, claims_list, evidence_index)

    # Filter out stale gaps / risks for gate evaluation.  Stale items are
    # still included in the full report for visibility.
    active_gaps = [g for g in merged_gaps if not g.get("stale")]
    active_risks = [r for r in final_risks if not r.get("stale")]

    # Build staged_items for debt awareness (EVO-TASK-025 / EVO-TASK-012).
    staged_items: Optional[Set[str]] = None
    directly_staged_items: Optional[Set[str]] = None
    if staged_files:
        affected_claims, affected_reqs, affected_acs = _determine_affected_items(
            staged_files, claims_list, ctx,
        )
        staged_items = set(affected_claims)
        if ctx.task_result and ctx.task_result.tasks:
            affected_task_ids = {
                claim.related_task
                for claim in claims_list
                if claim.claim_id in affected_claims
            }
            staged_items.update(affected_task_ids)
        staged_items.update(affected_acs)
        staged_items.update(affected_reqs)

        # Build directly_staged_items: only items whose definitions were
        # directly modified in this commit.
        claims_file_rel = ".vibetracing/claims/current.json"
        if claims_file_rel in staged_files:
            from vibe_tracing.git_utils import git_show
            try:
                old_json = git_show("HEAD", ".vibetracing/claims/current.json", project_root)
                old_claims = json.loads(old_json) if old_json else []
            except Exception:
                old_claims = []
            new_claims_raw = []
            for c in claims_list:
                if hasattr(c, '__dict__'):
                    new_claims_raw.append(c.__dict__)
                elif isinstance(c, dict):
                    new_claims_raw.append(c)
                else:
                    new_claims_raw.append(asdict(c) if hasattr(c, '__dataclass_fields__') else {})
            directly_staged_claims = _get_directly_modified_claims(old_claims, new_claims_raw)
        else:
            directly_staged_claims = set()
        directly_staged_items = set(directly_staged_claims)

    return active_gaps, active_risks, evidence_index, staged_items, directly_staged_items


def _run_gate_evaluation(
    project_root: Path,
    active_gaps: list,
    active_risks: list,
    compliance_res: Optional[dict],
    ctx: UnifiedContext,
    evidence_index: dict,
    staged_items: Optional[Set[str]],
    directly_staged_items: Optional[Set[str]],
) -> dict:
    """Run MergeGateEngine and return gate result dict."""
    human_decisions = _load_human_decisions()
    gate_engine = MergeGateEngine(project_root)
    gate_res = gate_engine.evaluate(
        active_gaps, active_risks, compliance_res,
        prd_status=ctx.prd.status, staged_items=staged_items,
        directly_staged_items=directly_staged_items,
        evidence_index=evidence_index,
        human_decisions=human_decisions,
    )
    hd_applied = gate_res.get("human_decisions_applied", 0)
    if hd_applied > 0:
        print(f"  Applied {hd_applied} human decision(s).", file=sys.stderr)
    return gate_res


def _evaluate_and_output(
    ctx: UnifiedContext,
    merged_gaps: list,
    final_risks: list,
    compliance_res: Optional[dict],
    output_dir: Path,
    evidence_index: dict,
    claim_res: dict,
    req_res: dict,
    project_root: Path,
    is_draft: bool,
    staged_files: Optional[Set[str]] = None,
) -> int:
    """Run MergeGateEngine, output all reports, and return exit code."""
    if not ctx.manifest:
        return 1

    # Phase 1: Analysis (claim tests, active issues, staged items)
    active_gaps, active_risks, evidence_index, staged_items, directly_staged_items = \
        _run_analysis_phase(ctx, merged_gaps, final_risks, evidence_index, project_root, staged_files)

    # Phase 2: Gate evaluation
    gate_res = _run_gate_evaluation(
        project_root, active_gaps, active_risks, compliance_res,
        ctx, evidence_index, staged_items, directly_staged_items,
    )

    # Phase 3: Build report document
    report_doc = _build_report_document(
        ctx, gate_res, evidence_index, merged_gaps, final_risks,
        compliance_res, req_res, output_dir, project_root,
    )

    # Phase 4: Render output (dashboard, summary, agent actions, reflection)
    _render_output(
        ctx, gate_res, report_doc, evidence_index,
        active_gaps, active_risks, merged_gaps, final_risks, compliance_res,
        staged_items, output_dir, project_root, is_draft,
    )

    # Compute exit code
    exit_code = 2 if gate_res["gate_decision"] == "blocked" else 0

    return exit_code


def run_analyze(project_root: Path, output_dir: Optional[Path] = None, is_pre_commit: bool = False, gates_only: bool = False) -> int:
    """
    Execute the full Vibe Tracing analysis pipeline.

    Args:
        project_root: The workspace root path.
        output_dir: The target output directory. If None, resolved from
            config.json paths.output_dir (default: "output").
        is_pre_commit: Whether running in pre-commit hook mode.
        gates_only: If True, run only integrity gates (1, 2, 2.5) and skip
            tool execution and full analysis (fast mode for pre-commit).

    Returns:
        Exit code:
            0: Gate decision is 'pass' or 'fail' (conditional).
            1: Execution error, invalid inputs, schema errors.
            2: Gate decision is 'blocked'.
    """
    try:
        schemas_dir = project_root / "schemas"
        if not schemas_dir.is_dir():
            schemas_dir = Path(__file__).parents[2] / "schemas"
        validator = SchemaValidator(schemas_dir)

        ctx, raw_loader, validator = _load_context(project_root, schemas_dir, validator)
        prd_res = ctx.prd
        is_draft = (prd_res.status == "draft")
        config_prefix = ctx.config_prefix

        # Resolve output_dir from config if not explicitly provided
        if output_dir is None:
            _out_rel = ctx.config.get("paths", {}).get("output_dir", "output")
            output_dir = (project_root / _out_rel).resolve()

        exit_code = _run_integrity_gates(
            ctx, project_root, is_pre_commit, config_prefix,
        )
        if exit_code is not None:
            return exit_code

        if gates_only:
            print("Gates-only mode: integrity gates passed. Skipping analysis.")
            if is_pre_commit:
                _archive_claims(project_root)
            return 0

        tool_evidence = _execute_tools(ctx, project_root, is_draft)
        ctx.tool_evidence = tool_evidence

        # Build evidence index
        index_builder = EvidenceIndexBuilder(project_root)
        index_path = output_dir / "evidence_index.json"
        try:
            evidences_index = index_builder.build(
                output_path=index_path,
                ctx=ctx,
                tool_evidence_candidates=tool_evidence,
                prd_record=prd_res,
                task_result=ctx.task_result,
                claims_list=ctx.claims_list,
                manifest=ctx.manifest,
                config_prefix=config_prefix,
            )
        except Exception as exc:
            print(f"Error building evidence index: {exc}", file=sys.stderr)
            return 1

        evidence_list = evidences_index.get("evidences", [])

        staged_files = _get_staged_files(project_root)

        merged_gaps, final_risks, compliance_res, claim_res, req_res = _run_analyzers(
            ctx, evidence_list, project_root,
            staged_files=staged_files,
        )

        exit_code = _evaluate_and_output(
            ctx, merged_gaps, final_risks, compliance_res,
            output_dir, evidences_index, claim_res, req_res,
            project_root, is_draft, staged_files=staged_files,
        )
        if exit_code == 0 and is_pre_commit:
            _archive_claims(project_root)
        return exit_code

    except _GateBlocked as exc:
        return exc.exit_code
    except Exception as exc:
        print(f"Unexpected error running analyze command: {exc}", file=sys.stderr)
        return 1
