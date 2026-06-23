"""Domain package for Vibe Tracing.

This package contains the core business logic organized by responsibility:
  - evidence/: Evidence building and merging
  - gate/: Gate evaluation engine and staleness tracking
  - compliance/: Architecture compliance checking
  - risk/: Risk advisory
  - governance/: Governance (ghost code reconciliation)
  - context.py: UnifiedContext domain model

Note: loader/ and report/ have been moved to infra/ as they involve I/O operations.
"""

# Re-export from subpackages for backward compatibility
from vibe_tracing.domain.context import UnifiedContext

# Evidence
from vibe_tracing.domain.evidence import EvidenceBuilder, EvidenceMergeResult

# Gate
from vibe_tracing.domain.gate import MergeGateEngine, mark_staleness

# Compliance
from vibe_tracing.domain.compliance import ArchitectureComplianceChecker, validate_prd_architecture_mapping

# Risk
from vibe_tracing.domain.risk import RiskAdvisor

# Governance
from vibe_tracing.domain.governance import GhostCodeReconciler

__all__ = [
    "UnifiedContext",
    "EvidenceBuilder",
    "EvidenceMergeResult",
    "MergeGateEngine",
    "mark_staleness",
    "ArchitectureComplianceChecker",
    "validate_prd_architecture_mapping",
    "RiskAdvisor",
    "GhostCodeReconciler",
]
