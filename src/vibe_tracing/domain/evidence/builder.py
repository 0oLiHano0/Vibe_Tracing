"""
Evidence Builder for Vibe Tracing.

Builds evidence by merging tool results (tests, coverage) and persisting
to SQLite and split JSON files (test_results.json, coverage_reports.json).

Refactored into three phases:
  - merge():  Pure data processing, no DB dependency
  - apply():  Purge + upsert routing into SQLite
  - persist(): Export JSON files (no DB dependency)
"""

import json
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

from vibe_tracing.domain.evidence.merge_result import EvidenceMergeResult
from vibe_tracing.domain.evidence.candidate import ToolEvidenceCandidate


class EvidenceBuilder:
    """Builds evidence by merging tool results and persisting to SQLite/JSON."""

    def __init__(self, project_root: Path) -> None:
        """Initialize the Evidence Builder with the project root.

        Note: No conn parameter. Connection is passed to apply() only.
        """
        self.project_root = project_root

    def merge(self, tool_evidence: List[ToolEvidenceCandidate]) -> EvidenceMergeResult:
        """Merge tool evidence into structured upsert/purge operations.

        This is a pure data processing step with no DB dependency.
        Returns an EvidenceMergeResult that can be passed to apply().
        """
        test_results: List[Dict[str, Any]] = []
        coverage_reports: List[Dict[str, Any]] = []
        lint_results: List[Dict[str, Any]] = []
        files_to_purge: List[str] = []
        skipped: List[Dict[str, Any]] = []

        for ev in (tool_evidence or []):
            if ev.source_type == "test":
                # Extract bare file path from pytest nodeid
                file_path = ev.source_path.split("::")[0]
                if file_path:
                    files_to_purge.append(file_path)
                test_results.append({
                    "nodeid": ev.source_path,
                    "outcome": ev.status,
                    "exit_code": ev.exit_code,
                    "command": ev.command,
                    "carried_over": False,
                })
            elif ev.source_type == "coverage" or (ev.source_type == "tool" and ev.tool_category == "coverage"):
                coverage_reports.append({
                    "source_path": ev.source_path,
                    "percent_covered": ev.details.get("percent_covered", 0),
                    "num_statements": ev.details.get("num_statements", 0),
                    "status": ev.status,
                    "carried_over": False,
                })
            elif ev.tool_category == "lint":
                cnt = ev.details.get("violations_count", 0) or ev.details.get("results_count", 0)
                lint_results.append({
                    "source_path": ev.source_path,
                    "outcome": ev.status,
                    "violations_count": int(cnt),
                    "command": ev.command,
                    "carried_over": False,
                })
            else:
                skipped.append({
                    "source_path": ev.source_path,
                    "source_type": ev.source_type,
                    "reason": f"Unknown source_type: {ev.source_type}",
                })

        return EvidenceMergeResult(
            test_results_to_upsert=test_results,
            coverage_reports_to_upsert=coverage_reports,
            lint_results_to_upsert=lint_results,
            files_to_purge=list(set(files_to_purge)),  # deduplicate
            skipped_evidence=skipped,
            stats={
                "test_count": len(test_results),
                "coverage_count": len(coverage_reports),
                "lint_count": len(lint_results),
                "skipped_count": len(skipped),
                "purge_count": len(set(files_to_purge)),
            },
        )

    def apply(self, conn: Any, merge_result: EvidenceMergeResult,
              evidences_dir: "Path") -> None:
        """Apply merge result to SQLite: purge stale cache + upsert new data.

        Args:
            conn: SQLite connection.
            merge_result: Result from merge().
            evidences_dir: Directory path for split JSON evidence files.
        """
        from vibe_tracing.infra.db import (
            load_initial_cache,
            upsert_test_result,
            upsert_coverage_report,
            upsert_lint_result,
            purge_stale_cache,
        )

        # Load historical cache
        load_initial_cache(conn, evidences_dir, self.project_root)

        # Purge stale cache for files being updated
        if merge_result.files_to_purge:
            purge_stale_cache(conn, merge_result.files_to_purge)

        # Upsert test results
        for entry in merge_result.test_results_to_upsert:
            upsert_test_result(
                conn,
                nodeid=entry["nodeid"],
                outcome=entry["outcome"],
                exit_code=entry["exit_code"],
                command=entry["command"],
                carried_over=entry["carried_over"],
            )

        # Upsert coverage reports
        for entry in merge_result.coverage_reports_to_upsert:
            upsert_coverage_report(
                conn,
                source_path=entry["source_path"],
                percent_covered=entry["percent_covered"],
                num_statements=entry["num_statements"],
                status=entry["status"],
                carried_over=entry["carried_over"],
            )

        # Upsert lint results
        for entry in merge_result.lint_results_to_upsert:
            upsert_lint_result(
                conn,
                source_path=entry["source_path"],
                outcome=entry["outcome"],
                violations_count=entry["violations_count"],
                command=entry["command"],
                carried_over=entry["carried_over"],
            )

    def persist(self, output_dir: Path, merge_result: EvidenceMergeResult) -> Dict[str, str]:
        """Export evidence JSON files directly from merge result.

        Does NOT depend on SQLite connection. Writes split JSON files
        (test_results.json, coverage_reports.json) from in-memory data.

        Args:
            output_dir: Directory to write JSON files.
            merge_result: Result from merge().

        Returns:
            Dict with paths to exported files.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Write test_results.json
        test_file = output_dir / "test_results.json"
        with open(str(test_file), "w", encoding="utf-8") as fh:
            json.dump(merge_result.test_results_to_upsert, fh, indent=2, ensure_ascii=False)

        # Write coverage_reports.json
        cov_file = output_dir / "coverage_reports.json"
        with open(str(cov_file), "w", encoding="utf-8") as fh:
            json.dump(merge_result.coverage_reports_to_upsert, fh, indent=2, ensure_ascii=False)

        # Write lint_results.json
        lint_file = output_dir / "lint_results.json"
        with open(str(lint_file), "w", encoding="utf-8") as fh:
            json.dump(merge_result.lint_results_to_upsert, fh, indent=2, ensure_ascii=False)

        return {
            "evidences_dir": str(output_dir),
            "test_results_file": str(test_file),
            "coverage_reports_file": str(cov_file),
            "lint_results_file": str(lint_file),
        }

    def build_evidence_meta(self, conn: Any, config_prefix: str) -> Dict[str, Any]:
        """Build evidence metadata for reports.

        Encapsulates domain knowledge: run/project ID formats, scan timestamp,
        and full-chain traceability query. Keeps orchestration layer free of
        format decisions.

        Args:
            conn: SQLite connection.
            config_prefix: Project config prefix (e.g. "myproject").

        Returns:
            Dict with run_id, project_id, scan_time, full_chain.
        """
        from vibe_tracing.infra.db.queries import get_full_chain

        full_chain = get_full_chain(conn)
        BEIJING = timezone(timedelta(hours=8))
        return {
            "run_id": f"RUN-{uuid.uuid4()}",
            "project_id": f"PROJECT-{config_prefix}",
            "scan_time": datetime.now(BEIJING).isoformat(),
            "full_chain": full_chain,
        }
