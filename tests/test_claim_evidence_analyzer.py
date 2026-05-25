"""
Unit tests for ClaimEvidenceAnalyzer (TASK-VT-013).
"""

import shutil
from pathlib import Path
import pytest

from vibe_tracing.claim_loader import Claim
from vibe_tracing.core.enums import CoverageStatus
from vibe_tracing.traceability.claim_evidence_analyzer import ClaimEvidenceAnalyzer


@pytest.fixture
def temp_project_dir():
    """Create and clean up a temporary directory inside the workspace for file tests."""
    temp_dir = Path(__file__).parent / "tmp_claim_evidence"
    temp_dir.mkdir(parents=True, exist_ok=True)
    yield temp_dir
    if temp_dir.exists():
        shutil.rmtree(temp_dir)


def test_successful_claim_validation(temp_project_dir) -> None:
    """
    Validate a completed claim with correct tasks, passing tests, and matching files.
    covers: AC-VT-002-01, AC-VT-002-02
    """
    # Create code ref file
    code_file = temp_project_dir / "app.py"
    code_file.write_text("print('hello')")

    # Set file mtime to back in time relative to the claim
    # claim ts: 2026-05-22T10:00:00Z
    # let's set mtime to 1779444000 (equivalent to 2026-05-22T10:00:00Z) or smaller
    # We can just set mtime to 1000000000
    os_time_mtime = 1000000000
    import os

    os.utime(code_file, (os_time_mtime, os_time_mtime))

    claim = Claim(
        claim_id="CLAIM-VT-001",
        related_task="TASK-VT-001",
        claimed_status=CoverageStatus.COVERED.value,
        evidence_refs=["EVIDENCE-VT-002"],
        timestamp="2026-05-22T10:00:00Z",
        code_refs=[
            str(code_file.relative_to(temp_project_dir.parent.parent))
        ],  # relative path from project root
    )

    evidences = [
        # Related task evidence (status is covered)
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "task",
            "covers": ["AC-VT-001-01"],
            "status": CoverageStatus.COVERED.value,
            "details": {"task_id": "TASK-VT-001"},
        },
        # External evidence that backing the claim
        {
            "evidence_id": "EVIDENCE-VT-002",
            "source_type": "test",
            "covers": ["AC-VT-001-01"],
            "status": CoverageStatus.COVERED.value,
        },
    ]

    analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
    res = analyzer.analyze([claim], evidences)

    assert len(res["gaps"]) == 0
    assert len(res["risks"]) == 0
    assert len(res["claims_analysis"]) == 1

    analysis = res["claims_analysis"][0]
    assert analysis["claim_id"] == "CLAIM-VT-001"
    assert analysis["status"] == CoverageStatus.COVERED.value
    assert analysis["evidence_ids"] == ["EVIDENCE-VT-002"]
    assert len(analysis["mismatches"]) == 0


def test_self_referential_or_empty_evidence(temp_project_dir) -> None:
    """
    Validate completed claim with empty or self-referential evidence refs.
    covers: AC-VT-002-01, AC-VT-002-02
    """
    # Empty evidence_refs
    claim_empty = Claim(
        claim_id="CLAIM-VT-001",
        related_task="TASK-VT-001",
        claimed_status=CoverageStatus.COVERED.value,
        evidence_refs=[],
        timestamp="2026-05-22T10:00:00Z",
    )

    # Only self-referential evidence_refs
    claim_self = Claim(
        claim_id="CLAIM-VT-002",
        related_task="TASK-VT-001",
        claimed_status=CoverageStatus.COVERED.value,
        evidence_refs=["CLAIM-VT-002"],
        timestamp="2026-05-22T10:00:00Z",
    )

    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "task",
            "covers": [],
            "status": CoverageStatus.COVERED.value,
            "details": {"task_id": "TASK-VT-001"},
        }
    ]

    analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
    res = analyzer.analyze([claim_empty, claim_self], evidences)

    # 2 gaps should be generated
    assert len(res["gaps"]) == 2
    assert res["gaps"][0]["item_id"] == "CLAIM-VT-001"
    assert res["gaps"][0]["item_type"] == "claim"
    assert "only self-referential or empty" in res["gaps"][0]["reason"]

    assert res["gaps"][1]["item_id"] == "CLAIM-VT-002"
    assert "only self-referential or empty" in res["gaps"][1]["reason"]

    # Risks generated with must severity
    assert len(res["risks"]) == 2
    assert res["risks"][0]["severity"] == "must"
    assert "only self-referential or empty" in res["risks"][0]["description"]

    # Analyzed status should be blocked
    assert len(res["claims_analysis"]) == 2
    assert res["claims_analysis"][0]["status"] == CoverageStatus.BLOCKED.value
    assert res["claims_analysis"][1]["status"] == CoverageStatus.BLOCKED.value


