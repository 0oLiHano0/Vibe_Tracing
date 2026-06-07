"""Tests for AcFreshnessChecker (Gate 2.5 - AC Freshness Detection)."""

import json
import subprocess
from unittest.mock import patch
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


def _write_claims(base: Path, claims: list) -> None:
    """Write agent_claims.json."""
    (base / ".vibetracing").mkdir(parents=True, exist_ok=True)
    (base / ".vibetracing" / "agent_claims.json").write_text(
        json.dumps(claims, indent=2, ensure_ascii=False), encoding="utf-8",
    )


def _write_code_file(base: Path, rel_path: str, content: str = "# code\n") -> None:
    """Create a code file at the given relative path."""
    full = base / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


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

    @patch("vibe_tracing.ac_freshness_checker.subprocess.run", side_effect=FileNotFoundError)
    def test_git_not_installed_graceful(self, mock_run, tmp_path):
        """When git is not on PATH, check() returns gracefully without crashing."""
        checker = AcFreshnessChecker(tmp_path)
        success, msg = checker.check()

        assert success is True
        assert msg == ""


# ---------------------------------------------------------------------------
# Reverse coverage check tests
# ---------------------------------------------------------------------------


class TestReverseCoverageCheck:
    """Tests for the reverse coverage check (staged code -> covering task modified?)."""

    def _setup_baseline(self, tmp_path: Path) -> None:
        """Commit a baseline with task_list, claims, and a code file."""
        # Init repo first (empty commit not possible, so init without commit)
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Implement feature",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "todo",
                "owner_role": "agent",
                "objective": "Implement the feature",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
        ])
        _write_prd(tmp_path, "## Requirements\nAC-VT-001-01: criterion\n")
        _write_claims(tmp_path, [
            {
                "claim_id": "CLAIM-VT-001",
                "related_task": "TASK-VT-001",
                "claimed_status": "covered",
                "evidence_refs": [],
                "timestamp": "2030-01-01T00:00:00Z",
                "code_refs": ["src/feature.py#L1-L10"],
                "test_refs": [],
                "notes": "Baseline",
            },
        ])
        _write_code_file(tmp_path, "src/feature.py", "# baseline\n")
        _stage_all(tmp_path)
        subprocess.run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@test.com",
             "commit", "-m", "baseline"],
            cwd=tmp_path, check=True, capture_output=True,
        )

    def test_staged_code_no_covering_task__no_warning(self, tmp_path):
        """Staged code file with no covering task -> no warning."""
        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Old task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "done",
                "owner_role": "agent",
                "objective": "Old stuff",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
        ])
        _write_prd(tmp_path, "## Requirements\nAC-VT-001-01: old\n")
        _write_claims(tmp_path, [])  # No claims
        _init_git_repo(tmp_path)

        # Stage a new code file not covered by any claim
        _write_code_file(tmp_path, "src/new_file.py", "# new\n")
        _stage_file(tmp_path, "src/new_file.py")

        checker = AcFreshnessChecker(tmp_path)
        success, msg = checker.check()

        assert success is True
        assert msg == ""

    def test_staged_code_covered_by_unmodified_task__warns(self, tmp_path):
        """Staged code covered by a task that was NOT modified -> WARNING."""
        self._setup_baseline(tmp_path)

        # Modify code file but do NOT modify the task
        _write_code_file(tmp_path, "src/feature.py", "# modified\n")
        _stage_file(tmp_path, "src/feature.py")

        checker = AcFreshnessChecker(tmp_path)
        success, msg = checker.check()

        assert success is True
        assert "反向覆盖检查提醒" in msg
        assert "src/feature.py" in msg
        assert "TASK-VT-001" in msg
        assert "未在本次提交中修改" in msg

    def test_staged_code_covered_by_modified_task__no_warning(self, tmp_path):
        """Staged code covered by a task that WAS modified -> no warning."""
        self._setup_baseline(tmp_path)

        # Modify both the task AND the code file
        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Implement feature (updated)",  # Modified field
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "in_progress",  # Modified field
                "owner_role": "agent",
                "objective": "Implement the feature",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
        ])
        _write_code_file(tmp_path, "src/feature.py", "# modified\n")
        _stage_all(tmp_path)

        checker = AcFreshnessChecker(tmp_path)
        success, msg = checker.check()

        assert success is True
        assert "反向覆盖检查提醒" not in msg

    def test_line_range_suffix_stripped(self, tmp_path):
        """Line-range suffixes in code_refs are correctly stripped."""
        # Init repo
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "todo",
                "owner_role": "agent",
                "objective": "Do it",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
        ])
        _write_prd(tmp_path, "## Requirements\nAC-VT-001-01: criterion\n")
        _write_claims(tmp_path, [
            {
                "claim_id": "CLAIM-VT-001",
                "related_task": "TASK-VT-001",
                "claimed_status": "covered",
                "evidence_refs": [],
                "timestamp": "2030-01-01T00:00:00Z",
                "code_refs": ["src/foo.py#L5-L20"],
                "test_refs": [],
                "notes": "Baseline",
            },
        ])
        _write_code_file(tmp_path, "src/foo.py", "# code\n")
        _stage_all(tmp_path)
        subprocess.run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@test.com",
             "commit", "-m", "baseline"],
            cwd=tmp_path, check=True, capture_output=True,
        )

        # Now stage only the code file (task NOT modified)
        _write_code_file(tmp_path, "src/foo.py", "# modified\n")
        _stage_file(tmp_path, "src/foo.py")

        checker = AcFreshnessChecker(tmp_path)
        success, msg = checker.check()

        assert success is True
        assert "反向覆盖检查提醒" in msg
        assert "src/foo.py" in msg

    def test_no_claims__reverse_check_skipped(self, tmp_path):
        """When there are no staged claims, reverse check produces no warning."""
        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "todo",
                "owner_role": "agent",
                "objective": "Do it",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
        ])
        _write_prd(tmp_path, "## Requirements\nAC-VT-001-01: criterion\n")
        _init_git_repo(tmp_path)

        # Stage a code file but no claims
        _write_code_file(tmp_path, "src/feature.py", "# new\n")
        _stage_file(tmp_path, "src/feature.py")

        checker = AcFreshnessChecker(tmp_path)
        success, msg = checker.check()

        assert success is True
        assert "反向覆盖检查提醒" not in msg

    def test_new_task_also_counted_as_modified(self, tmp_path):
        """A new task (not in HEAD) is treated as modified -> no reverse warning."""
        self._setup_baseline(tmp_path)

        # Add a new task that covers the code file, plus stage code and PRD
        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Implement feature",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "todo",
                "owner_role": "agent",
                "objective": "Implement the feature",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
            {
                "task_id": "TASK-VT-002",
                "title": "New task covering same file",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "todo",
                "owner_role": "agent",
                "objective": "New task",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
        ])
        _write_claims(tmp_path, [
            {
                "claim_id": "CLAIM-VT-001",
                "related_task": "TASK-VT-001",
                "claimed_status": "covered",
                "evidence_refs": [],
                "timestamp": "2030-01-01T00:00:00Z",
                "code_refs": ["src/feature.py#L1-L10"],
                "test_refs": [],
                "notes": "Baseline",
            },
            {
                "claim_id": "CLAIM-VT-002",
                "related_task": "TASK-VT-002",
                "claimed_status": "covered",
                "evidence_refs": [],
                "timestamp": "2030-01-01T00:00:00Z",
                "code_refs": ["src/feature.py"],
                "test_refs": [],
                "notes": "New claim",
            },
        ])
        _write_prd(tmp_path, "## Requirements\nAC-VT-001-01: criterion\n")
        _write_code_file(tmp_path, "src/feature.py", "# modified\n")
        _stage_all(tmp_path)

        checker = AcFreshnessChecker(tmp_path)
        success, msg = checker.check()

        # TASK-VT-002 is new (modified), so no reverse warning for it.
        # TASK-VT-001 is NOT modified -> reverse warning for it.
        assert success is True
        assert "反向覆盖检查提醒" in msg
        assert "TASK-VT-001" in msg
        # TASK-VT-002 should NOT appear in the reverse check section
        # (it may appear in forward check if PRD not staged, but here PRD IS staged so forward check is clean)
        reverse_section = msg.split("反向覆盖检查提醒")[1] if "反向覆盖检查提醒" in msg else ""
        assert "TASK-VT-002" not in reverse_section

    def test_forward_and_reverse_warnings_combined(self, tmp_path):
        """Forward and reverse warnings are both present in output."""
        # Setup baseline
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Old task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "done",
                "owner_role": "agent",
                "objective": "Old stuff",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
        ])
        _write_prd(tmp_path, "## Requirements\nAC-VT-001-01: old\n")
        _write_claims(tmp_path, [
            {
                "claim_id": "CLAIM-VT-001",
                "related_task": "TASK-VT-001",
                "claimed_status": "covered",
                "evidence_refs": [],
                "timestamp": "2030-01-01T00:00:00Z",
                "code_refs": ["src/feature.py#L1-L10"],
                "test_refs": [],
                "notes": "Baseline",
            },
        ])
        _write_code_file(tmp_path, "src/feature.py", "# baseline\n")
        _stage_all(tmp_path)
        subprocess.run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@test.com",
             "commit", "-m", "baseline"],
            cwd=tmp_path, check=True, capture_output=True,
        )

        # Add a new task (triggers forward warning) + modify code without changing task
        _write_task_list(tmp_path, [
            {
                "task_id": "TASK-VT-001",
                "title": "Old task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "done",
                "owner_role": "agent",
                "objective": "Old stuff",
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
                "owner_role": "agent",
                "objective": "New stuff",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
        ])
        _write_code_file(tmp_path, "src/feature.py", "# modified\n")
        _stage_all(tmp_path)

        checker = AcFreshnessChecker(tmp_path)
        success, msg = checker.check()

        assert success is True
        # Forward warning present
        assert "AC 新鲜度提醒" in msg
        # Reverse warning present
        assert "反向覆盖检查提醒" in msg
        assert "TASK-VT-001" in msg
