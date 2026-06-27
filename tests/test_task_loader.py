"""
Tests for TaskLoader.
"""

from pathlib import Path
import pytest

from vibe_tracing.infra.loader.task_loader import TaskLoader

DOCS_DIR = Path(__file__).parent.parent / "docs"


@pytest.fixture
def task_loader():
    """Return a TaskLoader instance."""
    return TaskLoader()


def get_valid_task_list_dict(tasks=None):
    if tasks is None:
        tasks = [
            {
                "task_id": "TASK-VT-001",
                "title": "Setup skeleton",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "todo",
                "owner_role": "AI Coding Agent",
                "objective": "Build skeletal project structure.",
                "related_modules": ["MOD-VT-001"],
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [
                    {"dod_id": "DOD-VT-001-01", "description": "Done."}
                ],
            }
        ]
    return {
        "schema_version": "1.0",
        "project": {
            "project_id": "PROJECT-VT",
            "name": "Vibe Tracing",
            "stage": "development",
        },
        "tasks": tasks,
    }


def test_valid_task_list_passes(task_loader):
    data = get_valid_task_list_dict()
    res = task_loader.validate_data(data)
    assert res.is_valid is True
    assert len(res.errors) == 0
    assert len(res.tasks) == 1
    assert res.tasks[0].task_id == "TASK-VT-001"
    assert res.tasks[0].is_valid is True


def test_validate_real_files_load(task_loader):
    task_list_path = DOCS_DIR / "task_list.json"
    if not task_list_path.exists():
        pytest.skip("Real standard input files do not exist.")
    import json
    res = task_loader.load_and_validate(json.loads(task_list_path.read_text()))
    assert len(res.tasks) > 0
    assert res.is_valid is True, f"Real files load failed: {res.errors}"
