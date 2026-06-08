"""
Dashboard Renderer for Vibe Tracing.

Renders a self-contained, offline-compatible HTML dashboard from evidence index
and traceability report data. Strictly visualizes data without recalculation.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import importlib.resources as pkg_resources

from vibe_tracing import templates


class DashboardRenderer:
    """Renders a premium, single-file HTML report with zero external dependencies."""

    def __init__(
        self,
        project_root: Path,
        constraints_hash: Optional[str] = None,
        config_data: Optional[dict] = None,
    ) -> None:
        """Initialize the renderer with project root."""
        self.project_root = project_root
        self.constraints_hash = constraints_hash
        self.config_data = config_data

    def render(
        self,
        evidence_index: Dict[str, Any],
        traceability_report: Dict[str, Any],
        output_path: Path,
        prd_requirements: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """
        Renders the HTML dashboard file.

        Args:
            evidence_index: The evidence index JSON data.
            traceability_report: The traceability report JSON data.
            output_path: Target path to save the dashboard.html.
            prd_requirements: List of requirement dicts containing titles, priorities, and ACs.
        """
        # Ensure the directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Load proposal status
        from vibe_tracing.architecture_change_proposal import (
            ArchitectureChangeProposalEngine,
        )
        try:
            proposal_engine = ArchitectureChangeProposalEngine(
                self.project_root, config_data=self.config_data,
            )
            prop_res = proposal_engine.check_governance(
                constraints_hash=self.constraints_hash,
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

        # Prepare JSON data to embed
        prd_reqs_json = json.dumps(prd_requirements or [], ensure_ascii=False)
        evidence_idx_json = json.dumps(evidence_index, ensure_ascii=False)
        trace_report_json = json.dumps(traceability_report, ensure_ascii=False)
        prop_data_json = json.dumps(prop_res, ensure_ascii=False)

        # Load template from package resources
        try:
            template_content = pkg_resources.read_text(templates, "dashboard.template.html")
        except Exception as exc:
            raise FileNotFoundError(f"Failed to load dashboard.template.html resource: {exc}")

        # Inject JSON variables by replacing placeholders
        html_content = (
            template_content.replace("{prd_reqs_json}", prd_reqs_json)
            .replace("{evidence_idx_json}", evidence_idx_json)
            .replace("{trace_report_json}", trace_report_json)
            .replace("{boot_data_json}", "null")
            .replace("{prop_data_json}", prop_data_json)
        )

        # Write file
        with output_path.open("w", encoding="utf-8") as f:
            f.write(html_content)
