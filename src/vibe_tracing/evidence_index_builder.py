"""
Evidence Index Builder for Vibe Tracing.

Gathers raw tasks, agent claims, code references, and test/tool output candidates
into a unified evidence record index (output/evidence_index.json) that conforms
to the evidence index JSON Schema contract.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from vibe_tracing.core.enums import CoverageStatus
from vibe_tracing.schema_validator import SchemaValidator
from vibe_tracing.task_loader import TaskListLoadResult


class EvidenceIndexBuilder:
    """Consolidates tasks, claims, code references, and tool reports into an evidence index."""

    def __init__(self, project_root: Path) -> None:
        """Initialize the Evidence Index Builder with the project root directory."""
        self.project_root = project_root
        self.schemas_dir = project_root / "schemas"
        if not self.schemas_dir.is_dir():
            self.schemas_dir = Path(__file__).parent / "schemas"

        self.schema_validator = SchemaValidator(self.schemas_dir)

    def _to_relative_path(self, path_str: str) -> str:
        """Convert an absolute file path string to a relative path string if inside project_root."""
        try:
            p = Path(path_str)
            if p.is_absolute():
                if self.project_root in p.parents or p == self.project_root:
                    return str(p.relative_to(self.project_root))
        except Exception:
            pass
        return path_str

    def build(self, output_path: Path, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        """
        Gathers all sources of evidence, normalizes them, writes the output,
        and validates it against the JSON Schema contract.

        Args:
            output_path: Path for the output JSON file.
            ctx: UnifiedContext with pre-loaded data.

        Raises:
            ValueError: If required data is missing, invalid, or validation fails.
        """
        # Step 1: Load data from ctx
        prd_res = ctx.prd
        if not prd_res.is_valid:
            raise ValueError(f"PRD parsing errors: {'; '.join(prd_res.errors)}")
        is_draft = (prd_res.status == "draft")

        task_res = ctx.task_result
        if task_res is None:
            if not is_draft:
                raise ValueError("Task list failed to load successfully.")
            task_res = TaskListLoadResult(tasks=[], is_valid=True, errors=[])

        claims_list = ctx.claims_list or []
        manifest = ctx.manifest
        config_prefix = ctx.config_prefix
        tool_evidence_candidates = ctx.tool_evidence or []

        # Setup index tracking
        evidences: List[Dict[str, Any]] = []
        evidence_counter = 1

        def get_next_id() -> str:
            nonlocal evidence_counter
            ev_id = f"EVIDENCE-VT-{evidence_counter:03d}"
            evidence_counter += 1
            return ev_id

        # Cache task covers for claims/code lookups
        task_covers_map: Dict[str, List[str]] = {}

        # 1. Process Tasks
        # Resolve source paths from manifest records
        _task_record = next(
            (r for r in manifest.inputs_used if r.file_key == "task_list"), None
        )
        _claims_record = next(
            (r for r in manifest.inputs_used if r.file_key == "agent_claims"), None
        )
        task_list_rel = (
            self._to_relative_path(_task_record.file_path)
            if _task_record
            else "docs/task_list.json"
        )
        claims_file_rel = (
            self._to_relative_path(_claims_record.file_path)
            if _claims_record
            else ".vibetracing/agent_claims.json"
        )

        for task in task_res.tasks:
            ev_id = get_next_id()
            covers = sorted(
                list(set(task.related_requirements + task.related_acceptance_criteria))
            )
            task_covers_map[task.task_id] = covers

            # Map task status to evidence status
            # "todo", "in_progress", "blocked", "done"
            status_map = {
                "todo": CoverageStatus.MISSING.value,
                "in_progress": CoverageStatus.PARTIAL.value,
                "blocked": CoverageStatus.BLOCKED.value,
                "done": CoverageStatus.COVERED.value,
            }
            status = status_map.get(task.status, CoverageStatus.UNCLEAR.value)

            evidences.append(
                {
                    "evidence_id": ev_id,
                    "source_type": "task",
                    "source_path": task_list_rel,
                    "covers": covers,
                    "status": status,
                    "details": {
                        "task_id": task.task_id,
                        "title": task.title,
                        "phase_id": task.phase_id,
                        "priority": task.priority,
                    },
                }
            )

        # 2. Process Claims & Code References
        for claim in claims_list:
            ev_id = get_next_id()
            covers = task_covers_map.get(claim.related_task, [])

            evidences.append(
                {
                    "evidence_id": ev_id,
                    "source_type": "claim",
                    "source_path": claims_file_rel,
                    "covers": covers,
                    "status": claim.claimed_status,
                    "details": {
                        "claim_id": claim.claim_id,
                        "related_task": claim.related_task,
                        "timestamp": claim.timestamp,
                        "notes": claim.notes,
                    },
                }
            )

            # Process code references
            for code_ref in claim.code_refs:
                code_ev_id = get_next_id()
                evidences.append(
                    {
                        "evidence_id": code_ev_id,
                        "source_type": "code",
                        "source_path": code_ref,
                        "covers": covers,
                        "status": CoverageStatus.COMPLIANT.value,
                        "details": {
                            "claim_id": claim.claim_id,
                            "related_task": claim.related_task,
                        },
                    }
                )

        # 3. Process Tool Reports
        for cand in tool_evidence_candidates:
            ev_id = get_next_id()
            source_path = self._to_relative_path(cand.source_path)

            evidence_dict = {
                "evidence_id": ev_id,
                "source_type": cand.source_type,
                "source_path": source_path,
                "covers": cand.covers,
                "status": cand.status,
                "details": cand.details,
            }
            if cand.error_code:
                evidence_dict["error_code"] = cand.error_code

            # Copy other standard details if relevant
            if cand.command:
                evidence_dict["details"]["command"] = cand.command
            if cand.exit_code != 0 or cand.command:
                evidence_dict["details"]["exit_code"] = cand.exit_code
            if cand.stderr:
                evidence_dict["details"]["stderr"] = cand.stderr

            evidences.append(evidence_dict)

        # Assemble the index
        run_id = f"RUN-{uuid.uuid4()}"
        scan_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        index_doc = {
            "run_id": run_id,
            "project_id": f"PROJECT-{config_prefix}",
            "scan_time": scan_time,
            "evidences": evidences,
        }

        # Write output file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_file = output_path

        try:
            with output_file.open("w", encoding="utf-8") as f:
                json.dump(index_doc, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            raise ValueError(f"Failed to write output file: {exc}")

        # Validate with SchemaValidator
        val_res = self.schema_validator.validate_file(output_file, "evidence_index")
        if not val_res.is_valid:
            error_msg = f"Generated index failed schema validation: {val_res.message}"
            if val_res.field_path:
                error_msg += f" at field '{val_res.field_path}'"
            raise ValueError(error_msg)

        return index_doc
