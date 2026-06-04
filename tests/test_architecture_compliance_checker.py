"""
Tests for Architecture Compliance Checker.

Every test function declares which AC IDs it covers in its docstring.
"""

import json
import pytest

from vibe_tracing.architecture_compliance_checker import ArchitectureComplianceChecker


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
    """Sets up a temporary workspace with standard folders and a constraints file."""
    # Create standard folders
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    vibetracing_dir = tmp_path / ".vibetracing"
    vibetracing_dir.mkdir(parents=True)

    # Write constraints file
    constraints_file = docs_dir / "architecture_constraints.json"
    constraints_file.write_text(
        json.dumps(base_constraints_data, indent=2), encoding="utf-8"
    )

    # Write other standard files
    (docs_dir / "prd.md").write_text("# PRD", encoding="utf-8")
    (docs_dir / "task_list.json").write_text("[]", encoding="utf-8")
    (vibetracing_dir / "agent_claims.json").write_text("[]", encoding="utf-8")

    # Create source directory
    src_dir = tmp_path / "src/vibe_tracing"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text("", encoding="utf-8")

    return tmp_path


def test_init_and_missing_constraints(tmp_path):
    """covers: AC-VT-001-03, AC-VT-008-03"""
    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    with pytest.raises(
        FileNotFoundError, match="Architecture constraints file not found"
    ):
        checker._load_constraints()


def test_invalid_json_constraints(tmp_path):
    """covers: AC-VT-001-03, AC-VT-008-03"""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    constraints_file = docs_dir / "architecture_constraints.json"
    constraints_file.write_text("{invalid json", encoding="utf-8")

    checker = ArchitectureComplianceChecker(project_root=tmp_path)
    with pytest.raises(ValueError, match="Failed to parse architecture constraints"):
        checker._load_constraints()


def test_clean_workspace(temp_workspace):
    """covers: AC-VT-001-03, AC-VT-008-03"""
    # Create valid files in src
    src_dir = temp_workspace / "src/vibe_tracing"
    (src_dir / "raw_input_loader.py").write_text("import json\n", encoding="utf-8")
    (src_dir / "schema_validator.py").write_text(
        "import jsonschema\n", encoding="utf-8"
    )

    checker = ArchitectureComplianceChecker(project_root=temp_workspace)
    results = checker.check(evidences=[])

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
    src_dir = temp_workspace / "src/vibe_tracing"
    (src_dir / "raw_input_loader.py").write_text(
        "import sqlalchemy\n", encoding="utf-8"
    )

    checker = ArchitectureComplianceChecker(project_root=temp_workspace)
    evidences = [
        {
            "evidence_id": "EVIDENCE-VT-001",
            "source_path": "src/vibe_tracing/raw_input_loader.py",
        }
    ]
    results = checker.check(evidences=evidences)

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
    src_dir = temp_workspace / "src/vibe_tracing"
    (src_dir / "raw_input_loader.py").write_text(
        "import claude_code\n", encoding="utf-8"
    )

    checker = ArchitectureComplianceChecker(project_root=temp_workspace)
    results = checker.check(evidences=[])

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
    src_dir = temp_workspace / "src/vibe_tracing"
    (src_dir / "raw_input_loader.py").write_text(
        "import vibe_tracing.traceability.requirement_task_analyzer\n", encoding="utf-8"
    )

    checker = ArchitectureComplianceChecker(project_root=temp_workspace)
    results = checker.check(evidences=[])

    violations = results["architecture_violations"]
    assert len(violations) == 3
    rule_ids = {v["rule_id"] for v in violations}
    assert "MOD-VT-002" in rule_ids
    assert "GATE-VT-006" in rule_ids

    mod_violations = [v for v in violations if v["rule_id"] == "MOD-VT-002"]
    assert len(mod_violations) == 2
    messages = {v["message"] for v in mod_violations}
    assert any("Forbidden import" in m for m in messages)
    assert any("not in allowed_to_call whitelist" in m for m in messages)

    statuses = {
        s["rule_id"]: s["status"] for s in results["architecture_compliance_status"]
    }
    assert statuses["MOD-VT-002"] == "violated"


def test_allowed_module_import_violation(temp_workspace):
    """covers: AC-VT-001-03, AC-VT-008-03"""
    src_dir = temp_workspace / "src/vibe_tracing"
    # schema_validator (MOD-VT-003) is allowed to call []
    # If it imports raw_input_loader, it violates the whitelist
    (src_dir / "schema_validator.py").write_text(
        "import vibe_tracing.raw_input_loader\n", encoding="utf-8"
    )

    checker = ArchitectureComplianceChecker(project_root=temp_workspace)
    results = checker.check(evidences=[])

    violations = results["architecture_violations"]
    assert len(violations) == 2
    rule_ids = {v["rule_id"] for v in violations}
    assert "MOD-VT-003" in rule_ids
    assert "GATE-VT-006" in rule_ids

    mod_violation = next(v for v in violations if v["rule_id"] == "MOD-VT-003")
    assert "not in allowed_to_call whitelist" in mod_violation["message"]

    statuses = {
        s["rule_id"]: s["status"] for s in results["architecture_compliance_status"]
    }
    assert statuses["MOD-VT-003"] == "violated"


def test_dashboard_compliance_and_violation(temp_workspace):
    """covers: AC-VT-001-03, AC-VT-008-03"""
    # 1. Compliant dashboard
    dash_file = temp_workspace / "dashboard.html"
    dash_file.write_text(
        "<html><head><script src='local.js'></script></head></html>", encoding="utf-8"
    )

    checker = ArchitectureComplianceChecker(project_root=temp_workspace)
    results = checker.check(evidences=[])

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

    results2 = checker.check(evidences=[])
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
    assert "external front-end resources" in dash_violation["message"]


def test_missing_required_files(temp_workspace):
    """covers: AC-VT-001-03, AC-VT-008-03"""
    # Delete a required file
    (temp_workspace / "docs/prd.md").unlink()

    checker = ArchitectureComplianceChecker(project_root=temp_workspace)
    results = checker.check(evidences=[])

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
    assert "Required input files are missing" in gate_violation["message"]


def test_gate_compliance_logic(temp_workspace):
    """covers: AC-VT-001-03, AC-VT-008-03"""
    # In a clean workspace, the other MUST rules (unverifiable) will be returned as unclear
    # This should trigger GATE-VT-007 as unclear, and GATE-VT-006 as compliant (no MUST violations)
    checker = ArchitectureComplianceChecker(project_root=temp_workspace)
    results = checker.check(evidences=[])

    statuses = {
        s["rule_id"]: s["status"] for s in results["architecture_compliance_status"]
    }
    assert statuses["GATE-VT-006"] == "compliant"
    assert statuses["GATE-VT-007"] == "unclear"

    # If we introduce a violation (e.g. database import)
    (temp_workspace / "src/vibe_tracing/raw_input_loader.py").write_text(
        "import sqlite3\n", encoding="utf-8"
    )

    results2 = checker.check(evidences=[])
    statuses2 = {
        s["rule_id"]: s["status"] for s in results2["architecture_compliance_status"]
    }
    assert statuses2["GATE-VT-006"] == "violated"
