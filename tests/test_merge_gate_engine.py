"""
Unit tests for MergeGateEngine (TASK-VT-017).
"""

from pathlib import Path
from vibe_tracing.merge_gate_engine import MergeGateEngine


def test_missing_ac_test_blocks():
    """
    Test that a missing Acceptance Criterion (AC) test coverage blocks the merge gate.
    covers: AC-VT-008-01
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = [
        {
            "item_id": "AC-VT-001-01",
            "item_type": "ac",
            "reason": "Must acceptance criterion AC-VT-001-01 is missing passing test coverage.",
        }
    ]
    risks = []
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    res = engine.evaluate(gaps, risks, compliance)

    assert res["gate_decision"] == "blocked"
    assert any("AC-VT-001-01" in msg for msg in res["reasons"])
    assert len(res["blocked_items"]) > 0


def test_claim_missing_external_evidence_blocks():
    """
    Test that completed Agent Claims missing external evidence (violating self-attestation forbidden rules) block the merge gate.
    covers: AC-VT-001-03, AC-VT-002-02, AC-VT-008-02
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = []
    # completed claim without external evidence produces a risk with severity="must" and self-referential description
    risks = [
        {
            "risk_id": "RISK-VT-001",
            "description": "Completed claim CLAIM-VT-001 has only self-referential or empty evidence.",
            "severity": "must",
            "suggested_action": "Provide external evidence",
            "business_impact": "Violates no self-attestation principles",
        }
    ]
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    res = engine.evaluate(gaps, risks, compliance)

    assert res["gate_decision"] == "blocked"
    assert any("RISK-VT-001" in msg for msg in res["reasons"])
    assert len(res["blocked_items"]) > 0


def test_high_risk_lacking_details_blocks():
    """
    Test that a MUST/high risk lacking suggested action or business impact blocks the gate.
    covers: AC-VT-008-02
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = []
    risks = [
        {
            "risk_id": "RISK-VT-002",
            "description": "Critical security bug found by bandit.",
            "severity": "must",
            "suggested_action": "",  # missing action
            "business_impact": "Exposes workspace to arbitrary code execution",
        }
    ]
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    res = engine.evaluate(gaps, risks, compliance)

    assert res["gate_decision"] == "blocked"
    assert any("缺失处理建议" in msg for msg in res["reasons"])
    assert len(res["blocked_items"]) > 0


def test_must_constraint_violated_blocks():
    """
    Test that violated MUST-level architecture constraints block the merge gate.
    covers: AC-VT-008-03
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = []
    risks = []
    compliance = {
        "architecture_compliance_status": [
            {
                "rule_id": "DEP-VT-001",
                "status": "violated",
                "severity": "must",
                "title": "Forbidden dependency",
                "description": "Core must not depend on GUI components",
            }
        ],
        "architecture_violations": [
            {
                "rule_id": "DEP-VT-001",
                "evidence_id": "EVIDENCE-VT-005",
                "message": "Forbidden dependency found",
            }
        ],
        "unclear_constraints": [],
    }

    res = engine.evaluate(gaps, risks, compliance)

    assert res["gate_decision"] == "blocked"
    assert any("DEP-VT-001" in msg for msg in res["reasons"])
    assert len(res["blocked_items"]) > 0


def test_unclear_constraints_fails():
    """
    Test that unclear/unverifiable architecture constraints downgrade the gate to FAIL (conditional).
    covers: AC-VT-008-03
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = []
    risks = []
    compliance = {
        "architecture_compliance_status": [
            {
                "rule_id": "DEP-VT-002",
                "status": "unclear",
                "severity": "must",
                "title": "Manual audit needed",
                "description": "Audit deployment artifact existence",
            }
        ],
        "architecture_violations": [],
        "unclear_constraints": [
            {
                "rule_id": "DEP-VT-002",
                "reason": "File dashboard.html not yet generated in the workspace.",
            }
        ],
    }

    res = engine.evaluate(gaps, risks, compliance)

    assert res["gate_decision"] == "fail"
    assert any("DEP-VT-002" in msg for msg in res["reasons"])
    assert len(res["blocked_items"]) == 0


def test_should_level_issues_fails():
    """
    Test that should-level gaps or speculative risks downgrade the decision to FAIL (conditional) rather than BLOCK.
    covers: AC-VT-008-03
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    # Gap in requirement task coverage is should-level (since AC is must)
    gaps = [
        {
            "item_id": "REQ-VT-002",
            "item_type": "requirement",
            "reason": "No task coverage",
        }
    ]
    # Risk with should severity (speculative risk or modified file after claim timestamp)
    risks = [
        {
            "risk_id": "RISK-VT-003",
            "description": "Claim CLAIM-VT-003 references code file modified after timestamp.",
            "severity": "should",
            "confidence": "low_confidence",
            "type": "suggestion",
        }
    ]
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    res = engine.evaluate(gaps, risks, compliance)

    assert res["gate_decision"] == "fail"
    assert any("REQ-VT-002" in msg for msg in res["reasons"])
    assert any("RISK-VT-003" in msg for msg in res["reasons"])
    assert len(res["blocked_items"]) == 0


