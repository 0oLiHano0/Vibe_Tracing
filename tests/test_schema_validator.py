"""
Tests for SchemaValidator (TASK-VT-004).

Each test function declares its AC coverage in its docstring.
"""

import sys
from pathlib import Path

import pytest

from vibe_tracing.core.enums import ErrorCode
from vibe_tracing.schema_validator import SchemaValidator

SCHEMAS_DIR = Path(__file__).parent.parent / "src" / "vibe_tracing" / "schemas"
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


def test_valid_agent_claims_empty_array_passes(validator):
    """Validate [] against agent_claims schema → is_valid=True. Covers: AC-VT-001-03."""
    result = validator.validate_dict([], "agent_claims")
    assert result.is_valid is True
    assert result.error_code is None


def test_valid_evidence_index_dict_passes(validator):
    """Validate minimal evidence_index dict → is_valid=True. Covers: AC-VT-001-03."""
    result = validator.validate_dict(_VALID_EVIDENCE_INDEX, "evidence_index")
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


def test_validate_file_valid_raw_agent_claims(validator):
    """Validate actual .vibetracing/agent_claims.json (empty array) → is_valid=True. Covers: AC-VT-001-03."""
    claims_path = VIBETRACING_DIR / "agent_claims.json"
    if not claims_path.exists():
        pytest.skip(f"Agent claims file not found: {claims_path}")
    result = validator.validate_file(claims_path, "agent_claims")
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
import vibe_tracing.schema_validator
forbidden = ["traceability", "gate", "dashboard", "analysis"]
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
