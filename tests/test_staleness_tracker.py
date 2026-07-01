"""Tests for staleness_tracker pure function."""

from vibe_tracing.domain.gate.staleness import mark_staleness, determine_affected_items


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
        new_gaps, new_risks = mark_staleness(gaps, risks, staged, claims,
                                             affected_claim_ids={"CLAIM-1"})
        assert new_gaps[0].get("stale") is None

    def test_unrelated_requirement_gap_marked_stale(self):
        """Gaps for requirements not linked to staged files are marked stale."""
        claims = [_FakeClaim("CLAIM-1", "TASK-1", code_refs=["src/foo.py"])]
        task_list = [{"task_id": "TASK-1", "related_requirements": ["REQ-1"], "related_acceptance_criteria": []}]
        gaps = [{"item_id": "REQ-2", "item_type": "requirement"}]
        risks = []
        staged = {"src/foo.py"}
        new_gaps, _ = mark_staleness(gaps, risks, staged, claims, task_list,
                                     affected_claim_ids={"CLAIM-1"})
        assert new_gaps[0].get("stale") is True

    def test_related_requirement_gap_not_stale(self):
        """Gaps for requirements linked to staged files are NOT marked stale."""
        claims = [_FakeClaim("CLAIM-1", "TASK-1", code_refs=["src/foo.py"])]
        task_list = [{"task_id": "TASK-1", "related_requirements": ["REQ-1"], "related_acceptance_criteria": []}]
        gaps = [{"item_id": "REQ-1", "item_type": "requirement"}]
        risks = []
        staged = {"src/foo.py"}
        new_gaps, _ = mark_staleness(gaps, risks, staged, claims, task_list,
                                     affected_claim_ids={"CLAIM-1"})
        assert new_gaps[0].get("stale") is None

    def test_unrelated_ac_gap_marked_stale(self):
        """Gaps for ACs not linked to staged files are marked stale."""
        claims = [_FakeClaim("CLAIM-1", "TASK-1", code_refs=["src/foo.py"])]
        task_list = [{"task_id": "TASK-1", "related_requirements": [], "related_acceptance_criteria": ["AC-1"]}]
        gaps = [{"item_id": "AC-2", "item_type": "ac"}]
        risks = []
        staged = {"src/foo.py"}
        new_gaps, _ = mark_staleness(gaps, risks, staged, claims, task_list,
                                     affected_claim_ids={"CLAIM-1"})
        assert new_gaps[0].get("stale") is True

    def test_unrelated_risk_marked_stale(self):
        """Risks for claims not touching staged files are marked stale."""
        claims = [_FakeClaim("CLAIM-1", "TASK-1", code_refs=["src/foo.py"])]
        gaps = []
        risks = [{"claim_id": "CLAIM-2", "severity": "high"}]
        staged = {"src/foo.py"}
        _, new_risks = mark_staleness(gaps, risks, staged, claims,
                                      affected_claim_ids={"CLAIM-1"})
        assert new_risks[0].get("stale") is True

    def test_related_risk_not_stale(self):
        """Risks for claims touching staged files are NOT marked stale."""
        claims = [_FakeClaim("CLAIM-1", "TASK-1", code_refs=["src/foo.py"])]
        gaps = []
        risks = [{"claim_id": "CLAIM-1", "severity": "high"}]
        staged = {"src/foo.py"}
        _, new_risks = mark_staleness(gaps, risks, staged, claims,
                                      affected_claim_ids={"CLAIM-1"})
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
        mark_staleness(gaps, risks, staged, claims,
                       affected_claim_ids=set())
        # Originals should not have stale key
        assert "stale" not in gaps[0]
        assert "stale" not in risks[0]

    def test_test_refs_in_staged_files(self):
        """Claims with test_refs matching staged files are affected."""
        claims = [_FakeClaim("CLAIM-1", "TASK-1", test_refs=["tests/test_foo.py::test_bar"])]
        gaps = [{"item_id": "CLAIM-1", "item_type": "claim"}]
        # staged_files contains file paths (without ::test_func suffix)
        staged = {"tests/test_foo.py"}
        new_gaps, _ = mark_staleness(gaps, risks=[], staged_files=staged, claims_list=claims,
                                     affected_claim_ids={"CLAIM-1"})
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
        new_gaps, _ = mark_staleness(gaps, risks=[], staged_files=staged, claims_list=claims,
                                     affected_claim_ids={"CLAIM-1"})
        assert new_gaps[0].get("stale") is None  # CLAIM-1 affected
        assert new_gaps[1].get("stale") is True   # CLAIM-2 not affected
        assert new_gaps[2].get("stale") is True   # REQ-1 not affected


