"""
Tests for ClaimLoader.
"""

from pathlib import Path
import pytest

from vibe_tracing.infra.loader.claim_loader import ClaimLoader

@pytest.fixture
def claim_loader():
    """Return a ClaimLoader instance."""
    return ClaimLoader()


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


def test_valid_claims_list_passes(claim_loader):
    data = get_valid_claims_list()
    res = claim_loader.validate_data(data)
    assert res.is_valid is True
    assert len(res.errors) == 0
    assert len(res.claims) == 1
    assert res.claims[0].claim_id == "CLAIM-VT-001"


def test_claim_with_valid_data_passes(claim_loader):
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
