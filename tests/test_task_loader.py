"""
Tests for TaskLoader (TASK-VT-007).

Each test function declares its AC/DoD coverage in its docstring.
"""

from pathlib import Path
import pytest

from vibe_tracing.infra.loader.prd_parser import PrdParseResult, Requirement, AcceptanceCriteria
from vibe_tracing.infra.loader.task_loader import TaskLoader

DOCS_DIR = Path(__file__).parent.parent / "docs"


@pytest.fixture
def task_loader():
    """Return a TaskLoader instance."""
    return TaskLoader()


# Helper: Create a valid minimal task list dict
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


# Helper: Create a mock PrdParseResult
def get_mock_prd_result():
    return PrdParseResult(
        requirements=[
            Requirement(
                req_id="REQ-VT-001",
                title="Full Traceability",
                priority="must",
                category="functional",
                acceptance_criteria=[
                    AcceptanceCriteria(
                        ac_id="AC-VT-001-01",
                        title="Requirement must map to task",
                        is_testing_required=True,
                    ),
                    AcceptanceCriteria(
                        ac_id="AC-VT-001-02",
                        title="AC must map to test evidence",
                        is_testing_required=True,
                    ),
                ],
            ),
            Requirement(
                req_id="REQ-VT-002",
                title="Agent Claim Verification",
                priority="must",
                category="functional",
                acceptance_criteria=[
                    AcceptanceCriteria(
                        ac_id="AC-VT-002-01",
                        title="Claim validation",
                        is_testing_required=True,
                    )
                ],
            ),
        ],
        is_valid=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_valid_task_list_passes(task_loader):
    """
    Validate a clean and compliant task list against schema.
    Covers: AC-VT-001-01, AC-VT-001-04.
    """
    data = get_valid_task_list_dict()

    res = task_loader.validate_data(data)

    assert res.is_valid is True
    assert len(res.errors) == 0
    assert len(res.gaps) == 0
    assert len(res.tasks) == 1
    assert res.tasks[0].task_id == "TASK-VT-001"
    assert res.tasks[0].is_valid is True


def test_isolated_task_fails(task_loader):
    """
    Validate that an isolated task (no related REQs or ACs) is marked invalid/unclear.
    Covers: DOD-VT-007-01.
    """
    tasks = [
        {
            "task_id": "TASK-VT-001",
            "title": "Isolated Task",
            "phase_id": "PHASE-VT-001",
            "priority": "must",
            "status": "todo",
            "owner_role": "AI Coding Agent",
            "objective": "Isolated task objective",
            "related_modules": ["MOD-VT-001"],
            "related_requirements": [],  # Empty
            "related_acceptance_criteria": [],  # Empty
            "definition_of_done": [{"dod_id": "DOD-VT-001-01", "description": "Done."}],
        }
    ]
    data = get_valid_task_list_dict(tasks)
    res = task_loader.validate_data(data)

    assert res.is_valid is False
    assert res.tasks[0].is_valid is False
    assert any("is isolated" in err for err in res.tasks[0].errors)
    assert any("is isolated" in err for err in res.errors)
    assert len(res.gaps) == 1
    assert res.gaps[0].item_id == "TASK-VT-001"
    assert "isolated" in res.gaps[0].reason


def test_validate_real_files_load(task_loader):
    """
    Validate loading the real task_list.json file.
    Covers: AC-VT-001-01, AC-VT-001-04, DOD-VT-007-03.
    """
    task_list_path = DOCS_DIR / "task_list.json"

    if not task_list_path.exists():
        pytest.skip("Real standard input files do not exist.")

    res = task_loader.load_and_validate(task_list_path)

    assert len(res.tasks) > 0
    assert res.is_valid is True, f"Real files load failed: {res.errors}"

def test_strict_link_rejects_req_only_task(task_loader):
    """
    When id_rules.all_tasks_must_link_requirements_and_acceptance_criteria is true,
    a task with only REQ but no AC should be marked invalid (AND logic).
    Covers: REFACTOR-007.
    """
    tasks = [
        {
            "task_id": "TASK-VT-001",
            "title": "Task With Req Only",
            "phase_id": "PHASE-VT-001",
            "priority": "must",
            "status": "todo",
            "owner_role": "AI Coding Agent",
            "objective": "Task objective",
            "related_modules": ["MOD-VT-001"],
            "related_requirements": ["REQ-VT-001"],
            "related_acceptance_criteria": [],  # No AC
            "definition_of_done": [{"dod_id": "DOD-VT-001-01", "description": "Done."}],
        }
    ]
    data = get_valid_task_list_dict(tasks)
    data["id_rules"] = {
        "all_tasks_must_link_requirements_and_acceptance_criteria": True,
    }
    res = task_loader.validate_data(data)

    assert res.is_valid is False
    assert res.tasks[0].is_valid is False
    assert any("缺少验收标准关联" in err for err in res.tasks[0].errors)
    assert len(res.gaps) == 1
    assert res.gaps[0].item_id == "TASK-VT-001"


def test_or_logic_allows_req_only_task(task_loader):
    """
    When id_rules.all_tasks_must_link_requirements_and_acceptance_criteria is false
    or absent, a task with only REQ but no AC should pass the isolated check (OR logic).
    Covers: REFACTOR-008.
    """
    tasks = [
        {
            "task_id": "TASK-VT-001",
            "title": "Task With Req Only",
            "phase_id": "PHASE-VT-001",
            "priority": "must",
            "status": "todo",
            "owner_role": "AI Coding Agent",
            "objective": "Task objective",
            "related_modules": ["MOD-VT-001"],
            "related_requirements": ["REQ-VT-001"],
            "related_acceptance_criteria": [],  # No AC, but has REQ
            "definition_of_done": [{"dod_id": "DOD-VT-001-01", "description": "Done."}],
        }
    ]
    # Test with flag explicitly false
    data = get_valid_task_list_dict(tasks)
    data["id_rules"] = {
        "all_tasks_must_link_requirements_and_acceptance_criteria": False,
    }
    res = task_loader.validate_data(data)
    assert res.tasks[0].is_valid is True
    assert not any("is isolated" in err for err in res.tasks[0].errors)

    # Test with id_rules absent entirely
    data_no_rules = get_valid_task_list_dict(tasks)
    res2 = task_loader.validate_data(data_no_rules)
    assert res2.tasks[0].is_valid is True
    assert not any("is isolated" in err for err in res2.tasks[0].errors)


def test_architectural_orphan_rejection(task_loader):
    """
    Validate that a task without related_modules fails validation as an architectural orphan.
    Covers: Mandatory Architectural Bounding.
    """
    tasks = [
        {
            "task_id": "TASK-VT-001",
            "title": "Architectural Orphan Task",
            "phase_id": "PHASE-VT-001",
            "priority": "must",
            "status": "todo",
            "owner_role": "AI Coding Agent",
            "objective": "Task objective",
            "related_requirements": ["REQ-VT-001"],
            "related_acceptance_criteria": ["AC-VT-001-01"],
            "related_modules": [],  # Empty modules!
            "definition_of_done": [{"dod_id": "DOD-VT-001-01", "description": "Done."}]
        }
    ]
    data = get_valid_task_list_dict(tasks)
    res = task_loader.validate_data(data)

    assert res.is_valid is False
    assert res.tasks[0].is_valid is False
    assert any("architectural orphan" in err for err in res.tasks[0].errors)
    assert any("architectural orphan" in err for err in res.errors)
    assert len(res.gaps) == 1
    assert "Architectural orphan" in res.gaps[0].reason
