"""
Unit tests for MergeGateEngine (TASK-VT-017).
"""

from pathlib import Path
from vibe_tracing.domain.merge_gate_engine import MergeGateEngine
from vibe_tracing.infra.db import init_in_memory_db


def test_missing_ac_test_blocks():
    """
    Test that a missing Acceptance Criterion (AC) test coverage blocks the merge gate.
    covers: AC-VT-008-01
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    get [预存] prefix when staged_items is provided, but STILL block the
    gate (must-severity architecture violations always block).
    covers: EVO-TASK-025, EVO-TASK-012
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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

    # Must architecture violations always block, even in incremental mode
    assert res["gate_decision"] == "blocked"
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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

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


# ---------------------------------------------------------------
# directly_staged_items: indirect-claim fix tests
# ---------------------------------------------------------------

def test_indirectly_affected_claim_does_not_block():
    """
    Test that a MUST-severity risk for a claim whose code_refs file was
    modified (but the claim itself was NOT directly modified) is tagged
    [预存] and does NOT block the gate.

    Scenario: src/foo.py is staged.  CLAIM-VT-005 (old claim) references
    src/foo.py via code_refs.  The claim is in staged_items (indirectly
    affected) but NOT in directly_staged_items (not directly modified).
    The risk should be treated as pre-existing debt.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

    gaps = []
    risks = [
        {
            "risk_id": "RISK-VT-030",
            "claim_id": "CLAIM-VT-005",
            "description": "Claim CLAIM-VT-005 references evidence EVIDENCE-VT-010 which has status 'violated'.",
            "severity": "must",
            "risk_category": "violated_evidence",
            "suggested_action": "Re-verify the claim.",
            "business_impact": "Evidence chain broken.",
        }
    ]
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }
    # CLAIM-VT-005 is in staged_items (its code_refs file was modified)
    staged_items = {"CLAIM-VT-005", "TASK-VT-003", "AC-VT-001-01"}
    # But CLAIM-VT-005 is NOT in directly_staged_items (claim itself was not modified)
    directly_staged_items = {"TASK-VT-003", "AC-VT-001-01"}

    res = engine.evaluate(
        gaps, risks, compliance,
        staged_items=staged_items,
        directly_staged_items=directly_staged_items,
    )

    # Indirectly affected claim should NOT block
    assert res["gate_decision"] == "pass"
    assert len(res["blocked_items"]) == 0
    assert any("[预存]" in msg and "RISK-VT-030" in msg for msg in res["reasons"])


def test_directly_modified_claim_still_blocks():
    """
    Test that a MUST-severity risk for a claim that IS in directly_staged_items
    (claim definition was directly modified) still blocks the gate.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

    gaps = []
    risks = [
        {
            "risk_id": "RISK-VT-031",
            "claim_id": "CLAIM-VT-001",
            "description": "Claim CLAIM-VT-001 has only self-referential evidence.",
            "severity": "must",
            "suggested_action": "Provide external evidence.",
            "business_impact": "Violates no self-attestation rules.",
        }
    ]
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }
    # CLAIM-VT-001 is in both staged_items and directly_staged_items
    staged_items = {"CLAIM-VT-001", "TASK-VT-001"}
    directly_staged_items = {"CLAIM-VT-001", "TASK-VT-001"}

    res = engine.evaluate(
        gaps, risks, compliance,
        staged_items=staged_items,
        directly_staged_items=directly_staged_items,
    )

    # Directly modified claim should block
    assert res["gate_decision"] == "blocked"
    assert len(res["blocked_items"]) > 0
    assert any("[当前]" in msg and "RISK-VT-031" in msg for msg in res["reasons"])


def test_indirect_claim_ac_gap_still_blocks():
    """
    Test that when a claim is indirectly affected (in staged_items but not
    directly_staged_items), AC gaps for related items still block because
    AC/requirement IDs remain in directly_staged_items.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

    gaps = [
        {
            "item_id": "AC-VT-001-01",
            "item_type": "ac",
            "reason": "Missing test coverage for AC-VT-001-01.",
        }
    ]
    risks = [
        {
            "risk_id": "RISK-VT-032",
            "claim_id": "CLAIM-VT-005",
            "description": "Violated evidence.",
            "severity": "must",
            "risk_category": "violated_evidence",
            "suggested_action": "Re-verify.",
            "business_impact": "Broken chain.",
        }
    ]
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }
    # CLAIM-VT-005 is indirectly affected (in staged_items but not directly_staged_items)
    # AC-VT-001-01 is in directly_staged_items (its coverage is directly impacted)
    staged_items = {"CLAIM-VT-005", "TASK-VT-003", "AC-VT-001-01"}
    directly_staged_items = {"TASK-VT-003", "AC-VT-001-01"}

    res = engine.evaluate(
        gaps, risks, compliance,
        staged_items=staged_items,
        directly_staged_items=directly_staged_items,
    )

    # AC gap should still block (AC is in directly_staged_items)
    assert res["gate_decision"] == "blocked"
    assert any("AC-VT-001-01" in item for item in res["blocked_items"])
    assert any("[当前]" in msg and "AC-VT-001-01" in msg for msg in res["reasons"])
    # But the claim risk should be pre-existing
    assert any("[预存]" in msg and "RISK-VT-032" in msg for msg in res["reasons"])


