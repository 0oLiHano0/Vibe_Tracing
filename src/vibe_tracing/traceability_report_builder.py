"""
Traceability Report Builder for Vibe Tracing.

Combines output from the RequirementTaskAnalyzer, AcTestAnalyzer, and
ClaimEvidenceAnalyzer into a unified, schema-compliant traceability report.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from vibe_tracing.raw_input_loader import RawInputLoader
from vibe_tracing.risk_advisor import RiskAdvisor
from vibe_tracing.schema_validator import SchemaValidator
from vibe_tracing.traceability.ac_test_analyzer import AcTestAnalyzer
from vibe_tracing.traceability.claim_evidence_analyzer import ClaimEvidenceAnalyzer
from vibe_tracing.traceability.requirement_task_analyzer import RequirementTaskAnalyzer


class TraceabilityReportBuilder:
    """Orchestrates all traceability analyzers and compiles the final report."""

    def __init__(self, project_root: Path) -> None:
        """Initialize the builder with project root and schema validator."""
        self.project_root = project_root
        self.schemas_dir = project_root / "schemas"
        self.schema_validator = SchemaValidator(self.schemas_dir)

    def build(
        self,
        prd_requirements: List[Any],
        claims: List[Any],
        evidences: Union[Dict[str, Any], List[Dict[str, Any]]],
        gate_decision: str = "blocked",
        output_path: Optional[Path] = None,
        run_id: Optional[str] = None,
        project_id: Optional[str] = None,
        scan_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Assemble the final traceability report and write it to disk.

        Args:
            prd_requirements: List of requirements parsed from PRD.
            claims: List of parsed Agent Claims.
            evidences: Full evidence index dictionary or a list of evidence records.
            gate_decision: The quality gate decision ("pass", "fail", "blocked"). Defaults to "blocked".
            output_path: Output path for the traceability_report.json.
            run_id: Optional run ID to override what is in evidences/index.
            project_id: Optional project ID to override.
            scan_time: Optional scan time string to override.

        Returns:
            The compiled report dictionary.

        Raises:
            ValueError: If writing or validation fails.
        """
        # Resolve evidences list and extract metadata from the evidence index dict if available
        evidence_list: List[Dict[str, Any]] = []
        ref_run_id = None
        ref_project_id = None
        ref_scan_time = None

        if isinstance(evidences, dict):
            ref_run_id = evidences.get("run_id")
            ref_project_id = evidences.get("project_id")
            ref_scan_time = evidences.get("scan_time")
            evidence_list = evidences.get("evidences", [])
        elif isinstance(evidences, list):
            evidence_list = evidences

        # Determine metadata values
        final_run_id = run_id or ref_run_id or f"RUN-{uuid.uuid4()}"
        final_project_id = project_id or ref_project_id or "PROJECT-VT"
        final_scan_time = (
            scan_time
            or ref_scan_time
            or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )

        # 1. Run Requirement Task Analyzer
        req_analyzer = RequirementTaskAnalyzer()
        req_res = req_analyzer.analyze(prd_requirements, evidence_list)
        req_coverage = req_res.get("requirement_coverage", [])
        req_gaps = req_res.get("gaps", [])

        # 2. Run AC Test Analyzer
        ac_analyzer = AcTestAnalyzer()
        ac_res = ac_analyzer.analyze(prd_requirements, evidence_list)
        ac_gaps = ac_res.get("gaps", [])

        # 3. Run Claim Evidence Analyzer
        claim_analyzer = ClaimEvidenceAnalyzer(self.project_root)
        claim_res = claim_analyzer.analyze(claims, evidence_list)
        claim_gaps = claim_res.get("gaps", [])
        risks = claim_res.get("risks", [])

        # Merge and deduplicate gaps by (item_id, item_type)
        seen_gaps = set()
        merged_gaps = []
        for gap in req_gaps + ac_gaps + claim_gaps:
            key = (gap.get("item_id"), gap.get("item_type"))
            if key not in seen_gaps:
                seen_gaps.add(key)
                merged_gaps.append(gap)

        # 4. Run Architecture Compliance Checker if constraints file exists
        compliance_res = None
        raw_loader = RawInputLoader(self.project_root)
        constraints_path = raw_loader.get_path("architecture_constraints")

        if constraints_path.exists():
            import importlib

            ArchitectureComplianceChecker = importlib.import_module(
                "vibe_tracing.architecture_compliance_checker"
            ).ArchitectureComplianceChecker
            compliance_checker = ArchitectureComplianceChecker(
                self.project_root, constraints_path=constraints_path
            )
            compliance_res = compliance_checker.check(evidence_list)

        # 5. Run Risk Advisor
        risk_advisor = RiskAdvisor(self.project_root)
        final_risks = risk_advisor.generate_risks(
            gaps=merged_gaps,
            claims_analysis=claim_res.get("claims_analysis", []),
            claim_risks=risks,
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

        # Assemble the report document
        report_doc = {
            "run_id": final_run_id,
            "project_id": final_project_id,
            "scan_time": final_scan_time,
            "gate_decision": gate_decision,
            "requirement_coverage": req_coverage,
            "gaps": merged_gaps,
            "risks": final_risks,
            "architecture_compliance_status": compliance_res.get(
                "architecture_compliance_status", []
            )
            if compliance_res
            else [],
            "architecture_violations": compliance_res.get("architecture_violations", [])
            if compliance_res
            else [],
            "unclear_constraints": compliance_res.get("unclear_constraints", [])
            if compliance_res
            else [],
        }

        # Write output file
        if output_path is None:
            output_path = self.project_root / "output" / "traceability_report.json"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(report_doc, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            raise ValueError(f"Failed to write traceability report: {exc}")

        # Validate file against schemas/traceability_report.schema.json
        val_res = self.schema_validator.validate_file(
            output_path, "traceability_report"
        )
        if not val_res.is_valid:
            error_msg = f"Generated report failed schema validation: {val_res.message}"
            if val_res.field_path:
                error_msg += f" at field '{val_res.field_path}'"
            raise ValueError(error_msg)

        return report_doc
