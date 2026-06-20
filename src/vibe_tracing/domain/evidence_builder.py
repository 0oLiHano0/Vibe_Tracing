"""
Evidence Builder for Vibe Tracing.

Builds evidence by upserting tool results (tests, coverage) into SQLite
and exporting split JSON files (test_results.json, coverage_reports.json).
"""

import sqlite3
from pathlib import Path
from typing import Any


class EvidenceBuilder:
    """Builds evidence by upserting tool results into SQLite and exporting split JSON."""

    def __init__(self, project_root: Path, conn: sqlite3.Connection) -> None:
        """Initialize the Evidence Builder with the project root and a DB connection."""
        self.project_root = project_root
        self.conn = conn

    def build(self, ctx: Any) -> dict:
        """Build evidence by upserting tool results into SQLite and exporting split JSON.

        Prerequisite: data has been validated by validation/checks.py format checks.
        """
        from vibe_tracing.infra.db import (
            load_initial_cache, upsert_test_result, upsert_coverage_report,
            purge_stale_cache, persist_evidences,
        )

        # 1. Load historical cache
        evidences_dir = self.project_root / "output" / "evidences"
        load_initial_cache(self.conn, evidences_dir)

        # 2. Collect files touched in this run (for purging stale cache)
        target_files = set()
        for ev in (ctx.tool_evidence or []):
            # Extract bare file path from pytest nodeid (e.g., "tests/test_x.py::test_foo" -> "tests/test_x.py")
            file_path = ev.source_path.split("::")[0]
            if file_path:
                target_files.add(file_path)
        if target_files:
            purge_stale_cache(self.conn, list(target_files))

        # 3. Upsert tool execution results into the database
        for ev in (ctx.tool_evidence or []):
            if ev.source_type == "test":
                upsert_test_result(
                    self.conn,
                    nodeid=ev.source_path,
                    outcome=getattr(ev, 'status', 'unknown'),
                    exit_code=getattr(ev, 'exit_code', 0),
                    command=getattr(ev, 'command', ''),
                    carried_over=False,
                )
            elif ev.source_type == "coverage" or (
                ev.source_type == "tool"
                and getattr(ev, 'tool_category', '') == "coverage"
            ):
                details = getattr(ev, 'details', {}) or {}
                upsert_coverage_report(
                    self.conn,
                    source_path=ev.source_path,
                    percent_covered=details.get('percent_covered', 0),
                    num_statements=details.get('num_statements', 0),
                    status=getattr(ev, 'status', 'violated'),
                    carried_over=False,
                )

        # 4. Export split JSON
        persist_evidences(self.conn, evidences_dir)

        # 5. Return summary
        return {
            "evidences_dir": str(evidences_dir),
            "test_results_file": str(evidences_dir / "test_results.json"),
            "coverage_reports_file": str(evidences_dir / "coverage_reports.json"),
        }
