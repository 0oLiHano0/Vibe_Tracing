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


def test_claim_lookup_by_nodeid_and_source_path(temp_project_dir) -> None:
    """
    Validate that completed claims referencing evidence by nodeid or source_path are correctly verified.
    covers: AC-VT-002-01
    """
    code_file = temp_project_dir / "app.py"
    code_file.write_text("print('hello')")

    os_time_mtime = 1000000000
    import os

    os.utime(code_file, (os_time_mtime, os_time_mtime))

    claim = Claim(
        claim_id="CLAIM-VT-001",
        related_task="TASK-VT-001",
        claimed_status=CoverageStatus.COVERED.value,
        evidence_refs=["tests/my_test.py::test_func"],
        timestamp="2026-05-22T10:00:00Z",
        code_refs=[str(code_file.relative_to(temp_project_dir.parent.parent))],
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
            "source_path": "tests/my_test.py::test_func",
            "covers": ["AC-VT-001-01"],
            "status": CoverageStatus.COVERED.value,
            "details": {
                "nodeid": "tests/my_test.py::test_func",
                "outcome": "passed",
            },
        },
    ]

    analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
    res = analyzer.analyze([claim], evidences)

    assert len(res["gaps"]) == 0
    assert len(res["risks"]) == 0
    assert len(res["claims_analysis"]) == 1
    assert res["claims_analysis"][0]["status"] == CoverageStatus.COVERED.value


def test_claim_lookup_multi_matching_and_fail_fast(temp_project_dir) -> None:
    """
    Validate that completed claims referencing a NodeID with multiple executions are verified correctly (fail-fast and conflict warning).
    covers: AC-VT-002-04
    """
    code_file = temp_project_dir / "app.py"
    code_file.write_text("print('hello')")
    os_time_mtime = 1000000000
    import os

    os.utime(code_file, (os_time_mtime, os_time_mtime))

    # Test Case 1: Both pass -> Claim passes and links both evidences
    claim1 = Claim(
        claim_id="CLAIM-VT-001",
        related_task="TASK-VT-001",
        claimed_status=CoverageStatus.COVERED.value,
        evidence_refs=["tests/my_test.py::test_func"],
        timestamp="2026-05-22T10:00:00Z",
        code_refs=[str(code_file.relative_to(temp_project_dir.parent.parent))],
    )

    evidences1 = [
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
            "source_path": "tests/my_test.py::test_func",
            "covers": ["AC-VT-001-01"],
            "status": CoverageStatus.COVERED.value,
            "details": {"nodeid": "tests/my_test.py::test_func"},
        },
        {
            "evidence_id": "EVIDENCE-VT-003",
            "source_type": "test",
            "source_path": "tests/my_test.py::test_func",
            "covers": ["AC-VT-001-01"],
            "status": CoverageStatus.COVERED.value,
            "details": {"nodeid": "tests/my_test.py::test_func"},
        },
    ]

    analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
    res1 = analyzer.analyze([claim1], evidences1)
    assert len(res1["risks"]) == 0
    assert res1["claims_analysis"][0]["status"] == CoverageStatus.COVERED.value
    # Links both evidence IDs
    assert sorted(res1["claims_analysis"][0]["evidence_ids"]) == [
        "EVIDENCE-VT-002",
        "EVIDENCE-VT-003",
    ]

    # Test Case 2: One passes, one fails -> Fail-fast: claim becomes violated + Conflict warning
    evidences2 = [
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
            "source_path": "tests/my_test.py::test_func",
            "covers": ["AC-VT-001-01"],
            "status": CoverageStatus.COVERED.value,
            "details": {"nodeid": "tests/my_test.py::test_func"},
        },
        {
            "evidence_id": "EVIDENCE-VT-003",
            "source_type": "test",
            "source_path": "tests/my_test.py::test_func",
            "covers": ["AC-VT-001-01"],
            "status": CoverageStatus.VIOLATED.value,  # failed run!
            "details": {"nodeid": "tests/my_test.py::test_func"},
        },
    ]

    res2 = analyzer.analyze([claim1], evidences2)
    assert res2["claims_analysis"][0]["status"] == CoverageStatus.VIOLATED.value
    # There should be:
    # 1. A risk for the failed evidence (must)
    # 2. A risk for the conflict (should)
    # 3. An additional risk for AC test coverage checks (must)
    # Total = 3 risks
    assert len(res2["risks"]) == 3
    assert any(r["severity"] == "must" for r in res2["risks"])
    assert any(r["severity"] == "should" for r in res2["risks"])
    assert any(
        "conflicting statuses" in m for m in res2["claims_analysis"][0]["mismatches"]
    )
    assert any(
        "which has status 'violated'" in m
        for m in res2["claims_analysis"][0]["mismatches"]
    )


