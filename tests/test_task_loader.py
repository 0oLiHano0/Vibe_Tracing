"""
Tests for TaskLoader (TASK-VT-007).

Each test function declares its AC/DoD coverage in its docstring.
"""

from pathlib import Path
import pytest

from vibe_tracing.prd_parser import PrdParseResult, Requirement, AcceptanceCriteria
from vibe_tracing.task_loader import TaskLoader

SCHEMAS_DIR = Path(__file__).parent.parent / "src" / "vibe_tracing" / "schemas"
DOCS_DIR = Path(__file__).parent.parent / "docs"


@pytest.fixture
def task_loader():
    """Return a TaskLoader instance."""
    return TaskLoader(SCHEMAS_DIR)


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
    Validate a clean and compliant task list against schema and mock PRD.
    Covers: AC-VT-001-01, AC-VT-001-04.
    """
    prd_res = get_mock_prd_result()
    data = get_valid_task_list_dict()

    res = task_loader.validate_data(data, prd_result=prd_res)

    assert res.is_valid is True
    assert len(res.errors) == 0
    assert len(res.gaps) == 0
    assert len(res.tasks) == 1
    assert res.tasks[0].task_id == "TASK-VT-001"
    assert res.tasks[0].is_valid is True


def test_invalid_schema_structure_fails(task_loader):
    """
    Validate that invalid task list structures fail schema validation.
    Covers: AC-VT-001-04.
    """
    # missing 'tasks' field
    bad_data = {
        "schema_version": "1.0",
        "project": {
            "project_id": "PROJECT-VT",
            "name": "Vibe Tracing",
            "stage": "development",
        },
    }
    res = task_loader.validate_data(bad_data)
    assert res.is_valid is False
    assert len(res.errors) > 0
    assert "Schema validation failed" in res.errors[0]


def test_duplicate_task_ids(task_loader):
    """
    Validate that duplicate task IDs are detected and fail validation.
    Covers: AC-VT-001-04.
    """
    prd_res = get_mock_prd_result()
    tasks = [
        {
            "task_id": "TASK-VT-001",
            "title": "Task A",
            "phase_id": "PHASE-VT-001",
            "priority": "must",
            "status": "todo",
            "owner_role": "AI Coding Agent",
            "objective": "Task A objective",
            "related_modules": ["MOD-VT-001"],
            "related_requirements": ["REQ-VT-001"],
            "related_acceptance_criteria": ["AC-VT-001-01"],
            "definition_of_done": [{"dod_id": "DOD-VT-001-01", "description": "Done."}],
        },
        {
            "task_id": "TASK-VT-001",  # Duplicate ID
            "title": "Task B",
            "phase_id": "PHASE-VT-001",
            "priority": "should",
            "status": "todo",
            "owner_role": "AI Coding Agent",
            "objective": "Task B objective",
            "related_modules": ["MOD-VT-001"],
            "related_requirements": ["REQ-VT-001"],
            "related_acceptance_criteria": ["AC-VT-001-01"],
            "definition_of_done": [{"dod_id": "DOD-VT-001-01", "description": "Done."}],
        },
    ]
    data = get_valid_task_list_dict(tasks)
    res = task_loader.validate_data(data, prd_result=prd_res)

    assert res.is_valid is False
    assert any("Duplicate task ID: TASK-VT-001" in err for err in res.errors)


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


def test_references_non_existent_requirement_forms_gap(task_loader):
    """
    Validate that referencing a non-existent requirement ID generates a gap.
    Covers: DOD-VT-007-02.
    """
    prd_res = get_mock_prd_result()
    tasks = [
        {
            "task_id": "TASK-VT-001",
            "title": "Task Referencing Bad Req",
            "phase_id": "PHASE-VT-001",
            "priority": "must",
            "status": "todo",
            "owner_role": "AI Coding Agent",
            "objective": "Task objective",
            "related_modules": ["MOD-VT-001"],
            "related_requirements": [
                "REQ-VT-999",
                "REQ-VT-001",
            ],  # Non-existent requirement + valid parent requirement
            "related_acceptance_criteria": ["AC-VT-001-01"],
            "definition_of_done": [{"dod_id": "DOD-VT-001-01", "description": "Done."}],
        }
    ]
    data = get_valid_task_list_dict(tasks)
    res = task_loader.validate_data(data, prd_result=prd_res)

    assert res.is_valid is False
    assert res.tasks[0].is_valid is False
    assert any(
        "References non-existent requirement: REQ-VT-999" in err
        for err in res.tasks[0].errors
    )
    assert len(res.gaps) == 1
    assert res.gaps[0].item_id == "TASK-VT-001"
    assert "References non-existent requirement: REQ-VT-999" in res.gaps[0].reason


def test_references_non_existent_acceptance_criterion_forms_gap(task_loader):
    """
    Validate that referencing a non-existent AC ID generates a gap.
    Covers: DOD-VT-007-02.
    """
    prd_res = get_mock_prd_result()
    tasks = [
        {
            "task_id": "TASK-VT-001",
            "title": "Task Referencing Bad AC",
            "phase_id": "PHASE-VT-001",
            "priority": "must",
            "status": "todo",
            "owner_role": "AI Coding Agent",
            "objective": "Task objective",
            "related_modules": ["MOD-VT-001"],
            "related_requirements": ["REQ-VT-001"],
            "related_acceptance_criteria": ["AC-VT-001-99"],  # Non-existent AC
            "definition_of_done": [{"dod_id": "DOD-VT-001-01", "description": "Done."}],
        }
    ]
    data = get_valid_task_list_dict(tasks)
    res = task_loader.validate_data(data, prd_result=prd_res)

    assert res.is_valid is False
    assert res.tasks[0].is_valid is False
    assert any(
        "References non-existent acceptance criterion: AC-VT-001-99" in err
        for err in res.tasks[0].errors
    )
    assert len(res.gaps) == 1
    assert res.gaps[0].item_id == "TASK-VT-001"
    assert (
        "References non-existent acceptance criterion: AC-VT-001-99"
        in res.gaps[0].reason
    )


def test_inverse_relationship_mismatch_forms_gap(task_loader):
    """
    Validate that referencing an AC but missing its parent requirement in related_requirements generates a gap.
    Covers: DOD-VT-007-02.
    """
    prd_res = get_mock_prd_result()
    tasks = [
        {
            "task_id": "TASK-VT-001",
            "title": "Task with Mismatched Parent",
            "phase_id": "PHASE-VT-001",
            "priority": "must",
            "status": "todo",
            "owner_role": "AI Coding Agent",
            "objective": "Task objective",
            "related_modules": ["MOD-VT-001"],
            "related_requirements": ["REQ-VT-002"],  # Missing REQ-VT-001
            "related_acceptance_criteria": ["AC-VT-001-01"],  # Belongs to REQ-VT-001
            "definition_of_done": [{"dod_id": "DOD-VT-001-01", "description": "Done."}],
        }
    ]
    data = get_valid_task_list_dict(tasks)
    res = task_loader.validate_data(data, prd_result=prd_res)

    assert res.is_valid is False
    assert res.tasks[0].is_valid is False
    assert any(
        "parent requirement REQ-VT-001 is missing from related_requirements" in err
        for err in res.tasks[0].errors
    )
    assert len(res.gaps) == 1
    assert res.gaps[0].item_id == "TASK-VT-001"
    assert "parent requirement REQ-VT-001 is missing" in res.gaps[0].reason


def test_validate_real_files_load(task_loader):
    """
    Validate loading the real task_list.json file and parsing it with the real prd.md.
    Covers: AC-VT-001-01, AC-VT-001-04, DOD-VT-007-03.
    """
    task_list_path = DOCS_DIR / "task_list.json"
    prd_path = DOCS_DIR / "prd.md"

    if not task_list_path.exists() or not prd_path.exists():
        pytest.skip("Real standard input files do not exist.")

    from vibe_tracing.prd_parser import PrdParser

    prd_parser = PrdParser()
    prd_res = prd_parser.parse_file(prd_path)
    assert prd_res.is_valid is True

    res = task_loader.load_and_validate(task_list_path, prd_result=prd_res)

    # The real task_list.json has id_rules.all_tasks_must_link_requirements_and_acceptance_criteria=true,
    # and some tasks (e.g. TASK-VT-036, TASK-VT-042) have REQ but no AC.
    # Under the new AND logic, these are correctly flagged as invalid.
    assert len(res.tasks) > 0
    # Verify the strict-link rule is enforced on real data
    req_only_tasks = [
        t for t in res.tasks
        if t.related_requirements and not t.related_acceptance_criteria
    ]
    if req_only_tasks:
        assert res.is_valid is False
        for t in req_only_tasks:
            assert t.is_valid is False
            assert any("缺少验收标准关联" in e for e in t.errors)
    else:
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


def test_legacy_or_logic_allows_req_only_task(task_loader):
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
