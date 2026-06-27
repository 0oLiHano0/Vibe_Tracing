"""
Tests for ClaimLoader (TASK-VT-008).

Each test function declares its AC/DoD coverage in its docstring.
"""

from pathlib import Path
import pytest

from vibe_tracing.infra.loader.claim_loader import ClaimLoader
from vibe_tracing.infra.loader.task_loader import TaskListLoadResult, Task

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
    Validate a clean and compliant claims list against schema.
    Covers: AC-VT-002-01, AC-VT-002-02.
    """
    data = get_valid_claims_list()

    res = claim_loader.validate_data(data)

    assert res.is_valid is True
    assert len(res.errors) == 0
    assert len(res.gaps) == 0
    assert len(res.claims) == 1
    assert res.claims[0].claim_id == "CLAIM-VT-001"


def test_claim_with_valid_data_passes(claim_loader):
    """
    Validate that claims with valid data pass validation.
    Covers: DOD-VT-008-02, DOD-VT-008-03.
    """
    claims = [
        {
            "claim_id": "CLAIM-VT-001",
            "related_task": "TASK-VT-001",
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    res = claim_loader.validate_data(claims)

    assert res.is_valid is True
    assert len(res.errors) == 0
    assert len(res.gaps) == 0


def test_validate_real_files_load(claim_loader):
    """
    Validate loading the real claims/ directory.
    Covers: AC-VT-002-01, AC-VT-002-02, DOD-VT-008-03.
    """
    claims_path = VIBETRACING_DIR / "claims"

    if not claims_path.exists():
        pytest.skip("Real standard input files do not exist.")

    res = claim_loader.load(claims_path)

    # Claims directory may have CLAIM-*.json files or be empty
    # Empty directory is acceptable (no claims declared yet)
    if not list(claims_path.glob("CLAIM-*.json")):
        assert res.is_valid is False  # Expected: no CLAIM-*.json files found
    else:
        assert res.is_valid is True, f"Real claims load failed: {res.errors}"
