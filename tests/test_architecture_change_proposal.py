"""
Tests for Architecture Change Proposal Engine.

Covers:
  AC-VT-009-04 — Architecture change proposals must be explicitly governed.
  GATE-VT-014 — Architecture constraint changes must not be silent edits.
"""

import json
from pathlib import Path
import pytest

from vibe_tracing.architecture_change_proposal import ArchitectureChangeProposalEngine


@pytest.fixture
def temp_proposal_workspace(tmp_path):
    """Set up a temporary project structure with schema and architecture folders."""
    proj = tmp_path / "mock_project"
    proj.mkdir()

    # Create schemas directory and copy schemas
    (proj / "schemas").mkdir()
    real_schemas = Path(__file__).parent.parent / "schemas"
    for schema_file in real_schemas.glob("*.json"):
        (proj / "schemas" / schema_file.name).write_text(
            schema_file.read_text(encoding="utf-8"), encoding="utf-8"
        )

    # Create architecture directories
    (proj / "docs").mkdir(parents=True, exist_ok=True)
    (proj / ".vibetracing").mkdir(parents=True, exist_ok=True)

    # Define a base constraints dict
    base_constraints = {
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

    # Write constraints baseline and current version
    (proj / ".vibetracing/architecture_constraints.base.json").write_text(
        json.dumps(base_constraints, indent=2), encoding="utf-8"
    )
    (proj / "docs/architecture_constraints.json").write_text(
        json.dumps(base_constraints, indent=2), encoding="utf-8"
    )

    return proj


def test_valid_no_drift(temp_proposal_workspace):
    """covers: AC-VT-009-04"""
    engine = ArchitectureChangeProposalEngine(temp_proposal_workspace)
    res = engine.check_governance()

    assert res["is_valid"] is True
    assert len(res["errors"]) == 0
    assert len(res["warnings"]) == 0
    assert len(res["risks"]) == 0
    assert len(res["gaps"]) == 0


def test_drift_missing_change_log(temp_proposal_workspace):
    """covers: GATE-VT-014"""
    # Silently modify constraints: change severity from "must" to "should"
    curr_constraints = {
        "schema_version": "0.1",
        "project": {"project_id": "PROJECT-VT", "name": "Vibe Tracing", "stage": "mvp"},
        "storage_rules": [
            {
                "rule_id": "STORE-VT-001",
                "title": "MVP 不使用数据库",
                "severity": "should",  # Modified!
                "description": "No database in MVP",
            }
        ],
    }
    (temp_proposal_workspace / "docs/architecture_constraints.json").write_text(
        json.dumps(curr_constraints, indent=2), encoding="utf-8"
    )

    engine = ArchitectureChangeProposalEngine(temp_proposal_workspace)
    res = engine.check_governance()

    # Docs/architecture_change_log.md does not exist
    assert res["is_valid"] is False
    assert any(
        "缺失 docs/architecture_change_log.md 变更日志" in err for err in res["errors"]
    )
    assert len(res["risks"]) == 1
    assert res["risks"][0]["severity"] == "must"


def test_drift_undocumented(temp_proposal_workspace):
    """covers: GATE-VT-014"""
    # Silently modify constraints: change severity from "must" to "should"
    curr_constraints = {
        "schema_version": "0.1",
        "project": {"project_id": "PROJECT-VT", "name": "Vibe Tracing", "stage": "mvp"},
        "storage_rules": [
            {
                "rule_id": "STORE-VT-001",
                "title": "MVP 不使用数据库",
                "severity": "should",  # Modified!
                "description": "No database in MVP",
            }
        ],
    }
    (temp_proposal_workspace / "docs/architecture_constraints.json").write_text(
        json.dumps(curr_constraints, indent=2), encoding="utf-8"
    )

    # Create architecture_change_log.md but don't mention STORE-VT-001
    (temp_proposal_workspace / "docs").mkdir(exist_ok=True)
    (temp_proposal_workspace / "docs/architecture_change_log.md").write_text(
        "# Vibe Tracing Architecture Change Log\nSome unrelated rule changes here.",
        encoding="utf-8",
    )

    engine = ArchitectureChangeProposalEngine(temp_proposal_workspace)
    res = engine.check_governance()

    assert res["is_valid"] is False
    assert any(
        "STORE-VT-001" in err and "未找到对应的变更说明" in err for err in res["errors"]
    )
    assert len(res["risks"]) == 1
    assert res["risks"][0]["severity"] == "must"


def test_drift_documented(temp_proposal_workspace):
    """covers: GATE-VT-014, AC-VT-009-04"""
    # Modify constraints: change severity from "must" to "should"
    curr_constraints = {
        "schema_version": "0.1",
        "project": {"project_id": "PROJECT-VT", "name": "Vibe Tracing", "stage": "mvp"},
        "storage_rules": [
            {
                "rule_id": "STORE-VT-001",
                "title": "MVP 不使用数据库",
                "severity": "should",  # Modified!
                "description": "No database in MVP",
            }
        ],
    }
    (temp_proposal_workspace / "docs/architecture_constraints.json").write_text(
        json.dumps(curr_constraints, indent=2), encoding="utf-8"
    )

    # Create architecture_change_log.md and mention STORE-VT-001
    (temp_proposal_workspace / "docs").mkdir(exist_ok=True)
    (temp_proposal_workspace / "docs/architecture_change_log.md").write_text(
        "# Vibe Tracing Architecture Change Log\nWe modified rule STORE-VT-001 to should severity.",
        encoding="utf-8",
    )

    engine = ArchitectureChangeProposalEngine(temp_proposal_workspace)
    res = engine.check_governance()

    assert res["is_valid"] is True
    assert len(res["errors"]) == 0
    assert len(res["warnings"]) == 1
    assert "STORE-VT-001" in res["warnings"][0]
    assert len(res["risks"]) == 1
    assert res["risks"][0]["severity"] == "should"
