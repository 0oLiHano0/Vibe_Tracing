"""Tests for AcFreshnessChecker (Gate 2.5 - AC Freshness Detection)."""

import json
import subprocess
import pytest
from pathlib import Path

from vibe_tracing.ac_freshness_checker import AcFreshnessChecker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_git_repo(base: Path) -> None:
    """Initialise a git repo with an empty initial commit."""
    subprocess.run(["git", "init"], cwd=base, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@test.com",
         "add", "."], cwd=base, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@test.com",
         "commit", "-m", "initial"], cwd=base, check=True, capture_output=True,
    )


def _write_task_list(base: Path, tasks: list) -> None:
    """Write a minimal task_list.json."""
    data = {
        "schema_version": "0.1",
        "project": {
            "project_id": "PROJECT-TEST",
            "name": "Test",
            "stage": "mvp",
        },
        "tasks": tasks,
    }
    (base / "docs").mkdir(parents=True, exist_ok=True)
    (base / "docs" / "task_list.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8",
    )


def _write_prd(base: Path, content: str) -> None:
    """Write a minimal prd.md."""
    (base / "docs").mkdir(parents=True, exist_ok=True)
    (base / "docs" / "prd.md").write_text(content, encoding="utf-8")


def _stage_file(base: Path, rel_path: str) -> None:
    """Stage a single file."""
    subprocess.run(
        ["git", "add", rel_path], cwd=base, check=True, capture_output=True,
    )


