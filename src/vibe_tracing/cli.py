"""
CLI Entrypoint for Vibe Tracing.

Provides the `analyze` command to load raw inputs, parse requirements,
validate schemas, run analyzers, generate risks, evaluate quality gates,
and output the evidence index, traceability report, and run metadata.
"""

import argparse
import json
import sys
from pathlib import Path

from vibe_tracing import __version__
from vibe_tracing.raw_input_loader import RawInputLoader
from vibe_tracing.schema_validator import SchemaValidator
from vibe_tracing.prd_parser import PrdParser
from vibe_tracing.task_loader import TaskLoader
from vibe_tracing.claim_loader import ClaimLoader


def run_analyze(project_root: Path, output_dir: Path) -> int:
    """
    Execute the full Vibe Tracing analysis pipeline.

    Args:
        project_root: The workspace root path.
        output_dir: The target output directory.

    Returns:
        Exit code:
            0: Gate decision is 'pass' or 'fail' (conditional).
            1: Execution error, invalid inputs, schema errors.
            2: Gate decision is 'blocked'.
    """
    try:
        import importlib

        EvidenceIndexBuilder = importlib.import_module(
            "vibe_tracing.evidence_index_builder"
        ).EvidenceIndexBuilder
        TraceabilityReportBuilder = importlib.import_module(
            "vibe_tracing.traceability_report_builder"
        ).TraceabilityReportBuilder
        MergeGateEngine = importlib.import_module(
            "vibe_tracing.merge_gate_engine"
        ).MergeGateEngine
        ArchitectureComplianceChecker = importlib.import_module(
            "vibe_tracing.architecture_compliance_checker"
        ).ArchitectureComplianceChecker
        RequirementTaskAnalyzer = importlib.import_module(
            "vibe_tracing.traceability.requirement_task_analyzer"
        ).RequirementTaskAnalyzer
        AcTestAnalyzer = importlib.import_module(
            "vibe_tracing.traceability.ac_test_analyzer"
        ).AcTestAnalyzer
        ClaimEvidenceAnalyzer = importlib.import_module(
            "vibe_tracing.traceability.claim_evidence_analyzer"
        ).ClaimEvidenceAnalyzer
        RiskAdvisor = importlib.import_module("vibe_tracing.risk_advisor").RiskAdvisor

        schemas_dir = project_root / "schemas"
        validator = SchemaValidator(schemas_dir)

        # 1. Load raw inputs
        raw_loader = RawInputLoader(project_root)
        manifest = raw_loader.load()
        if manifest.has_required_errors:
            for record in manifest.inputs_used:
                if record.is_required and record.status != "ok":
                    print(
                        f"Error loading required file {record.file_key} ({record.file_path}): {record.error_message}",
                        file=sys.stderr,
                    )
            return 1

        # Check records
        records_dict = {r.file_key: r for r in manifest.inputs_used}
        prd_record = records_dict.get("prd")
        task_list_record = records_dict.get("task_list")
        claims_record = records_dict.get("agent_claims")

        if not prd_record or prd_record.status != "ok":
            print("Error: PRD file missing or failed to load.", file=sys.stderr)
            return 1
        if not task_list_record or task_list_record.status != "ok":
            print("Error: Task list file missing or failed to load.", file=sys.stderr)
            return 1

        # Validate task list schema
        task_list_path = Path(task_list_record.file_path)
        val_task = validator.validate_file(task_list_path, "task_list")
        if not val_task.is_valid:
            print(
                f"Schema validation failed for task list: {val_task.message} at {val_task.field_path}",
                file=sys.stderr,
            )
            return 1

        # Validate agent claims schema if it exists
        claims_exist = False
        claims_path = None
        if claims_record and claims_record.status == "ok":
            claims_exist = True
            claims_path = Path(claims_record.file_path)
            val_claims = validator.validate_file(claims_path, "agent_claims")
            if not val_claims.is_valid:
                print(
                    f"Schema validation failed for agent claims: {val_claims.message} at {val_claims.field_path}",
                    file=sys.stderr,
                )
                return 1

        # Validate Claude Code bootstrap configuration if bootstrap folder/manifest exists or GATE-VT-013 is in quality gates
        has_gate_13 = False
        constraints_path = raw_loader.get_path("architecture_constraints")

        if constraints_path.exists():
            try:
                with constraints_path.open("r", encoding="utf-8") as f:
                    constraints_data = json.load(f)
                for gate in constraints_data.get("quality_gates", []):
                    if gate.get("gate_id") == "GATE-VT-013":
                        has_gate_13 = True
                        break
            except Exception:
                pass

        bootstrap_manifest_path = (
            raw_loader.get_path("claude_bootstrap") / "bootstrap_manifest.json"
        )

        if bootstrap_manifest_path.exists() or has_gate_13:
            from vibe_tracing.claude_code_bootstrap_adapter import (
                ClaudeCodeBootstrapAdapter,
            )

            try:
                bootstrap_adapter = ClaudeCodeBootstrapAdapter(project_root)
                boot_res = bootstrap_adapter.check_governance_rules()
                if boot_res.get("errors"):
                    for err in boot_res["errors"]:
                        print(f"Bootstrap config error: {err}", file=sys.stderr)
                    return 1
            except Exception as exc:
                print(f"Error validating bootstrap config: {exc}", file=sys.stderr)
                return 1

        # 2. Map/parse PRD requirements
        prd_parser = PrdParser()
        prd_res = prd_parser.parse_file(Path(prd_record.file_path))
        if not prd_res.is_valid:
            print(f"PRD parsing error: {'; '.join(prd_res.errors)}", file=sys.stderr)
            return 1

        # 3. Load tasks
        task_loader = TaskLoader(schemas_dir)
        task_res = task_loader.load_and_validate(task_list_path, prd_res)
        if not task_res.is_valid:
            print(
                f"Task list validation error: {'; '.join(task_res.errors)}",
                file=sys.stderr,
            )
            return 1

        # 4. Load claims
        claims_list = []
        if claims_exist and claims_path:
            claim_loader = ClaimLoader(schemas_dir)
            claim_res = claim_loader.load_and_validate(claims_path, task_res)
            if not claim_res.is_valid:
                print(
                    f"Agent claims validation error: {'; '.join(claim_res.errors)}",
                    file=sys.stderr,
                )
                return 1
            claims_list = claim_res.claims

        # 5. Scan tool reports (automatically handled during index building step 6)

        # 6. Build and save evidence index
        index_builder = EvidenceIndexBuilder(project_root)
        index_path = output_dir / "evidence_index.json"
        try:
            evidences_index = index_builder.build(output_path=index_path)
        except Exception as exc:
            print(f"Error building evidence index: {exc}", file=sys.stderr)
            return 1

        evidence_list = evidences_index.get("evidences", [])

        # 7. Run compliance check and analyzers
        req_analyzer = RequirementTaskAnalyzer()
        req_res = req_analyzer.analyze(prd_res.requirements, evidence_list)
        req_gaps = req_res.get("gaps", [])

        ac_analyzer = AcTestAnalyzer()
        ac_res = ac_analyzer.analyze(prd_res.requirements, evidence_list)
        ac_gaps = ac_res.get("gaps", [])

        claim_analyzer = ClaimEvidenceAnalyzer(project_root)
        claim_res = claim_analyzer.analyze(claims_list, evidence_list)
        claim_gaps = claim_res.get("gaps", [])
        claim_risks = claim_res.get("risks", [])

        # Merge gaps
        seen_gaps = set()
        merged_gaps = []
        for gap in req_gaps + ac_gaps + claim_gaps:
            key = (gap.get("item_id"), gap.get("item_type"))
            if key not in seen_gaps:
                seen_gaps.add(key)
                merged_gaps.append(gap)

        # Run Architecture Compliance Checker if constraints file exists
        compliance_res = None
        constraints_path = raw_loader.get_path("architecture_constraints")

        if constraints_path.exists():
            compliance_checker = ArchitectureComplianceChecker(
                project_root, constraints_path=constraints_path
            )
            compliance_res = compliance_checker.check(evidence_list)

        # 8. Run Risk Advisor
        risk_advisor = RiskAdvisor(project_root)
        final_risks = risk_advisor.generate_risks(
            gaps=merged_gaps,
            claims_analysis=claim_res.get("claims_analysis", []),
            claim_risks=claim_risks,
            compliance_result=compliance_res,
        )

        if compliance_res:
            final_risks.extend(compliance_res.get("bootstrap_risks", []))
            final_risks.extend(compliance_res.get("proposal_risks", []))
            for gap in compliance_res.get("bootstrap_gaps", []) + compliance_res.get(
                "proposal_gaps", []
            ):
                key = (gap.get("item_id"), gap.get("item_type"))
                if key not in seen_gaps:
                    seen_gaps.add(key)
                    merged_gaps.append(gap)

        # 9. Run Merge Gate Engine
        gate_engine = MergeGateEngine(project_root)
        gate_res = gate_engine.evaluate(merged_gaps, final_risks, compliance_res)
        gate_decision = gate_res["gate_decision"]

        # 10. Compile and save traceability report
        report_builder = TraceabilityReportBuilder(project_root)
        report_path = output_dir / "traceability_report.json"
        try:
            report_doc = report_builder.build(
                prd_requirements=prd_res.requirements,
                claims=claims_list,
                evidences=evidences_index,
                gate_decision=gate_decision,
                output_path=report_path,
                run_id=evidences_index.get("run_id"),
                project_id=evidences_index.get("project_id"),
                scan_time=evidences_index.get("scan_time"),
            )
        except Exception as exc:
            print(f"Error building traceability report: {exc}", file=sys.stderr)
            return 1

        # 11. Write run_metadata.json
        run_id = report_doc.get("run_id")
        project_id = report_doc.get("project_id")
        scan_time = report_doc.get("scan_time")

        def rel_path_str(p: Path) -> str:
            try:
                if p.is_absolute() and (project_root in p.parents or p == project_root):
                    return str(p.relative_to(project_root))
            except Exception:
                pass
            return str(p)

        input_files_meta = {
            "prd": rel_path_str(Path(prd_record.file_path)),
            "architecture_constraints": rel_path_str(constraints_path)
            if constraints_path.exists()
            else "",
            "task_list": rel_path_str(task_list_path),
        }
        if claims_exist and claims_path:
            input_files_meta["agent_claims"] = rel_path_str(claims_path)

        exit_code = 2 if gate_decision == "blocked" else 0

        dashboard_path = output_dir / "dashboard.html"
        try:
            DashboardRenderer = importlib.import_module(
                "vibe_tracing.dashboard_renderer"
            ).DashboardRenderer
            renderer = DashboardRenderer(project_root)

            prd_reqs_serialized = []
            for req in prd_res.requirements:
                ac_list = []
                for ac in req.acceptance_criteria:
                    ac_list.append(
                        {
                            "ac_id": ac.ac_id,
                            "title": ac.title,
                            "is_testing_required": ac.is_testing_required,
                        }
                    )
                prd_reqs_serialized.append(
                    {
                        "req_id": req.req_id,
                        "title": req.title,
                        "priority": req.priority,
                        "acceptance_criteria": ac_list,
                    }
                )

            renderer.render(
                evidence_index=evidences_index,
                traceability_report=report_doc,
                output_path=dashboard_path,
                prd_requirements=prd_reqs_serialized,
            )
        except Exception as exc:
            print(f"Error rendering dashboard: {exc}", file=sys.stderr)
            return 1

        metadata_doc = {
            "run_id": run_id,
            "project_id": project_id,
            "scan_time": scan_time,
            "input_files": input_files_meta,
            "output_files": {
                "evidence_index": rel_path_str(index_path),
                "traceability_report": rel_path_str(report_path),
                "dashboard": rel_path_str(dashboard_path),
            },
            "gate_decision": gate_decision,
            "exit_code": exit_code,
            "summary": "; ".join(gate_res["reasons"]),
        }

        metadata_path = output_dir / "run_metadata.json"
        try:
            with metadata_path.open("w", encoding="utf-8") as f:
                json.dump(metadata_doc, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            print(f"Error writing run metadata: {exc}", file=sys.stderr)
            return 1

        # Print summary to console
        print(f"Analysis complete. Gate decision: {gate_decision.upper()}")
        for reason in gate_res["reasons"]:
            print(f"- {reason}")

        return exit_code

    except Exception as exc:
        print(f"Unexpected error running analyze command: {exc}", file=sys.stderr)
        return 1


def main(argv=None):
    """CLI main execution function."""
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        description="Vibe Tracing (VT) - Consistency validation framework for agent coding"
    )
    parser.add_argument(
        "--version", action="version", version=f"vibe-tracing {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="sub-command help")

    analyze_parser = subparsers.add_parser(
        "analyze", help="Analyze project consistency and compliance"
    )
    analyze_parser.add_argument(
        "--project-root",
        default=".",
        help="Path to the project workspace root (default: current working directory)",
    )
    analyze_parser.add_argument(
        "--out", help="Path to the output directory (default: <project-root>/output)"
    )

    args = parser.parse_args(argv)

    if args.command == "analyze":
        project_root = Path(args.project_root).resolve()
        raw_loader = RawInputLoader(project_root)
        if args.out:
            output_dir = Path(args.out)
            if not output_dir.is_absolute():
                output_dir = (project_root / output_dir).resolve()
        else:
            output_dir = raw_loader.get_path("output_dir").resolve()

        return run_analyze(project_root, output_dir)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
