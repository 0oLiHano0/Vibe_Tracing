# Phase 2 Adversarial Coverage Hardening — DB Query Gap Report

This report outlines the findings from the adversarial analysis of the implementation source files in `src/vibe_tracing/infra/db/` and the test coverage in `tests/test_db_query_functions.py` and other test files.

---

## 1. Critical Database Query Aggregation Bugs (Logic Gaps)

During the review of `src/vibe_tracing/infra/db/queries.py`, three severe logic bugs were discovered in the SQLite queries. These bugs lead to incorrect coverage reports under mixed test execution outcomes.

### A. Mixed Test Outcome Coverage Bypass in `check_ac_coverage`
* **Vulnerability/Bug**: If a must-priority task has multiple tests associated with its claim, where one test passes and another test fails, `check_ac_coverage` incorrectly reports the acceptance criteria (AC) as `'covered'` (i.e., excludes it from the uncovered list).
* **Root Cause**: The SQLite query checks if any test failed using `SUM(tr.outcome = 'passed') = 0`. Since at least one test passed, the SUM is `1`, making the condition false. The query lacks an aggregation check for failed tests, such as `SUM(CASE WHEN tr.outcome = 'passed' THEN 1 ELSE 0 END) < COUNT(ctr.test_nodeid)` or `SUM(tr.outcome != 'passed') > 0`.
* **Impact**: Uncovered acceptance criteria with failing tests are falsely reported as covered.

### B. Missing Test Coverage Bypass in `check_ac_coverage`
* **Vulnerability/Bug**: If a must-priority task has multiple tests, where one test has passed and another test has not been executed (missing from `test_results`), `check_ac_coverage` can incorrectly report the AC as `'covered'`.
* **Root Cause**: The check `WHEN tr.nodeid IS NULL THEN 'test_not_run'` uses a non-aggregated column `tr.nodeid` inside the `CASE` statement while grouping by `ta.task_id, ta.ac_id`. SQLite arbitrarily selects a row within the group to evaluate non-aggregated columns. If it selects the row corresponding to the passed test, `tr.nodeid IS NULL` evaluates to false, and the query proceeds to report the AC as `'covered'`.
* **Impact**: Incomplete tests are silently ignored, violating the verification gate.

### C. Missing Test Coverage Bypass in `check_requirement_coverage`
* **Vulnerability/Bug**: Similar to the AC check, if a requirement has a task with multiple tests, and one test passes while another has not run, `check_requirement_coverage` incorrectly reports the requirement status as `'covered'`.
* **Root Cause**: The condition `WHEN tr.nodeid IS NULL THEN 'test_not_run'` evaluates a non-aggregated column before aggregation. If the database picks the row of the passed test, both `tr.nodeid IS NULL` and `SUM(tr.outcome != 'passed') > 0` evaluate to false, resulting in `'covered'`.
* **Impact**: Requirements with pending/missing tests are marked as covered.

---

## 2. Invalid Input & Type Handling Gaps

The database loaders in `src/vibe_tracing/infra/db/loaders.py` exhibit weak input validation, relying on database errors or generic runtime exceptions.

### A. Missing Iterable Type Validation in `load_prd`
* **Gap**: If a dictionary with `"requirements": <integer>` is passed, or if a requirement's `"acceptance_criteria"` is not a list/iterable, `load_prd` crashes with `TypeError: 'int' object is not iterable` instead of raising a clean, descriptive application-level validation error.
* **Impact**: Internal parsing code crashes directly on unexpected malformed PRD structures.

### B. Corrupted Cache File Handling in `load_initial_cache`
* **Gap**: If the cache files (`test_results.json` or `coverage_reports.json`) are present but corrupted (invalid JSON structure), `load_initial_cache` raises `json.JSONDecodeError` directly. It does not catch decode errors or log warnings/initialize with empty states gracefully.
* **Impact**: Application bootstrap crashes if cache files are corrupted.

---

## 3. Database Integrity & Connection Gaps

### A. raw `sqlite3.IntegrityError` on NOT NULL violations
* **Gap**: In `load_tasks`, `load_claims`, and other loaders, passing `None` or missing fields that map to `NOT NULL` SQLite columns (e.g. `status` or `priority` in `tasks`) triggers raw `sqlite3.IntegrityError` from SQLite.
* **Impact**: Database schema constraints are used as the primary validation layer, exposing database-specific exception types to caller code.

### B. Raw `sqlite3.OperationalError` on Uninitialized Database
* **Gap**: Invoking queries or loaders with a blank/uninitialized connection (e.g. one created via `sqlite3.connect(":memory:")` without calling `init_in_memory_db`) raises a database error (`sqlite3.OperationalError: no such table`).
* **Impact**: Missing pre-flight checks for schema existence before running query functions.

---

## 4. Security & Injection Assessment

### A. Path Traversal Risk in Cache Loader
* **Analysis**: `load_initial_cache` checks if a source file exists relative to the cache folder parent via `(cache_path.parent / source_path).is_file()`. While this is a read-only check and only inserts the path into the database, a malicious cache file containing `source_path` with directory traversal (`../../etc/passwd`) could bypass the existence check and pollute the `coverage_reports` table with arbitrary system paths.
* **Mitigation**: Sanitize or block path traversal sequences in `source_path`.

### B. SQL Injection Safety
* **Analysis**: Highly robust. All database inserts and updates use parameterized queries (`?` bindings), and queries are static strings. Dynamic string formatting or direct SQL concatenation was not found. Adversarial inputs containing quotes and SQL statements (e.g., `' OR '1'='1`) are safely handled as literal values.

---

## 5. Adversarial Tests Added

Nine new adversarial test cases have been appended to `tests/test_db_query_functions.py` under the `# ── Adversarial Tests ──` section:
1. `test_adversarial_ac_coverage_mixed_outcomes_bug`: Asserts `check_ac_coverage` detects failure when one test passes and one fails.
2. `test_adversarial_ac_coverage_missing_test_bug`: Asserts `check_ac_coverage` detects missing execution when one test passes and one has not run.
3. `test_adversarial_requirement_coverage_missing_test_bug`: Asserts `check_requirement_coverage` detects missing execution.
4. `test_adversarial_load_prd_invalid_requirements_type`: Asserts input type safety for `requirements` list in `load_prd`.
5. `test_adversarial_load_prd_invalid_ac_type`: Asserts input type safety for `acceptance_criteria` list in `load_prd`.
6. `test_adversarial_uninitialized_database_connection`: Asserts operational safety check (expects error) on uninitialized connections.
7. `test_adversarial_load_tasks_not_null_violation`: Asserts NOT NULL constraints raise expected errors.
8. `test_adversarial_load_initial_cache_invalid_json`: Asserts JSON parse error handling.
9. `test_adversarial_sql_injection_mitigated`: Asserts parameter binding prevents SQL injection attacks.
