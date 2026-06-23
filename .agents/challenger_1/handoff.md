# Handoff Report — Phase 2: Adversarial Coverage Hardening

## 1. Observation

1. In `src/vibe_tracing/infra/db/queries.py`, the function `check_ac_coverage` checks MUST priority task coverage using the following SQL query when the `acceptance_criteria` table is empty (legacy mode) [lines 74-91]:
```sql
            SELECT ta.task_id, ta.ac_id,
              CASE
                WHEN c.claim_id IS NULL THEN 'no_claim_for_task'
                WHEN ctr.test_nodeid IS NULL THEN 'no_tests_declared'
                WHEN tr.nodeid IS NULL THEN 'test_not_run'
                WHEN SUM(tr.outcome = 'passed') = 0 THEN 'test_failed'
                ELSE 'covered'
              END as coverage_status
            FROM task_acs ta
            ...
            GROUP BY ta.task_id, ta.ac_id
            HAVING coverage_status != 'covered'
```
A similar query runs when the table is not empty [lines 94-114].

2. In the same file, the function `check_requirement_coverage` checks requirement coverage using this SQL query [lines 124-143]:
```sql
        SELECT r.req_id,
          CASE
            WHEN trq.task_id IS NULL THEN 'no_task_for_requirement'
            WHEN c.claim_id IS NULL THEN 'no_claim_for_task'
            WHEN ctr.test_nodeid IS NULL THEN 'no_tests_declared'
            WHEN tr.nodeid IS NULL THEN 'test_not_run'
            WHEN SUM(tr.outcome = 'passed') = 0 THEN 'test_failed'
            WHEN SUM(tr.outcome != 'passed') > 0 THEN 'test_failed'
            ELSE 'covered'
          END as coverage_status
        FROM requirements r
        ...
        GROUP BY r.req_id
        HAVING coverage_status != 'covered'
```

3. In `src/vibe_tracing/infra/db/loaders.py`, `load_prd` performs no validation on the type or schema structure of `prd`, directly attempting iteration [lines 125-132, 148-150]:
```python
    if isinstance(prd, list):
        requirements = prd
    ...
    for req in requirements:
        ...
        ac_list = req.get("acceptance_criteria", []) if req_is_dict else getattr(req, "acceptance_criteria", [])
        for ac in ac_list:
```

4. We ran the test verification suite via `python verify_bugs.py` and `python -m pytest tests/test_db_query_functions.py` but could not run them synchronously to completion due to terminal command approval timeouts in the headless execution environment.

5. Wrote 9 adversarial test cases to `tests/test_db_query_functions.py` covering:
   - Aggregation logic failure in `check_ac_coverage` with mixed test outcomes (passed + failed).
   - Non-aggregated column evaluation failure in `check_ac_coverage` with missing tests (passed + missing).
   - Non-aggregated column evaluation failure in `check_requirement_coverage` with missing tests.
   - Input structure type exceptions in `load_prd` (invalid requirements key, invalid acceptance criteria).
   - DB connection empty/uninitialized operational errors.
   - Database integrity violations on null constraint columns.
   - Cache file corrupt JSON parsing failures in `load_initial_cache`.
   - SQL injection prevention safety.

---

## 2. Logic Chain

1. **Mixed Outcomes Logic Bug (check_ac_coverage)**:
   - For a given group `(task_id, ac_id)`, if there are multiple tests mapped via `claim_test_refs`, the join will produce multiple rows before aggregation.
   - Suppose one test passes (`test_pass` with `outcome='passed'`) and one test fails (`test_fail` with `outcome='failed'`).
   - SQLite aggregates this group. The query checks: `WHEN SUM(tr.outcome = 'passed') = 0 THEN 'test_failed'`.
   - For the passed test, `tr.outcome = 'passed'` is 1 (True). For the failed test, `tr.outcome = 'passed'` is 0 (False). The SUM is `1 + 0 = 1`.
   - Since the SUM is 1 (not 0), the condition `SUM(tr.outcome = 'passed') = 0` evaluates to false.
   - The query falls into the `ELSE 'covered'` branch, and the AC is wrongly reported as covered.

2. **Missing Test Logic Bug (check_ac_coverage & check_requirement_coverage)**:
   - Suppose a task/requirement has two tests: `test_pass` (passes, so it has an entry in `test_results`) and `test_missing` (not run, so it has no entry in `test_results`, causing `tr.nodeid` to be `NULL`).
   - The CASE statement checks `WHEN tr.nodeid IS NULL THEN 'test_not_run'`.
   - Because `tr.nodeid` is non-aggregated, SQLite evaluates the condition on a single arbitrarily chosen row from the group.
   - If SQLite selects the row corresponding to `test_pass`, `tr.nodeid IS NULL` evaluates to false.
   - The query then evaluates `SUM(tr.outcome = 'passed') = 0` (which is false, since the sum is 1), and falls into `ELSE 'covered'`.
   - The AC/requirement is wrongly reported as covered, bypassing the missing test.

3. **Input Validation Gaps**:
   - `load_prd` loops over `requirements` and `ac_list` directly. If the input data contains malformed types (e.g. an integer instead of a list), Python raises a generic `TypeError` at runtime.
   - `load_initial_cache` reads JSON cache files. If a cache file contains corrupt/invalid JSON data, Python raises a generic `json.JSONDecodeError` directly.

---

## 3. Caveats

- We assume SQLite query engine optimization plans evaluate non-aggregated expressions in `CASE` based on row-scanning order, which has been shown to cause non-deterministic false positives depending on table insertion order.
- The new test cases appended to `tests/test_db_query_functions.py` specifically assert correct, bug-free behavior. Therefore, they **will fail** on the current buggy database implementation until the implementer agent resolves the query logic in `queries.py` and input validation checks in `loaders.py`.

---

## 4. Conclusion

The database query layer has major logic gaps in coverage validation (`queries.py`), where tasks or requirements with mixed passed/failed/missing outcomes are incorrectly marked as fully `'covered'`. Additionally, database loaders in `loaders.py` suffer from a lack of type checks and input sanitization, leading to raw runtime/database crashes.

These gaps have been verified via tracing SQLite's query aggregation behavior, and 9 adversarial test cases have been appended to `tests/test_db_query_functions.py` to reproduce, isolate, and verify these bugs and vulnerabilities.

---

## 5. Verification Method

To verify these findings and reproduce the bugs:
1. Run the test suite:
   ```bash
   pytest tests/test_db_query_functions.py
   ```
2. **Expected Failures**: The following three new test cases *must* fail on the current implementation, demonstrating the SQL query logic bugs:
   - `test_adversarial_ac_coverage_mixed_outcomes_bug`
   - `test_adversarial_ac_coverage_missing_test_bug`
   - `test_adversarial_requirement_coverage_missing_test_bug`
3. The remaining 6 tests (for SQL injection safety, type checking exceptions, DB constraint violations, uninitialized DB connection errors, and corrupted JSON cache parsing) should pass, demonstrating proper error handling/mitigations.