def test_pass_decision():
    """
    Test that when there are no gaps, risks, or compliance violations, the gate decision is PASS.
    covers: AC-VT-008-03
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = []
    risks = []
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    res = engine.evaluate(gaps, risks, compliance)

    assert res["gate_decision"] == "pass"
    assert "所有质量门禁规则均已通过" in res["reasons"][0]
    assert len(res["blocked_items"]) == 0


def test_separate_gate_and_human_decisions():
    """
    Test that the engine computes the gate decision strictly independently of any external human decisions.
    covers: AC-VT-008-03
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = []
    risks = []
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    res = engine.evaluate(gaps, risks, compliance)

    # The output structure is strictly defined by the machine rules
    assert "gate_decision" in res
    assert res["gate_decision"] == "pass"
    assert "human_decision" not in res


def test_blocked_with_fail_reasons_included():
    """
    Test that when a blocked condition (AC gap) AND a fail condition (REQ gap) both exist,
    the gate_decision is "blocked" but reasons list contains BOTH the blocked and fail entries.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = [
        {
            "item_id": "AC-VT-001-01",
            "item_type": "ac",
            "reason": "Must acceptance criterion AC-VT-001-01 is missing passing test coverage.",
        },
        {
            "item_id": "REQ-VT-002",
            "item_type": "requirement",
            "reason": "No task coverage for requirement REQ-VT-002.",
        },
    ]
    risks = []
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    res = engine.evaluate(gaps, risks, compliance)

    assert res["gate_decision"] == "blocked"
    assert any("AC-VT-001-01" in msg for msg in res["reasons"])
    assert any("REQ-VT-002" in msg for msg in res["reasons"])
    assert len(res["blocked_items"]) > 0


def test_blocked_with_should_risk_reasons_included():
    """
    Test that when a blocked condition (must risk) AND a fail condition (should risk) both exist,
    the gate_decision is "blocked" but reasons list contains BOTH.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = []
    risks = [
        {
            "risk_id": "RISK-VT-010",
            "description": "Critical vulnerability found.",
            "severity": "must",
            "suggested_action": "Patch immediately",
            "business_impact": "System compromise",
        },
        {
            "risk_id": "RISK-VT-011",
            "description": "Minor style inconsistency.",
            "severity": "should",
            "confidence": "low_confidence",
            "type": "suggestion",
        },
    ]
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    res = engine.evaluate(gaps, risks, compliance)

    assert res["gate_decision"] == "blocked"
    assert any("RISK-VT-010" in msg for msg in res["reasons"])
    assert any("RISK-VT-011" in msg for msg in res["reasons"])
    assert len(res["blocked_items"]) > 0


def test_pass_no_issues():
    """
    Test that with no gaps, no risks, and clean compliance, the gate passes with a pass message.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = []
    risks = []
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    res = engine.evaluate(gaps, risks, compliance)

    assert res["gate_decision"] == "pass"
    assert "所有质量门禁规则均已通过" in res["reasons"][0]
    assert len(res["blocked_items"]) == 0


def test_blocked_only_ac_gap():
    """
    Test that when only an AC gap is present (no fail conditions), the gate is blocked
    and reasons contain only the blocked reason.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = [
        {
            "item_id": "AC-VT-005-01",
            "item_type": "ac",
            "reason": "Missing test evidence for AC-VT-005-01.",
        }
    ]
    risks = []
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    res = engine.evaluate(gaps, risks, compliance)

    assert res["gate_decision"] == "blocked"
    assert any("AC-VT-005-01" in msg for msg in res["reasons"])
    # Only blocked reasons, no fail reasons
    assert len(res["reasons"]) == 1
    assert len(res["blocked_items"]) == 1


# ---------------------------------------------------------------
# EVO-TASK-025: Debt awareness tests
# ---------------------------------------------------------------

