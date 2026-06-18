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
#   - File hash comparison detects staleness in code_refs and test_refs.
#   - Invalidation detection via _check_invalidation() is available for
#     callers who pass an evidence_index dict for hash-based validation.
#
# Sections in analyze():
#   0. (reserved — invalidation is now caller-driven, not embedded)
#   1. Task completion checks
#   2. AC test coverage checks + test_refs covers consistency
#
# ============================================================================

import hashlib
from datetime import datetime, timezone
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

    def _check_invalidation(self, claim, evidence_index: dict) -> Optional[dict]:
        """Check if claim's referenced files have changed since last analysis.

        Validates file hashes against the evidence_index dict (output/evidences/).

        Note: analyze() no longer calls this method.
        Callers who need invalidation detection should pass evidence_index.

        Args:
            claim: The claim object to check.
            evidence_index: Evidence index dict for hash-based validation.

        Returns:
            A dict with invalidation details if files changed, else None.
        """
        cid = claim.claim_id if hasattr(claim, 'claim_id') else claim.get('claim_id')
        return self._check_invalidation_from_evidence_index(claim, cid, evidence_index)

    def _check_invalidation_from_evidence_index(
        self, claim, cid: str, evidence_index: dict
    ) -> Optional[dict]:
        """Validate claim file refs against evidence_index hashes.

        For each code_ref and test_ref in the claim:
        - File does not exist → needs_reverification
        - File exists but no hash record in evidence_index → needs_reverification
        - Hash mismatch → needs_reverification
        - Hash match → covered
        """
        # Build file_path → hash mapping from evidence_index
        evidence_hash_map: Dict[str, str] = {}
        scan_time = evidence_index.get("scan_time")
        for ev in evidence_index.get("evidences", []):
            file_hash = ev.get("file_hash") or (ev.get("details") or {}).get("file_hash")
            source_path = ev.get("source_path", "")
            if source_path and file_hash:
                # Strip nodeid suffix (e.g. "tests/test.py::test_func" → "tests/test.py")
                clean_path = source_path.split("#")[0].split("::")[0]
                evidence_hash_map[clean_path] = file_hash

        code_refs = claim.code_refs if hasattr(claim, 'code_refs') else (claim.get('code_refs') or [])
        test_refs = claim.test_refs if hasattr(claim, 'test_refs') else (claim.get('test_refs') or [])

        changed_files = []
        for ref in list(code_refs) + list(test_refs):
            clean_ref = ref.split("#")[0] if "#" in ref else ref
            # Strip nodeid for test refs
            clean_ref = clean_ref.split("::")[0] if "::" in clean_ref else clean_ref
            full_path = self.project_root / clean_ref

            if not full_path.exists():
                changed_files.append({
                    "file": clean_ref,
                    "reason": f"File {clean_ref} has been deleted",
                })
            else:
                current_hash = _file_sha256(full_path)
                stored_hash = evidence_hash_map.get(clean_ref)
                if stored_hash is None:
                    changed_files.append({
                        "file": clean_ref,
                        "new_hash": current_hash,
                        "reason": f"No hash record in evidence_index for {clean_ref}",
                    })
                elif current_hash and current_hash != stored_hash:
                    changed_files.append({
                        "file": clean_ref,
                        "old_hash": stored_hash,
                        "new_hash": current_hash,
                        "reason": f"File {clean_ref} hash has changed",
                    })

        if changed_files:
            return {
                "claim_id": cid,
                "status": CoverageStatus.NEEDS_REVERIFICATION.value,
                "files": changed_files,
                "stored_timestamp": scan_time,
            }
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
