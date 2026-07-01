"""Tests for infra/db.py — DDL correctness, UPSERT, cache cleanup, export."""

import sqlite3
from vibe_tracing.infra.config.enums import CoverageStatus
from vibe_tracing.infra.db import (
    init_in_memory_db,
    upsert_test_result,
    upsert_coverage_report,
    purge_stale_cache,
)


# ── DDL ────────────────────────────────────────────────────────────────────────


class TestDDL:
    def test_init_creates_tables(self):
        conn = init_in_memory_db()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {r[0] for r in rows}
        expected = {
            "claim_code_refs",
            "claim_test_refs",
            "claims",
            "coverage_reports",
            "lint_results",
            "task_acs",
            "tasks",
            "test_results",
            "requirements",
            "acceptance_criteria",
            "task_requirements",
            "arch_modules",
            "arch_constraints",
            "task_modules",
            "task_constraints",
        }
        assert table_names == expected, f"Got {table_names}, expected {expected}"
        conn.close()

    def test_no_foreign_keys(self):
        conn = init_in_memory_db()
        rows = conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND sql LIKE '%FOREIGN KEY%'"
        ).fetchall()
        assert len(rows) == 0, f"Found FOREIGN KEY constraints: {rows}"
        conn.close()


# ── UPSERT ─────────────────────────────────────────────────────────────────────


class TestUpsert:
    def test_upsert_test_result_insert_and_update(self):
        conn = init_in_memory_db()
        nodeid = "tests/test_x.py::test_foo"

        # Insert with outcome='failed'
        upsert_test_result(conn, nodeid, CoverageStatus.VIOLATED.value, 1, "pytest tests/test_x.py", False)
        rows = conn.execute("SELECT nodeid, outcome FROM test_results").fetchall()
        assert len(rows) == 1
        assert rows[0][1] == CoverageStatus.VIOLATED.value

        # Upsert same nodeid with outcome='passed'
        upsert_test_result(conn, nodeid, CoverageStatus.COVERED.value, 0, "pytest tests/test_x.py", False)
        rows = conn.execute("SELECT nodeid, outcome FROM test_results").fetchall()
        assert len(rows) == 1, "UPSERT should have replaced, not duplicated"
        assert rows[0][1] == CoverageStatus.COVERED.value

        conn.close()

    def test_upsert_coverage_report_insert_and_update(self):
        conn = init_in_memory_db()
        source_path = "src/vibe_tracing/infra/db.py"

        # Insert with status='violated'
        upsert_coverage_report(conn, source_path, 45.0, 100, "violated", False)
        rows = conn.execute(
            "SELECT source_path, status FROM coverage_reports"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][1] == "violated"

        # Upsert same source_path with status='compliant'
        upsert_coverage_report(conn, source_path, 95.0, 100, "compliant", False)
        rows = conn.execute(
            "SELECT source_path, status FROM coverage_reports"
        ).fetchall()
        assert len(rows) == 1, "UPSERT should have replaced, not duplicated"
        assert rows[0][1] == "compliant"

        conn.close()


# ── Purge stale cache ─────────────────────────────────────────────────────────


