"""
Tests for the Vibe Tracing Dashboard page rendering and new 6-dimension layout.
"""

import json
from pathlib import Path
import pytest
from vibe_tracing.infra.report.dashboard import DashboardRenderer


@pytest.fixture()
def rendered_dashboard(tmp_path: Path) -> str:
    """Render a dashboard and return its HTML content as a string."""
    renderer = DashboardRenderer(tmp_path)
    output_html = tmp_path / "output" / "dashboard.html"

    evidence_index = {
        "run_id": "RUN-DEC-001",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-06-08T12:00:00Z",
        "evidences": [],
        "full_chain": []
    }

    traceability_report = {
        "run_id": "RUN-DEC-001",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-06-08T12:00:00Z",
        "gate_decision": "blocked",
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

    return output_html.read_text(encoding="utf-8")


class TestNewDashboardLayout:
    """Verify the new sidebar-free horizontal top-nav layout and new tabs exist."""

    def test_top_navigation_bar_exists(self, rendered_dashboard: str):
        """The top-nav horizontal navigation bar is present."""
        assert 'class="top-nav"' in rendered_dashboard
        assert 'Vibe Tracing' in rendered_dashboard

    def test_no_sidebar_present(self, rendered_dashboard: str):
        """The legacy vertical sidebar has been cleaned up."""
        assert 'class="sidebar"' not in rendered_dashboard

    def test_new_tab_menu_items(self, rendered_dashboard: str):
        """Verify the 4 core tabs (Overview, Traceability, Debts, Evidences) exist."""
        assert "Overview" in rendered_dashboard
        assert "Traceability" in rendered_dashboard
        assert "Debts" in rendered_dashboard
        assert "Evidences" in rendered_dashboard
        # Legacy tabs are completely removed
        assert "Bootstrap" not in rendered_dashboard
        assert "Decisions" not in rendered_dashboard

    def test_six_dimension_pipeline_container_exists(self, rendered_dashboard: str):
        """The 6-dimension pipeline container is present."""
        assert 'id="pipeline-stepper-container"' in rendered_dashboard
        assert '质量门禁六维评估流水线' in rendered_dashboard

    def test_five_column_trace_layout_exists(self, rendered_dashboard: str):
        """The 5-column trace tree is present."""
        assert 'class="trace-layout"' in rendered_dashboard
        assert 'id="col-prd"' in rendered_dashboard
        assert 'id="col-ac"' in rendered_dashboard
        assert 'id="col-tasks"' in rendered_dashboard
        assert 'id="col-claims"' in rendered_dashboard
        assert 'id="col-tests"' in rendered_dashboard

    def test_whitelist_management_exists(self, rendered_dashboard: str):
        """The localStorage isolated task whitelist controls exist."""
        assert 'addToWhitelist' in rendered_dashboard
        assert 'removeFromWhitelist' in rendered_dashboard
        assert 'id="whitelist-tags-container"' in rendered_dashboard
