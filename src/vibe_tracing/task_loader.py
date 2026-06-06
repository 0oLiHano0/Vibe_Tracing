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

_HINTS_PATH = Path(__file__).parent / "templates" / "field_hints.json"


def _load_field_hints(schema_name: str) -> Dict[str, str]:
    with _HINTS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f).get(schema_name, {})


_task_field_hints = _load_field_hints("task_list")


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
    related_modules: List[str] = field(default_factory=list)
    related_architecture_constraints: List[str] = field(default_factory=list)
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

    def __init__(self, schemas_dir: Optional[Path] = None) -> None:
        self.schema_validator = SchemaValidator(schemas_dir)

    def load_and_validate(
        self,
        task_list_path: Path,
        prd_result: Optional[PrdParseResult] = None,
        arch_data: Optional[Dict] = None,
        content: Optional[dict] = None,
    ) -> TaskListLoadResult:
        """
        Load a task list file, validate it against the JSON schema, and cross-reference with the PRD and Architecture.
        """
        # Step 1: Validate file/dict using SchemaValidator
        if content is not None:
            val_res = self.schema_validator.validate_dict(
                content, "task_list", source_label=str(task_list_path)
            )
        else:
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
        if content is not None:
            data = content
        else:
            try:
                with task_list_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as exc:
                return TaskListLoadResult(
                    tasks=[],
                    is_valid=False,
                    errors=[f"Failed to read/parse file {task_list_path}: {exc}"],
                )

        return self.validate_data(data, prd_result, arch_data, source_label=str(task_list_path))

    def validate_data(
        self,
        data: Dict[str, Any],
        prd_result: Optional[PrdParseResult] = None,
        arch_data: Optional[Dict] = None,
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
        id_rules = data.get("id_rules", {})
        strict_link = id_rules.get(
            "all_tasks_must_link_requirements_and_acceptance_criteria", False
        )
        parsed_tasks: List[Task] = []
        errors: List[str] = []
        gaps: List[TaskGap] = []
        is_valid = True


        def get_err_msg(field_key: str, base_msg: str) -> str:
            hint = _task_field_hints.get(field_key)
            if hint:
                from vibe_tracing.core import ids
                hint = hint.replace("{PROJECT_PREFIX}", ids.get_project_prefix())
                return f"{base_msg}【修复指南】{hint}"
            return base_msg

        # Check for duplicate task IDs (ignoring template tasks)
        task_ids_seen = set()
        duplicate_task_ids = set()
        for task_dict in tasks_list:
            task_id = task_dict.get("task_id")
            if task_id and not task_id.endswith("-9999"):
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

        # Arch Modules/Constraints sets if arch_data is available
        arch_module_ids: Set[str] = set()
        arch_constraint_ids: Set[str] = set()
        if arch_data:
            for mod in arch_data.get("module_boundaries", []):
                if "module_id" in mod:
                    arch_module_ids.add(mod["module_id"])
            
            # Constraints can be in multiple sections
            for k in [
                "architecture_principles", 
                "dependency_rules", 
                "data_flow_rules", 
                "storage_rules", 
                "error_handling_rules", 
                "logging_rules", 
                "security_rules", 
                "technology_constraints", 
                "forbidden_patterns", 
                "quality_gates"
            ]:
                for item in arch_data.get(k, []):
                    # Each section has a different ID field name, but we can check all known ones
                    for id_field in ["principle_id", "constraint_id", "rule_id", "gate_id", "pattern_id", "tech_id", "dep_id"]:
                        if id_field in item:
                            arch_constraint_ids.add(item[id_field])

        for task_dict in tasks_list:
            task_id = task_dict.get("task_id", "")

            # Silently ignore template records ending in -9999
            if task_id.endswith("-9999"):
                continue

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
            related_modules = task_dict.get("related_modules", [])
            related_architecture_constraints = task_dict.get("related_architecture_constraints", [])
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
                related_modules=list(related_modules),
                related_architecture_constraints=list(related_architecture_constraints),
                definition_of_done=dods,
            )

            # Validate ID format using core validator
            id_ok, id_err = validate_id(task_id)
            if not id_ok:
                task_obj.is_valid = False
                base_msg = f"Invalid task ID format: {id_err}."
                full_msg = get_err_msg("task_id", f"{base_msg} ")
                task_obj.errors.append(full_msg)
                errors.append(full_msg)
                is_valid = False

            # Check isolated task condition: DOD-VT-007-01
            if strict_link:
                # AND logic: must have both REQ and AC
                if not related_requirements or not related_acceptance_criteria:
                    task_obj.is_valid = False
                    if not related_acceptance_criteria:
                        base_msg = f"Task {task_id} 缺少验收标准关联，请在 PRD 中定义对应的 AC 并在 task 中引用。"
                    else:
                        base_msg = f"Task {task_id} 缺少需求关联，请在 PRD 中定义对应的 REQ 并在 task 中引用。"
                    full_msg = get_err_msg("related_requirements", base_msg)
                    task_obj.errors.append(full_msg)
                    errors.append(full_msg)
                    gaps.append(TaskGap(item_id=task_id, reason="Task is isolated"))
            else:
                # OR logic (legacy): must have at least one of REQ or AC
                if not related_requirements and not related_acceptance_criteria:
                    task_obj.is_valid = False
                    base_msg = f"Task {task_id} is isolated (no related requirements or acceptance criteria)."
                    full_msg = get_err_msg("related_requirements", base_msg)
                    task_obj.errors.append(full_msg)
                    errors.append(full_msg)
                    gaps.append(TaskGap(item_id=task_id, reason="Task is isolated"))

            # Check architectural orphan condition
            if not related_modules and status != "done":
                task_obj.is_valid = False
                base_msg = f"Task {task_id} is an architectural orphan (no related modules defined). It must be bounded to at least one module."
                full_msg = get_err_msg("related_modules", base_msg)
                task_obj.errors.append(full_msg)
                errors.append(full_msg)
                gaps.append(TaskGap(item_id=task_id, reason="Architectural orphan"))

            # If prd_result is provided, perform cross-reference checks: DOD-VT-007-02
            if prd_result:
                # 1. Non-existent requirement IDs
                for req_id in related_requirements:
                    if req_id not in prd_req_ids:
                        task_obj.is_valid = False
                        base_msg = f"References non-existent requirement: {req_id}."
                        full_msg = get_err_msg("related_requirements", f"{base_msg} ")
                        task_obj.errors.append(full_msg)
                        errors.append(full_msg)
                        gaps.append(
                            TaskGap(
                                item_id=task_id,
                                reason=full_msg,
                            )
                        )

                # 2. Non-existent AC IDs
                for ac_id in related_acceptance_criteria:
                    if ac_id not in prd_ac_ids:
                        task_obj.is_valid = False
                        base_msg = (
                            f"References non-existent acceptance criterion: {ac_id}."
                        )
                        full_msg = get_err_msg(
                            "related_acceptance_criteria", f"{base_msg} "
                        )
                        task_obj.errors.append(full_msg)
                        errors.append(full_msg)
                        gaps.append(
                            TaskGap(
                                item_id=task_id,
                                reason=full_msg,
                            )
                        )
                    else:
                        # 3. Inverse relationship: if AC is referenced, its parent REQ must be in related_requirements
                        try:
                            parent_req_id = get_parent_req_id(ac_id)
                            if parent_req_id not in related_requirements:
                                task_obj.is_valid = False
                                base_msg = f"References acceptance criterion {ac_id} but parent requirement {parent_req_id} is missing from related_requirements."
                                full_msg = get_err_msg(
                                    "related_requirements", f"{base_msg} "
                                )
                                task_obj.errors.append(full_msg)
                                errors.append(full_msg)
                                gaps.append(
                                    TaskGap(
                                        item_id=task_id,
                                        reason=full_msg,
                                    )
                                )
                        except Exception:
                            pass
            
            # If arch_data is provided, perform cross-reference checks
            if arch_data:
                for mod_id in related_modules:
                    if mod_id not in arch_module_ids:
                        task_obj.is_valid = False
                        base_msg = f"References non-existent module in architecture constraints: {mod_id}."
                        full_msg = get_err_msg("related_modules", f"{base_msg} ")
                        task_obj.errors.append(full_msg)
                        errors.append(full_msg)
                        gaps.append(TaskGap(item_id=task_id, reason=full_msg))
                
                for constraint_id in related_architecture_constraints:
                    if constraint_id not in arch_constraint_ids:
                        task_obj.is_valid = False
                        base_msg = f"References non-existent logic constraint in architecture constraints: {constraint_id}."
                        full_msg = get_err_msg("related_architecture_constraints", f"{base_msg} ")
                        task_obj.errors.append(full_msg)
                        errors.append(full_msg)
                        gaps.append(TaskGap(item_id=task_id, reason=full_msg))

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
