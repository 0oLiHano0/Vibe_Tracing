"""
Unit tests for MergeGateEngine (TASK-VT-017).
"""

from pathlib import Path
from vibe_tracing.domain.gate.engine import MergeGateEngine


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
    Test that a MUST architecture constraint violation blocks the gate.
    covers: AC-VT-008-03
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = []
    risks = []
    compliance = {
        "architecture_compliance_status": [
            {
                "rule_id": "ARCH-RULE-MUST-001",
                "status": "violated",
                "severity": "must",
            }
        ],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    res = engine.evaluate(gaps, risks, compliance)

    assert res["gate_decision"] == "blocked"
    assert any("ARCH-RULE-MUST-001" in msg for msg in res["reasons"])


def test_unclear_constraint_produces_fail():
    """
    Test that an unclear architecture constraint produces 'fail' (not 'blocked').
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = []
    risks = []
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [
            {
                "rule_id": "ARCH-RULE-UNCLEAR-001",
                "reason": "Cannot automatically verify module boundary.",
            }
        ],
    }

    res = engine.evaluate(gaps, risks, compliance)

    assert res["gate_decision"] == "fail"
    assert any("ARCH-RULE-UNCLEAR-001" in msg for msg in res["reasons"])


def test_pass_when_no_gaps_risks_or_violations():
    """
    Test that the gate passes when there are no gaps, risks, or violations.
    covers: AC-VT-008-01
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
    assert any("所有质量门禁规则均已通过" in msg for msg in res["reasons"])
    assert len(res["blocked_items"]) == 0


def test_architecture_violation_blocks():
    """
    Test that an architecture violation in compliance result blocks the gate.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = []
    risks = []
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [
            {
                "rule_id": "FORBID-VT-001",
                "message": "Self-attestation detected.",
            }
        ],
        "unclear_constraints": [],
    }

    res = engine.evaluate(gaps, risks, compliance)

    assert res["gate_decision"] == "blocked"
    assert any("FORBID-VT-001" in msg for msg in res["reasons"])


def test_should_gap_produces_fail():
    """
    Test that a SHOULD-level gap produces 'fail' decision.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = [
        {
            "item_id": "REQ-VT-003",
            "item_type": "requirement",
            "reason": "Should requirement has no task coverage.",
        }
    ]
    risks = []
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    res = engine.evaluate(gaps, risks, compliance)

    assert res["gate_decision"] == "fail"
    assert any("REQ-VT-003" in msg for msg in res["reasons"])


def test_mixed_gaps_blocks_when_must_present():
    """
    Test that mixed gaps (must + should) result in 'blocked' when a must gap exists.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = [
        {
            "item_id": "AC-VT-001-01",
            "item_type": "ac",
            "reason": "Must AC missing test.",
        },
        {
            "item_id": "REQ-VT-003",
            "item_type": "requirement",
            "reason": "Should requirement has no task coverage.",
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
    # Both reasons should be present
    assert any("AC-VT-001-01" in msg for msg in res["reasons"])
    assert any("REQ-VT-003" in msg for msg in res["reasons"])


def test_should_risk_produces_fail():
    """
    Test that a SHOULD-level risk produces 'fail' decision.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = []
    risks = [
        {
            "risk_id": "RISK-VT-003",
            "description": "Low priority improvement suggestion.",
            "severity": "should",
        }
    ]
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    res = engine.evaluate(gaps, risks, compliance)

    assert res["gate_decision"] == "fail"
    assert any("RISK-VT-003" in msg for msg in res["reasons"])


def test_gate_decision_priority_blocked_over_fail():
    """
    Test that 'blocked' takes priority over 'fail' when both conditions exist.
    """
    engine = MergeGateEngine(Path("/dummy/project/root"))

    gaps = [
        {
            "item_id": "AC-VT-001-01",
            "item_type": "ac",
            "reason": "Must AC missing test.",
        },
    ]
    risks = [
        {
            "risk_id": "RISK-VT-003",
            "description": "Low priority improvement suggestion.",
            "severity": "should",
        }
    ]
    compliance = {
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
    }

    res = engine.evaluate(gaps, risks, compliance)

    assert res["gate_decision"] == "blocked"


# ---------------------------------------------------------------
# Dangling claims tests (Rule 3)
# ---------------------------------------------------------------

class TestDanglingClaims:
    """Tests for Rule 3: dangling claims detection."""

    def test_dangling_claims_blocks(self):
        """Claims referencing non-existent tasks block the gate."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        dangling_claims = [{"claim_id": "CLAIM-1", "related_task": "TASK-MISSING"}]
        res = engine.evaluate([], [], {}, dangling_claims=dangling_claims)

        assert res["gate_decision"] == "blocked"
        assert any("CLAIM-1" in item for item in res["blocked_items"])

    def test_no_dangling_claims_passes(self):
        """Empty dangling claims list doesn't block."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        res = engine.evaluate([], [], {}, dangling_claims=[])

        assert res["gate_decision"] == "pass"

    def test_dangling_claims_none_skips(self):
        """When dangling_claims is None, Rule 3 is skipped."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        res = engine.evaluate([], [], {}, dangling_claims=None)

        assert res["gate_decision"] == "pass"


# ---------------------------------------------------------------
# Claim evidence gaps tests (Rule 4)
# ---------------------------------------------------------------

class TestClaimEvidenceGaps:
    """Tests for Rule 4: claim evidence gaps detection."""

    def test_claim_evidence_test_failed_blocks(self):
        """Claims with failed tests block the gate."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        claim_evidence_gaps = [{"claim_id": "CLAIM-1", "verification_status": "test_failed"}]
        res = engine.evaluate([], [], {}, claim_evidence_gaps=claim_evidence_gaps)

        assert res["gate_decision"] == "blocked"
        assert any("CLAIM-1" in item for item in res["blocked_items"])

    def test_claim_evidence_no_tests_not_blocked(self):
        """Claims with no tests produce warning but don't block."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        claim_evidence_gaps = [{"claim_id": "CLAIM-1", "verification_status": "no_tests"}]
        res = engine.evaluate([], [], {}, claim_evidence_gaps=claim_evidence_gaps)

        assert res["gate_decision"] != "blocked"


# ---------------------------------------------------------------
# Ghost code tests (Rule 2)
# ---------------------------------------------------------------

class TestGhostCode:
    """Tests for Rule 2: ghost code detection."""

    def test_no_ghost_files_passes(self):
        """Empty ghost files list doesn't block."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        res = engine.evaluate([], [], {}, ghost_files=[], staged_items={"src/foo.py"})

        assert res["gate_decision"] == "pass"

    def test_ghost_files_none_skips(self):
        """When ghost_files is None, Rule 2 is skipped."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        res = engine.evaluate([], [], {}, ghost_files=None)

        assert res["gate_decision"] == "pass"



# ---------------------------------------------------------------
# AC coverage tests (Rule 5)
# ---------------------------------------------------------------

class TestAcCoverage:
    """Tests for Rule 5: AC coverage check."""

    def test_ac_gaps_blocks(self):
        """Uncovered ACs block the gate."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        ac_gaps = [{"ac_id": "AC-VT-001-01", "task_id": "TASK-VT-001", "coverage_status": "no_tests_declared"}]
        res = engine.evaluate([], [], {}, ac_gaps=ac_gaps)

        assert res["gate_decision"] == "blocked"
        assert any("AC-VT-001-01" in item for item in res["blocked_items"])

    def test_no_ac_gaps_passes(self):
        """Empty AC gaps list doesn't block."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        res = engine.evaluate([], [], {}, ac_gaps=[])

        assert res["gate_decision"] == "pass"

    def test_ac_gaps_none_skips(self):
        """When ac_gaps is None, Rule 5 is skipped."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        res = engine.evaluate([], [], {}, ac_gaps=None)

        assert res["gate_decision"] == "pass"


# ---------------------------------------------------------------
# Coverage violations tests
# ---------------------------------------------------------------

class TestCoverageViolations:
    """Tests for coverage violations check (warning-level, not blocking)."""

    def test_coverage_violations_fail_not_blocked(self):
        """Coverage violations produce 'fail' (warning), not 'blocked'."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        cov_violations = [{"source_path": "src/foo.py", "percent_covered": 45.0, "carried_over": False}]
        res = engine.evaluate([], [], {}, cov_violations=cov_violations)

        assert res["gate_decision"] == "fail"
        assert any("src/foo.py" in msg for msg in res["reasons"])

    def test_no_coverage_violations_passes(self):
        """Empty coverage violations list doesn't block."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        res = engine.evaluate([], [], {}, cov_violations=[])

        assert res["gate_decision"] == "pass"

    def test_coverage_violations_do_not_override_blocked(self):
        """Coverage violations don't downgrade an already-blocked gate."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        ac_gaps = [{"ac_id": "AC-1", "task_id": "TASK-1", "coverage_status": "no_tests_declared"}]
        cov_violations = [{"source_path": "src/foo.py", "percent_covered": 45.0, "carried_over": False}]
        res = engine.evaluate([], [], {}, ac_gaps=ac_gaps, cov_violations=cov_violations)

        assert res["gate_decision"] == "blocked"

    def test_coverage_violations_incremental_filters_carried_over(self):
        """In incremental mode, carried_over violations are counted as historical debt."""
        engine = MergeGateEngine(Path("/dummy/project/root"), incremental_only=True)

        cov_violations = [
            {"source_path": "src/old.py", "percent_covered": 30.0, "carried_over": True},
            {"source_path": "src/new.py", "percent_covered": 40.0, "carried_over": False},
        ]
        res = engine.evaluate([], [], {}, cov_violations=cov_violations)

        assert any("src/new.py" in msg for msg in res["reasons"])
        assert not any("src/old.py" in msg for msg in res["reasons"])
        assert res["historical_debt_count"] >= 1

    def test_coverage_violations_all_historical_incremental_pass(self):
        """All carried_over violations in incremental mode produce pass."""
        engine = MergeGateEngine(Path("/dummy/project/root"), incremental_only=True)

        cov_violations = [
            {"source_path": "src/old.py", "percent_covered": 30.0, "carried_over": True},
        ]
        res = engine.evaluate([], [], {}, cov_violations=cov_violations)

        assert res["gate_decision"] == "pass"
        assert res["historical_debt_count"] >= 1


# ---------------------------------------------------------------
# Human decisions tests
# ---------------------------------------------------------------

class TestHumanDecisions:
    """Tests for human decisions integration."""

    def test_mark_complete_resolves_gap(self):
        """mark_complete human decision resolves a gap."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        gaps = [
            {
                "item_id": "AC-VT-001-01",
                "item_type": "ac",
                "target_id": "AC-VT-001-01",
                "reason": "Must AC missing test.",
            }
        ]
        human_decisions = {
            "decisions": [
                {
                    "category": "mark_complete",
                    "targetId": "AC-VT-001-01",
                    "action": "mark_complete",
                }
            ]
        }

        res = engine.evaluate(gaps, [], {}, human_decisions=human_decisions)

        assert res["gate_decision"] == "pass"
        assert res["human_decisions_applied"] > 0

    def test_accept_risk_downgrades_risk(self):
        """accept_risk human decision downgrades a risk."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        risks = [
            {
                "risk_id": "RISK-VT-001",
                "description": "High risk issue.",
                "severity": "must",
                "target_id": "RISK-VT-001",
            }
        ]
        human_decisions = {
            "decisions": [
                {
                    "category": "accept_risk",
                    "targetId": "RISK-VT-001",
                    "action": "accept_risk",
                }
            ]
        }

        res = engine.evaluate([], risks, {}, human_decisions=human_decisions)

        assert res["gate_decision"] == "pass"
        assert res["human_decisions_applied"] > 0


# ---------------------------------------------------------------
# Staged items tests
# ---------------------------------------------------------------

class TestStagedItems:
    """Tests for staged items awareness."""

    def test_staged_items_none_full_analysis(self):
        """When staged_items is None, all items are considered current."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        gaps = [
            {
                "item_id": "AC-VT-001-01",
                "item_type": "ac",
                "reason": "Must AC missing test.",
            }
        ]

        res = engine.evaluate(gaps, [], {}, staged_items=None)

        assert res["gate_decision"] == "blocked"

    def test_staged_items_with_current_item(self):
        """Current staged items are evaluated normally."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        gaps = [
            {
                "item_id": "AC-VT-001-01",
                "item_type": "ac",
                "reason": "Must AC missing test.",
            }
        ]

        res = engine.evaluate(gaps, [], {}, staged_items={"AC-VT-001-01"})

        assert res["gate_decision"] == "blocked"
        assert any("[当前]" in msg for msg in res["reasons"])

    def test_staged_items_with_preexisting_item(self):
        """Pre-existing items get [预存] prefix and don't block."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        gaps = [
            {
                "item_id": "AC-VT-001-01",
                "item_type": "ac",
                "reason": "Must AC missing test.",
            }
        ]

        res = engine.evaluate(gaps, [], {}, staged_items={"OTHER-ITEM"})

        assert res["gate_decision"] != "blocked"
        assert any("[预存]" in msg for msg in res["reasons"])


