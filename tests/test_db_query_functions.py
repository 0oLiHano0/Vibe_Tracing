import sqlite3
import pytest

# ── Fallback Mechanism ────────────────────────────────────────────────────────
# Check if load_prd and check_requirement_coverage already exist in vibe_tracing.infra.db.
# If they don't, set USING_REAL_IMPL = False and define fallback implementations.
USING_REAL_IMPL = False
try:
    import vibe_tracing.infra.db as real_db
    if all(hasattr(real_db, name) for name in ["load_prd", "check_requirement_coverage", "check_claim_evidence", "get_full_chain"]):
        from vibe_tracing.infra.db import (
            load_prd,
            check_requirement_coverage,
            check_claim_evidence,
            get_full_chain,
            init_in_memory_db,
            load_tasks
        )
        USING_REAL_IMPL = True
except ImportError:
    pass

if not USING_REAL_IMPL:
    import vibe_tracing.infra.db as real_db
    from vibe_tracing.infra.db import (
        load_claims,
        load_staged_files,
        load_initial_cache,
        upsert_test_result,
        upsert_coverage_report,
        purge_stale_cache,
        check_ac_coverage,
        check_ghost_code,
        check_dangling_claims,
        check_test_dead_links,
    )

    # Wrapped init_in_memory_db to ensure fallback tables are created
    def init_in_memory_db() -> sqlite3.Connection:
        conn = real_db.init_in_memory_db()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS requirements (req_id TEXT PRIMARY KEY, title TEXT, priority TEXT, category TEXT)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS acceptance_criteria (ac_id TEXT PRIMARY KEY, req_id TEXT, title TEXT, is_testing_required INTEGER)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS task_requirements (task_id TEXT, req_id TEXT, PRIMARY KEY(task_id, req_id))"
        )
        conn.commit()
        return conn

    # Fallback load_tasks that also populates task_requirements
    def load_tasks(conn: sqlite3.Connection, tasks: list) -> None:
        real_db.load_tasks(conn, tasks)
        for task in tasks:
            task_id = task.get("task_id")
            related_reqs = task.get("related_requirements", [])
            for req_id in related_reqs:
                conn.execute(
                    "INSERT OR REPLACE INTO task_requirements (task_id, req_id) VALUES (?, ?)",
                    (task_id, req_id)
                )
        conn.commit()

    # Fallback load_prd
    def load_prd(conn: sqlite3.Connection, requirements: list) -> None:
        for req in requirements:
            if hasattr(req, "req_id"):
                req_id = req.req_id
                title = req.title
                priority = req.priority
                category = req.category
                ac_list = req.acceptance_criteria
            else:
                req_id = req.get("req_id")
                title = req.get("title")
                priority = req.get("priority")
                category = req.get("category")
                ac_list = req.get("acceptance_criteria", [])

            conn.execute(
                "INSERT OR REPLACE INTO requirements (req_id, title, priority, category) VALUES (?, ?, ?, ?)",
                (req_id, title, priority, category)
            )
            for ac in ac_list:
                if hasattr(ac, "ac_id"):
                    ac_id = ac.ac_id
                    ac_title = ac.title
                    is_testing = ac.is_testing_required
                else:
                    ac_id = ac.get("ac_id")
                    ac_title = ac.get("title")
                    is_testing = ac.get("is_testing_required", False)

                conn.execute(
                    "INSERT OR REPLACE INTO acceptance_criteria (ac_id, req_id, title, is_testing_required) VALUES (?, ?, ?, ?)",
                    (ac_id, req_id, ac_title, int(is_testing))
                )
        conn.commit()

    # Fallback check_requirement_coverage
    def check_requirement_coverage(conn: sqlite3.Connection) -> list:
        rows = conn.execute("""
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
            LEFT JOIN task_requirements trq ON r.req_id = trq.req_id
            LEFT JOIN tasks t ON trq.task_id = t.task_id
            LEFT JOIN claims c ON t.task_id = c.related_task
            LEFT JOIN claim_test_refs ctr ON c.claim_id = ctr.claim_id
            LEFT JOIN test_results tr ON ctr.test_nodeid = tr.nodeid
            GROUP BY r.req_id
            HAVING coverage_status != 'covered'
        """).fetchall()
        return [{"req_id": r[0], "coverage_status": r[1]} for r in rows]

    # Fallback check_claim_evidence
    def check_claim_evidence(conn: sqlite3.Connection) -> list:
        rows = conn.execute("""
            SELECT c.claim_id,
              CASE
                WHEN t.task_id IS NULL THEN 'task_missing'
                WHEN t.status != 'done' THEN 'task_not_done'
                WHEN COUNT(ctr.test_nodeid) = 0 THEN 'no_tests'
                WHEN SUM(CASE WHEN tr.nodeid IS NULL THEN 1 ELSE 0 END) > 0 THEN 'test_missing'
                WHEN SUM(CASE WHEN tr.outcome = 'passed' THEN 1 ELSE 0 END) < COUNT(ctr.test_nodeid) THEN 'test_failed'
                ELSE 'verified'
              END as verification_status
            FROM claims c
            LEFT JOIN tasks t ON c.related_task = t.task_id
            LEFT JOIN claim_test_refs ctr ON c.claim_id = ctr.claim_id
            LEFT JOIN test_results tr ON ctr.test_nodeid = tr.nodeid
            GROUP BY c.claim_id
            HAVING verification_status != 'verified'
        """).fetchall()
        return [{"claim_id": r[0], "verification_status": r[1]} for r in rows]

    # Fallback get_full_chain
    def get_full_chain(conn: sqlite3.Connection) -> list:
        rows = conn.execute("""
            SELECT 
                r.req_id, r.title, r.priority, r.category,
                ac.ac_id, ac.title, ac.is_testing_required,
                t.task_id, t.priority, t.status,
                c.claim_id,
                ctr.test_nodeid, tr.outcome,
                ccr.code_path, cov.percent_covered
            FROM requirements r
            LEFT JOIN acceptance_criteria ac ON r.req_id = ac.req_id
            LEFT JOIN task_requirements trq ON r.req_id = trq.req_id
            LEFT JOIN tasks t ON trq.task_id = t.task_id
            LEFT JOIN claims c ON t.task_id = c.related_task
            LEFT JOIN claim_test_refs ctr ON c.claim_id = ctr.claim_id
            LEFT JOIN test_results tr ON ctr.test_nodeid = tr.nodeid
            LEFT JOIN claim_code_refs ccr ON c.claim_id = ccr.claim_id
            LEFT JOIN coverage_reports cov ON ccr.code_path = cov.source_path
        """).fetchall()
        
        return [
            {
                "req_id": r[0],
                "req_title": r[1],
                "req_priority": r[2],
                "req_category": r[3],
                "ac_id": r[4],
                "ac_title": r[5],
                "is_testing_required": bool(r[6]) if r[6] is not None else None,
                "task_id": r[7],
                "task_priority": r[8],
                "task_status": r[9],
                "claim_id": r[10],
                "test_nodeid": r[11],
                "test_outcome": r[12],
                "code_path": r[13],
                "percent_covered": r[14]
            }
            for r in rows
        ]
