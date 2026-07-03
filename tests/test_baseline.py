"""
Unit tests for Baseline snapshot mechanism (VT-181).
"""

import json
from pathlib import Path

from vibe_tracing.domain.gate.baseline import BaselineManager, compute_fingerprint


class TestComputeFingerprint:
    """Tests for the pure compute_fingerprint function."""

    def test_deterministic(self):
        """Same inputs always produce the same output."""
        fp1 = compute_fingerprint("no_claim", ["src/foo.py"])
        fp2 = compute_fingerprint("no_claim", ["src/foo.py"])
        assert fp1 == fp2

    def test_different_issue_type_different_fingerprint(self):
        fp1 = compute_fingerprint("no_claim", ["src/foo.py"])
        fp2 = compute_fingerprint("chain_broken", ["src/foo.py"])
        assert fp1 != fp2

    def test_different_targets_different_fingerprint(self):
        fp1 = compute_fingerprint("no_claim", ["src/foo.py"])
        fp2 = compute_fingerprint("no_claim", ["src/bar.py"])
        assert fp1 != fp2

    def test_sorted_targets_same_fingerprint(self):
        fp1 = compute_fingerprint("no_claim", ["b.py", "a.py"])
        fp2 = compute_fingerprint("no_claim", ["a.py", "b.py"])
        assert fp1 == fp2

    def test_length_is_16(self):
        fp = compute_fingerprint("task_failed", ["AC-001"])
        assert len(fp) == 16

    def test_empty_targets(self):
        fp = compute_fingerprint("no_claim", [])
        assert len(fp) == 16


class TestBaselineManager:
    """Tests for BaselineManager lifecycle."""

    def test_generate_snapshot_first_call(self, tmp_path):
        """First call creates the snapshot file."""
        mgr = BaselineManager(tmp_path)
        result = mgr.generate_snapshot(["abc123", "def456"])
        assert result is True
        assert (tmp_path / ".vibetracing" / "baseline.json").exists()

    def test_generate_snapshot_second_call_no_overwrite(self, tmp_path):
        """Second call does not overwrite the existing snapshot."""
        mgr = BaselineManager(tmp_path)
        mgr.generate_snapshot(["abc123"])
        result = mgr.generate_snapshot(["xyz789"])
        assert result is False
        data = json.loads((tmp_path / ".vibetracing" / "baseline.json").read_text())
        assert "xyz789" not in data["fingerprints"]
        assert "abc123" in data["fingerprints"]

    def test_is_observed_existing_fingerprint(self, tmp_path):
        mgr = BaselineManager(tmp_path)
        mgr.generate_snapshot(["abc123"])
        assert mgr.is_observed("abc123") is True

    def test_is_observed_missing_fingerprint(self, tmp_path):
        mgr = BaselineManager(tmp_path)
        mgr.generate_snapshot(["abc123"])
        assert mgr.is_observed("zzz999") is False

    def test_is_observed_no_baseline_file(self, tmp_path):
        """No baseline file means nothing is observed."""
        mgr = BaselineManager(tmp_path)
        assert mgr.is_observed("abc123") is False

    def test_deduplicates_fingerprints(self, tmp_path):
        mgr = BaselineManager(tmp_path)
        mgr.generate_snapshot(["abc", "abc", "def"])
        data = json.loads((tmp_path / ".vibetracing" / "baseline.json").read_text())
        assert len(data["fingerprints"]) == 2

    def test_json_format(self, tmp_path):
        mgr = BaselineManager(tmp_path)
        mgr.generate_snapshot(["fp1"])
        data = json.loads((tmp_path / ".vibetracing" / "baseline.json").read_text())
        assert data["version"] == 1
        assert isinstance(data["fingerprints"], list)

    def test_loads_from_existing_file(self, tmp_path):
        """Manager loads from existing baseline.json on first query."""
        baseline_dir = tmp_path / ".vibetracing"
        baseline_dir.mkdir(parents=True)
        (baseline_dir / "baseline.json").write_text(
            json.dumps({"version": 1, "fingerprints": ["pre_existing"]})
        )
        mgr = BaselineManager(tmp_path)
        assert mgr.is_observed("pre_existing") is True
        assert mgr.is_observed("other") is False

    def test_tolerates_corrupt_json(self, tmp_path):
        baseline_dir = tmp_path / ".vibetracing"
        baseline_dir.mkdir(parents=True)
        (baseline_dir / "baseline.json").write_text("not json!!!")
        mgr = BaselineManager(tmp_path)
        assert mgr.is_observed("anything") is False