class TestIncrementalMode:
    """Test incremental_only mode (TASK-VT-096)."""

    def test_incremental_mode_initialization(self):
        """Test MergeGateEngine initialization with incremental_only."""
        engine = MergeGateEngine(
            Path("/dummy/project/root"),
            incremental_only=True,
            show_historical_debt=False,
        )

        assert engine.incremental_only is True
        assert engine.show_historical_debt is False

    def test_rule3_incremental_mode(self):
        """Test Rule 3 (dangling claims) in incremental mode."""
        engine = MergeGateEngine(
            Path("/dummy/project/root"),
            incremental_only=True,
        )

        gaps = []
        risks = []
        dangling_claims = [
            {
                "claim_id": "CLAIM-003",
                "related_task": "TASK-999",
            }
        ]
        staged_items = {"CLAIM-005"}  # Different claim

        res = engine.evaluate(
            gaps, risks,
            dangling_claims=dangling_claims,
            staged_items=staged_items,
        )

        # Historical dangling claim should NOT block in incremental mode
        assert res["gate_decision"] == "pass"
        assert res["historical_debt_count"] == 1

    def test_rule4_incremental_mode(self):
        """Test Rule 4 (claim evidence gaps) in incremental mode."""
        engine = MergeGateEngine(
            Path("/dummy/project/root"),
            incremental_only=True,
        )

        gaps = []
        risks = []
        claim_evidence_gaps = [
            {
                "claim_id": "CLAIM-003",
                "verification_status": "test_failed",
            }
        ]
        staged_items = {"CLAIM-005"}  # Different claim

        res = engine.evaluate(
            gaps, risks,
            claim_evidence_gaps=claim_evidence_gaps,
            staged_items=staged_items,
        )

        # Historical failed test should NOT block in incremental mode
        assert res["gate_decision"] == "pass"
        assert res["historical_debt_count"] == 1

    def test_rule5_incremental_mode(self):
        """Test Rule 5 (AC coverage) in incremental mode."""
        engine = MergeGateEngine(
            Path("/dummy/project/root"),
            incremental_only=True,
        )

        gaps = []
        risks = []
        ac_gaps = [
            {
                "ac_id": "AC-VT-001-01",
                "task_id": "TASK-VT-001",
                "coverage_status": "no_test_coverage",
            }
        ]
        staged_items = {"CLAIM-005"}  # Different claim

        res = engine.evaluate(
            gaps, risks,
            ac_gaps=ac_gaps,
            staged_items=staged_items,
        )

        # Historical AC gap should NOT block in incremental mode
        assert res["gate_decision"] == "pass"
        assert res["historical_debt_count"] == 1

    def test_incremental_mode_result_fields(self):
        """Test that incremental mode adds result fields."""
        engine = MergeGateEngine(
            Path("/dummy/project/root"),
            incremental_only=True,
        )

        res = engine.evaluate([], [], {})

        assert "incremental_mode" in res
        assert "historical_debt_count" in res
        assert res["incremental_mode"] is True
        assert res["historical_debt_count"] == 0


