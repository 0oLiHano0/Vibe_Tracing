"""
Unit tests for TraceabilityReportBuilder (TASK-VT-014).
"""

import json
import os
import shutil
import pytest
from pathlib import Path

from vibe_tracing.claim_loader import Claim
from vibe_tracing.core.enums import CoverageStatus
from vibe_tracing.prd_parser import AcceptanceCriteria, Requirement
from vibe_tracing.traceability_report_builder import TraceabilityReportBuilder


@pytest.fixture
def temp_project_dir():
    """Create and clean up a temporary directory inside the workspace for tests."""
    temp_dir = Path(__file__).parent / "tmp_report_builder"
    temp_dir.mkdir(parents=True, exist_ok=True)
    yield temp_dir
    if temp_dir.exists():
        shutil.rmtree(temp_dir)


def test_builder_successful_compilation(temp_project_dir) -> None:
    """
    Test successful compilation of traceability report, checking schema validity and positive coverage evidence matching.
    covers: AC-VT-001-01, AC-VT-001-02, AC-VT-001-03, AC-VT-001-04, AC-VT-002-01, AC-VT-006-01
    """
    # Create schemas dir dummy layout so SchemaValidator can work
    schemas_src = Path(__file__).parent.parent / "schemas"
    schemas_dest = temp_project_dir / "schemas"
    shutil.copytree(schemas_src, schemas_dest)

    # Prepare dummy files
    code_file = temp_project_dir / "app.py"
    code_file.write_text("print('hello')")
    os_time_mtime = 1000000000
    os.utime(code_file, (os_time_mtime, os_time_mtime))

    # Setup inputs
    prd_requirements = [
        Requirement(
            req_id="REQ-VT-001",
            title="全链路需求追踪",
            priority="must",
            acceptance_criteria=[
                AcceptanceCriteria(
                    ac_id="AC-VT-001-01",
                    title="需求必须能关联任务",
                    is_testing_required=True,
                )
            ],
        )
    ]

    claims = [
        Claim(
            claim_id="CLAIM-VT-001",
            related_task="TASK-VT-001",
            claimed_status=CoverageStatus.COVERED.value,
            evidence_refs=["EVIDENCE-VT-002"],
            timestamp="2026-05-22T10:00:00Z",
            code_refs=[str(code_file.relative_to(temp_project_dir))],
        )
    ]

    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "task",
            "covers": ["REQ-VT-001", "AC-VT-001-01"],
            "status": CoverageStatus.COVERED.value,
            "details": {
                "task_id": "TASK-VT-001",
                "title": "Task 1",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
            },
        },
        {
            "evidence_id": "EVIDENCE-VT-002",
            "source_type": "test",
            "covers": ["AC-VT-001-01"],
            "status": CoverageStatus.COVERED.value,
        },
    ]

    # Initialize builder
    builder = TraceabilityReportBuilder(temp_project_dir)
    output_path = temp_project_dir / "traceability_report.json"

    report = builder.build(
        prd_requirements=prd_requirements,
        claims=claims,
        evidences=evidences,
        gate_decision="pass",
        output_path=output_path,
        run_id="RUN-123",
        project_id="PROJECT-VT",
        scan_time="2026-05-22T12:00:00Z",
    )

    # DOD-VT-014-01: traceability_report.json must exist and be valid JSON
    assert output_path.exists()
    with output_path.open("r", encoding="utf-8") as f:
        saved_doc = json.load(f)
    assert saved_doc == report

    assert report["run_id"] == "RUN-123"
    assert report["project_id"] == "PROJECT-VT"
    assert report["scan_time"] == "2026-05-22T12:00:00Z"
    assert report["gate_decision"] == "pass"
    assert len(report["requirement_coverage"]) == 1

    req_cov = report["requirement_coverage"][0]
    assert req_cov["req_id"] == "REQ-VT-001"
    assert req_cov["status"] == CoverageStatus.COVERED.value

    # DOD-VT-014-02: Positive coverage status references must refer to evidence IDs present in the evidence index
    all_evidence_ids = {ev["evidence_id"] for ev in evidences}
    for req_item in report["requirement_coverage"]:
        if req_item["status"] in (
            CoverageStatus.COVERED.value,
            CoverageStatus.COMPLIANT.value,
        ):
            for ev_id in req_item["evidence_ids"]:
                assert ev_id in all_evidence_ids

    # Gaps and risks should be empty
    assert len(report["gaps"]) == 0
    assert len(report["risks"]) == 0


