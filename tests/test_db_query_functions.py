import sqlite3
import pytest

from vibe_tracing.infra.config.enums import CoverageStatus
from vibe_tracing.infra.db import (
    init_in_memory_db, load_tasks, load_prd, load_claims,
    check_ac_coverage, check_requirement_coverage, check_claim_evidence,
    check_dangling_claims, check_coverage_violations,
    get_full_chain, check_isolated_tasks, check_invalid_task_requirements,
    check_invalid_task_acs, check_invalid_task_modules, check_invalid_task_constraints,
    check_invalid_ac_parent,
    upsert_test_result, upsert_coverage_report, purge_stale_cache,
    load_initial_cache, load_architecture_constraints,
)


@pytest.fixture
def conn():
    c = init_in_memory_db()
    yield c
    c.close()


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
    upsert_test_result(conn, "test_node_1", CoverageStatus.COVERED.value, 0, "pytest", False)
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


def test_tier1_f1_coverage_2b_in_progress_no_claim_not_flagged():
    """in_progress 任务无 Claim 不应触发 no_claim_for_task（仅 done 任务需要 Claim）。"""
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-1", "title": "Test", "priority": "must",
              "category": "functional", "acceptance_criteria": [
                  {"ac_id": "AC-1-1", "title": "Test AC", "is_testing_required": True}
              ]}]})
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "in_progress",
                        "related_acceptance_criteria": ["AC-1-1"]}])
    res = check_ac_coverage(conn)
    assert len(res) == 0, f"in_progress task should not trigger no_claim_for_task, got: {res}"
    conn.close()


def test_tier1_f2_in_progress_no_claim_not_flagged():
    """in_progress 任务无 Claim 不应触发 no_claim_for_task（需求覆盖检查）。"""
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must",
                     "category": "functional", "acceptance_criteria": []}])
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "in_progress",
                        "related_requirements": ["REQ-1"]}])
    res = check_requirement_coverage(conn)
    assert len(res) == 0, f"in_progress task should not trigger no_claim_for_task, got: {res}"
    conn.close()


@pytest.mark.parametrize("status", ["in_progress", "todo", "blocked", "cancelled"])
def test_non_done_task_no_claim_not_flagged(status):
    """所有非 done 状态的任务无 Claim 均不应触发 no_claim_for_task。"""
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-1", "title": "Test", "priority": "must",
              "category": "functional", "acceptance_criteria": [
                  {"ac_id": "AC-1-1", "title": "AC", "is_testing_required": True}
              ]}]})
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": status,
                        "related_acceptance_criteria": ["AC-1-1"]}])
    res = check_ac_coverage(conn)
    assert len(res) == 0, f"status={status} should not trigger no_claim_for_task, got: {res}"
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
    upsert_test_result(conn, "test_node_1", CoverageStatus.VIOLATED.value, 1, "pytest", False)
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
    upsert_test_result(conn, "test_node_1", CoverageStatus.COVERED.value, 0, "pytest", False)
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
    upsert_test_result(conn, "test_node_1", CoverageStatus.COVERED.value, 0, "pytest", False)
    res = check_claim_evidence(conn)
    assert len(res) == 0
    conn.close()

def test_tier1_f3_coverage_2_task_missing():
    conn = init_in_memory_db()
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_node_1"]}])
    upsert_test_result(conn, "test_node_1", CoverageStatus.COVERED.value, 0, "pytest", False)
    res = check_claim_evidence(conn)
    assert len(res) == 1
    assert res[0]["verification_status"] == "task_missing"
    conn.close()

def test_tier1_f3_coverage_3_task_not_done():
    conn = init_in_memory_db()
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "in_progress"}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_node_1"]}])
    upsert_test_result(conn, "test_node_1", CoverageStatus.COVERED.value, 0, "pytest", False)
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
    upsert_test_result(conn, "test_node_1", CoverageStatus.COVERED.value, 0, "pytest", False)
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

@pytest.mark.parametrize("check_fn", [
    check_ac_coverage, check_requirement_coverage, check_claim_evidence,
    check_dangling_claims,
])
def test_empty_database_returns_empty(check_fn, conn):
    assert check_fn(conn) == []


# ──────────────────────────────────────────────────────────────────────────────
# TIER 2: BOUNDARY & CORNER CASES (5 tests per feature * 7 features = 35 tests)
# ──────────────────────────────────────────────────────────────────────────────

