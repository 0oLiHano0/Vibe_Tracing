# Project Plan — Vibe Tracing DB Refactoring & Query Extensions

## Objectives
1. Split `src/vibe_tracing/infra/db.py` into a package `src/vibe_tracing/infra/db/` with `__init__.py`, `schema.py`, `loaders.py`, `queries.py`, and `exports.py`.
2. Keep 100% backward compatibility for imports from `vibe_tracing.infra.db`.
3. Add `requirements` and `acceptance_criteria` tables to the database schema in `schema.py`.
4. Implement `load_prd(conn, prd)` in `loaders.py` to load requirements and ACs.
5. Implement new queries in `queries.py`: `check_requirement_coverage`, `check_claim_evidence`, `get_full_chain`.
6. Refactor `check_ac_coverage` in `queries.py` to start the LEFT JOIN from `acceptance_criteria`.
7. Add comprehensive unit tests in `tests/test_db_query_functions.py` to verify the new and refactored queries.
8. Ensure all existing tests in `pytest tests/` pass.

## Milestones
| # | Milestone Name | Scope | Dependencies | Status |
|---|---|---|---|---|
| 1 | E2E Testing Track | Design and write comprehensive E2E tests for the new query features and refactoring. | None | PLANNED |
| 2 | Code Exploration & Refactoring Plan | Deep-dive research of code structure, import verification, and draft implementation. | None | PLANNED |
| 3 | Package Split & Schema Update | Perform the package split, define new tables, and implement the loaders. | M2 | PLANNED |
| 4 | Query Layer Implementation & Refactoring | Implement new and refactored query functions. | M3 | PLANNED |
| 5 | E2E Verification & Hardening | Run all tests (unit and E2E) and perform forensic audit verification. | M1, M4 | PLANNED |

## Interface Contracts
- `vibe_tracing.infra.db` imports remain unchanged and export:
  - `init_in_memory_db`, `load_tasks`, `load_claims`, `load_staged_files`, `load_initial_cache`, `load_prd`
  - `check_ac_coverage`, `check_coverage_violations`, `check_ghost_code`, `check_dangling_claims`, `check_test_dead_links`, `check_active_task_coverage`
  - `check_requirement_coverage`, `check_claim_evidence`, `get_full_chain`
  - `upsert_test_result`, `upsert_coverage_report`, `purge_stale_cache`, `persist_evidences`

## Code Layout
- `src/vibe_tracing/infra/db/`
  - `__init__.py`
  - `schema.py`
  - `loaders.py`
  - `queries.py`
  - `exports.py`
- `tests/test_db_query_functions.py`
