"""
Tests for Architecture Change Proposal Engine.

Covers:
  AC-VT-009-04 — Architecture change proposals must be explicitly governed.
  GATE-VT-014 — Architecture constraint changes must not be silent edits.

Updated for Git-based baseline architecture: base.json removed,
check_governance is read-only (always returns is_valid=True).
"""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from vibe_tracing.architecture_change_proposal import ArchitectureChangeProposalEngine


# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

BASE_CONSTRAINTS = {
    "schema_version": "0.1",
    "project": {"project_id": "PROJECT-VT", "name": "Vibe Tracing", "stage": "mvp"},
    "storage_rules": [
        {
            "rule_id": "STORE-VT-001",
            "title": "MVP 不使用数据库",
            "severity": "must",
            "description": "No database in MVP",
        }
    ],
}


def _write_config(proj: Path, constraints_hash: str, git_commit: str = "abc123",
                  constraints_path: str = "docs/architecture_constraints.json") -> None:
    """Write a config.json with architecture_constraints_hash and finalize metadata."""
    config = {
        "project_id": "PROJECT-VT",
        "project_prefix": "VT",
        "project_name": "Vibe Tracing",
        "architecture_constraints_hash": constraints_hash,
        "finalize_git_commit": git_commit,
        "finalize_constraints_path": constraints_path,
        "paths": {
            "prd": "docs/prd.md",
            "architecture_constraints": "docs/architecture_constraints.json",
            "task_list": "docs/task_list.json",
            "agent_claims": ".vibetracing/claims/current.json",
            "output_dir": "output",
        },
    }
    (proj / ".vibetracing" / "config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )


@pytest.fixture
def proj(tmp_path):
    """Set up a minimal project structure for check_governance tests.

    No physical base.json is written — baseline is reconstructed via git_show.
    """
    p = tmp_path / "mock_project"
    p.mkdir()

    (p / "docs").mkdir(parents=True, exist_ok=True)
    (p / ".vibetracing").mkdir(parents=True, exist_ok=True)

    # Write constraints file
    (p / "docs" / "architecture_constraints.json").write_text(
        json.dumps(BASE_CONSTRAINTS, indent=2), encoding="utf-8"
    )

    return p


# ---------------------------------------------------------------------------
# Test: No stored hash (not yet finalized) -> skip, is_valid=True
# ---------------------------------------------------------------------------


def test_no_stored_hash_skips_check(proj):
    """When config.json has no architecture_constraints_hash, check_governance
    returns is_valid=True with no warnings, risks, or gaps."""
    # Write config WITHOUT hash (not yet finalized)
    config = {"project_id": "PROJECT-VT", "paths": {}}
    (proj / ".vibetracing" / "config.json").write_text(
        json.dumps(config), encoding="utf-8"
    )

    engine = ArchitectureChangeProposalEngine(proj)
    res = engine.check_governance()

    assert res["is_valid"] is True
    assert len(res["errors"]) == 0
    assert len(res["warnings"]) == 0
    assert len(res["risks"]) == 0
    assert len(res["gaps"]) == 0


# ---------------------------------------------------------------------------
# Test: Hash match (no drift) -> is_valid=True, empty
# ---------------------------------------------------------------------------


def test_hash_match_no_drift(proj):
    """When the stored hash matches the current constraints file, check_governance
    returns is_valid=True with no warnings."""
    constraints_path = proj / "docs" / "architecture_constraints.json"
    current_hash = hashlib.sha256(constraints_path.read_bytes()).hexdigest()

    _write_config(proj, current_hash)

    engine = ArchitectureChangeProposalEngine(proj)
    res = engine.check_governance()

    assert res["is_valid"] is True
    assert len(res["errors"]) == 0
    assert len(res["warnings"]) == 0
    assert len(res["risks"]) == 0
    assert len(res["gaps"]) == 0


# ---------------------------------------------------------------------------
# Test: Hash mismatch + no finalize metadata -> warning about missing finalize
# ---------------------------------------------------------------------------


def test_hash_mismatch_no_finalize_metadata(proj):
    """When hash doesn't match but finalize_git_commit is missing, check_governance
    returns is_valid=True with a warning about missing finalize info."""
    constraints_path = proj / "docs" / "architecture_constraints.json"
    current_hash = hashlib.sha256(constraints_path.read_bytes()).hexdigest()

    # Write config with a DIFFERENT hash but no finalize_git_commit
    config = {
        "project_id": "PROJECT-VT",
        "architecture_constraints_hash": "different_hash_value",
        "paths": {},
    }
    (proj / ".vibetracing" / "config.json").write_text(
        json.dumps(config), encoding="utf-8"
    )

    engine = ArchitectureChangeProposalEngine(proj)
    res = engine.check_governance()

    assert res["is_valid"] is True
    assert len(res["warnings"]) > 0
    assert any("finalize" in w.lower() or "定稿" in w for w in res["warnings"])
    assert len(res["risks"]) > 0


# ---------------------------------------------------------------------------
# Test: Hash mismatch + git_show returns None -> warning about unreachable baseline
# ---------------------------------------------------------------------------


def test_hash_mismatch_git_show_fails(proj):
    """When hash doesn't match and git_show can't reconstruct the baseline,
    check_governance returns is_valid=True with a warning."""
    constraints_path = proj / "docs" / "architecture_constraints.json"
    current_hash = hashlib.sha256(constraints_path.read_bytes()).hexdigest()

    _write_config(proj, "different_hash_value", git_commit="deadbeef")

    with patch("vibe_tracing.architecture_change_proposal.git_show", return_value=None):
        engine = ArchitectureChangeProposalEngine(proj)
        res = engine.check_governance()

    assert res["is_valid"] is True
    assert len(res["warnings"]) > 0
    assert any("定稿" in w or "finalize" in w.lower() for w in res["warnings"])


# ---------------------------------------------------------------------------
# Test: Hash mismatch + diff found -> is_valid=True with diff warnings
# ---------------------------------------------------------------------------


def test_hash_mismatch_with_diff(proj):
    """When hash doesn't match and git_show reveals rule differences,
    check_governance returns is_valid=True with diff details in warnings."""
    constraints_path = proj / "docs" / "architecture_constraints.json"

    # Current constraints: modified severity
    modified_constraints = {
        "schema_version": "0.1",
        "project": {"project_id": "PROJECT-VT", "name": "Vibe Tracing", "stage": "mvp"},
        "storage_rules": [
            {
                "rule_id": "STORE-VT-001",
                "title": "MVP 不使用数据库",
                "severity": "should",  # Changed from "must"!
                "description": "No database in MVP",
            }
        ],
    }
    constraints_path.write_text(json.dumps(modified_constraints, indent=2), encoding="utf-8")

    # Hash of the MODIFIED file (different from stored)
    current_hash = hashlib.sha256(constraints_path.read_bytes()).hexdigest()
    _write_config(proj, "stored_old_hash_value", git_commit="abc123")

    # git_show returns the BASE version (original)
    base_content = json.dumps(BASE_CONSTRAINTS, indent=2)

    with patch("vibe_tracing.architecture_change_proposal.git_show", return_value=base_content):
        engine = ArchitectureChangeProposalEngine(proj)
        res = engine.check_governance()

    assert res["is_valid"] is True
    assert len(res["warnings"]) > 0
    # Warning should contain diff details
    assert any("STORE-VT-001" in w for w in res["warnings"])
    assert any("MODIFY" in w.upper() for w in res["warnings"])
    assert len(res["risks"]) > 0
    assert len(res["gaps"]) > 0


# ---------------------------------------------------------------------------
# Test: Hash mismatch + no structural diff (format change only)
# ---------------------------------------------------------------------------


def test_hash_mismatch_format_change_only(proj):
    """When hash doesn't match but the semantic content is the same (format change),
    check_governance returns is_valid=True with a format-change warning."""
    constraints_path = proj / "docs" / "architecture_constraints.json"

    # Reformat: different indentation, same content
    reformatted = json.dumps(BASE_CONSTRAINTS, indent=4)
    constraints_path.write_text(reformatted, encoding="utf-8")

    current_hash = hashlib.sha256(reformatted.encode()).hexdigest()
    _write_config(proj, "stored_old_hash_value", git_commit="abc123")

    # git_show returns the base with different formatting but same rules
    base_content = json.dumps(BASE_CONSTRAINTS, indent=2)

    with patch("vibe_tracing.architecture_change_proposal.git_show", return_value=base_content):
        engine = ArchitectureChangeProposalEngine(proj)
        res = engine.check_governance()

    assert res["is_valid"] is True
    assert len(res["warnings"]) > 0
    # Should mention format change
    assert any("格式" in w for w in res["warnings"])
    assert len(res["risks"]) > 0
    # No gaps for format-only changes
    assert len(res["gaps"]) == 0


# ---------------------------------------------------------------------------
# Test: _find_differences still works correctly (method unchanged)
# ---------------------------------------------------------------------------


def test_find_differences_detects_addition(proj):
    """_find_differences detects additions in the current config."""
    engine = ArchitectureChangeProposalEngine(proj)

    base = {"key_a": "value_a"}
    current = {"key_a": "value_a", "key_b": "value_b"}

    diffs = engine._find_differences(base, current)
    assert len(diffs) == 1
    assert diffs[0]["action"] == "add"
    assert diffs[0]["path"] == "key_b"


def test_find_differences_detects_deletion(proj):
    """_find_differences detects deletions from the base config."""
    engine = ArchitectureChangeProposalEngine(proj)

    base = {"key_a": "value_a", "key_b": "value_b"}
    current = {"key_a": "value_a"}

    diffs = engine._find_differences(base, current)
    assert len(diffs) == 1
    assert diffs[0]["action"] == "delete"
    assert diffs[0]["path"] == "key_b"


def test_find_differences_detects_modification(proj):
    """_find_differences detects value modifications."""
    engine = ArchitectureChangeProposalEngine(proj)

    base = {"key_a": "old_value"}
    current = {"key_a": "new_value"}

    diffs = engine._find_differences(base, current)
    assert len(diffs) == 1
    assert diffs[0]["action"] == "modify"
    assert diffs[0]["path"] == "key_a"


def test_find_differences_no_diff(proj):
    """_find_differences returns empty list for identical configs."""
    engine = ArchitectureChangeProposalEngine(proj)

    data = {"key_a": "value_a", "nested": {"inner": 42}}
    diffs = engine._find_differences(data, data)
    assert len(diffs) == 0


# ---------------------------------------------------------------------------
# Test: _compare_lists_by_id still works correctly (method unchanged)
# ---------------------------------------------------------------------------


def test_compare_lists_by_id_detects_addition(proj):
    """_compare_lists_by_id detects added items."""
    engine = ArchitectureChangeProposalEngine(proj)

    base_list = [{"rule_id": "R1", "value": "a"}]
    current_list = [
        {"rule_id": "R1", "value": "a"},
        {"rule_id": "R2", "value": "b"},
    ]

    diffs = engine._compare_lists_by_id(base_list, current_list, "rule_id", "rules")
    assert len(diffs) == 1
    assert diffs[0]["action"] == "add"
    assert diffs[0]["rule_id"] == "R2"


def test_compare_lists_by_id_detects_deletion(proj):
    """_compare_lists_by_id detects deleted items."""
    engine = ArchitectureChangeProposalEngine(proj)

    base_list = [
        {"rule_id": "R1", "value": "a"},
        {"rule_id": "R2", "value": "b"},
    ]
    current_list = [{"rule_id": "R1", "value": "a"}]

    diffs = engine._compare_lists_by_id(base_list, current_list, "rule_id", "rules")
    assert len(diffs) == 1
    assert diffs[0]["action"] == "delete"
    assert diffs[0]["rule_id"] == "R2"


def test_compare_lists_by_id_detects_modification(proj):
    """_compare_lists_by_id detects modified items."""
    engine = ArchitectureChangeProposalEngine(proj)

    base_list = [{"rule_id": "R1", "value": "old"}]
    current_list = [{"rule_id": "R1", "value": "new"}]

    diffs = engine._compare_lists_by_id(base_list, current_list, "rule_id", "rules")
    assert len(diffs) == 1
    assert diffs[0]["action"] == "modify"
    assert diffs[0]["rule_id"] == "R1"
