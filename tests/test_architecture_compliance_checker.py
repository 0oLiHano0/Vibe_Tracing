"""
Tests for Architecture Compliance Checker.

Every test function declares which AC IDs it covers in its docstring.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from vibe_tracing.domain.compliance.checker import (
    ArchitectureComplianceChecker,
    _is_stale_acceptance,
)


@pytest.fixture
def base_constraints_data():
    """Returns a generic constraints dict for testing module boundary logic."""
    return {
        "module_boundaries": [
            {
                "module_id": "MOD-A",
                "name": "module_alpha",
                "responsibility": "Alpha module — may call B, forbidden to call C",
                "allowed_to_call": ["MOD-B"],
                "forbidden_to_call": ["MOD-C"],
                "owned_files": ["module_a.py"],
            },
            {
                "module_id": "MOD-B",
                "name": "module_beta",
                "responsibility": "Beta module — empty allowed_to_call means nothing is whitelisted",
                "allowed_to_call": [],
                "forbidden_to_call": [],
                "owned_files": ["module_b.py"],
            },
            {
                "module_id": "MOD-C",
                "name": "module_gamma",
                "responsibility": "Gamma module — no restrictions",
                "allowed_to_call": [],
                "forbidden_to_call": [],
                "owned_files": ["module_c.py"],
            },
        ],
    }


@pytest.fixture
def temp_workspace(tmp_path, base_constraints_data):
    """Sets up a temporary workspace with standard folders and a constraints file.

    Returns a tuple of (project_root_path, constraints_data_dict).
    """
    # Create standard folders
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    vibetracing_dir = tmp_path / ".vibetracing"
    vibetracing_dir.mkdir(parents=True)
    (vibetracing_dir / "claims").mkdir(parents=True, exist_ok=True)

    # Write constraints file
    constraints_file = docs_dir / "architecture_constraints.json"
    constraints_file.write_text(
        json.dumps(base_constraints_data, indent=2), encoding="utf-8"
    )

    # Write other standard files
    (docs_dir / "prd.md").write_text("# PRD", encoding="utf-8")
    (docs_dir / "task_list.json").write_text("[]", encoding="utf-8")
    # Empty claims directory -- no CLAIM-*.json files needed

    # Create source directory (abstract project, not VT-specific)
    src_dir = tmp_path / "src/project_x"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text("", encoding="utf-8")

    return tmp_path, base_constraints_data


def test_init_and_missing_constraints(tmp_path):
    """covers: AC-VT-001-03, AC-VT-008-03"""
    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    # constraints_path is set to the default even when not provided
    assert checker.constraints_path == tmp_path / "docs" / "architecture_constraints.json"


def test_check_requires_constraints_data(tmp_path):
    """covers: AC-VT-001-03 -- check() requires a constraints_data argument."""
    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    with pytest.raises(TypeError):
        checker.check(evidences=[])


def test_forbidden_module_import_violation(temp_workspace):
    """MOD-A imports module_c (owned by MOD-C, which is in MOD-A's forbidden_to_call
    and not in its allowed_to_call). Should produce two violations."""
    tmp_path, constraints_data = temp_workspace
    src_dir = tmp_path / "src/project_x"
    (src_dir / "module_a.py").write_text(
        "import project_x.sub.module_c\n", encoding="utf-8"
    )

    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    results = checker.check(evidences=[], constraints_data=constraints_data)

    violations = results["architecture_violations"]
    assert len(violations) == 2
    rule_ids = {v["rule_id"] for v in violations}
    assert "MOD-A" in rule_ids

    mod_violations = [v for v in violations if v["rule_id"] == "MOD-A"]
    assert len(mod_violations) == 2
    messages = {v["message"] for v in mod_violations}
    assert any("禁止导入" in m or "Forbidden import" in m for m in messages)
    assert any("白名单" in m or "not in allowed" in m for m in messages)

    statuses = {
        s["rule_id"]: s["status"] for s in results["architecture_compliance_status"]
    }
    assert statuses["MOD-A"] == "violated"


def test_allowed_module_import_violation(temp_workspace):
    """MOD-B has allowed_to_call=[] (empty whitelist). Importing module_c
    (owned by MOD-C) triggers a whitelist violation."""
    tmp_path, constraints_data = temp_workspace
    src_dir = tmp_path / "src/project_x"
    (src_dir / "module_b.py").write_text(
        "import project_x.sub.module_c\n", encoding="utf-8"
    )

    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    results = checker.check(evidences=[], constraints_data=constraints_data)

    violations = results["architecture_violations"]
    assert len(violations) == 1
    rule_ids = {v["rule_id"] for v in violations}
    assert "MOD-B" in rule_ids

    mod_violation = next(v for v in violations if v["rule_id"] == "MOD-B")
    assert "白名单" in mod_violation["message"] or "not in allowed" in mod_violation["message"]

    statuses = {
        s["rule_id"]: s["status"] for s in results["architecture_compliance_status"]
    }
    assert statuses["MOD-B"] == "violated"



# ---------------------------------------------------------------------------
# Tests for accepted_rules collection (T3 feature)
# ---------------------------------------------------------------------------


def test_accepted_rules_collected(temp_workspace):
    """Accepted manual rules appear in accepted_rules, not silently skipped."""
    tmp_path, constraints_data = temp_workspace
    now = datetime.now(timezone.utc).isoformat()
    constraints_data["architecture_principles"] = [
        {
            "principle_id": "PRINCIPLE-TEST-01",
            "title": "Accepted manual rule",
            "severity": "must",
            "description": "A rule that has been manually accepted.",
            "verification_method": "manual",
        }
    ]

    human_decisions = {
        "version": "1.0",
        "decisions": [
            {
                "category": "accepted_rule",
                "targetId": "PRINCIPLE-TEST-01",
                "action": "accept",
                "decidedBy": "agent-001",
                "timestamp": now,
            }
        ],
    }

    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    results = checker.check(evidences=[], constraints_data=constraints_data, human_decisions=human_decisions)

    # Rule should be in accepted_rules
    assert "accepted_rules" in results
    accepted_ids = [r["rule_id"] for r in results["accepted_rules"]]
    assert "PRINCIPLE-TEST-01" in accepted_ids

    # Rule should NOT appear in status_list or unclear_list
    status_ids = [s["rule_id"] for s in results["architecture_compliance_status"]]
    assert "PRINCIPLE-TEST-01" not in status_ids
    unclear_ids = [u["rule_id"] for u in results["unclear_constraints"]]
    assert "PRINCIPLE-TEST-01" not in unclear_ids

    # Verify accepted_rules entry fields
    entry = next(
        r for r in results["accepted_rules"] if r["rule_id"] == "PRINCIPLE-TEST-01"
    )
    assert entry["accepted_by"] == "agent-001"
    assert entry["verification_method"] == "manual"
    assert entry["stale_acceptance"] is False


def test_stale_acceptance_detected(temp_workspace):
    """Accepted rules older than 30 days are marked stale."""
    tmp_path, constraints_data = temp_workspace
    old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    constraints_data["architecture_principles"] = [
        {
            "principle_id": "PRINCIPLE-STALE-01",
            "title": "Stale accepted rule",
            "severity": "must",
            "description": "An old accepted rule.",
            "verification_method": "manual",
        }
    ]

    human_decisions = {
        "version": "1.0",
        "decisions": [
            {
                "category": "accepted_rule",
                "targetId": "PRINCIPLE-STALE-01",
                "action": "accept",
                "decidedBy": "agent-001",
                "timestamp": old_date,
            }
        ],
    }

    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    results = checker.check(evidences=[], constraints_data=constraints_data, human_decisions=human_decisions)

    assert len(results["accepted_rules"]) == 1
    assert results["accepted_rules"][0]["rule_id"] == "PRINCIPLE-STALE-01"
    assert results["accepted_rules"][0]["stale_acceptance"] is True


def test_unaccepted_manual_rules_not_in_unclear(temp_workspace):
    """Manual rules without accepted_by are in status_list but not unclear_list."""
    tmp_path, constraints_data = temp_workspace
    constraints_data["architecture_principles"] = [
        {
            "principle_id": "PRINCIPLE-UNACC-01",
            "title": "Unaccepted manual rule",
            "severity": "must",
            "description": "A manual rule that has not been accepted.",
            "verification_method": "manual",
        }
    ]

    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    results = checker.check(evidences=[], constraints_data=constraints_data)

    # Should appear in status_list as unclear
    status_ids = [s["rule_id"] for s in results["architecture_compliance_status"]]
    assert "PRINCIPLE-UNACC-01" in status_ids
    entry = next(
        s
        for s in results["architecture_compliance_status"]
        if s["rule_id"] == "PRINCIPLE-UNACC-01"
    )
    assert entry["status"] == "unclear"
    assert entry["verification_method"] == "manual"

    # Should appear in unclear_constraints (consumed by gate engine Rule 2.1)
    unclear_ids = [u["rule_id"] for u in results["unclear_constraints"]]
    assert "PRINCIPLE-UNACC-01" in unclear_ids

    # Should NOT appear in accepted_rules
    accepted_ids = [r["rule_id"] for r in results["accepted_rules"]]
    assert "PRINCIPLE-UNACC-01" not in accepted_ids


# ---------------------------------------------------------------------------
# Tests for _is_stale_acceptance helper
# ---------------------------------------------------------------------------


class TestIsStaleAcceptance:
    """Unit tests for the _is_stale_acceptance helper function."""

    def test_recent_timestamp_is_not_stale(self):
        recent = datetime.now(timezone.utc).isoformat()
        assert _is_stale_acceptance(recent, threshold_days=30) is False

    def test_old_timestamp_is_stale(self):
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        assert _is_stale_acceptance(old, threshold_days=30) is True

    def test_empty_string_is_not_stale(self):
        assert _is_stale_acceptance("", threshold_days=30) is False

    def test_none_is_not_stale(self):
        assert _is_stale_acceptance(None, threshold_days=30) is False

    def test_exactly_at_threshold_is_not_stale(self):
        """Exactly 30 days old should NOT be stale (only > 30 is stale)."""
        boundary = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        assert _is_stale_acceptance(boundary, threshold_days=30) is False

    def test_one_day_past_threshold_is_stale(self):
        just_over = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        assert _is_stale_acceptance(just_over, threshold_days=30) is True

    def test_z_suffix_parsed_correctly(self):
        """ISO format with 'Z' suffix should be parsed correctly."""
        old = (datetime.now(timezone.utc) - timedelta(days=60)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        assert _is_stale_acceptance(old, threshold_days=30) is True

    def test_custom_threshold(self):
        recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        assert _is_stale_acceptance(recent, threshold_days=7) is False
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        assert _is_stale_acceptance(old, threshold_days=7) is True