# ── Feature 1: Acceptance Criteria Coverage Check (F1) ──────────────────────

def test_tier2_f1_boundary_1_non_must_priority():
    """非 MUST 优先级的 requirement 有 AC 缺口也应被检测到（全量检查）。

    原测试名同名但数据构造只 load_tasks 不 load_prd（acceptance_criteria 空表），
    实际测的是"无 AC 数据→0 结果"。现改为真实的非 MUST 全量检查场景。
    """
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Should Req", "priority": "should",
                     "category": "functional",
                     "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "AC 1", "is_testing_required": True}]}])
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "should", "status": "done",
                        "related_acceptance_criteria": ["AC-1-1"]}])
    res = check_ac_coverage(conn)
    assert len(res) == 1
    assert res[0]["coverage_status"] == "no_claim_for_task"
    conn.close()

def test_tier2_f1_boundary_3_duplicate_loads():
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-1", "title": "Test Requirement", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "Test AC", "is_testing_required": True}]}]})
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_acceptance_criteria": ["AC-1-1"]}])
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_acceptance_criteria": ["AC-1-1"]}])
    res = check_ac_coverage(conn)
    assert len(res) == 1
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
    upsert_test_result(conn, "test_1", CoverageStatus.COVERED.value, 0, "pytest", False)
    res = check_requirement_coverage(conn)
    assert len(res) == 1
    assert res[0]["coverage_status"] in ("no_claim_for_task", "test_not_run")
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
    upsert_test_result(conn, "test_1", CoverageStatus.VIOLATED.value, 1, "pytest", False)
    res = check_claim_evidence(conn)
    assert len(res) == 1
    assert res[0]["verification_status"] == "test_failed"
    conn.close()

def test_tier2_f3_boundary_2_one_task_one_claim_enforced():
    """UNIQUE(related_task) 约束确保一个 task 只对应一个 claim，后加载的 claim 替换前者。"""
    conn = init_in_memory_db()
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done"}])
    load_claims(conn, [
        {"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_1"]},
        {"claim_id": "CLAIM-2", "related_task": "TASK-1", "test_refs": ["test_2"]}
    ])
    upsert_test_result(conn, "test_1", CoverageStatus.COVERED.value, 0, "pytest", False)
    res = check_claim_evidence(conn)
    assert len(res) == 1
    assert res[0]["claim_id"] == "CLAIM-2"
    assert res[0]["verification_status"] == "test_missing"
    conn.close()

def test_tier2_f3_boundary_3_multiple_tests_one_missing():
    conn = init_in_memory_db()
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done"}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_1", "test_2"]}])
    upsert_test_result(conn, "test_1", CoverageStatus.COVERED.value, 0, "pytest", False)
    res = check_claim_evidence(conn)
    assert len(res) == 1
    assert res[0]["verification_status"] == "test_missing"
    conn.close()

def test_tier2_f3_boundary_4_multiple_tests_one_failed():
    conn = init_in_memory_db()
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done"}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_1", "test_2"]}])
    upsert_test_result(conn, "test_1", CoverageStatus.COVERED.value, 0, "pytest", False)
    upsert_test_result(conn, "test_2", CoverageStatus.VIOLATED.value, 1, "pytest", False)
    res = check_claim_evidence(conn)
    assert len(res) == 1
    assert res[0]["verification_status"] == "test_failed"
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

def test_tier2_f4_regression_ac_misalignment_no_spurious_pairs():
    """退化测试：AC 通过 task_acs 关联 task，不产生虚假的 AC×Task 配对。

    REQ-A 下有 AC-001（关联 TASK-001）、AC-002（关联 TASK-002），
    预期 2 行（AC-001+TASK-001, AC-002+TASK-002），而非 4 行。
    """
    conn = init_in_memory_db()
    load_prd(conn, [{
        "req_id": "REQ-A", "title": "Req A", "priority": "must",
        "category": "functional",
        "acceptance_criteria": [
            {"ac_id": "AC-001", "title": "AC 1", "is_testing_required": True},
            {"ac_id": "AC-002", "title": "AC 2", "is_testing_required": True},
        ],
    }])
    # TASK-001 关联 AC-001，TASK-002 关联 AC-002（彼此错开）
    load_tasks(conn, [
        {"task_id": "TASK-001", "priority": "must", "status": "done",
         "related_requirements": ["REQ-A"],
         "related_acceptance_criteria": ["AC-001"]},
        {"task_id": "TASK-002", "priority": "must", "status": "done",
         "related_requirements": ["REQ-A"],
         "related_acceptance_criteria": ["AC-002"]},
    ])
    res = get_full_chain(conn)
    # 预期 2 行：AC-001+TASK-001, AC-002+TASK-002（无虚假配对）
    assert len(res) == 2, f"Expected 2 rows (correct pairs), got {len(res)}: {res}"
    # 验证配对正确
    pairs = {(r["ac_id"], r["task_id"]) for r in res}
    assert ("AC-001", "TASK-001") in pairs
    assert ("AC-002", "TASK-002") in pairs
    conn.close()

