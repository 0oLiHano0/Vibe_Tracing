"""
Unit tests for RequirementTaskAnalyzer (TASK-VT-011).
"""

from vibe_tracing.prd_parser import Requirement
from vibe_tracing.traceability.requirement_task_analyzer import RequirementTaskAnalyzer
from vibe_tracing.core.enums import CoverageStatus


def test_full_coverage() -> None:
    """covers: AC-VT-001-01, AC-VT-001-03"""
    req = Requirement(req_id="REQ-VT-001", title="Traceability", priority="must")

    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "task",
            "covers": ["REQ-VT-001", "AC-VT-001-01"],
            "status": CoverageStatus.COVERED.value,
        },
        {
            "evidence_id": "EVIDENCE-VT-002",
            "source_type": "task",
            "covers": ["REQ-VT-001", "AC-VT-001-02"],
            "status": CoverageStatus.COVERED.value,
        },
    ]

    analyzer = RequirementTaskAnalyzer()
    res = analyzer.analyze([req], evidences)

    coverage = res["requirement_coverage"]
    assert len(coverage) == 1
    assert coverage[0]["req_id"] == "REQ-VT-001"
    assert coverage[0]["status"] == CoverageStatus.COVERED.value
    assert coverage[0]["evidence_ids"] == ["EVIDENCE-VT-001", "EVIDENCE-VT-002"]
    assert len(res["gaps"]) == 0


def test_partial_coverage() -> None:
    """covers: AC-VT-001-01, AC-VT-001-03"""
    req = Requirement(req_id="REQ-VT-001", title="Traceability", priority="must")

    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "task",
            "covers": ["REQ-VT-001", "AC-VT-001-01"],
            "status": CoverageStatus.COVERED.value,
        },
        {
            "evidence_id": "EVIDENCE-VT-002",
            "source_type": "task",
            "covers": ["REQ-VT-001"],
            "status": CoverageStatus.PARTIAL.value,
        },
    ]

    analyzer = RequirementTaskAnalyzer()
    res = analyzer.analyze([req], evidences)

    coverage = res["requirement_coverage"]
    assert len(coverage) == 1
    assert coverage[0]["req_id"] == "REQ-VT-001"
    assert coverage[0]["status"] == CoverageStatus.PARTIAL.value
    assert coverage[0]["evidence_ids"] == ["EVIDENCE-VT-001", "EVIDENCE-VT-002"]
    assert len(res["gaps"]) == 0


def test_missing_coverage_with_gap() -> None:
    """covers: AC-VT-001-01, AC-VT-001-04"""
    req = Requirement(req_id="REQ-VT-001", title="Traceability", priority="must")

    analyzer = RequirementTaskAnalyzer()
    res = analyzer.analyze([req], [])

    coverage = res["requirement_coverage"]
    assert len(coverage) == 1
    assert coverage[0]["req_id"] == "REQ-VT-001"
    assert coverage[0]["status"] == CoverageStatus.MISSING.value
    assert coverage[0]["evidence_ids"] == []

    gaps = res["gaps"]
    assert len(gaps) == 1
    assert gaps[0]["item_id"] == "REQ-VT-001"
    assert gaps[0]["item_type"] == "requirement"
    assert "no task coverage" in gaps[0]["reason"]


def test_missing_coverage_no_gap() -> None:
    """covers: AC-VT-001-01, AC-VT-001-04"""
    req = Requirement(req_id="REQ-VT-001", title="Traceability", priority="should")

    analyzer = RequirementTaskAnalyzer()
    res = analyzer.analyze([req], [])

    coverage = res["requirement_coverage"]
    assert len(coverage) == 1
    assert coverage[0]["req_id"] == "REQ-VT-001"
    assert coverage[0]["status"] == CoverageStatus.MISSING.value
    assert coverage[0]["evidence_ids"] == []

    assert len(res["gaps"]) == 0


def test_unclear_priority_or_status() -> None:
    """covers: AC-VT-001-01, AC-VT-001-03"""
    req_unclear_pri = Requirement(
        req_id="REQ-VT-001", title="Unclear Req", priority="unclear"
    )
    req_must = Requirement(req_id="REQ-VT-002", title="Must Req", priority="must")

    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "task",
            "covers": ["REQ-VT-001"],
            "status": CoverageStatus.COVERED.value,
        },
        {
            "evidence_id": "EVIDENCE-VT-002",
            "source_type": "task",
            "covers": ["REQ-VT-002"],
            "status": CoverageStatus.UNCLEAR.value,
        },
    ]

    analyzer = RequirementTaskAnalyzer()
    res = analyzer.analyze([req_unclear_pri, req_must], evidences)

    coverage = res["requirement_coverage"]
    assert len(coverage) == 2

    cov_1 = next(c for c in coverage if c["req_id"] == "REQ-VT-001")
    assert cov_1["status"] == CoverageStatus.UNCLEAR.value

    cov_2 = next(c for c in coverage if c["req_id"] == "REQ-VT-002")
    assert cov_2["status"] == CoverageStatus.UNCLEAR.value
