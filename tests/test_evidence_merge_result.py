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

    def test_custom_stats(self):
        """Custom stats can be provided."""
        result = EvidenceMergeResult(
            stats={"test_count": 5, "coverage_count": 2, "skipped_count": 1, "purge_count": 3}
        )
        assert result.stats["test_count"] == 5
        assert result.stats["coverage_count"] == 2
