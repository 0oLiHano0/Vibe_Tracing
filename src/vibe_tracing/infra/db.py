"""
Vibe Tracing — in-memory SQLite management module.

Phase 1 refactoring: zero-dependency leaf module.
Only imports from the Python standard library.
"""

import json
import sqlite3
from pathlib import Path


# ── Helpers ──────────────────────────────────────────────────────────────────

def _coerce_strlist(val) -> list:
    """Normalise a value to a list of strings."""
    if isinstance(val, list):
        return [str(x) for x in val]
    if val is None:
        return []
    return [str(val)]


# ── 1. Database initialisation ──────────────────────────────────────────────

def init_in_memory_db() -> sqlite3.Connection:
    """Create :memory: SQLite database, execute all DDL, return connection."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")

    conn.executescript("""
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY,
            priority TEXT NOT NULL,
            status   TEXT NOT NULL
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
    """)
    return conn


# ── 2. Data loaders (write) ─────────────────────────────────────────────────

def load_tasks(conn: sqlite3.Connection, tasks: list) -> None:
    """Bulk-load tasks into the database.

    前置条件：数据已通过 validation/checks.py 的格式校验。
    仅执行 INSERT，不进行格式校验。
    """
    for task in tasks:
        conn.execute(
            "INSERT OR REPLACE INTO tasks (task_id, priority, status) VALUES (?, ?, ?)",
            (task["task_id"], task["priority"], task["status"]),
        )
        for ac in _coerce_strlist(task.get("related_acceptance_criteria", [])):
            conn.execute(
                "INSERT OR REPLACE INTO task_acs (task_id, ac_id) VALUES (?, ?)",
                (task["task_id"], ac),
            )
    conn.commit()


def load_claims(conn: sqlite3.Connection, claims: list) -> None:
    """Bulk-load claims into the database.

    前置条件：数据已通过 validation/checks.py 的格式校验。
    仅执行 INSERT，不进行格式校验。
    """
    for claim in claims:
        conn.execute(
            "INSERT OR REPLACE INTO claims (claim_id, related_task) VALUES (?, ?)",
            (claim["claim_id"], claim["related_task"]),
        )
        for ref in _coerce_strlist(claim.get("code_refs", [])):
            if not ref:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO claim_code_refs (claim_id, code_path) VALUES (?, ?)",
                (claim["claim_id"], ref),
            )
        for ref in _coerce_strlist(claim.get("test_refs", [])):
            if not ref:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO claim_test_refs (claim_id, test_nodeid) VALUES (?, ?)",
                (claim["claim_id"], ref),
            )
    conn.commit()


def load_staged_files(conn: sqlite3.Connection, files: set) -> list:
    """Insert *files* into the ``staged_files`` table.

    Returns a list of the file paths that were inserted.
    """
    inserted: list = []
    for f in files:
        conn.execute(
            "INSERT OR REPLACE INTO staged_files (file_path) VALUES (?)",
            (f,),
        )
        inserted.append(f)
    conn.commit()
    return inserted


def load_initial_cache(conn: sqlite3.Connection, cache_dir: str) -> None:
    """Load persisted test / coverage results from *cache_dir*.

    Looks for ``test_results.json`` and ``coverage_reports.json``.
    Every record receives ``carried_over = 1``.
    Records whose source file no longer exists on disk are silently skipped.
    """
    cache_path = Path(cache_dir)

    test_file = cache_path / "test_results.json"
    if test_file.is_file():
        with open(str(test_file), "r") as fh:
            records = json.load(fh)
        for rec in records:
            nodeid = rec.get("nodeid", "")
            outcome = rec.get("outcome", "failed")
            exit_code = rec.get("exit_code", -1)
            command = rec.get("command")
            conn.execute(
                "INSERT OR REPLACE INTO test_results "
                "(nodeid, outcome, exit_code, command, carried_over) "
                "VALUES (?, ?, ?, ?, 1)",
                (nodeid, outcome, exit_code, command),
            )
        conn.commit()

    cov_file = cache_path / "coverage_reports.json"
    if cov_file.is_file():
        with open(str(cov_file), "r") as fh:
            records = json.load(fh)
        for rec in records:
            source_path = rec.get("source_path", "")
            # Skip if the source file no longer exists on disk.
            if source_path and not (cache_path.parent / source_path).is_file():
                continue
            percent_covered = rec.get("percent_covered", 0.0)
            num_statements = rec.get("num_statements")
            status = rec.get("status", "violated")
            conn.execute(
                "INSERT OR REPLACE INTO coverage_reports "
                "(source_path, percent_covered, num_statements, status, carried_over) "
                "VALUES (?, ?, ?, ?, 1)",
                (source_path, percent_covered, num_statements, status),
            )
        conn.commit()


def upsert_test_result(
    conn: sqlite3.Connection,
    nodeid: str,
    outcome: str,
    exit_code: int,
    command: str,
    carried_over: bool,
) -> None:
    """Insert or replace a single test-result row."""
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
    """Insert or replace a single coverage-report row."""
    conn.execute(
        "INSERT OR REPLACE INTO coverage_reports "
        "(source_path, percent_covered, num_statements, status, carried_over) "
        "VALUES (?, ?, ?, ?, ?)",
        (source_path, percent_covered, num_statements, status, int(carried_over)),
    )
    conn.commit()


# ── 4. Cache cleanup ───────────────────────────────────────────────────────

def purge_stale_cache(conn: sqlite3.Connection, target_files: list) -> None:
    """Remove carried-over cache records for files that were re-run.

    For every file path *f* in *target_files*:

    - ``DELETE FROM test_results WHERE (nodeid LIKE 'f::%' OR nodeid = 'f')
      AND carried_over = 1``
    - ``DELETE FROM coverage_reports WHERE source_path = 'f' AND carried_over = 1``
    """
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


# ── 5. Relation validation (Layer 2) — 6 SQL query functions ────────────────

def check_ac_coverage(conn: sqlite3.Connection) -> list:
    """MUST-priority AC coverage check.

    Returns uncovered MUST ACs as dicts with keys
    ``task_id``, ``ac_id``, ``coverage_status``.
    """
    rows = conn.execute("""
        SELECT ta.task_id, ta.ac_id,
          CASE
            WHEN c.claim_id IS NULL THEN 'no_claim_for_task'
            WHEN ctr.test_nodeid IS NULL THEN 'no_tests_declared'
            WHEN tr.nodeid IS NULL THEN 'test_not_run'
            WHEN SUM(tr.outcome = 'passed') = 0 THEN 'test_failed'
            ELSE 'covered'
          END as coverage_status
        FROM task_acs ta
        JOIN tasks t ON ta.task_id = t.task_id
        LEFT JOIN claims c ON t.task_id = c.related_task
        LEFT JOIN claim_test_refs ctr ON c.claim_id = ctr.claim_id
        LEFT JOIN test_results tr ON ctr.test_nodeid = tr.nodeid
        WHERE t.priority = 'must'
        GROUP BY ta.task_id, ta.ac_id
        HAVING coverage_status != 'covered'
    """).fetchall()
    return [
        {"task_id": r[0], "ac_id": r[1], "coverage_status": r[2]}
        for r in rows
    ]


def check_coverage_violations(conn: sqlite3.Connection) -> list:
    """Return coverage-reports whose status is ``violated``."""
    rows = conn.execute(
        "SELECT source_path, percent_covered FROM coverage_reports "
        "WHERE status = 'violated'"
    ).fetchall()
    return [{"source_path": r[0], "percent_covered": r[1]} for r in rows]


def check_ghost_code(conn: sqlite3.Connection) -> list:
    """Return staged file paths not covered by any claim code_ref."""
    rows = conn.execute("""
        SELECT sf.file_path FROM staged_files sf
        LEFT JOIN claim_code_refs ccr ON sf.file_path = ccr.code_path
        LEFT JOIN claims c ON ccr.claim_id = c.claim_id
        LEFT JOIN tasks t ON c.related_task = t.task_id
        WHERE ccr.code_path IS NULL
    """).fetchall()
    return [r[0] for r in rows]


def check_dangling_claims(conn: sqlite3.Connection) -> list:
    """Return claims whose ``related_task`` does not exist in the tasks table."""
    rows = conn.execute("""
        SELECT c.claim_id, c.related_task FROM claims c
        LEFT JOIN tasks t ON c.related_task = t.task_id
        WHERE t.task_id IS NULL
    """).fetchall()
    return [{"claim_id": r[0], "related_task": r[1]} for r in rows]


def check_test_dead_links(conn: sqlite3.Connection) -> list:
    """Return test refs whose nodeid does not exist in test_results or has
    a non-passed outcome."""
    rows = conn.execute("""
        SELECT ctr.claim_id, ctr.test_nodeid FROM claim_test_refs ctr
        LEFT JOIN test_results tr ON ctr.test_nodeid = tr.nodeid
        WHERE tr.nodeid IS NULL OR tr.outcome != 'passed'
    """).fetchall()
    return [{"claim_id": r[0], "test_nodeid": r[1]} for r in rows]


def check_active_task_coverage(conn: sqlite3.Connection) -> list:
    """For active (``in_progress``) tasks, return code paths that are not
    covered by a compliant coverage report."""
    rows = conn.execute("""
        SELECT ccr.code_path, cr.percent_covered, cr.status
        FROM claim_code_refs ccr
        JOIN claims c ON ccr.claim_id = c.claim_id
        JOIN tasks t ON c.related_task = t.task_id
        LEFT JOIN coverage_reports cr ON ccr.code_path = cr.source_path
        WHERE t.status = 'in_progress'
          AND (cr.source_path IS NULL OR cr.status = 'violated')
    """).fetchall()
    return [
        {"code_path": r[0], "percent_covered": r[1], "status": r[2]}
        for r in rows
    ]


# ── 6. Export ───────────────────────────────────────────────────────────────

def export_test_results(conn: sqlite3.Connection) -> list:
    """Export all test_results rows as a list of dicts."""
    rows = conn.execute("SELECT * FROM test_results").fetchall()
    columns = [d[1] for d in conn.execute("PRAGMA table_info(test_results)").fetchall()]
    return [dict(zip(columns, row)) for row in rows]


def export_coverage_reports(conn: sqlite3.Connection) -> list:
    """Export all coverage_reports rows as a list of dicts."""
    rows = conn.execute("SELECT * FROM coverage_reports").fetchall()
    columns = [d[1] for d in conn.execute("PRAGMA table_info(coverage_reports)").fetchall()]
    return [dict(zip(columns, row)) for row in rows]


def persist_evidences(conn: sqlite3.Connection, output_dir: str) -> None:
    """Write ``test_results.json`` and ``coverage_reports.json`` into *output_dir*."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    test_data = export_test_results(conn)
    with open(str(out / "test_results.json"), "w") as fh:
        json.dump(test_data, fh, indent=2, ensure_ascii=False)

    cov_data = export_coverage_reports(conn)
    with open(str(out / "coverage_reports.json"), "w") as fh:
        json.dump(cov_data, fh, indent=2, ensure_ascii=False)
