"""Tests for infra/db.py — Layer 1 format validation and Layer 2 relation validation."""

from src.vibe_tracing.infra.db import (
    init_in_memory_db,
    load_tasks,
    load_claims,
    load_staged_files,
    check_dangling_claims,
    check_ghost_code,
    check_test_dead_links,
    upsert_test_result,
)


# ── Layer 1: Format validation ────────────────────────────────────────────────


class TestLayer1FormatValidation:
    def test_load_tasks_inserts_all_tasks(self):
        conn = init_in_memory_db()
        tasks = [
            {"task_id": "TASK-VT-001", "priority": "must", "status": "todo",
             "related_acceptance_criteria": ["AC-VT-01"]},
            {"task_id": "TASK-VT-002", "priority": "should", "status": "in_progress",
             "related_acceptance_criteria": ["AC-VT-02", "AC-VT-03"]},
        ]
        result = load_tasks(conn, tasks)
        assert result is None, "load_tasks should return None (pure data pump)"

        db_tasks = conn.execute("SELECT task_id FROM tasks ORDER BY task_id").fetchall()
        db_ids = [r[0] for r in db_tasks]
        assert db_ids == ["TASK-VT-001", "TASK-VT-002"]

        acs = conn.execute(
            "SELECT ac_id FROM task_acs WHERE task_id = ? ORDER BY ac_id",
            ("TASK-VT-002",),
        ).fetchall()
        ac_ids = [r[0] for r in acs]
        assert ac_ids == ["AC-VT-02", "AC-VT-03"]

        conn.close()


# ── Layer 2: Relation validation ──────────────────────────────────────────────


class TestLayer2RelationValidation:
    def test_dangling_claim_detected(self):
        conn = init_in_memory_db()
        # Insert a claim whose related_task does not exist
        conn.execute(
            "INSERT OR REPLACE INTO claims (claim_id, related_task) VALUES (?, ?)",
            ("CLAIM-VT-001", "TASK-NONEXISTENT"),
        )
        conn.commit()

        dangling = check_dangling_claims(conn)
        assert len(dangling) == 1
        assert dangling[0]["claim_id"] == "CLAIM-VT-001"
        assert dangling[0]["related_task"] == "TASK-NONEXISTENT"

        conn.close()

    def test_ghost_code_detected(self):
        conn = init_in_memory_db()
        # Stage a file without any claim code_ref covering it
        load_staged_files(conn, {"src/ghost.py", "src/legitimate.py"})

        # Add a claim covering only src/legitimate.py
        load_claims(conn, [
            {
                "claim_id": "CLAIM-VT-010",
                "related_task": "TASK-VT-010",
                "code_refs": ["src/legitimate.py"],
                "test_refs": [],
            },
        ])

        ghost = check_ghost_code(conn)
        assert "src/ghost.py" in ghost, (
            f"src/ghost.py should be detected as ghost code, got: {ghost}"
        )
        assert "src/legitimate.py" not in ghost, (
            f"src/legitimate.py should not be ghost code, got: {ghost}"
        )

        conn.close()

    def test_test_dead_link_detected(self):
        conn = init_in_memory_db()
        # Insert a claim with a test_ref whose nodeid has no corresponding test_result
        load_claims(conn, [
            {
                "claim_id": "CLAIM-VT-020",
                "related_task": "TASK-VT-020",
                "code_refs": [],
                "test_refs": ["tests/test_dead.py::test_gone"],
            },
        ])

        dead_links = check_test_dead_links(conn)
        assert len(dead_links) == 1
        assert dead_links[0]["claim_id"] == "CLAIM-VT-020"
        assert dead_links[0]["test_nodeid"] == "tests/test_dead.py::test_gone"

        # Now add a passed test_result for that nodeid — dead link should vanish
        upsert_test_result(
            conn,
            "tests/test_dead.py::test_gone",
            "passed",
            0,
            "pytest tests/test_dead.py",
            False,
        )

        dead_links_after = check_test_dead_links(conn)
        assert len(dead_links_after) == 0, (
            f"After adding a passed result, expected 0 dead links, got: {dead_links_after}"
        )

        conn.close()