# ---------------------------------------------------------------------------
# determine_affected_items
# ---------------------------------------------------------------------------


class _FakeTask:
    def __init__(self, task_id, related_requirements=None, related_acceptance_criteria=None):
        self.task_id = task_id
        self.related_requirements = related_requirements or []
        self.related_acceptance_criteria = related_acceptance_criteria or []


class _FakeTaskResult:
    def __init__(self, tasks):
        self.tasks = tasks


class TestDetermineAffectedItems:
    def test_no_affected_claim_ids_returns_empty(self):
        """affected_claim_ids=None 且无 fallback → 全空。"""
        claims = [_FakeClaim("C1", "T1", code_refs=["src/a.py"])]
        affected_c, affected_r, affected_a = determine_affected_items(
            {"src/a.py"}, claims,
        )
        assert affected_c == set()
        assert affected_r == set()
        assert affected_a == set()

    def test_precomputed_claim_ids_used_directly(self):
        """传入 affected_claim_ids 时直接使用，不做内联遍历。"""
        claims = [_FakeClaim("C1", "T1", code_refs=["src/other.py"])]
        affected_c, _, _ = determine_affected_items(
            {"src/a.py"}, claims,
            affected_claim_ids={"C1"},
        )
        assert affected_c == {"C1"}

    def test_task_propagation_with_precomputed_ids(self):
        """affected_claim_ids → task → req/ac 传播链路正确。"""
        claims = [
            _FakeClaim("C1", "T1", code_refs=["src/a.py"]),
            _FakeClaim("C2", "T2", code_refs=["src/b.py"]),
        ]
        task_result = _FakeTaskResult([
            _FakeTask("T1", related_requirements=["REQ-1"], related_acceptance_criteria=["AC-1-1"]),
            _FakeTask("T2", related_requirements=["REQ-2"], related_acceptance_criteria=["AC-2-1"]),
        ])
        affected_c, affected_r, affected_a = determine_affected_items(
            {"src/a.py"}, claims, task_result,
            affected_claim_ids={"C1"},
        )
        assert affected_c == {"C1"}
        assert affected_r == {"REQ-1"}
        assert affected_a == {"AC-1-1"}

    def test_unaffected_task_not_propagated(self):
        """未受影响的 claim 对应的 task/req/ac 不进入 affected 集合。"""
        claims = [
            _FakeClaim("C1", "T1", code_refs=["src/a.py"]),
            _FakeClaim("C2", "T2", code_refs=["src/b.py"]),
        ]
        task_result = _FakeTaskResult([
            _FakeTask("T1", related_requirements=["REQ-1"], related_acceptance_criteria=["AC-1-1"]),
            _FakeTask("T2", related_requirements=["REQ-2"], related_acceptance_criteria=["AC-2-1"]),
        ])
        affected_c, affected_r, affected_a = determine_affected_items(
            {"src/a.py"}, claims, task_result,
            affected_claim_ids={"C1"},
        )
        assert "REQ-2" not in affected_r
        assert "AC-2-1" not in affected_a

    def test_no_task_result_skips_propagation(self):
        """task_result=None 时仅返回 affected_claims，req/ac 为空。"""
        claims = [_FakeClaim("C1", "T1", code_refs=["src/a.py"])]
        affected_c, affected_r, affected_a = determine_affected_items(
            {"src/a.py"}, claims, None,
            affected_claim_ids={"C1"},
        )
        assert affected_c == {"C1"}
        assert affected_r == set()
        assert affected_a == set()
