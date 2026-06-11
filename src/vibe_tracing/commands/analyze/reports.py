"""
Report document building and dashboard rendering.
"""

import json
import sys
from pathlib import Path
from typing import Optional

from vibe_tracing.context import UnifiedContext
from vibe_tracing.commands.common import _GateBlocked, _rel_path_str


def _build_report_document(
    ctx: UnifiedContext,
    gate_res: dict,
    evidence_index: dict,
    merged_gaps: list,
    final_risks: list,
    compliance_res: Optional[dict],
    req_res: dict,
    output_dir: Path,
    project_root: Path,
) -> dict:
    """Assemble report document, build traceability report with metadata, and return it."""
    from vibe_tracing.traceability_report_builder import TraceabilityReportBuilder

    gate_decision = gate_res["gate_decision"]

    report_doc = {
        "run_id": evidence_index.get("run_id"),
        "project_id": evidence_index.get("project_id"),
        "scan_time": evidence_index.get("scan_time"),
        "gate_decision": gate_decision,
        "requirement_coverage": req_res.get("requirement_coverage", []),
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

    # Add coverage summary to report
    cb_data = evidence_index.get("coverage_baseline", {})
    if cb_data:
        total_stmts = sum(f.get("num_statements", 0) for f in cb_data.values() if isinstance(f, dict))
        total_covered_f = sum(
            f.get("num_statements", 0) * f.get("percent_covered", 0) / 100
            for f in cb_data.values() if isinstance(f, dict)
        )
        aggregate_pct = round(total_covered_f / total_stmts * 100, 1) if total_stmts > 0 else 0
        report_doc["coverage_summary"] = {
            "aggregate_percent": aggregate_pct,
            "total_statements": total_stmts,
            "total_covered": int(total_covered_f),
            "file_count": len(cb_data),
        }

    # Build and save traceability report
    report_builder = TraceabilityReportBuilder(project_root)
    report_path = output_dir / "traceability_report.json"
    try:
        report_doc = report_builder.build(report_doc, output_path=report_path)
    except Exception as exc:
        print(f"Error building traceability report: {exc}", file=sys.stderr)
        raise _GateBlocked(1)

    # Build and embed metadata
    metadata_doc = _build_metadata(ctx, gate_res, report_doc, output_dir, project_root)
    report_doc["metadata"] = metadata_doc
    try:
        with report_path.open("w", encoding="utf-8") as f:
            json.dump(report_doc, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"Error writing traceability report with metadata: {exc}", file=sys.stderr)
        raise _GateBlocked(1)

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
    index_path = output_dir / "evidence_index.json"
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
            "evidence_index": _rel_path_str(index_path, project_root),
            "traceability_report": _rel_path_str(report_path, project_root),
            "dashboard": _rel_path_str(dashboard_path, project_root),
        },
        "gate_decision": gate_decision,
        "exit_code": exit_code,
        "summary": "; ".join(gate_res["reasons"]),
    }


def _render_dashboard(
    ctx: UnifiedContext,
    report_doc: dict,
    evidence_index: dict,
    output_dir: Path,
    project_root: Path,
) -> None:
    """Render the dashboard HTML file."""
    from vibe_tracing.dashboard_renderer import DashboardRenderer

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
        renderer.render(
            evidence_index=evidence_index,
            traceability_report=report_doc,
            output_path=dashboard_path,
            prd_requirements=prd_reqs_serialized,
        )
    except Exception as exc:
        print(f"Error rendering dashboard: {exc}", file=sys.stderr)
        raise _GateBlocked(1)
