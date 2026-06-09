"""
Tests for the Dashboard decision-card rendering (EVO-TASK-013).

Verifies that the rendered dashboard HTML:
  - embeds the hints JSON (used by decision cards for contextual text)
  - contains the decisions tab container and related JS functions
  - includes the extractPendingDecisions logic for generating decision cards
"""

import json
from pathlib import Path

import pytest

from vibe_tracing.dashboard_renderer import DashboardRenderer


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


# ------------------------------------------------------------------
# Part B.1: Hints data embedding
# ------------------------------------------------------------------

class TestDashboardHintsData:
    """Verify the dashboard embeds hints for decision card contextual text."""

    def test_hints_json_script_tag_present(self, rendered_dashboard: str):
        """The hints-json script tag is present in the rendered HTML."""
        assert '<script id="hints-json" type="application/json">' in rendered_dashboard

    def test_window_hints_assigned(self, rendered_dashboard: str):
        """The JS code assigns parsed hints to window._hints."""
        assert "window._hints = hints" in rendered_dashboard

    def test_hints_contain_level2_values(self, rendered_dashboard: str):
        """The embedded hints JSON contains level2 hint keys used by decision cards.

        field_hints.json level2 entries like 'risk.ac_no_evidence' and
        'risk.stale_file' are keys the decision renderer uses for card text.
        """
        # Extract the hints JSON blob from the script tag
        marker_start = '<script id="hints-json" type="application/json">'
        marker_end = "</script>"
        start = rendered_dashboard.index(marker_start) + len(marker_start)
        end = rendered_dashboard.index(marker_end, start)
        hints_json_str = rendered_dashboard[start:end].strip()

        hints = json.loads(hints_json_str)
        assert isinstance(hints, dict)
        # These level2 keys should be present (from field_hints.json)
        assert "risk.ac_no_evidence" in hints
        assert "risk.stale_file" in hints


# ------------------------------------------------------------------
# Part B.2: Decisions tab structure
# ------------------------------------------------------------------

class TestDashboardDecisionsTab:
    """Verify the decisions tab DOM elements and JS functions exist."""

    def test_decisions_tab_div_exists(self, rendered_dashboard: str):
        """The decisions-container div is present for rendering decision cards."""
        assert 'id="decisions-container"' in rendered_dashboard

    def test_decision_history_div_exists(self, rendered_dashboard: str):
        """The decision-history div is present for showing recorded decisions."""
        assert 'id="decision-history"' in rendered_dashboard

    def test_tab_decisions_content_div(self, rendered_dashboard: str):
        """The tab-decisions content area is present."""
        assert 'id="tab-decisions"' in rendered_dashboard

    def test_nav_item_decisions(self, rendered_dashboard: str):
        """The sidebar has a nav item that switches to the decisions tab."""
        assert "switchTab('decisions')" in rendered_dashboard

    def test_extract_pending_decisions_function(self, rendered_dashboard: str):
        """The extractPendingDecisions function is defined in the JS."""
        assert "function extractPendingDecisions" in rendered_dashboard

    def test_render_decisions_function(self, rendered_dashboard: str):
        """The renderDecisions function is defined in the JS."""
        assert "function renderDecisions" in rendered_dashboard

    def test_submit_decision_function(self, rendered_dashboard: str):
        """The submitDecision function is defined in the JS."""
        assert "async function submitDecision" in rendered_dashboard

    def test_load_decision_history_function(self, rendered_dashboard: str):
        """The loadDecisionHistory function is defined in the JS."""
        assert "async function loadDecisionHistory" in rendered_dashboard

    def test_decision_card_css_class(self, rendered_dashboard: str):
        """The CSS includes the decision-card styling."""
        assert ".decision-card" in rendered_dashboard

    def test_map_action_to_api_function(self, rendered_dashboard: str):
        """The mapActionToApi helper is present for translating UI labels."""
        assert "function mapActionToApi" in rendered_dashboard

    def test_decision_id_generator_function(self, rendered_dashboard: str):
        """The generateDecisionId helper creates deterministic IDs."""
        assert "function generateDecisionId" in rendered_dashboard


# ------------------------------------------------------------------
# Part B.3: Decision card data flow in JS
# ------------------------------------------------------------------

class TestDecisionCardDataFlow:
    """Verify the JS decision card logic references the correct data sources."""

    def test_uses_window_report_for_decisions(self, rendered_dashboard: str):
        """extractPendingDecisions reads from window._report."""
        assert "window._report" in rendered_dashboard

    def test_uses_window_evidence_index_for_decisions(self, rendered_dashboard: str):
        """extractPendingDecisions reads from window._evidenceIndex."""
        assert "window._evidenceIndex" in rendered_dashboard

    def test_uses_window_hints_for_decisions(self, rendered_dashboard: str):
        """extractPendingDecisions reads from window._hints for contextual text."""
        assert "window._hints" in rendered_dashboard

    def test_decision_api_url_configured(self, rendered_dashboard: str):
        """submitDecision posts to the decision server API endpoint."""
        assert "localhost:5000/api/decisions" in rendered_dashboard


# ------------------------------------------------------------------
# Part B.4: DashboardRenderer loads and renders without errors
# ------------------------------------------------------------------

class TestDashboardRendererLoads:
    """Verify the DashboardRenderer can load the template and produce valid HTML."""

    def test_renderer_produces_nonempty_html(self, rendered_dashboard: str):
        """The rendered dashboard is a non-empty HTML document."""
        assert len(rendered_dashboard) > 0
        assert rendered_dashboard.strip().startswith("<")

    def test_renderer_produces_valid_html_structure(self, rendered_dashboard: str):
        """The rendered output contains basic HTML structure."""
        assert "<html" in rendered_dashboard
        assert "</html>" in rendered_dashboard

    def test_renderer_injects_traceability_data(self, rendered_dashboard: str):
        """The rendered HTML embeds the traceability report JSON."""
        assert "RUN-DEC-001" in rendered_dashboard

    def test_renderer_injects_evidence_index(self, rendered_dashboard: str):
        """The rendered HTML embeds the evidence index JSON."""
        assert "PROJECT-VT" in rendered_dashboard

    def test_renderer_creates_output_file(self, tmp_path: Path):
        """DashboardRenderer.render() creates the output file at the specified path."""
        renderer = DashboardRenderer(tmp_path)
        output_html = tmp_path / "output" / "dashboard.html"

        renderer.render(
            evidence_index={
                "run_id": "RUN-001",
                "project_id": "P-001",
                "scan_time": "2026-01-01T00:00:00Z",
                "evidences": [],
            },
            traceability_report={
                "run_id": "RUN-001",
                "project_id": "P-001",
                "scan_time": "2026-01-01T00:00:00Z",
                "gate_decision": "pass",
                "requirement_coverage": [],
                "gaps": [],
                "risks": [],
                "architecture_compliance_status": [],
                "architecture_violations": [],
                "unclear_constraints": [],
            },
            output_path=output_html,
            prd_requirements=[],
        )

        assert output_html.exists()
        content = output_html.read_text(encoding="utf-8")
        assert len(content) > 0
        assert "<html" in content
