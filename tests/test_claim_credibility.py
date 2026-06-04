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
    evidence_list = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "tool",
            "source_path": "tool_reports/pytest.xml",
            "covers": ["AC-VT-001-01"],
            "status": "covered",
        }
    ]

    warnings = assess_claim_credibility([claim], evidence_list)

    assert claim.credibility == "high"
    assert len(warnings) == 0
    assert len(claim.credibility_warnings) == 0


def test_high_credibility_with_test_evidence():
    """
    Claim with evidence_refs pointing to test evidence -> credibility = "high".
    covers: AC-VT-040-01
    """
    claim = _make_claim(evidence_refs=["EVIDENCE-VT-002"])
    evidence_list = [
        {
            "evidence_id": "EVIDENCE-VT-002",
            "source_type": "test",
            "source_path": "tests/test_something.py",
            "covers": ["AC-VT-001-01"],
            "status": "covered",
        }
    ]

    warnings = assess_claim_credibility([claim], evidence_list)

    assert claim.credibility == "high"
    assert len(warnings) == 0


# ---------------------------------------------------------------------------
# Test: Low Credibility
# ---------------------------------------------------------------------------


def test_low_credibility_no_tool_evidence():
    """
    Claim with no tool evidence refs -> credibility = "low_confidence".
    covers: AC-VT-040-02
    """
    claim = _make_claim(evidence_refs=["EVIDENCE-VT-003"])
    evidence_list = [
        {
            "evidence_id": "EVIDENCE-VT-003",
            "source_type": "code",
            "source_path": "src/module.py",
            "covers": ["AC-VT-001-01"],
            "status": "covered",
        }
    ]

    warnings = assess_claim_credibility(
        [claim], evidence_list, task_result=_make_task_result()
    )

    assert claim.credibility == "low_confidence"
    assert len(warnings) == 1
    assert "CLAIM-VT-001" in warnings[0]
    assert "low_confidence" in warnings[0]
    assert len(claim.credibility_warnings) == 1


def test_low_credibility_empty_evidence_refs():
    """
    Claim with empty evidence_refs -> credibility = "low_confidence".
    covers: AC-VT-040-02
    """
    claim = _make_claim(evidence_refs=[])
    evidence_list = []

    warnings = assess_claim_credibility([claim], evidence_list)

    assert claim.credibility == "low_confidence"
    assert len(warnings) == 1


def test_low_credibility_only_task_evidence():
    """
    Claim with only task-type evidence -> credibility = "low_confidence".
    covers: AC-VT-040-02
    """
    claim = _make_claim(evidence_refs=["EVIDENCE-VT-004"])
    evidence_list = [
        {
            "evidence_id": "EVIDENCE-VT-004",
            "source_type": "task",
            "source_path": "docs/task_list.json",
            "covers": [],
            "status": "covered",
        }
    ]

    warnings = assess_claim_credibility(
        [claim], evidence_list, task_result=_make_task_result()
    )

    assert claim.credibility == "low_confidence"
    assert len(warnings) == 1


# ---------------------------------------------------------------------------
# Test: Medium Credibility
# ---------------------------------------------------------------------------


def test_medium_credibility_non_code_task_with_deliverable(project_root):
    """
    Non-code claim with existing deliverable -> credibility = "medium".
    covers: AC-VT-040-03
    """
    # Create a task without ACs (non-code task)
    task = Task(
        task_id="TASK-VT-002",
        title="Write Documentation",
        phase_id="PHASE-VT-001",
        priority="should",
        status="done",
        owner_role="agent",
        objective="Write the readme.",
        # No related_acceptance_criteria, no definition_of_done
    )
    task_result = TaskListLoadResult(tasks=[task], is_valid=True)

    claim = _make_claim(
        related_task="TASK-VT-002",
        evidence_refs=["EVIDENCE-VT-005"],
        test_refs=["docs/readme.md"],
    )
    evidence_list = [
        {
            "evidence_id": "EVIDENCE-VT-005",
            "source_type": "claim",
            "source_path": ".vibetracing/agent_claims.json",
            "covers": [],
            "status": "covered",
        }
    ]

    warnings = assess_claim_credibility(
        [claim], evidence_list, task_result=task_result, project_root=project_root
    )

    assert claim.credibility == "medium"
    assert len(warnings) == 0