def test_tier2_f4_regression_ac_without_task_visibility():
    """退化测试：AC 可以无 task 关联，仍应可见。

    REQ-A 下有 AC-001 和 AC-002，均无 task 关联，
    预期 2 行（两个 AC 各一行，task_id 均为 NULL）。
    """
    conn = init_in_memory_db()
    load_prd(conn, [{
        "req_id": "REQ-A", "title": "Req A", "priority": "must",
        "category": "functional",
        "acceptance_criteria": [
            {"ac_id": "AC-001", "title": "AC 1", "is_testing_required": True},
            {"ac_id": "AC-002", "title": "AC 2", "is_testing_required": True},
        ],
    }])
    res = get_full_chain(conn)
    assert len(res) == 2, f"Expected 2 AC rows, got {len(res)}"
    ac_ids = {r["ac_id"] for r in res}
    assert ac_ids == {"AC-001", "AC-002"}
    assert all(r["task_id"] is None for r in res)
    conn.close()



# ── Feature 6: Dangling Claims Check (F6) ───────────────────────────────────

def test_tier2_f6_boundary_1_whitespace_ids():
    conn = init_in_memory_db()
    load_tasks(conn, [{"task_id": " TASK-1 ", "priority": "must", "status": "done"}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1"}])
    res = check_dangling_claims(conn)
    assert len(res) == 1
    conn.close()

def test_tier2_f6_boundary_2_multiple_claims_different_missing_tasks():
    conn = init_in_memory_db()
    load_claims(conn, [
        {"claim_id": "CLAIM-1", "related_task": "MISSING-1"},
        {"claim_id": "CLAIM-2", "related_task": "MISSING-2"}
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
    claims = [{"claim_id": f"CLAIM-{i}", "related_task": f"MISSING-{i}"} for i in range(50)]
    load_claims(conn, claims)
    res = check_dangling_claims(conn)
    assert len(res) == 50
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
    # AC 无 task 关联也应被检测到（全量检查）
    ac_res = check_ac_coverage(conn)
    assert len(ac_res) == 1
    assert ac_res[0]["coverage_status"] == "no_task_for_ac"
    conn.close()

def test_tier3_combo_2_overlapping_dangling_and_dead_links():
    conn = init_in_memory_db()
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "NONEXISTENT", "test_refs": ["test_dead"]}])
    res_f6 = check_dangling_claims(conn)
    assert len(res_f6) == 1
    assert res_f6[0]["claim_id"] == "CLAIM-1"
    conn.close()

def test_tier3_combo_3_cascading_test_failure():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "AC 1"}]}])
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_requirements": ["REQ-1"], "related_acceptance_criteria": ["AC-1-1"]}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "test_refs": ["test_1"]}])
    upsert_test_result(conn, "test_1", CoverageStatus.VIOLATED.value, 1, "pytest", False)

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
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "code_refs": ["src/foo.py"]}])
    upsert_coverage_report(conn, "src/foo.py", 45.0, 100, "violated", False)

    res_cov = check_coverage_violations(conn)
    assert len(res_cov) == 1
    assert res_cov[0]["source_path"] == "src/foo.py"
    assert res_cov[0]["carried_over"] is False
    conn.close()

def test_check_coverage_violations_carried_over_field():
    """check_coverage_violations 应返回 carried_over 字段以区分历史与当次违规。"""
    conn = init_in_memory_db()
    upsert_coverage_report(conn, "src/current.py", 45.0, 10, "violated", False)
    upsert_coverage_report(conn, "src/cached.py", 30.0, 5, "violated", True)
    res = check_coverage_violations(conn)
    assert len(res) == 2
    by_path = {r["source_path"]: r for r in res}
    assert by_path["src/current.py"]["carried_over"] is False
    assert by_path["src/cached.py"]["carried_over"] is True
    conn.close()

