"""
Unit tests for MergeGateEngine.detect_all_issues (VT-182).

Engine is a pure issue detector — no gate decisions, no signals.
Tests verify issue_type, severity, and key fields of DetectedIssue.
"""

from pathlib import Path

from vibe_tracing.domain.gate.engine import MergeGateEngine
from vibe_tracing.domain.gate.types import Severity


def _engine(tmp_path=None):
    return MergeGateEngine(tmp_path or Path("/dummy/project/root"))


def _find_issues(issues, issue_type=None, severity=None):
    result = issues
    if issue_type:
        result = [i for i in result if i.issue_type == issue_type]
    if severity:
        result = [i for i in result if i.severity == severity]
    return result


# ── Rule 2: Ghost code (no_claim / BLOCK) ─────────────────────────

class TestClaimExistence:
    def test_ghost_files_produce_issues(self, tmp_path):
        engine = _engine(tmp_path)
        issues = engine.detect_all_issues(ghost_files=["src/foo.py", "src/bar.py"])
        assert len(issues) == 2
        assert all(i.issue_type == "no_claim" for i in issues)
        assert all(i.severity == Severity.BLOCK for i in issues)

    def test_empty_ghost_files(self, tmp_path):
        issues = _engine(tmp_path).detect_all_issues(ghost_files=[])
        assert len(issues) == 0

    def test_none_ghost_files_skipped(self, tmp_path):
        issues = _engine(tmp_path).detect_all_issues(ghost_files=None)
        assert len(issues) == 0

    def test_ghost_file_in_issue_id(self, tmp_path):
        issues = _engine(tmp_path).detect_all_issues(ghost_files=["src/foo.py"])
        assert issues[0].issue_id == "no_claim:src/foo.py"

    def test_ghost_code_exclusions(self, tmp_path):
        import json
        config_dir = tmp_path / ".vibetracing"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text(
            json.dumps({"ghost_code_exclusions": ["generated/"]})
        )
        engine = _engine(tmp_path)
        issues = engine.detect_all_issues(ghost_files=["generated/auto.py", "src/manual.py"])
        assert len(issues) == 1
        assert issues[0].item_id == "src/manual.py"


# ── Rule 3: Dangling claims (chain_broken / BLOCK) ───────────────

class TestDanglingClaims:
    def test_dangling_claims_blocks(self, tmp_path):
        engine = _engine(tmp_path)
        dangling = [{"claim_id": "CLAIM-1", "related_task": "TASK-MISSING"}]
        issues = engine.detect_all_issues(dangling_claims=dangling)
        assert len(issues) == 1
        assert issues[0].issue_type == "chain_broken"
        assert issues[0].severity == Severity.BLOCK

    def test_no_dangling_claims(self, tmp_path):
        issues = _engine(tmp_path).detect_all_issues(dangling_claims=[])
        assert len(issues) == 0

    def test_dangling_claims_none_skipped(self, tmp_path):
        issues = _engine(tmp_path).detect_all_issues(dangling_claims=None)
        assert len(issues) == 0

    def test_dangling_claim_related_task(self, tmp_path):
        engine = _engine(tmp_path)
        dangling = [{"claim_id": "CLAIM-1", "related_task": "TASK-MISSING"}]
        issues = engine.detect_all_issues(dangling_claims=dangling)
        assert issues[0].related_task_id == "TASK-MISSING"


# ── Rule 4: Claim evidence gaps (mixed severity) ─────────────────

