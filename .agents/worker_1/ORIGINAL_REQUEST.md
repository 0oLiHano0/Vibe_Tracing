## 2026-06-22T18:36:53Z

You are tasked with implementing the E2E test suite in the Vibe Tracing workspace.
Your goal is to write `tests/test_db_query_functions.py` containing exactly 82 tests.
The test cases must be designed following the 4-tier model for 7 features (F1 to F7):
- F1: Acceptance Criteria Coverage Check (`check_ac_coverage`)
- F2: Requirement Coverage Check (`check_requirement_coverage`)
- F3: Claim Evidence Verification Check (`check_claim_evidence`)
- F4: Full Traceability Chain Query (`get_full_chain`)
- F5: Ghost Code Check (`check_ghost_code`)
- F6: Dangling Claims Check (`check_dangling_claims`)
- F7: Test Dead Links Check (`check_test_dead_links`)

Test Count breakdown:
- Tier 1 Feature Coverage: 5 tests per feature (5 * 7 = 35 tests)
- Tier 2 Boundary & Corner Cases: 5 tests per feature (5 * 7 = 35 tests)
- Tier 3 Cross-Feature Combinations: 7 tests
- Tier 4 Real-World Application Scenarios: 5 tests
Total = 82 tests.

IMPLEMENTATION DETAIL (Fallback Mechanism):
Because the implementation track runs after the E2E testing track, the new tables (`requirements`, `acceptance_criteria`, `task_requirements`) and functions (`load_prd`, `check_requirement_coverage`, `check_claim_evidence`, `get_full_chain`) may not yet be defined in `src/vibe_tracing/infra/db.py`.
To ensure the test suite is collected and runs successfully:
1. Attempt to import `load_prd`, `check_requirement_coverage`, `check_claim_evidence`, `get_full_chain` from `vibe_tracing.infra.db`.
2. Define a boolean flag `USING_REAL_IMPL`. If any of the imports fail, set `USING_REAL_IMPL = False`.
3. If `USING_REAL_IMPL` is False, write helper fallback implementations for these functions and a wrapped `init_in_memory_db()` that intercepts the sqlite Connection to execute:
   - `CREATE TABLE IF NOT EXISTS requirements (req_id TEXT PRIMARY KEY, title TEXT, priority TEXT, category TEXT)`
   - `CREATE TABLE IF NOT EXISTS acceptance_criteria (ac_id TEXT PRIMARY KEY, req_id TEXT, title TEXT, is_testing_required INTEGER)`
   - `CREATE TABLE IF NOT EXISTS task_requirements (task_id TEXT, req_id TEXT, PRIMARY KEY(task_id, req_id))`
   And define a fallback `load_tasks` that also inserts task-requirement associations.
4. Implement all 82 test cases in `tests/test_db_query_functions.py` so that they use the imported functions if `USING_REAL_IMPL` is True, or the fallbacks if False.
5. In this way, when the implementation track runs later and refactors the DB module, these same tests will automatically test the real implementation.
