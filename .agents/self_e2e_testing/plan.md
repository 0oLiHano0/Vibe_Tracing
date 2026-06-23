# E2E Test Plan — Vibe Tracing DB Refactoring

## 1. Test Methodology
We will design a comprehensive, requirement-driven E2E test suite using the 4-tier methodology:
- **Tier 1: Feature Coverage** (≥ 5 tests per feature, total 35 tests)
- **Tier 2: Boundary & Corner Cases** (≥ 5 tests per feature, total 35 tests)
- **Tier 3: Cross-Feature Combinations** (pairwise coverage of major interactions, total 7 tests)
- **Tier 4: Real-World Application Scenarios** (≥ 5 realistic workload scenarios, total 5 tests)
Total tests: **82**.

## 2. Feature-to-Test Mapping

### Feature 1: Acceptance Criteria Coverage Check (`check_ac_coverage`)
- **Tier 1 (Feature Coverage):**
  1. `test_f1_t1_all_covered`: Verify that when all MUST ACs have tasks, claims, and passing tests, the status is "covered".
  2. `test_f1_t1_no_task`: Verify that when an AC has no task, the status is "no_task".
  3. `test_f1_t1_no_claim`: Verify that when an AC has a task but no claim, the status is "no_claim".
  4. `test_f1_t1_no_tests`: Verify that when an AC has a claim but no tests are declared, the status is "no_tests".
  5. `test_f1_t1_test_failed`: Verify that when an AC's tests failed, the status is "test_failed".
- **Tier 2 (Boundary & Corner Cases):**
  6. `test_f1_t2_non_must_ac`: Verify that SHOULD/COULD ACs behave correctly when not covered (should not affect MUST check or should report correct status).
  7. `test_f1_t2_empty_db`: Verify query on empty database tables.
  8. `test_f1_t2_partial_test_pass`: Verify that when multiple tests are declared for an AC, if at least one passes, it is "covered".
  9. `test_f1_t2_duplicate_links`: Verify duplicate mappings between tasks and ACs do not duplicate results.
  10. `test_f1_t2_null_values`: Verify handling of NULL/missing fields.

### Feature 2: Requirement Coverage Check (`check_requirement_coverage`)
- **Tier 1 (Feature Coverage):**
  1. `test_f2_t1_covered`: Verify requirement is "covered" when all associated tasks are "done".
  2. `test_f2_t1_partial`: Verify requirement is "partial" when some associated tasks are "in_progress" or "todo".
  3. `test_f2_t1_missing`: Verify requirement is "missing" when it has no associated tasks.
  4. `test_f2_t1_unclear`: Verify requirement is "unclear" when requirement priority is "unclear".
  5. `test_f2_t1_task_count`: Verify requirement task count returns the correct number of mapped tasks.
- **Tier 2 (Boundary & Corner Cases):**
  6. `test_f2_t2_multiple_tasks_done_todo`: Verify status is "partial" when one task is "done" and another is "todo".
  7. `test_f2_t2_no_requirements_in_db`: Verify behavior when no requirements exist in database.
  8. `test_f2_t2_unclear_task_status`: Verify status is "unclear" when one associated task has status "unclear".
  9. `test_f2_t2_large_task_count`: Verify behavior with a requirement mapped to a large number of tasks (e.g., 20 tasks).
  10. `test_f2_t2_null_priority`: Verify handling of NULL or unrecognized priorities.

### Feature 3: Claim Evidence Verification (`check_claim_evidence`)
- **Tier 1 (Feature Coverage):**
  1. `test_f3_t1_covered`: Verify claim is "covered" when all declared tests passed.
  2. `test_f3_t1_violated`: Verify claim is "violated" when any declared test failed.
  3. `test_f3_t1_unclear`: Verify claim is "unclear" when no tests are declared.
  4. `test_f3_t1_test_counts`: Verify correct test_count and passed_count in results.
  5. `test_f3_t1_no_claims`: Verify behavior when no claims exist in database.
