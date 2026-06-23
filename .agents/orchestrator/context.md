# Context — Vibe Tracing DB Refactoring

## Project Workspace
- Path: `/Users/lihan/Project/Vibe_Tracing`

## Core Requirements (Summary)
- **R1: Split DB module**: Split `db.py` to `db/` subpackage. Export all functions through `__init__.py` for backward compatibility.
- **R2: New tables & loaders**:
  - Add tables `requirements` and `acceptance_criteria` to SQLite database.
  - Implement `load_prd(conn, prd)` to map and write `PrdParseResult` requirements/ACs.
- **R3: SQL Query Layer**:
  - Implement `check_requirement_coverage(conn)`.
  - Implement `check_claim_evidence(conn)`.
  - Implement `get_full_chain(conn)`.
  - Refactor `check_ac_coverage(conn)` to use `acceptance_criteria` as starting table for LEFT JOIN.

## Existing Test Suites
- Running command: `pytest tests/` (all must pass).
- Special test target: `tests/test_db_query_functions.py` needs to be created.
