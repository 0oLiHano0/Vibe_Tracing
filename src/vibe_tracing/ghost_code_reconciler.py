import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

from vibe_tracing.governance import load_boundary, is_in_scope

class GhostCodeReconciler:
    """
    Implements the Ghost Code Reconciliation engine (Gate 2) including
    merged AC Freshness checks (Gate 2.5).

    Enforces the First Principle (State is Delta) to detect Reusable Receipt
    Exploits, and validates task coverage and AC freshness for staged code.
    """
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.claims_path = project_root / ".vibetracing" / "claims" / "current.json"

        # Exact Whitelist (The ledger itself shouldn't require a receipt)
        self.whitelist_paths = {
            ".vibetracing/claims/current.json",
            ".vibetracing/agent_claims.json",
            ".vibetracing/config.json",
            ".vibetracing/semantic_audit.json",
            "docs/task_list.json",
        }

        # Prefix Whitelist
        self.whitelist_prefixes = [
            ".git/",
            "output/",
        ]

    def _is_whitelisted(self, file_path: str) -> bool:
        if file_path in self.whitelist_paths:
            return True
        for prefix in self.whitelist_prefixes:
            if file_path.startswith(prefix):
                return True
        return False

    def _get_staged_files(self) -> Set[str]:
        try:
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True
            )
            return {line.strip() for line in result.stdout.splitlines() if line.strip()}
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("Warning: git 未安装或不在 PATH 中，跳过检查。")
            return set()

    def _get_active_claims_code_refs(self) -> Set[str]:
        # 1. Get Staged Claims (from git index, NOT working directory)
        staged_claims = []
        try:
            claims_rel = str(self.claims_path.relative_to(self.project_root))
            result = subprocess.run(
                ["git", "show", f":{claims_rel}"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True
            )
            staged_claims = json.loads(result.stdout)
        except FileNotFoundError:
            print("Warning: git 未安装或不在 PATH 中，跳过检查。")
            staged_claims = []
        except subprocess.CalledProcessError:
            # File not staged - no claims available
            staged_claims = []
        except Exception as exc:
            print(f"Warning: claims/current.json 格式解析失败，将按无 claims 处理: {exc}", file=sys.stderr)
            staged_claims = []

        # 2. Get HEAD Claims (unchanged)
        head_claims = []
        try:
            claims_rel = str(self.claims_path.relative_to(self.project_root))
            result = subprocess.run(
                ["git", "show", f"HEAD:{claims_rel}"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True
            )
            head_claims = json.loads(result.stdout)
        except FileNotFoundError:
            print("Warning: git 未安装或不在 PATH 中，跳过检查。")
            head_claims = []
        except subprocess.CalledProcessError:
            head_claims = []
        except Exception as exc:
            print(f"Warning: claims/current.json 格式解析失败，将按无 claims 处理: {exc}", file=sys.stderr)
            head_claims = []

        # 3. Calculate Delta (State is Delta)
        active_code_refs = set()
        for staged_claim in staged_claims:
            # Check if it exists and is identical in HEAD
            # Ignore template records
            if staged_claim.get("claim_id", "").endswith("-9999"):
                continue
            if staged_claim not in head_claims:
                # It is a NEW or MODIFIED claim in this commit!
                active_code_refs.update(staged_claim.get("code_refs", []))

        return active_code_refs

    def reconcile(self) -> Tuple[bool, str]:
        staged_files = self._get_staged_files()

        # Filter whitelisted files
        business_code_files = {f for f in staged_files if not self._is_whitelisted(f)}

        # Filter files outside governance boundary
        boundary = load_boundary(self.project_root)
        business_code_files = {f for f in business_code_files if is_in_scope(f, boundary)}

        if not business_code_files:
            # No business code modified, perfect agility for governance assets
            return True, ""

        active_refs = self._get_active_claims_code_refs()

        ghost_files = business_code_files - active_refs

        if ghost_files:
            files_str = "\n".join(f"  - {f}" for f in ghost_files)
            return False, (
                "发现未经报备的幽灵代码！\n"
                f"{files_str}\n"
                "上述文件在本次提交中没有对应的【活跃发票】（Claim）。\n"
                "如果它是合法代码，请在 .vibetracing/claims/current.json 中增加或更新对应的发票，并将其与代码一同提交。"
            )

        # Gate 2.5 checks (merged from AcFreshnessChecker)
        all_warnings: List[str] = []

        blocked, warnings = self._check_task_coverage(business_code_files, active_refs)
        if blocked:
            return False, "\n".join(blocked)
        all_warnings.extend(warnings)

        ac_warnings = self._check_ac_freshness()
        all_warnings.extend(ac_warnings)

        if all_warnings:
            return True, "\n".join(all_warnings)

        return True, ""

    # ------------------------------------------------------------------
    # Internal helpers -- claims / tasks
    # ------------------------------------------------------------------

    def _get_staged_claims(self) -> List[dict]:
        """Read staged agent_claims.json from the git index."""
        try:
            claims_rel = str(self.claims_path.relative_to(self.project_root))
            result = subprocess.run(
                ["git", "show", f":{claims_rel}"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True,
            )
            data = json.loads(result.stdout)
            if isinstance(data, list):
                return data
            return []
        except (subprocess.CalledProcessError, FileNotFoundError):
            return []
        except (json.JSONDecodeError, Exception) as exc:
            print(f"Warning: claims/current.json 格式解析失败，将按无 claims 处理: {exc}", file=sys.stderr)
            return []

    def _get_staged_tasks(self) -> Optional[dict]:
        """Read staged task_list.json from the git index."""
        try:
            result = subprocess.run(
                ["git", "show", ":docs/task_list.json"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True,
            )
            return json.loads(result.stdout)
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
            return None

    def _get_head_tasks(self) -> Optional[dict]:
        """Read HEAD task_list.json."""
        try:
            result = subprocess.run(
                ["git", "show", "HEAD:docs/task_list.json"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True,
            )
            return json.loads(result.stdout)
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
            return None

    def _get_modified_task_ids(self) -> Set[str]:
        """Return set of task_ids whose content differs between staged and HEAD.

        Detects both *new* tasks (exist in staged but not HEAD) and *modified*
        tasks (exist in both but content differs).
        """
        staged_data = self._get_staged_tasks()
        head_data = self._get_head_tasks()

        if not staged_data:
            return set()

        if head_data is None:
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
                modified.add(task_id)
            elif task != head_task:
                modified.add(task_id)

        return modified

    # ------------------------------------------------------------------
    # Gate 2.5 -- Reverse coverage check
    # ------------------------------------------------------------------

    def _check_task_coverage(
        self, staged_files: Set[str], active_code_refs: Set[str]
    ) -> Tuple[List[str], List[str]]:
        """Reverse coverage check: staged code files vs covering tasks.

        Returns ``(blocked_messages, warning_messages)``.

        * **BLOCKED** -- A staged code file IS covered by a claim, but NO task
          exists for that claim.
        * **WARNING** -- A staged code file IS covered by a claim, and a task
          exists but was NOT modified in this commit.

        Files with no covering claim are skipped (already handled by ghost code
        check).
        """
        staged_claims = self._get_staged_claims()

        # Build mapping: code_file -> set of task_ids
        file_to_tasks: Dict[str, Set[str]] = {}
        for claim in staged_claims:
            task_id = claim.get("related_task", "")
            if not task_id:
                continue
            for code_ref in claim.get("code_refs", []):
                clean_ref = code_ref.split("#")[0]
                if clean_ref:
                    file_to_tasks.setdefault(clean_ref, set()).add(task_id)

        modified_task_ids = self._get_modified_task_ids()
        all_task_ids = self._get_all_task_ids()
        task_statuses = self._get_task_statuses()

        blocked: List[str] = []
        warnings: List[str] = []
        for code_file in sorted(staged_files):
            if code_file not in file_to_tasks:
                # No claim covers this file -- already handled by ghost code check
                continue

            task_ids = file_to_tasks[code_file]
            for task_id in sorted(task_ids):
                if task_id not in all_task_ids:
                    blocked.append(
                        f"  - 代码文件 {code_file} 关联的 Claim 引用任务 {task_id}，"
                        f"但该任务不存在于 task_list.json 中。"
                    )
                elif task_id not in modified_task_ids and task_statuses.get(task_id) != "done":
                    warnings.append(
                        f"  - 代码文件 {code_file} 被活跃任务 {task_id} 覆盖，"
                        f"但该任务未在本次提交中修改。"
                        f"请确认是否需要更新任务状态或提交 Claim。"
                    )

        blocked_messages: List[str] = []
        if blocked:
            blocked_messages.append(
                "反向覆盖检查阻断："
                "以下代码文件的覆盖任务不存在于 task_list.json 中：\n"
                + "\n".join(blocked)
                + "\n请确保 task_list.json 中包含对应的 Task 定义。"
            )

        warning_messages: List[str] = []
        if warnings:
            warning_messages.append(
                "反向覆盖检查提醒："
                "以下代码文件的覆盖任务未在本次提交中修改：\n"
                + "\n".join(warnings)
                + "\n如果这是有意为之"
                "（例如仅修改实现细节），可忽略此警告。"
            )

        return blocked_messages, warning_messages

    def _get_all_task_ids(self) -> Set[str]:
        """Return set of all task_ids in the staged task_list.json."""
        staged_data = self._get_staged_tasks()
        if not staged_data:
            return set()
        return {t.get("task_id") for t in staged_data.get("tasks", []) if t.get("task_id")}

    def _get_task_statuses(self) -> Dict[str, str]:
        """Return mapping of task_id -> status from staged task_list.json."""
        staged_data = self._get_staged_tasks()
        if not staged_data:
            return {}
        return {t.get("task_id"): t.get("status", "") for t in staged_data.get("tasks", []) if t.get("task_id")}

    # ------------------------------------------------------------------
    # Gate 2.5 -- Forward AC freshness check
    # ------------------------------------------------------------------

    def _check_ac_freshness(self) -> List[str]:
        """Forward AC freshness check: new tasks referencing ACs not in staged PRD.

        Returns warning messages (never blocks).
        """
        staged_data = self._get_staged_tasks()
        head_data = self._get_head_tasks()

        if not staged_data:
            return []

        head_task_ids = set()
        if head_data:
            head_task_ids = {t.get("task_id") for t in head_data.get("tasks", []) if t.get("task_id")}

        # Find new tasks
        new_tasks: Dict[str, Set[str]] = {}
        for task in staged_data.get("tasks", []):
            task_id = task.get("task_id")
            if task_id and task_id not in head_task_ids:
                ac_ids = set(task.get("related_acceptance_criteria", []))
                new_tasks[task_id] = ac_ids

        if not new_tasks:
            return []

        # Check if PRD is staged
        prd_path = "docs/prd.md"
        prd_is_staged = False
        try:
            subprocess.run(
                ["git", "show", f":{prd_path}"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True,
            )
            prd_is_staged = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        # Get AC IDs from staged PRD
        staged_ac_ids: Set[str] = set()
        if prd_is_staged:
            staged_ac_ids = self._get_staged_prd_ac_ids()

        warnings: List[str] = []
        for task_id, ac_ids in new_tasks.items():
            if not ac_ids:
                continue
            for ac_id in ac_ids:
                if prd_is_staged and ac_id in staged_ac_ids:
                    continue
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
                "（例如复用已有 AC），可忽略此警告。"
            ]

        return []

    def _get_staged_prd_ac_ids(self) -> Set[str]:
        """Parse staged PRD content and extract all AC IDs."""
        try:
            result = subprocess.run(
                ["git", "show", ":docs/prd.md"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True,
            )
            content = result.stdout
            ac_pattern = re.compile(r"AC-[A-Z]+-\d+-\d+")
            return set(ac_pattern.findall(content))
        except (subprocess.CalledProcessError, FileNotFoundError):
            return set()
