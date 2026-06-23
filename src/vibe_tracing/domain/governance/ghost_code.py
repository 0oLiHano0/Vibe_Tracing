import json
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

from vibe_tracing.infra.config.boundary import load_boundary, is_in_scope
from vibe_tracing.infra.logging.logger import OperationalLogger

class GhostCodeReconciler:
    """
    Implements the Ghost Code Reconciliation engine (Gate 2) including
    merged AC Freshness checks (Gate 2.5).

    Enforces the First Principle (State is Delta) to detect Reusable Receipt
    Exploits, and validates task coverage and AC freshness for staged code.
    """
    def __init__(self, project_root: Path, conn: sqlite3.Connection):
        self.project_root = project_root
        self.conn = conn
        self.claims_dir = project_root / ".vibetracing" / "claims"

        # Exact Whitelist (The ledger itself shouldn't require a receipt)
        self.whitelist_paths = {
            ".vibetracing/config.json",
            "docs/task_list.json",
        }

        # Prefix Whitelist for claims directory files
        self.whitelist_prefixes_claims = ".vibetracing/claims/"

        # Prefix Whitelist
        self.whitelist_prefixes = [
            ".git/",
            "output/",
        ]

    def _is_whitelisted(self, file_path: str) -> bool:
        if file_path in self.whitelist_paths:
            return True
        if file_path.startswith(self.whitelist_prefixes_claims):
            return True
        for prefix in self.whitelist_prefixes:
            if file_path.startswith(prefix):
                return True
        return False

    def _read_claims_from_filesystem(self) -> List[dict]:
        """Read all CLAIM-*.json files from the claims directory on disk."""
        all_claims = []
        if not self.claims_dir.is_dir():
            return all_claims
        for claim_file in sorted(self.claims_dir.glob("CLAIM-*.json")):
            try:
                data = json.loads(claim_file.read_text(encoding="utf-8"))
                items = data if isinstance(data, list) else [data]
                for item in items:
                    # Skip template records
                    if item.get("claim_id", "").endswith("-9999"):
                        continue
                    # Skip claims missing required fields (load_claims needs claim_id + related_task)
                    if not item.get("claim_id") or not item.get("related_task"):
                        continue
                    all_claims.append(item)
            except (json.JSONDecodeError, OSError) as exc:
                OperationalLogger.get().debug(
                    "claim_file_load_failed",
                    f"Could not load claim file {claim_file}",
                    exc=exc,
                )
        return all_claims

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
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            OperationalLogger.get().warning("git_subprocess_failed", "Git operation failed: _get_staged_files", exc=e)
            print("Warning: git 未安装或不在 PATH 中，跳过检查。")
            return set()

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

        claims = self._read_claims_from_filesystem()
        from vibe_tracing.infra.db import load_staged_files, load_claims, check_ghost_code
        load_staged_files(self.conn, business_code_files)
        load_claims(self.conn, claims)
        ghost_files = set(check_ghost_code(self.conn))

        if ghost_files:
            files_str = "\n".join(f"  - {f}" for f in ghost_files)
            return False, (
                "发现未经报备的幽灵代码！\n"
                f"{files_str}\n"
                "上述文件在本次提交中没有对应的【活跃发票】（Claim）。\n"
                "如果它是合法代码，请在 .vibetracing/claims/ 中创建或更新对应的 Claim 文件，并将其与代码一同提交。"
            )

        # Gate 2.5 checks (merged from AcFreshnessChecker)
        all_warnings: List[str] = []

        blocked, warnings = self._check_task_coverage(business_code_files)
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
        """Read CLAIM-*.json files from the claims directory on disk."""
        return self._read_claims_from_filesystem()

    def _get_staged_tasks(self) -> Optional[dict]:
        """Read task_list.json from the filesystem."""
        task_list_path = self.project_root / "docs" / "task_list.json"
        try:
            return json.loads(task_list_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            OperationalLogger.get().warning(
                "task_list_load_failed", "Could not load task_list.json", exc=exc
            )
            return None

    # ------------------------------------------------------------------
    # Gate 2.5 -- Reverse coverage check
    # ------------------------------------------------------------------

    def _check_task_coverage(
        self, staged_files: Set[str]
    ) -> Tuple[List[str], List[str]]:
        """Reverse coverage check: staged code files vs covering tasks.

        Returns ``(blocked_messages, warning_messages)``.

        Only checks if referenced tasks exist in task_list.json (BLOCKED).
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

        all_task_ids = self._get_all_task_ids()

        blocked: List[str] = []
        for code_file in sorted(staged_files):
            if code_file not in file_to_tasks:
                continue
            task_ids = file_to_tasks[code_file]
            for task_id in sorted(task_ids):
                if task_id not in all_task_ids:
                    blocked.append(
                        f"  - 代码文件 {code_file} 关联的 Claim 引用任务 {task_id}，"
                        f"但该任务不存在于 task_list.json 中。"
                    )

        blocked_messages: List[str] = []
        if blocked:
            blocked_messages.append(
                "反向覆盖检查阻断："
                "以下代码文件的覆盖任务不存在于 task_list.json 中：\n"
                + "\n".join(blocked)
                + "\n请确保 task_list.json 中包含对应的 Task 定义。"
            )

        return blocked_messages, []

    def _get_all_task_ids(self) -> Set[str]:
        """Return set of all task_ids in task_list.json."""
        data = self._get_staged_tasks()
        if not data:
            return set()
        return {t.get("task_id") for t in data.get("tasks", []) if t.get("task_id")}

    # ------------------------------------------------------------------
    # Gate 2.5 -- Forward AC freshness check
    # ------------------------------------------------------------------

    def _check_ac_freshness(self) -> List[str]:
        """Forward AC freshness check: tasks referencing ACs not in PRD.

        Returns warning messages (never blocks).
        """
        staged_data = self._get_staged_tasks()
        if not staged_data:
            return []

        # Collect all AC IDs referenced by tasks
        task_acs: Dict[str, Set[str]] = {}
        for task in staged_data.get("tasks", []):
            task_id = task.get("task_id", "")
            ac_ids = set(task.get("related_acceptance_criteria", []))
            if task_id and ac_ids:
                task_acs[task_id] = ac_ids

        if not task_acs:
            return []

        # Check if PRD exists on disk
        prd_path = self.project_root / "docs" / "prd.md"
        prd_exists = prd_path.is_file()

        # Get AC IDs from PRD
        staged_ac_ids: Set[str] = set()
        if prd_exists:
            staged_ac_ids = self._get_staged_prd_ac_ids()

        warnings: List[str] = []
        for task_id, ac_ids in task_acs.items():
            for ac_id in ac_ids:
                if prd_exists and ac_id in staged_ac_ids:
                    continue
                if not prd_exists:
                    warnings.append(
                        f"  - 任务 {task_id} 引用 AC {ac_id}，"
                        f"但 PRD 文件不存在。"
                        f"请确认需求文档是否需要创建。"
                    )
                else:
                    warnings.append(
                        f"  - 任务 {task_id} 引用 AC {ac_id}，"
                        f"但该 AC 不在 PRD 中。"
                    )

        if warnings:
            return [
                "AC 新鲜度提醒："
                "以下任务引用的 AC 未在 PRD 中找到：\n"
                + "\n".join(warnings)
                + "\n如果这是有意为之"
                "（例如复用已有 AC），可忽略此警告。"
            ]

        return []

    def _get_staged_prd_ac_ids(self) -> Set[str]:
        """Parse PRD content from filesystem and extract all AC IDs."""
        prd_path = self.project_root / "docs" / "prd.md"
        try:
            content = prd_path.read_text(encoding="utf-8")
            ac_pattern = re.compile(r"AC-[A-Z]+-\d+-\d+")
            return set(ac_pattern.findall(content))
        except OSError as exc:
            OperationalLogger.get().warning(
                "prd_ac_parse_failed", "Could not read PRD for AC extraction", exc=exc
            )
            return set()
