"""
Doctor command -- scan governance data health and report issues.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set


def run_doctor(project_root: Path) -> int:
    """Run governance data health checks and output a JSON report.

    Checks:
      1. evidence_refs_integrity -- each claim's evidence_refs exist in evidence index or on disk
      2. file_refs_integrity -- each claim's code_refs and test_refs exist on disk
      3. requirement_mapping -- each task's related_requirements exist in the PRD
      4. ac_mapping -- each task's related_acceptance_criteria exist in the PRD
      5. machine_rule_coverage -- architecture rules with verification_method=="machine" have no obvious checker
    """
    checks: List[Dict[str, Any]] = []

    # ---- Load governance data ----
    claims_path = project_root / ".vibetracing" / "claims" / "current.json"
    task_list_path = project_root / "docs" / "task_list.json"
    prd_path = project_root / "docs" / "prd.md"
    constraints_path = project_root / "docs" / "architecture_constraints.json"
    evidence_index_path = project_root / "output" / "evidence_index.json"

    # Load claims (tolerate missing files)
    claims_data: List[Dict[str, Any]] = []
    if claims_path.exists():
        try:
            with claims_path.open("r", encoding="utf-8") as f:
                claims_data = json.load(f)
            if not isinstance(claims_data, list):
                claims_data = []
        except Exception:
            claims_data = []

    # Load tasks
    tasks_data: List[Dict[str, Any]] = []
    if task_list_path.exists():
        try:
            with task_list_path.open("r", encoding="utf-8") as f:
                tldata = json.load(f)
            tasks_data = tldata.get("tasks", []) if isinstance(tldata, dict) else []
        except Exception:
            tasks_data = []

    # Load PRD requirement and AC IDs
    prd_req_ids: Set[str] = set()
    prd_ac_ids: Set[str] = set()
    if prd_path.exists():
        try:
            from vibe_tracing.prd_parser import PrdParser
            prd_parser = PrdParser()
            prd_res = prd_parser.parse_file(prd_path)
            for req in prd_res.requirements:
                prd_req_ids.add(req.req_id)
                for ac in req.acceptance_criteria:
                    prd_ac_ids.add(ac.ac_id)
        except Exception:
            pass

    # Load architecture constraints
    constraints_data: Dict[str, Any] = {}
    if constraints_path.exists():
        try:
            with constraints_path.open("r", encoding="utf-8") as f:
                constraints_data = json.load(f)
        except Exception:
            constraints_data = {}

    # Load evidence index (optional)
    evidence_index: Dict[str, Any] = {}
    if evidence_index_path.exists():
        try:
            with evidence_index_path.open("r", encoding="utf-8") as f:
                evidence_index = json.load(f)
        except Exception:
            evidence_index = {}

    # Collect all evidence_ids from the index
    evidence_ids_in_index: Set[str] = set()
    for ev in evidence_index.get("evidences", []):
        eid = ev.get("evidence_id", "")
        if eid:
            evidence_ids_in_index.add(eid)

    # ---- Check 1: evidence_refs_integrity ----
    issues_1: List[Dict[str, Any]] = []
    for claim in claims_data:
        claim_id = claim.get("claim_id", "")
        for ref in claim.get("evidence_refs", []):
            # Check if the ref is in the evidence index
            if ref in evidence_ids_in_index:
                continue
            # Check if a file with that name exists on disk
            ref_path = project_root / ref
            if ref_path.exists():
                continue
            issues_1.append({
                "claim_id": claim_id,
                "evidence_ref": ref,
                "message": f"Evidence ref '{ref}' not found in evidence index or on disk",
            })
    checks.append({"name": "evidence_refs_integrity", "issues": issues_1})

    # ---- Check 2: file_refs_integrity ----
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

    # ---- Check 3: requirement_mapping ----
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

    # ---- Check 4: ac_mapping ----
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

    # ---- Check 5: machine_rule_coverage ----
    issues_5: List[Dict[str, Any]] = []
    if constraints_data:
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
        # Collect all module_ids from module_boundaries for heuristic matching
        module_ids: Set[str] = set()
        for mod in constraints_data.get("module_boundaries", []):
            mid = mod.get("module_id", "")
            if mid:
                module_ids.add(mid)

        for key in rule_keys:
            for rule in constraints_data.get(key, []):
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

    # ---- Assemble report ----
    total_issues = sum(len(c["issues"]) for c in checks)
    report = {
        "checks": checks,
        "total_issues": total_issues,
    }

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0