class TestClaimEvidenceGaps:
    def test_test_failed_blocks(self, tmp_path):
        engine = _engine(tmp_path)
        ceg = [{"claim_id": "CLAIM-1", "verification_status": "test_failed"}]
        issues = engine.detect_all_issues(claim_evidence_gaps=ceg)
        assert len(issues) == 1
        assert issues[0].issue_type == "task_failed"
        assert issues[0].severity == Severity.BLOCK

    def test_no_tests_warning(self, tmp_path):
        engine = _engine(tmp_path)
        ceg = [{"claim_id": "CLAIM-1", "verification_status": "no_tests"}]
        issues = engine.detect_all_issues(claim_evidence_gaps=ceg)
        assert len(issues) == 1
        assert issues[0].severity == Severity.WARNING

    def test_empty_claim_evidence_gaps(self, tmp_path):
        issues = _engine(tmp_path).detect_all_issues(claim_evidence_gaps=[])
        assert len(issues) == 0


# ── Rule 5: AC coverage (no_claim / BLOCK) ───────────────────────

class TestAcCoverage:
    def test_ac_gaps_blocks(self, tmp_path):
        engine = _engine(tmp_path)
        ac_gaps = [{"ac_id": "AC-001", "task_id": "TASK-001", "coverage_status": "no_tests_declared"}]
        issues = engine.detect_all_issues(ac_gaps=ac_gaps)
        assert len(issues) == 1
        assert issues[0].issue_type == "no_claim"
        assert issues[0].severity == Severity.BLOCK

    def test_no_ac_gaps(self, tmp_path):
        issues = _engine(tmp_path).detect_all_issues(ac_gaps=[])
        assert len(issues) == 0

    def test_ac_gaps_none_skipped(self, tmp_path):
        issues = _engine(tmp_path).detect_all_issues(ac_gaps=None)
        assert len(issues) == 0

    def test_no_claim_for_task_uses_task_id(self, tmp_path):
        engine = _engine(tmp_path)
        ac_gaps = [{"ac_id": "AC-001", "task_id": "TASK-001", "coverage_status": "no_claim_for_task"}]
        issues = engine.detect_all_issues(ac_gaps=ac_gaps)
        assert issues[0].related_task_id == "TASK-001"
        assert issues[0].gap_targets == ["TASK-001"]


# ── Rule 9: Invalid task references ──────────────────────────────

class TestInvalidTaskReferences:
    def test_invalid_requirements_blocks(self, tmp_path):
        engine = _engine(tmp_path)
        refs = {"invalid_requirements": [{"task_id": "TASK-1", "req_id": "REQ-MISSING"}]}
        issues = engine.detect_all_issues(invalid_task_references=refs)
        assert len(issues) == 1
        assert issues[0].issue_type == "chain_broken"
        assert issues[0].severity == Severity.BLOCK
        assert issues[0].related_task_id == "TASK-1"

    def test_invalid_modules_blocks(self, tmp_path):
        engine = _engine(tmp_path)
        refs = {"invalid_modules": [{"task_id": "TASK-1", "module_id": "MOD-MISSING"}]}
        issues = engine.detect_all_issues(invalid_task_references=refs)
        assert len(issues) == 1
        assert issues[0].issue_type == "chain_broken"

    def test_invalid_module_code_paths_misaligned(self, tmp_path):
        engine = _engine(tmp_path)
        refs = {"invalid_module_code_paths": [
            {"task_id": "TASK-1", "module_id": "MOD-A", "code_path": "src/b.py", "actual_module": "MOD-B"}
        ]}
        issues = engine.detect_all_issues(invalid_task_references=refs)
        assert len(issues) == 1
        assert issues[0].issue_type == "chain_misaligned"

    def test_empty_invalid_references(self, tmp_path):
        engine = _engine(tmp_path)
        refs = {
            "invalid_requirements": [],
            "invalid_acs": [],
            "invalid_modules": [],
            "invalid_constraints": [],
            "invalid_ac_parents": [],
            "invalid_module_code_paths": [],
        }
        issues = engine.detect_all_issues(invalid_task_references=refs)
        assert len(issues) == 0

    def test_invalid_acs(self, tmp_path):
        engine = _engine(tmp_path)
        refs = {"invalid_acs": [{"task_id": "TASK-1", "ac_id": "AC-MISSING"}]}
        issues = engine.detect_all_issues(invalid_task_references=refs)
        assert len(issues) == 1
        assert issues[0].gap_targets == ["AC-MISSING"]

    def test_invalid_constraints(self, tmp_path):
        engine = _engine(tmp_path)
        refs = {"invalid_constraints": [{"task_id": "TASK-1", "constraint_id": "CON-001"}]}
        issues = engine.detect_all_issues(invalid_task_references=refs)
        assert len(issues) == 1

    def test_invalid_ac_parents(self, tmp_path):
        engine = _engine(tmp_path)
        refs = {"invalid_ac_parents": [{"task_id": "TASK-1", "ac_id": "AC-001", "parent_req_id": "REQ-X"}]}
        issues = engine.detect_all_issues(invalid_task_references=refs)
        assert len(issues) == 1
        assert issues[0].issue_type == "chain_misaligned"


