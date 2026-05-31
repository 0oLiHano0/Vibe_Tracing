"""
Tests for Claude Code bootstrap and architecture change proposal schemas.

Covers:
  AC-VT-009-02 — Self-bootstrap must generate traceable governance outputs.
  AC-VT-009-03 — Subagent and skill definitions must be reviewable.
  AC-VT-009-04 — Architecture change proposals must be explicitly governed.
"""

import json
import pytest
from pathlib import Path
from jsonschema import validate, ValidationError

SCHEMAS_DIR = Path(__file__).parent.parent / "src" / "vibe_tracing" / "schemas"


def load_schema(name: str) -> dict:
    """Load a JSON schema from the schemas/ directory by filename."""
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Minimal valid document generators
# ---------------------------------------------------------------------------


def _minimal_bootstrap_manifest() -> dict:
    return {
        "schema_version": "1.0.0",
        "runtime": "claude-code",
        "subagents": [
            {
                "id": "SUBAGENT-VT-001",
                "name": "Researcher",
                "definition_file": "claude_bootstrap/subagents/researcher.json",
                "role": "researcher",
            }
        ],
        "skills": [
            {
                "id": "SKILL-VT-001",
                "name": "View File",
                "definition_file": "claude_bootstrap/skills/view_file.json",
                "purpose": "Read file content",
            }
        ],
        "forbidden_actions": ["modify_architecture_without_proposal"],
        "structured_governance_outputs": ["architecture_change_proposal"],
    }


def _minimal_subagent_definition() -> dict:
    return {
        "subagent_id": "SUBAGENT-VT-001",
        "role": "Codebase Researcher",
        "responsibilities": ["Read files", "Perform grep searches"],
        "allowed_skills": ["SKILL-VT-001"],
        "forbidden_behaviors": ["Write code files"],
        "required_outputs": ["research_notes.md"],
    }


def _minimal_skill_definition() -> dict:
    return {
        "skill_id": "SKILL-VT-001",
        "name": "view_file",
        "purpose": "Read files from workspace",
        "inputs": [{"name": "path", "type": "string"}],
        "outputs": [{"name": "content", "type": "string"}],
        "boundaries": ["Only access files under workspace root"],
        "constraints": ["must not override factual evidence fields"],
    }


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------


class TestClaudeBootstrapManifestSchema:
    """Tests for claude_bootstrap_manifest.schema.json."""

    def test_valid_manifest(self):
        """covers: AC-VT-009-02, AC-VT-009-03"""
        schema = load_schema("claude_bootstrap_manifest.schema.json")
        data = _minimal_bootstrap_manifest()
        validate(instance=data, schema=schema)

    def test_missing_required_fields(self):
        """covers: AC-VT-009-02"""
        schema = load_schema("claude_bootstrap_manifest.schema.json")
        required_fields = [
            "schema_version",
            "runtime",
            "subagents",
            "skills",
            "forbidden_actions",
            "structured_governance_outputs",
        ]
        for field in required_fields:
            data = _minimal_bootstrap_manifest()
            del data[field]
            with pytest.raises(ValidationError):
                validate(instance=data, schema=schema)

    def test_invalid_runtime_pattern(self):
        """covers: AC-VT-009-02"""
        schema = load_schema("claude_bootstrap_manifest.schema.json")
        data = _minimal_bootstrap_manifest()
        data["runtime"] = "not-claude-code"
        with pytest.raises(ValidationError):
            validate(instance=data, schema=schema)

    def test_invalid_subagent_id_pattern(self):
        """covers: AC-VT-009-02, AC-VT-009-03"""
        schema = load_schema("claude_bootstrap_manifest.schema.json")
        data = _minimal_bootstrap_manifest()
        data["subagents"][0]["id"] = "AGENT-VT-001"  # Needs SUBAGENT-VT-
        with pytest.raises(ValidationError):
            validate(instance=data, schema=schema)


class TestClaudeSubagentDefinitionSchema:
    """Tests for claude_subagent_definition.schema.json."""

    def test_valid_definition(self):
        """covers: AC-VT-009-02, AC-VT-009-03"""
        schema = load_schema("claude_subagent_definition.schema.json")
        data = _minimal_subagent_definition()
        validate(instance=data, schema=schema)

    def test_missing_required_fields(self):
        """covers: AC-VT-009-02"""
        schema = load_schema("claude_subagent_definition.schema.json")
        required_fields = [
            "subagent_id",
            "role",
            "responsibilities",
            "allowed_skills",
            "forbidden_behaviors",
            "required_outputs",
        ]
        for field in required_fields:
            data = _minimal_subagent_definition()
            del data[field]
            with pytest.raises(ValidationError):
                validate(instance=data, schema=schema)

    def test_invalid_subagent_id_pattern(self):
        """covers: AC-VT-009-02, AC-VT-009-03"""
        schema = load_schema("claude_subagent_definition.schema.json")
        data = _minimal_subagent_definition()
        data["subagent_id"] = "SUBAGENT-VT-XYZ"  # Non-digit suffix
        with pytest.raises(ValidationError):
            validate(instance=data, schema=schema)

    def test_invalid_allowed_skill_pattern(self):
        """covers: AC-VT-009-02, AC-VT-009-03"""
        schema = load_schema("claude_subagent_definition.schema.json")
        data = _minimal_subagent_definition()
        data["allowed_skills"] = ["SKILL-001"]  # Needs SKILL-VT-
        with pytest.raises(ValidationError):
            validate(instance=data, schema=schema)


class TestClaudeSkillDefinitionSchema:
    """Tests for claude_skill_definition.schema.json."""

    def test_valid_definition(self):
        """covers: AC-VT-009-02, AC-VT-009-03"""
        schema = load_schema("claude_skill_definition.schema.json")
        data = _minimal_skill_definition()
        validate(instance=data, schema=schema)

    def test_missing_required_fields(self):
        """covers: AC-VT-009-02"""
        schema = load_schema("claude_skill_definition.schema.json")
        required_fields = [
            "skill_id",
            "name",
            "purpose",
            "inputs",
            "outputs",
            "boundaries",
            "constraints",
        ]
        for field in required_fields:
            data = _minimal_skill_definition()
            del data[field]
            with pytest.raises(ValidationError):
                validate(instance=data, schema=schema)

    def test_invalid_skill_id_pattern(self):
        """covers: AC-VT-009-02, AC-VT-009-03"""
        schema = load_schema("claude_skill_definition.schema.json")
        data = _minimal_skill_definition()
        data["skill_id"] = "SKILL-VT-abc"  # Non-digit suffix
        with pytest.raises(ValidationError):
            validate(instance=data, schema=schema)
