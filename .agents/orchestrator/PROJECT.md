# Project: Vibe Tracing DB Refactoring & Query Extensions

## Architecture
The database layer (`vibe_tracing.infra.db`) is a central hub for tracing and verification data (tasks, claims, test results, coverage reports). The project refactors this layer from a single file to a structured subpackage (`db/`), and adds PRD requirement and acceptance criteria tables/loaders.

```
                  ┌──────────────────────┐
                  │      prd_parser      │
                  └──────────┬───────────┘
                             │ (PrdParseResult)
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │                   vibe_tracing.infra.db                │
  │                                                        │
  │  ┌───────────────┐ ┌───────────────┐ ┌──────────────┐  │
  │  │   schema.py   │ │  loaders.py   │ │  queries.py  │  │
  │  └───────────────┘ └───────────────┘ └──────────────┘  │
  │  ┌───────────────┐ ┌───────────────┐                   │
  │  │  exports.py   │ │  __init__.py  │                   │
  │  └───────────────┘ └───────────────┘                   │
  └────────────────────────────────────────────────────────┘
```

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | E2E Testing Track | Design and implement opaque-box E2E test cases for requirements & AC verification. | none | IN_PROGRESS (ID: f888abe6-d396-4e81-adb2-73403054a57a) |
| 2 | Implementation Track | Decompose and execute DB subpackage split, loaders, and queries. | M1 | IN_PROGRESS (ID: a2bf854d-97d6-4e92-bd46-e5cad98ad45a) |

## Interface Contracts
### `vibe_tracing.infra.db` exports
- `init_in_memory_db() -> sqlite3.Connection`
- `load_tasks(conn, tasks)`, `load_claims(conn, claims)`, `load_staged_files(conn, files)`, `load_initial_cache(conn, cache_dir)`, `load_prd(conn, prd)`
- `check_ac_coverage(conn)`, `check_coverage_violations(conn)`, `check_ghost_code(conn)`, `check_dangling_claims(conn)`, `check_test_dead_links(conn)`, `check_active_task_coverage(conn)`
- `check_requirement_coverage(conn)`, `check_claim_evidence(conn)`, `get_full_chain(conn)`
- `upsert_test_result(conn, ...)` , `upsert_coverage_report(conn, ...)` , `purge_stale_cache(conn, ...)` , `persist_evidences(conn, ...)`

## Code Layout
- `src/vibe_tracing/infra/db/`
  - `__init__.py`: Package initialization & export exports
  - `schema.py`: Database DDL & table schema definitions
  - `loaders.py`: Bulk loaders for tasks, claims, staging files, cache, and PRD
  - `queries.py`: SQL relational check & query functions
  - `exports.py`: UPSERT logic, cache purging, and file exports
- `tests/test_db_query_functions.py`: Unit tests for the new query functions & refactored queries
