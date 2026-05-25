"""
Unit and integration tests for the Dashboard Renderer (TASK-VT-019).
"""

import json
from pathlib import Path
from vibe_tracing.dashboard_renderer import DashboardRenderer
from vibe_tracing.cli import main
from test_cli_analyze import setup_mock_project


def test_dashboard_renderer_success(tmp_path: Path):
    """
    covers: AC-VT-006-01, AC-VT-006-02
    Verify that DashboardRenderer generates a self-contained dashboard.html,
    properly embedding the provided JSON structures and containing the required script/style blocks.
    """
    renderer = DashboardRenderer(tmp_path)
    output_html = tmp_path / ".vibetracing" / "output" / "dashboard.html"

    evidence_index = {
        "run_id": "RUN-TEST-001",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-05-22T12:00:00Z",
        "evidences": [
            {
                "evidence_id": "EVIDENCE-VT-001",
                "source_type": "test",
                "source_path": "tests/test_something.py",
                "covers": ["AC-VT-001-01"],
                "status": "covered",
                "details": {},
            }
        ],
    }

    traceability_report = {
        "run_id": "RUN-TEST-001",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-05-22T12:00:00Z",
        "gate_decision": "pass",
        "requirement_coverage": [
            {
                "req_id": "REQ-VT-001",
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

    prd_requirements = [
        {
            "req_id": "REQ-VT-001",
            "title": "Test Requirement 1",
            "priority": "must",
            "acceptance_criteria": [
                {
                    "ac_id": "AC-VT-001-01",
                    "title": "Test AC 1",
                    "is_testing_required": True,
                }
            ],
        }
    ]

    renderer.render(
        evidence_index=evidence_index,
        traceability_report=traceability_report,
        output_path=output_html,
        prd_requirements=prd_requirements,
    )

    assert output_html.exists()
    html_content = output_html.read_text(encoding="utf-8")

    # Check for embedded data tags
    assert '<script id="prd-reqs-json" type="application/json">' in html_content
    assert '<script id="evidence-idx-json" type="application/json">' in html_content
    assert '<script id="trace-report-json" type="application/json">' in html_content

    # Check for embedded data content
    assert "RUN-TEST-001" in html_content
    assert "Test Requirement 1" in html_content
    assert "Test AC 1" in html_content

    # Check for styles and script
    assert "<style>" in html_content
    assert "function switchTab" in html_content


def test_dashboard_renderer_missing_fields(tmp_path: Path):
    """
    covers: AC-VT-006-01, AC-VT-006-02
    Verify that rendering works correctly and gracefully even when parts of the
    report are empty or missing (e.g. empty lists of risks, gaps, or compliance statuses).
    """
    renderer = DashboardRenderer(tmp_path)
    output_html = tmp_path / ".vibetracing" / "output" / "dashboard.html"

    # Minimal dictionaries with empty lists
    evidence_index = {
        "run_id": "RUN-EMPTY",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-05-22T12:00:00Z",
        "evidences": [],
    }

    traceability_report = {
        "run_id": "RUN-EMPTY",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-05-22T12:00:00Z",
        "gate_decision": "blocked",
        "requirement_coverage": [],
        "gaps": [],
        "risks": [],
    }

    renderer.render(
        evidence_index=evidence_index,
        traceability_report=traceability_report,
        output_path=output_html,
        prd_requirements=[],
    )

    assert output_html.exists()
    html_content = output_html.read_text(encoding="utf-8")
    assert "RUN-EMPTY" in html_content


def test_cli_analyze_generates_dashboard(tmp_path: Path):
    """
    covers: AC-VT-006-01
    Verify that executing the CLI analyze command automatically generates the dashboard.html,
    and updates run_metadata.json to include the dashboard's output path.
    """
    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01\ncovers: AC-VT-001-02",
        include_claims=True,
        claim_has_evidence=True,
    )

    exit_code = main(["analyze", "--project-root", str(tmp_path)])
    assert exit_code == 0

    # Check generated files
    dashboard_file = tmp_path / ".vibetracing" / "output" / "dashboard.html"
    assert dashboard_file.exists()

    run_metadata_path = tmp_path / ".vibetracing" / "output" / "run_metadata.json"
    assert run_metadata_path.exists()

    meta = json.loads(run_metadata_path.read_text(encoding="utf-8"))
    assert "dashboard" in meta["output_files"]
    assert meta["output_files"]["dashboard"] == ".vibetracing/output/dashboard.html"
