"""Staleness tracking for incremental analysis.

Pure functions that mark gaps and risks from unchanged items as ``stale``
so that gate evaluation can skip them while the report still includes
them for full visibility.
"""

from typing import Dict, List, Optional, Set, Tuple


def mark_staleness(
    merged_gaps: List[Dict],
    risks: List[Dict],
    staged_files: Optional[Set[str]],
    claims_list: list,
    task_list_data: Optional[list] = None,
) -> Tuple[List[Dict], List[Dict]]:
    """Mark gaps and risks from unchanged items as stale.

    This is a pure function: it does NOT modify the input lists. Instead,
    it returns new lists with ``stale=True`` added to items whose source
    files are not in ``staged_files``.

    Args:
        merged_gaps: Gap dicts from analysis (requirement, AC, claim gaps).
        risks: Risk dicts from RiskAdvisor.
        staged_files: Set of staged file paths. If None or empty, no items
            are marked stale (full analysis mode).
        claims_list: List of Claim objects for mapping claim_id -> code_refs.
        task_list_data: Optional list of task dicts for mapping task_id -> requirements/ACs.

    Returns:
        Tuple of (new_gaps, new_risks) with stale markers added.
    """
    # If no staged files, nothing can be stale (full analysis mode)
    if not staged_files:
        return list(merged_gaps), list(risks)

    # Build sets of affected item IDs based on staged file paths
    affected_claims: Set[str] = set()
    affected_reqs: Set[str] = set()
    affected_acs: Set[str] = set()

    # Map claims to staged files
    for claim in claims_list:
        claim_id = getattr(claim, "claim_id", None)
        if not claim_id:
            continue
        code_refs = getattr(claim, "code_refs", []) or []
        test_refs = getattr(claim, "test_refs", []) or []
        for ref in code_refs + test_refs:
            path = ref.split("#")[0].split("::")[0]
            if path in staged_files:
                affected_claims.add(claim_id)
                break

    # Map affected claims -> tasks -> requirements / ACs
    if affected_claims and task_list_data:
        affected_task_ids: Set[str] = set()
        for claim in claims_list:
            if getattr(claim, "claim_id", None) in affected_claims:
                task_id = getattr(claim, "related_task", None)
                if task_id:
                    affected_task_ids.add(task_id)

        for task in task_list_data:
            task_id = task.get("task_id")
            if task_id in affected_task_ids:
                for req_id in task.get("related_requirements", []):
                    affected_reqs.add(req_id)
                for ac_id in task.get("related_acceptance_criteria", []):
                    affected_acs.add(ac_id)

    # Mark stale gaps (create new list, don't modify originals)
    new_gaps = []
    for gap in merged_gaps:
        new_gap = dict(gap)  # shallow copy
        item_type = gap.get("item_type")
        item_id = gap.get("item_id")
        if item_type == "claim" and item_id not in affected_claims:
            new_gap["stale"] = True
        elif item_type == "requirement" and item_id not in affected_reqs:
            new_gap["stale"] = True
        elif item_type == "ac" and item_id not in affected_acs:
            new_gap["stale"] = True
        new_gaps.append(new_gap)

    # Mark stale risks (create new list, don't modify originals)
    new_risks = []
    for risk in risks:
        new_risk = dict(risk)  # shallow copy
        claim_id = risk.get("claim_id")
        if claim_id is not None and claim_id not in affected_claims:
            new_risk["stale"] = True
        new_risks.append(new_risk)

    return new_gaps, new_risks