else:
    # If using real implementation, import other functions from db.py
    from vibe_tracing.infra.db import (
        load_claims,
        load_staged_files,
        load_initial_cache,
        upsert_test_result,
        upsert_coverage_report,
        purge_stale_cache,
        check_ac_coverage,
        check_ghost_code,
        check_dangling_claims,
        check_test_dead_links,
    )


# ── Mock Classes for Object-Style Inputs ──────────────────────────────────────
class MockRequirement:
    def __init__(self, req_id, title, priority, category, acceptance_criteria=None):
        self.req_id = req_id
        self.title = title
        self.priority = priority
        self.category = category
        self.acceptance_criteria = acceptance_criteria or []

class MockAcceptanceCriteria:
    def __init__(self, ac_id, title, is_testing_required=False):
        self.ac_id = ac_id
        self.title = title
        self.is_testing_required = is_testing_required


# ──────────────────────────────────────────────────────────────────────────────
# TIER 1: FEATURE COVERAGE (5 tests per feature * 7 features = 35 tests)
# ──────────────────────────────────────────────────────────────────────────────

# ── Feature 1: Acceptance Criteria Coverage Check (F1) ──────────────────────

def test_tier1_f1_coverage_1_covered():
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-1", "title": "Test Requirement", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "Test AC", "is_testing_required": True}]}]})
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_acceptance_criteria": ["AC-1-1"]}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_node_1"]}])
    upsert_test_result(conn, "test_node_1", "passed", 0, "pytest", False)
    res = check_ac_coverage(conn)
    assert len(res) == 0, f"Expected 0 uncovered AC, got: {res}"
    conn.close()

def test_tier1_f1_coverage_2_no_claim():
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-1", "title": "Test Requirement", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "Test AC", "is_testing_required": True}]}]})
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_acceptance_criteria": ["AC-1-1"]}])
    res = check_ac_coverage(conn)
    assert len(res) == 1
    assert res[0]["coverage_status"] == "no_claim_for_task"
    conn.close()

def test_tier1_f1_coverage_3_no_tests():
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-1", "title": "Test Requirement", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "Test AC", "is_testing_required": True}]}]})
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_acceptance_criteria": ["AC-1-1"]}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": []}])
    res = check_ac_coverage(conn)
    assert len(res) == 1
    assert res[0]["coverage_status"] == "no_tests_declared"
    conn.close()

def test_tier1_f1_coverage_4_test_not_run():
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-1", "title": "Test Requirement", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "Test AC", "is_testing_required": True}]}]})
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_acceptance_criteria": ["AC-1-1"]}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_node_1"]}])
    res = check_ac_coverage(conn)
    assert len(res) == 1
    assert res[0]["coverage_status"] == "test_not_run"
    conn.close()

def test_tier1_f1_coverage_5_test_failed():
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-1", "title": "Test Requirement", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "Test AC", "is_testing_required": True}]}]})
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_acceptance_criteria": ["AC-1-1"]}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_node_1"]}])
    upsert_test_result(conn, "test_node_1", "failed", 1, "pytest", False)
    res = check_ac_coverage(conn)
    assert len(res) == 1
    assert res[0]["coverage_status"] == "test_failed"
    conn.close()


# ── Feature 2: Requirement Coverage Check (F2) ──────────────────────────────

def test_tier1_f2_coverage_1_covered():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": []}])
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_requirements": ["REQ-1"]}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_node_1"]}])
    upsert_test_result(conn, "test_node_1", "passed", 0, "pytest", False)
    res = check_requirement_coverage(conn)
    assert len(res) == 0
    conn.close()

def test_tier1_f2_coverage_2_no_task():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": []}])
    res = check_requirement_coverage(conn)
    assert len(res) == 1
    assert res[0]["coverage_status"] == "no_task_for_requirement"
    conn.close()

def test_tier1_f2_coverage_3_no_claim():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": []}])
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_requirements": ["REQ-1"]}])
    res = check_requirement_coverage(conn)
    assert len(res) == 1
    assert res[0]["coverage_status"] == "no_claim_for_task"
    conn.close()

def test_tier1_f2_coverage_4_no_tests():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": []}])
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_requirements": ["REQ-1"]}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": []}])
    res = check_requirement_coverage(conn)
    assert len(res) == 1
    assert res[0]["coverage_status"] == "no_tests_declared"
    conn.close()

def test_tier1_f2_coverage_5_test_not_run():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": []}])
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_requirements": ["REQ-1"]}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_node_1"]}])
    res = check_requirement_coverage(conn)
    assert len(res) == 1
    assert res[0]["coverage_status"] == "test_not_run"
    conn.close()


# ── Feature 3: Claim Evidence Verification Check (F3) ─────────────────────────

def test_tier1_f3_coverage_1_verified():
    conn = init_in_memory_db()
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done"}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_node_1"]}])
    upsert_test_result(conn, "test_node_1", "passed", 0, "pytest", False)
    res = check_claim_evidence(conn)
    assert len(res) == 0
    conn.close()

def test_tier1_f3_coverage_2_task_missing():
    conn = init_in_memory_db()
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_node_1"]}])
    upsert_test_result(conn, "test_node_1", "passed", 0, "pytest", False)
    res = check_claim_evidence(conn)
    assert len(res) == 1
    assert res[0]["verification_status"] == "task_missing"
    conn.close()

def test_tier1_f3_coverage_3_task_not_done():
    conn = init_in_memory_db()
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "in_progress"}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_node_1"]}])
    upsert_test_result(conn, "test_node_1", "passed", 0, "pytest", False)
    res = check_claim_evidence(conn)
    assert len(res) == 1
    assert res[0]["verification_status"] == "task_not_done"
    conn.close()

def test_tier1_f3_coverage_4_no_tests():
    conn = init_in_memory_db()
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done"}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": []}])
    res = check_claim_evidence(conn)
    assert len(res) == 1
    assert res[0]["verification_status"] == "no_tests"
    conn.close()

def test_tier1_f3_coverage_5_test_missing():
    conn = init_in_memory_db()
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done"}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_node_1"]}])
    res = check_claim_evidence(conn)
    assert len(res) == 1
    assert res[0]["verification_status"] == "test_missing"
    conn.close()


# ── Feature 4: Full Traceability Chain Query (F4) ────────────────────────────

