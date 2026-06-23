"""
VT 内存数据库数据导出与持久化模块
"""

import json
import sqlite3
from pathlib import Path


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


def _export_test_results(conn: sqlite3.Connection) -> list:
    """内部函数：将 test_results 表全部记录导出为字典列表。"""
    rows = conn.execute("SELECT * FROM test_results").fetchall()
    columns = [d[1] for d in conn.execute("PRAGMA table_info(test_results)").fetchall()]
    return [dict(zip(columns, row)) for row in rows]


def _export_coverage_reports(conn: sqlite3.Connection) -> list:
    """内部函数：将 coverage_reports 表全部记录导出为字典列表。"""
    rows = conn.execute("SELECT * FROM coverage_reports").fetchall()
    columns = [d[1] for d in conn.execute("PRAGMA table_info(coverage_reports)").fetchall()]
    return [dict(zip(columns, row)) for row in rows]


def persist_evidences(conn: sqlite3.Connection, output_dir: str) -> None:
    """将数据库中的测试和覆盖率数据导出为 JSON 文件。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    test_data = _export_test_results(conn)
    with open(str(out / "test_results.json"), "w") as fh:
        json.dump(test_data, fh, indent=2, ensure_ascii=False)

    cov_data = _export_coverage_reports(conn)
    with open(str(out / "coverage_reports.json"), "w") as fh:
        json.dump(cov_data, fh, indent=2, ensure_ascii=False)