def test_staged_claim_gets_current_prefix():
    """
    Test that a risk from a staged (modified) claim gets [当前] prefix.
    covers: EVO-TASK-025
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = []
    risks = [
        {
            "risk_id": "RISK-VT-010",
            "claim_id": "CLAIM-VT-001",
            "description": "Critical vulnerability found.",
            "severity": "must",
            "suggested_action": "Patch immediately",
            "business_impact": "System compromise",
        }
    ]
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }
    staged_items = {"CLAIM-VT-001"}

    res = engine.evaluate(gaps, risks, compliance, staged_items=staged_items)

    assert res["gate_decision"] == "blocked"
    assert any("[当前]" in msg and "RISK-VT-010" in msg for msg in res["reasons"])


def test_non_staged_claim_gets_pre_existing_prefix():
    """
    Test that a risk from a non-staged claim gets [预存] prefix and does NOT
    block the gate (pre-existing debt does not block in pre-commit mode).
    covers: EVO-TASK-025, EVO-TASK-012
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = []
    risks = [
        {
            "risk_id": "RISK-VT-011",
            "claim_id": "CLAIM-VT-002",
            "description": "Critical vulnerability found.",
            "severity": "must",
            "suggested_action": "Patch immediately",
            "business_impact": "System compromise",
        }
    ]
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }
    # Only CLAIM-VT-001 is staged, not CLAIM-VT-002
    staged_items = {"CLAIM-VT-001"}

    res = engine.evaluate(gaps, risks, compliance, staged_items=staged_items)

    # Pre-existing debt should NOT block in pre-commit mode
    assert res["gate_decision"] == "pass"
    assert any("[预存]" in msg and "RISK-VT-011" in msg for msg in res["reasons"])


def test_no_staged_items_backward_compatible():
    """
    Test that without staged_items, all reasons have no prefix (backward compatible).
    covers: EVO-TASK-025
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = []
    risks = [
        {
            "risk_id": "RISK-VT-012",
            "claim_id": "CLAIM-VT-001",
            "description": "Critical vulnerability found.",
            "severity": "must",
            "suggested_action": "Patch immediately",
            "business_impact": "System compromise",
        }
    ]
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    res = engine.evaluate(gaps, risks, compliance)

    assert res["gate_decision"] == "blocked"
    # No prefix when staged_items is None
    assert not any("[当前]" in msg or "[预存]" in msg for msg in res["reasons"])


def test_architecture_violation_gets_pre_existing_prefix():
    """
    Test that architecture violations (not tied to a specific claim/task)
    get [预存] prefix when staged_items is provided, and do NOT block the
    gate (cannot prove relation to staged changes).
    covers: EVO-TASK-025, EVO-TASK-012
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = []
    risks = []
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [
            {
                "rule_id": "DEP-VT-001",
                "evidence_id": "EVIDENCE-VT-005",
                "message": "Forbidden dependency found",
            }
        ],
        "unclear_constraints": [],
    }
    staged_items = {"CLAIM-VT-001"}

    res = engine.evaluate(gaps, risks, compliance, staged_items=staged_items)

    # Architecture violations cannot be mapped to staged items → pre-existing
    assert res["gate_decision"] == "pass"
    assert any("[预存]" in msg and "DEP-VT-001" in msg for msg in res["reasons"])


# ---------------------------------------------------------------
# EVO-TASK-012: Current vs pre-existing gate separation tests
# ---------------------------------------------------------------

def test_pre_existing_ac_gap_does_not_block():
    """
    Test that an AC gap from a non-staged item does NOT block in pre-commit mode.
    The gap is still reported with [预存] prefix but the gate passes.
    covers: EVO-TASK-012
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    # AC-VT-001-01 has a gap but it's not in staged_items
    gaps = [
        {
            "item_id": "AC-VT-001-01",
            "item_type": "ac",
            "reason": "Must acceptance criterion AC-VT-001-01 is missing passing test coverage.",
        }
    ]
    risks = []
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }
    staged_items = {"CLAIM-VT-099"}  # unrelated claim

    res = engine.evaluate(gaps, risks, compliance, staged_items=staged_items)

    # Pre-existing AC gap should NOT block
    assert res["gate_decision"] == "pass"
    assert len(res["blocked_items"]) == 0
    assert any("[预存]" in msg and "AC-VT-001-01" in msg for msg in res["reasons"])


def test_current_ac_gap_blocks():
    """
    Test that an AC gap from a staged item DOES block in pre-commit mode.
    covers: EVO-TASK-012
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = [
        {
            "item_id": "AC-VT-001-01",
            "item_type": "ac",
            "reason": "Must acceptance criterion AC-VT-001-01 is missing passing test coverage.",
        }
    ]
    risks = []
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }
    # AC-VT-001-01 is in staged_items (affected by staged changes)
    staged_items = {"AC-VT-001-01", "CLAIM-VT-001"}

    res = engine.evaluate(gaps, risks, compliance, staged_items=staged_items)

    # Current AC gap should block
    assert res["gate_decision"] == "blocked"
    assert len(res["blocked_items"]) > 0
    assert any("[当前]" in msg and "AC-VT-001-01" in msg for msg in res["reasons"])