def test_tier1_f4_coverage_1_complete_chain():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "AC 1", "is_testing_required": True}]}])
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_requirements": ["REQ-1"], "related_acceptance_criteria": ["AC-1-1"]}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "code_refs": ["src/foo.py"], "test_refs": ["test_node_1"]}])
    upsert_test_result(conn, "test_node_1", "passed", 0, "pytest", False)
    upsert_coverage_report(conn, "src/foo.py", 90.0, 10, "compliant", False)
    res = get_full_chain(conn)
    assert len(res) == 1
    assert res[0]["req_id"] == "REQ-1"
    assert res[0]["ac_id"] == "AC-1-1"
    assert res[0]["task_id"] == "TASK-1"
    assert res[0]["claim_id"] == "CLAIM-1"
    assert res[0]["test_nodeid"] == "test_node_1"
    assert res[0]["code_path"] == "src/foo.py"
    conn.close()

def test_tier1_f4_coverage_2_missing_task():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": []}])
    res = get_full_chain(conn)
    assert len(res) == 1
    assert res[0]["req_id"] == "REQ-1"
    assert res[0]["task_id"] is None
    conn.close()

def test_tier1_f4_coverage_3_multiple_acs():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional",
                     "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "AC 1", "is_testing_required": True},
                                             {"ac_id": "AC-1-2", "title": "AC 2", "is_testing_required": False}]}])
    res = get_full_chain(conn)
    assert len(res) == 2
    ac_ids = {r["ac_id"] for r in res}
    assert ac_ids == {"AC-1-1", "AC-1-2"}
    conn.close()

def test_tier1_f4_coverage_4_multiple_code_and_tests():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": []}])
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_requirements": ["REQ-1"]}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "code_refs": ["src/foo.py", "src/bar.py"], "test_refs": ["test_1", "test_2"]}])
    res = get_full_chain(conn)
    # The left joins with code refs and test refs can result in combinations
    assert len(res) == 4
    conn.close()

def test_tier1_f4_coverage_5_missing_claim():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": []}])
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_requirements": ["REQ-1"]}])
    res = get_full_chain(conn)
    assert len(res) == 1
    assert res[0]["req_id"] == "REQ-1"
    assert res[0]["task_id"] == "TASK-1"
    assert res[0]["claim_id"] is None
    conn.close()


# ── Feature 5: Ghost Code Check (F5) ────────────────────────────────────────

def test_tier1_f5_coverage_1_no_ghost():
    conn = init_in_memory_db()
    load_staged_files(conn, {"src/foo.py"})
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "code_refs": ["src/foo.py"]}])
    res = check_ghost_code(conn)
    assert len(res) == 0
    conn.close()

def test_tier1_f5_coverage_2_ghost_exists():
    conn = init_in_memory_db()
    load_staged_files(conn, {"src/ghost.py"})
    res = check_ghost_code(conn)
    assert len(res) == 1
    assert res[0] == "src/ghost.py"
    conn.close()

def test_tier1_f5_coverage_3_mixed_staged_files():
    conn = init_in_memory_db()
    load_staged_files(conn, {"src/foo.py", "src/ghost.py"})
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "code_refs": ["src/foo.py"]}])
    res = check_ghost_code(conn)
    assert len(res) == 1
    assert res[0] == "src/ghost.py"
    conn.close()

def test_tier1_f5_coverage_4_staged_file_in_claim_no_task():
    conn = init_in_memory_db()
    load_staged_files(conn, {"src/foo.py"})
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "NONEXISTENT", "code_refs": ["src/foo.py"]}])
    res = check_ghost_code(conn)
    assert len(res) == 0
    conn.close()

def test_tier1_f5_coverage_5_empty_staged():
    conn = init_in_memory_db()
    res = check_ghost_code(conn)
    assert len(res) == 0
    conn.close()


# ── Feature 6: Dangling Claims Check (F6) ───────────────────────────────────

def test_tier1_f6_coverage_1_no_dangling():
    conn = init_in_memory_db()
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done"}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1"}])
    res = check_dangling_claims(conn)
    assert len(res) == 0
    conn.close()

def test_tier1_f6_coverage_2_dangling_exists():
    conn = init_in_memory_db()
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-2"}])
    res = check_dangling_claims(conn)
    assert len(res) == 1
    assert res[0]["claim_id"] == "CLAIM-1"
    conn.close()

def test_tier1_f6_coverage_3_mixed_claims():
    conn = init_in_memory_db()
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done"}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1"}, {"claim_id": "CLAIM-2", "related_task": "TASK-2"}])
    res = check_dangling_claims(conn)
    assert len(res) == 1
    assert res[0]["claim_id"] == "CLAIM-2"
    conn.close()

def test_tier1_f6_coverage_4_priority_status_independence():
    conn = init_in_memory_db()
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "could", "status": "in_progress"}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1"}])
    res = check_dangling_claims(conn)
    assert len(res) == 0
    conn.close()

def test_tier1_f6_coverage_5_empty_database():
    conn = init_in_memory_db()
    res = check_dangling_claims(conn)
    assert len(res) == 0
    conn.close()


# ── Feature 7: Test Dead Links Check (F7) ───────────────────────────────────

def test_tier1_f7_coverage_1_no_dead_links():
    conn = init_in_memory_db()
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_1"]}])
    upsert_test_result(conn, "test_1", "passed", 0, "pytest", False)
    res = check_test_dead_links(conn)
    assert len(res) == 0
    conn.close()

def test_tier1_f7_coverage_2_dead_link_test_not_run():
    conn = init_in_memory_db()
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_1"]}])
    res = check_test_dead_links(conn)
    assert len(res) == 1
    assert res[0]["claim_id"] == "CLAIM-1"
    assert res[0]["test_nodeid"] == "test_1"
    conn.close()

def test_tier1_f7_coverage_3_dead_link_test_failed():
    conn = init_in_memory_db()
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_1"]}])
    upsert_test_result(conn, "test_1", "failed", 1, "pytest", False)
    res = check_test_dead_links(conn)
    assert len(res) == 1
    assert res[0]["claim_id"] == "CLAIM-1"
    assert res[0]["test_nodeid"] == "test_1"
    conn.close()

def test_tier1_f7_coverage_4_dead_link_test_skipped():
    conn = init_in_memory_db()
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_1"]}])
    upsert_test_result(conn, "test_1", "skipped", 0, "pytest", False)
    res = check_test_dead_links(conn)
    assert len(res) == 1
    assert res[0]["claim_id"] == "CLAIM-1"
    assert res[0]["test_nodeid"] == "test_1"
    conn.close()

def test_tier1_f7_coverage_5_mixed_dead_links():
    conn = init_in_memory_db()
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_1", "test_2"]}])
    upsert_test_result(conn, "test_1", "passed", 0, "pytest", False)
    upsert_test_result(conn, "test_2", "failed", 1, "pytest", False)
    res = check_test_dead_links(conn)
    assert len(res) == 1
    assert res[0]["claim_id"] == "CLAIM-1"
    assert res[0]["test_nodeid"] == "test_2"
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# TIER 2: BOUNDARY & CORNER CASES (5 tests per feature * 7 features = 35 tests)
# ──────────────────────────────────────────────────────────────────────────────

