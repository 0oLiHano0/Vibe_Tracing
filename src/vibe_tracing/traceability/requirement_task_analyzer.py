"""
Requirement to Task Coverage Analyzer for Vibe Tracing.

Analyzes if each requirement in the PRD is covered by valid tasks in the
task list/evidence index, maps statuses, and identifies gaps for must-priority
requirements without task coverage.
"""

from typing import Any, Dict, List
from vibe_tracing.core.enums import CoverageStatus


class RequirementTaskAnalyzer:
    """Analyzes PRD Requirement to Task coverage mapping and identifies coverage gaps."""

    def __init__(self) -> None:
        """Initialize the analyzer."""
        pass

    def analyze(
        self,
        prd_requirements: List[Any],
        evidences: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Analyze requirement task coverage.

        Args:
            prd_requirements: List of parsed requirements from PRD.
            evidences: List of evidence records from the evidence index.

        Returns:
            A dictionary with:
                "requirement_coverage": List of requirement coverage status dicts.
                "gaps": List of identified gaps.
        """
        requirement_coverage: List[Dict[str, Any]] = []
        gaps: List[Dict[str, Any]] = []

        # Filter to only task evidence
        task_evidences = [ev for ev in evidences if ev.get("source_type") == "task"]

        for req in prd_requirements:
            req_id = req.req_id
            priority = req.priority

            # Find matching task evidences covering this req_id
            matching_evs = []
            for ev in task_evidences:
                covers = ev.get("covers", [])
                if req_id in covers:
                    matching_evs.append(ev)

            evidence_ids = sorted([ev["evidence_id"] for ev in matching_evs])

            # Determine requirement coverage status
            if not matching_evs:
                status = CoverageStatus.MISSING.value
                # Check for gap: must requirement with no task coverage
                if priority == "must":
                    gaps.append(
                        {
                            "item_id": req_id,
                            "item_type": "requirement",
                            "reason": f"Must requirement {req_id} ({req.title}) has no task coverage.",
                        }
                    )
            else:
                # If priority is unclear, or any task status is unclear, requirement status is unclear
                task_statuses = {ev.get("status") for ev in matching_evs}
                if (
                    priority == "unclear"
                    or CoverageStatus.UNCLEAR.value in task_statuses
                ):
                    status = CoverageStatus.UNCLEAR.value
                # If all task statuses are covered, requirement is covered
                elif all(st == CoverageStatus.COVERED.value for st in task_statuses):
                    status = CoverageStatus.COVERED.value
                else:
                    status = CoverageStatus.PARTIAL.value

            requirement_coverage.append(
                {
                    "req_id": req_id,
                    "status": status,
                    "evidence_ids": evidence_ids,
                }
            )

        return {
            "requirement_coverage": requirement_coverage,
            "gaps": gaps,
        }
