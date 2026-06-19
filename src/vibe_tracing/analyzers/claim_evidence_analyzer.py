"""
Agent Claims to Evidence Consistency Analyzer for Vibe Tracing.

Validates that agent claims are backed by external evidence, checks for mismatches
with task completeness or test results, and flags nonexistent or outdated file references.
"""

# ============================================================================
# DESIGN: Claim as Pointer — Test-Backed Validation
# ============================================================================
#
# Claim is a pointer: task + code_refs + test_refs.
# The analyzer validates whether the declared test_refs actually have passing
# results in evidence, not whether the claim self-reports a status.
#
# Key principles:
#   - A claim is considered "covered" if it has non-empty test_refs.
#   - Validation checks task completion and AC test coverage via evidence.
#
# Sections in analyze():
#   1. Task completion checks
#   2. AC test coverage checks + test_refs covers consistency
#
# ============================================================================

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from vibe_tracing.infra import validation as ids
from vibe_tracing.infra.enums import CoverageStatus
from vibe_tracing.infra.operational_logger import OperationalLogger


def _file_sha256(path: Path) -> Optional[str]:
    """Compute SHA-256 hex digest of a file. Returns None if file missing."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, IOError):
        return None


class ClaimEvidenceAnalyzer:
    """Analyzes Agent Claims against compiled evidences and identifies gaps and risks."""

    def __init__(self, project_root: Path) -> None:
        """Initialize the analyzer with project root for path verification."""
        self.project_root = project_root

    def analyze(
        self,
        claims: List[Any],
        evidences: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Analyze the consistency between agent claims and external evidences.

        Args:
            claims: List of parsed Agent Claims.
            evidences: List of compiled evidence records.

        Returns:
            A dictionary containing:
                "claims_analysis": List of evaluated claim results.
                "gaps": List of identified gaps.
                "risks": List of identified risk objects (e.g. mismatches, failing tests, etc.).
        """
        claims_analysis: List[Dict[str, Any]] = []
        gaps: List[Dict[str, Any]] = []
        risks: List[Dict[str, Any]] = []
        risk_counter = 1

        # Quick lookup for evidences by evidence_id, source_path, and nodeid
        ev_map: dict[str, list] = {}
        for ev in evidences:
            if "evidence_id" in ev:
                ev_map.setdefault(ev["evidence_id"], []).append(ev)
            if ev.get("source_path"):
                ev_map.setdefault(ev["source_path"], []).append(ev)
            if ev.get("source_type") == "test" and ev.get("details", {}).get("nodeid"):
                ev_map.setdefault(ev["details"]["nodeid"], []).append(ev)

        # Find task evidence by task_id
        task_evs = {}
        for ev in evidences:
            if ev.get("source_type") == "task":
                t_id = ev.get("details", {}).get("task_id")
                if t_id:
                    task_evs[t_id] = ev

        # Find test evidences
        test_evs = [ev for ev in evidences if ev.get("source_type") == "test"]

        for claim in claims:
            claim_id = claim.claim_id
            related_task = claim.related_task
            code_refs = claim.code_refs or []
            test_refs = claim.test_refs or []

            mismatches: List[str] = []
            supporting_evidence_ids: List[str] = []

            # A claim is considered "covered" if it has non-empty test_refs
            is_completed = bool(test_refs)

            has_failed_test = False
            has_other_mismatch = False

            if is_completed:
                # 1. Task completion checks
                if related_task in task_evs:
                    task_ev = task_evs[related_task]
                    task_status = task_ev.get("status")
                    if task_status != CoverageStatus.COVERED.value:
                        has_other_mismatch = True
                        reason = (
                            f"Claim {claim_id} is completed but related task {related_task} "
                            f"is not completed (status: '{task_status}')."
                        )
                        mismatches.append(reason)
                        risks.append(
                            {
                                "risk_id": ids.make_risk_id(risk_counter),
                                "description": reason,
                                "severity": "must",
                                "risk_category": "task_not_completed",
                                "claim_id": claim_id,
                            }
                        )
                        risk_counter += 1

                    # 2. AC test coverage checks for the task
                    _ac_prefix = f"AC-{ids.get_project_prefix()}-"
                    related_acs = [
                        item
                        for item in task_ev.get("covers", [])
                        if item.startswith(_ac_prefix)
                    ]
                    for ac_id in related_acs:
                        ac_tests = [t for t in test_evs if ac_id in t.get("covers", [])]
                        if not ac_tests:
                            has_other_mismatch = True
                            reason = f"Claim {claim_id} is completed but related AC {ac_id} has no test coverage."
                            mismatches.append(reason)
                            risks.append(
                                {
                                    "risk_id": ids.make_risk_id(risk_counter),
                                    "description": reason,
                                    "severity": "must",
                                    "risk_category": "no_test_coverage",
                                    "claim_id": claim_id,
                                }
                            )
                            risk_counter += 1
                        else:
                            for test in ac_tests:
                                test_status = test.get("status")
                                if test_status != CoverageStatus.COVERED.value:
                                    has_failed_test = True
                                    reason = f"Claim {claim_id} is completed but related AC {ac_id} has failed tests."
                                    mismatches.append(reason)
                                    risks.append(
                                        {
                                            "risk_id": ids.make_risk_id(risk_counter),
                                            "description": reason,
                                            "severity": "must",
                                            "risk_category": "failed_tests",
                                            "claim_id": claim_id,
                                        }
                                    )
                                    risk_counter += 1

                    # 2b. Covers consistency: claim's test_refs must include tests covering related ACs
                    if claim.test_refs:
                        claim_test_paths = set(ref.split("#")[0] for ref in claim.test_refs)
                        for ac_id in related_acs:
                            # Find test evidences that cover this AC
                            ac_covering_tests = [t for t in test_evs if ac_id in t.get("covers", [])]
                            if not ac_covering_tests:
                                continue  # No test covers this AC - already caught by existing check above

                            # Check if any of the covering tests are in claim's test_refs
                            claim_covers_ac = any(
                                t.get("source_path") in claim_test_paths
                                for t in ac_covering_tests
                            )
                            if not claim_covers_ac:
                                has_other_mismatch = True
                                reason = (
                                    f"Claim {claim_id} 声明完成但 test_refs 中无测试覆盖 AC {ac_id}。"
                                    f"已有覆盖测试: {[t.get('source_path') for t in ac_covering_tests]}"
                                )
                                mismatches.append(reason)
                                risks.append(
                                    {
                                        "risk_id": ids.make_risk_id(risk_counter),
                                        "description": reason,
                                        "severity": "must",
                                        "risk_category": "test_covers_mismatch",
                                        "claim_id": claim_id,
                                    }
                                )
                                risk_counter += 1
                else:
                    has_other_mismatch = True
                    reason = (
                        f"Claim {claim_id} references non-existent task {related_task}."
                    )
                    mismatches.append(reason)
                    risks.append(
                        {
                            "risk_id": ids.make_risk_id(risk_counter),
                            "description": reason,
                            "severity": "must",
                            "risk_category": "non_existent_task",
                            "claim_id": claim_id,
                        }
                    )
                    risk_counter += 1

            # Determine final status for claims_analysis
            if not test_refs:
                final_status = CoverageStatus.UNCLEAR.value
            else:
                final_status = CoverageStatus.COVERED.value
                if has_failed_test:
                    final_status = CoverageStatus.VIOLATED.value
                elif has_other_mismatch:
                    final_status = CoverageStatus.LOW_CONFIDENCE.value

            claims_analysis.append(
                {
                    "claim_id": claim_id,
                    "status": final_status,
                    "evidence_ids": sorted(list(set(supporting_evidence_ids))),
                    "mismatches": mismatches,
                }
            )

            # Per-claim evidence chain debug log
            missing_code_refs = [ref for ref in code_refs if ref not in ev_map]
            missing_test_refs = [ref for ref in test_refs if ref not in ev_map]
            claim_log_status = (
                "missing_refs" if mismatches
                else "valid"
            )
            OperationalLogger.get().debug("claim_mapping", "Claim evidence mapping",
                claim_id=claim_id,
                related_task=related_task,
                code_refs_count=len(code_refs),
                test_refs_count=len(test_refs),
                missing_code_refs=missing_code_refs[:20],
                missing_test_refs=missing_test_refs[:20],
                status=claim_log_status)

        OperationalLogger.get().debug("analyzer_result", "ClaimEvidenceAnalyzer complete",
            claims_count=len(claims),
            claim_ids=[c.claim_id for c in claims],
            evidences_count=len(evidences),
            gaps_count=len(gaps),
            gap_ids=[g.get("item_id") for g in gaps],
            risks_count=len(risks),
            claims_analysis_count=len(claims_analysis))

        return {
            "claims_analysis": claims_analysis,
            "gaps": gaps,
            "risks": risks,
        }
