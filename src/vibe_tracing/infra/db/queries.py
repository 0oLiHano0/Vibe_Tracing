"""
VT 内存数据库查询与校验模块
"""

import sqlite3


def check_coverage_violations(conn: sqlite3.Connection) -> list:
    """检查覆盖率违规：返回所有 status='violated' 的覆盖率记录。"""
    rows = conn.execute(
        "SELECT source_path, percent_covered FROM coverage_reports "
        "WHERE status = 'violated'"
    ).fetchall()
    return [{"source_path": r[0], "percent_covered": r[1]} for r in rows]


def check_ghost_code(conn: sqlite3.Connection) -> list:
    """检查幽灵代码：返回暂存区中未被任何 Claim 关联的文件。"""
    rows = conn.execute("""
        SELECT sf.file_path FROM staged_files sf
        LEFT JOIN claim_code_refs ccr ON sf.file_path = ccr.code_path
        LEFT JOIN claims c ON ccr.claim_id = c.claim_id
        LEFT JOIN tasks t ON c.related_task = t.task_id
        WHERE ccr.code_path IS NULL
    """).fetchall()
    return [r[0] for r in rows]


def check_dangling_claims(conn: sqlite3.Connection) -> list:
    """检查悬空声明：返回指向不存在 Task 的 Claim。"""
    rows = conn.execute("""
        SELECT c.claim_id, c.related_task FROM claims c
        LEFT JOIN tasks t ON c.related_task = t.task_id
        WHERE t.task_id IS NULL
    """).fetchall()
    return [{"claim_id": r[0], "related_task": r[1]} for r in rows]


def check_ac_coverage(conn: sqlite3.Connection) -> list:
    """检查 MUST 优先级任务/验收标准的覆盖情况。"""
    rows = conn.execute("""
        SELECT ta.task_id, ac.ac_id,
          CASE
            WHEN ta.task_id IS NULL THEN 'no_task_for_ac'
            WHEN c.claim_id IS NULL THEN 'no_claim_for_task'
            WHEN COUNT(ctr.test_nodeid) = 0 THEN 'no_tests_declared'
            WHEN SUM(CASE WHEN tr.nodeid IS NULL THEN 1 ELSE 0 END) > 0 THEN 'test_not_run'
            WHEN SUM(CASE WHEN tr.outcome != 'passed' THEN 1 ELSE 0 END) > 0 THEN 'test_failed'
            ELSE 'covered'
          END as coverage_status
        FROM acceptance_criteria ac
        LEFT JOIN requirements r ON ac.req_id = r.req_id
        LEFT JOIN task_acs ta ON ac.ac_id = ta.ac_id
        LEFT JOIN tasks t ON ta.task_id = t.task_id
        LEFT JOIN claims c ON t.task_id = c.related_task
        LEFT JOIN claim_test_refs ctr ON c.claim_id = ctr.claim_id
        LEFT JOIN test_results tr ON ctr.test_nodeid = tr.nodeid
        WHERE t.priority = 'must' OR (r.priority = 'must' AND ac.is_testing_required = 1)
        GROUP BY ta.task_id, ac.ac_id
        HAVING coverage_status != 'covered'
    """).fetchall()

    return [
        {"task_id": r[0], "ac_id": r[1], "coverage_status": r[2]}
        for r in rows
    ]


