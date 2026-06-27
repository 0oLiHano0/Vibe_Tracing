"""
Tests for dynamic Chinese guidance reflection mechanism based on schema descriptions (TASK-VT-035).
"""

import json
import pytest
from pathlib import Path
from vibe_tracing.infra.validation.schema_validator import SchemaValidator
from vibe_tracing.infra.loader.task_loader import TaskLoader
from vibe_tracing.infra.loader.claim_loader import ClaimLoader

SCHEMAS_DIR = Path(__file__).parent.parent / "src" / "vibe_tracing" / "infra" / "validation" / "schemas"


@pytest.fixture
def validator():
    return SchemaValidator(SCHEMAS_DIR)


def test_claims_schema_validation_error_with_dynamic_hints(validator):
    """Test that a schema validation error in agent_claims successfully extracts the dynamic hint from schema description."""
    data = [
        {
            "related_task": "TASK-VT-001",
            # claim_id is missing, which is a required field
        },
    ]

    res = validator.validate_dict(data, "agent_claims")
    assert res.is_valid is False
    assert "claim_id" in res.message


def test_tasks_schema_validation_error_with_dynamic_hints(validator):
    """Test that a schema validation error in task_list successfully extracts the dynamic hint from schema description."""
    data = {
        "schema_version": "1.0.0",
        "project": {
            "project_id": "PROJECT-VT",
            "name": "Sample Project",
            "stage": "Development",
        },
        "tasks": [
            {
                "task_id": "TASK-VT-001",
                # title is missing
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "todo",
                "owner_role": "AI Developer",
                "objective": "目标",
                "related_requirements": [],
                "related_acceptance_criteria": [],
                "definition_of_done": [],
            },
        ],
    }

    res = validator.validate_dict(data, "task_list")
    assert res.is_valid is False
    assert "title" in res.message
    assert "【修复指南】任务标题，简短描述开发任务内容。" in res.hint


def test_root_level_non_required_error_with_dynamic_hints(validator):
    """Test that a non-required schema validation error at the root level successfully extracts the dynamic hint."""
    data = {
        "schema_version": 12345,  # Invalid type (should be string)
        "project": {
            "project_id": "PROJECT-VT",
            "name": "Sample Project",
            "stage": "Development",
        },
        "tasks": []
    }

    res = validator.validate_dict(data, "task_list")
    assert res.is_valid is False
    assert res.field_path == "schema_version"
    assert "【修复指南】指明当前模式的版本" in res.hint








def test_architecture_constraints_schema_validation_error_with_dynamic_hints(validator):
    """Test that a schema validation error in architecture_constraints successfully extracts the dynamic hint."""
    data = {
        "schema_version": "1.0.0",
        "project": {
            "project_id": "PROJECT-VT",
            "name": "Sample Project",
            "stage": "Development",
        },
        "architecture_principles": [
            {
                "principle_id": "PRINCIPLE-VT-001",
                "title": "Real Principle",
                "description": "真实原则",
                "severity": "invalid-severity"  # Schema violation
            }
        ]
    }

    res = validator.validate_dict(data, "architecture_constraints")
    assert res.is_valid is False
    assert "severity" in res.message
    assert "【修复指南】强度级别" in res.hint
