"""Unified context domain model for vt analyze pipeline."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class UnifiedContext:
    """Single source of truth for all parsed vt analyze inputs.

    Holds the result of one-pass loading so downstream components
    never re-read or re-parse files from disk.
    """

    config: Dict[str, Any]
    prd: Any  # PrdParseResult
    constraints: Optional[Dict[str, Any]] = None
    task_result: Optional[Any] = None  # TaskListLoadResult
    claims_list: List[Any] = field(default_factory=list)
    tool_evidence: List[Any] = field(default_factory=list)
    manifest: Optional[Any] = None  # InputManifest
    config_prefix: str = "VT"