# ── Architecture compliance: must gaps (task_failed / BLOCK) ─────

class TestMustGaps:
    def test_must_ac_gap_blocks(self, tmp_path):
        engine = _engine(tmp_path)
        gaps = [{"item_id": "AC-001", "item_type": "ac", "reason": "missing test"}]
        issues = engine.detect_all_issues(gaps=gaps)
        block_issues = _find_issues(issues, severity=Severity.BLOCK)
        assert len(block_issues) >= 1
        assert block_issues[0].issue_type == "task_failed"

    def test_non_ac_gap_skipped_in_must(self, tmp_path):
        engine = _engine(tmp_path)
        gaps = [{"item_id": "REQ-001", "item_type": "requirement", "reason": "no coverage"}]
        issues = engine.detect_all_issues(gaps=gaps)
        must_issues = _find_issues(issues, issue_type="task_failed")
        assert len(must_issues) == 0

    def test_stale_gap_skipped(self, tmp_path):
        engine = _engine(tmp_path)
        gaps = [{"item_id": "AC-001", "item_type": "ac", "reason": "old", "stale": True}]
        issues = engine.detect_all_issues(gaps=gaps)
        must_issues = _find_issues(issues, issue_type="task_failed")
        assert len(must_issues) == 0


# ── Architecture compliance: must risks (chain_broken / BLOCK) ───

class TestMustRisks:
    def test_must_risk_blocks(self, tmp_path):
        engine = _engine(tmp_path)
        risks = [{"risk_id": "RISK-001", "severity": "must", "description": "critical bug"}]
        issues = engine.detect_all_issues(risks=risks)
        block_issues = _find_issues(issues, severity=Severity.BLOCK)
        assert len(block_issues) >= 1

    def test_self_referential_risk_blocks(self, tmp_path):
        engine = _engine(tmp_path)
        risks = [{"risk_id": "RISK-001", "severity": "should", "description": "self-referential claim detected"}]
        issues = engine.detect_all_issues(risks=risks)
        block_issues = _find_issues(issues, severity=Severity.BLOCK)
        assert len(block_issues) >= 1

    def test_high_risk_missing_action(self, tmp_path):
        engine = _engine(tmp_path)
        risks = [{
            "risk_id": "RISK-001", "severity": "must",
            "description": "critical", "suggested_action": "", "business_impact": "high"
        }]
        issues = engine.detect_all_issues(risks=risks)
        assert len(issues) >= 2

    def test_low_risk_not_in_must(self, tmp_path):
        engine = _engine(tmp_path)
        risks = [{"risk_id": "RISK-001", "severity": "should", "description": "minor"}]
        issues = engine.detect_all_issues(risks=risks)
        must_issues = _find_issues(issues, issue_type="chain_broken")
        assert len(must_issues) == 0


# ── Architecture compliance: violations ──────────────────────────

