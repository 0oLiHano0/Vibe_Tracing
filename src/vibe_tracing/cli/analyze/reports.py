"""
Report document building and dashboard rendering.
"""

import json
import sys
from pathlib import Path
from typing import Optional

from vibe_tracing.domain.context import UnifiedContext
from vibe_tracing.domain.task.session import TaskSession
from vibe_tracing.domain.governance.metrics import GovernanceMetricsAggregator
from vibe_tracing.domain.capability.metrics import AgentCapabilityMetricsAggregator
from vibe_tracing.cli.analyze.exceptions import _GateBlocked


def _rel_path_str(p: Path, project_root: Path) -> str:
    """Return a relative path string if p is under project_root, else the full path."""
    try:
        if p.is_absolute() and (project_root in p.parents or p == project_root):
            return str(p.relative_to(project_root))
    except Exception:
        pass
    return str(p)


def _build_acceptance_archive(sessions: dict) -> list:
    """聚合所有 CLOSED task 的 acceptance_summary 为存档列表（按 closed_at 倒序）。"""
    archive = []
    for session in sessions.values():
        if session.status != "CLOSED" or session.acceptance_summary is None:
            continue
        s = session.acceptance_summary
        archive.append(
            {
                "task_id": session.task_id,
                "phase_id": session.phase_id,
                "closed_at": session.closed_at,
                "iterations": session.iterations,
                "model": session.model,
                "recommendation": s.recommendation,
                "delivery": s.delivery,
                "severe_risks": list(s.severe_risks),
                "resolved_block": s.resolved_block,
                "resolved_warning": s.resolved_warning,
                "remaining_warning": s.remaining_warning,
            }
        )
    archive.sort(key=lambda r: r.get("closed_at", ""), reverse=True)
    return archive


def _build_report_document(
    ctx: UnifiedContext,
    gate_res: dict,
    evidence_meta: dict,
    merged_gaps: list,
    final_risks: list,
    compliance_res: Optional[dict],
    output_dir: Path,
    project_root: Path,
    isolated_tasks: Optional[list] = None,
    sessions: Optional[dict] = None,
    task_list_for_governance: Optional[list] = None,
) -> dict:
    """Assemble report document, build traceability report with metadata, and return it."""
    from vibe_tracing.infra.report.traceability import TraceabilityReportBuilder

    gate_decision = gate_res["gate_decision"]

    report_doc = {
        "run_id": evidence_meta.get("run_id"),
        "project_id": evidence_meta.get("project_id"),
        "scan_time": evidence_meta.get("scan_time"),
        "gate_decision": gate_decision,
        "per_issue_states": gate_res.get("per_issue_states", []),
        "historical_issues": gate_res.get("historical_issues", []),
        "requirement_coverage": [],
        "gaps": merged_gaps,
        "risks": final_risks,
        "architecture_compliance_status": compliance_res.get(
            "architecture_compliance_status", []
        ) if compliance_res else [],
        "architecture_violations": compliance_res.get(
            "architecture_violations", []
        ) if compliance_res else [],
        "unclear_constraints": compliance_res.get("unclear_constraints", [])
        if compliance_res else [],
        "accepted_rules": compliance_res.get("accepted_rules", [])
        if compliance_res else [],
    }

    # Add isolated tasks as non-blocking warnings
    if isolated_tasks:
        warnings = []
        for task in isolated_tasks:
            reason = task.get("reason", "")
            if reason == "missing_req":
                desc = f"孤立任务 {task['task_id']}: 缺少需求关联"
            elif reason == "missing_ac":
                desc = f"孤立任务 {task['task_id']}: 缺少验收标准关联"
            else:
                desc = f"孤立任务 {task['task_id']}: 缺少需求和验收标准关联"
            warnings.append(desc)
        report_doc["warnings"] = warnings

    # ── T195：治理演进 / 验收存档 三个顶层 key ───────────────────────────
    if sessions:
        acceptance_archive = _build_acceptance_archive(sessions)
        rule_stats_table = GovernanceMetricsAggregator.aggregate_rule_stats_table(
            sessions
        )
        governance_metrics = {
            "derived_task_ratio": GovernanceMetricsAggregator.aggregate_derived_task_ratio(
                task_list_for_governance or [], sessions
            ),
            "avg_iterations_by_phase": GovernanceMetricsAggregator.aggregate_avg_iterations_by_phase(
                sessions
            ),
        }
    else:
        acceptance_archive = []
        rule_stats_table = []
        governance_metrics = {
            "derived_task_ratio": 0.0,
            "avg_iterations_by_phase": {},
        }
    report_doc["acceptance_archive"] = acceptance_archive
    report_doc["rule_stats_table"] = rule_stats_table
    report_doc["governance_metrics"] = governance_metrics

    # ── T196：Agent 能力指标 ────────────────────────────────────────────
    if sessions:
        report_doc["agent_capability_metrics"] = AgentCapabilityMetricsAggregator.compute_all(
            sessions
        )
    else:
        report_doc["agent_capability_metrics"] = {
            "first_time_right_rate": 0.0,
            "avg_iterations": 0.0,
            "same_category_repeat_tasks": 0,
            "block_concentration": [],
            "capability_warnings": [],
            "closed_task_count": 0,
        }

    # Build and save traceability report
    report_builder = TraceabilityReportBuilder(project_root)
    report_path = output_dir / "traceability_report.json"
    try:
        report_doc = report_builder.build(report_doc, output_path=report_path)
    except Exception as exc:
        print(f"Error building traceability report: {exc}", file=sys.stderr)
        raise _GateBlocked(1) from exc

    # Build and embed metadata
    metadata_doc = _build_metadata(ctx, gate_res, report_doc, output_dir, project_root)
    report_doc["metadata"] = metadata_doc
    try:
        with report_path.open("w", encoding="utf-8") as f:
            json.dump(report_doc, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"Error writing traceability report with metadata: {exc}", file=sys.stderr)
        raise _GateBlocked(1) from exc

    return report_doc


