"""Tests for staleness_tracker pure function."""

from vibe_tracing.domain.gate.staleness import mark_staleness


class _FakeClaim:
    """Minimal claim stub for testing."""
    def __init__(self, claim_id: str, related_task: str, code_refs=None, test_refs=None):
        self.claim_id = claim_id
        self.related_task = related_task
        self.code_refs = code_refs or []
        self.test_refs = test_refs or []


class TestMarkStaleness:
    """Tests for mark_staleness()."""

    def test_no_staged_files_returns_copies(self):
        """When staged_files is None, return copies with no stale markers."""
        gaps = [{"item_id": "REQ-1", "item_type": "requirement"}]
        risks = [{"claim_id": "CLAIM-1", "severity": "high"}]
        new_gaps, new_risks = mark_staleness(gaps, risks, None, [])
        assert new_gaps == gaps
        assert new_risks == risks
        # Verify copies returned (not same objects)
        assert new_gaps is not gaps
        assert new_risks is not risks

    def test_empty_staged_files_returns_copies(self):
        """When staged_files is empty set, return copies with no stale markers."""
        gaps = [{"item_id": "REQ-1", "item_type": "requirement"}]
        risks = []
        new_gaps, new_risks = mark_staleness(gaps, risks, set(), [])
        assert new_gaps == gaps
        assert new_risks == risks

    def test_unrelated_claim_gap_marked_stale(self):
        """Gaps for claims not touching staged files are marked stale."""
        claims = [_FakeClaim("CLAIM-1", "TASK-1", code_refs=["src/foo.py"])]
        gaps = [{"item_id": "CLAIM-2", "item_type": "claim"}]
        risks = []
        staged = {"src/foo.py"}
        new_gaps, new_risks = mark_staleness(gaps, risks, staged, claims)
        assert new_gaps[0].get("stale") is True

    def test_related_claim_gap_not_stale(self):
        """Gaps for claims touching staged files are NOT marked stale."""
        claims = [_FakeClaim("CLAIM-1", "TASK-1", code_refs=["src/foo.py"])]
        gaps = [{"item_id": "CLAIM-1", "item_type": "claim"}]
        risks = []
        staged = {"src/foo.py"}
        new_gaps, new_risks = mark_staleness(gaps, risks, staged, claims)
        assert new_gaps[0].get("stale") is None

    def test_unrelated_requirement_gap_marked_stale(self):
        """Gaps for requirements not linked to staged files are marked stale."""
        claims = [_FakeClaim("CLAIM-1", "TASK-1", code_refs=["src/foo.py"])]
        task_list = [{"task_id": "TASK-1", "related_requirements": ["REQ-1"], "related_acceptance_criteria": []}]
        gaps = [{"item_id": "REQ-2", "item_type": "requirement"}]
        risks = []
        staged = {"src/foo.py"}
        new_gaps, _ = mark_staleness(gaps, risks, staged, claims, task_list)
        assert new_gaps[0].get("stale") is True

    def test_related_requirement_gap_not_stale(self):
        """Gaps for requirements linked to staged files are NOT marked stale."""
        claims = [_FakeClaim("CLAIM-1", "TASK-1", code_refs=["src/foo.py"])]
        task_list = [{"task_id": "TASK-1", "related_requirements": ["REQ-1"], "related_acceptance_criteria": []}]
        gaps = [{"item_id": "REQ-1", "item_type": "requirement"}]
        risks = []
        staged = {"src/foo.py"}
        new_gaps, _ = mark_staleness(gaps, risks, staged, claims, task_list)
        assert new_gaps[0].get("stale") is None

    def test_unrelated_ac_gap_marked_stale(self):
        """Gaps for ACs not linked to staged files are marked stale."""
        claims = [_FakeClaim("CLAIM-1", "TASK-1", code_refs=["src/foo.py"])]
        task_list = [{"task_id": "TASK-1", "related_requirements": [], "related_acceptance_criteria": ["AC-1"]}]
        gaps = [{"item_id": "AC-2", "item_type": "ac"}]
        risks = []
        staged = {"src/foo.py"}
        new_gaps, _ = mark_staleness(gaps, risks, staged, claims, task_list)
        assert new_gaps[0].get("stale") is True

    def test_unrelated_risk_marked_stale(self):
        """Risks for claims not touching staged files are marked stale."""
        claims = [_FakeClaim("CLAIM-1", "TASK-1", code_refs=["src/foo.py"])]
        gaps = []
        risks = [{"claim_id": "CLAIM-2", "severity": "high"}]
        staged = {"src/foo.py"}
        _, new_risks = mark_staleness(gaps, risks, staged, claims)
        assert new_risks[0].get("stale") is True

    def test_related_risk_not_stale(self):
        """Risks for claims touching staged files are NOT marked stale."""
        claims = [_FakeClaim("CLAIM-1", "TASK-1", code_refs=["src/foo.py"])]
        gaps = []
        risks = [{"claim_id": "CLAIM-1", "severity": "high"}]
        staged = {"src/foo.py"}
        _, new_risks = mark_staleness(gaps, risks, staged, claims)
        assert new_risks[0].get("stale") is None

    def test_risk_without_claim_id_not_stale(self):
        """Risks without claim_id are not marked stale."""
        gaps = []
        risks = [{"severity": "high", "description": "some risk"}]
        staged = {"src/foo.py"}
        _, new_risks = mark_staleness(gaps, risks, staged, [])
        assert new_risks[0].get("stale") is None

    def test_does_not_modify_original_lists(self):
        """Original gap and risk lists must not be modified."""
        gaps = [{"item_id": "CLAIM-1", "item_type": "claim"}]
        risks = [{"claim_id": "CLAIM-1"}]
        claims = [_FakeClaim("CLAIM-1", "TASK-1", code_refs=["src/other.py"])]
        staged = {"src/foo.py"}
        mark_staleness(gaps, risks, staged, claims)
        # Originals should not have stale key
        assert "stale" not in gaps[0]
        assert "stale" not in risks[0]

    def test_test_refs_in_staged_files(self):
        """Claims with test_refs matching staged files are affected."""
        claims = [_FakeClaim("CLAIM-1", "TASK-1", test_refs=["tests/test_foo.py::test_bar"])]
        gaps = [{"item_id": "CLAIM-1", "item_type": "claim"}]
        # staged_files contains file paths (without ::test_func suffix)
        staged = {"tests/test_foo.py"}
        new_gaps, _ = mark_staleness(gaps, risks=[], staged_files=staged, claims_list=claims)
        # The path extraction splits on ::, so "tests/test_foo.py" should match
        assert new_gaps[0].get("stale") is None

    def test_multiple_gaps_mixed_staleness(self):
        """Multiple gaps with mixed affected/unaffected status."""
        claims = [_FakeClaim("CLAIM-1", "TASK-1", code_refs=["src/foo.py"])]
        gaps = [
            {"item_id": "CLAIM-1", "item_type": "claim"},
            {"item_id": "CLAIM-2", "item_type": "claim"},
            {"item_id": "REQ-1", "item_type": "requirement"},
        ]
        staged = {"src/foo.py"}
        new_gaps, _ = mark_staleness(gaps, risks=[], staged_files=staged, claims_list=claims)
        assert new_gaps[0].get("stale") is None  # CLAIM-1 affected
        assert new_gaps[1].get("stale") is True   # CLAIM-2 not affected
        assert new_gaps[2].get("stale") is True   # REQ-1 not affected