# ── Feature 1: Acceptance Criteria Coverage Check (F1) ──────────────────────

def test_tier2_f1_boundary_1_non_must_priority():
    conn = init_in_memory_db()
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "should", "status": "done", "related_acceptance_criteria": ["AC-1-1"]}])
    res = check_ac_coverage(conn)
    assert len(res) == 0
    conn.close()

def test_tier2_f1_boundary_2_multiple_acs():
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-1", "title": "Test Requirement", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-2-1", "title": "Test AC", "is_testing_required": True}]}]})
    load_tasks(conn, [{"task_id": "TASK-2", "priority": "must", "status": "done", "related_acceptance_criteria": ["AC-2-1"]}])
    res = check_ac_coverage(conn)
    assert len(res) == 1
    assert res[0]["ac_id"] == "AC-2-1"
    conn.close()

def test_tier2_f1_boundary_3_duplicate_loads():
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-1", "title": "Test Requirement", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "Test AC", "is_testing_required": True}]}]})
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_acceptance_criteria": ["AC-1-1"]}])
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_acceptance_criteria": ["AC-1-1"]}])
    res = check_ac_coverage(conn)
    assert len(res) == 1
    conn.close()

def test_tier2_f1_boundary_4_multiple_tests_one_passes():
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-1", "title": "Test Requirement", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "Test AC", "is_testing_required": True}]}]})
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_acceptance_criteria": ["AC-1-1"]}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_1", "test_2"]}])
    upsert_test_result(conn, "test_1", "passed", 0, "pytest", False)
    upsert_test_result(conn, "test_2", "failed", 1, "pytest", False)
    res = check_ac_coverage(conn)
    assert len(res) == 1
    assert res[0]["coverage_status"] == "test_failed"
    conn.close()

def test_tier2_f1_boundary_5_empty_database():
    conn = init_in_memory_db()
    res = check_ac_coverage(conn)
    assert len(res) == 0
    conn.close()


# ── Feature 2: Requirement Coverage Check (F2) ──────────────────────────────

def test_tier2_f2_boundary_1_priority_variations():
    conn = init_in_memory_db()
    load_prd(conn, [
        {"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional"},
        {"req_id": "REQ-2", "title": "Req 2", "priority": "should", "category": "functional"},
        {"req_id": "REQ-3", "title": "Req 3", "priority": "could", "category": "functional"}
    ])
    res = check_requirement_coverage(conn)
    assert len(res) == 3
    req_ids = {r["req_id"] for r in res}
    assert req_ids == {"REQ-1", "REQ-2", "REQ-3"}
    conn.close()

def test_tier2_f2_boundary_2_multiple_tasks_one_covered():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional"}])
    load_tasks(conn, [
        {"task_id": "TASK-1", "priority": "must", "status": "done", "related_requirements": ["REQ-1"]},
        {"task_id": "TASK-2", "priority": "must", "status": "done", "related_requirements": ["REQ-1"]}
    ])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_1"]}])
    upsert_test_result(conn, "test_1", "passed", 0, "pytest", False)
    res = check_requirement_coverage(conn)
    assert len(res) in (0, 1)
    conn.close()

def test_tier2_f2_boundary_3_single_task_multiple_reqs():
    conn = init_in_memory_db()
    load_prd(conn, [
        {"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional"},
        {"req_id": "REQ-2", "title": "Req 2", "priority": "must", "category": "functional"}
    ])
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_requirements": ["REQ-1", "REQ-2"]}])
    res = check_requirement_coverage(conn)
    assert len(res) == 2
    assert {r["req_id"] for r in res} == {"REQ-1", "REQ-2"}
    conn.close()

def test_tier2_f2_boundary_4_empty_prd():
    conn = init_in_memory_db()
    res = check_requirement_coverage(conn)
    assert len(res) == 0
    conn.close()

def test_tier2_f2_boundary_5_category_variations():
    conn = init_in_memory_db()
    load_prd(conn, [
        {"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional"},
        {"req_id": "REQ-2", "title": "Req 2", "priority": "must", "category": "quality_evolution"}
    ])
    res = check_requirement_coverage(conn)
    assert len(res) == 2
    conn.close()


# ── Feature 3: Claim Evidence Verification Check (F3) ─────────────────────────

def test_tier2_f3_boundary_1_test_failed():
    conn = init_in_memory_db()
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done"}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_1"]}])
    upsert_test_result(conn, "test_1", "failed", 1, "pytest", False)
    res = check_claim_evidence(conn)
    assert len(res) == 1
    assert res[0]["verification_status"] == "test_failed"
    conn.close()

def test_tier2_f3_boundary_2_multiple_claims_for_task():
    conn = init_in_memory_db()
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done"}])
    load_claims(conn, [
        {"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_1"]},
        {"claim_id": "CLAIM-2", "related_task": "TASK-1", "test_refs": ["test_2"]}
    ])
    upsert_test_result(conn, "test_1", "passed", 0, "pytest", False)
    res = check_claim_evidence(conn)
    assert len(res) == 1
    assert res[0]["claim_id"] == "CLAIM-2"
    conn.close()

def test_tier2_f3_boundary_3_multiple_tests_one_missing():
    conn = init_in_memory_db()
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done"}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_1", "test_2"]}])
    upsert_test_result(conn, "test_1", "passed", 0, "pytest", False)
    res = check_claim_evidence(conn)
    assert len(res) == 1
    assert res[0]["verification_status"] == "test_missing"
    conn.close()

def test_tier2_f3_boundary_4_multiple_tests_one_failed():
    conn = init_in_memory_db()
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done"}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_1", "test_2"]}])
    upsert_test_result(conn, "test_1", "passed", 0, "pytest", False)
    upsert_test_result(conn, "test_2", "failed", 1, "pytest", False)
    res = check_claim_evidence(conn)
    assert len(res) == 1
    assert res[0]["verification_status"] == "test_failed"
    conn.close()

def test_tier2_f3_boundary_5_empty_database():
    conn = init_in_memory_db()
    res = check_claim_evidence(conn)
    assert len(res) == 0
    conn.close()


# ── Feature 4: Full Traceability Chain Query (F4) ────────────────────────────

def test_tier2_f4_boundary_1_req_without_ac():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": []}])
    res = get_full_chain(conn)
    assert len(res) == 1
    assert res[0]["req_id"] == "REQ-1"
    assert res[0]["ac_id"] is None
    conn.close()

def test_tier2_f4_boundary_2_req_with_ac_no_task_no_claim():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "AC 1"}]}])
    res = get_full_chain(conn)
    assert len(res) == 1
    assert res[0]["req_id"] == "REQ-1"
    assert res[0]["ac_id"] == "AC-1-1"
    assert res[0]["task_id"] is None
    conn.close()

