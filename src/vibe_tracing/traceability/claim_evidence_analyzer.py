"""
Agent Claims to Evidence Consistency Analyzer for Vibe Tracing.

Validates that agent claims are backed by external evidence, checks for mismatches
with task completeness or test results, and flags nonexistent or outdated file references.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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

        # Quick lookup for evidences by evidence_id
        ev_map = {ev["evidence_id"]: ev for ev in evidences if "evidence_id" in ev}

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
                            "risk_id": f"RISK-VT-{risk_counter:03d}",
                            "description": reason,
                            "severity": "must",
                        }
                    )
                    risk_counter += 1
                else:
                    for ref in external_refs:
                        if ref in ev_map:
                            ev = ev_map[ref]
                            ev_status = ev.get("status")
                            if ev_status not in (
                                CoverageStatus.COVERED.value,
                                CoverageStatus.COMPLIANT.value,
                            ):
                                if ev_status == CoverageStatus.VIOLATED.value:
                                    has_failed_test = True
                                else:
                                    has_other_mismatch = True
                                reason = f"Claim {claim_id} references evidence {ref} which has status '{ev_status}'."
                                mismatches.append(reason)
                                risks.append(
                                    {
                                        "risk_id": f"RISK-VT-{risk_counter:03d}",
                                        "description": reason,
                                        "severity": "must",
                                    }
                                )
                                risk_counter += 1
                            else:
                                supporting_evidence_ids.append(ref)
                        else:
                            has_other_mismatch = True
                            reason = f"Claim {claim_id} references non-existent evidence {ref}."
                            mismatches.append(reason)
                            risks.append(
                                {
                                    "risk_id": f"RISK-VT-{risk_counter:03d}",
                                    "description": reason,
                                    "severity": "must",
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
                                "risk_id": f"RISK-VT-{risk_counter:03d}",
                                "description": reason,
                                "severity": "must",
                            }
                        )
                        risk_counter += 1

                    # 3. AC test coverage checks for the task
                    related_acs = [
                        item
                        for item in task_ev.get("covers", [])
                        if item.startswith("AC-VT-")
                    ]
                    for ac_id in related_acs:
                        ac_tests = [t for t in test_evs if ac_id in t.get("covers", [])]
                        if not ac_tests:
                            has_other_mismatch = True
                            reason = f"Claim {claim_id} is completed but related AC {ac_id} has no test coverage."
                            mismatches.append(reason)
                            risks.append(
                                {
                                    "risk_id": f"RISK-VT-{risk_counter:03d}",
                                    "description": reason,
                                    "severity": "must",
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
                                            "risk_id": f"RISK-VT-{risk_counter:03d}",
                                            "description": reason,
                                            "severity": "must",
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
                            "risk_id": f"RISK-VT-{risk_counter:03d}",
                            "description": reason,
                            "severity": "must",
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
                                "risk_id": f"RISK-VT-{risk_counter:03d}",
                                "description": reason,
                                "severity": "must",
                            }
                        )
                        risk_counter += 1
                    elif claim_ts:
                        # Check modification time
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
                                        "risk_id": f"RISK-VT-{risk_counter:03d}",
                                        "description": reason,
                                        "severity": "should",
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