def test_directly_staged_items_none_falls_back():
    """
    Test that when directly_staged_items is None (not provided), the engine
    falls back to staged_items for risk evaluation (backward compatible).
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

    gaps = []
    risks = [
        {
            "risk_id": "RISK-VT-033",
            "claim_id": "CLAIM-VT-001",
            "description": "Critical vulnerability.",
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

    # directly_staged_items not provided → falls back to staged_items
    res = engine.evaluate(gaps, risks, compliance, staged_items=staged_items)

    assert res["gate_decision"] == "blocked"
    assert any("[当前]" in msg and "RISK-VT-033" in msg for msg in res["reasons"])


# ---------------------------------------------------------------
# Section 2.5: Per-file coverage violations
# ---------------------------------------------------------------

def test_per_file_coverage_pass_when_all_compliant():
    """
    When all source files have >= 80% coverage (all 'compliant'),
    the gate does NOT block on coverage, even if aggregate is low.
    """
    from vibe_tracing.infra.db import upsert_coverage_report

    conn = init_in_memory_db()
    upsert_coverage_report(conn, "src/foo.py", 95.0, 100, "compliant", False)
    upsert_coverage_report(conn, "src/bar.py", 82.0, 100, "compliant", False)

    engine = MergeGateEngine(Path("/dummy/project/root"), conn)

    res = engine.evaluate([], [], {})

    assert res["gate_decision"] == "pass"
    assert not any("Coverage below 80%" in msg for msg in res["reasons"])


def test_per_file_coverage_blocks_when_violated():
    """
    When a source file has < 80% coverage (status 'violated'),
    the gate blocks.
    """
    from vibe_tracing.infra.db import upsert_coverage_report

    conn = init_in_memory_db()
    upsert_coverage_report(conn, "src/foo.py", 95.0, 100, "compliant", False)
    upsert_coverage_report(conn, "src/bad.py", 45.0, 100, "violated", False)

    engine = MergeGateEngine(Path("/dummy/project/root"), conn)

    res = engine.evaluate([], [], {})

    assert res["gate_decision"] == "blocked"
    assert any("src/bad.py" in msg and "45.0%" in msg for msg in res["reasons"])


def test_per_file_coverage_ignores_non_coverage_evidence():
    """
    Evidence entries with tool_category != 'coverage' are ignored.
    Coverage violations are now sourced from DB, not evidence_index.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

    # No coverage data in DB -> no coverage violations -> pass
    res = engine.evaluate([], [], {})

    # lint violation should not affect coverage gate
    assert res["gate_decision"] == "pass"


# ---------------------------------------------------------------
# Human decisions integration tests
# ---------------------------------------------------------------

