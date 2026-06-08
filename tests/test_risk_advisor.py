"""
Unit tests for RiskAdvisor (TASK-VT-016).
"""

from pathlib import Path

from vibe_tracing.risk_advisor import RiskAdvisor


def test_enrich_claim_risks():
    """
    Test that existing claim risks are enriched with business_impact and suggested_action.
    covers: AC-VT-007-01, AC-VT-007-02
    """
    advisor = RiskAdvisor(Path("/dummy/project/root"))

    claim_risks = [
        {
            "risk_id": "RISK-VT-001",
            "description": "Completed claim CLAIM-VT-001 has only self-referential or empty evidence.",
            "severity": "must",
            "risk_category": "self_referential_claim",
        },
        {
            "risk_id": "RISK-VT-002",
            "description": "Claim CLAIM-VT-002 references non-existent evidence.",
            "severity": "must",
            "risk_category": "non_existent_evidence",
        },
        {
            "risk_id": "RISK-VT-003",
            "description": "Claim CLAIM-VT-003 modified after claim timestamp.",
            "severity": "should",
            "risk_category": "stale_file",
        },
        {
            "risk_id": "RISK-VT-004",
            "description": "Claim CLAIM-VT-004 references non-existent task.",
            "severity": "should",
            "risk_category": "non_existent_task",
        },
        {
            "risk_id": "RISK-VT-005",
            "description": "Claim CLAIM-VT-005 references non-existent code file.",
            "severity": "should",
            "risk_category": "non_existent_code_ref",
        },
        {
            "risk_id": "RISK-VT-006",
            "description": "Claim CLAIM-VT-006 has no test coverage.",
            "severity": "must",
            "risk_category": "no_test_coverage",
        },
        {
            "risk_id": "RISK-VT-007",
            "description": "Claim CLAIM-VT-007 has failed tests.",
            "severity": "must",
            "risk_category": "failed_tests",
        },
        {
            "risk_id": "RISK-VT-008",
            "description": "Some generic/unmatched risk.",
            "severity": "should",
        },
    ]

    res = advisor.generate_risks(
        gaps=[], claims_analysis=[], claim_risks=claim_risks, compliance_result=None
    )

    assert len(res) == 8

    # Check self-referential
    assert "违反" in res[0]["business_impact"]
    assert "Agent" in res[0]["business_impact"]
    assert "自证" in res[0]["business_impact"]
    assert "提供独立的外部证据" in res[0]["suggested_action"]

    # Check non-existent evidence
    assert "证据链中断" in res[1]["business_impact"]
    assert "确保被引用的证据项已正确生成" in res[1]["suggested_action"]

    # Check modified after (speculative risk -> low confidence, suggestion)
    assert "已失效" in res[2]["business_impact"]
    assert res[2]["confidence"] == "low_confidence"
    assert res[2]["type"] == "suggestion"

    # Check non-existent task
    assert "不存在" in res[3]["business_impact"]

    # Check non-existent file
    assert "工作区中不存在" in res[4]["business_impact"]

    # Check no test coverage
    assert "测试" in res[5]["business_impact"]

    # Check failed tests
    assert "测试" in res[6]["business_impact"]

    # Check generic
    assert "不一致" in res[7]["business_impact"]


def test_process_gaps_to_risks():
    """
    Test that traceability gaps (requirements, AC, and tasks) are converted into risks.
    covers: AC-VT-007-01, AC-VT-007-02
    """
    advisor = RiskAdvisor(Path("/dummy/project/root"))

    gaps = [
        {
            "item_id": "REQ-VT-001",
            "item_type": "requirement",
            "reason": "Missing task coverage",
        },
        {
            "item_id": "AC-VT-001-01",
            "item_type": "ac",
            "reason": "Missing passing tests",
        },
        {
            "item_id": "TASK-VT-002",
            "item_type": "task",
            "reason": "Missing agent claim",
        },
    ]

    # No existing risks
    res = advisor.generate_risks(
        gaps=gaps, claims_analysis=[], claim_risks=[], compliance_result=None
    )

    assert len(res) == 3
    assert res[0]["risk_id"] == "RISK-VT-001"
    assert res[0]["severity"] == "must"
    assert "REQ-VT-001" in res[0]["description"]

    assert res[1]["risk_id"] == "RISK-VT-002"
    assert res[1]["severity"] == "must"
    assert "AC-VT-001-01" in res[1]["description"]

    assert res[2]["risk_id"] == "RISK-VT-003"
    assert res[2]["severity"] == "should"
    assert "TASK-VT-002" in res[2]["description"]


