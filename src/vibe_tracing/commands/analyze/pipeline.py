"""
Main analyze pipeline orchestration.
"""

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Optional, Set, Tuple

from vibe_tracing.domain.evidence_index_builder import EvidenceIndexBuilder
from vibe_tracing.domain.merge_gate_engine import MergeGateEngine
from vibe_tracing.domain.context import UnifiedContext

from vibe_tracing.commands.common import (
    _GateBlocked,
    _load_context,
    _get_staged_files,
    _determine_affected_items,
)
from vibe_tracing.commands.analyze.gates import _run_integrity_gates
from vibe_tracing.commands.analyze.tools import _execute_tools, _archive_claims
from vibe_tracing.commands.analyze.analysis import (
    _run_analyzers,
    _run_claim_tests,
)
from vibe_tracing.commands.analyze.reports import _build_report_document
from vibe_tracing.commands.analyze.output import _render_output


def _classify_staged_files(staged_files: Set[str], project_root: Path) -> Tuple[list, list]:
    """Classify staged .py files into source code and test file lists.

    Source code: files under ``src/`` with ``.py`` extension.
    Test files:  files under ``tests/`` with ``.py`` extension.

    Returns ``(code_refs, test_refs)`` — each is a list of relative path strings.
    """
    code_refs = []
    test_refs = []
    for f in sorted(staged_files):
        if not f.endswith(".py"):
            continue
        if f.startswith("src/") or f.startswith("src\\"):
            code_refs.append(f)
        elif f.startswith("tests/") or f.startswith("tests\\"):
            test_refs.append(f)
    return code_refs, test_refs


def _auto_generate_claim_from_staged(
    ctx: UnifiedContext,
    project_root: Path,
) -> Optional[UnifiedContext]:
    """Auto-generate a claim from git staged files when current claims are empty.

    Only called in pre-commit mode.  Writes the generated claim to
    ``claims/current.json`` and updates ``ctx.claims_list`` in memory.

    Returns the updated context, or None if no auto-generation was needed.
    """
    claims_path = project_root / ".vibetracing" / "claims" / "current.json"

    staged_files = _get_staged_files(project_root)
    if not staged_files:
        return None

    code_refs, test_refs = _classify_staged_files(staged_files, project_root)
    if not code_refs and not test_refs:
        return None

    config_prefix = ctx.config_prefix
    claim = {
        "claim_id": f"CLAIM-{config_prefix}-001",
        "related_task": "",
        "code_refs": code_refs,
        "test_refs": test_refs,
        "notes": "Auto-generated from staged files",
    }

    claims_path.parent.mkdir(parents=True, exist_ok=True)
    with claims_path.open("w", encoding="utf-8") as f:
        json.dump([claim], f, indent=2, ensure_ascii=False)
        f.write("\n")

    from vibe_tracing.domain.claim_loader import Claim
    claim_obj = Claim(
        claim_id=claim["claim_id"],
        related_task=claim["related_task"],
        code_refs=code_refs,
        test_refs=test_refs,
        notes=claim["notes"],
        is_valid=False,
    )
    ctx.claims_list.append(claim_obj)

    print(
        f"Auto-generated claim from staged files: "
        f"{len(code_refs)} code_refs, {len(test_refs)} test_refs",
        file=sys.stderr,
    )
    return ctx


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

        # 新架构：基于 staged 文件路径判断哪些 claim 被修改
        # 一任务一文件模式下，staged 的 CLAIM-*.json 文件即为被修改的 claim
        directly_staged_claims = set()
        for f in staged_files:
            if f.startswith(".vibetracing/claims/CLAIM-") and f.endswith(".json"):
                # 从文件名提取 claim_id（去掉路径前缀和 .json 后缀）
                claim_id = f.replace(".vibetracing/claims/", "").replace(".json", "")
                directly_staged_claims.add(claim_id)
        directly_staged_items = set(directly_staged_claims)

    return active_gaps, active_risks, evidence_index, staged_items, directly_staged_items


