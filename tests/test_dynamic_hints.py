"""
Tests for dynamic Chinese guidance reflection mechanism based on template field hints (TASK-VT-035).
"""

import json
import pytest
from pathlib import Path
from vibe_tracing.schema_validator import SchemaValidator
from vibe_tracing.task_loader import TaskLoader
from vibe_tracing.claim_loader import ClaimLoader

SCHEMAS_DIR = Path(__file__).parent.parent / "src" / "vibe_tracing" / "schemas"


@pytest.fixture
def validator():
    return SchemaValidator(SCHEMAS_DIR)


def test_claims_schema_validation_error_with_dynamic_hints(validator):
    """Test that a schema validation error in agent_claims successfully extracts the dynamic hint.
    Covers: AC-VT-009-07
    """
    data = [
        {
            "claim_id": "CLAIM-VT-9999",
            "related_task": "TASK-VT-9999",
            "claimed_status": "unclear",
            "evidence_refs": [],
            "timestamp": "2026-05-31T10:00:00Z",
            "__field_hints__": {
                "claim_id": "申索ID，必须符合正则格式 CLAIM-VT-\\d+。",
                "timestamp": "ISO 8601格式的时间戳。",
            },
        },
        {
            "claim_id": "CLAIM-VT-001",
            "related_task": "TASK-VT-001",
            "claimed_status": "covered",
            "evidence_refs": [],
            # timestamp is missing, which is a required field
        },
    ]

    res = validator.validate_dict(data, "agent_claims")
    assert res.is_valid is False
    assert "timestamp" in res.message
    # Check that custom hint is resolved and wrapped with 【修复指南】
    assert "【修复指南】ISO 8601格式的时间戳。" in res.hint


def test_tasks_schema_validation_error_with_dynamic_hints(validator):
    """Test that a schema validation error in task_list successfully extracts the dynamic hint.
    Covers: AC-VT-009-07
    """
    data = {
        "schema_version": "1.0.0",
        "project": {
            "project_id": "PROJECT-VT",
            "name": "Sample Project",
            "stage": "Development",
            "__field_hints__": {"project_id": "项目ID，必须为 PROJECT-VT。"},
        },
        "__field_hints__": {"schema_version": "指明当前模式的版本。"},
        "tasks": [
            {
                "task_id": "TASK-VT-9999",
                "title": "样例任务标题",
                "phase_id": "PHASE-VT-9999",
                "priority": "must",
                "status": "todo",
                "owner_role": "AI Developer",
                "objective": "目标",
                "related_requirements": [],
                "related_acceptance_criteria": [],
                "definition_of_done": [],
                "__field_hints__": {"title": "任务标题，简短描述开发任务内容。"},
            },
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


def test_task_loader_logical_validation_error_with_dynamic_hints(tmp_path):
    """Test that consistency validation error in TaskLoader dynamically appends Chinese hint.
    Covers: AC-VT-009-07
    """
    data = {
        "schema_version": "1.0.0",
        "project": {
            "project_id": "PROJECT-VT",
            "name": "Sample Project",
            "stage": "Development",
        },
        "tasks": [
            {
                "task_id": "TASK-VT-9999",
                "title": "样例任务标题",
                "phase_id": "PHASE-VT-9999",
                "priority": "must",
                "status": "todo",
                "owner_role": "AI Developer",
                "objective": "目标",
                "related_requirements": [],
                "related_acceptance_criteria": [],
                "definition_of_done": [],
                "__field_hints__": {
                    "task_id": "任务ID，必须符合正则格式 `TASK-VT-\\d+`。"
                },
            },
            {
                # Invalid format for task_id
                "task_id": "TASK-VT-invalid",
                "title": "Real Task",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "todo",
                "owner_role": "AI Developer",
                "objective": "目标",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": [],
                "definition_of_done": [],
            },
        ],
    }

    file_path = tmp_path / "task_list.json"
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f)

    loader = TaskLoader(SCHEMAS_DIR)
    res = loader.load_and_validate(file_path)
    assert res.is_valid is False

    # Check that error contains dynamic guide
    error_msg = "; ".join(res.errors)
    assert "TASK-VT-invalid" in error_msg
    assert "【修复指南】任务ID，必须符合正则格式 `TASK-VT-\\d+`。" in error_msg


def test_claim_loader_logical_validation_error_with_dynamic_hints(tmp_path):
    """Test that consistency validation error in ClaimLoader dynamically appends Chinese hint.
    Covers: AC-VT-009-07
    """
    data = [
        {
            "claim_id": "CLAIM-VT-9999",
            "related_task": "TASK-VT-9999",
            "claimed_status": "unclear",
            "evidence_refs": [],
            "timestamp": "2026-05-31T10:00:00Z",
            "__field_hints__": {
                "related_task": "关联任务ID，必须符合正则格式 `TASK-VT-\\d+`。"
            },
        },
        {
            "claim_id": "CLAIM-VT-001",
            # Invalid format for related_task
            "related_task": "TASK-VT-invalid",
            "claimed_status": "unclear",
            "evidence_refs": [],
            "timestamp": "2026-05-31T10:00:00Z",
        },
    ]

    file_path = tmp_path / "agent_claims.json"
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f)

    loader = ClaimLoader(SCHEMAS_DIR)
    res = loader.load_and_validate(file_path)
    assert res.is_valid is False

    # Check that error contains dynamic guide
    error_msg = "; ".join(res.errors)
    assert "TASK-VT-invalid" in error_msg
    assert "【修复指南】关联任务ID，必须符合正则格式 `TASK-VT-\\d+`。" in error_msg