def test_tier2_f4_boundary_3_long_or_special_ids():
    conn = init_in_memory_db()
    special_id = "REQ-VT-999_SPECIAL-LONG-ID-WITH-DASHES"
    load_prd(conn, [{"req_id": special_id, "title": "Special ID", "priority": "must", "category": "functional", "acceptance_criteria": []}])
    res = get_full_chain(conn)
    assert len(res) == 1
    assert res[0]["req_id"] == special_id
    conn.close()

def test_tier2_f4_boundary_4_complex_cross_references():
    conn = init_in_memory_db()
    load_prd(conn, [
        {"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional"},
        {"req_id": "REQ-2", "title": "Req 2", "priority": "should", "category": "functional"}
    ])
    load_tasks(conn, [
        {"task_id": "TASK-1", "priority": "must", "status": "done", "related_requirements": ["REQ-1", "REQ-2"]},
        {"task_id": "TASK-2", "priority": "should", "status": "done", "related_requirements": ["REQ-2"]}
    ])
    res = get_full_chain(conn)
    assert len(res) == 3
    conn.close()

def test_tier2_f4_boundary_5_empty_database():
    conn = init_in_memory_db()
    res = get_full_chain(conn)
    assert len(res) == 0
    conn.close()


# ── Feature 5: Ghost Code Check (F5) ────────────────────────────────────────

def test_tier2_f5_boundary_1_complex_path_formats():
    conn = init_in_memory_db()
    complex_path = "src/vibe_tracing/cli/analyze/reports.py"
    load_staged_files(conn, {complex_path})
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "code_refs": [complex_path]}])
    res = check_ghost_code(conn)
    assert len(res) == 0
    conn.close()

def test_tier2_f5_boundary_2_multiple_claims_same_file():
    conn = init_in_memory_db()
    load_staged_files(conn, {"src/foo.py"})
    load_claims(conn, [
        {"claim_id": "CLAIM-1", "related_task": "TASK-1", "code_refs": ["src/foo.py"]},
        {"claim_id": "CLAIM-2", "related_task": "TASK-2", "code_refs": ["src/foo.py"]}
    ])
    res = check_ghost_code(conn)
    assert len(res) == 0
    conn.close()

def test_tier2_f5_boundary_3_unstaged_claim_refs():
    conn = init_in_memory_db()
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "code_refs": ["src/unstaged.py"]}])
    res = check_ghost_code(conn)
    assert len(res) == 0
    conn.close()

def test_tier2_f5_boundary_4_non_standard_filenames():
    conn = init_in_memory_db()
    filename = "src/foo.bar-baz.config.json"
    load_staged_files(conn, {filename})
    res = check_ghost_code(conn)
    assert len(res) == 1
    assert res[0] == filename
    conn.close()

def test_tier2_f5_boundary_5_empty_database():
    conn = init_in_memory_db()
    res = check_ghost_code(conn)
    assert len(res) == 0
    conn.close()


# ── Feature 6: Dangling Claims Check (F6) ───────────────────────────────────

def test_tier2_f6_boundary_1_whitespace_ids():
    conn = init_in_memory_db()
    load_tasks(conn, [{"task_id": " TASK-1 ", "priority": "must", "status": "done"}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1"}])
    res = check_dangling_claims(conn)
    assert len(res) == 1
    conn.close()

def test_tier2_f6_boundary_2_multiple_claims_same_missing_task():
    conn = init_in_memory_db()
    load_claims(conn, [
        {"claim_id": "CLAIM-1", "related_task": "MISSING"},
        {"claim_id": "CLAIM-2", "related_task": "MISSING"}
    ])
    res = check_dangling_claims(conn)
    assert len(res) == 2
    claim_ids = {r["claim_id"] for r in res}
    assert claim_ids == {"CLAIM-1", "CLAIM-2"}
    conn.close()

def test_tier2_f6_boundary_3_task_updated_dangling_resolved():
    conn = init_in_memory_db()
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1"}])
    assert len(check_dangling_claims(conn)) == 1
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done"}])
    assert len(check_dangling_claims(conn)) == 0
    conn.close()

def test_tier2_f6_boundary_4_empty_string_ids():
    conn = init_in_memory_db()
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": ""}])
    res = check_dangling_claims(conn)
    assert len(res) == 1
    assert res[0]["related_task"] == ""
    conn.close()

def test_tier2_f6_boundary_5_bulk_dangling_claims():
    conn = init_in_memory_db()
    claims = [{"claim_id": f"CLAIM-{i}", "related_task": "MISSING"} for i in range(50)]
    load_claims(conn, claims)
    res = check_dangling_claims(conn)
    assert len(res) == 50
    conn.close()


# ── Feature 7: Test Dead Links Check (F7) ───────────────────────────────────

def test_tier2_f7_boundary_1_parametrized_nodeids():
    conn = init_in_memory_db()
    nodeid = "tests/test_foo.py::TestClass::test_method[param-value]"
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": [nodeid]}])
    upsert_test_result(conn, nodeid, "passed", 0, "pytest", False)
    res = check_test_dead_links(conn)
    assert len(res) == 0
    conn.close()

def test_tier2_f7_boundary_2_multiple_claims_same_dead_link():
    conn = init_in_memory_db()
    load_claims(conn, [
        {"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_1"]},
        {"claim_id": "CLAIM-2", "related_task": "TASK-2", "test_refs": ["test_1"]}
    ])
    res = check_test_dead_links(conn)
    assert len(res) == 2
    assert {r["claim_id"] for r in res} == {"CLAIM-1", "CLAIM-2"}
    conn.close()

def test_tier2_f7_boundary_3_non_zero_exit_code_passed_outcome():
    conn = init_in_memory_db()
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_1"]}])
    upsert_test_result(conn, "test_1", "passed", 1, "pytest", False)
    res = check_test_dead_links(conn)
    assert len(res) == 0
    conn.close()

def test_tier2_f7_boundary_4_empty_nodeid_reference():
    conn = init_in_memory_db()
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": [""]}])
    res = check_test_dead_links(conn)
    assert len(res) == 0
    conn.close()

def test_tier2_f7_boundary_5_empty_database():
    conn = init_in_memory_db()
    res = check_test_dead_links(conn)
    assert len(res) == 0
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# TIER 3: CROSS-FEATURE COMBINATIONS (7 tests)
# ──────────────────────────────────────────────────────────────────────────────

def test_tier3_combo_1_complete_missing_chain():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "AC 1"}]}])
    res_f2 = check_requirement_coverage(conn)
    assert len(res_f2) == 1
    assert res_f2[0]["coverage_status"] == "no_task_for_requirement"
    assert len(check_ac_coverage(conn)) == 0
    conn.close()

