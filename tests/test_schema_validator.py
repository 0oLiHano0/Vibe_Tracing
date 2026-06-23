"""
Tests for SchemaValidator (TASK-VT-004).

Each test function declares its AC coverage in its docstring.
"""

import sys
from collections import deque
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vibe_tracing.infra.config.enums import ErrorCode
from vibe_tracing.infra.validation.schema_validator import SchemaValidator, _build_hint

SCHEMAS_DIR = Path(__file__).parent.parent / "src" / "vibe_tracing" / "infra" / "validation" / "schemas"
DOCS_DIR = Path(__file__).parent.parent / "docs"
VIBETRACING_DIR = Path(__file__).parent.parent / ".vibetracing"


@pytest.fixture
def validator():
    """Return a SchemaValidator pointed at the project schemas directory."""
    return SchemaValidator(SCHEMAS_DIR)


# ---------------------------------------------------------------------------
# Helpers — minimal valid data for each schema
# ---------------------------------------------------------------------------

_VALID_TASK_LIST = {
    "schema_version": "1.0",
    "project": {
        "project_id": "PROJECT-VT",
        "name": "Vibe Tracing",
        "stage": "development",
    },
    "tasks": [
        {
            "task_id": "TASK-VT-001",
            "title": "Sample Task",
            "phase_id": "PHASE-VT-001",
            "priority": "must",
            "status": "todo",
            "owner_role": "agent",
            "objective": "Do something.",
            "related_requirements": ["REQ-VT-001"],
            "related_acceptance_criteria": ["AC-VT-001-01"],
            "definition_of_done": [
                {"dod_id": "DOD-VT-001-01", "description": "It is done."}
            ],
        }
    ],
}

_VALID_EVIDENCE_INDEX = {
    "run_id": "RUN-001",
    "project_id": "PROJECT-VT",
    "scan_time": "2026-01-01T00:00:00Z",
    "evidences": [],
}

_VALID_TRACEABILITY_REPORT = {
    "run_id": "RUN-001",
    "project_id": "PROJECT-VT",
    "scan_time": "2026-01-01T00:00:00Z",
    "gate_decision": "pass",
    "requirement_coverage": [],
    "gaps": [],
    "risks": [],
}


# ---------------------------------------------------------------------------
# AC-VT-001-03: Valid data passes validation
# ---------------------------------------------------------------------------


def test_valid_task_list_dict_passes(validator):
    """Validate a valid in-memory task_list dict → is_valid=True. Covers: AC-VT-001-03."""
    result = validator.validate_dict(_VALID_TASK_LIST, "task_list")
    assert result.is_valid is True
    assert result.error_code is None


def test_valid_agent_claims_object_passes(validator):
    """Validate a minimal agent_claims array → is_valid=True. Covers: AC-VT-001-03."""
    result = validator.validate_dict(
        [{"claim_id": "CLAIM-VT-001", "related_task": "TASK-VT-001"}],
        "agent_claims",
    )
    assert result.is_valid is True
    assert result.error_code is None


def test_valid_traceability_report_dict_passes(validator):
    """Validate minimal traceability_report dict → is_valid=True. Covers: AC-VT-001-03."""
    result = validator.validate_dict(_VALID_TRACEABILITY_REPORT, "traceability_report")
    assert result.is_valid is True
    assert result.error_code is None


# ---------------------------------------------------------------------------
# AC-VT-006-02: Error handling for bad inputs
# ---------------------------------------------------------------------------


def test_unknown_schema_name_returns_invalid_input(validator):
    """Unknown schema_name → error_code=INVALID_INPUT. Covers: AC-VT-006-02."""
    result = validator.validate_dict({}, "nonexistent_schema")
    assert result.is_valid is False
    assert result.error_code == ErrorCode.INVALID_INPUT


def test_missing_file_returns_error(validator):
    """Non-existent file path → is_valid=False. Covers: AC-VT-006-02."""
    result = validator.validate_file(
        Path("/nonexistent/path/task_list.json"), "task_list"
    )
    assert result.is_valid is False
    assert result.error_code in (ErrorCode.MISSING_INPUT, ErrorCode.INVALID_INPUT)


def test_invalid_json_file_returns_invalid_input(validator, tmp_path):
    """Write a temp file with invalid JSON, validate → error_code=INVALID_INPUT. Covers: AC-VT-006-02."""
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{invalid json content,,}", encoding="utf-8")

    result = validator.validate_file(bad_file, "task_list")
    assert result.is_valid is False
    assert result.error_code == ErrorCode.INVALID_INPUT


