"""
任务列表加载器与校验器。

从 task_list.json 加载任务列表，进行任务自身属性的自洽校验
（孤立任务检测、架构孤儿检测）。

注意：Task↔PRD 的跨引用校验已下沉至 SQL 查询层（check_invalid_task_* 系列函数），
本模块不进行文件之间的交叉引用校验。
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from vibe_tracing.infra.config.hint_loader import load_hints, resolve_hint


_task_field_hints = None


def _get_task_field_hints() -> dict:
    """延迟加载输入字段提示信息。"""
    global _task_field_hints
    if _task_field_hints is None:
        _task_field_hints = load_hints("input")
    return _task_field_hints


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
    """加载并校验任务列表。"""

    def load_and_validate(
        self,
        task_list_path: Path,
        content: Optional[dict] = None,
    ) -> TaskListLoadResult:
        """
        Load a task list file and validate it against the JSON schema.
        """
        # Parse the file content (schema is validated once by the CLI caller)
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

        return self.validate_data(data, source_label=str(task_list_path))

    def validate_data(
        self,
        data: Dict[str, Any],
        source_label: str = "",
    ) -> TaskListLoadResult:
        """
        Validate task list data directly (useful for testing and in-memory validation).
        """
        tasks_list = data.get("tasks", [])
        id_rules = data.get("id_rules", {})
        strict_link = id_rules.get(
            "all_tasks_must_link_requirements_and_acceptance_criteria", False
        )
        parsed_tasks: List[Task] = []
        errors: List[str] = []
        gaps: List[TaskGap] = []
        is_valid = True


        def get_err_msg(field_key: str, base_msg: str, level: str = "level3") -> str:
            hint_raw = _get_task_field_hints().get(field_key)
            if hint_raw:
                from vibe_tracing.infra import validation as ids
                hint = resolve_hint(hint_raw, level).replace("{PROJECT_PREFIX}", ids.get_project_prefix())
                return f"{base_msg}【修复指南】{hint}"
            return base_msg

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
                # OR logic: must have at least one of REQ or AC
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