def test_tier3_combo_5_large_scale_sync():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "AC 1"}]}])
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_requirements": ["REQ-1"], "related_acceptance_criteria": ["AC-1-1"]}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "code_refs": ["src/foo.py"], "test_refs": ["test_1"]}])
    upsert_test_result(conn, "test_1", CoverageStatus.COVERED.value, 0, "pytest", False)
    upsert_coverage_report(conn, "src/foo.py", 95.0, 100, "compliant", False)

    assert len(check_ac_coverage(conn)) == 0
    assert len(check_requirement_coverage(conn)) == 0
    assert len(check_claim_evidence(conn)) == 0
    assert len(check_dangling_claims(conn)) == 0
    assert len(get_full_chain(conn)) == 1
    conn.close()

def test_tier3_combo_7_soft_integrity_violations():
    conn = init_in_memory_db()
    load_claims(conn, [
        {"claim_id": "CLAIM-1", "related_task": "TASK-MISSING-1", "test_refs": ["test_dead_1"]},
        {"claim_id": "CLAIM-2", "related_task": "TASK-MISSING-2", "test_refs": ["test_dead_2"]}
    ])
    assert len(check_dangling_claims(conn)) == 2
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# TIER 4: REAL-WORLD APPLICATION SCENARIOS (5 tests)
# ──────────────────────────────────────────────────────────────────────────────

def test_tier4_scenario_1_new_feature_development():
    conn = init_in_memory_db()
    load_prd(conn, [{"req_id": "REQ-100", "title": "New Auth", "priority": "must", "category": "functional", "acceptance_criteria": []}])
    load_tasks(conn, [{"task_id": "TASK-100", "priority": "must", "status": "in_progress", "related_requirements": ["REQ-100"]}])

    res_f2 = check_requirement_coverage(conn)
    assert len(res_f2) == 0, f"in_progress task should not trigger no_claim_for_task, got: {res_f2}"
    conn.close()

def test_tier4_scenario_3_feature_complete_verification():
    conn = init_in_memory_db()
    load_prd(conn, [MockRequirement("REQ-1", "Auth Feature", "must", "functional", [MockAcceptanceCriteria("AC-1-1", "Login validation", True)])])
    load_tasks(conn, [{"task_id": "TASK-1", "priority": "must", "status": "done", "related_requirements": ["REQ-1"], "related_acceptance_criteria": ["AC-1-1"]}])
    load_claims(conn, [{"claim_id": "CLAIM-1", "related_task": "TASK-1", "code_refs": ["src/login.py"], "test_refs": ["tests/test_login.py::test_valid"]}])
    upsert_test_result(conn, "tests/test_login.py::test_valid", CoverageStatus.COVERED.value, 0, "pytest", False)
    upsert_coverage_report(conn, "src/login.py", 90.0, 50, "compliant", False)

    assert len(check_ac_coverage(conn)) == 0
    assert len(check_requirement_coverage(conn)) == 0
    assert len(check_claim_evidence(conn)) == 0
    assert len(check_dangling_claims(conn)) == 0

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
    upsert_test_result(conn, "tests/test_hotfix.py::test_bug", CoverageStatus.VIOLATED.value, 1, "pytest", False)

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
    upsert_test_result(conn, "tests/test_perf.py::test_speed", CoverageStatus.COVERED.value, 0, "pytest", False)

    assert len(check_requirement_coverage(conn)) == 0

    chain = get_full_chain(conn)
    assert len(chain) == 1
    assert chain[0]["req_id"] == "REQ-Q-1"
    assert chain[0]["req_category"] == "quality_evolution"
    assert chain[0]["task_id"] == "TASK-Q-1"
    assert chain[0]["test_outcome"] == CoverageStatus.COVERED.value
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
    upsert_test_result(conn, "test_pass", CoverageStatus.COVERED.value, 0, "pytest", False)
    upsert_test_result(conn, "test_fail", CoverageStatus.VIOLATED.value, 1, "pytest", False)

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
    upsert_test_result(conn, "test_pass", CoverageStatus.COVERED.value, 0, "pytest", False)

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
    upsert_test_result(conn, "test_pass", CoverageStatus.COVERED.value, 0, "pytest", False)
    
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
        load_initial_cache(conn, cache_dir, tmp_path)
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


