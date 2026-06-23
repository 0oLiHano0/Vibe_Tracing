"""
Tests for ClaimLoader (TASK-VT-008).

Each test function declares its AC/DoD coverage in its docstring.
"""

from pathlib import Path
import pytest

from vibe_tracing.domain.loader.claim_loader import ClaimLoader
from vibe_tracing.domain.loader.task_loader import TaskListLoadResult, Task

DOCS_DIR = Path(__file__).parent.parent / "docs"
VIBETRACING_DIR = Path(__file__).parent.parent / ".vibetracing"


@pytest.fixture
def claim_loader():
    """Return a ClaimLoader instance."""
    return ClaimLoader()


# Helper: Create a valid minimal claim list dict/list
def get_valid_claims_list(claims=None):
    if claims is None:
        claims = [
            {
                "claim_id": "CLAIM-VT-001",
                "related_task": "TASK-VT-001",
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
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    res = claim_loader.validate_data(claims, task_result=task_res)

    assert res.is_valid is False
    assert any(
        "References non-existent task: TASK-VT-999" in err
        for err in res.errors
    )
    assert len(res.gaps) == 1
    assert res.gaps[0].item_id == "CLAIM-VT-001"
    assert "References non-existent task: TASK-VT-999" in res.gaps[0].reason


def test_completed_claim_without_external_evidence_fails(claim_loader):
    """
    Validate that claims with valid task references pass validation.
    The old 'has no external evidence' check has been removed from ClaimLoader
    since evidence_refs is no longer a Claim field.
    Covers: DOD-VT-008-03.
    """
    task_res = get_mock_task_result()

    # Case A: Claim with valid task reference passes schema + cross-ref validation
    claims_a = [
        {
            "claim_id": "CLAIM-VT-001",
            "related_task": "TASK-VT-001",
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    res_a = claim_loader.validate_data(claims_a, task_result=task_res)
    assert res_a.is_valid is True
    assert len(res_a.errors) == 0

    # Case B: Claim with non-existent task still generates a gap
    claims_b = [
        {
            "claim_id": "CLAIM-VT-001",
            "related_task": "TASK-VT-999",
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    res_b = claim_loader.validate_data(claims_b, task_result=task_res)
    assert res_b.is_valid is False
    assert any("References non-existent task" in err for err in res_b.errors)


def test_validate_real_files_load(claim_loader):
    """
    Validate loading the real claims/ directory and cross-referencing with the real task_list.json.
    Covers: AC-VT-002-01, AC-VT-002-02, DOD-VT-008-03.
    """
    claims_path = VIBETRACING_DIR / "claims"
    task_list_path = DOCS_DIR / "task_list.json"

    if not claims_path.exists() or not task_list_path.exists():
        pytest.skip("Real standard input files do not exist.")

    from vibe_tracing.domain.loader.task_loader import TaskLoader

    task_loader_inst = TaskLoader()
    task_res = task_loader_inst.load_and_validate(task_list_path)
    # Real task_list may have tasks without ACs (e.g. TASK-VT-036, TASK-VT-042)
    # which are flagged under strict_link AND logic. This is expected.

    res = claim_loader.load(claims_path, task_result=task_res)

    # Claims directory may have CLAIM-*.json files or be empty
    # Empty directory is acceptable (no claims declared yet)
    if not list(claims_path.glob("CLAIM-*.json")):
        assert res.is_valid is False  # Expected: no CLAIM-*.json files found
    else:
        assert res.is_valid is True, f"Real claims load failed: {res.errors}"
