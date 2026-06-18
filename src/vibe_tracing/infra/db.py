"""
Vibe Tracing — in-memory SQLite management module.

Phase 1 refactoring: zero-dependency leaf module.
Only imports from the Python standard library.
"""

import json
import re
import sqlite3
from pathlib import Path
from typing import List


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


# ── 2. Format validation (Layer 1) ──────────────────────────────────────────

# Compiled patterns for reuse.
_RE_TASK = re.compile(r"^TASK-[A-Z]+-\d{3,4}$")
_RE_CLAIM = re.compile(r"^CLAIM-[A-Z]+-\d{3,4}$")


def validate_task(task: dict) -> List[str]:
    """Validate a single task dict.

    Rules:
      - *task_id* must match ``TASK-[A-Z]+-\d{3,4}``
      - *priority* is one of ``must``, ``should``, ``could``
      - *status* is one of ``todo``, ``in_progress``, ``done``, ``blocked``
    Returns a list of error strings (empty means valid).
    """
    errors: List[str] = []

    task_id = task.get("task_id", "")
    if not isinstance(task_id, str) or not _RE_TASK.match(task_id):
        errors.append(f"task_id {task_id!r}: must match TASK-[A-Z]+-\\d{{3,4}}")

    priority = task.get("priority", "")
    if priority not in ("must", "should", "could"):
        errors.append(f"priority {priority!r}: must be must|should|could")

    status = task.get("status", "")
    if status not in ("todo", "in_progress", "done", "blocked"):
        errors.append(f"status {status!r}: must be todo|in_progress|done|blocked")

    return errors


def validate_claim(claim: dict) -> List[str]:
    """Validate a single claim dict.

    Rules:
      - *claim_id* must match ``CLAIM-[A-Z]+-\d{3,4}``
      - *related_task* must match ``TASK-[A-Z]+-\d{3,4}``
      - *code_refs* / *test_refs* paths must not contain ``..`` traversal and
        must not be absolute paths.
    Returns a list of error strings.
    """
    errors: List[str] = []

    claim_id = claim.get("claim_id", "")
    if not isinstance(claim_id, str) or not _RE_CLAIM.match(claim_id):
        errors.append(f"claim_id {claim_id!r}: must match CLAIM-[A-Z]+-\\d{{3,4}}")

    related_task = claim.get("related_task", "")
    if not isinstance(related_task, str) or not _RE_TASK.match(related_task):
        errors.append(
            f"related_task {related_task!r}: must match TASK-[A-Z]+-\\d{{3,4}}"
        )

    for key, refs in (("code_refs", _coerce_strlist(claim.get("code_refs"))),
                      ("test_refs", _coerce_strlist(claim.get("test_refs")))):
        for ref in refs:
            if not isinstance(ref, str):
                errors.append(f"{key} item {ref!r}: must be a string")
                continue
            if ref.startswith("/"):
                errors.append(f"{key} {ref!r}: absolute paths not allowed")
            if ".." in ref.split("/"):
                errors.append(f"{key} {ref!r}: parent-directory traversal (..) not allowed")

    return errors


def validate_test_result(entry: dict) -> List[str]:
    """Validate a single test result entry.

    Rules:
      - *nodeid* is non-empty and contains ``::``
      - *outcome* is one of ``passed``, ``failed``, ``skipped``
      - *exit_code* >= 0
    """
    errors: List[str] = []

    nodeid = entry.get("nodeid", "")
    if not isinstance(nodeid, str) or not nodeid or "::" not in nodeid:
        errors.append(f"nodeid {nodeid!r}: must be non-empty and contain '::'")

    outcome = entry.get("outcome", "")
    if outcome not in ("passed", "failed", "skipped"):
        errors.append(f"outcome {outcome!r}: must be passed|failed|skipped")

    exit_code = entry.get("exit_code", -1)
    if not isinstance(exit_code, int) or exit_code < 0:
        errors.append(f"exit_code {exit_code!r}: must be >= 0")

    return errors


def validate_coverage_report(entry: dict) -> List[str]:
    """Validate a single coverage report entry.

    Rules:
      - *source_path* is a valid relative path (not absolute, no .. traversal)
      - *percent_covered* is between 0.0 and 100.0 inclusive
      - *status* is one of ``compliant``, ``violated``
    """
    errors: List[str] = []

    source_path = entry.get("source_path", "")
    if not isinstance(source_path, str) or not source_path:
        errors.append(f"source_path {source_path!r}: must be a non-empty string")
    else:
        if source_path.startswith("/"):
            errors.append(f"source_path {source_path!r}: absolute paths not allowed")
        if ".." in source_path.split("/"):
            errors.append(
                f"source_path {source_path!r}: parent-directory traversal (..) not allowed"
            )

    percent_covered = entry.get("percent_covered")
    if percent_covered is None:
        errors.append("percent_covered: missing")
    elif not isinstance(percent_covered, (int, float)):
        errors.append(f"percent_covered {percent_covered!r}: must be numeric")
    elif not (0.0 <= float(percent_covered) <= 100.0):
        errors.append(f"percent_covered {percent_covered}: must be in range 0.0-100.0")

    status = entry.get("status", "")
    if status not in ("compliant", "violated"):
        errors.append(f"status {status!r}: must be compliant|violated")

    return errors


# ── 3. Data loaders (write) ─────────────────────────────────────────────────

def load_tasks(conn: sqlite3.Connection, tasks: list) -> List[str]:
    """Bulk-load tasks into the database.

    For each dict in *tasks*:
      1. Validate via :func:`validate_task`.
      2. If valid, INSERT into ``tasks`` and ``task_acs``.

    Returns a flat list of all validation error strings (empty = all pass).
    """
    all_errors: List[str] = []
    for task in tasks:
        errs = validate_task(task)
        if errs:
            all_errors.extend(errs)
            continue

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
    return all_errors


def load_claims(conn: sqlite3.Connection, claims: list) -> List[str]:
    """Bulk-load claims into the database.

    For each dict in *claims*:
      1. Validate via :func:`validate_claim`.
      2. If valid, INSERT into ``claims``, ``claim_code_refs``, ``claim_test_refs``.

    Returns a flat list of all validation error strings.
    """
    all_errors: List[str] = []
    for claim in claims:
        errs = validate_claim(claim)
        if errs:
            all_errors.extend(errs)
            continue

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
    return all_errors


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