def test_adversarial_check_coverage_violations_multiple():
    """
    Test check_coverage_violations under different coverage report statuses.
    """
    conn = init_in_memory_db()
    upsert_coverage_report(conn, "src/violated_1.py", 10.0, 5, "violated", False)
    upsert_coverage_report(conn, "src/compliant.py", 90.0, 20, "compliant", False)
    upsert_coverage_report(conn, "src/violated_2.py", 50.0, 8, "violated", False)

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
    upsert_test_result(conn, "tests/test_a.py::test_1", CoverageStatus.COVERED.value, 0, "pytest", True)
    upsert_test_result(conn, "tests/test_b.py::test_2", CoverageStatus.COVERED.value, 0, "pytest", True)

    # Purge stale cache with a wildcard pattern
    purge_stale_cache(conn, ["tests/test_%.py"])

    # If '%' is treated as a wildcard in LIKE 'tests/test_%.py::%', both test results will be purged!
    rows = conn.execute("SELECT nodeid FROM test_results WHERE carried_over = 1").fetchall()
    assert len(rows) == 0, "Wildcard in filename caused unintended cache purging"
    conn.close()


def test_adversarial_load_initial_cache_missing_source_path(tmp_path):
    """
    Edge case: load_initial_cache resolves source_path relative to project_root.
    When source file exists at that level the record is loaded; when absent it is skipped.
    """
    import json
    conn = init_in_memory_db()
    cache_dir = tmp_path / "output" / "evidences"
    cache_dir.mkdir(parents=True)

    # Create a source file that DOES exist at parent.parent level
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    existing_file = source_dir / "existing_file.py"
    existing_file.write_text("# test")

    # Write coverage_reports.json with both existing and missing source paths
    cov_data = [
        {"source_path": "src/existing_file.py", "percent_covered": 80.0, "num_statements": 10, "status": "compliant"},
        {"source_path": "src/missing_file.py", "percent_covered": 50.0, "num_statements": 5, "status": "violated"},
    ]
    (cache_dir / "coverage_reports.json").write_text(json.dumps(cov_data))

    load_initial_cache(conn, cache_dir, tmp_path)

    rows = conn.execute("SELECT source_path FROM coverage_reports ORDER BY source_path").fetchall()
    # Only the existing file should be loaded; missing file is skipped
    assert len(rows) == 1, f"Expected 1 coverage report, got: {rows}"
    assert rows[0][0] == "src/existing_file.py"
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


# ── Invalid Task References Checks ──────────────────────────────────────────

def test_check_invalid_task_requirements():
    """Test that check_invalid_task_requirements detects tasks referencing non-existent requirements."""
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": []}]})
    load_tasks(conn, [
        {"task_id": "TASK-1", "priority": "must", "status": "done", "related_requirements": ["REQ-1"]},
        {"task_id": "TASK-2", "priority": "must", "status": "done", "related_requirements": ["REQ-999"]},
    ])
    res = check_invalid_task_requirements(conn)
    assert len(res) == 1
    assert res[0]["task_id"] == "TASK-2"
    assert res[0]["req_id"] == "REQ-999"
    conn.close()


def test_check_invalid_task_acs():
    """Test that check_invalid_task_acs detects tasks referencing non-existent ACs."""
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "AC 1", "is_testing_required": True}]}]})
    load_tasks(conn, [
        {"task_id": "TASK-1", "priority": "must", "status": "done", "related_acceptance_criteria": ["AC-1-1"]},
        {"task_id": "TASK-2", "priority": "must", "status": "done", "related_acceptance_criteria": ["AC-999"]},
    ])
    res = check_invalid_task_acs(conn)
    assert len(res) == 1
    assert res[0]["task_id"] == "TASK-2"
    assert res[0]["ac_id"] == "AC-999"
    conn.close()


def test_check_invalid_task_modules():
    """Test that check_invalid_task_modules detects tasks referencing non-existent modules."""
    conn = init_in_memory_db()
    load_architecture_constraints(conn, {"module_boundaries": [{"module_id": "MOD-1"}]})
    load_tasks(conn, [
        {"task_id": "TASK-1", "priority": "must", "status": "done", "related_modules": ["MOD-1"]},
        {"task_id": "TASK-2", "priority": "must", "status": "done", "related_modules": ["MOD-999"]},
    ])
    res = check_invalid_task_modules(conn)
    assert len(res) == 1
    assert res[0]["task_id"] == "TASK-2"
    assert res[0]["module_id"] == "MOD-999"
    conn.close()