def test_human_decisions_applied_field_always_present():
    """
    The human_decisions_applied field should be present in the return dict
    even when no human_decisions are provided (value 0).
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

    res = engine.evaluate([], [], {})

    assert "human_decisions_applied" in res
    assert res["human_decisions_applied"] == 0


def test_accept_risk_unblocks_must_risk():
    """
    A MUST-severity risk with a matching accept_risk human decision
    should be downgraded to 'accepted' and NOT block the gate.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

    risks = [
        {
            "risk_id": "RISK-VT-050",
            "target_id": "RISK-VT-050",
            "description": "Critical vulnerability found.",
            "severity": "must",
            "suggested_action": "Patch immediately",
            "business_impact": "System compromise",
        }
    ]
    human_decisions = [
        {
            "decision_id": 1,
            "category": "risk",
            "targetId": "RISK-VT-050",
            "action": "accept_risk",
            "reason": "Accepted by tech lead",
            "decidedBy": "tech_lead",
            "timestamp": "2026-06-09T10:00:00Z",
        }
    ]

    res = engine.evaluate([], risks, {}, human_decisions=human_decisions)

    assert res["gate_decision"] == "pass"
    assert len(res["blocked_items"]) == 0
    assert any("[已接受风险]" in msg for msg in res["reasons"])
    assert res["human_decisions_applied"] == 1


def test_mark_complete_unblocks_ac_gap():
    """
    An AC gap with a matching mark_complete human decision
    should be marked 'human_resolved' and NOT block the gate.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

    gaps = [
        {
            "item_id": "AC-VT-001-01",
            "item_type": "ac",
            "target_id": "AC-VT-001-01",
            "reason": "Missing test coverage.",
        }
    ]
    human_decisions = [
        {
            "decision_id": 2,
            "category": "gap",
            "targetId": "AC-VT-001-01",
            "action": "mark_complete",
            "reason": "Verified manually",
            "decidedBy": "qa_lead",
            "timestamp": "2026-06-09T10:00:00Z",
        }
    ]

    res = engine.evaluate(gaps, [], {}, human_decisions=human_decisions)

    assert res["gate_decision"] == "pass"
    assert len(res["blocked_items"]) == 0
    assert any("[已人工完成]" in msg for msg in res["reasons"])
    assert res["human_decisions_applied"] == 1


def test_human_decisions_wrapper_format():
    """
    human_decisions can be passed as {"decisions": [...]} wrapper dict.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

    risks = [
        {
            "risk_id": "RISK-VT-051",
            "target_id": "RISK-VT-051",
            "description": "High risk issue.",
            "severity": "must",
            "suggested_action": "Fix it",
            "business_impact": "Major impact",
        }
    ]
    human_decisions = {
        "decisions": [
            {
                "decision_id": 3,
                "category": "risk",
                "targetId": "RISK-VT-051",
                "action": "accept_risk",
                "reason": "Risk accepted",
                "decidedBy": "pm",
                "timestamp": "2026-06-09T11:00:00Z",
            }
        ]
    }

    res = engine.evaluate([], risks, {}, human_decisions=human_decisions)

    assert res["gate_decision"] == "pass"
    assert res["human_decisions_applied"] == 1


def test_human_decisions_empty_list_no_effect():
    """
    An empty human_decisions list should have no effect on gate logic.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

    risks = [
        {
            "risk_id": "RISK-VT-052",
            "target_id": "RISK-VT-052",
            "description": "Critical issue.",
            "severity": "must",
            "suggested_action": "Fix",
            "business_impact": "Major",
        }
    ]

    res = engine.evaluate([], risks, {}, human_decisions=[])

    assert res["gate_decision"] == "blocked"
    assert res["human_decisions_applied"] == 0


def test_human_decisions_none_backward_compatible():
    """
    human_decisions=None (default) should behave identically to before.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

    risks = [
        {
            "risk_id": "RISK-VT-053",
            "target_id": "RISK-VT-053",
            "description": "Critical issue.",
            "severity": "must",
            "suggested_action": "Fix",
            "business_impact": "Major",
        }
    ]

    res = engine.evaluate([], risks, {})

    assert res["gate_decision"] == "blocked"
    assert res["human_decisions_applied"] == 0
    assert not any("[已接受风险]" in msg for msg in res["reasons"])


