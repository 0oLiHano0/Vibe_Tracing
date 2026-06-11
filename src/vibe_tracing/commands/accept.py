"""
Accept command -- accept a manual architecture constraint rule.
"""

import json
import sys
from pathlib import Path


def run_accept(project_root: Path, rule_id: str, accepted_by: str = "human") -> int:
    """Accept a manual architecture constraint rule.

    Reads architecture_constraints.json, finds the rule by rule_id across
    all sections, sets ``accepted_by`` and ``accepted_at``, and writes back.
    """
    import datetime

    constraints_path = project_root / "docs" / "architecture_constraints.json"
    if not constraints_path.exists():
        print(f"Error: {constraints_path} not found.", file=sys.stderr)
        return 1

    try:
        with constraints_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"Error reading {constraints_path}: {exc}", file=sys.stderr)
        return 1

    # All rule array keys to search
    rule_keys = [
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

    found = False
    for key in rule_keys:
        for rule in data.get(key, []):
            r_id = (
                rule.get("rule_id")
                or rule.get("principle_id")
                or rule.get("constraint_id")
                or rule.get("pattern_id")
                or rule.get("gate_id")
                or rule.get("contract_id")
            )
            if r_id == rule_id:
                # Check if already accepted
                if rule.get("accepted_by"):
                    print(
                        f"Rule {rule_id} is already accepted by "
                        f"{rule['accepted_by']} at {rule.get('accepted_at', 'N/A')}."
                    )
                    return 0

                # Set acceptance fields
                rule["accepted_by"] = accepted_by
                rule["accepted_at"] = datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat()
                found = True
                break
        if found:
            break

    if not found:
        print(
            f"Error: Rule {rule_id} not found in architecture_constraints.json.",
            file=sys.stderr,
        )
        return 1

    # Write back
    try:
        with constraints_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except Exception as exc:
        print(f"Error writing {constraints_path}: {exc}", file=sys.stderr)
        return 1

    print(
        f"Rule {rule_id} accepted by '{accepted_by}' at "
        f"{rule['accepted_at']}."
    )
    return 0
