"""
VT 内存数据库 Schema 定义
"""

import sqlite3


def init_in_memory_db() -> sqlite3.Connection:
    """创建内存 SQLite 数据库并建表。

    包括 8 张原始表和 2 张新增需求/验收标准关联表。
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")

    conn.executescript("""
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY,
            priority TEXT NOT NULL,
            status   TEXT NOT NULL
        );
        CREATE TABLE task_requirements (
            task_id TEXT,
            req_id TEXT,
            PRIMARY KEY (task_id, req_id)
        );
        CREATE TABLE task_acs (
            task_id TEXT,
            ac_id   TEXT,
            PRIMARY KEY (task_id, ac_id)
        );
        CREATE TABLE claims (
            claim_id     TEXT PRIMARY KEY,
            related_task TEXT NOT NULL
        );
        CREATE TABLE claim_code_refs (
            claim_id  TEXT,
            code_path TEXT,
            PRIMARY KEY (claim_id, code_path)
        );
        CREATE TABLE claim_test_refs (
            claim_id     TEXT,
            test_nodeid  TEXT,
            PRIMARY KEY (claim_id, test_nodeid)
        );
        CREATE TABLE test_results (
            nodeid       TEXT PRIMARY KEY,
            outcome      TEXT NOT NULL,
            exit_code    INTEGER NOT NULL,
            command      TEXT,
            carried_over INTEGER DEFAULT 0
        );
        CREATE TABLE coverage_reports (
            source_path      TEXT PRIMARY KEY,
            percent_covered  REAL NOT NULL,
            num_statements   INTEGER,
            status           TEXT NOT NULL,
            carried_over    INTEGER DEFAULT 0
        );
        CREATE TABLE staged_files (
            file_path TEXT PRIMARY KEY
        );
        CREATE TABLE requirements (
            req_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            priority TEXT NOT NULL,
            category TEXT NOT NULL
        );
        CREATE TABLE acceptance_criteria (
            ac_id TEXT PRIMARY KEY,
            req_id TEXT NOT NULL,
            title TEXT NOT NULL,
            is_testing_required INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS arch_modules (
            module_id TEXT PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS arch_constraints (
            constraint_id TEXT PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS task_modules (
            task_id TEXT,
            module_id TEXT,
            PRIMARY KEY (task_id, module_id)
        );
        CREATE TABLE IF NOT EXISTS task_constraints (
            task_id TEXT,
            constraint_id TEXT,
            PRIMARY KEY (task_id, constraint_id)
        );
    """)
    return conn