# ---------------------------------------------------------------
# Isolated tasks tests (Stage 8 Fix 1)
# ---------------------------------------------------------------

class TestIsolatedTasks:
    """Tests for isolated tasks warning."""

    def test_isolated_tasks_appear_in_reasons(self):
        """Isolated tasks appear as warnings in reasons, gate still passes."""
        engine = MergeGateEngine(Path("/dummy/project/root"))
        isolated_tasks = [
            {"task_id": "TASK-005", "reason": "无关联需求/AC"},
        ]
        res = engine.evaluate([], [], {}, isolated_tasks=isolated_tasks)
        assert res["gate_decision"] == "pass"
        assert any("TASK-005" in msg for msg in res["reasons"])
        assert any("[告警]" in msg for msg in res["reasons"])

    def test_no_isolated_tasks_passes(self):
        """Empty isolated tasks list produces pass."""
        engine = MergeGateEngine(Path("/dummy/project/root"))
        res = engine.evaluate([], [], {}, isolated_tasks=[])
        assert res["gate_decision"] == "pass"
        assert not any("[告警]" in msg for msg in res["reasons"])

    def test_isolated_tasks_none_skips(self):
        """When isolated_tasks is None, no warning added."""
        engine = MergeGateEngine(Path("/dummy/project/root"))
        res = engine.evaluate([], [], {}, isolated_tasks=None)
        assert res["gate_decision"] == "pass"
        assert not any("[告警]" in msg for msg in res["reasons"])

    def test_isolated_tasks_do_not_override_blocked(self):
        """Isolated tasks don't downgrade an already-blocked gate."""
        engine = MergeGateEngine(Path("/dummy/project/root"))
        ac_gaps = [{"ac_id": "AC-1", "task_id": "TASK-1", "coverage_status": "no_tests_declared"}]
        isolated_tasks = [{"task_id": "TASK-005", "reason": "无关联需求/AC"}]
        res = engine.evaluate([], [], {}, ac_gaps=ac_gaps, isolated_tasks=isolated_tasks)
        assert res["gate_decision"] == "blocked"
        assert any("[告警]" in msg for msg in res["reasons"])

    def test_isolated_tasks_incremental_tagged(self):
        """Isolated tasks get [当前] tag when staged_items is not None."""
        engine = MergeGateEngine(Path("/dummy/project/root"))
        isolated_tasks = [{"task_id": "TASK-005", "reason": "无关联需求/AC"}]
        res = engine.evaluate([], [], {}, isolated_tasks=isolated_tasks, staged_items={"TASK-005"})
        assert any("[当前]" in msg and "TASK-005" in msg for msg in res["reasons"])


