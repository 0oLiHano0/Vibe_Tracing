"""Infrastructure package for Vibe Tracing.

This package contains infrastructure utilities organized by responsibility:
  - db/: Database operations (schema, loaders, queries, exports)
  - validation/: Schema validation and input checks
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

__all__ = [
    "OperationalLogger",
    "git_show",
    "git_diff_cached",
    "CoverageStatus",
    "ErrorCode",
    "load_hints",
    "resolve_hint",
    "ToolResolver",
]
