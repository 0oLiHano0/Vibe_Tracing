"""
One-time migration: extract inline ``accepted_by`` / ``accepted_at`` from
``architecture_constraints.json`` and write them as ``accepted_rule`` entries in
``human_decisions.json``.

Idempotent — safe to run multiple times.
"""

import datetime
import json
import sys
from typing import List, Optional
from pathlib import Path

# All rule-array keys that may contain rules with inline accepted_by.
_RULE_KEYS = [
    "architecture_principles",
    "module_boundaries",
    "dependency_rules",
    "data_flow_rules",
    "storage_rules",
    "error_handling_rules",
    "logging_rules",
    "security_rules",
    "technology_constraints",
    "forbidden_patterns",
    "quality_gates",
    "interface_contracts",
    "performance_constraints",
    "deployment_constraints",
    "test_constraints",
]


def _extract_id(rule: dict) -> Optional[str]:
    """Extract the canonical rule ID from a rule dict.

    Different arrays use different key names for the identifier field.
    Returns the first match found, or *None* if none is present.
    """
    for field in (
        "rule_id",
        "principle_id",
        "module_id",
        "constraint_id",
        "pattern_id",
        "gate_id",
        "contract_id",
    ):
        val = rule.get(field)
        if val:
            return val
    return None


def _build_decision_entry(
    rule_id: str,
    existing_decisions: List[dict],
    accepted_by: str,
    accepted_at: Optional[str],
) -> dict:
    """Create a single ``accepted_rule`` decision dict.

    ``decision_id`` is derived from the maximum existing id + 1 (or 1 if empty).
    """
    next_id = 1
    if existing_decisions:
        max_id = max(
            (e.get("decision_id", 0) for e in existing_decisions),
            default=0,
        )
        next_id = max_id + 1

    if not accepted_at:
        accepted_at = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    return {
        "decision_id": next_id,
        "category": "accepted_rule",
        "targetId": rule_id,
        "action": "accept",
        "reason": "",
        "decidedBy": accepted_by,
        "timestamp": accepted_at,
    }


def run_migrate(project_root: Path) -> int:
    """Execute the migration. Returns 0 on success, 1 on failure."""
    # ------------------------------------------------------------------
    # 1. Read architecture_constraints.json
    # ------------------------------------------------------------------
    constraints_path = project_root / "docs" / "architecture_constraints.json"
    if not constraints_path.exists():
        print(
            f"Error: {constraints_path} not found.",
            file=sys.stderr,
        )
        return 1

    try:
        with constraints_path.open("r", encoding="utf-8") as f:
            constraints = json.load(f)
    except Exception as exc:
        print(
            f"Error reading {constraints_path}: {exc}",
            file=sys.stderr,
        )
        return 1

    # ------------------------------------------------------------------
    # 2. Read existing human_decisions.json (create if absent)
    # ------------------------------------------------------------------
    decisions_path = project_root / ".vibetracing" / "human_decisions.json"
    existing_decisions: list[dict] = []
    decisions_version = "1.0"
    if decisions_path.exists():
        try:
            with decisions_path.open("r", encoding="utf-8") as f:
                decisions_data = json.load(f)
            existing_decisions = decisions_data.get("decisions", [])
            decisions_version = decisions_data.get("version", "1.0")
        except Exception as exc:
            print(
                f"Warning: Could not read {decisions_path}: {exc}. "
                "Will create new file.",
                file=sys.stderr,
            )
            existing_decisions = []

    # Build a set of already-migrated target ids for fast idempotency checking.
    migrated_target_ids: set[str] = {
        e["targetId"]
        for e in existing_decisions
        if e.get("category") == "accepted_rule" and e.get("targetId")
    }

    # ------------------------------------------------------------------
    # 3. Walk arrays and collect migrations
    # ------------------------------------------------------------------
    new_entries: list[dict] = []

    for key in _RULE_KEYS:
        rules = constraints.get(key, [])
        if not isinstance(rules, list):
            continue  # skip unexpected non-list values

        for rule in rules:
            if not isinstance(rule, dict):
                continue

            accepted_by = rule.get("accepted_by")
            if not accepted_by:
                continue  # only migrate rules with an inline accepted_by

            rule_id = _extract_id(rule)
            if not rule_id:
                continue  # skip malformed rules (shouldn't happen)

            # Idempotency: skip if already migrated.
            if rule_id in migrated_target_ids:
                # Still strip inline fields so the constraints file is clean.
                rule.pop("accepted_by", None)
                rule.pop("accepted_at", None)
                continue

            accepted_at = rule.get("accepted_at")
            entry = _build_decision_entry(
                rule_id, existing_decisions, accepted_by, accepted_at
            )
            new_entries.append(entry)
            existing_decisions.append(entry)

            # Track in the set so subsequent duplicates within the same run
            # are skipped.
            migrated_target_ids.add(rule_id)

            # Strip inline fields from the rule dict.
            rule.pop("accepted_by", None)
            rule.pop("accepted_at", None)

    # ------------------------------------------------------------------
    # 4. Write back human_decisions.json
    # ------------------------------------------------------------------
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    output_decisions = {
        "version": decisions_version,
        "decisions": existing_decisions,
    }
    decisions_path.write_text(
        json.dumps(output_decisions, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # ------------------------------------------------------------------
    # 5. Write back architecture_constraints.json (cleaned)
    # ------------------------------------------------------------------
    constraints_path.write_text(
        json.dumps(constraints, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # ------------------------------------------------------------------
    # 6. Summary
    # ------------------------------------------------------------------
    if new_entries:
        for entry in new_entries:
            print(
                f"  Migrated: {entry['targetId']} ← "
                f"'{entry['decidedBy']}' @ {entry['timestamp']}"
            )
        print(f"\nMigrated {len(new_entries)} rule(s).")
    else:
        print("No new rules to migrate (idempotent run).")

    # Verify no accepted_by/accepted_at remain.
    remaining = 0
    for key in _RULE_KEYS:
        for rule in constraints.get(key, []):
            if isinstance(rule, dict) and (
                "accepted_by" in rule or "accepted_at" in rule
            ):
                remaining += 1

    if remaining > 0:
        print(
            f"Warning: {remaining} rule(s) still have inline fields.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    project_root = Path.cwd()
    if len(sys.argv) > 1:
        project_root = Path(sys.argv[1]).resolve()
    sys.exit(run_migrate(project_root))