def test_mismatched_target_id_does_not_accept():
    """
    A human decision with a targetId that doesn't match any risk
    should not affect the gate decision.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

    risks = [
        {
            "risk_id": "RISK-VT-054",
            "target_id": "RISK-VT-054",
            "description": "Critical issue.",
            "severity": "must",
            "suggested_action": "Fix",
            "business_impact": "Major",
        }
    ]
    human_decisions = [
        {
            "decision_id": 4,
            "category": "risk",
            "targetId": "RISK-VT-999",  # doesn't match
            "action": "accept_risk",
            "reason": "Wrong target",
            "decidedBy": "someone",
            "timestamp": "2026-06-09T10:00:00Z",
        }
    ]

    res = engine.evaluate([], risks, {}, human_decisions=human_decisions)

    assert res["gate_decision"] == "blocked"
    assert res["human_decisions_applied"] == 1  # decision was parsed but had no matching target


def test_mixed_human_decisions_risk_and_gap():
    """
    Multiple human decisions can be applied simultaneously to both risks and gaps.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

    gaps = [
        {
            "item_id": "AC-VT-060-01",
            "item_type": "ac",
            "target_id": "AC-VT-060-01",
            "reason": "Missing test coverage.",
        }
    ]
    risks = [
        {
            "risk_id": "RISK-VT-060",
            "target_id": "RISK-VT-060",
            "description": "Critical vulnerability.",
            "severity": "must",
            "suggested_action": "Patch",
            "business_impact": "Compromise",
        }
    ]
    human_decisions = [
        {
            "decision_id": 5,
            "category": "risk",
            "targetId": "RISK-VT-060",
            "action": "accept_risk",
            "reason": "Accepted",
            "decidedBy": "tech_lead",
            "timestamp": "2026-06-09T10:00:00Z",
        },
        {
            "decision_id": 6,
            "category": "gap",
            "targetId": "AC-VT-060-01",
            "action": "mark_complete",
            "reason": "Verified",
            "decidedBy": "qa_lead",
            "timestamp": "2026-06-09T10:00:00Z",
        },
    ]

    res = engine.evaluate(gaps, risks, {}, human_decisions=human_decisions)

    assert res["gate_decision"] == "pass"
    assert len(res["blocked_items"]) == 0
    assert res["human_decisions_applied"] == 2
    assert any("[已接受风险]" in msg for msg in res["reasons"])
    assert any("[已人工完成]" in msg for msg in res["reasons"])


def test_accept_risk_on_should_risk_no_fail():
    """
    A SHOULD-severity risk with a matching accept_risk decision
    should not contribute to the 'fail' gate decision.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

    risks = [
        {
            "risk_id": "RISK-VT-070",
            "target_id": "RISK-VT-070",
            "description": "Minor style issue.",
            "severity": "should",
            "confidence": "low_confidence",
            "type": "suggestion",
        }
    ]
    human_decisions = [
        {
            "decision_id": 7,
            "category": "risk",
            "targetId": "RISK-VT-070",
            "action": "accept_risk",
            "reason": "Not important",
            "decidedBy": "tech_lead",
            "timestamp": "2026-06-09T10:00:00Z",
        }
    ]

    res = engine.evaluate([], risks, {}, human_decisions=human_decisions)

    assert res["gate_decision"] == "pass"
    assert res["human_decisions_applied"] == 1
    assert any("[已接受风险]" in msg for msg in res["reasons"])


def test_mark_complete_on_should_gap_no_fail():
    """
    A SHOULD-level gap with a matching mark_complete decision
    should not contribute to the 'fail' gate decision.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

    gaps = [
        {
            "item_id": "REQ-VT-080",
            "item_type": "requirement",
            "target_id": "REQ-VT-080",
            "reason": "No task coverage",
        }
    ]
    human_decisions = [
        {
            "decision_id": 8,
            "category": "gap",
            "targetId": "REQ-VT-080",
            "action": "mark_complete",
            "reason": "Covered by other work",
            "decidedBy": "pm",
            "timestamp": "2026-06-09T10:00:00Z",
        }
    ]

    res = engine.evaluate(gaps, [], {}, human_decisions=human_decisions)

    assert res["gate_decision"] == "pass"
    assert res["human_decisions_applied"] == 1
    assert any("[已人工完成]" in msg for msg in res["reasons"])


