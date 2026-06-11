"""
Analyzer execution, claim tests, and claims archival.
"""

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from vibe_tracing.context import UnifiedContext
from vibe_tracing.commands.common import _determine_affected_items
from vibe_tracing.commands.analyze.tools import _check_staged_extensions


def _run_analyzers(
    ctx: UnifiedContext,
    evidence_list: list,
    project_root: Path,
    staged_files: Optional[Set[str]] = None,
) -> Tuple[list, list, Optional[dict], dict, dict]:
    """Run all analyzers and return (merged_gaps, final_risks, compliance_res, claim_res, req_res)."""
    from vibe_tracing.architecture_compliance_checker import ArchitectureComplianceChecker
    from vibe_tracing.traceability.requirement_task_analyzer import RequirementTaskAnalyzer
    from vibe_tracing.traceability.ac_test_analyzer import AcTestAnalyzer
    from vibe_tracing.traceability.claim_evidence_analyzer import ClaimEvidenceAnalyzer
    from vibe_tracing.risk_advisor import RiskAdvisor

    prd_res = ctx.prd
    claims_list = ctx.claims_list

    req_analyzer = RequirementTaskAnalyzer()
    req_res = req_analyzer.analyze(prd_res.requirements, evidence_list)
    req_gaps = req_res.get("gaps", [])

    ac_analyzer = AcTestAnalyzer()
    ac_res = ac_analyzer.analyze(prd_res.requirements, evidence_list)
    ac_gaps = ac_res.get("gaps", [])

    claim_analyzer = ClaimEvidenceAnalyzer(project_root)
    claim_res = claim_analyzer.analyze(claims_list, evidence_list)
    claim_gaps = claim_res.get("gaps", [])
    claim_risks = claim_res.get("risks", [])

    # Merge gaps
    seen_gaps = set()
    merged_gaps = []
    for gap in req_gaps + ac_gaps + claim_gaps:
        key = (gap.get("item_id"), gap.get("item_type"))
        if key not in seen_gaps:
            seen_gaps.add(key)
            merged_gaps.append(gap)

    # Architecture compliance check
    compliance_res = None
    constraints_path = project_root / "docs" / "architecture_constraints.json"
    if constraints_path.exists() and ctx.constraints is not None:
        # Extract pre-computed hash from manifest to avoid re-reading file
        _constraints_hash = None
        if ctx.manifest:
            for _r in ctx.manifest.inputs_used:
                if _r.file_key == "architecture_constraints" and _r.sha256_hash:
                    _constraints_hash = _r.sha256_hash
                    break
        compliance_checker = ArchitectureComplianceChecker(
            project_root,
            constraints_path=constraints_path,
            constraints_hash=_constraints_hash,
            config_data=ctx.config,
        )
        compliance_res = compliance_checker.check(
            evidence_list, constraints_data=ctx.constraints
        )

    # Risk Advisor
    risk_advisor = RiskAdvisor(project_root)
    final_risks = risk_advisor.generate_risks(
        gaps=merged_gaps,
        claims_analysis=claim_res.get("claims_analysis", []),
        claim_risks=claim_risks,
        compliance_result=compliance_res,
        claims_list=claims_list,
    )

    if compliance_res:
        final_risks.extend(compliance_res.get("proposal_risks", []))
        for gap in compliance_res.get("proposal_gaps", []):
            key = (gap.get("item_id"), gap.get("item_type"))
            if key not in seen_gaps:
                seen_gaps.add(key)
                merged_gaps.append(gap)

    # ------------------------------------------------------------------
    # Incremental staleness tracking: mark gaps / risks from unchanged
    # items as ``stale`` so that gate evaluation can skip them while the
    # report still includes them for full visibility.
    # ------------------------------------------------------------------
    has_staged = staged_files is not None and len(staged_files) > 0
    if has_staged and staged_files is not None:
        affected_claims, affected_reqs, affected_acs = _determine_affected_items(
            staged_files, claims_list, ctx,
        )

        for gap in merged_gaps:
            item_type = gap.get("item_type")
            item_id = gap.get("item_id")
            if item_type == "claim" and item_id not in affected_claims:
                gap["stale"] = True
            elif item_type == "requirement" and item_id not in affected_reqs:
                gap["stale"] = True
            elif item_type == "ac" and item_id not in affected_acs:
                gap["stale"] = True

        for risk in final_risks:
            claim_id = risk.get("claim_id")
            if claim_id is not None and claim_id not in affected_claims:
                risk["stale"] = True

        stale_gap_count = sum(1 for g in merged_gaps if g.get("stale"))
        stale_risk_count = sum(1 for r in final_risks if r.get("stale"))
        if stale_gap_count > 0 or stale_risk_count > 0:
            print(f"  Note: {stale_gap_count} gaps and {stale_risk_count} risks from unchanged files (marked stale).", file=sys.stderr)

    # Staged file extension coverage check (WARNING only)
    _check_staged_extensions(project_root, ctx.constraints, ctx.config.get("language"))

    return merged_gaps, final_risks, compliance_res, claim_res, req_res


