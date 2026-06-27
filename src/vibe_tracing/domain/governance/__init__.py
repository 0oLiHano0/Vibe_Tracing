"""Governance package for Vibe Tracing."""

from vibe_tracing.domain.governance.ghost_code import GhostCodeReconciler
from vibe_tracing.domain.governance.change_proposal import ArchitectureChangeProposalEngine

__all__ = ["GhostCodeReconciler", "ArchitectureChangeProposalEngine"]