def test_check_invalid_task_constraints():
    """Test that check_invalid_task_constraints detects tasks referencing non-existent constraints."""
    conn = init_in_memory_db()
    load_architecture_constraints(conn, {"architecture_principles": [{"principle_id": "PRINCIPLE-1"}]})
    load_tasks(conn, [
        {"task_id": "TASK-1", "priority": "must", "status": "done", "related_architecture_constraints": ["PRINCIPLE-1"]},
        {"task_id": "TASK-2", "priority": "must", "status": "done", "related_architecture_constraints": ["PRINCIPLE-999"]},
    ])
    res = check_invalid_task_constraints(conn)
    assert len(res) == 1
    assert res[0]["task_id"] == "TASK-2"
    assert res[0]["constraint_id"] == "PRINCIPLE-999"
    conn.close()


def test_check_invalid_ac_parent():
    """Test that check_invalid_ac_parent detects tasks referencing ACs without parent requirement."""
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-1", "title": "Req 1", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "AC 1", "is_testing_required": True}]}]})
    load_tasks(conn, [
        {"task_id": "TASK-1", "priority": "must", "status": "done", "related_requirements": ["REQ-1"], "related_acceptance_criteria": ["AC-1-1"]},
        {"task_id": "TASK-2", "priority": "must", "status": "done", "related_requirements": ["REQ-2"], "related_acceptance_criteria": ["AC-1-1"]},
    ])
    res = check_invalid_ac_parent(conn)
    assert len(res) == 1
    assert res[0]["task_id"] == "TASK-2"
    assert res[0]["ac_id"] == "AC-1-1"
    assert res[0]["parent_req_id"] == "REQ-1"
    conn.close()


# ── check_isolated_tasks ────────────────────────────────────────────────────

def test_check_isolated_tasks_no_links():
    """Task with no requirements and no ACs is detected as isolated."""
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-1", "title": "Req", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "AC", "is_testing_required": True}]}]})
    load_tasks(conn, [
        {"task_id": "TASK-1", "priority": "must", "status": "todo", "related_requirements": [], "related_acceptance_criteria": []},
    ])
    res = check_isolated_tasks(conn, strict_link=False)
    assert len(res) == 1
    assert res[0]["task_id"] == "TASK-1"
    conn.close()


def test_check_isolated_tasks_with_req_pass():
    """Task with requirements but no ACs passes in OR mode (strict_link=False)."""
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-1", "title": "Req", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "AC", "is_testing_required": True}]}]})
    load_tasks(conn, [
        {"task_id": "TASK-1", "priority": "must", "status": "todo", "related_requirements": ["REQ-1"], "related_acceptance_criteria": []},
    ])
    res = check_isolated_tasks(conn, strict_link=False)
    assert len(res) == 0
    conn.close()


def test_check_isolated_tasks_with_ac_pass():
    """Task with ACs but no requirements passes in OR mode (strict_link=False)."""
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-1", "title": "Req", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "AC", "is_testing_required": True}]}]})
    load_tasks(conn, [
        {"task_id": "TASK-1", "priority": "must", "status": "todo", "related_requirements": [], "related_acceptance_criteria": ["AC-1-1"]},
    ])
    res = check_isolated_tasks(conn, strict_link=False)
    assert len(res) == 0
    conn.close()


def test_check_isolated_tasks_strict_link():
    """Task with only REQ but no AC is detected in AND mode (strict_link=True)."""
    conn = init_in_memory_db()
    load_prd(conn, {"requirements": [{"req_id": "REQ-1", "title": "Req", "priority": "must", "category": "functional", "acceptance_criteria": [{"ac_id": "AC-1-1", "title": "AC", "is_testing_required": True}]}]})
    load_tasks(conn, [
        {"task_id": "TASK-1", "priority": "must", "status": "todo", "related_requirements": ["REQ-1"], "related_acceptance_criteria": []},
    ])
    res = check_isolated_tasks(conn, strict_link=True)
    assert len(res) == 1
    assert res[0]["task_id"] == "TASK-1"
    conn.close()


def test_check_isolated_tasks_empty_db():
    """Empty database returns empty list."""
    conn = init_in_memory_db()
    res = check_isolated_tasks(conn, strict_link=False)
    assert len(res) == 0
    conn.close()


