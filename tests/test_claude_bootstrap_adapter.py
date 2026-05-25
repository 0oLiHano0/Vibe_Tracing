"""
Tests for Claude Code Bootstrap Loader, Validator, and Adapter.

Covers:
  AC-VT-009-03 — Subagent and skill definitions must be reviewable.
  GATE-VT-013 — Claude Code bootstrap configuration must be reviewable.
"""

import json
import shutil
from pathlib import Path
import pytest

from vibe_tracing.claude_code_bootstrap_adapter import ClaudeCodeBootstrapAdapter


@pytest.fixture
def temp_project(tmp_path):
    """Set up a temporary project directory with schema and bootstrap configurations."""
    proj = tmp_path / "mock_project"
    proj.mkdir()

    # Create schemas directory and copy schemas
    (proj / "schemas").mkdir()
    real_schemas = Path(__file__).parent.parent / "schemas"
    for schema_file in real_schemas.glob("*.json"):
        (proj / "schemas" / schema_file.name).write_text(
            schema_file.read_text(encoding="utf-8"), encoding="utf-8"
        )

    # Copy fixtures to claude_bootstrap/
    (proj / ".vibetracing/claude_bootstrap" / "subagents").mkdir(parents=True)
    (proj / ".vibetracing/claude_bootstrap" / "skills").mkdir(parents=True)

    fixtures_dir = Path(__file__).parent / "fixtures" / "claude_bootstrap"
    shutil.copy(
        fixtures_dir / "bootstrap_manifest.json",
        proj / ".vibetracing/claude_bootstrap" / "bootstrap_manifest.json",
    )
    shutil.copy(
        fixtures_dir / "subagents" / "researcher.json",
        proj / ".vibetracing/claude_bootstrap" / "subagents" / "researcher.json",
    )
    shutil.copy(
        fixtures_dir / "skills" / "view_file.json",
        proj / ".vibetracing/claude_bootstrap" / "skills" / "view_file.json",
    )

    return proj


def test_valid_bootstrap_load(temp_project):
    """covers: AC-VT-009-03"""
    adapter = ClaudeCodeBootstrapAdapter(temp_project)
    report = adapter.check_governance_rules()

    assert report["is_valid"] is True
    assert len(report["errors"]) == 0
    assert len(report["warnings"]) == 0
    assert len(report["risks"]) == 0
    assert len(report["gaps"]) == 0


def test_missing_manifest(temp_project):
    """covers: AC-VT-009-03, GATE-VT-013"""
    manifest_file = (
        temp_project / ".vibetracing/claude_bootstrap" / "bootstrap_manifest.json"
    )
    manifest_file.unlink()

    adapter = ClaudeCodeBootstrapAdapter(temp_project)
    report = adapter.check_governance_rules()

    assert report["is_valid"] is False
    assert any("manifest not found" in err for err in report["errors"])
    assert len(report["risks"]) > 0
    assert report["risks"][0]["severity"] == "must"


def test_manifest_schema_error(temp_project):
    """covers: AC-VT-009-03, GATE-VT-013"""
    manifest_file = (
        temp_project / ".vibetracing/claude_bootstrap" / "bootstrap_manifest.json"
    )
    # Overwrite manifest with invalid JSON structure (runtime is invalid pattern)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["runtime"] = "invalid-runtime-name"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

    adapter = ClaudeCodeBootstrapAdapter(temp_project)
    report = adapter.check_governance_rules()

    assert report["is_valid"] is False
    assert any("Bootstrap manifest schema violation" in err for err in report["errors"])
    assert len(report["risks"]) > 0
    assert report["risks"][0]["severity"] == "must"


def test_missing_subagent_file(temp_project):
    """covers: AC-VT-009-03, GATE-VT-013"""
    subagent_file = (
        temp_project / ".vibetracing/claude_bootstrap" / "subagents" / "researcher.json"
    )
    subagent_file.unlink()

    adapter = ClaudeCodeBootstrapAdapter(temp_project)
    report = adapter.check_governance_rules()

    assert report["is_valid"] is False
    assert any("Subagent definition file not found" in err for err in report["errors"])


def test_subagent_schema_error(temp_project):
    """covers: AC-VT-009-03, GATE-VT-013"""
    subagent_file = (
        temp_project / ".vibetracing/claude_bootstrap" / "subagents" / "researcher.json"
    )
    subagent = json.loads(subagent_file.read_text(encoding="utf-8"))
    subagent["subagent_id"] = "INVALID-ID-VT-99"  # invalid ID pattern
    subagent_file.write_text(json.dumps(subagent), encoding="utf-8")

    adapter = ClaudeCodeBootstrapAdapter(temp_project)
    report = adapter.check_governance_rules()

    assert report["is_valid"] is False
    assert any("subagent_id" in err for err in report["errors"])


def test_skill_not_in_manifest(temp_project):
    """covers: AC-VT-009-03, GATE-VT-013"""
    # subagent lists SKILL-VT-002, but manifest only registers SKILL-VT-001
    subagent_file = (
        temp_project / ".vibetracing/claude_bootstrap" / "subagents" / "researcher.json"
    )
    subagent = json.loads(subagent_file.read_text(encoding="utf-8"))
    subagent["allowed_skills"].append("SKILL-VT-002")
    subagent_file.write_text(json.dumps(subagent), encoding="utf-8")

    adapter = ClaudeCodeBootstrapAdapter(temp_project)
    report = adapter.check_governance_rules()

    assert report["is_valid"] is False
    assert any(
        "requests skill 'SKILL-VT-002' which is not registered" in err
        for err in report["errors"]
    )


def test_governance_risk_researcher_edit(temp_project):
    """covers: AC-VT-009-03, GATE-VT-013"""
    # Grant researcher subagent the write permission skill SKILL-VT-002 (edit_file)
    # Register SKILL-VT-002 in manifest
    manifest_file = (
        temp_project / ".vibetracing/claude_bootstrap" / "bootstrap_manifest.json"
    )
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["skills"].append(
        {
            "id": "SKILL-VT-002",
            "name": "edit_file",
            "definition_file": "skills/edit_file.json",
            "purpose": "Edit file contents",
        }
    )
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

    # Write skill definition file
    (
        temp_project / ".vibetracing/claude_bootstrap" / "skills" / "edit_file.json"
    ).write_text(
        json.dumps(
            {
                "skill_id": "SKILL-VT-002",
                "name": "edit_file",
                "purpose": "Modify code",
                "inputs": [{"name": "path", "type": "string"}],
                "outputs": [{"name": "success", "type": "boolean"}],
                "boundaries": [],
                "constraints": ["must not override factual evidence fields"],
            }
        ),
        encoding="utf-8",
    )

    # Add SKILL-VT-002 to researcher's allowed_skills
    subagent_file = (
        temp_project / ".vibetracing/claude_bootstrap" / "subagents" / "researcher.json"
    )
    subagent = json.loads(subagent_file.read_text(encoding="utf-8"))
    subagent["allowed_skills"].append("SKILL-VT-002")
    subagent_file.write_text(json.dumps(subagent), encoding="utf-8")

    adapter = ClaudeCodeBootstrapAdapter(temp_project)
    report = adapter.check_governance_rules()

    # Errors should be empty because configurations are structurally valid
    assert len(report["errors"]) == 0
    # But should emit a governance warning about researcher having write permission
    assert len(report["warnings"]) == 1
    assert "write permission" in report["warnings"][0]

    # Warnings are mapped to should-severity risks
    assert len(report["risks"]) == 1
    assert report["risks"][0]["severity"] == "should"
    assert "Subagent 职责" in report["risks"][0]["business_impact"]