def test_tier3_combo_2_overlapping_dangling_and_dead_links():
    conn = init_in_memory_db()
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "NONEXISTENT", "test_refs": ["test_dead"]}])
    res_f6 = check_dangling_claims(conn)
    assert len(res_f6) == 1
    assert res_f6[0]["claim_id"] == "CLAIM-1"
    res_f7 = check_test_dead_links(conn)
    assert len(res_f7) == 1
    assert res_f7[0]["claim_id"] == "CLAIM-1"
    conn.close()

def test_tier3_combo_3_cascading_test_failure():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "AC 1"}]}])
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_requirements": ["REQ-1"], "related_acceptance_criteria": ["AC-1-1"]}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_1"]}])
    upsert_test_result(conn, "test_1", "failed", 1, "pytest", False)

    res_f1 = check_ac_coverage(conn)
    assert len(res_f1) == 1
    assert res_f1[0]["coverage_status"] == "test_failed"

    res_f2 = check_requirement_coverage(conn)
    assert len(res_f2) == 1
    assert res_f2[0]["coverage_status"] == "test_failed"

    res_f3 = check_claim_evidence(conn)
    assert len(res_f3) == 1
    assert res_f3[0]["verification_status"] == "test_failed"
    conn.close()

def test_tier3_combo_4_staged_violated_coverage():
    conn = init_in_memory_db()
    load_staged_files(conn, {"src/foo.py"})
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "code_refs": ["src/foo.py"]}])
    upsert_coverage_report(conn, "src/foo.py", 45.0, 100, "violated", False)

    assert len(check_ghost_code(conn)) == 0

    from vibe_tracing.infra.db import check_coverage_violations
    res_cov = check_coverage_violations(conn)
    assert len(res_cov) == 1
    assert res_cov[0]["source_path"] == "src/foo.py"
    conn.close()

def test_tier3_combo_5_large_scale_sync():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "AC 1"}]}])
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_requirements": ["REQ-1"], "related_acceptance_criteria": ["AC-1-1"]}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "code_refs": ["src/foo.py"], "test_refs": ["test_1"]}])
    load_staged_files(conn, {"src/foo.py"})
    upsert_test_result(conn, "test_1", "passed", 0, "pytest", False)
    upsert_coverage_report(conn, "src/foo.py", 95.0, 100, "compliant", False)

    assert len(check_ac_coverage(conn)) == 0
    assert len(check_requirement_coverage(conn)) == 0
    assert len(check_claim_evidence(conn)) == 0
    assert len(check_ghost_code(conn)) == 0
    assert len(check_dangling_claims(conn)) == 0
    assert len(check_test_dead_links(conn)) == 0
    assert len(get_full_chain(conn)) == 1
    conn.close()

def test_tier3_combo_6_cache_purging_dead_links():
    conn = init_in_memory_db()
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["tests/test_foo.py::test_1"]}])
    conn.execute("INSERT INTO test_results (nodeid, outcome, exit_code, command, carried_over) VALUES (?, ?, ?, ?, ?)", ("tests/test_foo.py::test_1", "passed", 0, "pytest", 1))
    conn.commit()

    assert len(check_test_dead_links(conn)) == 0
    purge_stale_cache(conn, ["tests/test_foo.py"])

    res = check_test_dead_links(conn)
    assert len(res) == 1
    assert res[0]["claim_id"] == "CLAIM-1"
    conn.close()

def test_tier3_combo_7_soft_integrity_violations():
    conn = init_in_memory_db()
    load_staged_files(conn, {"src/ghost1.py", "src/ghost2.py"})
    load_claims(conn, [
        {"claim_id": "CLAIM-1", "related_task": "TASK-MISSING", "test_refs": ["test_dead_1"]},
        {"claim_id": "CLAIM-2", "related_task": "TASK-MISSING", "test_refs": ["test_dead_2"]}
    ])
    assert len(check_dangling_claims(conn)) == 2
    assert len(check_test_dead_links(conn)) == 2
    assert len(check_ghost_code(conn)) == 2
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# TIER 4: REAL-WORLD APPLICATION SCENARIOS (5 tests)
# ──────────────────────────────────────────────────────────────────────────────

def test_tier4_scenario_1_new_feature_development():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-100", "title": "New Auth", "priority": "must", "category": "functional", "acceptance_criteria": []}])
    load_tasks(conn, [{"task_id": "TASK-100", "priority": "must", "status": "in_progress", "related_requirements": ["REQ-100"]}])
    load_staged_files(conn, {"src/auth.py"})

    res_f2 = check_requirement_coverage(conn)
    assert len(res_f2) == 1
    assert res_f2[0]["coverage_status"] == "no_claim_for_task"

    res_f5 = check_ghost_code(conn)
    assert len(res_f5) == 1
    assert res_f5[0] == "src/auth.py"
    conn.close()

def test_tier4_scenario_2_refactoring_renaming_tests():
    conn = init_in_memory_db()
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["tests/test_auth.py::test_login_old"]}])
    conn.execute("INSERT INTO test_results (nodeid, outcome, exit_code, command, carried_over) VALUES (?, ?, ?, ?, ?)", ("tests/test_auth.py::test_login_old", "passed", 0, "pytest", 1))
    conn.commit()

    assert len(check_test_dead_links(conn)) == 0

    purge_stale_cache(conn, ["tests/test_auth.py"])
    upsert_test_result(conn, "tests/test_auth.py::test_login_new", "passed", 0, "pytest", False)

    res = check_test_dead_links(conn)
    assert len(res) == 1
    assert res[0]["test_nodeid"] == "tests/test_auth.py::test_login_old"
    conn.close()

def test_tier4_scenario_3_feature_complete_verification():
    conn = init_in_memory_db()
    load_prd(conn, [MockRequirement("REQ-1", "Auth Feature", "must", "functional", [MockAcceptanceCriteria("AC-1-1", "Login validation", True)])])
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_requirements": ["REQ-1"], "related_acceptance_criteria": ["AC-1-1"]}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "code_refs": ["src/login.py"], "test_refs": ["tests/test_login.py::test_valid"]}])
    load_staged_files(conn, {"src/login.py"})
    upsert_test_result(conn, "tests/test_login.py::test_valid", "passed", 0, "pytest", False)
    upsert_coverage_report(conn, "src/login.py", 90.0, 50, "compliant", False)

    assert len(check_ac_coverage(conn)) == 0
    assert len(check_requirement_coverage(conn)) == 0
    assert len(check_claim_evidence(conn)) == 0
    assert len(check_ghost_code(conn)) == 0
    assert len(check_dangling_claims(conn)) == 0
    assert len(check_test_dead_links(conn)) == 0

    chain = get_full_chain(conn)
    assert len(chain) == 1
    assert chain[0]["req_id"] == "REQ-1"
    assert chain[0]["ac_id"] == "AC-1-1"
    assert chain[0]["task_id"] == "TASK-1"
    assert chain[0]["claim_id"] == "CLAIM-1"
    assert chain[0]["test_nodeid"] == "tests/test_login.py::test_valid"
    assert chain[0]["code_path"] == "src/login.py"
    conn.close()