def test_code_ref_outdated_skipped_in_ci(temp_project_dir, monkeypatch) -> None:
    """
    Validate that if the CI environment variable is set to true, the outdated file modification check is bypassed.
    """
    import os

    # Create code ref file
    code_file = temp_project_dir / "app.py"
    code_file.write_text("print('outdated')")

    # Set file mtime to a later time (outdated)
    os_time_mtime = 1800000000
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

    # 1. Set CI=true -> Check should be skipped, no risks/mismatches should be produced
    monkeypatch.setenv("CI", "true")
    res_ci = analyzer.analyze([claim], evidences)
    assert len(res_ci["risks"]) == 0
    assert len(res_ci["claims_analysis"][0]["mismatches"]) == 0
    assert res_ci["claims_analysis"][0]["status"] == CoverageStatus.COVERED.value

    # 2. Set CI=false -> Check should run, should risk must be produced
    monkeypatch.setenv("CI", "false")
    res_no_ci = analyzer.analyze([claim], evidences)
    assert len(res_no_ci["risks"]) == 1
    assert res_no_ci["risks"][0]["severity"] == "should"
    assert "was modified after the claim timestamp" in res_no_ci["risks"][0]["description"]
    assert res_no_ci["claims_analysis"][0]["status"] == CoverageStatus.LOW_CONFIDENCE.value


def test_claim_test_refs_cover_ac(temp_project_dir) -> None:
    """
    Claim's test_refs includes a test that covers the related AC.
    No risk should be raised from covers consistency check.
    """
    # Create test file so the file-existence check does not flag it
    import os

    test_file = temp_project_dir / "tests" / "test_feature.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_feature(): pass")
    # Set mtime to before the claim timestamp (2026-05-22T10:00:00Z)
    os.utime(test_file, (1000000000, 1000000000))

    claim = Claim(
        claim_id="CLAIM-VT-001",
        related_task="TASK-VT-001",
        claimed_status=CoverageStatus.COVERED.value,
        evidence_refs=["EVIDENCE-VT-002"],
        timestamp="2026-05-22T10:00:00Z",
        test_refs=[str(test_file.relative_to(temp_project_dir.parent.parent))],
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
            "source_path": str(test_file.relative_to(temp_project_dir.parent.parent)),
            "covers": ["AC-VT-001-01"],
            "status": CoverageStatus.COVERED.value,
        },
    ]

    analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
    res = analyzer.analyze([claim], evidences)

    # No risks at all - claim's test_refs covers the AC
    assert len(res["risks"]) == 0
    assert res["claims_analysis"][0]["status"] == CoverageStatus.COVERED.value