def test_medium_not_applied_when_deliverable_missing(project_root):
    """
    Non-code claim with missing deliverable file -> credibility = "low_confidence".
    covers: AC-VT-040-03
    """
    task = Task(
        task_id="TASK-VT-003",
        title="Write Documentation",
        phase_id="PHASE-VT-001",
        priority="should",
        status="done",
        owner_role="agent",
        objective="Write the readme.",
    )
    task_result = TaskListLoadResult(tasks=[task], is_valid=True)

    claim = _make_claim(
        related_task="TASK-VT-003",
        evidence_refs=["EVIDENCE-VT-006"],
        test_refs=["docs/nonexistent.md"],
    )
    evidence_list = [
        {
            "evidence_id": "EVIDENCE-VT-006",
            "source_type": "claim",
            "source_path": ".vibetracing/agent_claims.json",
            "covers": [],
            "status": "covered",
        }
    ]

    warnings = assess_claim_credibility(
        [claim], evidence_list, task_result=task_result, project_root=project_root
    )

    assert claim.credibility == "low_confidence"
    assert len(warnings) == 1


# ---------------------------------------------------------------------------
# Test: Risk Generation
# ---------------------------------------------------------------------------


def test_low_confidence_claim_generates_risk():
    """
    Low-confidence claim generates a risk entry with correct fields.
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

    assert len(risks) == 1
    risk = risks[0]
    assert risk["risk_id"] == "RISK-VT-001"
    assert "CLAIM-VT-001" in risk["description"]
    assert "无 VT 执行的工具验证证据" in risk["description"]
    assert risk["severity"] == "must"
    assert "Agent 可能" in risk["business_impact"]
    assert "pytest" in risk["suggested_action"]
    assert risk["item_type"] == "claim_credibility"


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
    Mixed credibility claims generate risks only for low_confidence ones.
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

    assert len(risks) == 1
    assert "CLAIM-VT-002" in risks[0]["description"]
    assert risks[0]["item_type"] == "claim_credibility"


# ---------------------------------------------------------------------------
# Test: Gate Blocking
# ---------------------------------------------------------------------------


def test_low_confidence_claim_blocks_gate():
    """
    Low-confidence claim with MUST severity risk blocks the merge gate.
    covers: AC-VT-040-05
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    risks = [
        {
            "risk_id": "RISK-VT-001",
            "description": "Claim CLAIM-VT-001 声明任务完成但无 VT 执行的工具验证证据",
            "severity": "must",
            "business_impact": "Agent 可能在未经实际验证的情况下声称任务完成，存在交付质量风险",
            "suggested_action": "确保关联的测试文件存在、声明了 covers AC、且 pytest 能通过。然后重新运行 vibe-tracing analyze。",
            "item_type": "claim_credibility",
        }
    ]

    res = engine.evaluate(gaps=[], risks=risks, compliance_result=None)

    assert res["gate_decision"] == "blocked"
    assert any("RISK-VT-001" in msg for msg in res["reasons"])
    assert any(
        "存在低可信度 Claim（无工具验证证据）" in msg for msg in res["blocked_items"]
    )
    assert any(
        "存在低可信度 Claim（无工具验证证据）" in msg for msg in res["reasons"]
    )


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

    evidence_list = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_type": "tool",
            "source_path": "tool_reports/pytest.xml",
            "covers": ["AC-VT-001-01"],
            "status": "covered",
        },
        {
            "evidence_id": "EVIDENCE-VT-003",
            "source_type": "code",
            "source_path": "src/module.py",
            "covers": [],
            "status": "covered",
        },
        {
            "evidence_id": "EVIDENCE-VT-005",
            "source_type": "claim",
            "source_path": ".vibetracing/agent_claims.json",
            "covers": [],
            "status": "covered",
        },
    ]

    task_result = _make_task_result()

    warnings = assess_claim_credibility(claims, evidence_list, task_result=task_result)

    assert claims[0].credibility == "high"
    assert claims[1].credibility == "low_confidence"
    assert claims[2].credibility == "low_confidence"
    assert len(warnings) == 2
    assert all("low_confidence" in w for w in warnings)


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
