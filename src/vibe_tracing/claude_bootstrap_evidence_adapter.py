"""
Claude Bootstrap Evidence Adapter for Vibe Tracing.

Normalizes subagent execution logs, actions, and dialogues into candidate evidence.
"""

import json
from pathlib import Path
from typing import List

from vibe_tracing.core.enums import CoverageStatus
from vibe_tracing.tool_evidence_adapter import ToolEvidenceCandidate


class ClaudeBootstrapEvidenceAdapter:
    """Converts subagent runtime outputs (logs, traces, dialogues) into evidence candidates."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self._evidence_counter = 1

    def _next_evidence_id(self) -> str:
        """Generate sequential evidence ID."""
        ev_id = f"EVIDENCE-VT-SUB-{self._evidence_counter:03d}"
        self._evidence_counter += 1
        return ev_id

    def parse_log_file(self, file_path: Path) -> List[ToolEvidenceCandidate]:
        """
        Parse a subagent runtime log file and return list of evidence candidates.

        Args:
            file_path: Path to the subagent log JSON file.

        Returns:
            List of ToolEvidenceCandidate.
        """
        path_str = str(
            file_path.relative_to(self.project_root)
            if file_path.is_absolute() and self.project_root in file_path.parents
            else file_path
        )

        if not file_path.exists():
            return []

        try:
            with file_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            # If not valid JSON, treat it as unstructured dialogue / corrupt log
            return [
                ToolEvidenceCandidate(
                    evidence_id=self._next_evidence_id(),
                    source_type="tool",
                    source_path=path_str,
                    covers=[],
                    status=CoverageStatus.LOW_CONFIDENCE.value,
                    details={
                        "error": "Corrupt or unstructured log format. Interpreted as dialogue only."
                    },
                )
            ]

        candidates: List[ToolEvidenceCandidate] = []
        if isinstance(data, dict) and "runs" in data:
            runs = data["runs"]
        elif isinstance(data, list):
            runs = data
        else:
            runs = [data]

        for run in runs:
            subagent_id = run.get("subagent_id", "UNKNOWN-SUBAGENT")
            task_id = run.get("task_id", "")
            dialogue = run.get("dialogue", "")
            actions = run.get("actions", [])
            claims = run.get("produced_claims", [])

            # Determine covers from claims or default to empty
            covers = []
            for claim in claims:
                for ref in claim.get("evidence_refs", []):
                    if ref not in covers:
                        covers.append(ref)

            # Rule: If there is dialogue but no structured actions or claims,
            # it is a pure unstructured dialogue, which defaults to 'low_confidence' or 'missing'.
            if dialogue and not actions and not claims:
                candidates.append(
                    ToolEvidenceCandidate(
                        evidence_id=self._next_evidence_id(),
                        source_type="tool",
                        source_path=path_str,
                        covers=[],
                        status=CoverageStatus.LOW_CONFIDENCE.value,
                        details={
                            "subagent_id": subagent_id,
                            "task_id": task_id,
                            "dialogue_snippet": dialogue[:100],
                            "type": "unstructured_dialogue",
                        },
                    )
                )
                continue

            # Determine status based on actions success rate and presence of claims
            if not actions and not claims:
                status = CoverageStatus.MISSING.value
            else:
                # Check if any action failed
                failed_actions = [a for a in actions if a.get("status") == "failed"]
                if failed_actions:
                    status = CoverageStatus.PARTIAL.value
                else:
                    status = CoverageStatus.COVERED.value

            candidates.append(
                ToolEvidenceCandidate(
                    evidence_id=self._next_evidence_id(),
                    source_type="tool",
                    source_path=path_str,
                    covers=covers,
                    status=status,
                    details={
                        "subagent_id": subagent_id,
                        "task_id": task_id,
                        "actions_count": len(actions),
                        "claims_count": len(claims),
                        "type": "structured_subagent_run",
                    },
                )
            )

        return candidates