- **Tier 2 (Boundary & Corner Cases):**
  6. `test_f3_t2_multiple_tests_mixed`: Verify status is "violated" when 2 tests pass and 1 test fails.
  7. `test_f3_t2_test_not_run`: Verify status is "violated" when a test is declared but has no result in `test_results` (not run).
  8. `test_f3_t2_duplicate_test_refs`: Verify duplicate test_refs for the same claim do not double count.
  9. `test_f3_t2_empty_nodeid`: Verify claim with empty test_nodeid string.
  10. `test_f3_t2_outcome_case_sensitivity`: Verify handling of outcome strings (e.g., "PASSED" vs "passed").

### Feature 4: Full Traceability Chain Query (`get_full_chain`)
- **Tier 1 (Feature Coverage):**
  1. `test_f4_t1_complete_chain`: Verify full chain returns correct mapping for a complete path (Req -> AC -> Task -> Claim -> Test -> Code -> Coverage).
  2. `test_f4_t1_broken_at_task`: Verify chain returns correct values when task is missing.
  3. `test_f4_t1_broken_at_claim`: Verify chain returns correct values when claim is missing.
  4. `test_f4_t1_broken_at_test`: Verify chain returns correct values when test is missing.
  5. `test_f4_t1_broken_at_coverage`: Verify chain returns correct values when coverage is missing.
- **Tier 2 (Boundary & Corner Cases):**
  6. `test_f4_t2_multiple_branches`: Verify correct cartesian product expansion when one Req has multiple ACs, tasks, and claims.
  7. `test_f4_t2_orphaned_entities`: Verify entities without parents (e.g., dangling claims, tasks without ACs) are not returned or handled properly depending on LEFT JOIN structure.
  8. `test_f4_t2_empty_tables`: Verify behavior when all tables are empty.
  9. `test_f4_t2_special_characters`: Verify handling of special characters in titles and nodeids.
  10. `test_f4_t2_duplicate_records`: Verify query output correctness when duplicate rows exist in intermediate tables.

### Feature 5: Ghost Code Detection (`check_ghost_code`)
- **Tier 1 (Feature Coverage):**
  1. `test_f5_t1_detect_ghost`: Verify that a staged file not referenced by any claim is flagged as ghost code.
  2. `test_f5_t1_no_ghost`: Verify that a staged file referenced by a claim is not flagged.
  3. `test_f5_t1_empty_staged`: Verify that no ghost code is returned when staged_files is empty.
  4. `test_f5_t1_default_exclusion_docs`: Verify that `docs/` files are excluded by default.
  5. `test_f5_t1_default_exclusion_tests`: Verify that `tests/` files are excluded by default.
- **Tier 2 (Boundary & Corner Cases):**
  6. `test_f5_t2_custom_exclusions`: Verify custom exclusions passed via config dict.
  7. `test_f5_t2_multiple_claims_ref`: Verify file is not ghost code if referenced by multiple claims.
  8. `test_f5_t2_regex_exclusion`: Verify wildcard or suffix exclusions (e.g., `.json`).
  9. `test_f5_t2_slash_handling`: Verify handling of trailing/leading slashes in custom exclusions.
  10. `test_f5_t2_staged_but_ignored`: Verify staged files that match custom exclusion prefixes are ignored.

### Feature 6: Dangling Claims Detection (`check_dangling_claims`)
- **Tier 1 (Feature Coverage):**
  1. `test_f6_t1_detect_dangling`: Verify claim with related_task pointing to non-existent task is flagged.
  2. `test_f6_t1_no_dangling`: Verify claim with related_task pointing to existing task is not flagged.
  3. `test_f6_t1_empty_claims`: Verify no dangling claims returned on empty claims table.
  4. `test_f6_t1_multiple_dangling`: Verify multiple dangling claims are all detected.
  5. `test_f6_t1_dangling_details`: Verify returned dict contains `claim_id` and `related_task`.
- **Tier 2 (Boundary & Corner Cases):**
  6. `test_f6_t2_whitespace_task_id`: Verify task_id with leading/trailing whitespace.
  7. `test_f6_t2_case_sensitivity`: Verify case sensitivity of task ID match.
  8. `test_f6_t2_invalid_format`: Verify claim with improperly formatted related_task.
  9. `test_f6_t2_orphaned_tasks`: Verify that tasks without claims do not affect this check.
  10. `test_f6_t2_null_task_id`: Verify claim with null or empty task ID.

