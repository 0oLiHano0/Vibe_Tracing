"""
Accept command -- accept a manual architecture constraint rule.
"""

import datetime
import json
import sys
import time
import uuid

from pathlib import Path


def run_accept(project_root: Path, rule_id: str, accepted_by: str = "human") -> int:
    """Accept a manual architecture constraint rule.

    Reads architecture_constraints.json to locate the rule by rule_id across
    all sections, checks that ``verification_method`` is ``"manual"``, then
    records the acceptance decision in ``.vibetracing/human_decisions.json``.

    The constraints file is **never** modified by this function.
    """
    # 获取 main() 已初始化的日志实例；若直接调用（非 main 路径），则自动初始化
    # 若日志初始化失败，accept 仍须继续运行（LOG-VT-011 约束）
    vt_logger = None
    try:
        from vibe_tracing.infra.logging.logger import OperationalLogger
        vt_logger = OperationalLogger.get_or_init(
            run_id=f"ACCEPT-{uuid.uuid4()}", project_root=project_root,
        )
        vt_logger.info("run_start", "Accept command started",
                       rule_id=rule_id, accepted_by=accepted_by,
                       project_root=str(project_root))
    except Exception:
        vt_logger = None

    _run_start_t = time.perf_counter()

    constraints_path = project_root / "docs" / "architecture_constraints.json"
    if not constraints_path.exists():
        print(f"Error: {constraints_path} not found.", file=sys.stderr)
        if vt_logger:
            vt_logger.error("accept_error", "Constraints file not found",
                            path=str(constraints_path))
        return 1

    try:
        _t_step = time.perf_counter()
        with constraints_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if vt_logger:
            vt_logger.info("accept_step", "Loaded architecture constraints",
                           path=str(constraints_path),
                           duration_ms=int((time.perf_counter() - _t_step) * 1000),
                           sections=len(data))
    except Exception as exc:
        print(f"Error reading {constraints_path}: {exc}", file=sys.stderr)
        if vt_logger:
            vt_logger.exception("accept_error", "Failed to read constraints file",
                                exc=exc, path=str(constraints_path))
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
        if vt_logger:
            vt_logger.warning("accept_validation", "Rule not found",
                              rule_id=rule_id, searched_keys=len(rule_keys))
        return 1

    if vt_logger:
        vt_logger.info("accept_step", "Rule found in constraints",
                       rule_id=rule_id,
                       verification_method=found_rule.get("verification_method", "machine"),
                       description=found_rule.get("description", "")[:200])

    # Check verification_method -- only "manual" rules can be accepted
    verification = found_rule.get("verification_method", "machine")
    if verification != "manual":
        print(
            f"Error: Rule {rule_id} verification_method is '{verification}', "
            f"requires programmatic verification and cannot be accepted manually.",
            file=sys.stderr,
        )
        if vt_logger:
            vt_logger.warning("accept_validation",
                              "Rule rejected: verification_method is not manual",
                              rule_id=rule_id, verification_method=verification)
        return 1

    # Load existing human_decisions.json
    decisions_path = project_root / ".vibetracing" / "human_decisions.json"
    existing_decisions: list = []
    if decisions_path.exists():
        try:
            existing_data = json.loads(decisions_path.read_text(encoding="utf-8"))
            existing_decisions = existing_data.get("decisions", [])
            if vt_logger:
                vt_logger.debug("accept_step", "Loaded existing human decisions",
                                path=str(decisions_path),
                                existing_count=len(existing_decisions))
        except (json.JSONDecodeError, OSError) as exc:
            existing_decisions = []
            if vt_logger:
                vt_logger.warning("accept_step", "Could not parse human_decisions.json",
                                  path=str(decisions_path))

    # Check if already accepted
    for d in existing_decisions:
        if (
            d.get("category") == "accepted_rule"
            and d.get("targetId") == rule_id
            and d.get("action") == "accept"
        ):
            print(f"Rule {rule_id} has already been accepted.")
            if vt_logger:
                total_ms = int((time.perf_counter() - _run_start_t) * 1000)
                vt_logger.info("run_end", "Accept completed (already accepted)",
                               rule_id=rule_id, accepted_by=accepted_by,
                               already_accepted=True,
                               total_duration_ms=total_ms)
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
        _t_step = time.perf_counter()
        decisions_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if vt_logger:
            vt_logger.info("accept_step", "Wrote human_decisions.json",
                           path=str(decisions_path),
                           decision_id=next_id,
                           total_decisions=len(existing_decisions),
                           duration_ms=int((time.perf_counter() - _t_step) * 1000))
    except Exception as exc:
        print(f"Error writing {decisions_path}: {exc}", file=sys.stderr)
        if vt_logger:
            vt_logger.exception("accept_error", "Failed to write human_decisions.json",
                                exc=exc, path=str(decisions_path),
                                rule_id=rule_id)
        return 1

    print(
        f"Rule {rule_id} accepted by '{accepted_by}' at {entry['timestamp']}."
    )
    if vt_logger:
        total_ms = int((time.perf_counter() - _run_start_t) * 1000)
        vt_logger.info("accept_rule", "Architecture rule accepted",
                       rule_id=rule_id, accepted_by=accepted_by,
                       decision_id=next_id, reason=entry.get("reason", "")[:200],
                       timestamp=entry["timestamp"])
        vt_logger.info("run_end", "Accept command completed",
                       rule_id=rule_id, accepted_by=accepted_by,
                       decision_id=next_id,
                       total_duration_ms=total_ms, exit_code=0)
    return 0