def test_references_non_existent_evidence(temp_project_dir) -> None:
    """
    Validate completed claim referencing non-existent evidence ID.
    covers: AC-VT-002-01
    """
    claim = Claim(
        claim_id="CLAIM-VT-001",
        related_task="TASK-VT-001",
        claimed_status=CoverageStatus.COVERED.value,
        evidence_refs=["EVIDENCE-VT-999"],
        timestamp="2026-05-22T10:00:00Z",
    )

    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "task",
            "covers": [],
            "status": CoverageStatus.COVERED.value,
            "details": {"task_id": "TASK-VT-001"},
        }
    ]

    analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
    res = analyzer.analyze([claim], evidences)

    assert len(res["risks"]) == 1
    assert res["risks"][0]["severity"] == "must"
    assert "references non-existent evidence" in res["risks"][0]["description"]

    assert res["claims_analysis"][0]["status"] == CoverageStatus.LOW_CONFIDENCE.value


def test_references_non_compliant_evidence_status(temp_project_dir) -> None:
    """
    Validate completed claim referencing evidence that failed or is violated.
    covers: AC-VT-002-01
    """
    claim = Claim(
        claim_id="CLAIM-VT-001",
        related_task="TASK-VT-001",
        claimed_status=CoverageStatus.COVERED.value,
        evidence_refs=["EVIDENCE-VT-002"],
        timestamp="2026-05-22T10:00:00Z",
    )

    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "task",
            "covers": [],
            "status": CoverageStatus.COVERED.value,
            "details": {"task_id": "TASK-VT-001"},
        },
        {
            "evidence_id": "EVIDENCE-VT-002",
            "source_type": "test",
            "covers": [],
            "status": CoverageStatus.VIOLATED.value,  # Violated/failed test
        },
    ]

    analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
    res = analyzer.analyze([claim], evidences)

    assert len(res["risks"]) == 1
    assert res["risks"][0]["severity"] == "must"
    assert (
        "references evidence EVIDENCE-VT-002 which has status 'violated'"
        in res["risks"][0]["description"]
    )

    assert res["claims_analysis"][0]["status"] == CoverageStatus.VIOLATED.value


def test_task_not_completed(temp_project_dir) -> None:
    """
    Validate completed claim whose related task status is not covered (completed).
    covers: AC-VT-002-02
    """
    claim = Claim(
        claim_id="CLAIM-VT-001",
        related_task="TASK-VT-001",
        claimed_status=CoverageStatus.COVERED.value,
        evidence_refs=["EVIDENCE-VT-002"],
        timestamp="2026-05-22T10:00:00Z",
    )

    evidences = [
        # Related task is in_progress / partial
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "task",
            "covers": [],
            "status": CoverageStatus.PARTIAL.value,
            "details": {"task_id": "TASK-VT-001"},
        },
        {
            "evidence_id": "EVIDENCE-VT-002",
            "source_type": "test",
            "covers": [],
            "status": CoverageStatus.COVERED.value,
        },
    ]

    analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
    res = analyzer.analyze([claim], evidences)

    assert len(res["risks"]) == 1
    assert res["risks"][0]["severity"] == "must"
    assert "related task TASK-VT-001 is not completed" in res["risks"][0]["description"]

    assert res["claims_analysis"][0]["status"] == CoverageStatus.LOW_CONFIDENCE.value


def test_task_non_existent(temp_project_dir) -> None:
    """
    Validate completed claim referencing non-existent task ID.
    covers: AC-VT-002-02
    """
    claim = Claim(
        claim_id="CLAIM-VT-001",
        related_task="TASK-VT-999",
        claimed_status=CoverageStatus.COVERED.value,
        evidence_refs=["EVIDENCE-VT-002"],
        timestamp="2026-05-22T10:00:00Z",
    )

    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-002",
            "source_type": "test",
            "covers": [],
            "status": CoverageStatus.COVERED.value,
        }
    ]

    analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
    res = analyzer.analyze([claim], evidences)

    assert len(res["risks"]) == 1
    assert res["risks"][0]["severity"] == "must"
    assert "references non-existent task TASK-VT-999" in res["risks"][0]["description"]

    assert res["claims_analysis"][0]["status"] == CoverageStatus.LOW_CONFIDENCE.value