def test_claim_test_refs_miss_ac_coverage(temp_project_dir) -> None:
    """
    Claim's test_refs has tests but none cover the AC, while other tests do.
    A must risk with 'test_covers_mismatch' should be raised.
    """
    # Create both test files so the file-existence check does not flag them
    import os

    tests_dir = temp_project_dir / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_feature = tests_dir / "test_feature.py"
    test_feature.write_text("def test_feature(): pass")
    test_other = tests_dir / "test_other.py"
    test_other.write_text("def test_other(): pass")
    # Set mtime to before the claim timestamp (2026-05-22T10:00:00Z)
    os.utime(test_feature, (1000000000, 1000000000))
    os.utime(test_other, (1000000000, 1000000000))

    root = temp_project_dir.parent.parent
    claim = Claim(
        claim_id="CLAIM-VT-001",
        related_task="TASK-VT-001",
        claimed_status=CoverageStatus.COVERED.value,
        evidence_refs=["EVIDENCE-VT-002"],
        timestamp="2026-05-22T10:00:00Z",
        test_refs=[str(test_other.relative_to(root))],
    )

    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "task",
            "covers": ["AC-VT-001-01"],
            "status": CoverageStatus.COVERED.value,
            "details": {"task_id": "TASK-VT-001"},
        },
        # This test covers the AC but is NOT in claim's test_refs
        {
            "evidence_id": "EVIDENCE-VT-002",
            "source_type": "test",
            "source_path": str(test_feature.relative_to(root)),
            "covers": ["AC-VT-001-01"],
            "status": CoverageStatus.COVERED.value,
        },
        # This test is in claim's test_refs but does NOT cover the AC
        {
            "evidence_id": "EVIDENCE-VT-003",
            "source_type": "test",
            "source_path": str(test_other.relative_to(root)),
            "covers": ["AC-VT-001-02"],
            "status": CoverageStatus.COVERED.value,
        },
    ]

    analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
    res = analyzer.analyze([claim], evidences)

    # Should have exactly 1 risk for test_covers_mismatch
    covers_risks = [r for r in res["risks"] if r.get("risk_category") == "test_covers_mismatch"]
    assert len(covers_risks) == 1
    assert covers_risks[0]["severity"] == "must"
    assert "AC-VT-001-01" in covers_risks[0]["description"]

    assert res["claims_analysis"][0]["status"] == CoverageStatus.LOW_CONFIDENCE.value


def test_claim_no_test_refs_skips_check(temp_project_dir) -> None:
    """
    Claim has no test_refs -> covers consistency check is skipped.
    No risk from this check should be raised.
    """
    claim = Claim(
        claim_id="CLAIM-VT-001",
        related_task="TASK-VT-001",
        claimed_status=CoverageStatus.COVERED.value,
        evidence_refs=["EVIDENCE-VT-002"],
        timestamp="2026-05-22T10:00:00Z",
        # No test_refs
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
            "source_path": "tests/test_feature.py",
            "covers": ["AC-VT-001-01"],
            "status": CoverageStatus.COVERED.value,
        },
    ]

    analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
    res = analyzer.analyze([claim], evidences)

    # No test_covers_mismatch risks should be raised
    covers_risks = [r for r in res["risks"] if r.get("risk_category") == "test_covers_mismatch"]
    assert len(covers_risks) == 0
    assert res["claims_analysis"][0]["status"] == CoverageStatus.COVERED.value


# ============================================================================
# Tests for Claim Invalidation Detection (CLAIM-TASK-005)
# ============================================================================