def _build_metadata(
    ctx: UnifiedContext,
    gate_res: dict,
    report_doc: dict,
    output_dir: Path,
    project_root: Path,
) -> dict:
    """Build the metadata section for the traceability report."""
    manifest = ctx.manifest
    claims_list = ctx.claims_list
    gate_decision = gate_res["gate_decision"]
    evidences_dir = output_dir / "evidences"
    report_path = output_dir / "traceability_report.json"
    dashboard_path = output_dir / "dashboard.html"
    exit_code = 2 if gate_decision == "blocked" else 0

    records_dict = {r.file_key: r for r in manifest.inputs_used}
    prd_record = records_dict.get("prd")
    constraints_path = project_root / "docs" / "architecture_constraints.json"
    task_list_path = project_root / "docs" / "task_list.json"
    claims_record = records_dict.get("agent_claims")

    input_files_meta = {
        "prd": _rel_path_str(Path(prd_record.file_path), project_root) if prd_record else "",
        "architecture_constraints": _rel_path_str(constraints_path, project_root) if constraints_path.exists() else "",
        "task_list": _rel_path_str(task_list_path, project_root),
    }
    if claims_list and claims_record:
        input_files_meta["agent_claims"] = _rel_path_str(Path(claims_record.file_path), project_root)

    return {
        "run_id": report_doc.get("run_id"),
        "project_id": report_doc.get("project_id"),
        "scan_time": report_doc.get("scan_time"),
        "input_files": input_files_meta,
        "output_files": {
            "evidences_dir": _rel_path_str(evidences_dir, project_root),
            "traceability_report": _rel_path_str(report_path, project_root),
            "dashboard": _rel_path_str(dashboard_path, project_root),
        },
        "gate_decision": gate_decision,
        "exit_code": exit_code,
        "summary": "; ".join(
            pis.get("reason", pis.get("issue_id", ""))
            for pis in gate_res.get("per_issue_states", [])
            if pis.get("state") not in ("RESOLVED",)
        ),
    }


def _render_dashboard(
    ctx: UnifiedContext,
    report_doc: dict,
    evidence_meta: dict,
    output_dir: Path,
    project_root: Path,
) -> None:
    """Render the dashboard HTML file."""
    from vibe_tracing.infra.report.dashboard import DashboardRenderer
    from vibe_tracing.domain.governance.change_proposal import ArchitectureChangeProposalEngine

    manifest = ctx.manifest
    prd_res = ctx.prd
    dashboard_path = output_dir / "dashboard.html"
    try:
        _dash_constraints_hash = None
        if manifest:
            for _r in manifest.inputs_used:
                if _r.file_key == "architecture_constraints" and _r.sha256_hash:
                    _dash_constraints_hash = _r.sha256_hash
                    break

        # Get proposal status (cli layer calls domain layer)
        prop_engine = ArchitectureChangeProposalEngine(
            project_root, config_data=ctx.config,
            constraints_data=ctx.constraints,
        )
        try:
            prop_res = prop_engine.check_governance(
                constraints_hash=_dash_constraints_hash,
            )
        except Exception as exc:
            prop_res = {
                "is_valid": False,
                "errors": [f"评估架构约束变更建议时发生异常: {exc}"],
                "warnings": [],
                "risks": [],
                "gaps": [],
                "proposals": [],
            }

        renderer = DashboardRenderer(
            project_root,
            constraints_hash=_dash_constraints_hash,
            config_data=ctx.config,
        )
        prd_reqs_serialized = []
        for req in prd_res.requirements:
            ac_list = [
                {
                    "ac_id": ac.ac_id,
                    "title": ac.title,
                    "is_testing_required": ac.is_testing_required,
                }
                for ac in req.acceptance_criteria
            ]
            prd_reqs_serialized.append(
                {
                    "req_id": req.req_id,
                    "title": req.title,
                    "priority": req.priority,
                    "acceptance_criteria": ac_list,
                }
            )
        # Load split evidence data
        evidences_dir = output_dir / "evidences"
        test_results_data = []
        coverage_reports_data = []
        tr_path = evidences_dir / "test_results.json"
        cr_path = evidences_dir / "coverage_reports.json"
        if tr_path.is_file():
            try:
                test_results_data = json.loads(tr_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        if cr_path.is_file():
            try:
                coverage_reports_data = json.loads(cr_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        # Build evidence index from full_chain data
        evidence_index = {
            "run_id": evidence_meta.get("run_id"),
            "project_id": evidence_meta.get("project_id"),
            "scan_time": evidence_meta.get("scan_time"),
            "full_chain": evidence_meta.get("full_chain", []),
        }
        renderer.render(
            evidence_index=evidence_index,
            traceability_report=report_doc,
            output_path=dashboard_path,
            prd_requirements=prd_reqs_serialized,
            test_results=test_results_data,
            coverage_reports=coverage_reports_data,
            prop_res=prop_res,
        )
    except Exception as exc:
        print(f"Error rendering dashboard: {exc}", file=sys.stderr)
        raise _GateBlocked(1) from exc