def check_requirement_coverage(conn: sqlite3.Connection) -> list:
    """检查需求覆盖率。"""
    rows = conn.execute("""
        SELECT r.req_id,
          CASE
            WHEN trq.task_id IS NULL THEN 'no_task_for_requirement'
            WHEN c.claim_id IS NULL THEN 'no_claim_for_task'
            WHEN COUNT(ctr.test_nodeid) = 0 THEN 'no_tests_declared'
            WHEN SUM(CASE WHEN tr.nodeid IS NULL THEN 1 ELSE 0 END) > 0 THEN 'test_not_run'
            WHEN SUM(CASE WHEN tr.outcome != 'passed' THEN 1 ELSE 0 END) > 0 THEN 'test_failed'
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


def check_claim_evidence(conn: sqlite3.Connection) -> list:
    """检查 Claim 证据覆盖状态。"""
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


def get_full_chain(conn: sqlite3.Connection) -> list:
    """获取需求到测试/覆盖率的全链路追踪视图。"""
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


def query_related_code(conn: sqlite3.Connection, ac_id: str) -> list:
    """查询与 AC 关联的代码文件路径（通过 task_acs → claims → claim_code_refs 链路）。

    返回路径列表（最多 3 个），仅返回文件系统中实际存在的路径。
    """
    cursor = conn.execute("""
        SELECT DISTINCT ccr.code_path
        FROM task_acs ta
        JOIN claims c ON c.related_task = ta.task_id
        JOIN claim_code_refs ccr ON ccr.claim_id = c.claim_id
        WHERE ta.ac_id = ?
    """, (ac_id,))
    from pathlib import Path
    return [r[0] for r in cursor.fetchall() if Path(r[0]).exists()][:3]


def query_existing_tests(conn: sqlite3.Connection, ac_id: str) -> list:
    """查询与 AC 关联的测试 nodeid（通过 task_acs → claims → claim_test_refs 链路）。

    返回 nodeid 列表（最多 2 个）。
    """
    cursor = conn.execute("""
        SELECT DISTINCT ctr.test_nodeid
        FROM task_acs ta
        JOIN claims c ON c.related_task = ta.task_id
        JOIN claim_test_refs ctr ON ctr.claim_id = c.claim_id
        WHERE ta.ac_id = ?
    """, (ac_id,))
    return [r[0] for r in cursor.fetchall()][:2]


def check_invalid_task_requirements(conn: sqlite3.Connection) -> list:
    """检查 Task 引用的 Requirement 是否存在。"""
    rows = conn.execute("""
        SELECT tr.task_id, tr.req_id
        FROM task_requirements tr
        LEFT JOIN requirements r ON tr.req_id = r.req_id
        WHERE r.req_id IS NULL
    """).fetchall()
    return [{"task_id": r[0], "req_id": r[1]} for r in rows]


def check_invalid_task_acs(conn: sqlite3.Connection) -> list:
    """检查 Task 引用的 AC 是否存在。"""
    rows = conn.execute("""
        SELECT ta.task_id, ta.ac_id
        FROM task_acs ta
        LEFT JOIN acceptance_criteria ac ON ta.ac_id = ac.ac_id
        WHERE ac.ac_id IS NULL
    """).fetchall()
    return [{"task_id": r[0], "ac_id": r[1]} for r in rows]


def check_invalid_task_modules(conn: sqlite3.Connection) -> list:
    """检查 Task 引用的 Module 是否存在。"""
    rows = conn.execute("""
        SELECT tm.task_id, tm.module_id
        FROM task_modules tm
        LEFT JOIN arch_modules am ON tm.module_id = am.module_id
        WHERE am.module_id IS NULL
    """).fetchall()
    return [{"task_id": r[0], "module_id": r[1]} for r in rows]


def check_invalid_task_constraints(conn: sqlite3.Connection) -> list:
    """检查 Task 引用的 Constraint 是否存在。"""
    rows = conn.execute("""
        SELECT tc.task_id, tc.constraint_id
        FROM task_constraints tc
        LEFT JOIN arch_constraints ac ON tc.constraint_id = ac.constraint_id
        WHERE ac.constraint_id IS NULL
    """).fetchall()
    return [{"task_id": r[0], "constraint_id": r[1]} for r in rows]


def check_invalid_ac_parent(conn: sqlite3.Connection) -> list:
    """检查 Task 引用的 AC 其父 Requirement 是否在 Task 的关联需求中。"""
    rows = conn.execute("""
        SELECT ta.task_id, ta.ac_id, ac.req_id
        FROM task_acs ta
        JOIN acceptance_criteria ac ON ta.ac_id = ac.ac_id
        LEFT JOIN task_requirements tr ON ta.task_id = tr.task_id AND ac.req_id = tr.req_id
        WHERE tr.req_id IS NULL
    """).fetchall()
    return [{"task_id": r[0], "ac_id": r[1], "parent_req_id": r[2]} for r in rows]

def check_isolated_tasks(conn: sqlite3.Connection, strict_link: bool) -> list:
    """检查孤立任务（无 REQ 或 无 AC 的情况，具体取决于 strict_link 配置）。"""
    if strict_link:
        query = """
            SELECT t.task_id, 
                   CASE 
                     WHEN COUNT(tr.req_id) = 0 THEN 'missing_req'
                     WHEN COUNT(ta.ac_id) = 0 THEN 'missing_ac'
                   END as reason
            FROM tasks t
            LEFT JOIN task_requirements tr ON t.task_id = tr.task_id
            LEFT JOIN task_acs ta ON t.task_id = ta.task_id
            GROUP BY t.task_id
            HAVING COUNT(tr.req_id) = 0 OR COUNT(ta.ac_id) = 0
        """
    else:
        query = """
            SELECT t.task_id, 'isolated' as reason
            FROM tasks t
            LEFT JOIN task_requirements tr ON t.task_id = tr.task_id
            LEFT JOIN task_acs ta ON t.task_id = ta.task_id
            GROUP BY t.task_id
            HAVING COUNT(tr.req_id) = 0 AND COUNT(ta.ac_id) = 0
        """
    rows = conn.execute(query).fetchall()
    return [{"task_id": r[0], "reason": r[1]} for r in rows]

def check_architectural_orphans(conn: sqlite3.Connection) -> list:
    """检查架构孤儿任务（状态不为 done 且未关联任何模块）。"""
    rows = conn.execute("""
        SELECT t.task_id, 'architectural_orphan' as reason
        FROM tasks t
        LEFT JOIN task_modules tm ON t.task_id = tm.task_id
        WHERE t.status != 'done'
        GROUP BY t.task_id
        HAVING COUNT(tm.module_id) = 0
    """).fetchall()
    return [{"task_id": r[0], "reason": r[1]} for r in rows]
