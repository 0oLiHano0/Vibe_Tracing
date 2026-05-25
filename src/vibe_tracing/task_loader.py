"""
Task List Loader and Validator for Vibe Tracing.

Loads task_list.json, validates it against the JSON Schema contract, and
performs cross-reference validation against the parsed PRD.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from vibe_tracing.core.ids import validate_id
from vibe_tracing.prd_parser import PrdParseResult, get_parent_req_id
from vibe_tracing.schema_validator import SchemaValidator


@dataclass
class DodItem:
    """Definition of Done item for a task."""

    dod_id: str
    description: str


@dataclass
class Task:
    """Representation of a task parsed from the task list."""

    task_id: str
    title: str
    phase_id: str
    priority: str
    status: str
    owner_role: str
    objective: str
    related_requirements: List[str] = field(default_factory=list)
    related_acceptance_criteria: List[str] = field(default_factory=list)
    definition_of_done: List[DodItem] = field(default_factory=list)
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)


@dataclass
class TaskGap:
    """Gap identified during task list cross-reference validation."""

    item_id: str
    item_type: str = "task"
    reason: str = ""


@dataclass
class TaskListLoadResult:
    """Result of loading and validating the task list."""

    tasks: List[Task] = field(default_factory=list)
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    gaps: List[TaskGap] = field(default_factory=list)


class TaskLoader:
    """Loads and validates the task list, cross-referencing with the PRD."""

    def __init__(self, schemas_dir: Path) -> None:
        self.schema_validator = SchemaValidator(schemas_dir)

    def load_and_validate(
        self,
        task_list_path: Path,
        prd_result: Optional[PrdParseResult] = None,
    ) -> TaskListLoadResult:
        """
        Load a task list file, validate it against the JSON schema, and cross-reference with the PRD.
        """
        # Step 1: Validate file using SchemaValidator
        val_res = self.schema_validator.validate_file(task_list_path, "task_list")
        if not val_res.is_valid:
            error_msg = f"Schema validation failed for {task_list_path}"
            if val_res.message:
                error_msg += f": {val_res.message}"
            if val_res.field_path:
                error_msg += f" at field '{val_res.field_path}'"
            if val_res.hint:
                error_msg += f" (Hint: {val_res.hint})"
            return TaskListLoadResult(
                tasks=[],
                is_valid=False,
                errors=[error_msg],
            )

        # Step 2: Parse the file content
        try:
            with task_list_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            return TaskListLoadResult(
                tasks=[],
                is_valid=False,
                errors=[f"Failed to read/parse file {task_list_path}: {exc}"],
            )

        return self.validate_data(data, prd_result, source_label=str(task_list_path))

    def validate_data(
        self,
        data: Dict[str, Any],
        prd_result: Optional[PrdParseResult] = None,
        source_label: str = "",
    ) -> TaskListLoadResult:
        """
        Validate task list data directly (useful for testing and in-memory validation).
        """
        # If not validated by caller, run schema validation first
        val_res = self.schema_validator.validate_dict(data, "task_list", source_label)
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
            return TaskListLoadResult(
                tasks=[],
                is_valid=False,
                errors=[error_msg],
            )

        tasks_list = data.get("tasks", [])
        parsed_tasks: List[Task] = []
        errors: List[str] = []
        gaps: List[TaskGap] = []
        is_valid = True

        # Check for duplicate task IDs
        task_ids_seen = set()
        duplicate_task_ids = set()
        for task_dict in tasks_list:
            task_id = task_dict.get("task_id")
            if task_id:
                if task_id in task_ids_seen:
                    duplicate_task_ids.add(task_id)
                task_ids_seen.add(task_id)

        if duplicate_task_ids:
            is_valid = False
            for tid in sorted(duplicate_task_ids):
                errors.append(f"Duplicate task ID: {tid}")

        # PRD requirement/AC sets if prd_result is available
        prd_req_ids: Set[str] = set()
        prd_ac_ids: Set[str] = set()
        if prd_result:
            for req in prd_result.requirements:
                prd_req_ids.add(req.req_id)
                for ac in req.acceptance_criteria:
                    prd_ac_ids.add(ac.ac_id)

        for task_dict in tasks_list:
            task_id = task_dict.get("task_id", "")
            title = task_dict.get("title", "")
            phase_id = task_dict.get("phase_id", "")
            priority = task_dict.get("priority", "")
            status = task_dict.get("status", "")
            owner_role = task_dict.get("owner_role", "")
            objective = task_dict.get("objective", "")
            related_requirements = task_dict.get("related_requirements", [])
            related_acceptance_criteria = task_dict.get(
                "related_acceptance_criteria", []
            )
            dod_list = task_dict.get("definition_of_done", [])

            # Parse DodItem objects
            dods = []
            for dod_dict in dod_list:
                dods.append(
                    DodItem(
                        dod_id=dod_dict.get("dod_id", ""),
                        description=dod_dict.get("description", ""),
                    )
                )

            task_obj = Task(
                task_id=task_id,
                title=title,
                phase_id=phase_id,
                priority=priority,
                status=status,
                owner_role=owner_role,
                objective=objective,
                related_requirements=list(related_requirements),
                related_acceptance_criteria=list(related_acceptance_criteria),
                definition_of_done=dods,
            )

            # Validate ID format using core validator
            id_ok, id_err = validate_id(task_id)
            if not id_ok:
                task_obj.is_valid = False
                task_obj.errors.append(f"Invalid task ID format: {id_err}")
                errors.append(f"Task {task_id} has invalid ID format: {id_err}")
                is_valid = False

            # Check isolated task condition: DOD-VT-007-01
            if not related_requirements and not related_acceptance_criteria:
                task_obj.is_valid = False
                err_msg = f"Task {task_id} is isolated (no related requirements or acceptance criteria)"
                task_obj.errors.append(err_msg)
                errors.append(err_msg)
                gaps.append(TaskGap(item_id=task_id, reason="Task is isolated"))

            # If prd_result is provided, perform cross-reference checks: DOD-VT-007-02
            if prd_result:
                # 1. Non-existent requirement IDs
                for req_id in related_requirements:
                    if req_id not in prd_req_ids:
                        task_obj.is_valid = False
                        task_obj.errors.append(
                            f"References non-existent requirement: {req_id}"
                        )
                        gaps.append(
                            TaskGap(
                                item_id=task_id,
                                reason=f"References non-existent requirement: {req_id}",
                            )
                        )

                # 2. Non-existent AC IDs
                for ac_id in related_acceptance_criteria:
                    if ac_id not in prd_ac_ids:
                        task_obj.is_valid = False
                        task_obj.errors.append(
                            f"References non-existent acceptance criterion: {ac_id}"
                        )
                        gaps.append(
                            TaskGap(
                                item_id=task_id,
                                reason=f"References non-existent acceptance criterion: {ac_id}",
                            )
                        )
                    else:
                        # 3. Inverse relationship: if AC is referenced, its parent REQ must be in related_requirements
                        try:
                            parent_req_id = get_parent_req_id(ac_id)
                            if parent_req_id not in related_requirements:
                                task_obj.is_valid = False
                                task_obj.errors.append(
                                    f"References acceptance criterion {ac_id} but parent requirement {parent_req_id} "
                                    f"is missing from related_requirements"
                                )
                                gaps.append(
                                    TaskGap(
                                        item_id=task_id,
                                        reason=f"References acceptance criterion {ac_id} but parent requirement {parent_req_id} "
                                        f"is missing from related_requirements",
                                    )
                                )
                        except ValueError as val_err:
                            task_obj.is_valid = False
                            task_obj.errors.append(str(val_err))

            parsed_tasks.append(task_obj)

        # If any parsed task is invalid, the overall result is invalid
        if any(not t.is_valid for t in parsed_tasks):
            is_valid = False

        return TaskListLoadResult(
            tasks=parsed_tasks,
            is_valid=is_valid,
            errors=errors,
            gaps=gaps,
        )
