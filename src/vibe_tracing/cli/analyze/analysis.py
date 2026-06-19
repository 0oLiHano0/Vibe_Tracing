"""
Analyzer execution and claims archival.
"""

import hashlib
import json
import sys
from pathlib import Path
from typing import Optional, Set, Tuple

from vibe_tracing.domain.context import UnifiedContext
from vibe_tracing.cli.common import _determine_affected_items
from vibe_tracing.cli.analyze.tools import _check_staged_extensions
from vibe_tracing.infra.operational_logger import OperationalLogger


def _run_analyzers(
    ctx: UnifiedContext,
    evidence_list: list,
    project_root: Path,
    staged_files: Optional[Set[str]] = None,
    human_decisions: Optional[dict] = None,
) -> Tuple[list, list, Optional[dict], dict, dict]:
    """Run all analyzers and return (merged_gaps, final_risks, compliance_res, claim_res, req_res)."""
    from vibe_tracing.domain.architecture_compliance_checker import ArchitectureComplianceChecker
    from vibe_tracing.analyzers.requirement_task_analyzer import RequirementTaskAnalyzer
    from vibe_tracing.analyzers.ac_test_analyzer import AcTestAnalyzer
    from vibe_tracing.analyzers.claim_evidence_analyzer import ClaimEvidenceAnalyzer
    from vibe_tracing.domain.risk_advisor import RiskAdvisor

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
            evidence_list, constraints_data=ctx.constraints,
            human_decisions=human_decisions,
        )

    # Risk Advisor
    risk_advisor = RiskAdvisor(project_root)
    final_risks = risk_advisor.generate_risks(
        gaps=merged_gaps,
        claims_analysis=claim_res.get("claims_analysis", []),
        claim_risks=claim_risks,
        compliance_result=compliance_res,
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


def _load_human_decisions(project_root: Optional[Path] = None) -> dict:
    """Read human decision log."""
    if project_root is None:
        project_root = Path(".")
    decisions_path = project_root / ".vibetracing" / "human_decisions.json"
    if not decisions_path.exists():
        return {"version": "1.0", "decisions": []}
    try:
        return json.loads(decisions_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        OperationalLogger.get().warning("human_decisions_load_failed", "Could not load human decisions file", path=str(decisions_path))
        return {"version": "1.0", "decisions": []}


def _result_hash(entry: dict) -> str:
    """Compute a stable hash of a test result entry (excluding cache metadata)."""
    cache_keys = {"last_run_time", "file_mtime", "result_hash"}
    content = {k: v for k, v in entry.items() if k not in cache_keys}
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]

