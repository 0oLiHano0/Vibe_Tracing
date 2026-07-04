"""
Unit tests for the Dashboard Renderer (TASK-VT-019).
"""

import json
from pathlib import Path
from vibe_tracing.infra.report.dashboard import DashboardRenderer
import pytest


def test_dashboard_renderer_success(tmp_path: Path):
    """
    covers: AC-VT-006-01, AC-VT-006-02
    Verify that DashboardRenderer generates a self-contained dashboard.html,
    properly embedding the provided JSON structures and containing the required script/style blocks.
    """
    renderer = DashboardRenderer(tmp_path)
    output_html = tmp_path / "output" / "dashboard.html"

    evidence_index = {
        "run_id": "RUN-TEST-001",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-05-22T12:00:00Z",
        "full_chain": [
            {
                "req_id": "REQ-VT-001",
                "req_title": "Test Requirement 1",
                "req_priority": "must",
                "req_category": "functional",
                "ac_id": "AC-VT-001-01",
                "ac_title": "Test AC 1",
                "is_testing_required": True,
                "task_id": "TASK-VT-001",
                "task_status": "done",
                "claim_id": "CLAIM-VT-001",
                "test_nodeid": "tests/test_something.py::test_case",
                "test_outcome": "passed",
                "code_path": "src/foo.py",
                "percent_covered": 85.0,
            }
        ],
    }

    traceability_report = {
        "run_id": "RUN-TEST-001",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-05-22T12:00:00Z",
        "gate_decision": "pass",
        "per_issue_states": [
            {
                "issue_id": "substandard:src/foo.py",
                "issue_type": "substandard",
                "state": "CURRENT_WARNING",
                "severity": "WARNING",
                "task_id": "TASK-VT-001",
                "reason": "Test AC coverage substandard",
                "observed": False,
                "activated": True,
                "resolved": False,
                "accepted": False,
            }
        ],
        "historical_issues": [
            {
                "issue_id": "isolated_task:TASK-VT-002",
                "issue_type": "isolated_task",
                "severity": "BLOCK",
                "task_id": "TASK-VT-002",
                "reason": "Isolated task in baseline",
            }
        ],
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
    assert '<script id="hints-json" type="application/json">' in html_content
    assert '<script id="test-results-json" type="application/json">' in html_content
    assert '<script id="coverage-reports-json" type="application/json">' in html_content

    # Check for embedded data content
    assert "RUN-TEST-001" in html_content
    assert "Test Requirement 1" in html_content
    assert "Test AC 1" in html_content

    # TASK-VT-199: verify full_chain 5-column identifiers are embedded
    assert "REQ-VT-001" in html_content
    assert "AC-VT-001-01" in html_content
    assert "TASK-VT-001" in html_content
    assert "CLAIM-VT-001" in html_content
    assert "tests/test_something.py::test_case" in html_content

    # Check that level2 hints are embedded (from field_hints.json)
    assert "window._hints" in html_content
    assert "risk.ac_no_evidence" in html_content

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
    output_html = tmp_path / "output" / "dashboard.html"

    # Minimal dictionaries with empty lists
    evidence_index = {
        "run_id": "RUN-EMPTY",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-05-22T12:00:00Z",
        "full_chain": [],
    }

    traceability_report = {
        "run_id": "RUN-EMPTY",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-05-22T12:00:00Z",
        "gate_decision": "blocked",
        "per_issue_states": [],
        "historical_issues": [],
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


def test_dashboard_renderer_svg_no_emojis(tmp_path: Path):
    """
    covers: AC-VT-006-04
    Verify that the rendered dashboard completely uses inline SVGs and contains no emojis
    in the navigation menus, dynamic statuses, and warnings.
    """
    renderer = DashboardRenderer(tmp_path)
    output_html = tmp_path / "output" / "dashboard.html"

    renderer.render(
        evidence_index={
            "run_id": "RUN-TEST",
            "project_id": "PROJECT-VT",
            "scan_time": "2026-05-22T12:00:00Z",
            "full_chain": [],
        },
        traceability_report={
            "run_id": "RUN-TEST",
            "project_id": "PROJECT-VT",
            "scan_time": "2026-05-22T12:00:00Z",
            "gate_decision": "pass",
            "per_issue_states": [],
            "historical_issues": [],
            "requirement_coverage": [],
            "gaps": [],
            "risks": [],
            "architecture_violations": [],
        },
        output_path=output_html,
        prd_requirements=[],
    )

    assert output_html.exists()
    html_content = output_html.read_text(encoding="utf-8")

    # The sidebar nav-items should contain SVG icons and no emojis
    assert "<svg" in html_content
    # Emojis from original navigation sidebar should be removed
    for emoji in ["📊", "📋", "🧱", "⚙️"]:
        assert emoji not in html_content


def test_dashboard_tab4_evidence_chain_headers_and_fixtures(tmp_path: Path):
    """
    covers: TASK-VT-199 DOD-06 / DOD-07
    Verify Tab 4 (证据索引) renders the 5-column full-traceability chain table
    headers and that both a complete record and a partial-null record (task exists
    but claim_id is null) are embedded into the HTML for client-side rendering.
    """
    renderer = DashboardRenderer(tmp_path)
    output_html = tmp_path / "output" / "dashboard.html"

    evidence_index = {
        "run_id": "RUN-T199",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-07-04T12:00:00Z",
        "full_chain": [
            # Complete 5-column record
            {
                "req_id": "REQ-VT-T199",
                "req_title": "Channel separation",
                "req_priority": "must",
                "req_category": "governance",
                "ac_id": "AC-VT-T199-01",
                "ac_title": "stdout structure",
                "is_testing_required": True,
                "task_id": "TASK-VT-199",
                "task_status": "done",
                "claim_id": "CLAIM-VT-T199",
                "test_nodeid": "tests/test_tab4.py::test_chain",
                "test_outcome": "passed",
                "code_path": "src/vibe_tracing/templates/dashboard.template.html",
                "percent_covered": 92.5,
            },
            # Partial-null record: task exists but no claim (chain-break)
            {
                "req_id": "REQ-VT-T199",
                "req_title": "Channel separation",
                "req_priority": "must",
                "req_category": "governance",
                "ac_id": "AC-VT-T199-02",
                "ac_title": "Dashboard Tab 4",
                "is_testing_required": True,
                "task_id": "TASK-VT-199",
                "task_status": "done",
                "claim_id": None,
                "test_nodeid": None,
                "test_outcome": None,
                "code_path": None,
                "percent_covered": None,
            },
        ],
    }

    traceability_report = {
        "run_id": "RUN-T199",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-07-04T12:00:00Z",
        "gate_decision": "pass",
        "per_issue_states": [],
        "historical_issues": [],
        "requirement_coverage": [],
        "gaps": [],
        "risks": [],
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    renderer.render(
        evidence_index=evidence_index,
        traceability_report=traceability_report,
        output_path=output_html,
        prd_requirements=[],
    )

    assert output_html.exists()
    html_content = output_html.read_text(encoding="utf-8")

    # 5-column th headers (Tab 4 evidence index)
    for header in [
        "需求 / Requirement",
        "AC / Acceptance Criteria",
        "任务 / Task",
        "声明 / Claim",
        "验证与测试 / Test &amp; Coverage",
    ]:
        assert header in html_content, f"missing th header: {header}"

    # Embedded JSON must contain both complete and partial-null fixtures
    assert "REQ-VT-T199" in html_content
    assert "AC-VT-T199-01" in html_content
    assert "AC-VT-T199-02" in html_content
    assert "TASK-VT-199" in html_content
    assert "CLAIM-VT-T199" in html_content
    assert "tests/test_tab4.py::test_chain" in html_content

    # Empty-state fallback string must be present (rendered by JS when full_chain is empty)
    assert "暂无追踪链路数据" in html_content


def test_dashboard_tab4_evidence_chain_empty_state(tmp_path: Path):
    """
    covers: TASK-VT-199 DOD-07
    When full_chain is empty, the Tab 4 container still renders and the JS
    empty-state fallback text is embedded in the template.
    """
    renderer = DashboardRenderer(tmp_path)
    output_html = tmp_path / "output" / "dashboard.html"

    renderer.render(
        evidence_index={
            "run_id": "RUN-T199-EMPTY",
            "project_id": "PROJECT-VT",
            "scan_time": "2026-07-04T12:00:00Z",
            "full_chain": [],
        },
        traceability_report={
            "run_id": "RUN-T199-EMPTY",
            "project_id": "PROJECT-VT",
            "scan_time": "2026-07-04T12:00:00Z",
            "gate_decision": "pass",
            "per_issue_states": [],
            "historical_issues": [],
            "requirement_coverage": [],
            "gaps": [],
            "risks": [],
            "architecture_violations": [],
        },
        output_path=output_html,
        prd_requirements=[],
    )

    assert output_html.exists()
    html_content = output_html.read_text(encoding="utf-8")
    assert 'id="tab-evidences"' in html_content
    assert 'id="evidence-table-body"' in html_content
    assert 'id="evidence-pagination"' in html_content
    assert "暂无追踪链路数据" in html_content
    assert "vt finalize" in html_content
