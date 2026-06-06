"""AC Freshness Checker - detect tasks referencing ACs not updated in this commit.

Implements Gate 2.5 in the pre-commit flow: if a new task references ACs that
were NOT touched in the same PRD update, emit a WARNING (never blocks).
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Dict, Set, Tuple


class AcFreshnessChecker:
    """Check whether new tasks reference ACs that were updated in this commit."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.prd_path = "docs/prd.md"
        self.task_list_path = "docs/task_list.json"

    def check(self) -> Tuple[bool, str]:
        """Run the AC freshness check.

        Returns ``(success, warning_message)``.
        *success* is always ``True`` -- this gate only warns, never blocks.
        """
        staged_files = self._get_staged_files()
        prd_is_staged = self.prd_path in staged_files

        new_ac_ids: Set[str] = set()
        if prd_is_staged:
            new_ac_ids = self._get_staged_prd_ac_ids()

        new_tasks = self._get_new_tasks()

        if not new_tasks:
            return True, ""

        warnings = []
        for task_id, ac_ids in new_tasks.items():
            if not ac_ids:
                continue
            for ac_id in ac_ids:
                if prd_is_staged and ac_id in new_ac_ids:
                    continue  # AC was updated in this commit -- OK
                if not prd_is_staged:
                    warnings.append(
                        f"  - 任务 {task_id} 引用 AC {ac_id}，"
                        f"但本次提交未更新 PRD。"
                        f"请确认需求文档是否需要同步更新。"
                    )
                else:
                    warnings.append(
                        f"  - 任务 {task_id} 引用 AC {ac_id}，"
                        f"但该 AC 不在本次 PRD 更新范围内。"
                    )

        if warnings:
            return True, (
                "AC 新鲜度提醒："
                "以下新增任务引用的 AC 未在本次提交中更新：\n"
                + "\n".join(warnings)
                + "\n如果这是有意为之"
                f"（例如复用已有 AC），可忽略此警告。"
            )

        return True, ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_staged_files(self) -> Set[str]:
        """Get list of staged file paths."""
        try:
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True,
            )
            return {line.strip() for line in result.stdout.splitlines() if line.strip()}
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("Warning: git 未安装或不在 PATH 中，跳过检查。")
            return set()

    def _get_staged_prd_ac_ids(self) -> Set[str]:
        """Parse staged PRD content and extract all AC IDs."""
        try:
            result = subprocess.run(
                ["git", "show", f":{self.prd_path}"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True,
            )
            content = result.stdout
            ac_pattern = re.compile(r"AC-[A-Z]+-\d+-\d+")
            return set(ac_pattern.findall(content))
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("Warning: git 未安装或不在 PATH 中，跳过检查。")
            return set()

    def _get_new_tasks(self) -> Dict[str, Set[str]]:
        """Compare staged vs HEAD task_list.json to find new tasks.

        Returns ``{task_id: {ac_id, ...}}`` for tasks that exist in the
        staged index but not in HEAD.
        """
        try:
            staged_result = subprocess.run(
                ["git", "show", f":{self.task_list_path}"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True,
            )
            staged_data = json.loads(staged_result.stdout)
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
            print("Warning: git 未安装或不在 PATH 中，跳过检查。")
            return {}

        try:
            head_result = subprocess.run(
                ["git", "show", f"HEAD:{self.task_list_path}"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True,
            )
            head_data = json.loads(head_result.stdout)
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
            print("Warning: git 未安装或不在 PATH 中，跳过检查。")
            head_data = {"tasks": []}

        head_task_ids = {t.get("task_id") for t in head_data.get("tasks", [])}

        new_tasks: Dict[str, Set[str]] = {}
        for task in staged_data.get("tasks", []):
            task_id = task.get("task_id")
            if task_id and task_id not in head_task_ids:
                ac_ids = set(task.get("related_acceptance_criteria", []))
                new_tasks[task_id] = ac_ids

        return new_tasks