def test_pre_existing_must_risk_does_not_block():
    """
    Test that a MUST-severity risk from a non-staged claim does NOT block
    in pre-commit mode.
    covers: EVO-TASK-012
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = []
    risks = [
        {
            "risk_id": "RISK-VT-020",
            "claim_id": "CLAIM-VT-002",
            "description": "Critical vulnerability found.",
            "severity": "must",
            "suggested_action": "Patch immediately",
            "business_impact": "System compromise",
        }
    ]
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }
    # Only CLAIM-VT-001 is staged
    staged_items = {"CLAIM-VT-001"}

    res = engine.evaluate(gaps, risks, compliance, staged_items=staged_items)

    assert res["gate_decision"] == "pass"
    assert len(res["blocked_items"]) == 0
    assert any("[预存]" in msg and "RISK-VT-020" in msg for msg in res["reasons"])


def test_current_must_risk_blocks():
    """
    Test that a MUST-severity risk from a staged claim DOES block.
    covers: EVO-TASK-012
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = []
    risks = [
        {
            "risk_id": "RISK-VT-021",
            "claim_id": "CLAIM-VT-001",
            "description": "Critical vulnerability found.",
            "severity": "must",
            "suggested_action": "Patch immediately",
            "business_impact": "System compromise",
        }
    ]
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }
    staged_items = {"CLAIM-VT-001"}

    res = engine.evaluate(gaps, risks, compliance, staged_items=staged_items)

    assert res["gate_decision"] == "blocked"
    assert len(res["blocked_items"]) > 0
    assert any("[当前]" in msg and "RISK-VT-021" in msg for msg in res["reasons"])


def test_mixed_current_and_pre_existing_only_current_blocks():
    """
    Test that when both current and pre-existing issues exist, only the
    current ones determine the gate decision.
    covers: EVO-TASK-012
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = [
        # Current AC gap (in staged_items)
        {
            "item_id": "AC-VT-001-01",
            "item_type": "ac",
            "reason": "Missing test coverage for AC-VT-001-01.",
        },
        # Pre-existing AC gap (NOT in staged_items)
        {
            "item_id": "AC-VT-099-01",
            "item_type": "ac",
            "reason": "Missing test coverage for AC-VT-099-01.",
        },
    ]
    risks = []
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }
    staged_items = {"AC-VT-001-01", "CLAIM-VT-001"}

    res = engine.evaluate(gaps, risks, compliance, staged_items=staged_items)

    # Should be blocked because of the current AC gap
    assert res["gate_decision"] == "blocked"
    # Only the current gap should be in blocked_items
    assert any("AC-VT-001-01" in item for item in res["blocked_items"])
    assert not any("AC-VT-099-01" in item for item in res["blocked_items"])
    # Both should appear in reasons
    assert any("[当前]" in msg and "AC-VT-001-01" in msg for msg in res["reasons"])
    assert any("[预存]" in msg and "AC-VT-099-01" in msg for msg in res["reasons"])


def test_pre_existing_should_gap_does_not_upgrade_to_fail():
    """
    Test that a SHOULD-level gap from a non-staged item does NOT upgrade
    the gate decision to "fail" in pre-commit mode.
    covers: EVO-TASK-012
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = [
        {
            "item_id": "REQ-VT-002",
            "item_type": "requirement",
            "reason": "No task coverage",
        }
    ]
    risks = []
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }
    staged_items = {"CLAIM-VT-099"}  # unrelated

    res = engine.evaluate(gaps, risks, compliance, staged_items=staged_items)

    # Pre-existing SHOULD gap should not upgrade to fail
    assert res["gate_decision"] == "pass"
    assert any("[预存]" in msg and "REQ-VT-002" in msg for msg in res["reasons"])


def test_staged_ac_in_items_matches_ac_gap():
    """
    Test that when staged_items contains an AC ID (not just claim/task IDs),
    the gate engine correctly identifies the AC gap as current.
    covers: EVO-TASK-012
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = [
        {
            "item_id": "AC-VT-001-01",
            "item_type": "ac",
            "reason": "Missing test coverage.",
        }
    ]
    risks = []
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }
    # staged_items includes the AC ID directly
    staged_items = {"AC-VT-001-01"}

    res = engine.evaluate(gaps, risks, compliance, staged_items=staged_items)

    assert res["gate_decision"] == "blocked"
    assert any("[当前]" in msg and "AC-VT-001-01" in msg for msg in res["reasons"])
