import sqlite3
from vibe_tracing.infra.db import (
    init_in_memory_db,
    load_tasks,
    load_claims,
    upsert_test_result,
    check_ac_coverage,
    check_requirement_coverage
)

def test_ac_coverage_with_passed_and_failed():
    conn = init_in_memory_db()
    # Load tasks
    load_tasks(conn, [
        {"task_id": "TASK-1", "priority": "must", "status": "done", "related_acceptance_criteria": ["AC-1"]}
    ])
    # Load claims with 2 tests: one passed, one failed
    load_claims(conn, [
        {"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_pass", "test_fail"]}
    ])
    upsert_test_result(conn, "test_pass", "passed", 0, "pytest", False)
    upsert_test_result(conn, "test_fail", "failed", 1, "pytest", False)
    
    res = check_ac_coverage(conn)
    print("AC Coverage Result (one pass, one fail):", res)
    conn.close()

def test_ac_coverage_with_passed_and_missing():
    conn = init_in_memory_db()
    load_tasks(conn, [
        {"task_id": "TASK-1", "priority": "must", "status": "done", "related_acceptance_criteria": ["AC-1"]}
    ])
    # Load claims with 2 tests: one passed, one missing (not run)
    load_claims(conn, [
        {"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_pass", "test_missing"]}
    ])
    upsert_test_result(conn, "test_pass", "passed", 0, "pytest", False)
    
    res = check_ac_coverage(conn)
    print("AC Coverage Result (one pass, one missing):", res)
    conn.close()

if __name__ == "__main__":
    test_ac_coverage_with_passed_and_failed()
    test_ac_coverage_with_passed_and_missing()