def _stage_all(base: Path) -> None:
    """Stage all files."""
    subprocess.run(
        ["git", "add", "."], cwd=base, check=True, capture_output=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAcFreshnessChecker:
    """Unit tests for AcFreshnessChecker."""

    def test_new_task_refs_existing_ac_prd_not_staged__warns(self, tmp_path):
        """New task references an existing AC, PRD is NOT staged -> WARNING."""
        # -- Setup: commit a task_list and PRD as baseline --
        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Old task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "done",
                "owner_role": "AI Coding Agent",
                "objective": "Do old stuff",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
        ])
        _write_prd(tmp_path, "## Requirements\nAC-VT-001-01: old criterion\n")
        _init_git_repo(tmp_path)

        # -- Modify task_list: add a new task referencing an existing AC --
        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Old task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "done",
                "owner_role": "AI Coding Agent",
                "objective": "Do old stuff",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
            {
                "task_id": "TASK-VT-002",
                "title": "New task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "todo",
                "owner_role": "AI Coding Agent",
                "objective": "Do new stuff",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
        ])
        _stage_file(tmp_path, "docs/task_list.json")
        # NOTE: PRD is NOT staged

        checker = AcFreshnessChecker(tmp_path)
        success, msg = checker.check()

        assert success is True
        assert "TASK-VT-002" in msg
        assert "AC-VT-001-01" in msg
        assert "未更新 PRD" in msg

    def test_new_task_refs_ac_updated_in_prd__no_warning(self, tmp_path):
        """New task references AC that IS in the staged PRD -> no warning."""
        # -- Setup: commit baseline --
        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Old task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "done",
                "owner_role": "AI Coding Agent",
                "objective": "Do old stuff",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
        ])
        _write_prd(tmp_path, "## Requirements\nAC-VT-001-01: old criterion\n")
        _init_git_repo(tmp_path)

        # -- Modify both task_list and PRD --
        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Old task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "done",
                "owner_role": "AI Coding Agent",
                "objective": "Do old stuff",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
            {
                "task_id": "TASK-VT-002",
                "title": "New task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "todo",
                "owner_role": "AI Coding Agent",
                "objective": "Do new stuff",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01", "AC-VT-002-01"],
                "definition_of_done": [],
            },
        ])
        _write_prd(tmp_path, "## Requirements\nAC-VT-001-01: old\nAC-VT-002-01: new criterion\n")
        _stage_all(tmp_path)

        checker = AcFreshnessChecker(tmp_path)
        success, msg = checker.check()

        assert success is True
        assert msg == ""

    def test_no_new_tasks__no_output(self, tmp_path):
        """No new tasks in delta -> no output at all."""
        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Same task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "done",
                "owner_role": "AI Coding Agent",
                "objective": "Do stuff",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
        ])
        _write_prd(tmp_path, "## Requirements\n")
        _init_git_repo(tmp_path)

        # Re-stage identical task_list (no changes)
        _stage_file(tmp_path, "docs/task_list.json")

        checker = AcFreshnessChecker(tmp_path)
        success, msg = checker.check()

        assert success is True
        assert msg == ""

    def test_new_task_without_ac_refs__no_warning(self, tmp_path):
        """New task has empty AC list -> no warning (handled by task_loader AND logic)."""
        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Old task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "done",
                "owner_role": "AI Coding Agent",
                "objective": "Do old stuff",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
        ])
        _write_prd(tmp_path, "## Requirements\n")
        _init_git_repo(tmp_path)

        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Old task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "done",
                "owner_role": "AI Coding Agent",
                "objective": "Do old stuff",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
            {
                "task_id": "TASK-VT-002",
                "title": "Task without AC",
                "phase_id": "PHASE-VT-001",
                "priority": "should",
                "status": "todo",
                "owner_role": "AI Coding Agent",
                "objective": "Do something",
                "related_requirements": ["REQ-VT-002"],
                "related_acceptance_criteria": [],
                "definition_of_done": [],
            },
        ])
        _stage_file(tmp_path, "docs/task_list.json")

        checker = AcFreshnessChecker(tmp_path)
        success, msg = checker.check()

        assert success is True
        assert msg == ""

    def test_prd_staged_with_ac_not_matching_task__warns(self, tmp_path):
        """PRD staged with AC-A, new task references AC-B -> warning."""
        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Old task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "done",
                "owner_role": "AI Coding Agent",
                "objective": "Do old stuff",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
        ])
        _write_prd(tmp_path, "## Requirements\nAC-VT-001-01: old\n")
        _init_git_repo(tmp_path)

        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Old task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "done",
                "owner_role": "AI Coding Agent",
                "objective": "Do old stuff",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
            {
                "task_id": "TASK-VT-002",
                "title": "New task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "todo",
                "owner_role": "AI Coding Agent",
                "objective": "Do new stuff",
                "related_requirements": ["REQ-VT-002"],
                "related_acceptance_criteria": ["AC-VT-002-01"],
                "definition_of_done": [],
            },
        ])
        # PRD updated but only with AC-VT-003-01 (not AC-VT-002-01)
        _write_prd(tmp_path, "## Requirements\nAC-VT-001-01: old\nAC-VT-003-01: something else\n")
        _stage_all(tmp_path)

        checker = AcFreshnessChecker(tmp_path)
        success, msg = checker.check()

        assert success is True
        assert "TASK-VT-002" in msg
        assert "AC-VT-002-01" in msg
        assert "不在本次 PRD 更新范围内" in msg

    def test_no_staged_task_list__no_output(self, tmp_path):
        """task_list.json is not staged at all -> no output."""
        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Old task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "done",
                "owner_role": "AI Coding Agent",
                "objective": "Do old stuff",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
        ])
        _write_prd(tmp_path, "## Requirements\n")
        _init_git_repo(tmp_path)

        # Don't stage anything new
        checker = AcFreshnessChecker(tmp_path)
        success, msg = checker.check()

        assert success is True
        assert msg == ""

    def test_multiple_new_tasks_multiple_acs__all_warned(self, tmp_path):
        """Multiple new tasks each referencing different ACs -> all warned."""
        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Old task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "done",
                "owner_role": "AI Coding Agent",
                "objective": "Do old stuff",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
        ])
        _write_prd(tmp_path, "## Requirements\nAC-VT-001-01: old\n")
        _init_git_repo(tmp_path)

        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Old task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "done",
                "owner_role": "AI Coding Agent",
                "objective": "Do old stuff",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
            {
                "task_id": "TASK-VT-002",
                "title": "New task A",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "todo",
                "owner_role": "AI Coding Agent",
                "objective": "A",
                "related_requirements": ["REQ-VT-002"],
                "related_acceptance_criteria": ["AC-VT-002-01"],
                "definition_of_done": [],
            },
            {
                "task_id": "TASK-VT-003",
                "title": "New task B",
                "phase_id": "PHASE-VT-001",
                "priority": "should",
                "status": "todo",
                "owner_role": "AI Coding Agent",
                "objective": "B",
                "related_requirements": ["REQ-VT-003"],
                "related_acceptance_criteria": ["AC-VT-003-01", "AC-VT-003-02"],
                "definition_of_done": [],
            },
        ])
        _stage_file(tmp_path, "docs/task_list.json")

        checker = AcFreshnessChecker(tmp_path)
        success, msg = checker.check()

        assert success is True
        assert "TASK-VT-002" in msg
        assert "AC-VT-002-01" in msg
        assert "TASK-VT-003" in msg
        assert "AC-VT-003-01" in msg
        assert "AC-VT-003-02" in msg