class TestArchitectureViolations:
    def test_violation_blocks(self, tmp_path):
        engine = _engine(tmp_path)
        compliance = {
            "architecture_violations": [{"rule_id": "FORBID-001", "message": "Self-attestation."}],
            "architecture_compliance_status": [],
            "unclear_constraints": [],
        }
        issues = engine.detect_all_issues(compliance_res=compliance)
        block_issues = _find_issues(issues, severity=Severity.BLOCK)
        assert len(block_issues) >= 1
        assert any("FORBID-001" in i.issue_id for i in block_issues)

    def test_violated_must_status_blocks(self, tmp_path):
        engine = _engine(tmp_path)
        compliance = {
            "architecture_violations": [],
            "architecture_compliance_status": [
                {"rule_id": "ARCH-001", "status": "violated", "severity": "must"}
            ],
            "unclear_constraints": [],
        }
        issues = engine.detect_all_issues(compliance_res=compliance)
        block_issues = _find_issues(issues, severity=Severity.BLOCK)
        assert len(block_issues) >= 1


# ── Architecture compliance: proposal governance ─────────────────

class TestProposalGovernance:
    def test_proposal_risk_blocks(self, tmp_path):
        engine = _engine(tmp_path)
        compliance = {
            "architecture_violations": [],
            "architecture_compliance_status": [],
            "unclear_constraints": [],
            "proposal_risks": [{"risk_id": "PROP-R1", "description": "Breaking change"}],
            "proposal_gaps": [],
        }
        issues = engine.detect_all_issues(compliance_res=compliance)
        block_issues = _find_issues(issues, severity=Severity.BLOCK)
        assert len(block_issues) >= 1

    def test_proposal_gap_blocks(self, tmp_path):
        engine = _engine(tmp_path)
        compliance = {
            "architecture_violations": [],
            "architecture_compliance_status": [],
            "unclear_constraints": [],
            "proposal_risks": [],
            "proposal_gaps": [{"item_id": "PROP-G1", "reason": "Missing migration"}],
        }
        issues = engine.detect_all_issues(compliance_res=compliance)
        block_issues = _find_issues(issues, severity=Severity.BLOCK)
        assert len(block_issues) >= 1


# ── Should gaps (substandard / WARNING) ──────────────────────────

class TestShouldGaps:
    def test_should_gap_warning(self, tmp_path):
        engine = _engine(tmp_path)
        gaps = [{"item_id": "REQ-003", "item_type": "requirement", "reason": "no task coverage"}]
        issues = engine.detect_all_issues(gaps=gaps)
        warnings = _find_issues(issues, issue_type="substandard")
        assert len(warnings) >= 1
        assert warnings[0].severity == Severity.WARNING

    def test_ac_gap_not_in_should(self, tmp_path):
        """AC-type gaps are handled by _check_must_gaps, not _check_should_gaps."""
        engine = _engine(tmp_path)
        gaps = [{"item_id": "AC-001", "item_type": "ac", "reason": "test"}]
        issues = engine.detect_all_issues(gaps=gaps)
        should_issues = _find_issues(issues, issue_type="substandard")
        assert len(should_issues) == 0


# ── Should risks (substandard / WARNING) ─────────────────────────

class TestShouldRisks:
    def test_should_risk_warning(self, tmp_path):
        engine = _engine(tmp_path)
        risks = [{"risk_id": "RISK-003", "severity": "should", "description": "Low priority"}]
        issues = engine.detect_all_issues(risks=risks)
        warnings = _find_issues(issues, severity=Severity.WARNING)
        assert len(warnings) >= 1

    def test_low_confidence_risk_warning(self, tmp_path):
        engine = _engine(tmp_path)
        risks = [{"risk_id": "RISK-004", "severity": "must", "confidence": "low_confidence", "description": "maybe"}]
        issues = engine.detect_all_issues(risks=risks)
        warnings = _find_issues(issues, issue_type="substandard")
        assert len(warnings) >= 1


# ── Unclear constraints (substandard / WARNING) ──────────────────

