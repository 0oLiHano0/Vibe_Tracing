"""
任务列表反序列化器。

从已解析的 dict 反序列化任务列表数据为结构化对象。

注意：Task↔PRD 的跨引用校验已下沉至 SQL 查询层，
本模块不进行文件之间的交叉引用校验。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class DodItem:
    """任务的完成定义条目。"""

    dod_id: str
    description: str


@dataclass
class Task:
    """从任务列表中解析出的任务数据对象。"""

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


@dataclass
class TaskListLoadResult:
    """任务列表加载与校验的结果容器。"""

    tasks: List[Task] = field(default_factory=list)


class TaskLoader:
    """加载并反序列化任务列表。"""

    def deserialize(
        self,
        data: Dict[str, Any],
    ) -> TaskListLoadResult:
        """反序列化任务列表数据为结构化对象。"""
        tasks_list = data.get("tasks", [])
        parsed_tasks: List[Task] = []

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

            parsed_tasks.append(task_obj)

        return TaskListLoadResult(tasks=parsed_tasks)
