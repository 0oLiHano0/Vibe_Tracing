"""Infrastructure package for Vibe Tracing.

This package contains infrastructure utilities organized by responsibility:
  - db/: Database operations (schema, loaders, queries, exports)
  - validation/: Schema validation and input checks
  - loader/: Data loading (PRD, tasks, claims)
  - report/: Report generation (traceability, dashboard, reflection)
  - logging/: Operational logging
  - git/: Git utilities
  - config/: Configuration (enums, hints)
  - tools/: Tool resolution
"""

# Re-export from subpackages for backward compatibility
from vibe_tracing.infra.logging import OperationalLogger
from vibe_tracing.infra.git import git_show, git_has_uncommitted_changes
from vibe_tracing.infra.config import CoverageStatus, ErrorCode, load_hints, resolve_hint
from vibe_tracing.infra.tools import ToolResolver
from vibe_tracing.infra.loader import (
    RawInputLoader,
    PrdParser,
    PrdParseResult,
    TaskLoader,
    TaskListLoadResult,
    ClaimLoader,
    ClaimListLoadResult,
)
from vibe_tracing.infra.report import (
    TraceabilityReportBuilder,
    DashboardRenderer,
    render_reflection_prompts,
)

__all__ = [
    "OperationalLogger",
    "git_show",
    "git_has_uncommitted_changes",
    "CoverageStatus",
    "ErrorCode",
    "load_hints",
    "resolve_hint",
    "ToolResolver",
    "RawInputLoader",
    "PrdParser",
    "PrdParseResult",
    "TaskLoader",
    "TaskListLoadResult",
    "ClaimLoader",
    "ClaimListLoadResult",
    "TraceabilityReportBuilder",
    "DashboardRenderer",
    "render_reflection_prompts",
]
