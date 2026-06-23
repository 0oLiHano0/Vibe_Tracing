"""Evidence merge result data model.

Holds the outcome of EvidenceBuilder.merge() so that apply() and persist()
can operate on a well-defined structure rather than ad-hoc dicts.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EvidenceMergeResult:
    """Result container from EvidenceBuilder.merge().

    Attributes:
        test_results_to_upsert: Test result entries to insert/update in DB.
        coverage_reports_to_upsert: Coverage report entries to insert/update in DB.
        files_to_purge: File paths whose stale cache should be purged.
        skipped_evidence: Evidence entries that were skipped (e.g., unknown source_type).
        stats: Summary statistics for logging/reporting.
    """

    test_results_to_upsert: List[Dict[str, Any]] = field(default_factory=list)
    coverage_reports_to_upsert: List[Dict[str, Any]] = field(default_factory=list)
    files_to_purge: List[str] = field(default_factory=list)
    skipped_evidence: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=lambda: {
        "test_count": 0,
        "coverage_count": 0,
        "skipped_count": 0,
        "purge_count": 0,
    })

    def is_empty(self) -> bool:
        """Check if there's nothing to apply."""
        return (
            len(self.test_results_to_upsert) == 0
            and len(self.coverage_reports_to_upsert) == 0
            and len(self.files_to_purge) == 0
        )
