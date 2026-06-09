"""
Agent Claims to Evidence Consistency Analyzer for Vibe Tracing.

Validates that agent claims are backed by external evidence, checks for mismatches
with task completeness or test results, and flags nonexistent or outdated file references.
"""

# ============================================================================
# DESIGN: Claim Auto-Invalidation Mechanism (EVO-TASK-011)
# ============================================================================
#
# Problem:
#   Currently, ClaimEvidenceAnalyzer detects stale claims by comparing file
#   modification timestamps against the claim timestamp (Section 4 in analyze()).
#   This is a passive, runtime-only check. There is no mechanism to proactively
#   mark claims as "needs re-verification" when their referenced files change
#   between analysis runs.
#
# Proposed Mechanism:
#   1. File Fingerprint Storage:
#      - After each successful vt analyze run, store a snapshot of SHA-256
#        fingerprints for all files referenced in code_refs, test_refs, and
#        evidence_refs of every claim.
#      - Store in .vibetracing/claim_fingerprints.json with structure:
#        {
#          "CLAIM-VT-005": {
#            "timestamp": "2026-06-08T13:26:39Z",
#            "fingerprints": {
#              "src/vibe_tracing/raw_input_loader.py": "abc123...",
#              "tests/test_raw_input_loader.py": "def456..."
#            }
#          }
#        }
#
#   2. Invalidation Detection (in analyze() or a new pre-analyze step):
#      - Before claim analysis, load claim_fingerprints.json.
#      - For each claim, compute current SHA-256 of all referenced files.
#      - If any file's fingerprint differs from the stored snapshot:
#        * Set claim status to "needs_reverification" (new CoverageStatus enum).
#        * Generate a risk with risk_category "claim_invalidated_by_file_change".
#        * Include which specific files changed and their old/new fingerprints.
#
#   3. Integration Points:
#      - ClaimEvidenceAnalyzer.__init__: accept optional fingerprints_path.
#      - ClaimEvidenceAnalyzer.analyze: add a _check_invalidation() step that
#        runs before existing Section 1-4 logic.
#      - CLI (run_analyze): after analysis, write updated fingerprints to disk.
#      - Gate 2 (pre-commit hook): can check invalidation to warn about stale
#        claims in staged files without full analysis.
#
#   4. Status Lifecycle:
#      covered -> needs_reverification (file changed)
#      needs_reverification -> covered (re-analysis confirms evidence still valid)
#      needs_reverification -> violated (re-analysis finds evidence broken)
#      needs_reverification -> blocked (evidence file deleted)
#
#   5. Dashboard Impact:
#      - Add "needs_reverification" badge style (amber/yellow).
#      - In Decisions tab, auto-generate decision cards for invalidated claims
#        asking: "Claim evidence may have changed. Re-verify or accept risk?"
#
#   6. Files to Modify (implementation phase):
#      - src/vibe_tracing/traceability/claim_evidence_analyzer.py  (core logic)
#      - src/vibe_tracing/core/enums.py                            (new status)
#      - src/vibe_tracing/cli.py                                   (fingerprint I/O)
#      - src/vibe_tracing/templates/dashboard.template.html        (UI badge)
#      - tests/test_claim_evidence_analyzer.py                     (tests)
#
# ============================================================================

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from vibe_tracing.core import ids
from vibe_tracing.core.enums import CoverageStatus


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

    def _check_invalidation(self, claim, stored_fingerprints: dict, evidence_index=None) -> Optional[dict]:
        """Check if claim's referenced files have changed since last analysis.

        Args:
            claim: The claim object to check.
            stored_fingerprints: Legacy fingerprint data from claim_fingerprints.json.
            evidence_index: Optional evidence_index dict. When provided, validates
                file hashes against evidence_index instead of stored_fingerprints.
                When None, falls back to stored_fingerprints logic.

        Returns:
            A dict with invalidation details if files changed, else None.
        """
        cid = claim.claim_id if hasattr(claim, 'claim_id') else claim.get('claim_id')

        # ---- New path: evidence_index based validation ----
        if evidence_index is not None:
            return self._check_invalidation_from_evidence_index(claim, cid, evidence_index)

        # ---- Fallback: original stored_fingerprints logic ----
        if stored_fingerprints is None:
            return None

        stored = stored_fingerprints.get(cid)
        if not stored:
            return None

        changed_files = []
        for ref_path, old_hash in stored.get("fingerprints", {}).items():
            full_path = self.project_root / ref_path
            if not full_path.exists():
                changed_files.append({"file": ref_path, "old_hash": old_hash, "reason": f"File {ref_path} has been deleted"})
            else:
                current_hash = _file_sha256(full_path)
                if current_hash and current_hash != old_hash:
                    changed_files.append({"file": ref_path, "old_hash": old_hash, "new_hash": current_hash, "reason": f"File {ref_path} hash has changed"})

        if changed_files:
            return {
                "claim_id": cid,
                "status": CoverageStatus.NEEDS_REVERIFICATION.value,
                "files": changed_files,
                "stored_timestamp": stored.get("timestamp"),
            }
        return None

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
                "gaps": List of identified gaps (e.g. self-referential completed claims).
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

        # Load stored file fingerprints for invalidation detection
        fingerprints_path = self.project_root / ".vibetracing" / "claim_fingerprints.json"
        stored_fingerprints: Dict[str, Any] = {}
        if fingerprints_path.exists():
            try:
                with open(fingerprints_path, "r", encoding="utf-8") as pf:
                    stored_fingerprints = json.load(pf)
            except (OSError, json.JSONDecodeError):
                stored_fingerprints = {}

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

            # 0. Claim invalidation detection (file fingerprint changes)
            invalidation = self._check_invalidation(claim, stored_fingerprints)
            if invalidation:
                risks.append(
                    {
                        "risk_id": f"RISK-INVALIDATED-{claim_id}",
                        "risk_category": "claim_invalidated_by_file_change",
                        "severity": "must",
                        "claim_id": claim_id,
                        "description": f"Claim {claim_id} 引用的文件已变化，需要重新验证",
                        "changed_files": [f["file"] for f in invalidation["files"]],
                        "suggested_action": "重新运行 vt analyze 验证证据是否仍然有效",
                    }
                )

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
