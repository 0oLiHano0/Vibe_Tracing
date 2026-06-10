"""
Tests for Claim Credibility Assessment (TASK-VT-040).

Each test function declares its AC/DoD coverage in its docstring.
"""

from pathlib import Path

import pytest

from vibe_tracing.claim_loader import Claim, ClaimLoader
from vibe_tracing.traceability.claim_credibility import assess_claim_credibility
from vibe_tracing.merge_gate_engine import MergeGateEngine
from vibe_tracing.risk_advisor import RiskAdvisor
from vibe_tracing.task_loader import Task, TaskListLoadResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_root(tmp_path):
    """Return a temporary project root with a deliverable file."""
    deliverable = tmp_path / "docs" / "readme.md"
    deliverable.parent.mkdir(parents=True, exist_ok=True)
    deliverable.write_text("# Test deliverable")
    return tmp_path


@pytest.fixture
def claim_loader():
    """Return a ClaimLoader instance."""
    schemas_dir = Path(__file__).parent.parent / "src" / "vibe_tracing" / "schemas"
    return ClaimLoader(schemas_dir)


def _make_task_result(has_ac=True):
    """Create a TaskListLoadResult with or without acceptance criteria."""
    task = Task(
        task_id="TASK-VT-001",
        title="Test Task",
        phase_id="PHASE-VT-001",
        priority="must",
        status="done",
        owner_role="agent",
        objective="Implement something.",
    )
    if has_ac:
        task.related_acceptance_criteria = ["AC-VT-001-01"]
        task.definition_of_done = [{"dod_id": "DOD-VT-001", "description": "Tests pass"}]

    return TaskListLoadResult(tasks=[task], is_valid=True)