# ---------------------------------------------------------------
# Invalid task references tests (Rule 9)
# ---------------------------------------------------------------

class TestInvalidTaskReferences:
    """Tests for Rule 9: invalid task references."""

    def test_invalid_requirements_blocks(self):
        """Tasks referencing non-existent requirements block the gate."""
        engine = MergeGateEngine(Path("/dummy/project/root"))
        refs = {"invalid_requirements": [{"task_id": "TASK-1", "req_id": "REQ-MISSING"}]}
        res = engine.evaluate([], [], {}, invalid_task_references=refs)
        assert res["gate_decision"] == "blocked"
        assert any("TASK-1" in msg for msg in res["reasons"])

    def test_invalid_modules_blocks(self):
        """Tasks referencing non-existent modules block the gate."""
        engine = MergeGateEngine(Path("/dummy/project/root"))
        refs = {"invalid_modules": [{"task_id": "TASK-1", "module_id": "MOD-MISSING"}]}
        res = engine.evaluate([], [], {}, invalid_task_references=refs)
        assert res["gate_decision"] == "blocked"

    def test_invalid_module_code_paths_blocks(self):
        """Code path module mismatch blocks the gate."""
        engine = MergeGateEngine(Path("/dummy/project/root"))
        refs = {"invalid_module_code_paths": [
            {"task_id": "TASK-1", "module_id": "MOD-A", "code_path": "src/b.py", "actual_module": "MOD-B"}
        ]}
        res = engine.evaluate([], [], {}, invalid_task_references=refs)
        assert res["gate_decision"] == "blocked"
        assert any("链条错位" in msg for msg in res["reasons"])

    def test_empty_invalid_references_passes(self):
        """Empty invalid references produce pass."""
        engine = MergeGateEngine(Path("/dummy/project/root"))
        refs = {
            "invalid_requirements": [],
            "invalid_acs": [],
            "invalid_modules": [],
            "invalid_constraints": [],
            "invalid_ac_parents": [],
            "invalid_module_code_paths": [],
        }
        res = engine.evaluate([], [], {}, invalid_task_references=refs)
        assert res["gate_decision"] == "pass"

    def test_invalid_refs_incremental_filters_historical(self):
        """In incremental mode, historical invalid refs don't block."""
        engine = MergeGateEngine(Path("/dummy/project/root"), incremental_only=True)
        refs = {"invalid_requirements": [{"task_id": "TASK-OLD", "req_id": "REQ-X"}]}
        res = engine.evaluate([], [], {}, invalid_task_references=refs, staged_items={"TASK-NEW"})
        assert res["gate_decision"] == "pass"
        assert res["historical_debt_count"] >= 1