class TestUnclearConstraints:
    def test_unclear_constraint_warning(self, tmp_path):
        engine = _engine(tmp_path)
        compliance = {
            "architecture_violations": [],
            "architecture_compliance_status": [],
            "unclear_constraints": [{"rule_id": "UNCLEAR-001", "reason": "Cannot verify"}],
        }
        issues = engine.detect_all_issues(compliance_res=compliance)
        warnings = _find_issues(issues, severity=Severity.WARNING)
        assert any("UNCLEAR-001" in i.issue_id for i in warnings)

    def test_unclear_status_in_compliance(self, tmp_path):
        engine = _engine(tmp_path)
        compliance = {
            "architecture_violations": [],
            "architecture_compliance_status": [
                {"rule_id": "RULE-001", "status": "unclear"}
            ],
            "unclear_constraints": [],
        }
        issues = engine.detect_all_issues(compliance_res=compliance)
        warnings = _find_issues(issues, severity=Severity.WARNING)
        assert len(warnings) >= 1


# ── Coverage violations (substandard / WARNING) ──────────────────

class TestCoverageViolations:
    def test_coverage_violation_warning(self, tmp_path):
        engine = _engine(tmp_path)
        cov = [{"source_path": "src/foo.py", "percent_covered": 45.0}]
        issues = engine.detect_all_issues(cov_violations=cov)
        assert len(issues) == 1
        assert issues[0].issue_type == "substandard"
        assert issues[0].severity == Severity.WARNING

    def test_empty_coverage_violations(self, tmp_path):
        issues = _engine(tmp_path).detect_all_issues(cov_violations=[])
        assert len(issues) == 0


# ── Lint violations (substandard / WARNING) ──────────────────────

class TestLintViolations:
    def test_lint_violation_warning(self, tmp_path):
        engine = _engine(tmp_path)
        lint = [{"source_path": "src/foo.py", "violations_count": 3}]
        issues = engine.detect_all_issues(lint_violations=lint)
        assert len(issues) == 1
        assert issues[0].issue_type == "substandard"
        assert issues[0].severity == Severity.WARNING

    def test_empty_lint_violations(self, tmp_path):
        issues = _engine(tmp_path).detect_all_issues(lint_violations=[])
        assert len(issues) == 0


# ── Isolated tasks (isolated_task / WARNING) ─────────────────────

class TestIsolatedTasks:
    def test_isolated_task_warning(self, tmp_path):
        engine = _engine(tmp_path)
        isolated = [{"task_id": "TASK-005", "reason": "no req/AC"}]
        issues = engine.detect_all_issues(isolated_tasks=isolated)
        assert len(issues) == 1
        assert issues[0].issue_type == "isolated_task"
        assert issues[0].severity == Severity.WARNING
        assert issues[0].related_task_id == "TASK-005"

    def test_empty_isolated_tasks(self, tmp_path):
        issues = _engine(tmp_path).detect_all_issues(isolated_tasks=[])
        assert len(issues) == 0

    def test_isolated_tasks_none_skipped(self, tmp_path):
        issues = _engine(tmp_path).detect_all_issues(isolated_tasks=None)
        assert len(issues) == 0


# ── Combined detection ───────────────────────────────────────────

class TestCombinedDetection:
    def test_multiple_sources_combined(self, tmp_path):
        engine = _engine(tmp_path)
        issues = engine.detect_all_issues(
            ghost_files=["src/orphan.py"],
            ac_gaps=[{"ac_id": "AC-001", "task_id": "TASK-001", "coverage_status": "no_tests"}],
            isolated_tasks=[{"task_id": "TASK-005", "reason": "no req"}],
        )
        types = {i.issue_type for i in issues}
        assert "no_claim" in types
        assert "isolated_task" in types
        assert len(issues) == 3

    def test_no_inputs_produces_empty(self, tmp_path):
        issues = _engine(tmp_path).detect_all_issues()
        assert len(issues) == 0
