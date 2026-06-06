import json
import subprocess
from pathlib import Path
from typing import Tuple, Set

class GhostCodeReconciler:
    """
    Implements the Ghost Code Reconciliation engine (Gate 2).
    Enforces the First Principle (State is Delta) to detect Reusable Receipt Exploits.
    """
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.claims_path = project_root / ".vibetracing" / "agent_claims.json"
        
        # Exact Whitelist (The ledger itself shouldn't require a receipt)
        self.whitelist_paths = {
            ".vibetracing/agent_claims.json",
            ".vibetracing/config.json",
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
        except subprocess.CalledProcessError:
            return set()

    def _get_active_claims_code_refs(self) -> Set[str]:
        # 1. Get Staged Claims
        if not self.claims_path.exists():
            staged_claims = []
        else:
            try:
                staged_claims = json.loads(self.claims_path.read_text(encoding="utf-8"))
            except Exception:
                staged_claims = []

        # 2. Get HEAD Claims
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
        except Exception:
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
                "如果它是合法代码，请在 .vibetracing/agent_claims.json 中增加或更新对应的发票，并将其与代码一同提交。"
            )
            
        return True, ""
