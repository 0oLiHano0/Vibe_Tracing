"""Tests for infra/db.py — Layer 1 format validation and Layer 2 relation validation."""

from src.vibe_tracing.infra.db import (
    init_in_memory_db,
    validate_task,
    validate_claim,
    validate_test_result,
    validate_coverage_report,
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
    def test_validate_task_invalid_id_rejected(self):
        errors = validate_task({"task_id": "INVALID-ID", "priority": "must", "status": "todo"})
        assert any("task_id" in e for e in errors), (
            f"Expected task_id error, got: {errors}"
        )

    def test_validate_task_invalid_priority_rejected(self):
        errors = validate_task(
            {"task_id": "TASK-VT-001", "priority": "urgent", "status": "todo"}
        )
        assert any("priority" in e for e in errors), (
            f"Expected priority error, got: {errors}"
        )

    def test_validate_claim_path_traversal_rejected(self):
        errors = validate_claim(
            {
                "claim_id": "CLAIM-VT-001",
                "related_task": "TASK-VT-001",
                "code_refs": ["src/../../secret.py"],
                "test_refs": [],
            }
        )
        assert any("traversal" in e.lower() or ".." in e for e in errors), (
            f"Expected path traversal error, got: {errors}"
        )

    def test_validate_claim_absolute_path_rejected(self):
        errors = validate_claim(
            {
                "claim_id": "CLAIM-VT-002",
                "related_task": "TASK-VT-002",
                "code_refs": [],
                "test_refs": ["/etc/passwd"],
            }
        )
        assert any("absolute" in e.lower() for e in errors), (
            f"Expected absolute path error, got: {errors}"
        )

    def test_load_tasks_rejects_invalid_and_accepts_valid(self):
        conn = init_in_memory_db()
        tasks = [
            {"task_id": "TASK-VT-001", "priority": "must", "status": "todo",
             "related_acceptance_criteria": ["AC-VT-01"]},
            {"task_id": "BAD-ID", "priority": "must", "status": "todo",
             "related_acceptance_criteria": []},
            {"task_id": "TASK-VT-002", "priority": "should", "status": "in_progress",
             "related_acceptance_criteria": ["AC-VT-02", "AC-VT-03"]},
        ]
        errors = load_tasks(conn, tasks)

        # The invalid task should produce an error
        assert any("BAD-ID" in e for e in errors), (
            f"Expected error for BAD-ID task, got: {errors}"
        )

        # Only valid tasks should be in the database
        db_tasks = conn.execute("SELECT task_id FROM tasks ORDER BY task_id").fetchall()
        db_ids = [r[0] for r in db_tasks]
        assert "TASK-VT-001" in db_ids
        assert "TASK-VT-002" in db_ids
        assert "BAD-ID" not in db_ids, "Invalid task should not have been inserted"

        # ACs should be present for the valid tasks
        acs = conn.execute(
            "SELECT ac_id FROM task_acs WHERE task_id = ? ORDER BY ac_id",
            ("TASK-VT-002",),
        ).fetchall()
        ac_ids = [r[0] for r in acs]
        assert "AC-VT-02" in ac_ids
        assert "AC-VT-03" in ac_ids

        conn.close()

    def test_validate_test_result_invalid_nodeid(self):
        errors = validate_test_result(
            {"nodeid": "", "outcome": "passed", "exit_code": 0}
        )
        assert any("nodeid" in e for e in errors), (
            f"Expected nodeid error for empty string, got: {errors}"
        )

        errors2 = validate_test_result(
            {"nodeid": "no_separator", "outcome": "passed", "exit_code": 0}
        )
        assert any("nodeid" in e for e in errors2), (
            f"Expected nodeid error for missing '::', got: {errors2}"
        )

    def test_validate_test_result_invalid_outcome(self):
        errors = validate_test_result(
            {"nodeid": "test.py::test_x", "outcome": "unknown", "exit_code": 0}
        )
        assert any("outcome" in e for e in errors), (
            f"Expected outcome error, got: {errors}"
        )

    def test_validate_coverage_report_invalid_range(self):
        errors = validate_coverage_report(
            {"source_path": "src/foo.py", "percent_covered": 150.0, "status": "compliant"}
        )
        assert any("range" in e.lower() or "0.0-100" in e for e in errors), (
            f"Expected range error, got: {errors}"
        )


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