def test_risk_without_target_id_not_affected():
    """
    A risk without a target_id field should not be affected by any human decision,
    even if the risk_id matches a decision's targetId.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

    risks = [
        {
            "risk_id": "RISK-VT-090",
            # no target_id field
            "description": "Critical issue.",
            "severity": "must",
            "suggested_action": "Fix",
            "business_impact": "Major",
        }
    ]
    human_decisions = [
        {
            "decision_id": 9,
            "category": "risk",
            "targetId": "RISK-VT-090",
            "action": "accept_risk",
            "reason": "Accepted",
            "decidedBy": "tech_lead",
            "timestamp": "2026-06-09T10:00:00Z",
        }
    ]

    res = engine.evaluate([], risks, {}, human_decisions=human_decisions)

    # Without target_id on the risk, the decision cannot match
    assert res["gate_decision"] == "blocked"
    assert res["human_decisions_applied"] == 1  # decision was parsed but had no effect


def test_gap_without_target_id_not_affected():
    """
    A gap without a target_id field should not be affected by any human decision.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())

    gaps = [
        {
            "item_id": "AC-VT-090-01",
            "item_type": "ac",
            # no target_id field
            "reason": "Missing test coverage.",
        }
    ]
    human_decisions = [
        {
            "decision_id": 10,
            "category": "gap",
            "targetId": "AC-VT-090-01",
            "action": "mark_complete",
            "reason": "Verified",
            "decidedBy": "qa_lead",
            "timestamp": "2026-06-09T10:00:00Z",
        }
    ]

    res = engine.evaluate(gaps, [], {}, human_decisions=human_decisions)

    # Without target_id on the gap, the decision cannot match
    assert res["gate_decision"] == "blocked"
    assert res["human_decisions_applied"] == 1  # decision was parsed but had no effect


# ---------------------------------------------------------------
# Claim existence check tests (evaluate integration)
# ---------------------------------------------------------------

