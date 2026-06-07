"""AC Freshness Checker - detect tasks referencing ACs not updated in this commit.

Implements Gate 2.5 in the pre-commit flow: if a new task references ACs that
were NOT touched in the same PRD update, emit a WARNING (never blocks).

Also implements a **reverse coverage check** with two severity levels:

* **BLOCKED** -- A staged code file has NO claim covering it at all (equivalent
  to ghost code).  This produces ``success=False``.
* **WARNING** -- A staged code file IS covered by a claim, but the covering
  task was NOT modified in this commit.  This produces ``success=True`` with a
  warning message.

This prevents the bypass pattern where task+AC land in commit A and code
changes silently land in commit B.
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Set, Tuple

_CODE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx"}


class AcFreshnessChecker:
    """Check whether new tasks reference ACs that were updated in this commit."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.prd_path = "docs/prd.md"
        self.task_list_path = "docs/task_list.json"
        self.claims_path = ".vibetracing/agent_claims.json"

    def check(self) -> Tuple[bool, str]:
        """Run the AC freshness check.

        Returns ``(success, message)``.

        * ``success=False`` when the reverse check finds staged code files with
          **no covering claim at all** (BLOCKED).
        * ``success=True`` when there are only warnings (task not modified) or
          no issues.
        """
        # -- Forward check: new task -> AC fresh? (always WARNING) --
        forward_warnings = self._forward_check()

        # -- Reverse check: staged code -> covering task modified? --
        reverse_blocked, reverse_warnings = self._reverse_check()

        # Combine all messages
        all_parts: List[str] = []
        if reverse_blocked:
            all_parts.extend(reverse_blocked)
        if forward_warnings:
            all_parts.extend(forward_warnings)
        if reverse_warnings:
            all_parts.extend(reverse_warnings)

        if all_parts:
            success = not reverse_blocked  # False only when BLOCKED
            return success, "\n".join(all_parts)

        return True, ""

    # ------------------------------------------------------------------
    # Forward check (original logic)
    # ------------------------------------------------------------------

    def _forward_check(self) -> List[str]:
        """Forward check: new tasks referencing ACs not updated in this commit."""
        staged_files = self._get_staged_files()
        prd_is_staged = self.prd_path in staged_files

        new_ac_ids: Set[str] = set()
        if prd_is_staged:
            new_ac_ids = self._get_staged_prd_ac_ids()

        new_tasks = self._get_new_tasks()

        if not new_tasks:
            return []

        warnings: List[str] = []
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
            return [
                "AC 新鲜度提醒："
                "以下新增任务引用的 AC 未在本次提交中更新：\n"
                + "\n".join(warnings)
                + "\n如果这是有意为之"
                f"（例如复用已有 AC），可忽略此警告。"
            ]

        return []

    # ------------------------------------------------------------------
    # Reverse check (new logic)
    # ------------------------------------------------------------------

    def _reverse_check(self) -> Tuple[List[str], List[str]]:
        """Reverse check: staged code files vs. covering claims.

        Returns ``(blocked, warnings)`` where each is a list of formatted
        message strings.

        * **BLOCKED** -- staged code file has no covering claim at all.
        * **WARNING** -- staged code file is covered but its task was not
          modified in this commit.
        """
        staged_code_files = self._get_staged_code_files()
        if not staged_code_files:
            return [], []

        staged_claims = self._get_staged_claims()

        # Build mapping: code_file -> set of task_ids that cover it
        file_to_tasks: Dict[str, Set[str]] = {}
        for claim in staged_claims:
            task_id = claim.get("related_task", "")
            if not task_id:
                continue
            for code_ref in claim.get("code_refs", []):
                # Strip line-range suffixes like #L1-L10
                clean_ref = code_ref.split("#")[0]
                if clean_ref:
                    file_to_tasks.setdefault(clean_ref, set()).add(task_id)

        modified_task_ids = self._get_modified_task_ids()

        blocked: List[str] = []
        warnings: List[str] = []
        for code_file in sorted(staged_code_files):
            if code_file not in file_to_tasks:
                # No claim covers this file at all -> BLOCKED
                blocked.append(
                    f"  - 代码文件 {code_file} 没有关联的 Claim。"
                    f"请创建 Claim 或将文件加入白名单。"
                )
            else:
                # Has covering claims -> check if any task was modified
                for task_id in sorted(file_to_tasks[code_file]):
                    if task_id not in modified_task_ids:
                        warnings.append(
                            f"  - 代码文件 {code_file} 被任务 {task_id} 覆盖，"
                            f"但该任务未在本次提交中修改。"
                            f"请确认是否需要更新任务状态或提交 Claim。"
                        )

        blocked_messages: List[str] = []
        if blocked:
            blocked_messages.append(
                "反向覆盖检查阻断："
                "以下代码文件没有被任何任务覆盖：\n"
                + "\n".join(blocked)
                + "\n未声明 Claim 的业务代码将阻断提交。"
            )

        warning_messages: List[str] = []
        if warnings:
            warning_messages.append(
                "反向覆盖检查提醒："
                "以下代码文件的覆盖任务未在本次提交中修改：\n"
                + "\n".join(warnings)
                + "\n如果这是有意为之"
                f"（例如仅修改实现细节），可忽略此警告。"
            )

        return blocked_messages, warning_messages

    # ------------------------------------------------------------------
    # Internal helpers -- staged files / PRD / new tasks
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

    # ------------------------------------------------------------------
    # Internal helpers -- reverse check
    # ------------------------------------------------------------------

    def _get_staged_code_files(self) -> Set[str]:
        """Get staged file paths filtered to code files."""
        all_staged = self._get_staged_files()
        code_files: Set[str] = set()
        for path in all_staged:
            suffix = Path(path).suffix.lower()
            if suffix in _CODE_EXTENSIONS:
                code_files.add(path)
        return code_files

    def _get_staged_claims(self) -> List[dict]:
        """Read staged agent_claims.json from the git index."""
        try:
            result = subprocess.run(
                ["git", "show", f":{self.claims_path}"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True,
            )
            data = json.loads(result.stdout)
            if isinstance(data, list):
                return data
            return []
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
            return []

    def _get_modified_task_ids(self) -> Set[str]:
        """Return set of task_ids whose content differs between staged and HEAD.

        Detects both *new* tasks (exist in staged but not HEAD) and *modified*
        tasks (exist in both but content differs).
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
            return set()

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
            # No HEAD version -- every task in staged is new
            return {t.get("task_id") for t in staged_data.get("tasks", []) if t.get("task_id")}

        head_tasks_by_id = {
            t.get("task_id"): t for t in head_data.get("tasks", []) if t.get("task_id")
        }

        modified: Set[str] = set()
        for task in staged_data.get("tasks", []):
            task_id = task.get("task_id")
            if not task_id:
                continue
            head_task = head_tasks_by_id.get(task_id)
            if head_task is None:
                # New task
                modified.add(task_id)
            elif task != head_task:
                # Modified task (content differs)
                modified.add(task_id)

        return modified
