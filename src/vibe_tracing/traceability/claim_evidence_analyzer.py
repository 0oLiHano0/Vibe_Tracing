"""
Agent Claims to Evidence Consistency Analyzer for Vibe Tracing.

Validates that agent claims are backed by external evidence, checks for mismatches
with task completeness or test results, and flags nonexistent or outdated file references.
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from vibe_tracing.core import ids
from vibe_tracing.core.enums import CoverageStatus


class ClaimEvidenceAnalyzer:
    """Analyzes Agent Claims against compiled evidences and identifies gaps and risks."""

    def __init__(self, project_root: Path) -> None:
        """Initialize the analyzer with project root for path verification."""
        self.project_root = project_root

    def _parse_timestamp(self, ts_str: str) -> Optional[datetime]:
        """Parse an ISO-8601 timestamp string into a timezone-aware datetime in UTC."""
        if not ts_str:
            return None
        try:
            if ts_str.endswith("Z"):
                ts_str = ts_str[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts_str)
            # Ensure it is timezone aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

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
                "gaps": List of identified gaps (e.g. self-referential completed claims).
                "risks": List of identified risk objects (e.g. mismatches, failing tests, etc.).
        """
        claims_analysis: List[Dict[str, Any]] = []
        gaps: List[Dict[str, Any]] = []
        risks: List[Dict[str, Any]] = []
        risk_counter = 1

        # Quick lookup for evidences by evidence_id, source_path, and nodeid
        ev_map = {}
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
            claimed_status = claim.claimed_status
            related_task = claim.related_task
            evidence_refs = claim.evidence_refs or []
            code_refs = claim.code_refs or []
            test_refs = claim.test_refs or []

            mismatches: List[str] = []
            supporting_evidence_ids: List[str] = []

            # Determine if claim claims completion
            is_completed = claimed_status in (
                CoverageStatus.COVERED.value,
                CoverageStatus.COMPLIANT.value,
            )

            has_failed_test = False
            has_self_ref_gap = False
            has_other_mismatch = False

            # 1. External evidence checks (only relevant if completed)
            external_refs = [ref for ref in evidence_refs if ref != claim_id]

            if is_completed:
                if not external_refs:
                    has_self_ref_gap = True
                    reason = f"Completed claim {claim_id} has only self-referential or empty evidence."
                    mismatches.append(reason)
                    gaps.append(
                        {
                            "item_id": claim_id,
                            "item_type": "claim",
                            "reason": reason,
                        }
                    )
                    risks.append(
                        {
                            "risk_id": ids.make_risk_id(risk_counter),
                            "description": reason,
                            "severity": "must",
                            "risk_category": "self_referential_claim",
                            "claim_id": claim_id,
                        }
                    )
                    risk_counter += 1
                else:
                    for ref in external_refs:
                        if ref in ev_map:
                            matches = ev_map[ref]

                            # Filter unique matches based on evidence_id
                            seen_ids = set()
                            unique_matches = []
                            for ev in matches:
                                ev_id = ev.get("evidence_id")
                                if ev_id and ev_id not in seen_ids:
                                    seen_ids.add(ev_id)
                                    unique_matches.append(ev)

                            # Check status across unique matches
                            has_failed_in_matches = False
                            has_unclear_or_missing_in_matches = False
                            failed_status = ""
                            unclear_status = ""
                            statuses = set()

                            for ev in unique_matches:
                                ev_status = ev.get("status")
                                statuses.add(ev_status)
                                if ev_status not in (
                                    CoverageStatus.COVERED.value,
                                    CoverageStatus.COMPLIANT.value,
                                ):
                                    if ev_status == CoverageStatus.VIOLATED.value:
                                        has_failed_in_matches = True
                                        failed_status = ev_status
                                    else:
                                        has_unclear_or_missing_in_matches = True
                                        unclear_status = ev_status
                                else:
                                    supporting_evidence_ids.append(ev["evidence_id"])

                            # Expose conflicts (outcome inconsistency)
                            if len(statuses) > 1:
                                conflict_msg = (
                                    f"Claim {claim_id} references evidence {ref} "
                                    f"which has conflicting statuses: {sorted(list(statuses))}."
                                )
                                mismatches.append(conflict_msg)
                                risks.append(
                                    {
                                        "risk_id": ids.make_risk_id(risk_counter),
                                        "description": conflict_msg,
                                        "severity": "should",
                                        "risk_category": "conflicting_statuses",
                                        "claim_id": claim_id,
                                    }
                                )
                                risk_counter += 1

                            # Fail-fast evaluation based on matches
                            if has_failed_in_matches:
                                has_failed_test = True
                                reason = f"Claim {claim_id} references evidence {ref} which has status '{failed_status}'."
                                mismatches.append(reason)
                                risks.append(
                                    {
                                        "risk_id": ids.make_risk_id(risk_counter),
                                        "description": reason,
                                        "severity": "must",
                                        "risk_category": "violated_evidence",
                                        "claim_id": claim_id,
                                    }
                                )
                                risk_counter += 1
                            elif has_unclear_or_missing_in_matches:
                                has_other_mismatch = True
                                reason = f"Claim {claim_id} references evidence {ref} which has status '{unclear_status}'."
                                mismatches.append(reason)
                                risks.append(
                                    {
                                        "risk_id": ids.make_risk_id(risk_counter),
                                        "description": reason,
                                        "severity": "must",
                                        "risk_category": "unclear_evidence_status",
                                        "claim_id": claim_id,
                                    }
                                )
                                risk_counter += 1
                        else:
                            has_other_mismatch = True
                            reason = f"Claim {claim_id} references non-existent evidence {ref}."
                            mismatches.append(reason)
                            risks.append(
                                {
                                    "risk_id": ids.make_risk_id(risk_counter),
                                    "description": reason,
                                    "severity": "must",
                                    "claim_id": claim_id,
                                }
                            )
                            risk_counter += 1

                # 2. Task completion checks
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

                    # 3. AC test coverage checks for the task
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

                    # 3b. Covers consistency: claim's test_refs must include tests covering related ACs
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

            # 4. File existence and expiration checks (regardless of completion claim, check refs if present)
            claim_ts = self._parse_timestamp(claim.timestamp)

            for ref_type, refs in [("code", code_refs), ("test", test_refs)]:
                for ref in refs:
                    clean_ref = ref.split("#")[0] if "#" in ref else ref
                    ref_path = Path(clean_ref)
                    if not ref_path.is_absolute():
                        ref_path = self.project_root / ref_path

                    if not ref_path.exists():
                        # Non-existent file is a must-severity risk if the claim is completed
                        has_other_mismatch = True
                        reason = f"Claim {claim_id} references non-existent {ref_type} path: {ref}."
                        mismatches.append(reason)
                        risks.append(
                            {
                                "risk_id": ids.make_risk_id(risk_counter),
                                "description": reason,
                                "severity": "must",
                                "risk_category": f"non_existent_{ref_type}_ref",
                                "claim_id": claim_id,
                            }
                        )
                        risk_counter += 1
                    elif claim_ts:
                        # Check modification time (skip in CI environment to prevent Git checkout timestamp false positives)
                        if os.getenv("CI") != "true":
                            try:
                                mtime = ref_path.stat().st_mtime
                                file_dt = datetime.fromtimestamp(mtime, timezone.utc)
                                if file_dt > claim_ts:
                                    has_other_mismatch = True
                                    reason = (
                                        f"Claim {claim_id} references {ref_type} file {ref} "
                                        "which was modified after the claim timestamp."
                                    )
                                    mismatches.append(reason)
                                    risks.append(
                                        {
                                            "risk_id": ids.make_risk_id(risk_counter),
                                            "description": reason,
                                            "severity": "should",
                                            "risk_category": "stale_file",
                                            "claim_id": claim_id,
                                        }
                                    )
                                    risk_counter += 1
                            except Exception:
                                pass

            # Determine final status for claims_analysis
            final_status = claimed_status
            if is_completed:
                if has_failed_test:
                    final_status = CoverageStatus.VIOLATED.value
                elif has_self_ref_gap:
                    final_status = CoverageStatus.BLOCKED.value
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

        return {
            "claims_analysis": claims_analysis,
            "gaps": gaps,
            "risks": risks,
        }