def test_builder_gaps_and_risks_merging(temp_project_dir) -> None:
    """
    Test that gaps and risks from all three analyzers are correctly merged and present in the final output.
    covers: AC-VT-001-01, AC-VT-001-02, AC-VT-001-03, AC-VT-001-04, AC-VT-002-01, AC-VT-006-01
    """
    # Create schemas dir dummy layout so SchemaValidator can work
    schemas_src = Path(__file__).parent.parent / "schemas"
    schemas_dest = temp_project_dir / "schemas"
    shutil.copytree(schemas_src, schemas_dest)

    # 1. Req REQ-VT-001 with no task evidence (Gap from RequirementTaskAnalyzer)
    # 2. AC AC-VT-001-02 with no test evidence (Gap from AcTestAnalyzer)
    # 3. Completed Claim CLAIM-VT-001 with empty evidence refs (Gap & Risk from ClaimEvidenceAnalyzer)
    prd_requirements = [
        Requirement(
            req_id="REQ-VT-001",
            title="Req 1",
            priority="must",
            acceptance_criteria=[
                AcceptanceCriteria(
                    ac_id="AC-VT-001-01", title="AC 1", is_testing_required=True
                ),
                AcceptanceCriteria(
                    ac_id="AC-VT-001-02", title="AC 2", is_testing_required=True
                ),
            ],
        )
    ]

    claims = [
        Claim(
            claim_id="CLAIM-VT-001",
            related_task="TASK-VT-001",
            claimed_status=CoverageStatus.COVERED.value,
            evidence_refs=[],  # empty -> gap and risk
            timestamp="2026-05-22T10:00:00Z",
        )
    ]

    # Task exists but is completed, and test for AC-01 is present
    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "task",
            "covers": ["AC-VT-001-01", "AC-VT-001-02"],
            "status": CoverageStatus.COVERED.value,
            "details": {
                "task_id": "TASK-VT-001",
                "title": "Task 1",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
            },
        },
        {
            "evidence_id": "EVIDENCE-VT-002",
            "source_type": "test",
            "covers": ["AC-VT-001-01"],
            "status": CoverageStatus.COVERED.value,
        },
    ]

    # Note that REQ-VT-001 is NOT covered by task evidence because "covers" in EVIDENCE-VT-001 only has ACs.
    # So RequirementTaskAnalyzer will see REQ-VT-001 as missing task coverage (must requirement -> gap).
    # AC-VT-001-02 has no test coverage -> AcTestAnalyzer gap.
    # claim has empty evidence -> ClaimEvidenceAnalyzer gap and risk.

    builder = TraceabilityReportBuilder(temp_project_dir)
    output_path = temp_project_dir / "traceability_report.json"

    report = builder.build(
        prd_requirements=prd_requirements,
        claims=claims,
        evidences=evidences,
        gate_decision="blocked",
        output_path=output_path,
    )

    # DOD-VT-014-03: Gaps and risks must be explicitly populated
    assert len(report["gaps"]) == 3
    assert len(report["risks"]) == 4

    gap_item_ids = {g["item_id"] for g in report["gaps"]}
    assert "REQ-VT-001" in gap_item_ids
    assert "AC-VT-001-02" in gap_item_ids
    assert "CLAIM-VT-001" in gap_item_ids

    risk_descriptions = {r["description"] for r in report["risks"]}
    assert (
        "Completed claim CLAIM-VT-001 has only self-referential or empty evidence."
        in risk_descriptions
    )
    assert (
        "Claim CLAIM-VT-001 is completed but related AC AC-VT-001-02 has no test coverage."
        in risk_descriptions
    )
    assert any("REQ-VT-001" in desc for desc in risk_descriptions)
    assert any("AC-VT-001-02" in desc for desc in risk_descriptions)

    # Verify enrichment
    for r in report["risks"]:
        assert "business_impact" in r
        assert "suggested_action" in r


def test_builder_schema_validation_failure(temp_project_dir) -> None:
    """
    Test that schema validation failure throws a ValueError.
    covers: AC-VT-001-03, AC-VT-006-01
    """
    # Create schemas dir dummy layout so SchemaValidator can work
    schemas_src = Path(__file__).parent.parent / "schemas"
    schemas_dest = temp_project_dir / "schemas"
    shutil.copytree(schemas_src, schemas_dest)

    builder = TraceabilityReportBuilder(temp_project_dir)

    with pytest.raises(ValueError) as excinfo:
        builder.build(
            prd_requirements=[],
            claims=[],
            evidences=[],
            gate_decision="invalid_decision_value",  # will fail enum schema check
        )

    assert "Generated report failed schema validation" in str(excinfo.value)