def test_silent_filtering_of_template_records(tmp_path):
    """Test that template records ending with -9999 are silently ignored and do not cause errors.
    Covers: AC-VT-009-07
    """
    task_data = {
        "schema_version": "1.0.0",
        "project": {
            "project_id": "PROJECT-VT",
            "name": "Sample Project",
            "stage": "Development",
        },
        "tasks": [
            {
                "task_id": "TASK-VT-9999",
                "title": "样例任务标题",
                "phase_id": "PHASE-VT-9999",
                "priority": "must",
                "status": "todo",
                "owner_role": "AI Developer",
                "objective": "目标",
                "related_requirements": [],
                "related_acceptance_criteria": [],
                "definition_of_done": [],
                "__field_hints__": {},
            },
            {
                "task_id": "TASK-VT-001",
                "title": "Real Task",
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
    task_path = tmp_path / "task_list.json"
    with task_path.open("w", encoding="utf-8") as f:
        json.dump(task_data, f)

    # 1. Load tasks
    task_loader = TaskLoader(SCHEMAS_DIR)
    task_res = task_loader.load_and_validate(task_path)

    # Check that only TASK-VT-001 is present in parsed tasks
    parsed_ids = [t.task_id for t in task_res.tasks]
    assert "TASK-VT-001" in parsed_ids
    assert "TASK-VT-9999" not in parsed_ids

    # 2. Check claim loader silent filter
    claim_data = [
        {
            "claim_id": "CLAIM-VT-9999",
            "related_task": "TASK-VT-9999",
            "claimed_status": "unclear",
            "evidence_refs": [],
            "timestamp": "2026-05-31T10:00:00Z",
            "__field_hints__": {},
        },
        {
            "claim_id": "CLAIM-VT-001",
            "related_task": "TASK-VT-001",
            "claimed_status": "unclear",
            "evidence_refs": [],
            "timestamp": "2026-05-31T10:00:00Z",
        },
    ]
    claim_path = tmp_path / "agent_claims.json"
    with claim_path.open("w", encoding="utf-8") as f:
        json.dump(claim_data, f)

    claim_loader = ClaimLoader(SCHEMAS_DIR)
    claim_res = claim_loader.load_and_validate(claim_path, task_res)

    parsed_cids = [c.claim_id for c in claim_res.claims]
    assert "CLAIM-VT-001" in parsed_cids
    assert "CLAIM-VT-9999" not in parsed_cids


def test_architecture_constraints_schema_validation_error_with_dynamic_hints(validator):
    """Test that a schema validation error in architecture_constraints successfully extracts the dynamic hint.
    Covers: AC-VT-009-07
    """
    data = {
        "schema_version": "1.0.0",
        "project": {
            "project_id": "PROJECT-VT",
            "name": "Sample Project",
            "stage": "Development",
        },
        "__field_hints__": {
            "schema_version": "指明架构约束规范的版本号。",
        },
        "architecture_principles": [
            {
                "principle_id": "PRINCIPLE-VT-9999",
                "title": "样例原则",
                "description": "原则描述",
                "severity": "must",
                "__field_hints__": {
                    "severity": "强度级别必须为 must、should 或 could。"
                }
            },
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
    assert "【修复指南】强度级别必须为 must、should 或 could。" in res.hint