# ---------------------------------------------------------------
# Lint violations tests
# ---------------------------------------------------------------

class TestLintViolations:
    """Tests for lint violations (warning-level, not blocking)."""

    def test_lint_violations_fail_not_blocked(self):
        """Lint violations produce fail, not blocked."""
        engine = MergeGateEngine(Path("/dummy/project/root"))
        lint_violations = [{"source_path": "src/foo.py", "violations_count": 3, "carried_over": False}]
        res = engine.evaluate([], [], {}, lint_violations=lint_violations)
        assert res["gate_decision"] == "fail"
        assert any("src/foo.py" in msg for msg in res["reasons"])

    def test_no_lint_violations_passes(self):
        """Empty lint violations list produces pass."""
        engine = MergeGateEngine(Path("/dummy/project/root"))
        res = engine.evaluate([], [], {}, lint_violations=[])
        assert res["gate_decision"] == "pass"


# ---------------------------------------------------------------
# AC coverage dimension fix test (Stage 8 Fix 3)
# ---------------------------------------------------------------

def test_ac_coverage_incremental_no_claim_for_task_uses_task_id():
    """no_claim_for_task gap uses task_id for incremental check, not ac_id."""
    engine = MergeGateEngine(Path("/dummy/project/root"), incremental_only=True)
    ac_gaps = [{"ac_id": "AC-OLD", "task_id": "TASK-NEW", "coverage_status": "no_claim_for_task"}]
    res = engine.evaluate([], [], {}, ac_gaps=ac_gaps, staged_items={"TASK-NEW"})
    assert res["gate_decision"] == "blocked"
