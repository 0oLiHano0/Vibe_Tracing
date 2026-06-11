"""
Tests for Architecture Compliance Checker.

Every test function declares which AC IDs it covers in its docstring.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from vibe_tracing.architecture_compliance_checker import (
    ArchitectureComplianceChecker,
    _is_stale_acceptance,
)


@pytest.fixture
def base_constraints_data():
    """Returns a basic dict matching the schema of architecture_constraints.json."""
    return {
        "schema_version": "0.1",
        "project": {"project_id": "PROJECT-VT", "name": "Vibe Tracing", "stage": "mvp"},
        "module_boundaries": [
            {
                "module_id": "MOD-VT-001",
                "name": "agent_runtime_adapter",
                "responsibility": "Adapter module",
                "allowed_to_call": ["MOD-VT-002"],
                "forbidden_to_call": ["MOD-VT-007"],
                "owned_files": ["cli.py", "agent_runtime_adapter.py"],
            },
            {
                "module_id": "MOD-VT-002",
                "name": "raw_input_loader",
                "responsibility": "Raw loader",
                "allowed_to_call": [],
                "forbidden_to_call": ["MOD-VT-006"],
                "owned_files": [
                    "raw_input_loader.py",
                    "prd_parser.py",
                    "task_loader.py",
                    "claim_loader.py",
                ],
            },
            {
                "module_id": "MOD-VT-003",
                "name": "schema_validator",
                "responsibility": "Validator",
                "allowed_to_call": [],
                "forbidden_to_call": [],
                "owned_files": ["schema_validator.py"],
            },
        ],
        "dependency_rules": [
            {
                "rule_id": "DEP-VT-001",
                "title": "Core 不得依赖特定 Agent Runtime",
                "severity": "must",
                "description": "Core must not import specific runtimes",
            },
            {
                "rule_id": "DEP-VT-002",
                "title": "Dashboard 不得依赖外部前端资源",
                "severity": "must",
                "description": "No CDN",
            },
        ],
        "storage_rules": [
            {
                "rule_id": "STORE-VT-001",
                "title": "MVP 不使用数据库",
                "severity": "must",
                "description": "No databases",
            }
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
    (vibetracing_dir / "claims/current.json").write_text("[]", encoding="utf-8")

    # Create source directory
    src_dir = tmp_path / "src/vibe_tracing"
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


def test_clean_workspace(temp_workspace):
    """covers: AC-VT-001-03, AC-VT-008-03"""
    tmp_path, constraints_data = temp_workspace
    # Create valid files in src
    src_dir = tmp_path / "src/vibe_tracing"
    (src_dir / "raw_input_loader.py").write_text("import json\n", encoding="utf-8")
    (src_dir / "schema_validator.py").write_text(
        "import jsonschema\n", encoding="utf-8"
    )

    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    results = checker.check(evidences=[], constraints_data=constraints_data)

    assert "architecture_compliance_status" in results
    assert "architecture_violations" in results
    assert "unclear_constraints" in results

    violations = results["architecture_violations"]
    assert len(violations) == 0, f"Expected no violations, got {violations}"

    # Verify rules are compliant
    statuses = {
        s["rule_id"]: s["status"] for s in results["architecture_compliance_status"]
    }
    assert statuses["STORE-VT-001"] == "compliant"
    assert statuses["DEP-VT-001"] == "compliant"
    # DEP-VT-002 is unclear because dashboard.html does not exist
    assert statuses["DEP-VT-002"] == "unclear"


def test_database_import_violation(temp_workspace):
    """covers: AC-VT-001-03, AC-VT-008-03"""
    tmp_path, constraints_data = temp_workspace
    src_dir = tmp_path / "src/vibe_tracing"
    (src_dir / "raw_input_loader.py").write_text(
        "import sqlalchemy\n", encoding="utf-8"
    )

    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_path": "src/vibe_tracing/raw_input_loader.py",
        }
    ]
    results = checker.check(evidences=evidences, constraints_data=constraints_data)

    violations = results["architecture_violations"]
    assert len(violations) == 2
    rule_ids = {v["rule_id"] for v in violations}
    assert "STORE-VT-001" in rule_ids
    assert "GATE-VT-006" in rule_ids

    db_violation = next(v for v in violations if v["rule_id"] == "STORE-VT-001")
    assert db_violation["evidence_id"] == "EVIDENCE-VT-001"
    assert "sqlalchemy" in db_violation["message"]

    statuses = {
        s["rule_id"]: s["status"] for s in results["architecture_compliance_status"]
    }
    assert statuses["STORE-VT-001"] == "violated"


def test_agent_runtime_import_violation(temp_workspace):
    """covers: AC-VT-001-03, AC-VT-008-03"""
    tmp_path, constraints_data = temp_workspace
    src_dir = tmp_path / "src/vibe_tracing"
    (src_dir / "raw_input_loader.py").write_text(
        "import claude_code\n", encoding="utf-8"
    )

    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    results = checker.check(evidences=[], constraints_data=constraints_data)

    violations = results["architecture_violations"]
    assert len(violations) == 2
    rule_ids = {v["rule_id"] for v in violations}
    assert "DEP-VT-001" in rule_ids
    assert "GATE-VT-006" in rule_ids

    dep_violation = next(v for v in violations if v["rule_id"] == "DEP-VT-001")
    assert dep_violation["evidence_id"] == "EVIDENCE-VT-999"  # Default fallback
    assert "claude_code" in dep_violation["message"]

    statuses = {
        s["rule_id"]: s["status"] for s in results["architecture_compliance_status"]
    }
    assert statuses["DEP-VT-001"] == "violated"


def test_forbidden_module_import_violation(temp_workspace):
    """covers: AC-VT-001-03, AC-VT-008-03"""
    tmp_path, constraints_data = temp_workspace
    src_dir = tmp_path / "src/vibe_tracing"
    (src_dir / "raw_input_loader.py").write_text(
        "import vibe_tracing.traceability.requirement_task_analyzer\n", encoding="utf-8"
    )

    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    results = checker.check(evidences=[], constraints_data=constraints_data)

    violations = results["architecture_violations"]
    assert len(violations) == 3
    rule_ids = {v["rule_id"] for v in violations}
    assert "MOD-VT-002" in rule_ids
    assert "GATE-VT-006" in rule_ids

    mod_violations = [v for v in violations if v["rule_id"] == "MOD-VT-002"]
    assert len(mod_violations) == 2
    messages = {v["message"] for v in mod_violations}
    assert any("禁止导入" in m or "Forbidden import" in m for m in messages)
    assert any("白名单" in m or "not in allowed" in m for m in messages)

    statuses = {
        s["rule_id"]: s["status"] for s in results["architecture_compliance_status"]
    }
    assert statuses["MOD-VT-002"] == "violated"


def test_allowed_module_import_violation(temp_workspace):
    """covers: AC-VT-001-03, AC-VT-008-03"""
    tmp_path, constraints_data = temp_workspace
    src_dir = tmp_path / "src/vibe_tracing"
    # schema_validator (MOD-VT-003) is allowed to call []
    # If it imports raw_input_loader, it violates the whitelist
    (src_dir / "schema_validator.py").write_text(
        "import vibe_tracing.raw_input_loader\n", encoding="utf-8"
    )

    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    results = checker.check(evidences=[], constraints_data=constraints_data)

    violations = results["architecture_violations"]
    assert len(violations) == 2
    rule_ids = {v["rule_id"] for v in violations}
    assert "MOD-VT-003" in rule_ids
    assert "GATE-VT-006" in rule_ids

    mod_violation = next(v for v in violations if v["rule_id"] == "MOD-VT-003")
    assert "白名单" in mod_violation["message"] or "not in allowed" in mod_violation["message"]

    statuses = {
        s["rule_id"]: s["status"] for s in results["architecture_compliance_status"]
    }
    assert statuses["MOD-VT-003"] == "violated"


def test_dashboard_compliance_and_violation(temp_workspace):
    """covers: AC-VT-001-03, AC-VT-008-03"""
    tmp_path, constraints_data = temp_workspace
    # 1. Compliant dashboard
    dash_file = tmp_path / "dashboard.html"
    dash_file.write_text(
        "<html><head><script src='local.js'></script></head></html>", encoding="utf-8"
    )

    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    results = checker.check(evidences=[], constraints_data=constraints_data)

    statuses = {
        s["rule_id"]: s["status"] for s in results["architecture_compliance_status"]
    }
    assert statuses["DEP-VT-002"] == "compliant"
    assert len(results["architecture_violations"]) == 0

    # 2. Violated dashboard with CDN url
    dash_file.write_text(
        "<html><head><script src='https://cdn.jsdelivr.net/npm/vue'></script></head></html>",
        encoding="utf-8",
    )

    results2 = checker.check(evidences=[], constraints_data=constraints_data)
    statuses2 = {
        s["rule_id"]: s["status"] for s in results2["architecture_compliance_status"]
    }
    assert statuses2["DEP-VT-002"] == "violated"
    assert len(results2["architecture_violations"]) == 2
    rule_ids = {v["rule_id"] for v in results2["architecture_violations"]}
    assert "DEP-VT-002" in rule_ids
    assert "GATE-VT-006" in rule_ids

    dash_violation = next(
        v for v in results2["architecture_violations"] if v["rule_id"] == "DEP-VT-002"
    )
    assert "外部" in dash_violation["message"] or "external" in dash_violation["message"].lower()


def test_missing_required_files(temp_workspace):
    """covers: AC-VT-001-03, AC-VT-008-03"""
    tmp_path, constraints_data = temp_workspace
    # Delete a required file
    (tmp_path / "docs/prd.md").unlink()

    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    results = checker.check(evidences=[], constraints_data=constraints_data)

    statuses = {
        s["rule_id"]: s["status"] for s in results["architecture_compliance_status"]
    }
    assert statuses["GATE-VT-001"] == "violated"
    assert len(results["architecture_violations"]) == 2
    rule_ids = {v["rule_id"] for v in results["architecture_violations"]}
    assert "GATE-VT-001" in rule_ids
    assert "GATE-VT-006" in rule_ids

    gate_violation = next(
        v for v in results["architecture_violations"] if v["rule_id"] == "GATE-VT-001"
    )
    assert "缺失" in gate_violation["message"] or "missing" in gate_violation["message"].lower()


def test_gate_compliance_logic(temp_workspace):
    """covers: AC-VT-001-03, AC-VT-008-03"""
    tmp_path, constraints_data = temp_workspace
    # In a clean workspace, the other MUST rules (unverifiable) will be returned as unclear
    # This should trigger GATE-VT-007 as unclear, and GATE-VT-006 as compliant (no MUST violations)
    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    results = checker.check(evidences=[], constraints_data=constraints_data)

    statuses = {
        s["rule_id"]: s["status"] for s in results["architecture_compliance_status"]
    }
    assert statuses["GATE-VT-006"] == "compliant"
    assert statuses["GATE-VT-007"] == "unclear"

    # If we introduce a violation (e.g. database import)
    (tmp_path / "src/vibe_tracing/raw_input_loader.py").write_text(
        "import sqlite3\n", encoding="utf-8"
    )

    results2 = checker.check(evidences=[], constraints_data=constraints_data)
    statuses2 = {
        s["rule_id"]: s["status"] for s in results2["architecture_compliance_status"]
    }
    assert statuses2["GATE-VT-006"] == "violated"


def test_check_uses_constraints_data(temp_workspace, base_constraints_data):
    """covers: REFACTOR-007 -- check() uses the provided constraints_data directly."""
    tmp_path, _ = temp_workspace

    src_dir = tmp_path / "src/vibe_tracing"
    (src_dir / "raw_input_loader.py").write_text("import json\n", encoding="utf-8")

    checker = ArchitectureComplianceChecker(project_root=tmp_path)

    results = checker.check(evidences=[], constraints_data=base_constraints_data)

    assert "architecture_compliance_status" in results
    violations = results["architecture_violations"]
    assert len(violations) == 0, f"Expected no violations, got {violations}"

    statuses = {
        s["rule_id"]: s["status"] for s in results["architecture_compliance_status"]
    }
    assert statuses["STORE-VT-001"] == "compliant"
    assert statuses["DEP-VT-001"] == "compliant"


# ---------------------------------------------------------------------------
# Tests for accepted_rules collection (T3 feature)
# ---------------------------------------------------------------------------


def test_accepted_rules_collected(temp_workspace):
    """Accepted manual rules appear in accepted_rules, not silently skipped."""
    tmp_path, constraints_data = temp_workspace
    constraints_data["architecture_principles"] = [
        {
            "principle_id": "PRINCIPLE-VT-TEST-01",
            "title": "Accepted manual rule",
            "severity": "must",
            "description": "A rule that has been manually accepted.",
            "verification_method": "manual",
            "accepted_by": "agent-001",
            "accepted_at": datetime.now(timezone.utc).isoformat(),
        }
    ]

    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    results = checker.check(evidences=[], constraints_data=constraints_data)

    # Rule should be in accepted_rules
    assert "accepted_rules" in results
    accepted_ids = [r["rule_id"] for r in results["accepted_rules"]]
    assert "PRINCIPLE-VT-TEST-01" in accepted_ids

    # Rule should NOT appear in status_list or unclear_list
    status_ids = [s["rule_id"] for s in results["architecture_compliance_status"]]
    assert "PRINCIPLE-VT-TEST-01" not in status_ids
    unclear_ids = [u["rule_id"] for u in results["unclear_constraints"]]
    assert "PRINCIPLE-VT-TEST-01" not in unclear_ids

    # Verify accepted_rules entry fields
    entry = next(
        r for r in results["accepted_rules"] if r["rule_id"] == "PRINCIPLE-VT-TEST-01"
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
            "principle_id": "PRINCIPLE-VT-STALE-01",
            "title": "Stale accepted rule",
            "severity": "must",
            "description": "An old accepted rule.",
            "verification_method": "manual",
            "accepted_by": "agent-001",
            "accepted_at": old_date,
        }
    ]

    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    results = checker.check(evidences=[], constraints_data=constraints_data)

    assert len(results["accepted_rules"]) == 1
    assert results["accepted_rules"][0]["rule_id"] == "PRINCIPLE-VT-STALE-01"
    assert results["accepted_rules"][0]["stale_acceptance"] is True


def test_unaccepted_manual_rules_not_in_unclear(temp_workspace):
    """Manual rules without accepted_by are in status_list but not unclear_list."""
    tmp_path, constraints_data = temp_workspace
    constraints_data["architecture_principles"] = [
        {
            "principle_id": "PRINCIPLE-VT-UNACC-01",
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
    assert "PRINCIPLE-VT-UNACC-01" in status_ids
    entry = next(
        s
        for s in results["architecture_compliance_status"]
        if s["rule_id"] == "PRINCIPLE-VT-UNACC-01"
    )
    assert entry["status"] == "unclear"
    assert entry["verification_method"] == "manual"

    # Should NOT appear in unclear_constraints (so it does not block GATE-VT-007)
    unclear_ids = [u["rule_id"] for u in results["unclear_constraints"]]
    assert "PRINCIPLE-VT-UNACC-01" not in unclear_ids

    # Should NOT appear in accepted_rules
    accepted_ids = [r["rule_id"] for r in results["accepted_rules"]]
    assert "PRINCIPLE-VT-UNACC-01" not in accepted_ids


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