class TestEvaluateClaimExistence:
    """Integration tests for claim existence check within evaluate()."""

    def test_staged_items_none_skips_check(self):
        """When staged_items=None, the check is skipped."""
        engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())
        res = engine.evaluate([], [], {})
        assert res["gate_decision"] == "pass"

    def test_all_claimed_passes(self):
        """When all staged code files are claimed in the DB, gate passes."""
        from vibe_tracing.infra.db import load_claims, load_staged_files

        conn = init_in_memory_db()
        load_claims(conn, [
            {"claim_id": "C1", "related_task": "T1", "code_refs": ["src/foo.py"], "test_refs": []},
        ])
        load_staged_files(conn, {"src/foo.py"})

        engine = MergeGateEngine(Path("/dummy/project/root"), conn)
        res = engine.evaluate([], [], {}, staged_items={"src/foo.py"})
        assert res["gate_decision"] == "pass"

    def test_unclaimed_file_blocks(self):
        """An unclaimed staged file blocks the gate with missing_claim gap."""
        from vibe_tracing.infra.db import load_claims, load_staged_files

        conn = init_in_memory_db()
        load_claims(conn, [
            {"claim_id": "C1", "related_task": "T1", "code_refs": ["src/foo.py"], "test_refs": []},
        ])
        load_staged_files(conn, {"src/foo.py", "src/orphan.py"})

        engine = MergeGateEngine(Path("/dummy/project/root"), conn)
        gaps = []
        res = engine.evaluate(gaps, [], {}, staged_items={"src/foo.py", "src/orphan.py"})
        assert res["gate_decision"] == "blocked"
        assert any("src/orphan.py" in item for item in res["blocked_items"])
        assert any("src/orphan.py" in msg for msg in res["reasons"])
        assert any("missing_claim" in gap.get("item_type", "") for gap in gaps)

    def test_unclaimed_gap_appended_to_gaps(self):
        """Unclaimed files produce gaps with item_type='missing_claim'."""
        from vibe_tracing.infra.db import load_claims, load_staged_files

        conn = init_in_memory_db()
        load_claims(conn, [
            {"claim_id": "C1", "related_task": "T1", "code_refs": ["src/foo.py"], "test_refs": []},
        ])
        load_staged_files(conn, {"src/foo.py", "src/orphan.py"})

        engine = MergeGateEngine(Path("/dummy/project/root"), conn)
        gaps = []
        res = engine.evaluate(gaps, [], {}, staged_items={"src/foo.py", "src/orphan.py"})
        assert res["gate_decision"] == "blocked"
        assert any(g.get("item_type") == "missing_claim" for g in gaps)

    def test_unclaimed_file_gets_current_prefix(self):
        """Unclaimed file reasons get [当前] prefix when staged_items is provided."""
        from vibe_tracing.infra.db import load_claims, load_staged_files

        conn = init_in_memory_db()
        load_claims(conn, [
            {"claim_id": "C1", "related_task": "T1", "code_refs": ["src/foo.py"], "test_refs": []},
        ])
        load_staged_files(conn, {"src/foo.py", "src/orphan.py"})

        engine = MergeGateEngine(Path("/dummy/project/root"), conn)
        res = engine.evaluate([], [], {}, staged_items={"src/foo.py", "src/orphan.py"})
        assert any("[当前]" in msg and "src/orphan.py" in msg for msg in res["reasons"])

    def test_multiple_unclaimed_files_sorted(self):
        """Multiple unclaimed files appear in sorted order in reasons."""
        from vibe_tracing.infra.db import load_claims, load_staged_files

        conn = init_in_memory_db()
        load_claims(conn, [
            {"claim_id": "C1", "related_task": "T1", "code_refs": ["src/foo.py"], "test_refs": []},
        ])
        load_staged_files(conn, {"src/foo.py", "src/aaa.py", "src/zzz.py"})

        engine = MergeGateEngine(Path("/dummy/project/root"), conn)
        res = engine.evaluate([], [], {}, staged_items={"src/foo.py", "src/aaa.py", "src/zzz.py"})
        assert res["gate_decision"] == "blocked"
        assert len(res["blocked_items"]) == 2
        aaa_idx = next(i for i, m in enumerate(res["reasons"]) if "src/aaa.py" in m)
        zzz_idx = next(i for i, m in enumerate(res["reasons"]) if "src/zzz.py" in m)
        assert aaa_idx < zzz_idx

    def test_claim_existence_blocks_even_with_other_pass_conditions(self):
        """Claim existence block takes effect even when no other gaps/risks exist."""
        from vibe_tracing.infra.db import load_staged_files

        conn = init_in_memory_db()
        load_staged_files(conn, {"src/orphan.py"})

        engine = MergeGateEngine(Path("/dummy/project/root"), conn)
        res = engine.evaluate([], [], {}, staged_items={"src/orphan.py"})
        assert res["gate_decision"] == "blocked"
        assert any("src/orphan.py" in item for item in res["blocked_items"])

    def test_backward_compatible_no_staged(self):
        """Without staged_items, behavior is identical to before."""
        engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())
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


# ---------------------------------------------------------------
# AC coverage derivation tests (evaluate integration)
# ---------------------------------------------------------------

