# Implementation Context

## Project Scope
Refactoring `src/vibe_tracing/infra/db.py` into a package `src/vibe_tracing/infra/db/`.
We need to implement:
- Package structure: `__init__.py`, `schema.py`, `loaders.py`, `queries.py`, `exports.py`.
- Requirements & Acceptance Criteria tables.
- `load_prd(conn, prd)` in loaders.
- `check_requirement_coverage(conn)`, `check_claim_evidence(conn)`, `get_full_chain(conn)` in queries.
- Refactored `check_ac_coverage(conn)` starting LEFT JOIN from `acceptance_criteria`.

## Current State
- Codebase: `/Users/lihan/Project/Vibe_Tracing`
- Scope document: `/Users/lihan/Project/Vibe_Tracing/.agents/orchestrator/PROJECT.md`
- Designing query behavior for check_requirement_coverage, check_claim_evidence, get_full_chain, and refactored check_ac_coverage.
- Ready to dispatch Worker to implement subpackage and tests.