class TestClaimInvalidation:
    """Tests for claim auto-invalidation by file change detection."""

    def test_file_hash_change_triggers_invalidation(self, temp_project_dir) -> None:
        """When a referenced file's hash changes, claim is marked needs_reverification."""
        import hashlib

        # Create a code file
        code_file = temp_project_dir / "app.py"
        original_content = "print('original')"
        code_file.write_text(original_content)
        original_hash = hashlib.sha256(original_content.encode()).hexdigest()

        claim = Claim(
            claim_id="CLAIM-VT-001",
            related_task="TASK-VT-001",
            claimed_status=CoverageStatus.COVERED.value,
            evidence_refs=["EVIDENCE-VT-002"],
            timestamp="2026-05-22T10:00:00Z",
            code_refs=[str(code_file.relative_to(temp_project_dir.parent.parent))],
        )

        # Stored fingerprints reflect the original content
        stored_fingerprints = {
            "CLAIM-VT-001": {
                "timestamp": "2026-05-22T10:00:00Z",
                "fingerprints": {
                    str(code_file.relative_to(temp_project_dir.parent.parent)): original_hash,
                },
            }
        }

        # Change the file content after fingerprints were stored
        code_file.write_text("print('modified content')")

        analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
        result = analyzer._check_invalidation(claim, stored_fingerprints)

        assert result is not None
        assert result["claim_id"] == "CLAIM-VT-001"
        assert result["status"] == CoverageStatus.NEEDS_REVERIFICATION.value
        assert any(
            "changed" in f.get("reason", "").lower() or "hash" in f.get("reason", "").lower()
            for f in result.get("files", [result])
        )

    def test_file_hash_unchanged_no_invalidation(self, temp_project_dir) -> None:
        """When referenced files haven't changed, no invalidation."""
        import hashlib

        code_file = temp_project_dir / "app.py"
        content = "print('stable')"
        code_file.write_text(content)
        file_hash = hashlib.sha256(content.encode()).hexdigest()

        claim = Claim(
            claim_id="CLAIM-VT-001",
            related_task="TASK-VT-001",
            claimed_status=CoverageStatus.COVERED.value,
            evidence_refs=["EVIDENCE-VT-002"],
            timestamp="2026-05-22T10:00:00Z",
            code_refs=[str(code_file.relative_to(temp_project_dir.parent.parent))],
        )

        stored_fingerprints = {
            "CLAIM-VT-001": {
                "timestamp": "2026-05-22T10:00:00Z",
                "fingerprints": {
                    str(code_file.relative_to(temp_project_dir.parent.parent)): file_hash,
                },
            }
        }

        analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
        result = analyzer._check_invalidation(claim, stored_fingerprints)

        assert result is None

    def test_deleted_file_triggers_invalidation(self, temp_project_dir) -> None:
        """When a referenced file is deleted, claim is invalidated."""
        import hashlib

        code_file = temp_project_dir / "app.py"
        content = "print('will be deleted')"
        code_file.write_text(content)
        file_hash = hashlib.sha256(content.encode()).hexdigest()

        claim = Claim(
            claim_id="CLAIM-VT-001",
            related_task="TASK-VT-001",
            claimed_status=CoverageStatus.COVERED.value,
            evidence_refs=["EVIDENCE-VT-002"],
            timestamp="2026-05-22T10:00:00Z",
            code_refs=[str(code_file.relative_to(temp_project_dir.parent.parent))],
        )

        stored_fingerprints = {
            "CLAIM-VT-001": {
                "timestamp": "2026-05-22T10:00:00Z",
                "fingerprints": {
                    str(code_file.relative_to(temp_project_dir.parent.parent)): file_hash,
                },
            }
        }

        # Delete the file
        code_file.unlink()

        analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
        result = analyzer._check_invalidation(claim, stored_fingerprints)

        assert result is not None
        assert result["claim_id"] == "CLAIM-VT-001"
        assert result["status"] == CoverageStatus.NEEDS_REVERIFICATION.value
        # Should indicate the file was deleted
        assert any(
            "deleted" in f.get("reason", "").lower() or "missing" in f.get("reason", "").lower()
            for f in result.get("files", [result])
        )

    def test_no_stored_fingerprints_skips_check(self, temp_project_dir) -> None:
        """When no fingerprints exist for a claim, skip invalidation check."""
        code_file = temp_project_dir / "app.py"
        code_file.write_text("print('hello')")

        claim = Claim(
            claim_id="CLAIM-VT-001",
            related_task="TASK-VT-001",
            claimed_status=CoverageStatus.COVERED.value,
            evidence_refs=["EVIDENCE-VT-002"],
            timestamp="2026-05-22T10:00:00Z",
            code_refs=[str(code_file.relative_to(temp_project_dir.parent.parent))],
        )

        # Empty stored fingerprints -- no entry for this claim
        stored_fingerprints: dict = {}

        analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
        result = analyzer._check_invalidation(claim, stored_fingerprints)

        assert result is None

    def test_fingerprints_file_not_found_skips_check(self, temp_project_dir) -> None:
        """When claim_fingerprints.json doesn't exist, skip check without errors."""
        code_file = temp_project_dir / "app.py"
        code_file.write_text("print('hello')")

        claim = Claim(
            claim_id="CLAIM-VT-001",
            related_task="TASK-VT-001",
            claimed_status=CoverageStatus.COVERED.value,
            evidence_refs=["EVIDENCE-VT-002"],
            timestamp="2026-05-22T10:00:00Z",
            code_refs=[str(code_file.relative_to(temp_project_dir.parent.parent))],
        )

        analyzer = ClaimEvidenceAnalyzer(temp_project_dir.parent.parent)
        # Passing None as stored_fingerprints simulates the fingerprint file not existing
        result = analyzer._check_invalidation(claim, None)

        assert result is None

