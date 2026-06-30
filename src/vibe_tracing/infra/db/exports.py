"""
VT 内存数据库数据操作模块（UPSERT、缓存清理）
"""

import sqlite3


def upsert_test_result(
    conn: sqlite3.Connection,
    nodeid: str,
    outcome: str,
    exit_code: int,
    command: str,
    carried_over: bool,
) -> None:
    """插入或替换单条测试结果。"""
    conn.execute(
        "INSERT OR REPLACE INTO test_results "
        "(nodeid, outcome, exit_code, command, carried_over) "
        "VALUES (?, ?, ?, ?, ?)",
        (nodeid, outcome, exit_code, command, int(carried_over)),
    )
    conn.commit()


def upsert_coverage_report(
    conn: sqlite3.Connection,
    source_path: str,
    percent_covered: float,
    num_statements: int,
    status: str,
    carried_over: bool,
) -> None:
    """插入或替换单条覆盖率报告。"""
    conn.execute(
        "INSERT OR REPLACE INTO coverage_reports "
        "(source_path, percent_covered, num_statements, status, carried_over) "
        "VALUES (?, ?, ?, ?, ?)",
        (source_path, percent_covered, num_statements, status, int(carried_over)),
    )
    conn.commit()


def purge_stale_cache(conn: sqlite3.Connection, target_files: list) -> None:
    """清除目标文件对应的陈旧缓存记录。"""
    for f in target_files:
        conn.execute(
            "DELETE FROM test_results "
            "WHERE (nodeid LIKE ? OR nodeid = ?) AND carried_over = 1",
            (f"{f}::%", f),
        )
        conn.execute(
            "DELETE FROM coverage_reports "
            "WHERE source_path = ? AND carried_over = 1",
            (f,),
        )
    conn.commit()