def _run_gate_evaluation(
    project_root: Path,
    active_gaps: list,
    active_risks: list,
    compliance_res: Optional[dict],
    ctx: UnifiedContext,
    staged_items: Optional[Set[str]],
    directly_staged_items: Optional[Set[str]],
    human_decisions: Optional[dict] = None,
) -> dict:
    """Run MergeGateEngine and return gate result dict."""
    from vibe_tracing.infra.db import init_in_memory_db
    if human_decisions is None:
        human_decisions = ctx.human_decisions or {"version": "1.0", "decisions": []}
    conn = init_in_memory_db()
    gate_engine = MergeGateEngine(project_root, conn)
    gate_res = gate_engine.evaluate(
        active_gaps, active_risks,
        compliance_res=compliance_res,
        staged_items=staged_items,
        directly_staged_items=directly_staged_items,
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
    is_pre_commit: bool = False,
    human_decisions: Optional[dict] = None,
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
        ctx, staged_items, directly_staged_items,
        human_decisions=human_decisions,
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
        is_pre_commit=is_pre_commit, staged_files=staged_files,
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
        # Initialize operational logger
        from vibe_tracing.infra.operational_logger import OperationalLogger
        _run_start_t = time.perf_counter()

        _t_ctx = time.perf_counter()
        ctx, raw_loader = _load_context(project_root)
        prd_res = ctx.prd
        is_draft = (prd_res.status == "draft")
        config_prefix = ctx.config_prefix

        log_level = ctx.config.get("logging", {}).get("level", "DEBUG")
        vt_logger = OperationalLogger.init(
            run_id=f"RUN-{uuid.uuid4()}",
            project_root=project_root,
            level=log_level,
        )
        vt_logger.info("run_start", "Analysis pipeline started",
                       is_pre_commit=is_pre_commit, gates_only=gates_only)
        vt_logger.info("phase_end", "Load context completed",
                       phase="load_context",
                       duration_ms=int((time.perf_counter() - _t_ctx) * 1000),
                       config_prefix=config_prefix,
                       has_prd=prd_res is not None,
                       claims_count=len(ctx.claims_list),
                       )

        # Resolve output_dir from config if not explicitly provided
        if output_dir is None:
            _out_rel = ctx.config.get("paths", {}).get("output_dir", "output")
            output_dir = (project_root / _out_rel).resolve()

        _t_gates = time.perf_counter()
        exit_code = _run_integrity_gates(
            ctx, project_root, is_pre_commit, config_prefix,
        )
        vt_logger.info("phase_end", "Integrity gates completed",
                       phase="integrity_gates",
                       duration_ms=int((time.perf_counter() - _t_gates) * 1000),
                       gate_result="pass" if exit_code is None else "blocked",
                       exit_code=exit_code if exit_code is not None else 0,
                       )
        if exit_code is not None:
            return exit_code

        # Auto-generate claim from staged files when claims are empty (pre-commit only)
        if is_pre_commit and not ctx.claims_list:
            _auto_generate_claim_from_staged(ctx, project_root)

        if gates_only:
            print("Gates-only mode: integrity gates passed. Skipping analysis.")
            if is_pre_commit:
                _archive_claims(project_root)
            return 0

        _t_tools = time.perf_counter()
        tool_evidence = _execute_tools(ctx, project_root, is_draft)
        ctx.tool_evidence = tool_evidence
        vt_logger.info("phase_end", "Tool execution completed",
                       phase="execute_tools",
                       duration_ms=int((time.perf_counter() - _t_tools) * 1000),
                       tools_executed=len(tool_evidence),
                       )

        # Build evidence index
        index_builder = EvidenceIndexBuilder(project_root)
        index_path = output_dir / "evidence_index.json"
        _t_build = time.perf_counter()
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
        vt_logger.info("phase_end", "Evidence index built",
                       phase="build_evidence_index",
                       duration_ms=int((time.perf_counter() - _t_build) * 1000),
                       evidences_count=len(evidences_index.get("evidences", [])),
                       )

        # Auto-run claim tests when claims have test_refs but test_results is empty
        _t_claim_tests = time.perf_counter()
        if ctx.claims_list and any(
            getattr(c, "test_refs", None) for c in ctx.claims_list
        ):
            existing_test_results = evidences_index.get("test_results")
            if not existing_test_results:
                evidences_index = _run_claim_tests(
                    project_root, ctx.claims_list, evidences_index
                )
                test_results_map = evidences_index.get("test_results", {})
                total = len(test_results_map)
                passed = sum(
                    1 for v in test_results_map.values()
                    if v.get("status") == "passed"
                )
                failed = sum(
                    1 for v in test_results_map.values()
                    if v.get("status") == "failed"
                )
                cached = 0  # first run, no cache hits possible
                print(
                    f"Executed {total} claim tests: "
                    f"{passed} passed, {failed} failed, {cached} cached",
                    file=sys.stderr,
                )
        vt_logger.info("phase_end", "Claim tests completed",
                       phase="run_claim_tests",
                       duration_ms=int((time.perf_counter() - _t_claim_tests) * 1000),
                       test_results_count=len(evidences_index.get("test_results", {})),
                       )

        evidence_list = evidences_index.get("evidences", [])

        staged_files = _get_staged_files(project_root)

        human_decisions = ctx.human_decisions or {"version": "1.0", "decisions": []}

        _t_analyzers = time.perf_counter()
        merged_gaps, final_risks, compliance_res, claim_res, req_res = _run_analyzers(
            ctx, evidence_list, project_root,
            staged_files=staged_files,
            human_decisions=human_decisions,
        )
        vt_logger.info("phase_end", "Analyzers completed",
                       phase="run_analyzers",
                       duration_ms=int((time.perf_counter() - _t_analyzers) * 1000),
                       gaps_count=len(merged_gaps),
                       risks_count=len(final_risks),
                       has_compliance=compliance_res is not None,
                       )

        _t_eval = time.perf_counter()
        exit_code = _evaluate_and_output(
            ctx, merged_gaps, final_risks, compliance_res,
            output_dir, evidences_index, claim_res, req_res,
            project_root, is_draft, staged_files=staged_files,
            is_pre_commit=is_pre_commit,
            human_decisions=human_decisions,
        )
        gate_decision = "blocked" if exit_code == 2 else "pass"
        vt_logger.info("phase_end", "Evaluate and output completed",
                       phase="evaluate_and_output",
                       duration_ms=int((time.perf_counter() - _t_eval) * 1000),
                       gate_decision=gate_decision,
                       )
        if exit_code == 0 and is_pre_commit:
            _archive_claims(project_root)

        total_duration_ms = int((time.perf_counter() - _run_start_t) * 1000)
        vt_logger.info("run_end", "Analysis pipeline completed",
                       total_duration_ms=total_duration_ms,
                       gate_decision=gate_decision,
                       exit_code=exit_code,
                       )
        return exit_code

    except _GateBlocked as exc:
        return exc.exit_code
    except Exception as exc:
        print(f"Unexpected error running analyze command: {exc}", file=sys.stderr)
        return 1