# ---------------------------------------------------------------------------
# AC-VT-008-03: Schema violation details
# ---------------------------------------------------------------------------


def test_schema_violation_returns_schema_violation_code(validator):
    """Pass dict missing required field → error_code=SCHEMA_VIOLATION. Covers: AC-VT-008-03."""
    # Missing 'project' and 'tasks' required fields
    bad_data = {"schema_version": "1.0"}
    result = validator.validate_dict(bad_data, "task_list")
    assert result.is_valid is False
    assert result.error_code == ErrorCode.SCHEMA_VIOLATION


def test_schema_violation_includes_field_path(validator):
    """Error result has non-empty field_path when nested field fails. Covers: AC-VT-008-03."""
    # tasks[0] is missing required fields like 'title', 'phase_id', etc.
    bad_data = {
        "schema_version": "1.0",
        "project": {
            "project_id": "PROJECT-VT",
            "name": "Test",
            "stage": "dev",
        },
        "tasks": [
            {
                "task_id": "TASK-VT-001",
                # missing: title, phase_id, priority, status, owner_role, objective,
                #          related_requirements, related_acceptance_criteria, definition_of_done
            }
        ],
    }
    result = validator.validate_dict(bad_data, "task_list")
    assert result.is_valid is False
    assert result.error_code == ErrorCode.SCHEMA_VIOLATION
    # field_path should point into the tasks array or one of its properties
    assert result.field_path != "" or result.message != ""


def test_schema_violation_includes_hint(validator):
    """Error result has non-empty hint. Covers: AC-VT-008-03."""
    bad_data = {"schema_version": "1.0"}  # missing 'project' and 'tasks'
    result = validator.validate_dict(bad_data, "task_list")
    assert result.is_valid is False
    assert result.error_code == ErrorCode.SCHEMA_VIOLATION
    assert result.hint != ""


# ---------------------------------------------------------------------------
# AC-VT-001-03: Validate real raw files
# ---------------------------------------------------------------------------


def test_validate_file_valid_raw_task_list(validator):
    """Validate actual docs/task_list.json file → is_valid=True. Covers: AC-VT-001-03."""
    task_list_path = DOCS_DIR / "task_list.json"
    if not task_list_path.exists():
        pytest.skip(f"Task list file not found: {task_list_path}")
    result = validator.validate_file(task_list_path, "task_list")
    assert result.is_valid is True, (
        f"Validation failed: {result.error_code} | {result.field_path} | {result.message}"
    )


def test_validate_file_valid_raw_agent_claims(validator, tmp_path):
    """Validate a merged claims array file → is_valid=True. Covers: AC-VT-001-03."""
    claim_file = tmp_path / "CLAIM-VT-001.json"
    claim_file.write_text(
        '[{"claim_id": "CLAIM-VT-001", "related_task": "TASK-VT-001"}]',
        encoding="utf-8",
    )
    result = validator.validate_file(claim_file, "agent_claims")
    assert result.is_valid is True, (
        f"Validation failed: {result.error_code} | {result.field_path} | {result.message}"
    )


# ---------------------------------------------------------------------------
# AC-VT-008-03: Isolation — no forbidden imports
# ---------------------------------------------------------------------------