def _load_human_decisions() -> dict:
    """Read human decision log."""
    decisions_path = Path(".vibetracing/human_decisions.json")
    if not decisions_path.exists():
        return {"version": "1.0", "decisions": []}
    try:
        return json.loads(decisions_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": "1.0", "decisions": []}


def _result_hash(entry: dict) -> str:
    """Compute a stable hash of a test result entry (excluding cache metadata)."""
    cache_keys = {"last_run_time", "file_mtime", "result_hash"}
    content = {k: v for k, v in entry.items() if k not in cache_keys}
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]


def _run_claim_tests(project_root: Path, claims_list: list, evidence_index: dict) -> dict:
    """Run pytest for each Claim's test_refs and write results into evidence_index.

    Uses incremental caching: if a test file's mtime has not changed since the
    last run, the cached result from ``evidence_index["test_results"]`` is reused
    instead of re-running pytest.

    Args:
        project_root: The workspace root path.
        claims_list: List of Claim objects (each with a ``test_refs`` attribute).
        evidence_index: The current evidence index dict (mutated in place).

    Returns:
        The updated evidence_index with a new ``test_results`` field.
    """
    # Collect unique test_refs across all claims
    all_test_refs: Set[str] = set()
    for claim in claims_list:
        for ref in getattr(claim, "test_refs", []) or []:
            path_part = ref.split("#")[0]
            if path_part:
                all_test_refs.add(path_part)

    if not all_test_refs:
        evidence_index["test_results"] = {}
        return evidence_index

    # Load previous test_results cache from evidence_index (if any)
    prev_results: Dict[str, Any] = evidence_index.get("test_results", {})

    test_results: Dict[str, Any] = {}
    cache_hits = 0
    cache_misses = 0

    for test_ref in sorted(all_test_refs):
        test_path = project_root / test_ref
        if not test_path.exists():
            test_results[test_ref] = {
                "status": "file_not_found",
                "num_tests": 0,
                "errors": [f"Test file not found: {test_ref}"],
            }
            continue

        # --- Incremental cache check ---
        cached = prev_results.get(test_ref)
        if cached and "file_mtime" in cached:
            try:
                current_mtime = test_path.stat().st_mtime
            except OSError:
                current_mtime = None

            if current_mtime is not None and current_mtime == cached["file_mtime"]:
                # File unchanged -- reuse cached result
                test_results[test_ref] = cached
                cache_hits += 1
                continue

        # --- Cache miss: run pytest ---
        cache_misses += 1
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_path),
                 "--tb=short", "-q"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            # Parse pytest output: "X passed, Y failed, Z errors in ..."
            num_passed = 0
            num_failed = 0
            errors: List[str] = []

            # Check for "X passed" pattern
            passed_match = re.search(r"(\d+) passed", stdout)
            if passed_match:
                num_passed = int(passed_match.group(1))

            failed_match = re.search(r"(\d+) failed", stdout)
            if failed_match:
                num_failed = int(failed_match.group(1))

            error_match = re.search(r"(\d+) error", stdout)
            num_errors = int(error_match.group(1)) if error_match else 0

            total_tests = num_passed + num_failed + num_errors

            if result.returncode == 0:
                status = "passed"
            else:
                status = "failed"
                # Capture failure details from stdout (short tracebacks)
                if stdout:
                    errors.append(stdout)
                if stderr:
                    errors.append(stderr)

            entry: Dict[str, Any] = {
                "status": status,
                "num_tests": total_tests,
                "errors": errors,
            }

        except subprocess.TimeoutExpired:
            entry = {
                "status": "timeout",
                "num_tests": 0,
                "errors": ["Test execution timed out after 30 seconds"],
            }
        except Exception as exc:
            entry = {
                "status": "error",
                "num_tests": 0,
                "errors": [str(exc)],
            }

        # Record incremental cache metadata
        try:
            entry["file_mtime"] = test_path.stat().st_mtime
        except OSError:
            entry["file_mtime"] = None
        entry["last_run_time"] = datetime.now(timezone.utc).isoformat()
        entry["result_hash"] = _result_hash(entry)

        test_results[test_ref] = entry

    evidence_index["test_results"] = test_results
    if cache_hits > 0 or cache_misses > 0:
        print(
            f"  Claim tests: {cache_misses} run, {cache_hits} cached "
            f"(of {len(all_test_refs)} total).",
            file=sys.stderr,
        )
    return evidence_index
