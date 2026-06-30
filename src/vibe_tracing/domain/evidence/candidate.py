"""Evidence data models for tool execution.

ToolEvidenceCandidate: normalized evidence candidate parsed from a tool execution report.
ToolExecutionResult: structured return value from execute_from_claims().
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from vibe_tracing.infra.config.enums import CoverageStatus

_VALID_STATUSES: frozenset = frozenset(v.value for v in CoverageStatus)


@dataclass
class ToolEvidenceCandidate:
    """Normalized evidence candidate parsed from a tool execution report."""

    source_type: str  # "test" (for pytest) or "tool" (for others)
    source_path: str  # Path to the source report file or test nodeid
    covers: List[str]  # AC or REQ IDs that this evidence covers
    status: str  # CoverageStatus enum value
    tool_category: str = ""  # Tool category (e.g., "test", "lint", "type_check", "security", "coverage")
    command: str = ""
    exit_code: int = 0
    stderr: str = ""
    error_code: Optional[str] = None  # ErrorCode value (e.g., tool_execution_failed)
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                f"status must be a CoverageStatus value, got {self.status!r}"
            )


@dataclass
class ToolExecutionResult:
    """Structured return value from ToolExecutionEngine.execute_from_claims().

    Contains evidence candidates plus execution metadata, so callers can
    distinguish "no files found" from "precheck failed" from "success".
    """

    candidates: List[ToolEvidenceCandidate]
    skipped: bool = False          # True = precheck failed or no code files, not executed
    skip_reason: str = ""          # "precheck_failed" | "no_code_files" | "no_extensions"
    missing_tools: List[str] = field(default_factory=list)
