"""Unified context domain model for vt analyze pipeline."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

if TYPE_CHECKING:
    from vibe_tracing.infra.loader.claim_loader import Claim
    from vibe_tracing.infra.loader.prd_parser import PrdParseResult
    from vibe_tracing.infra.loader.raw_input import RawInputManifest
    from vibe_tracing.infra.loader.task_loader import TaskListLoadResult
    from vibe_tracing.infra.tools.executor import ToolEvidenceCandidate


@dataclass
class UnifiedContext:
    """Single source of truth for all parsed vt analyze inputs.

    Holds the result of one-pass loading so downstream components
    never re-read or re-parse files from disk.

    Note: tool_evidence is NOT stored here. It's a pipeline-local variable
    returned by _execute_tools() and passed directly to EvidenceBuilder.merge().
    """

    config: Dict[str, Any]
    prd: "PrdParseResult"
    constraints: Optional[Dict[str, Any]] = None
    task_result: Optional["TaskListLoadResult"] = None
    claims_list: List["Claim"] = field(default_factory=list)
    manifest: Optional["RawInputManifest"] = None
    human_decisions: Optional[dict] = None
    config_prefix: str = "VT"
    is_draft: bool = False
    governance_whitelist: Set[str] = field(default_factory=set)
    governance_boundary: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.config, dict):
            raise TypeError(f"config must be a dict, got {type(self.config).__name__}")
        if not hasattr(self.prd, "requirements"):
            raise TypeError(
                f"prd must have a 'requirements' attribute (PrdParseResult), "
                f"got {type(self.prd).__name__}"
            )
