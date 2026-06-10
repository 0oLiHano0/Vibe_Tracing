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
    claims_list: List[Any],
    evidence_index: Dict[str, Any],
    project_root: Optional[Path] = None,
) -> List[str]:
    """Assess credibility of each claim.

    In the new evidence chain design, claim credibility is determined by
    VT-executed tool results (pytest), not by evidence_refs. This function
    is kept for backward compatibility but returns an empty list.
    """
    return []
