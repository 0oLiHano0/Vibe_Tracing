"""
Acceptance Criteria to Test Evidence Coverage Analyzer for Vibe Tracing.

Analyzes if each Acceptance Criterion (AC) in the PRD is covered by a passing
test evidence record, and flags gaps for Must-priority ACs that lack test coverage.
"""

from typing import Any, Dict, List
from vibe_tracing.core.enums import CoverageStatus
from vibe_tracing.operational_logger import OperationalLogger


class AcTestAnalyzer:
    """Analyzes Acceptance Criteria to Test Evidence coverage and identifies gaps."""

    def __init__(self) -> None:
        """Initialize the analyzer."""
        pass

    def analyze(
        self,
        prd_requirements: List[Any],
        evidences: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Analyze AC test coverage.

        Args:
            prd_requirements: List of parsed requirements from PRD.
            evidences: List of evidence records from the evidence index.

        Returns:
            A dictionary with:
                "ac_coverage": List of AC coverage status dicts.
                "gaps": List of identified gaps.
        """
        ac_coverage: List[Dict[str, Any]] = []
        gaps: List[Dict[str, Any]] = []

        # Filter to only passing test evidence (source_type == "test" and status == "covered")
        passing_tests = [
            ev
            for ev in evidences
            if ev.get("source_type") == "test"
            and ev.get("status") == CoverageStatus.COVERED.value
        ]

        # Filter to task evidences for parent task lookup
        task_evidences = [ev for ev in evidences if ev.get("source_type") == "task"]

        for req in prd_requirements:
            priority = req.priority

            for ac in req.acceptance_criteria:
                ac_id = ac.ac_id
                is_testing_required = ac.is_testing_required

                # Find passing tests covering this ac_id
                matching_evs = []
                for ev in passing_tests:
                    covers = ev.get("covers", [])
                    if ac_id in covers:
                        matching_evs.append(ev)

                evidence_ids = sorted([ev["evidence_id"] for ev in matching_evs])

                # Build test refs and results for debug logging
                test_refs = []
                test_results_map = {}
                for ev in matching_evs:
                    src = ev.get("source_path", "")
                    if src:
                        test_refs.append(src)
                        test_results_map[src] = ev.get("status", "")

                if not matching_evs:
                    status = CoverageStatus.MISSING.value
                    # Check for gap: must requirement AC with testing required missing test
                    uncovered_reason = "no_tests" if not any(
                        ev for ev in evidences
                        if ev.get("source_type") == "test" and ac_id in ev.get("covers", [])
                    ) else "all_failed"
                    if priority == "must" and is_testing_required:
                        gaps.append(
                            {
                                "item_id": ac_id,
                                "item_type": "ac",
                                "reason": f"Must acceptance criterion {ac_id} is missing passing test coverage.",
                            }
                        )
                else:
                    status = CoverageStatus.COVERED.value
                    uncovered_reason = ""

                ac_coverage.append(
                    {
                        "ac_id": ac_id,
                        "status": status,
                        "evidence_ids": evidence_ids,
                    }
                )

                # Find parent task_id from task evidences that cover this AC
                parent_task_id = ""
                for ev in task_evidences:
                    if ac_id in ev.get("covers", []):
                        parent_task_id = ev.get("details", {}).get("task_id", "")
                        break

                OperationalLogger.get().debug("ac_mapping", "AC test mapping",
                    ac_id=ac_id,
                    parent_task_id=parent_task_id,
                    test_refs=test_refs,
                    test_results=test_results_map,
                    covered=status == CoverageStatus.COVERED.value,
                    uncovered_reason=uncovered_reason)

        covered_ac_ids = [c["ac_id"] for c in ac_coverage if c["status"] == CoverageStatus.COVERED.value]
        OperationalLogger.get().debug("analyzer_result", "AcTestAnalyzer complete",
            requirements_count=len(prd_requirements),
            evidences_count=len(evidences),
            gaps_count=len(gaps),
            gap_ids=[g.get("item_id") for g in gaps],
            ac_coverage_count=len(ac_coverage),
            ac_ids=[c["ac_id"] for c in ac_coverage],
            covered_ac_ids=covered_ac_ids)

        return {
            "ac_coverage": ac_coverage,
            "gaps": gaps,
        }
