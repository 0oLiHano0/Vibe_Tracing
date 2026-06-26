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