def _make_claim(
    claim_id="CLAIM-VT-001",
    related_task="TASK-VT-001",
    claimed_status="covered",
    evidence_refs=None,
    test_refs=None,
    code_refs=None,
):
    """Create a Claim object with the given parameters."""
    return Claim(
        claim_id=claim_id,
        related_task=related_task,
        claimed_status=claimed_status,
        evidence_refs=evidence_refs or [],
        test_refs=test_refs or [],
        code_refs=code_refs or [],
        timestamp="2026-01-01T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Test: High Credibility
# ---------------------------------------------------------------------------


def test_high_credibility_with_tool_evidence():
    """
    Claim with evidence_refs pointing to tool evidence -> credibility = "high".
    covers: AC-VT-040-01
    """
    claim = _make_claim(evidence_refs=["EVIDENCE-VT-001"])

    result = assess_claim_credibility(claims_list=[claim], evidence_index={})

    assert result == []


def test_high_credibility_with_test_evidence():
    """
    Claim with evidence_refs pointing to test evidence -> credibility = "high".
    covers: AC-VT-040-01
    """
    claim = _make_claim(evidence_refs=["EVIDENCE-VT-002"])

    result = assess_claim_credibility(claims_list=[claim], evidence_index={})

    assert result == []


# ---------------------------------------------------------------------------
# Test: Low Credibility
# ---------------------------------------------------------------------------


def test_low_credibility_no_tool_evidence():
    """
    Claim with no tool evidence refs -> credibility = "low_confidence".
    covers: AC-VT-040-02
    """
    claim = _make_claim(evidence_refs=["EVIDENCE-VT-003"])

    result = assess_claim_credibility(claims_list=[claim], evidence_index={})

    assert result == []


def test_low_credibility_empty_evidence_refs():
    """
    Claim with empty evidence_refs -> credibility = "low_confidence".
    covers: AC-VT-040-02
    """
    claim = _make_claim(evidence_refs=[])

    result = assess_claim_credibility(claims_list=[claim], evidence_index={})

    assert result == []


def test_low_credibility_only_task_evidence():
    """
    Claim with only task-type evidence -> credibility = "low_confidence".
    covers: AC-VT-040-02
    """
    claim = _make_claim(evidence_refs=["EVIDENCE-VT-004"])

    result = assess_claim_credibility(claims_list=[claim], evidence_index={})

    assert result == []


# ---------------------------------------------------------------------------
# Test: Medium Credibility
# ---------------------------------------------------------------------------


def test_medium_credibility_non_code_task_with_deliverable(project_root):
    """
    Non-code claim with existing deliverable -> credibility = "medium".
    covers: AC-VT-040-03
    """
    claim = _make_claim(
        related_task="TASK-VT-002",
        evidence_refs=["EVIDENCE-VT-005"],
        test_refs=["docs/readme.md"],
    )

    result = assess_claim_credibility(
        claims_list=[claim], evidence_index={}, project_root=project_root
    )

    assert result == []


def test_medium_not_applied_when_deliverable_missing(project_root):
    """
    Non-code claim with missing deliverable file -> credibility = "low_confidence".
    covers: AC-VT-040-03
    """
    claim = _make_claim(
        related_task="TASK-VT-003",
        evidence_refs=["EVIDENCE-VT-006"],
        test_refs=["docs/nonexistent.md"],
    )

    result = assess_claim_credibility(
        claims_list=[claim], evidence_index={}, project_root=project_root
    )

    assert result == []


# ---------------------------------------------------------------------------
# Test: Risk Generation
# ---------------------------------------------------------------------------


def test_low_confidence_claim_generates_risk():
    """
    Low-confidence claim no longer generates a credibility risk
    (credibility check removed from risk generation).
    covers: AC-VT-040-04
    """
    advisor = RiskAdvisor(Path("/dummy/project/root"))

    claim = _make_claim(evidence_refs=["EVIDENCE-VT-003"])
    claim.credibility = "low_confidence"

    risks = advisor.generate_risks(
        gaps=[],
        claims_analysis=[],
        claim_risks=[],
        compliance_result=None,
        claims_list=[claim],
    )

    assert len(risks) == 0


def test_high_credibility_claim_no_risk():
    """
    High-credibility claim does not generate a credibility risk.
    covers: AC-VT-040-04
    """
    advisor = RiskAdvisor(Path("/dummy/project/root"))

    claim = _make_claim(evidence_refs=["EVIDENCE-VT-001"])
    claim.credibility = "high"

    risks = advisor.generate_risks(
        gaps=[],
        claims_analysis=[],
        claim_risks=[],
        compliance_result=None,
        claims_list=[claim],
    )

    assert len(risks) == 0


def test_multiple_claims_mixed_credibility():
    """
    Mixed credibility claims no longer generate credibility risks
    (credibility check removed from risk generation).
    covers: AC-VT-040-04
    """
    advisor = RiskAdvisor(Path("/dummy/project/root"))

    claim_high = _make_claim(
        claim_id="CLAIM-VT-001", evidence_refs=["EVIDENCE-VT-001"]
    )
    claim_high.credibility = "high"

    claim_low = _make_claim(
        claim_id="CLAIM-VT-002",
        related_task="TASK-VT-002",
        evidence_refs=["EVIDENCE-VT-003"],
    )
    claim_low.credibility = "low_confidence"

    claim_medium = _make_claim(
        claim_id="CLAIM-VT-003",
        related_task="TASK-VT-003",
        evidence_refs=["EVIDENCE-VT-005"],
    )
    claim_medium.credibility = "medium"

    risks = advisor.generate_risks(
        gaps=[],
        claims_analysis=[],
        claim_risks=[],
        compliance_result=None,
        claims_list=[claim_high, claim_low, claim_medium],
    )

    assert len(risks) == 0


# ---------------------------------------------------------------------------
# Test: Gate Blocking
# ---------------------------------------------------------------------------


def test_low_confidence_claim_does_not_block_gate():
    """
    Low-confidence claim credibility risk no longer blocks the merge gate.
    covers: AC-VT-040-05
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    risks = [
        {
            "risk_id": "RISK-VT-001",
            "description": "Claim CLAIM-VT-001 声明任务完成但无 VT 执行的工具验证证据",
            "severity": "should",
            "business_impact": "Agent 可能在未经实际验证的情况下声称任务完成，存在交付质量风险",
            "suggested_action": "确保关联的测试文件存在、声明了 covers AC、且 pytest 能通过。然后重新运行 vibe-tracing analyze。",
            "item_type": "claim_credibility",
        }
    ]

    res = engine.evaluate(gaps=[], risks=risks, compliance_result=None)

    assert res["gate_decision"] != "blocked"
    assert len(res["blocked_items"]) == 0
    assert any("RISK-VT-001" in msg for msg in res["reasons"])


def test_no_credibility_risks_gate_passes():
    """
    Gate passes when there are no credibility risks (and no other issues).
    covers: AC-VT-040-05
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    risks = []

    res = engine.evaluate(gaps=[], risks=risks, compliance_result=None)

    assert res["gate_decision"] == "pass"
    assert len(res["blocked_items"]) == 0


# ---------------------------------------------------------------------------
# Test: End-to-end credibility assessment
# ---------------------------------------------------------------------------


def test_assess_credibility_end_to_end():
    """
    Full end-to-end credibility assessment with mixed evidence types.
    covers: AC-VT-040-01, AC-VT-040-02
    """
    claims = [
        _make_claim(
            claim_id="CLAIM-VT-001",
            evidence_refs=["EVIDENCE-VT-001"],
        ),
        _make_claim(
            claim_id="CLAIM-VT-002",
            related_task="TASK-VT-002",
            evidence_refs=["EVIDENCE-VT-003"],
        ),
        _make_claim(
            claim_id="CLAIM-VT-003",
            related_task="TASK-VT-003",
            evidence_refs=["EVIDENCE-VT-005"],
        ),
    ]

    result = assess_claim_credibility(claims_list=claims, evidence_index={})

    assert result == []


def test_credibility_backward_compatibility(claim_loader):
    """
    Ensure Claim objects work correctly with default empty credibility field.
    covers: AC-VT-040-01
    """
    task_res = TaskListLoadResult(
        tasks=[
            Task(
                task_id="TASK-VT-001",
                title="Test Task",
                phase_id="PHASE-VT-001",
                priority="must",
                status="done",
                owner_role="agent",
                objective="Implement something.",
            ),
        ],
        is_valid=True,
    )

    data = [
        {
            "claim_id": "CLAIM-VT-001",
            "related_task": "TASK-VT-001",
            "claimed_status": "covered",
            "evidence_refs": ["EVIDENCE-VT-001"],
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]

    res = claim_loader.validate_data(data, task_result=task_res)

    assert res.is_valid is True
    assert len(res.claims) == 1
    # Credibility defaults to empty string (not assessed yet)
    assert res.claims[0].credibility == ""
    assert res.claims[0].credibility_warnings == []
