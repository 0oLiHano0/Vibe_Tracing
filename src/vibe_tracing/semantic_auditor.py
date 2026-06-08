"""
Protocol-Based Self-Semantic Audit for Vibe Tracing.

VT stays deterministic (no LLM) but generates audit tickets that the Coding Agent
fills in with LLM-generated reasons.  Only code changes linked to
``quality_evolution`` tasks trigger semantic audit.

Two-phase flow:
  1. ``generate_tickets()`` -- creates pending tickets for staged code files
     whose covering claim links to a quality_evolution task.
  2. ``verify_tickets()`` -- checks that all tickets for staged files are in
     ``passed`` status with a non-empty ``audit_reason`` and a matching
     ``file_hash``.
"""

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


class SemanticAuditor:
    """Deterministic semantic audit gate -- generates and verifies audit tickets."""

    # Code extensions that trigger semantic audit
    CODE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx"}

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.audit_path = project_root / ".vibetracing" / "semantic_audit.json"
        self.task_list_path = "docs/task_list.json"
        self.claims_path = ".vibetracing/agent_claims.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_staged_code_files(self) -> Set[str]:
        """Get staged code files filtered to code extensions (.py, .js, .ts, .jsx, .tsx)."""
        try:
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True,
            )
            files: Set[str] = set()
            for line in result.stdout.splitlines():
                line = line.strip()
                if line and Path(line).suffix in self.CODE_EXTENSIONS:
                    files.add(line)
            return files
        except (subprocess.CalledProcessError, FileNotFoundError):
            return set()

    def generate_tickets(
        self,
        staged_files: Set[str],
        claims: List[dict],
        tasks: List[dict],
        requirements: Optional[List[dict]] = None,
    ) -> List[dict]:
        """Generate pending audit tickets for *quality_evolution* code changes.

        For each staged code file:
        1. Find a covering claim (via ``code_refs``).
        2. Find the linked task (via the claim's ``related_task``).
        3. Check if the task is a quality_evolution task by:
           a. task.get("category") == "quality_evolution", OR
           b. Any of task's related_requirements has category "quality_evolution"
              (looked up from *requirements* list).
        4. If yes and no existing ticket with a matching hash already exists,
           generate a new pending ticket.

        Returns the list of **newly** generated tickets.
        """
        if not staged_files:
            return []

        existing_tickets = self._load_tickets()
        existing_hashes: Dict[str, dict] = {
            t["file_path"]: t for t in existing_tickets
        }

        # Build task lookup
        task_map: Dict[str, dict] = {t["task_id"]: t for t in tasks}

        # Build requirement category lookup
        req_categories: Dict[str, str] = {}
        if requirements:
            for req in requirements:
                req_id = req.get("req_id", "") if isinstance(req, dict) else getattr(req, "req_id", "")
                category = req.get("category", "") if isinstance(req, dict) else getattr(req, "category", "")
                if req_id:
                    req_categories[req_id] = category

        new_tickets: List[dict] = []
        ticket_counter = len(existing_tickets) + 1

        for file_path in sorted(staged_files):
            # 1. Find covering claim
            covering_claim = None
            for claim in claims:
                if claim.get("claim_id", "").endswith("-9999"):
                    continue
                if file_path in claim.get("code_refs", []):
                    covering_claim = claim
                    break

            if covering_claim is None:
                continue

            # 2. Find linked task
            task_id = covering_claim.get("related_task", "")
            task = task_map.get(task_id)
            if task is None:
                continue

            # 3. Check category (task-level or via related requirements)
            is_quality_evolution = task.get("category") == "quality_evolution"
            if not is_quality_evolution:
                for req_id in task.get("related_requirements", []):
                    if req_categories.get(req_id) == "quality_evolution":
                        is_quality_evolution = True
                        break
            if not is_quality_evolution:
                continue

            # 4. Compute hash and check for existing ticket
            file_hash = self._compute_staged_file_hash(file_path)
            if file_hash is None:
                continue

            existing = existing_hashes.get(file_path)
            if existing is not None and existing.get("file_hash") == file_hash:
                # Ticket already covers this exact content -- skip
                continue

            # Collect AC IDs from the task
            ac_ids = task.get("related_acceptance_criteria", [])

            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            ticket_id = f"AUDIT-VT-{ticket_counter:03d}"
            ticket_counter += 1

            ticket = {
                "ticket_id": ticket_id,
                "file_path": file_path,
                "file_hash": file_hash,
                "task_id": task_id,
                "ac_ids": ac_ids,
                "status": "pending",
                "audit_reason": "",
                "created_at": now,
                "updated_at": now,
            }
            new_tickets.append(ticket)

        # Persist
        if new_tickets:
            self._save_tickets(existing_tickets + new_tickets)

        return new_tickets

    def verify_tickets(self, staged_files: Set[str]) -> Tuple[bool, str]:
        """Verify that all tickets for staged files have ``passed``.

        Checks:
        - ``status != "passed"`` -- BLOCKED.
        - ``audit_reason`` is empty -- BLOCKED.
        - ``file_hash`` does not match current staged content -- reset to
          *pending* and BLOCKED.

        Also cleans up archived tickets older than 48 hours.

        Returns ``(success, message)``.
        """
        tickets = self._load_tickets()
        if not tickets:
            return True, ""

        now = datetime.now(timezone.utc)
        cleaned: List[dict] = []
        for t in tickets:
            if t.get("status") == "archived":
                updated_at = t.get("updated_at", "")
                if updated_at:
                    try:
                        dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                        if now - dt > timedelta(hours=48):
                            continue  # drop expired archived ticket
                    except (ValueError, TypeError):
                        pass
            cleaned.append(t)
        tickets = cleaned

        issues: List[str] = []
        blocked = False
        for t in tickets:
            fp = t.get("file_path", "")
            if fp not in staged_files:
                continue

            status = t.get("status", "")
            reason = t.get("audit_reason", "")
            file_hash = t.get("file_hash", "")

            # Re-check hash
            current_hash = self._compute_staged_file_hash(fp)
            if current_hash is not None and current_hash != file_hash:
                t["status"] = "pending"
                t["file_hash"] = current_hash
                t["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                issues.append(f"Ticket {t['ticket_id']} for {fp}: file hash changed, reset to pending")
                blocked = True
                continue

            if status != "passed":
                issues.append(f"Ticket {t['ticket_id']} for {fp}: status is '{status}', expected 'passed'")
                blocked = True

            if not reason:
                issues.append(f"Ticket {t['ticket_id']} for {fp}: audit_reason is empty")
                blocked = True
            else:
                filename = Path(fp).name
                if len(reason) < 20:
                    issues.append(
                        f"Ticket {t['ticket_id']} for {fp}: audit_reason too short "
                        f"({len(reason)} chars, need >= 20)"
                    )
                    blocked = True
                if filename not in reason:
                    issues.append(
                        f"Ticket {t['ticket_id']} for {fp}: audit_reason does not "
                        f"contain filename '{filename}'"
                    )
                    blocked = True

        # Persist any hash resets
        self._save_tickets(tickets)

        if blocked:
            return False, "; ".join(issues)
        return True, ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_staged_file_hash(self, file_path: str) -> Optional[str]:
        """Compute SHA-256 of a staged file via ``git show :path``."""
        try:
            result = subprocess.run(
                ["git", "show", f":{file_path}"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True,
            )
            return "sha256:" + hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

    def _load_tickets(self) -> List[dict]:
        """Load tickets from ``.vibetracing/semantic_audit.json``."""
        try:
            with self.audit_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            return []
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_tickets(self, tickets: List[dict]) -> None:
        """Save tickets to ``.vibetracing/semantic_audit.json``."""
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("w", encoding="utf-8") as f:
            json.dump(tickets, f, indent=2, ensure_ascii=False)
