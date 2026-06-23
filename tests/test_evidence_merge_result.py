"""Tests for EvidenceMergeResult dataclass."""

from vibe_tracing.domain.evidence.merge_result import EvidenceMergeResult


class TestEvidenceMergeResult:
    """Tests for EvidenceMergeResult."""

    def test_default_initialization(self):
        """Default initialization creates empty lists and stats."""
        result = EvidenceMergeResult()
        assert result.test_results_to_upsert == []
        assert result.coverage_reports_to_upsert == []
        assert result.files_to_purge == []
        assert result.skipped_evidence == []
        assert result.stats["test_count"] == 0
        assert result.stats["coverage_count"] == 0
        assert result.stats["skipped_count"] == 0
        assert result.stats["purge_count"] == 0

    def test_is_empty_true(self):
        """is_empty() returns True when all lists are empty."""
        result = EvidenceMergeResult()
        assert result.is_empty() is True

    def test_is_empty_false_with_test_results(self):
        """is_empty() returns False when test_results has entries."""
        result = EvidenceMergeResult(
            test_results_to_upsert=[{"nodeid": "test_foo"}]
        )
        assert result.is_empty() is False

    def test_is_empty_false_with_coverage(self):
        """is_empty() returns False when coverage_reports has entries."""
        result = EvidenceMergeResult(
            coverage_reports_to_upsert=[{"source_path": "src/foo.py"}]
        )
        assert result.is_empty() is False

    def test_is_empty_false_with_purge(self):
        """is_empty() returns False when files_to_purge has entries."""
        result = EvidenceMergeResult(files_to_purge=["src/old.py"])
        assert result.is_empty() is False

    def test_custom_stats(self):
        """Custom stats can be provided."""
        result = EvidenceMergeResult(
            stats={"test_count": 5, "coverage_count": 2, "skipped_count": 1, "purge_count": 3}
        )
        assert result.stats["test_count"] == 5
        assert result.stats["coverage_count"] == 2