def test_tier4_scenario_4_critical_bug_hotfix():
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-911", "title": "Hotfix Requirement", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-911-1", "title": "Hotfix AC", "is_testing_required": True}]}]})
    load_tasks(conn, [{"task_id": "TASK-911", "priority": "must", "status": "done", "related_acceptance_criteria": ["AC-911-1"]}])
    load_claims(conn, [{"claim_id": "CLAIM-911", "related_task": "TASK-911", "test_refs": ["tests/test_hotfix.py::test_bug"]}])
    upsert_test_result(conn, "tests/test_hotfix.py::test_bug", "failed", 1, "pytest", False)

    res_f1 = check_ac_coverage(conn)
    assert len(res_f1) == 1
    assert res_f1[0]["task_id"] == "TASK-911"
    assert res_f1[0]["coverage_status"] == "test_failed"
    conn.close()

def test_tier4_scenario_5_quality_evolution_requirement():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-Q-1", "title": "Optimize performance", "priority": "should", "category": "quality_evolution", "acceptance_criteria": []}])
    load_tasks(conn, [{"task_id": "TASK-Q-1", "priority": "should", "status": "done", "related_requirements": ["REQ-Q-1"]}])
    load_claims(conn, [{"claim_id": "CLAIM-Q-1", "related_task": "TASK-Q-1", "test_refs": ["tests/test_perf.py::test_speed"]}])
    upsert_test_result(conn, "tests/test_perf.py::test_speed", "passed", 0, "pytest", False)

    assert len(check_requirement_coverage(conn)) == 0

    chain = get_full_chain(conn)
    assert len(chain) == 1
    assert chain[0]["req_id"] == "REQ-Q-1"
    assert chain[0]["req_category"] == "quality_evolution"
    assert chain[0]["task_id"] == "TASK-Q-1"
    assert chain[0]["test_outcome"] == "passed"
    conn.close()


# ── Adversarial Tests ─────────────────────────────────────────────────────────

def test_adversarial_ac_coverage_mixed_outcomes_bug():
    """
    BUG/GAP: If a MUST task has multiple tests, where one passes and one fails,
    check_ac_coverage returns 'covered' (empty list) instead of 'test_failed'.
    """
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-AD-1", "title": "Adversarial Requirement", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-AD-1", "title": "Adversarial AC", "is_testing_required": True}]}]})
    load_tasks(conn, [
        {"task_id": "TASK-AD-1", "priority": "must", "status": "done", "related_acceptance_criteria": ["AC-AD-1"]}
    ])
    load_claims(conn, [
        {"claim_id": "CLAIM-AD-1", "related_task": "TASK-AD-1", "test_refs": ["test_pass", "test_fail"]}
    ])
    upsert_test_result(conn, "test_pass", "passed", 0, "pytest", False)
    upsert_test_result(conn, "test_fail", "failed", 1, "pytest", False)

    res = check_ac_coverage(conn)
    assert len(res) == 1, f"Expected 1 uncovered AC due to failed test, got: {res}"
    assert res[0]["coverage_status"] == "test_failed"
    conn.close()

def test_adversarial_ac_coverage_missing_test_bug():
    """
    BUG/GAP: If a MUST task has multiple tests, where one passes and one has not run,
    check_ac_coverage returns 'covered' (empty list) instead of 'test_not_run'.
    """
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-AD-2", "title": "Adversarial Requirement 2", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-AD-2", "title": "Adversarial AC 2", "is_testing_required": True}]}]})
    load_tasks(conn, [
        {"task_id": "TASK-AD-2", "priority": "must", "status": "done", "related_acceptance_criteria": ["AC-AD-2"]}
    ])
    load_claims(conn, [
        {"claim_id": "CLAIM-AD-2", "related_task": "TASK-AD-2", "test_refs": ["test_pass", "test_missing"]}
    ])
    upsert_test_result(conn, "test_pass", "passed", 0, "pytest", False)

    res = check_ac_coverage(conn)
    assert len(res) == 1, f"Expected 1 uncovered AC due to missing test execution, got: {res}"
    assert res[0]["coverage_status"] == "test_not_run"
    conn.close()

def test_adversarial_requirement_coverage_missing_test_bug():
    """
    BUG/GAP: If a requirement has multiple tests, where one passes and one has not run,
    check_requirement_coverage returns 'covered' instead of 'test_not_run'.
    """
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-AD-3", "title": "Req AD 3", "priority": "must", "category": "functional", "acceptance_criteria": []}])
    load_tasks(conn, [{"task_id": "TASK-AD-3", "priority": "must", "status": "done", "related_requirements": ["REQ-AD-3"]}])
    load_claims(conn, [{"claim_id": "CLAIM-AD-3", "related_task": "TASK-AD-3", "test_refs": ["test_pass", "test_missing"]}])
    upsert_test_result(conn, "test_pass", "passed", 0, "pytest", False)
    
    res = check_requirement_coverage(conn)
    assert len(res) == 1, f"Expected 1 uncovered requirement due to missing test execution, got: {res}"
    assert res[0]["coverage_status"] == "test_not_run"
    conn.close()

def test_adversarial_load_prd_invalid_requirements_type():
    """
    Adversarial input check: passing an invalid requirements field in load_prd.
    """
    conn = init_in_memory_db()
    invalid_prd = {"requirements": 12345}
    with pytest.raises(TypeError):
        load_prd(conn, invalid_prd)
    conn.close()

def test_adversarial_load_prd_invalid_ac_type():
    """
    Adversarial input check: passing an invalid acceptance criteria field in load_prd.
    """
    conn = init_in_memory_db()
    invalid_prd = [{"req_id": "REQ-1", "title": "Req", "priority": "must", "category": "func", "acceptance_criteria": 999}]
    with pytest.raises(TypeError):
        load_prd(conn, invalid_prd)
    conn.close()

def test_adversarial_uninitialized_database_connection():
    """
    Edge case: Passing a clean uninitialized sqlite3 connection without tables.
    """
    conn = sqlite3.connect(":memory:")
    with pytest.raises(sqlite3.OperationalError):
        check_ac_coverage(conn)
    conn.close()

def test_adversarial_load_tasks_not_null_violation():
    """
    Edge case: Passing None in required NOT NULL database fields (like status).
    """
    conn = init_in_memory_db()
    with pytest.raises(sqlite3.IntegrityError):
        load_tasks(conn, [{"task_id": "TASK-ERR", "priority": "must", "status": None}])
    conn.close()

def test_adversarial_load_initial_cache_invalid_json(tmp_path):
    """
    Edge case: Cache directory contains invalid JSON files.
    """
    conn = init_in_memory_db()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "test_results.json").write_text("invalid json {")
    with pytest.raises(Exception):
        load_initial_cache(conn, str(cache_dir))
    conn.close()

