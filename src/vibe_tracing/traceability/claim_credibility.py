"""
Claim Credibility Assessment for Vibe Tracing.

Assesses the credibility of agent claims based on VT-executed tool evidence,
task path lookups, and deliverable file existence checks.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from vibe_tracing.claim_loader import Claim
from vibe_tracing.task_loader import TaskListLoadResult


def assess_claim_credibility(
    claims: List[Claim],
    evidence_list: List[Dict[str, Any]],
    task_result: Optional[TaskListLoadResult] = None,
    project_root: Optional[Path] = None,
) -> List[str]:
    """
    Assess credibility of each claim based on VT-executed tool evidence.

    For each claim, checks if evidence_refs point to evidence entries with
    source_type of "test" or "tool" (VT-executed tool evidence).

    - If a claim has tool evidence references -> credibility = "high"
    - For non-code claims (task has no test paths) with existing deliverable -> credibility = "medium"
    - Otherwise -> credibility = "low_confidence"

    Args:
        claims: List of Claim objects to assess.
        evidence_list: List of evidence dicts from the evidence index.
        task_result: Optional TaskListLoadResult for task path lookups.
        project_root: Optional project root for file existence checks.

    Returns:
        List of warning messages for low_confidence claims.
    """
    # Build task_id -> Task mapping for path lookups
    task_map: Dict[str, Any] = {}
    if task_result:
        for task in task_result.tasks:
            task_map[task.task_id] = task

    # Build evidence_id -> source_type mapping
    ev_id_to_source_type: Dict[str, str] = {}
    for ev in evidence_list:
        ev_id = ev.get("evidence_id", "")
        source_type = ev.get("source_type", "")
        if ev_id:
            ev_id_to_source_type[ev_id] = source_type

    all_warnings: List[str] = []

    for claim in claims:
        has_tool_evidence = False

        # Check if evidence_refs point to evidence with source_type "test" or "tool"
        for ref in claim.evidence_refs:
            source_type = ev_id_to_source_type.get(ref, "")
            if source_type in ("test", "tool"):
                has_tool_evidence = True
                break

        if has_tool_evidence:
            claim.credibility = "high"
        else:
            # Check for medium credibility: non-code claim with existing deliverable
            is_medium = False
            task = task_map.get(claim.related_task)

            if task:
                # Determine if task is non-code by checking for test path indicators
                has_test_paths = bool(
                    task.related_acceptance_criteria
                    or task.definition_of_done
                )

                if not has_test_paths and project_root and claim.test_refs:
                    # Non-code task: check if deliverable file exists
                    deliverable_path = Path(claim.test_refs[0])
                    if not deliverable_path.is_absolute():
                        deliverable_path = project_root / deliverable_path
                    if deliverable_path.exists():
                        is_medium = True

            if is_medium:
                claim.credibility = "medium"
            else:
                claim.credibility = "low_confidence"
                warning = (
                    f"Claim {claim.claim_id} has no VT-executed tool evidence. "
                    f"Marked as low_confidence."
                )
                claim.credibility_warnings.append(warning)
                all_warnings.append(warning)

    return all_warnings
