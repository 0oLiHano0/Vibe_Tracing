"""
Tests for ClaimLoader (TASK-VT-008).

Each test function declares its AC/DoD coverage in its docstring.
"""

from pathlib import Path
import pytest

from vibe_tracing.claim_loader import ClaimLoader
from vibe_tracing.task_loader import TaskListLoadResult, Task

SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"
DOCS_DIR = Path(__file__).parent.parent / "docs"
VIBETRACING_DIR = Path(__file__).parent.parent / ".vibetracing"


@pytest.fixture
def claim_loader():
    """Return a ClaimLoader instance."""
    return ClaimLoader(SCHEMAS_DIR)


# Helper: Create a valid minimal claim list dict/list
def get_valid_claims_list(claims=None):
    if claims is None:
        claims = [
            {
                "claim_id": "CLAIM-VT-001",
                "related_task": "TASK-VT-001",
                "claimed_status": "covered",
                "evidence_refs": ["EVIDENCE-VT-001"],
                "timestamp": "2026-01-01T00:00:00Z",
            }
        ]
    return claims


# Helper: Create a mock TaskListLoadResult
def get_mock_task_result():
    return TaskListLoadResult(
        tasks=[
            Task(
                task_id="TASK-VT-001",
                title="Skeleton Setup",
                phase_id="PHASE-VT-001",
                priority="must",
                status="done",
                owner_role="agent",
                objective="Implement skeletal files.",
            ),
            Task(
                task_id="TASK-VT-002",
                title="Status Enums",
                phase_id="PHASE-VT-001",
                priority="must",
                status="done",
                owner_role="agent",
                objective="Implement status enums.",
            ),
        ],
        is_valid=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_valid_claims_list_passes(claim_loader):
    """
    Validate a clean and compliant claims list against schema and mock task list.
    Covers: AC-VT-002-01, AC-VT-002-02.
    """
    task_res = get_mock_task_result()
    data = get_valid_claims_list()

    res = claim_loader.validate_data(data, task_result=task_res)

    assert res.is_valid is True
    assert len(res.errors) == 0
    assert len(res.gaps) == 0
    assert len(res.claims) == 1
    assert res.claims[0].claim_id == "CLAIM-VT-001"
    assert res.claims[0].is_valid is True


def test_invalid_schema_structure_fails(claim_loader):
    """
    Validate that invalid claim list structures fail schema validation.
    Covers: AC-VT-002-02.
    """
    # top level must be an array, passing a dict instead
    bad_data = {
        "claim_id": "CLAIM-VT-001",
    }
    res = claim_loader.validate_data(bad_data)
    assert res.is_valid is False
    assert len(res.errors) > 0
    assert "Schema validation failed" in res.errors[0]


def test_duplicate_claim_ids(claim_loader):
    """
    Validate that duplicate claim IDs are detected and fail validation.
    Covers: AC-VT-002-02.
    """
    task_res = get_mock_task_result()
    claims = [
        {
            "claim_id": "CLAIM-VT-001",
            "related_task": "TASK-VT-001",
            "claimed_status": "covered",
            "evidence_refs": ["EVIDENCE-VT-001"],
            "timestamp": "2026-01-01T00:00:00Z",
        },
        {
            "claim_id": "CLAIM-VT-001",  # Duplicate claim ID
            "related_task": "TASK-VT-002",
            "claimed_status": "partial",
            "evidence_refs": ["EVIDENCE-VT-002"],
            "timestamp": "2026-01-01T00:00:00Z",
        },
    ]
    res = claim_loader.validate_data(claims, task_result=task_res)

    assert res.is_valid is False
    assert any("Duplicate claim ID: CLAIM-VT-001" in err for err in res.errors)


def test_missing_required_fields_fails_validation(claim_loader):
    """
    Validate that missing required fields inside a claim fails validation.
    Covers: DOD-VT-008-01.
    """
    # missing 'related_task' field
    bad_claims = [
        {
            "claim_id": "CLAIM-VT-001",
            "claimed_status": "covered",
            "evidence_refs": ["EVIDENCE-VT-001"],
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    res = claim_loader.validate_data(bad_claims)
    assert res.is_valid is False
    assert len(res.errors) > 0
    assert "Schema validation failed" in res.errors[0]


def test_references_non_existent_task_forms_gap(claim_loader):
    """
    Validate that referencing a non-existent task ID generates a gap.
    Covers: DOD-VT-008-02.
    """
    task_res = get_mock_task_result()
    claims = [
        {
            "claim_id": "CLAIM-VT-001",
            "related_task": "TASK-VT-999",  # Non-existent task
            "claimed_status": "partial",
            "evidence_refs": ["EVIDENCE-VT-001"],
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    res = claim_loader.validate_data(claims, task_result=task_res)

    assert res.is_valid is False
    assert res.claims[0].is_valid is False
    assert any(
        "References non-existent task: TASK-VT-999" in err
        for err in res.claims[0].errors
    )
    assert len(res.gaps) == 1
    assert res.gaps[0].item_id == "CLAIM-VT-001"
    assert "References non-existent task: TASK-VT-999" in res.gaps[0].reason


def test_completed_claim_without_external_evidence_fails(claim_loader):
    """
    Validate that completed claims ('covered' / 'compliant') must have external evidence.
    Covers: DOD-VT-008-03.
    """
    task_res = get_mock_task_result()

    # Case A: Empty evidence_refs
    claims_a = [
        {
            "claim_id": "CLAIM-VT-001",
            "related_task": "TASK-VT-001",
            "claimed_status": "covered",
            "evidence_refs": [],  # Empty
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    res_a = claim_loader.validate_data(claims_a, task_result=task_res)
    assert res_a.is_valid is False
    assert res_a.claims[0].is_valid is False
    assert any("has no external evidence" in err for err in res_a.claims[0].errors)
    assert any("has no external evidence" in err for err in res_a.errors)
    assert len(res_a.gaps) == 1
    assert "no external evidence" in res_a.gaps[0].reason

    # Case B: Self-referential evidence only
    claims_b = [
        {
            "claim_id": "CLAIM-VT-001",
            "related_task": "TASK-VT-001",
            "claimed_status": "compliant",
            "evidence_refs": ["CLAIM-VT-001"],  # Self-referential
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    res_b = claim_loader.validate_data(claims_b, task_result=task_res)
    assert res_b.is_valid is False
    assert res_b.claims[0].is_valid is False
    assert any("has no external evidence" in err for err in res_b.claims[0].errors)


def test_validate_real_files_load(claim_loader):
    """
    Validate loading the real agent_claims.json file and cross-referencing with the real task_list.json.
    Covers: AC-VT-002-01, AC-VT-002-02, DOD-VT-008-03.
    """
    claims_path = VIBETRACING_DIR / "agent_claims.json"
    task_list_path = DOCS_DIR / "task_list.json"

    if not claims_path.exists() or not task_list_path.exists():
        pytest.skip("Real standard input files do not exist.")

    from vibe_tracing.task_loader import TaskLoader

    task_loader_inst = TaskLoader(SCHEMAS_DIR)
    task_res = task_loader_inst.load_and_validate(task_list_path)
    assert task_res.is_valid is True

    res = claim_loader.load_and_validate(claims_path, task_result=task_res)

    # Since the real agent_claims.json might be empty array [], it should load successfully and be valid
    assert res.is_valid is True, f"Real claims load failed: {res.errors}"
    assert len(res.errors) == 0
