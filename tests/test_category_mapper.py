"""5 分类验收链条映射测试。"""

import pytest

from vibe_tracing.domain.governance.category_mapper import (
    CATEGORIES,
    CATEGORY_CHAIN_INTEGRITY,
    CATEGORY_DELIVERY_PROOF,
    CATEGORY_DELIVERY_QUALITY,
    CATEGORY_EVIDENCE_VERIFICATION,
    CATEGORY_PROCESS_COMPLIANCE,
    categorize,
)


class TestCategoryDefinitions:
    def test_five_categories(self):
        assert len(CATEGORIES) == 5

    def test_category_ids_unique(self):
        ids = [c["id"] for c in CATEGORIES]
        assert len(ids) == len(set(ids))

    def test_all_categories_have_gate(self):
        for c in CATEGORIES:
            assert c["gate"] in ("BLOCK", "WARNING")


class TestCategorizeMapping:
    def test_no_claim_to_delivery_proof(self):
        assert categorize("no_claim") == CATEGORY_DELIVERY_PROOF

    def test_task_failed_to_evidence_verification(self):
        assert categorize("task_failed") == CATEGORY_EVIDENCE_VERIFICATION
        assert categorize("task_failed:test_failed") == CATEGORY_EVIDENCE_VERIFICATION
        assert categorize("task_failed:CLAIM-VT-001") == CATEGORY_EVIDENCE_VERIFICATION

    def test_isolated_task_to_chain_integrity(self):
        assert categorize("isolated_task") == CATEGORY_CHAIN_INTEGRITY

    def test_chain_misaligned_to_chain_integrity(self):
        assert categorize("chain_misaligned") == CATEGORY_CHAIN_INTEGRITY
        assert categorize("chain_misaligned:TASK-VT-192:AC-001") == CATEGORY_CHAIN_INTEGRITY

    def test_chain_broken_plain_to_chain_integrity(self):
        assert categorize("chain_broken") == CATEGORY_CHAIN_INTEGRITY
        assert categorize("chain_broken:TASK-VT-192:REQ-003") == CATEGORY_CHAIN_INTEGRITY
        assert categorize("chain_broken:CLAIM-VT-001") == CATEGORY_CHAIN_INTEGRITY

    def test_chain_broken_gate_vt_to_delivery_quality(self):
        assert categorize("chain_broken:GATE-VT-006") == CATEGORY_DELIVERY_QUALITY
        assert categorize("chain_broken:GATE-VT-001") == CATEGORY_DELIVERY_QUALITY

    def test_chain_broken_proposal_to_process_compliance(self):
        assert categorize("chain_broken:proposal:RISK-001") == CATEGORY_PROCESS_COMPLIANCE
        assert categorize("chain_broken:proposal_gap:GAP-001") == CATEGORY_PROCESS_COMPLIANCE

    def test_chain_broken_risk_vt_to_process_compliance(self):
        assert categorize("chain_broken:RISK-VT-001") == CATEGORY_PROCESS_COMPLIANCE
        assert categorize("chain_broken:RISK-VT-272:missing_action") == CATEGORY_PROCESS_COMPLIANCE

    def test_substandard_unclear_to_process_compliance(self):
        assert categorize("substandard:unclear:GATE-VT-007") == CATEGORY_PROCESS_COMPLIANCE
        assert categorize("substandard:unclear_status:GATE-VT-011") == CATEGORY_PROCESS_COMPLIANCE

    def test_substandard_other_to_delivery_quality(self):
        assert categorize("substandard:coverage:src/foo.py") == CATEGORY_DELIVERY_QUALITY
        assert categorize("substandard:lint:src/bar.py") == CATEGORY_DELIVERY_QUALITY
        assert categorize("substandard:some_item") == CATEGORY_DELIVERY_QUALITY

    def test_unknown_type_defaults_to_chain_integrity(self):
        assert categorize("unknown_type") == CATEGORY_CHAIN_INTEGRITY


class TestCategorizeAllIssueTypesCovered:
    """验证 engine 产出的所有 issue_type 都有明确分类。"""

    @pytest.mark.parametrize("key", [
        "no_claim",
        "chain_broken",
        "chain_misaligned",
        "task_failed",
        "isolated_task",
        "substandard",
        "chain_broken:GATE-VT-006",
        "chain_broken:proposal:r1",
        "chain_broken:proposal_gap:g1",
        "chain_broken:RISK-VT-001",
        "substandard:coverage:src/a.py",
        "substandard:lint:src/b.py",
        "substandard:unclear:GATE-VT-007",
        "substandard:unclear_status:GATE-VT-011",
    ])
    def test_known_keys_map_to_valid_category(self, key):
        result = categorize(key)
        valid = {c["id"] for c in CATEGORIES}
        assert result in valid
