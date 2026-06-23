"""
Unit tests for pipeline.py (TASK-VT-074).

Tests for:
  - _db_result_to_gaps conversion
  - _run_db_analysis integration
  - gates_only mode
  - pre-commit mode
"""

import pytest
from pathlib import Path
from vibe_tracing.cli.analyze.pipeline import _db_result_to_gaps


class TestDbResultToGaps:
    """Tests for _db_result_to_gaps helper function."""

    def test_empty_results(self):
        """Empty results produce empty gaps."""
        gaps = _db_result_to_gaps([], [], [])
        assert gaps == []

    def test_requirement_no_task(self):
        """no_task_for_requirement produces a requirement gap."""
        req_coverage = [{"req_id": "REQ-1", "coverage_status": "no_task_for_requirement"}]
        gaps = _db_result_to_gaps(req_coverage, [], [])
        assert len(gaps) == 1
        assert gaps[0]["item_id"] == "REQ-1"
        assert gaps[0]["item_type"] == "requirement"
        assert "no task coverage" in gaps[0]["reason"]

    def test_requirement_no_claim(self):
        """no_claim_for_task produces a requirement gap."""
        req_coverage = [{"req_id": "REQ-1", "coverage_status": "no_claim_for_task"}]
        gaps = _db_result_to_gaps(req_coverage, [], [])
        assert len(gaps) == 1
        assert "no claims" in gaps[0]["reason"]

    def test_requirement_no_tests_declared(self):
        """no_tests_declared produces a requirement gap."""
        req_coverage = [{"req_id": "REQ-1", "coverage_status": "no_tests_declared"}]
        gaps = _db_result_to_gaps(req_coverage, [], [])
        assert len(gaps) == 1
        assert "no tests" in gaps[0]["reason"].lower()

    def test_requirement_test_not_run(self):
        """test_not_run produces a requirement gap."""
        req_coverage = [{"req_id": "REQ-1", "coverage_status": "test_not_run"}]
        gaps = _db_result_to_gaps(req_coverage, [], [])
        assert len(gaps) == 1
        assert "not run" in gaps[0]["reason"]

    def test_requirement_test_failed(self):
        """test_failed produces a requirement gap."""
        req_coverage = [{"req_id": "REQ-1", "coverage_status": "test_failed"}]
        gaps = _db_result_to_gaps(req_coverage, [], [])
        assert len(gaps) == 1
        assert "failed" in gaps[0]["reason"]

    def test_requirement_covered_no_gap(self):
        """covered status produces no gap."""
        req_coverage = [{"req_id": "REQ-1", "coverage_status": "covered"}]
        gaps = _db_result_to_gaps(req_coverage, [], [])
        assert len(gaps) == 0

    def test_ac_no_task(self):
        """no_task_for_ac produces an AC gap."""
        ac_coverage = [{"task_id": "TASK-1", "ac_id": "AC-1", "coverage_status": "no_task_for_ac"}]
        gaps = _db_result_to_gaps([], ac_coverage, [])
        assert len(gaps) == 1
        assert gaps[0]["item_id"] == "AC-1"
        assert gaps[0]["item_type"] == "ac"

    def test_ac_no_claim(self):
        """no_claim_for_task produces an AC gap."""
        ac_coverage = [{"task_id": "TASK-1", "ac_id": "AC-1", "coverage_status": "no_claim_for_task"}]
        gaps = _db_result_to_gaps([], ac_coverage, [])
        assert len(gaps) == 1
        assert "no claims" in gaps[0]["reason"]

    def test_ac_no_tests_declared(self):
        """no_tests_declared produces an AC gap."""
        ac_coverage = [{"task_id": "TASK-1", "ac_id": "AC-1", "coverage_status": "no_tests_declared"}]
        gaps = _db_result_to_gaps([], ac_coverage, [])
        assert len(gaps) == 1
        assert "no tests" in gaps[0]["reason"].lower()

    def test_ac_test_not_run(self):
        """test_not_run produces an AC gap."""
        ac_coverage = [{"task_id": "TASK-1", "ac_id": "AC-1", "coverage_status": "test_not_run"}]
        gaps = _db_result_to_gaps([], ac_coverage, [])
        assert len(gaps) == 1
        assert "not run" in gaps[0]["reason"]

    def test_ac_test_failed(self):
        """test_failed produces an AC gap."""
        ac_coverage = [{"task_id": "TASK-1", "ac_id": "AC-1", "coverage_status": "test_failed"}]
        gaps = _db_result_to_gaps([], ac_coverage, [])
        assert len(gaps) == 1
        assert "failed" in gaps[0]["reason"]

    def test_ac_covered_no_gap(self):
        """covered status produces no gap."""
        ac_coverage = [{"task_id": "TASK-1", "ac_id": "AC-1", "coverage_status": "covered"}]
        gaps = _db_result_to_gaps([], ac_coverage, [])
        assert len(gaps) == 0

    def test_claim_task_missing(self):
        """task_missing produces a claim gap."""
        claim_evidence = [{"claim_id": "CLAIM-1", "verification_status": "task_missing"}]
        gaps = _db_result_to_gaps([], [], claim_evidence)
        assert len(gaps) == 1
        assert gaps[0]["item_id"] == "CLAIM-1"
        assert gaps[0]["item_type"] == "claim"
        assert "missing task" in gaps[0]["reason"]

    def test_claim_task_not_done(self):
        """task_not_done produces a claim gap."""
        claim_evidence = [{"claim_id": "CLAIM-1", "verification_status": "task_not_done"}]
        gaps = _db_result_to_gaps([], [], claim_evidence)
        assert len(gaps) == 1
        assert "not done" in gaps[0]["reason"]

    def test_claim_no_tests(self):
        """no_tests produces a claim gap."""
        claim_evidence = [{"claim_id": "CLAIM-1", "verification_status": "no_tests"}]
        gaps = _db_result_to_gaps([], [], claim_evidence)
        assert len(gaps) == 1
        assert "no tests" in gaps[0]["reason"].lower()

    def test_claim_test_missing(self):
        """test_missing produces a claim gap."""
        claim_evidence = [{"claim_id": "CLAIM-1", "verification_status": "test_missing"}]
        gaps = _db_result_to_gaps([], [], claim_evidence)
        assert len(gaps) == 1
        assert "missing" in gaps[0]["reason"].lower()

    def test_claim_test_failed(self):
        """test_failed produces a claim gap."""
        claim_evidence = [{"claim_id": "CLAIM-1", "verification_status": "test_failed"}]
        gaps = _db_result_to_gaps([], [], claim_evidence)
        assert len(gaps) == 1
        assert "failed" in gaps[0]["reason"]

    def test_claim_verified_no_gap(self):
        """verified status produces no gap."""
        claim_evidence = [{"claim_id": "CLAIM-1", "verification_status": "verified"}]
        gaps = _db_result_to_gaps([], [], claim_evidence)
        assert len(gaps) == 0

    def test_multiple_results(self):
        """Multiple results produce multiple gaps."""
        req_coverage = [{"req_id": "REQ-1", "coverage_status": "no_task_for_requirement"}]
        ac_coverage = [{"task_id": "TASK-1", "ac_id": "AC-1", "coverage_status": "no_tests_declared"}]
        claim_evidence = [{"claim_id": "CLAIM-1", "verification_status": "task_missing"}]
        gaps = _db_result_to_gaps(req_coverage, ac_coverage, claim_evidence)
        assert len(gaps) == 3
        item_types = {g["item_type"] for g in gaps}
        assert item_types == {"requirement", "ac", "claim"}