def test_counter_sequential_continuity():
    """
    Test that generated risk IDs continue sequentially from the highest existing claim risk ID.
    covers: AC-VT-007-01
    """
    advisor = RiskAdvisor(Path("/dummy/project/root"))

    claim_risks = [
        {"risk_id": "RISK-VT-005", "description": "First risk", "severity": "must"},
        {"risk_id": "RISK-VT-012", "description": "Second risk", "severity": "should"},
    ]

    gaps = [
        {
            "item_id": "REQ-VT-001",
            "item_type": "requirement",
            "reason": "Missing task coverage",
        }
    ]

    res = advisor.generate_risks(
        gaps=gaps, claims_analysis=[], claim_risks=claim_risks, compliance_result=None
    )

    # There should be 3 risks total (2 existing + 1 from gap)
    assert len(res) == 3
    assert res[0]["risk_id"] == "RISK-VT-005"
    assert res[1]["risk_id"] == "RISK-VT-012"
    assert res[2]["risk_id"] == "RISK-VT-013"  # Should start at max(5, 12) + 1 = 13


def test_compliance_results_to_risks():
    """
    Test that compliance violations are mapped to MUST risks and unclear constraints to speculative/should risks.
    covers: AC-VT-007-01, AC-VT-007-03, AC-VT-008-02, AC-VT-008-03
    """
    advisor = RiskAdvisor(Path("/dummy/project/root"))

    compliance_result = {
        "architecture_compliance_status": [],
        "architecture_violations": [
            {
                "rule_id": "DEP-VT-001",
                "evidence_id": "EVIDENCE-VT-005",
                "message": "Core imports agent runtime package hermes",
            }
        ],
        "unclear_constraints": [
            {
                "rule_id": "DEP-VT-002",
                "reason": "dashboard.html not yet generated in the workspace.",
            }
        ],
    }

    res = advisor.generate_risks(
        gaps=[], claims_analysis=[], claim_risks=[], compliance_result=compliance_result
    )

    assert len(res) == 2

    # First risk: violation
    assert res[0]["risk_id"] == "RISK-VT-001"
    assert "DEP-VT-001" in res[0]["description"]
    assert res[0]["severity"] == "must"
    assert res[0]["evidence_ids"] == ["EVIDENCE-VT-005"]
    assert "suggested_action" in res[0]
    assert "business_impact" in res[0]

    # Second risk: unclear (speculative -> low confidence, suggestion)
    assert res[1]["risk_id"] == "RISK-VT-002"
    assert "DEP-VT-002" in res[1]["description"]
    assert res[1]["severity"] == "should"
    assert res[1]["confidence"] == "low_confidence"
    assert res[1]["type"] == "suggestion"
    assert "suggested_action" in res[1]
    assert "business_impact" in res[1]


def test_compliance_deduplication():
    """
    Test that architecture violations with duplicate rule IDs are deduplicated.
    covers: AC-VT-007-01
    """
    advisor = RiskAdvisor(Path("/dummy/project/root"))

    compliance_result = {
        "architecture_compliance_status": [],
        "architecture_violations": [
            {
                "rule_id": "DEP-VT-001",
                "evidence_id": "EVIDENCE-VT-005",
                "message": "Violation 1",
            },
            {
                "rule_id": "DEP-VT-001",
                "evidence_id": "EVIDENCE-VT-006",
                "message": "Violation 2",
            },
        ],
        "unclear_constraints": [],
    }

    res = advisor.generate_risks(
        gaps=[], claims_analysis=[], claim_risks=[], compliance_result=compliance_result
    )

    # Should deduplicate DEP-VT-001 to 1 risk item
    assert len(res) == 1
    assert "DEP-VT-001" in res[0]["description"]
