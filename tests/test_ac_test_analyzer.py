"""
Unit tests for AcTestAnalyzer (TASK-VT-012).
"""

from vibe_tracing.prd_parser import Requirement, AcceptanceCriteria
from vibe_tracing.traceability.ac_test_analyzer import AcTestAnalyzer
from vibe_tracing.core.enums import CoverageStatus


def test_successful_test_coverage() -> None:
    """covers: AC-VT-001-02, AC-VT-008-01"""
    ac = AcceptanceCriteria(
        ac_id="AC-VT-001-01", title="AC 1", is_testing_required=True
    )
    req = Requirement(
        req_id="REQ-VT-001", title="Req 1", priority="must", category="functional", acceptance_criteria=[ac]
    )

    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "test",
            "covers": ["AC-VT-001-01"],
            "status": CoverageStatus.COVERED.value,
        }
    ]

    analyzer = AcTestAnalyzer()
    res = analyzer.analyze([req], evidences)

    coverage = res["ac_coverage"]
    assert len(coverage) == 1
    assert coverage[0]["ac_id"] == "AC-VT-001-01"
    assert coverage[0]["status"] == CoverageStatus.COVERED.value
    assert coverage[0]["evidence_ids"] == ["EVIDENCE-VT-001"]
    assert len(res["gaps"]) == 0


def test_failed_test_non_coverage() -> None:
    """covers: AC-VT-001-02, AC-VT-008-01"""
    ac = AcceptanceCriteria(
        ac_id="AC-VT-001-01", title="AC 1", is_testing_required=True
    )
    req = Requirement(
        req_id="REQ-VT-001", title="Req 1", priority="must", category="functional", acceptance_criteria=[ac]
    )

    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "test",
            "covers": ["AC-VT-001-01"],
            "status": CoverageStatus.VIOLATED.value,  # failed outcome
        }
    ]

    analyzer = AcTestAnalyzer()
    res = analyzer.analyze([req], evidences)

    coverage = res["ac_coverage"]
    assert len(coverage) == 1
    assert coverage[0]["ac_id"] == "AC-VT-001-01"
    assert coverage[0]["status"] == CoverageStatus.MISSING.value
    assert coverage[0]["evidence_ids"] == []

    gaps = res["gaps"]
    assert len(gaps) == 1
    assert gaps[0]["item_id"] == "AC-VT-001-01"
    assert gaps[0]["item_type"] == "ac"
    assert "missing passing test coverage" in gaps[0]["reason"]


def test_no_covers_tag_non_coverage() -> None:
    """covers: AC-VT-001-02, AC-VT-008-01"""
    ac = AcceptanceCriteria(
        ac_id="AC-VT-001-01", title="AC 1", is_testing_required=True
    )
    req = Requirement(
        req_id="REQ-VT-001", title="Req 1", priority="must", category="functional", acceptance_criteria=[ac]
    )

    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "test",
            "covers": ["AC-VT-001-02"],  # covers something else
            "status": CoverageStatus.COVERED.value,
        }
    ]

    analyzer = AcTestAnalyzer()
    res = analyzer.analyze([req], evidences)

    coverage = res["ac_coverage"]
    assert len(coverage) == 1
    assert coverage[0]["ac_id"] == "AC-VT-001-01"
    assert coverage[0]["status"] == CoverageStatus.MISSING.value
    assert coverage[0]["evidence_ids"] == []

    gaps = res["gaps"]
    assert len(gaps) == 1
    assert gaps[0]["item_id"] == "AC-VT-001-01"
    assert gaps[0]["item_type"] == "ac"


def test_missing_test_with_gap() -> None:
    """covers: AC-VT-001-02, AC-VT-008-01"""
    ac = AcceptanceCriteria(
        ac_id="AC-VT-001-01", title="AC 1", is_testing_required=True
    )
    req = Requirement(
        req_id="REQ-VT-001", title="Req 1", priority="must", category="functional", acceptance_criteria=[ac]
    )

    analyzer = AcTestAnalyzer()
    res = analyzer.analyze([req], [])

    coverage = res["ac_coverage"]
    assert len(coverage) == 1
    assert coverage[0]["ac_id"] == "AC-VT-001-01"
    assert coverage[0]["status"] == CoverageStatus.MISSING.value

    gaps = res["gaps"]
    assert len(gaps) == 1
    assert gaps[0]["item_id"] == "AC-VT-001-01"
    assert gaps[0]["item_type"] == "ac"


def test_missing_test_no_gap_not_must_req() -> None:
    """covers: AC-VT-001-02, AC-VT-008-01"""
    ac = AcceptanceCriteria(
        ac_id="AC-VT-001-01", title="AC 1", is_testing_required=True
    )
    req = Requirement(
        req_id="REQ-VT-001", title="Req 1", priority="should", category="functional", acceptance_criteria=[ac]
    )

    analyzer = AcTestAnalyzer()
    res = analyzer.analyze([req], [])

    coverage = res["ac_coverage"]
    assert len(coverage) == 1
    assert coverage[0]["ac_id"] == "AC-VT-001-01"
    assert coverage[0]["status"] == CoverageStatus.MISSING.value
    assert len(res["gaps"]) == 0


def test_missing_test_no_gap_testing_not_required() -> None:
    """covers: AC-VT-001-02, AC-VT-008-01"""
    ac = AcceptanceCriteria(
        ac_id="AC-VT-001-01", title="AC 1", is_testing_required=False
    )
    req = Requirement(
        req_id="REQ-VT-001", title="Req 1", priority="must", category="functional", acceptance_criteria=[ac]
    )

    analyzer = AcTestAnalyzer()
    res = analyzer.analyze([req], [])

    coverage = res["ac_coverage"]
    assert len(coverage) == 1
    assert coverage[0]["ac_id"] == "AC-VT-001-01"
    assert coverage[0]["status"] == CoverageStatus.MISSING.value
    assert len(res["gaps"]) == 0