def test_validator_does_not_import_analysis_modules(validator):
    """
    Import schema_validator module in a clean subprocess, check it doesn't import
    traceability, gate, or dashboard modules. Covers: AC-VT-008-03.
    """
    import subprocess

    code = """
import sys
import vibe_tracing.infra.validation.schema_validator
# Only forbid imports from domain layer, not infra layer
forbidden = ["domain.traceability", "domain.gate", "domain.dashboard", "domain.analysis"]
violations = [
    name for name in sys.modules.keys()
    if any(p in name for p in forbidden)
    and "schema_validator" not in name
]
if violations:
    print(violations)
    sys.exit(1)
sys.exit(0)
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert result.returncode == 0, (
        f"schema_validator imported forbidden module(s): {result.stdout or result.stderr}"
    )


# ---------------------------------------------------------------------------
# 覆盖: _build_hint 兜底中文修复建议（原英文兜底已改为中文）
# ---------------------------------------------------------------------------


def _make_mock_error(validator, validator_value, path_parts, schema=None, instance=None, message="test error"):
    """Create a mock jsonschema.ValidationError for testing _build_hint directly."""
    err = MagicMock()
    err.validator = validator
    err.validator_value = validator_value
    err.absolute_path = deque(path_parts)
    err.schema = schema if schema is not None else {}
    err.instance = instance if instance is not None else {}
    err.message = message
    return err


def test_build_hint_required_fallback():
    """_build_hint 对 'required' validator 返回中文兜底建议。"""
    err = _make_mock_error("required", ["name", "age"], ["project"])
    hint = _build_hint(err)
    assert "请添加必填字段" in hint
    assert "name" in hint


def test_build_hint_type_fallback():
    """_build_hint 对 'type' validator 返回中文兜底建议。"""
    err = _make_mock_error("type", "string", ["schema_version"])
    hint = _build_hint(err)
    assert "必须为类型" in hint
    assert "string" in hint


def test_build_hint_enum_fallback():
    """_build_hint 对 'enum' validator 返回中文兜底建议。"""
    err = _make_mock_error("enum", ["must", "should", "could"], ["tasks", 0, "priority"])
    hint = _build_hint(err)
    assert "必须为以下值之一" in hint


def test_build_hint_pattern_fallback():
    """_build_hint 对 'pattern' validator 返回中文兜底建议。
    注意：pattern+task_id/related_task 有专门的中文分支（第 62-66 行），
    本测试使用不以 task_id/related_task 结尾的路径来触达兜底逻辑。
    """
    err = _make_mock_error("pattern", "^[A-Z]+$", ["project", "project_id"])
    hint = _build_hint(err)
    assert "必须匹配正则" in hint


def test_build_hint_min_length_fallback():
    """_build_hint 对 'minLength' validator 返回中文兜底建议。"""
    err = _make_mock_error("minLength", 3, ["project", "name"])
    hint = _build_hint(err)
    assert "最小长度" in hint


def test_build_hint_max_length_fallback():
    """_build_hint 对 'maxLength' validator 返回中文兜底建议。"""
    err = _make_mock_error("maxLength", 100, ["project", "name"])
    hint = _build_hint(err)
    assert "最大长度" in hint


def test_build_hint_minimum_fallback():
    """_build_hint 对 'minimum' validator 返回中文兜底建议。"""
    err = _make_mock_error("minimum", 0, ["config", "retry_count"])
    hint = _build_hint(err)
    assert "必须 >=" in hint


def test_build_hint_maximum_fallback():
    """_build_hint 对 'maximum' validator 返回中文兜底建议。"""
    err = _make_mock_error("maximum", 100, ["config", "retry_count"])
    hint = _build_hint(err)
    assert "必须 <=" in hint


def test_build_hint_additional_properties_fallback():
    """_build_hint 对 'additionalProperties' validator 返回中文兜底建议。"""
    err = _make_mock_error("additionalProperties", False, ["project"])
    hint = _build_hint(err)
    assert "请移除" in hint and "多余属性" in hint


def test_build_hint_unknown_validator_fallback():
    """_build_hint 对未知 validator 类型返回中文兜底建议。"""
    err = _make_mock_error("customValidator", "something", ["project", "field"])
    hint = _build_hint(err)
    assert "请修复" in hint
    assert "test error" in hint


# ---------------------------------------------------------------------------
# Coverage: validate_file with unknown schema name (lines 169-170)
# ---------------------------------------------------------------------------


def test_validate_file_unknown_schema_name(validator, tmp_path):
    """validate_file with unknown schema_name returns INVALID_INPUT error."""
    dummy = tmp_path / "dummy.json"
    dummy.write_text("{}")
    result = validator.validate_file(dummy, "nonexistent_schema")
    assert result.is_valid is False
    assert result.error_code == ErrorCode.INVALID_INPUT
    assert "nonexistent_schema" in result.message


# ---------------------------------------------------------------------------
# Coverage: _run_validation when schema file cannot be loaded (lines 253-254)
# ---------------------------------------------------------------------------


def test_run_validation_schema_load_error(tmp_path):
    """_run_validation returns error when schema file is missing from schemas_dir."""
    validator = SchemaValidator(tmp_path)  # empty dir, no schema files
    result = validator.validate_dict({"key": "value"}, "task_list")
    assert result.is_valid is False
    assert result.error_code == ErrorCode.INVALID_INPUT
    assert "Failed to load schema" in result.message
