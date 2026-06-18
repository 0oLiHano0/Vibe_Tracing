"""Unified context domain model for vt analyze pipeline."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from vibe_tracing.domain.claim_loader import Claim
    from vibe_tracing.domain.prd_parser import PrdParseResult
    from vibe_tracing.domain.raw_input_loader import RawInputManifest
    from vibe_tracing.domain.task_loader import TaskListLoadResult
    from vibe_tracing.domain.tool_evidence_adapter import ToolEvidenceCandidate


@dataclass
class UnifiedContext:
    """Single source of truth for all parsed vt analyze inputs.

    Holds the result of one-pass loading so downstream components
    never re-read or re-parse files from disk.
    """

    config: Dict[str, Any]
    prd: "PrdParseResult"
    constraints: Optional[Dict[str, Any]] = None
    task_result: Optional["TaskListLoadResult"] = None
    claims_list: List["Claim"] = field(default_factory=list)
    tool_evidence: List["ToolEvidenceCandidate"] = field(default_factory=list)
    manifest: Optional["RawInputManifest"] = None
    human_decisions: Optional[dict] = None
    config_prefix: str = "VT"

    def __post_init__(self) -> None:
        if not isinstance(self.config, dict):
            raise TypeError(f"config must be a dict, got {type(self.config).__name__}")
        if not hasattr(self.prd, "requirements"):
            raise TypeError(
                f"prd must have a 'requirements' attribute (PrdParseResult), "
                f"got {type(self.prd).__name__}"
            )