class TestEvaluateAcCoverage:
    """Integration tests for AC coverage derivation within evaluate()."""

    def test_ac_coverage_blocks_when_uncovered(self):
        """An uncovered MUST AC blocks the gate."""
        from vibe_tracing.infra.db import load_tasks

        conn = init_in_memory_db()
        load_tasks(conn, [
            {
                "task_id": "TASK-VT-001",
                "priority": "must",
                "status": "done",
                "related_acceptance_criteria": ["AC-VT-001-01"],
            }
        ])

        engine = MergeGateEngine(Path("/dummy/project/root"), conn)
        res = engine.evaluate([], [], {})
        assert res["gate_decision"] == "blocked"
        assert any("AC-VT-001-01" in item for item in res["blocked_items"])

    def test_ac_coverage_passes_when_covered_by_passing_test(self):
        """AC coverage passes when a passing test exists in the DB."""
        from vibe_tracing.infra.db import load_tasks, load_claims, upsert_test_result

        conn = init_in_memory_db()
        load_tasks(conn, [
            {
                "task_id": "TASK-VT-001",
                "priority": "must",
                "status": "done",
                "related_acceptance_criteria": ["AC-VT-001-01"],
            }
        ])
        load_claims(conn, [
            {
                "claim_id": "CLAIM-VT-001",
                "related_task": "TASK-VT-001",
                "test_refs": ["tests/test_foo.py"],
            }
        ])
        upsert_test_result(conn, "tests/test_foo.py", "passed", 0, "pytest", False)

        engine = MergeGateEngine(Path("/dummy/project/root"), conn)
        res = engine.evaluate([], [], {})
        assert res["gate_decision"] == "pass"

    def test_ac_gap_appended_to_gaps_list(self):
        """Uncovered AC produces a gap entry in the gaps list."""
        from vibe_tracing.infra.db import load_tasks

        conn = init_in_memory_db()
        load_tasks(conn, [
            {
                "task_id": "TASK-VT-001",
                "priority": "must",
                "status": "done",
                "related_acceptance_criteria": ["AC-VT-001-01"],
            }
        ])

        engine = MergeGateEngine(Path("/dummy/project/root"), conn)
        gaps = []
        engine.evaluate(gaps, [], {})
        assert any(
            g.get("item_type") == "ac"
            and g.get("category") == "ac_not_covered"
            for g in gaps
        )

    def test_ac_not_covered_uses_hint(self):
        """The reason message uses the ac_not_covered hint from field_hints.json."""
        from vibe_tracing.infra.db import load_tasks

        conn = init_in_memory_db()
        load_tasks(conn, [
            {
                "task_id": "TASK-VT-001",
                "priority": "must",
                "status": "done",
                "related_acceptance_criteria": ["AC-VT-001-01"],
            }
        ])

        engine = MergeGateEngine(Path("/dummy/project/root"), conn)
        res = engine.evaluate([], [], {})
        assert any("AC-VT-001-01" in msg for msg in res["reasons"])
        assert any("TASK-VT-001" in msg for msg in res["reasons"])

    def test_ac_coverage_with_test_failed_in_db(self):
        """A MUST AC with a failed test in DB blocks with test_failed reason."""
        from vibe_tracing.infra.db import load_tasks, load_claims, upsert_test_result

        conn = init_in_memory_db()
        load_tasks(conn, [
            {
                "task_id": "TASK-VT-001",
                "priority": "must",
                "status": "done",
                "related_acceptance_criteria": ["AC-VT-001-01"],
            }
        ])
        load_claims(conn, [
            {
                "claim_id": "CLAIM-VT-001",
                "related_task": "TASK-VT-001",
                "test_refs": ["tests/test_foo.py"],
            }
        ])
        upsert_test_result(conn, "tests/test_foo.py", "failed", 1, "pytest", False)

        engine = MergeGateEngine(Path("/dummy/project/root"), conn)
        res = engine.evaluate([], [], {})
        assert res["gate_decision"] == "blocked"
        assert any("test_failed" in msg for msg in res["reasons"])

    def test_backward_compatible_no_tasks(self):
        """Without tasks in DB, behavior is identical to before."""
        engine = MergeGateEngine(Path("/dummy/project/root"), init_in_memory_db())
        res = engine.evaluate([], [], {})
        assert res["gate_decision"] == "pass"
        assert "所有质量门禁规则均已通过" in res["reasons"][0]