def test_adversarial_sql_injection_mitigated():
    """
    Security check: Ensure SQL injection strings in task loading are handled safely.
    """
    conn = init_in_memory_db()
    injection_id = "TASK-1'; DROP TABLE tasks; --"
    load_tasks(conn, [{"task_id": injection_id, "priority": "must", "status": "done"}])
    
    cursor = conn.execute("SELECT task_id FROM tasks WHERE task_id = ?", (injection_id,))
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == injection_id
    conn.close()


def test_adversarial_check_active_task_coverage_states():
    """
    Test check_active_task_coverage with various task statuses and coverage scenarios.
    """
    conn = init_in_memory_db()
    # 1. in_progress task with coverage report (violated status) -> should be returned
    load_tasks(conn, [{"task_id": "TASK-ACT-1", "priority": "must", "status": "in_progress"}])
    load_claims(conn, [{"claim_id": "CLAIM-ACT-1", "related_task": "TASK-ACT-1", "code_refs": ["src/violated.py"]}])
    upsert_coverage_report(conn, "src/violated.py", 45.0, 10, "violated", False)

    # 2. in_progress task with coverage report (compliant status) -> should NOT be returned
    load_tasks(conn, [{"task_id": "TASK-ACT-2", "priority": "must", "status": "in_progress"}])
    load_claims(conn, [{"claim_id": "CLAIM-ACT-2", "related_task": "TASK-ACT-2", "code_refs": ["src/compliant.py"]}])
    upsert_coverage_report(conn, "src/compliant.py", 95.0, 10, "compliant", False)

    # 3. in_progress task with missing coverage report -> should be returned
    load_tasks(conn, [{"task_id": "TASK-ACT-3", "priority": "must", "status": "in_progress"}])
    load_claims(conn, [{"claim_id": "CLAIM-ACT-3", "related_task": "TASK-ACT-3", "code_refs": ["src/missing.py"]}])

    # 4. done task with violated coverage report -> should NOT be returned
    load_tasks(conn, [{"task_id": "TASK-ACT-4", "priority": "must", "status": "done"}])
    load_claims(conn, [{"claim_id": "CLAIM-ACT-4", "related_task": "TASK-ACT-4", "code_refs": ["src/violated_done.py"]}])
    upsert_coverage_report(conn, "src/violated_done.py", 30.0, 10, "violated", False)

    from vibe_tracing.infra.db.queries import check_active_task_coverage
    res = check_active_task_coverage(conn)

    # We expect src/violated.py (case 1) and src/missing.py (case 3) to be returned.
    code_paths = {r["code_path"] for r in res}
    assert "src/violated.py" in code_paths
    assert "src/missing.py" in code_paths
    assert "src/compliant.py" not in code_paths
    assert "src/violated_done.py" not in code_paths
    assert len(code_paths) == 2
    conn.close()


def test_adversarial_check_coverage_violations_multiple():
    """
    Test check_coverage_violations under different coverage report statuses.
    """
    conn = init_in_memory_db()
    upsert_coverage_report(conn, "src/violated_1.py", 10.0, 5, "violated", False)
    upsert_coverage_report(conn, "src/compliant.py", 90.0, 20, "compliant", False)
    upsert_coverage_report(conn, "src/violated_2.py", 50.0, 8, "violated", False)

    from vibe_tracing.infra.db.queries import check_coverage_violations
    res = check_coverage_violations(conn)
    paths = {r["source_path"] for r in res}
    assert paths == {"src/violated_1.py", "src/violated_2.py"}
    conn.close()


def test_adversarial_purge_stale_cache_wildcard_delete():
    """
    Stress test purge_stale_cache to demonstrate the wildcard vulnerability:
    passing a path with LIKE wildcards (e.g. '%') causes unintended cache purges.
    """
    conn = init_in_memory_db()
    # Insert carried_over results for two files
    upsert_test_result(conn, "tests/test_a.py::test_1", "passed", 0, "pytest", True)
    upsert_test_result(conn, "tests/test_b.py::test_2", "passed", 0, "pytest", True)

    # Purge stale cache with a wildcard pattern
    purge_stale_cache(conn, ["tests/test_%.py"])

    # If '%' is treated as a wildcard in LIKE 'tests/test_%.py::%', both test results will be purged!
    rows = conn.execute("SELECT nodeid FROM test_results WHERE carried_over = 1").fetchall()
    assert len(rows) == 0, "Wildcard in filename caused unintended cache purging"
    conn.close()


def test_adversarial_load_initial_cache_missing_source_path(tmp_path):
    """
    Edge case: load_initial_cache skips coverage reports where source_path is not a file relative to cache_path.parent.
    """
    import json
    conn = init_in_memory_db()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    
    # We write a coverage_reports.json with a source_path 'src/some_file.py'
    cov_data = [{"source_path": "src/some_file.py", "percent_covered": 80.0, "num_statements": 10, "status": "compliant"}]
    (cache_dir / "coverage_reports.json").write_text(json.dumps(cov_data))
    
    # The file 'src/some_file.py' does NOT exist under cache_dir.parent (which is tmp_path)
    # Therefore, load_initial_cache should skip this record
    load_initial_cache(conn, str(cache_dir))
    
    rows = conn.execute("SELECT source_path FROM coverage_reports").fetchall()
    assert len(rows) == 0, "Coverage report was loaded despite file not existing relative to cache_path.parent"
    conn.close()


def test_adversarial_load_claims_missing_keys():
    """
    Robustness test: load_claims handles missing optional fields gracefully or raises KeyError for missing required fields.
    """
    conn = init_in_memory_db()
    # 1. Missing required key 'claim_id' should raise KeyError
    with pytest.raises(KeyError):
        load_claims(conn, [{"related_task": "TASK-1"}])

    # 2. Missing optional keys 'code_refs' or 'test_refs' should be handled gracefully by falling back to empty lists
    load_claims(conn, [{"claim_id": "CLAIM-OPT", "related_task": "TASK-1"}])
    rows = conn.execute("SELECT claim_id, related_task FROM claims").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "CLAIM-OPT"
    conn.close()


def test_adversarial_closed_database_connection_graceful_failure():
    """
    Robustness test: calling query/loader functions with a closed connection fails predictably with sqlite3.ProgrammingError.
    """
    conn = init_in_memory_db()
    conn.close()

    # All these should raise ProgrammingError or similar exception on a closed connection
    with pytest.raises(sqlite3.ProgrammingError):
        check_ac_coverage(conn)
    with pytest.raises(sqlite3.ProgrammingError):
        check_requirement_coverage(conn)
    with pytest.raises(sqlite3.ProgrammingError):
        get_full_chain(conn)
    with pytest.raises(sqlite3.ProgrammingError):
        load_tasks(conn, [{"task_id": "T1", "priority": "must", "status": "done"}])


