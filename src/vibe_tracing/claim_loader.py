"""
Agent Claim Loader and Validator for Vibe Tracing.

Loads agent_claims.json, validates it against the JSON Schema contract,
and performs cross-reference validation against the task list and external evidence rules.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from vibe_tracing.core.ids import validate_id
from vibe_tracing.schema_validator import SchemaValidator
from vibe_tracing.task_loader import TaskListLoadResult

_HINTS_PATH = Path(__file__).parent / "templates" / "field_hints.json"


def _load_field_hints(schema_name: str) -> Dict[str, str]:
    with _HINTS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f).get(schema_name, {})


_claim_field_hints = _load_field_hints("agent_claims")


@dataclass
class Claim:
    """Representation of an Agent Claim parsed from the agent claims list."""

    claim_id: str
    related_task: str
    claimed_status: str
    evidence_refs: List[str] = field(default_factory=list)
    timestamp: str = ""
    code_refs: List[str] = field(default_factory=list)
    test_refs: List[str] = field(default_factory=list)
    notes: str = ""
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    credibility: str = ""
    credibility_warnings: List[str] = field(default_factory=list)


@dataclass
class ClaimGap:
    """Gap identified during claim list validation."""

    item_id: str
    item_type: str = "claim"
    reason: str = ""


@dataclass
class ClaimListLoadResult:
    """Result of loading and validating the agent claims."""

    claims: List[Claim] = field(default_factory=list)
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    gaps: List[ClaimGap] = field(default_factory=list)


class ClaimLoader:
    """Loads and validates agent claims, cross-referencing with the task list."""

    def __init__(self, schemas_dir: Optional[Path] = None) -> None:
        self.schema_validator = SchemaValidator(schemas_dir)

    def load_and_validate(
        self,
        claims_path: Path,
        task_result: Optional[TaskListLoadResult] = None,
        content: Optional[list] = None,
        skip_schema: bool = False,
    ) -> ClaimListLoadResult:
        """
        Load an agent claims file, validate it against the JSON schema, and cross-reference with tasks.
        """
        # Step 1: Validate file/dict using SchemaValidator
        if not skip_schema:
            if content is not None:
                val_res = self.schema_validator.validate_dict(
                    content, "agent_claims", source_label=str(claims_path)
                )
            else:
                val_res = self.schema_validator.validate_file(claims_path, "agent_claims")

            if not val_res.is_valid:
                error_msg = f"Schema validation failed for {claims_path}"
                if val_res.message:
                    error_msg += f": {val_res.message}"
                if val_res.field_path:
                    error_msg += f" at field '{val_res.field_path}'"
                if val_res.hint:
                    error_msg += f" (Hint: {val_res.hint})"
                return ClaimListLoadResult(
                    claims=[],
                    is_valid=False,
                    errors=[error_msg],
                )

        # Step 2: Parse the file content
        if content is not None:
            data = content
        else:
            try:
                with claims_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as exc:
                return ClaimListLoadResult(
                    claims=[],
                    is_valid=False,
                    errors=[f"Failed to read/parse file {claims_path}: {exc}"],
                )

        return self.validate_data(data, task_result, source_label=str(claims_path))

    def validate_data(
        self,
        data: List[Dict[str, Any]],
        task_result: Optional[TaskListLoadResult] = None,
        source_label: str = "",
    ) -> ClaimListLoadResult:
        """
        Validate agent claims data directly (useful for testing and in-memory validation).
        """
        # If not validated by caller, run schema validation first
        val_res = self.schema_validator.validate_dict(
            data, "agent_claims", source_label
        )
        if not val_res.is_valid:
            error_msg = "Schema validation failed"
            if source_label:
                error_msg += f" for {source_label}"
            if val_res.message:
                error_msg += f": {val_res.message}"
            if val_res.field_path:
                error_msg += f" at field '{val_res.field_path}'"
            if val_res.hint:
                error_msg += f" (Hint: {val_res.hint})"
            return ClaimListLoadResult(
                claims=[],
                is_valid=False,
                errors=[error_msg],
            )

        parsed_claims: List[Claim] = []
        errors: List[str] = []
        gaps: List[ClaimGap] = []
        is_valid = True

        def get_err_msg(field_key: str, base_msg: str) -> str:
            hint = _claim_field_hints.get(field_key)
            if hint:
                from vibe_tracing.core import ids
                hint = hint.replace("{PROJECT_PREFIX}", ids.get_project_prefix())
                return f"{base_msg}【修复指南】{hint}"
            return base_msg

        # Check for duplicate claim IDs (ignoring template claims)
        claim_ids_seen = set()
        duplicate_claim_ids = set()
        for claim_dict in data:
            claim_id = claim_dict.get("claim_id")
            if claim_id and not claim_id.endswith("-9999"):
                if claim_id in claim_ids_seen:
                    duplicate_claim_ids.add(claim_id)
                claim_ids_seen.add(claim_id)

        if duplicate_claim_ids:
            is_valid = False
            for cid in sorted(duplicate_claim_ids):
                errors.append(f"Duplicate claim ID: {cid}")

        # Task ID set if task_result is available
        valid_task_ids: Set[str] = set()
        if task_result:
            for task in task_result.tasks:
                valid_task_ids.add(task.task_id)

        for claim_dict in data:
            claim_id = claim_dict.get("claim_id", "")

            # Silently ignore template records ending in -9999
            if claim_id.endswith("-9999"):
                continue

            related_task = claim_dict.get("related_task", "")
            claimed_status = claim_dict.get("claimed_status", "")
            evidence_refs = claim_dict.get("evidence_refs", [])
            timestamp = claim_dict.get("timestamp", "")
            code_refs = claim_dict.get("code_refs", [])
            test_refs = claim_dict.get("test_refs", [])
            notes = claim_dict.get("notes", "")

            claim_obj = Claim(
                claim_id=claim_id,
                related_task=related_task,
                claimed_status=claimed_status,
                evidence_refs=list(evidence_refs),
                timestamp=timestamp,
                code_refs=list(code_refs),
                test_refs=list(test_refs),
                notes=notes,
            )

            # Validate ID format using core validator
            id_ok, id_err = validate_id(claim_id)
            if not id_ok:
                claim_obj.is_valid = False
                base_msg = f"Invalid claim ID format: {id_err}."
                full_msg = get_err_msg("claim_id", f"{base_msg} ")
                claim_obj.errors.append(full_msg)
                errors.append(full_msg)
                is_valid = False

            # Validate related task ID format
            task_ok, task_err = validate_id(related_task)
            if not task_ok:
                claim_obj.is_valid = False
                base_msg = f"Invalid related task ID format: {task_err}."
                full_msg = get_err_msg("related_task", f"{base_msg} ")
                claim_obj.errors.append(full_msg)
                errors.append(full_msg)
                is_valid = False

            # Check if claim references a non-existent task: DOD-VT-008-02
            if task_result and task_ok:
                if related_task not in valid_task_ids:
                    claim_obj.is_valid = False
                    base_msg = f"References non-existent task: {related_task}."
                    full_msg = get_err_msg("related_task", f"{base_msg} ")
                    claim_obj.errors.append(full_msg)
                    errors.append(full_msg)
                    gaps.append(
                        ClaimGap(
                            item_id=claim_id,
                            reason=full_msg,
                        )
                    )

            # Completed claims must have external evidence: DOD-VT-008-03
            if claimed_status in ("covered", "compliant"):
                # Filter out self-referential evidence
                external_evidences = [ref for ref in evidence_refs if ref != claim_id]
                if not external_evidences:
                    claim_obj.is_valid = False
                    base_msg = f"Completed claim {claim_id} has no external evidence (self-referential or empty)."
                    full_msg = get_err_msg("evidence_refs", f"{base_msg} ")
                    claim_obj.errors.append(full_msg)
                    errors.append(full_msg)
                    gaps.append(
                        ClaimGap(
                            item_id=claim_id,
                            reason=full_msg,
                        )
                    )

            parsed_claims.append(claim_obj)

        # If any parsed claim is invalid, the overall result is invalid
        if any(not c.is_valid for c in parsed_claims):
            is_valid = False

        return ClaimListLoadResult(
            claims=parsed_claims,
            is_valid=is_valid,
            errors=errors,
            gaps=gaps,
        )