class TestPurgeStaleCache:
    def test_purge_removes_carried_over_for_target_file(self):
        conn = init_in_memory_db()

        # Insert two test results in the same test file
        conn.execute(
            "INSERT OR REPLACE INTO test_results "
            "(nodeid, outcome, exit_code, command, carried_over) "
            "VALUES (?, ?, ?, ?, ?)",
            ("tests/test_y.py::test_old", CoverageStatus.VIOLATED.value, 1, "", 1),
        )
        conn.execute(
            "INSERT OR REPLACE INTO test_results "
            "(nodeid, outcome, exit_code, command, carried_over) "
            "VALUES (?, ?, ?, ?, ?)",
            ("tests/test_y.py::test_new", CoverageStatus.COVERED.value, 0, "", 0),
        )
        conn.commit()

        purge_stale_cache(conn, ["tests/test_y.py"])

        remaining = conn.execute(
            "SELECT nodeid FROM test_results ORDER BY nodeid"
        ).fetchall()
        remaining_nodeids = [r[0] for r in remaining]
        assert (
            "tests/test_y.py::test_new" in remaining_nodeids
        ), "carried_over=0 record should survive"
        assert (
            "tests/test_y.py::test_old" not in remaining_nodeids
        ), "carried_over=1 record should be purged"

        conn.close()

    def test_purge_does_not_affect_non_target(self):
        conn = init_in_memory_db()

        # Insert test results for two different test files, both carried_over=1
        conn.execute(
            "INSERT OR REPLACE INTO test_results "
            "(nodeid, outcome, exit_code, command, carried_over) "
            "VALUES (?, ?, ?, ?, ?)",
            ("tests/test_y.py::test_old", CoverageStatus.VIOLATED.value, 1, "", 1),
        )
        conn.execute(
            "INSERT OR REPLACE INTO test_results "
            "(nodeid, outcome, exit_code, command, carried_over) "
            "VALUES (?, ?, ?, ?, ?)",
            ("tests/test_z.py::test_only", CoverageStatus.COVERED.value, 0, "", 1),
        )
        conn.commit()

        # Purge only test_y.py
        purge_stale_cache(conn, ["tests/test_y.py"])

        remaining = conn.execute(
            "SELECT nodeid FROM test_results ORDER BY nodeid"
        ).fetchall()
        remaining_nodeids = [r[0] for r in remaining]
        assert (
            "tests/test_y.py::test_old" not in remaining_nodeids
        ), "carried_over=1 for target file should be purged"
        assert "tests/test_z.py::test_only" in remaining_nodeids, (
            "carried_over=1 for non-target file should survive"
        )

        conn.close()

    def test_purge_removes_all_carried_over_from_same_file(self):
        """Purging a file path should remove ALL carried_over tests in that file."""
        conn = init_in_memory_db()

        # Insert 3 tests from the same file, all carried_over=1
        for nodeid in [
            "tests/test_z.py::test_a",
            "tests/test_z.py::test_b",
            "tests/test_z.py::test_c",
        ]:
            conn.execute(
                "INSERT OR REPLACE INTO test_results "
                "(nodeid, outcome, exit_code, command, carried_over) "
                "VALUES (?, ?, ?, ?, ?)",
                (nodeid, CoverageStatus.COVERED.value, 0, "", 1),
            )
        conn.commit()

        purge_stale_cache(conn, ["tests/test_z.py"])

        remaining = conn.execute("SELECT nodeid FROM test_results").fetchall()
        assert len(remaining) == 0, (
            f"All 3 carried_over tests should be purged, got {remaining}"
        )
        conn.close()

    def test_purge_preserves_new_results_from_same_file(self):
        """Purging should only remove carried_over=1, keeping fresh results."""
        conn = init_in_memory_db()

        conn.execute(
            "INSERT OR REPLACE INTO test_results "
            "(nodeid, outcome, exit_code, command, carried_over) "
            "VALUES (?, ?, ?, ?, ?)",
            ("tests/test_y.py::test_old", CoverageStatus.VIOLATED.value, 1, "", 1),
        )
        conn.execute(
            "INSERT OR REPLACE INTO test_results "
            "(nodeid, outcome, exit_code, command, carried_over) "
            "VALUES (?, ?, ?, ?, ?)",
            ("tests/test_y.py::test_new", CoverageStatus.COVERED.value, 0, "", 0),
        )
        conn.commit()

        purge_stale_cache(conn, ["tests/test_y.py"])

        remaining = conn.execute(
            "SELECT nodeid, carried_over FROM test_results ORDER BY nodeid"
        ).fetchall()
        nodeids = [r[0] for r in remaining]
        assert "tests/test_y.py::test_old" not in nodeids, (
            "carried_over=1 test should be purged"
        )
        assert "tests/test_y.py::test_new" in nodeids, (
            "carried_over=0 test should survive"
        )
        conn.close()

    def test_purge_does_not_affect_different_file(self):
        """Purging file A should not touch entries from file B."""
        conn = init_in_memory_db()

        conn.execute(
            "INSERT OR REPLACE INTO test_results "
            "(nodeid, outcome, exit_code, command, carried_over) "
            "VALUES (?, ?, ?, ?, ?)",
            ("tests/test_a.py::test_x", CoverageStatus.COVERED.value, 0, "", 1),
        )
        conn.execute(
            "INSERT OR REPLACE INTO test_results "
            "(nodeid, outcome, exit_code, command, carried_over) "
            "VALUES (?, ?, ?, ?, ?)",
            ("tests/test_b.py::test_y", CoverageStatus.COVERED.value, 0, "", 1),
        )
        conn.commit()

        purge_stale_cache(conn, ["tests/test_a.py"])

        remaining = conn.execute(
            "SELECT nodeid FROM test_results ORDER BY nodeid"
        ).fetchall()
        nodeids = [r[0] for r in remaining]
        assert "tests/test_a.py::test_x" not in nodeids, (
            "carried_over=1 for purged file should be removed"
        )
        assert "tests/test_b.py::test_y" in nodeids, (
            "carried_over=1 for different file should survive"
        )
        conn.close()


