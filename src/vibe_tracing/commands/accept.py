"""
Accept command -- accept a manual architecture constraint rule.
"""

import datetime
import json
import sys
from pathlib import Path


def run_accept(project_root: Path, rule_id: str, accepted_by: str = "human") -> int:
    """Accept a manual architecture constraint rule.

    Reads architecture_constraints.json to locate the rule by rule_id across
    all sections, checks that ``verification_method`` is ``"manual"``, then
    records the acceptance decision in ``.vibetracing/human_decisions.json``.

    The constraints file is **never** modified by this function.
    """
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

    found_rule = None
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
                found_rule = rule
                break
        if found_rule is not None:
            break

    if found_rule is None:
        print(
            f"Error: Rule {rule_id} not found in architecture_constraints.json.",
            file=sys.stderr,
        )
        return 1

    # Check verification_method -- only "manual" rules can be accepted
    verification = found_rule.get("verification_method", "machine")
    if verification != "manual":
        print(
            f"Error: Rule {rule_id} verification_method is '{verification}', "
            f"requires programmatic verification and cannot be accepted manually.",
            file=sys.stderr,
        )
        return 1

    # Load existing human_decisions.json
    decisions_path = project_root / ".vibetracing" / "human_decisions.json"
    existing_decisions: list = []
    if decisions_path.exists():
        try:
            existing_data = json.loads(decisions_path.read_text(encoding="utf-8"))
            existing_decisions = existing_data.get("decisions", [])
        except (json.JSONDecodeError, OSError):
            existing_decisions = []

    # Check if already accepted
    for d in existing_decisions:
        if (
            d.get("category") == "accepted_rule"
            and d.get("targetId") == rule_id
            and d.get("action") == "accept"
        ):
            print(f"Rule {rule_id} has already been accepted.")
            return 0

    # Compute next decision_id
    next_id = 1
    if existing_decisions:
        max_id = max((e.get("decision_id", 0) for e in existing_decisions), default=0)
        next_id = max_id + 1

    # Build new entry
    entry = {
        "decision_id": next_id,
        "category": "accepted_rule",
        "targetId": rule_id,
        "action": "accept",
        "reason": "",
        "decidedBy": accepted_by,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }
    existing_decisions.append(entry)

    # Ensure parent directory exists
    decisions_path.parent.mkdir(parents=True, exist_ok=True)

    # Write human_decisions.json
    output = {"version": "1.0", "decisions": existing_decisions}
    try:
        decisions_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"Error writing {decisions_path}: {exc}", file=sys.stderr)
        return 1

    print(
        f"Rule {rule_id} accepted by '{accepted_by}' at {entry['timestamp']}."
    )
    return 0