### Feature 7: Test Dead Links Detection (`check_test_dead_links`)
- **Tier 1 (Feature Coverage):**
  1. `test_f7_t1_detect_missing`: Verify test referenced by claim but not in `test_results` is flagged.
  2. `test_f7_t1_detect_failed`: Verify test referenced by claim but failing is flagged.
  3. `test_f7_t1_no_dead_links`: Verify test referenced by claim and passing is not flagged.
  4. `test_f7_t1_empty_refs`: Verify behavior when claim has no test_refs.
  5. `test_f7_t1_details`: Verify returned dict contains `claim_id` and `test_nodeid`.
- **Tier 2 (Boundary & Corner Cases):**
  6. `test_f7_t2_skipped_test`: Verify status of skipped tests (should they be flagged as dead links? Usually yes, if they didn't pass).
  7. `test_f7_t2_partially_failed_claim`: Verify claim with multiple tests where one passes and one fails flags only the failed one.
  8. `test_f7_t2_special_chars_nodeid`: Verify nodeid with special chars (e.g. `[param]`) is matched correctly.
  9. `test_f7_t2_duplicate_results`: Verify query handles duplicate results for the same test nodeid gracefully.
  10. `test_f7_t2_cache_carried_over`: Verify carried_over test results are matched correctly.

---

### Tier 3: Cross-Feature Combinations (7 tests)
1. `test_t3_req_task_claim_interaction`: Test interaction where a Requirement has a Task, which has a Claim, but the Claim's tests fail. Check `check_requirement_coverage` (partial/covered?), `check_claim_evidence` (violated), and `check_ac_coverage` (test_failed).
2. `test_t3_ghost_code_and_claim_evidence`: A file is staged and covered by a claim, but that claim's tests fail. Ensure `check_ghost_code` is clean, but `check_claim_evidence` reports `violated`.
3. `test_t3_dangling_claim_and_ac_coverage`: A claim is dangling. Ensure `check_dangling_claims` flags it, and `check_ac_coverage` reports `no_claim_for_task` or correct state since the task doesn't exist.
4. `test_t3_test_dead_link_and_ac_coverage`: A test is a dead link (failed). Check that both `check_test_dead_links` flags it and `check_ac_coverage` flags the AC as `test_failed`.
5. `test_t3_coverage_violation_in_full_chain`: A test passes, but the code has a coverage violation. Check that `get_full_chain` returns the coverage percentage, and `check_coverage_violations` catches the violation.
6. `test_t3_task_status_propagation`: Test how task status changes ("todo" -> "in_progress" -> "done") propagate simultaneously to requirement coverage (`check_requirement_coverage`) and AC coverage (`check_ac_coverage`).
7. `test_t3_carried_over_purging_cascade`: Purging stale cache for a file cascades to clean up test results and coverage, affecting `check_claim_evidence` and `check_ac_coverage` simultaneously.

---

### Tier 4: Real-World Application Scenarios (5 tests)
1. `test_t4_scenario_happy_path`: E2E simulation of a fully completed requirement. PRD loaded, tasks loaded, claims loaded, tests run and passed, coverage matches. Verify all checks are clean and `get_full_chain` shows complete path.
2. `test_t4_scenario_in_progress_milestone`: Simulation of a milestone in progress. Some tasks are done, some are todo. Verify `check_requirement_coverage` is partial, some ACs are `no_claim` or `no_tests`, and merge gate would block.
3. `test_t4_scenario_refactoring_cleanup`: Simulation of code cleanup. Staged files include new code, old tests are purged. Stale test results are deleted using `purge_stale_cache`. Verify that only active tests are matched, no ghost code exists, and no dead links remain.
4. `test_t4_scenario_malformed_input_recovery`: Loader recovery scenario where some input lists contain invalid formats, duplicates, or empty lists, verifying the DB layer filters or handles them without crashing.
5. `test_t4_scenario_complex_multimodule_chain`: A large-scale project verification with multiple requirements, cross-referenced tasks, shared claims, and mixed test outcomes. Verify that all 7 check functions return the mathematically correct sets of records.