def test_ac_test_missing(temp_project_dir) -> None:
    """
    Validate completed claim whose related task covers ACs, but they lack test coverage.
    covers: AC-VT-002-02
    """
    claim = Claim(
        claim_id="CLAIM-VT-001",
        related_task="TASK-VT-001",
        claimed_status=CoverageStatus.COVERED.value,
        evidence_refs=["EVIDENCE-VT-002"],
        timestamp="2026-05-22T10:00:00Z",
    )

    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "task",
            # Related task covers AC-VT-001-01
            "covers": ["AC-VT-001-01"],
            "status": CoverageStatus.COVERED.value,
            "details": {"task_id": "TASK-VT-001"},
        },
        {
            "evidence_id": "EVIDENCE-VT-002",
            "source_type": "test",
            # This test covers something else, leaving AC-VT-001-01 untested
            "covers": ["AC-VT-001-02"],
            "status": CoverageStatus.COVERED.value,
        },
    ]

    analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
    res = analyzer.analyze([claim], evidences)

    assert len(res["risks"]) == 1
    assert res["risks"][0]["severity"] == "must"
    assert (
        "related AC AC-VT-001-01 has no test coverage" in res["risks"][0]["description"]
    )

    assert res["claims_analysis"][0]["status"] == CoverageStatus.LOW_CONFIDENCE.value


def test_ac_test_failed(temp_project_dir) -> None:
    """
    Validate completed claim with failed tests for its related ACs.
    covers: AC-VT-002-03
    """
    claim = Claim(
        claim_id="CLAIM-VT-001",
        related_task="TASK-VT-001",
        claimed_status=CoverageStatus.COVERED.value,
        evidence_refs=["EVIDENCE-VT-002"],
        timestamp="2026-05-22T10:00:00Z",
    )

    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "task",
            "covers": ["AC-VT-001-01"],
            "status": CoverageStatus.COVERED.value,
            "details": {"task_id": "TASK-VT-001"},
        },
        {
            "evidence_id": "EVIDENCE-VT-002",
            "source_type": "test",
            "covers": ["AC-VT-001-01"],
            "status": CoverageStatus.VIOLATED.value,  # failed test!
        },
    ]

    analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
    res = analyzer.analyze([claim], evidences)

    # 1 risk for failed AC-VT-001-01 test, 1 risk for evidence status being violated
    assert len(res["risks"]) == 2
    assert res["risks"][0]["severity"] == "must"
    assert (
        "has failed tests" in res["risks"][1]["description"]
        or "has failed tests" in res["risks"][0]["description"]
    )

    assert res["claims_analysis"][0]["status"] == CoverageStatus.VIOLATED.value


def test_code_ref_non_existent(temp_project_dir) -> None:
    """
    Validate completed claim referencing non-existent file path.
    covers: AC-VT-002-03
    """
    claim = Claim(
        claim_id="CLAIM-VT-001",
        related_task="TASK-VT-001",
        claimed_status=CoverageStatus.COVERED.value,
        evidence_refs=["EVIDENCE-VT-002"],
        timestamp="2026-05-22T10:00:00Z",
        code_refs=["src/non_existent_file.py"],  # Non-existent path
    )

    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "task",
            "covers": [],
            "status": CoverageStatus.COVERED.value,
            "details": {"task_id": "TASK-VT-001"},
        },
        {
            "evidence_id": "EVIDENCE-VT-002",
            "source_type": "test",
            "covers": [],
            "status": CoverageStatus.COVERED.value,
        },
    ]

    analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
    res = analyzer.analyze([claim], evidences)

    assert len(res["risks"]) == 1
    assert res["risks"][0]["severity"] == "must"
    assert "references non-existent code path" in res["risks"][0]["description"]

    assert res["claims_analysis"][0]["status"] == CoverageStatus.LOW_CONFIDENCE.value


def test_code_ref_outdated(temp_project_dir) -> None:
    """
    Validate completed claim referencing file modified after the claim timestamp.
    covers: AC-VT-002-03
    """
    # Create code ref file
    code_file = temp_project_dir / "app.py"
    code_file.write_text("print('outdated')")

    # Set claim timestamp: 2026-05-22T10:00:00Z
    # Set file mtime to a later time: e.g. time.time() which is current year (2026) or far in the future
    # Let's explicitly set mtime to 1800000000 (after 2026-05-22)
    os_time_mtime = 1800000000
    import os

    os.utime(code_file, (os_time_mtime, os_time_mtime))

    claim = Claim(
        claim_id="CLAIM-VT-001",
        related_task="TASK-VT-001",
        claimed_status=CoverageStatus.COVERED.value,
        evidence_refs=["EVIDENCE-VT-002"],
        timestamp="2026-05-22T10:00:00Z",
        code_refs=[str(code_file.relative_to(temp_project_dir.parent.parent))],
    )

    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "task",
            "covers": [],
            "status": CoverageStatus.COVERED.value,
            "details": {"task_id": "TASK-VT-001"},
        },
        {
            "evidence_id": "EVIDENCE-VT-002",
            "source_type": "test",
            "covers": [],
            "status": CoverageStatus.COVERED.value,
        },
    ]

    analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
    res = analyzer.analyze([claim], evidences)

    assert len(res["risks"]) == 1
    assert res["risks"][0]["severity"] == "should"
    assert "was modified after the claim timestamp" in res["risks"][0]["description"]

    assert res["claims_analysis"][0]["status"] == CoverageStatus.LOW_CONFIDENCE.value
