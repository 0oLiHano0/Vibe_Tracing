"""
Doctor command -- scan governance data health and report issues.
"""

import json
import time
import uuid

from pathlib import Path
from typing import Any, Dict, List, Set


def run_doctor(project_root: Path) -> int:
    """Run governance data health checks and output a JSON report.

    Checks:
      1. dangling_claims -- each claim's related_task exists in task_list.json
      2. file_refs_integrity -- each claim's code_refs and test_refs exist on disk
      3. requirement_mapping -- each task's related_requirements exist in the PRD
      4. ac_mapping -- each task's related_acceptance_criteria exist in the PRD
      5. machine_rule_coverage -- architecture rules with verification_method=="machine" have no obvious checker
    """
    # ---- 获取 main() 已初始化的日志实例；若直接调用（非 main 路径），则自动初始化 ----
    # 若日志初始化失败，doctor 仍须继续运行（LOG-VT-011 约束）
    vt_logger = None
    try:
        from vibe_tracing.infra.logging.logger import OperationalLogger
        vt_logger = OperationalLogger.get_or_init(
            run_id=f"DOCTOR-{uuid.uuid4()}", project_root=project_root,
        )
        vt_logger.info("doctor_start", "Doctor diagnostic scan started")
    except Exception:
        vt_logger = None

    _run_start_t = time.perf_counter()
    checks: List[Dict[str, Any]] = []

    # ---- Load governance data ----
    claims_dir = project_root / ".vibetracing" / "claims"
    task_list_path = project_root / "docs" / "task_list.json"
    prd_path = project_root / "docs" / "prd.md"
    constraints_path = project_root / "docs" / "architecture_constraints.json"
    evidences_dir = project_root / "output" / "evidences"
    test_results_path = evidences_dir / "test_results.json"
    coverage_reports_path = evidences_dir / "coverage_reports.json"

    # Load claims (tolerate missing files) - CLAIM-*.json directory mode
    import glob as glob_mod
    claims_data: List[Dict[str, Any]] = []
    _t = time.perf_counter()
    claim_files = sorted(glob_mod.glob(str(claims_dir / "CLAIM-*.json")))
    if claim_files:
        for fp in claim_files:
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    claims_data.extend(data)
                else:
                    claims_data.append(data)
            except Exception:
                continue
        if vt_logger:
            vt_logger.info("doctor_load", "Loaded claims from CLAIM-*.json files",
                           file="claims", result="pass",
                           path=str(claims_dir),
                           claims_count=len(claims_data),
                           duration_ms=int((time.perf_counter() - _t) * 1000))
    else:
        if vt_logger:
            vt_logger.info("doctor_load", "No CLAIM-*.json files found",
                           file="claims", result="warning",
                           path=str(claims_dir),
                           duration_ms=int((time.perf_counter() - _t) * 1000))

    # Load tasks
    tasks_data: List[Dict[str, Any]] = []
    _t = time.perf_counter()
    if task_list_path.exists():
        try:
            with task_list_path.open("r", encoding="utf-8") as f:
                tldata = json.load(f)
            tasks_data = tldata.get("tasks", []) if isinstance(tldata, dict) else []
            if vt_logger:
                vt_logger.info("doctor_load", "Loaded task list",
                               file="task_list", result="pass",
                               path=str(task_list_path),
                               tasks_count=len(tasks_data),
                               duration_ms=int((time.perf_counter() - _t) * 1000))
        except Exception as e:
            tasks_data = []
            if vt_logger:
                vt_logger.exception("doctor_load", "Failed to parse task list",
                                    exc=e, file="task_list", result="fail",
                                    path=str(task_list_path),
                                    duration_ms=int((time.perf_counter() - _t) * 1000))
    else:
        if vt_logger:
            vt_logger.info("doctor_load", "Task list not found",
                           file="task_list", result="warning",
                           path=str(task_list_path),
                           duration_ms=int((time.perf_counter() - _t) * 1000))

    # Load PRD requirement and AC IDs
    prd_req_ids: Set[str] = set()
    prd_ac_ids: Set[str] = set()
    _t = time.perf_counter()
    if prd_path.exists():
        try:
            from vibe_tracing.infra.loader.prd_parser import PrdParser
            prd_parser = PrdParser()
            prd_res = prd_parser.parse_text(prd_path.read_text(encoding="utf-8"))
            for req in prd_res.requirements:
                prd_req_ids.add(req.req_id)
                for ac in req.acceptance_criteria:
                    prd_ac_ids.add(ac.ac_id)
            if vt_logger:
                vt_logger.info("doctor_load", "Loaded and parsed PRD",
                               file="prd", result="pass",
                               path=str(prd_path),
                               requirements_count=len(prd_req_ids),
                               ac_count=len(prd_ac_ids),
                               duration_ms=int((time.perf_counter() - _t) * 1000))
        except Exception as e:
            if vt_logger:
                vt_logger.exception("doctor_load", "Failed to parse PRD",
                                    exc=e, file="prd", result="fail",
                                    path=str(prd_path),
                                    duration_ms=int((time.perf_counter() - _t) * 1000))
    else:
        if vt_logger:
            vt_logger.info("doctor_load", "PRD file not found",
                           file="prd", result="warning",
                           path=str(prd_path),
                           duration_ms=int((time.perf_counter() - _t) * 1000))

    # Load architecture constraints
    constraints_data: Dict[str, Any] = {}
    _t = time.perf_counter()
    if constraints_path.exists():
        try:
            with constraints_path.open("r", encoding="utf-8") as f:
                constraints_data = json.load(f)
            if vt_logger:
                vt_logger.info("doctor_load", "Loaded architecture constraints",
                               file="constraints", result="pass",
                               path=str(constraints_path),
                               duration_ms=int((time.perf_counter() - _t) * 1000))
        except Exception as e:
            constraints_data = {}
            if vt_logger:
                vt_logger.exception("doctor_load", "Failed to parse constraints",
                                    exc=e, file="constraints", result="fail",
                                    path=str(constraints_path),
                                    duration_ms=int((time.perf_counter() - _t) * 1000))
    else:
        if vt_logger:
            vt_logger.info("doctor_load", "Constraints file not found",
                           file="constraints", result="warning",
                           path=str(constraints_path),
                           duration_ms=int((time.perf_counter() - _t) * 1000))

    # Load test results from evidences/ directory
    test_results_data: Dict[str, Any] = {}
    _t = time.perf_counter()
    if test_results_path.exists():
        try:
            with test_results_path.open("r", encoding="utf-8") as f:
                test_results_data = json.load(f)
            if vt_logger:
                vt_logger.info("doctor_load", "Loaded test results",
                               file="test_results", result="pass",
                               path=str(test_results_path),
                               duration_ms=int((time.perf_counter() - _t) * 1000))
        except Exception as e:
            test_results_data = {}
            if vt_logger:
                vt_logger.exception("doctor_load", "Failed to parse test results",
                                    exc=e, file="test_results", result="fail",
                                    path=str(test_results_path),
                                    duration_ms=int((time.perf_counter() - _t) * 1000))
    else:
        if vt_logger:
            vt_logger.info("doctor_load", "Test results not found",
                           file="test_results", result="warning",
                           path=str(test_results_path),
                           duration_ms=int((time.perf_counter() - _t) * 1000))

    # Load coverage reports from evidences/ directory
    coverage_reports_data: Dict[str, Any] = {}
    _t = time.perf_counter()
    if coverage_reports_path.exists():
        try:
            with coverage_reports_path.open("r", encoding="utf-8") as f:
                coverage_reports_data = json.load(f)
            if vt_logger:
                vt_logger.info("doctor_load", "Loaded coverage reports",
                               file="coverage_reports", result="pass",
                               path=str(coverage_reports_path),
                               duration_ms=int((time.perf_counter() - _t) * 1000))
        except Exception as e:
            coverage_reports_data = {}
            if vt_logger:
                vt_logger.exception("doctor_load", "Failed to parse coverage reports",
                                    exc=e, file="coverage_reports", result="fail",
                                    path=str(coverage_reports_path),
                                    duration_ms=int((time.perf_counter() - _t) * 1000))
    else:
        if vt_logger:
            vt_logger.info("doctor_load", "Coverage reports not found",
                           file="coverage_reports", result="warning",
                           path=str(coverage_reports_path),
                           duration_ms=int((time.perf_counter() - _t) * 1000))

    # ---- Check 1: dangling_claims ----
    _t = time.perf_counter()
    issues_dc: List[Dict[str, Any]] = []
    # Load task IDs from task_list.json
    task_ids = set()
    task_list_path_check = project_root / "docs" / "task_list.json"
    if task_list_path_check.is_file():
        try:
            task_data = json.loads(task_list_path_check.read_text(encoding="utf-8"))
            if isinstance(task_data, dict):
                task_ids = {t.get("task_id") for t in task_data.get("tasks", []) if t.get("task_id")}
        except (json.JSONDecodeError, OSError):
            pass
    for claim in claims_data:
        related_task = claim.get("related_task", "")
        if related_task and related_task not in task_ids:
            issues_dc.append({
                "claim_id": claim.get("claim_id", ""),
                "related_task": related_task,
                "message": f"Claim references task '{related_task}' not found in task_list.json",
            })
    checks.append({"name": "dangling_claims", "issues": issues_dc})
    if vt_logger:
        vt_logger.info("doctor_check", "Dangling claims check",
                       check="dangling_claims",
                       result="pass" if not issues_dc else "fail",
                       issues_count=len(issues_dc),
                       claims_checked=len(claims_data),
                       duration_ms=int((time.perf_counter() - _t) * 1000))

    # ---- Check 2: file_refs_integrity ----
    _t = time.perf_counter()
    issues_2: List[Dict[str, Any]] = []
    for claim in claims_data:
        claim_id = claim.get("claim_id", "")
        for ref_type in ("code_refs", "test_refs"):
            for ref in claim.get(ref_type, []):
                # Strip fragment identifiers (e.g., "#L1-L10")
                path_part = ref.split("#")[0]
                if not path_part:
                    continue
                ref_path = project_root / path_part
                if not ref_path.exists():
                    issues_2.append({
                        "claim_id": claim_id,
                        "ref_type": ref_type,
                        "ref": ref,
                        "message": f"Referenced file '{path_part}' does not exist on disk",
                    })
    checks.append({"name": "file_refs_integrity", "issues": issues_2})
    if vt_logger:
        vt_logger.info("doctor_check", "File refs integrity check",
                       check="file_refs_integrity",
                       result="pass" if not issues_2 else "fail",
                       issues_count=len(issues_2),
                       claims_checked=len(claims_data),
                       duration_ms=int((time.perf_counter() - _t) * 1000))

    # ---- Check 3: requirement_mapping ----
    _t = time.perf_counter()
    issues_3: List[Dict[str, Any]] = []
    for task in tasks_data:
        task_id = task.get("task_id", "")
        for req_id in task.get("related_requirements", []):
            if req_id not in prd_req_ids:
                issues_3.append({
                    "task_id": task_id,
                    "requirement_id": req_id,
                    "message": f"Requirement '{req_id}' referenced by task '{task_id}' not found in PRD",
                })
    checks.append({"name": "requirement_mapping", "issues": issues_3})
    if vt_logger:
        vt_logger.info("doctor_check", "Requirement mapping check",
                       check="requirement_mapping",
                       result="pass" if not issues_3 else "fail",
                       issues_count=len(issues_3),
                       tasks_checked=len(tasks_data),
                       duration_ms=int((time.perf_counter() - _t) * 1000))

    # ---- Check 4: ac_mapping ----
    _t = time.perf_counter()
    issues_4: List[Dict[str, Any]] = []
    for task in tasks_data:
        task_id = task.get("task_id", "")
        for ac_id in task.get("related_acceptance_criteria", []):
            if ac_id not in prd_ac_ids:
                issues_4.append({
                    "task_id": task_id,
                    "ac_id": ac_id,
                    "message": f"AC '{ac_id}' referenced by task '{task_id}' not found in PRD",
                })
    checks.append({"name": "ac_mapping", "issues": issues_4})
    if vt_logger:
        vt_logger.info("doctor_check", "AC mapping check",
                       check="ac_mapping",
                       result="pass" if not issues_4 else "fail",
                       issues_count=len(issues_4),
                       tasks_checked=len(tasks_data),
                       duration_ms=int((time.perf_counter() - _t) * 1000))

    # ---- Check 5: machine_rule_coverage ----
    _t = time.perf_counter()
    issues_5: List[Dict[str, Any]] = []
    if constraints_data:
        # Collect all module_ids from module_boundaries for heuristic matching
        module_ids: Set[str] = set()
        for mod in constraints_data.get("module_boundaries", []):
            mid = mod.get("module_id", "")
            if mid:
                module_ids.add(mid)

        # Dynamically iterate all list-type keys for machine rules
        for key, value in constraints_data.items():
            if not isinstance(value, list):
                continue
            for rule in value:
                if not isinstance(rule, dict):
                    continue
                if rule.get("verification_method") != "machine":
                    continue
                rule_id = (
                    rule.get("rule_id")
                    or rule.get("principle_id")
                    or rule.get("constraint_id")
                    or rule.get("pattern_id")
                    or rule.get("gate_id")
                    or rule.get("contract_id")
                    or "unknown"
                )
                # Heuristic: if the rule references a module that exists in
                # module_boundaries, assume there *may* be a checker.  Otherwise
                # flag it.  Also check for common verification keywords.
                related_modules = rule.get("related_modules", [])
                has_module_support = any(m in module_ids for m in related_modules)

                # Check for explicit checker references
                has_checker = has_module_support or bool(
                    rule.get("checker") or rule.get("verification_command")
                )

                if not has_checker:
                    issues_5.append({
                        "rule_id": rule_id,
                        "section": key,
                        "message": (
                            f"Rule '{rule_id}' in '{key}' has verification_method=machine "
                            "but no obvious checker implementation found"
                        ),
                    })
    checks.append({"name": "machine_rule_coverage", "issues": issues_5})
    if vt_logger:
        vt_logger.info("doctor_check", "Machine rule coverage check",
                       check="machine_rule_coverage",
                       result="pass" if not issues_5 else "warning",
                       issues_count=len(issues_5),
                       constraints_loaded=bool(constraints_data),
                       duration_ms=int((time.perf_counter() - _t) * 1000))

    # ---- Assemble report ----
    total_issues = sum(len(c["issues"]) for c in checks)
    report = {
        "checks": checks,
        "total_issues": total_issues,
    }

    # ---- Log summary and end ----
    if vt_logger:
        check_summary = {}
        for c in checks:
            name = c["name"]
            issue_count = len(c["issues"])
            check_summary[name] = "pass" if issue_count == 0 else "fail"
        total_duration_ms = int((time.perf_counter() - _run_start_t) * 1000)
        vt_logger.info("doctor_end", "Doctor diagnostic scan completed",
                       total_checks=len(checks),
                       total_issues=total_issues,
                       check_summary=check_summary,
                       total_duration_ms=total_duration_ms)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0
