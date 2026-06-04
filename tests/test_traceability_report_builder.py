"""
Unit tests for TraceabilityReportBuilder (TASK-VT-014).
"""

import json
import shutil
import pytest
from pathlib import Path

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
    Test that the builder writes a pre-assembled report to disk and validates it.
    covers: AC-VT-001-01, AC-VT-001-02, AC-VT-001-03, AC-VT-001-04, AC-VT-002-01, AC-VT-006-01
    """
    # Create schemas dir dummy layout so SchemaValidator can work
    schemas_src = Path(__file__).parent.parent / "src" / "vibe_tracing" / "schemas"
    schemas_dest = temp_project_dir / "schemas"
    shutil.copytree(schemas_src, schemas_dest)

    # Pre-assemble the report document (as CLI would do)
    report_doc = {
        "run_id": "RUN-123",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-05-22T12:00:00Z",
        "gate_decision": "pass",
        "requirement_coverage": [
            {
                "req_id": "REQ-VT-001",
                "title": "全链路需求追踪",
                "status": "covered",
                "evidence_ids": ["EVIDENCE-VT-001"],
            }
        ],
        "gaps": [],
        "risks": [],
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    # Initialize builder
    builder = TraceabilityReportBuilder(temp_project_dir)
    output_path = temp_project_dir / "traceability_report.json"

    report = builder.build(report_doc, output_path=output_path)

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
    assert req_cov["status"] == "covered"

    # DOD-VT-014-02: Positive coverage status references must refer to evidence IDs
    all_evidence_ids = {"EVIDENCE-VT-001"}
    for req_item in report["requirement_coverage"]:
        if req_item["status"] in ("covered", "compliant"):
            for ev_id in req_item["evidence_ids"]:
                assert ev_id in all_evidence_ids

    # Gaps and risks should be empty
    assert len(report["gaps"]) == 0
    assert len(report["risks"]) == 0


def test_builder_gaps_and_risks_merging(temp_project_dir) -> None:
    """
    Test that the builder correctly writes a report containing gaps and risks.
    covers: AC-VT-001-01, AC-VT-001-02, AC-VT-001-03, AC-VT-001-04, AC-VT-002-01, AC-VT-006-01
    """
    # Create schemas dir dummy layout so SchemaValidator can work
    schemas_src = Path(__file__).parent.parent / "src" / "vibe_tracing" / "schemas"
    schemas_dest = temp_project_dir / "schemas"
    shutil.copytree(schemas_src, schemas_dest)

    # Pre-assemble report_doc with gaps and risks (as CLI would do after running analyzers)
    report_doc = {
        "run_id": "RUN-456",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-05-22T12:00:00Z",
        "gate_decision": "blocked",
        "requirement_coverage": [],
        "gaps": [
            {"item_id": "REQ-VT-001", "item_type": "requirement", "reason": "No task evidence found."},
            {"item_id": "AC-VT-001-02", "item_type": "acceptance_criterion", "reason": "No test coverage."},
            {"item_id": "CLAIM-VT-001", "item_type": "claim", "reason": "Empty evidence references."},
        ],
        "risks": [
            {
                "risk_id": "RISK-VT-001",
                "description": "Completed claim CLAIM-VT-001 has only self-referential or empty evidence.",
                "severity": "must",
                "business_impact": "Claimed coverage cannot be verified.",
                "suggested_action": "Provide concrete evidence references.",
                "evidence_ids": [],
            },
            {
                "risk_id": "RISK-VT-002",
                "description": "Claim CLAIM-VT-001 is completed but related AC AC-VT-001-02 has no test coverage.",
                "severity": "must",
                "business_impact": "Acceptance criteria may be unverified.",
                "suggested_action": "Add test evidence for AC-VT-001-02.",
                "evidence_ids": [],
            },
            {
                "risk_id": "RISK-VT-003",
                "description": "Requirement REQ-VT-001 has no task coverage.",
                "severity": "must",
                "business_impact": "Requirement may not be implemented.",
                "suggested_action": "Create a task for REQ-VT-001.",
                "evidence_ids": [],
            },
            {
                "risk_id": "RISK-VT-004",
                "description": "AC AC-VT-001-02 has no test coverage.",
                "severity": "must",
                "business_impact": "Acceptance criteria may be unverified.",
                "suggested_action": "Add test coverage for AC-VT-001-02.",
                "evidence_ids": [],
            },
        ],
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    builder = TraceabilityReportBuilder(temp_project_dir)
    output_path = temp_project_dir / "traceability_report.json"

    report = builder.build(report_doc, output_path=output_path)

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
    schemas_src = Path(__file__).parent.parent / "src" / "vibe_tracing" / "schemas"
    schemas_dest = temp_project_dir / "schemas"
    shutil.copytree(schemas_src, schemas_dest)

    builder = TraceabilityReportBuilder(temp_project_dir)

    # Pre-assemble a report_doc with an invalid gate_decision value
    invalid_report_doc = {
        "run_id": "RUN-789",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-05-22T12:00:00Z",
        "gate_decision": "invalid_decision_value",  # will fail enum schema check
        "requirement_coverage": [],
        "gaps": [],
        "risks": [],
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    with pytest.raises(ValueError) as excinfo:
        builder.build(invalid_report_doc)

    assert "Generated report failed schema validation" in str(excinfo.value)
