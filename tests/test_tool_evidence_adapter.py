"""
Unit tests for Tool Output Evidence Adapter.

Covers:
- Pytest, coverage, ruff, bandit report parsing.
- Tool execution failure mapping.
- AST test docstring fallback lookup.
- Tool type detection from JSON field and filename.
"""

import json
from pathlib import Path

import pytest

from vibe_tracing.core.enums import CoverageStatus, ErrorCode
from vibe_tracing.tool_evidence_adapter import ToolEvidenceAdapter


@pytest.fixture
def adapter(tmp_path: Path) -> ToolEvidenceAdapter:
    """Fixture returning a ToolEvidenceAdapter configured with a temp project root."""
    return ToolEvidenceAdapter(tmp_path)


def test_pytest_report_success(tmp_path: Path, adapter: ToolEvidenceAdapter) -> None:
    """covers: AC-VT-001-02, AC-VT-002-01"""
    report_data = {
        "tool": "pytest",
        "command": "pytest --json-report",
        "exit_code": 0,
        "tests": [
            {
                "nodeid": "tests/test_ids_and_enums.py::test_req_id_valid",
                "outcome": "passed",
                "docstring": "covers: AC-VT-001-03\nSome other details.",
            },
            {
                "nodeid": "tests/test_cli_stub.py::test_cli_version",
                "outcome": "failed",
                "metadata": {"docstring": "covers: AC-VT-001-01"},
            },
            {
                "nodeid": "tests/test_cli_stub.py::test_unrelated",
                "outcome": "passed",
                # no docstring/covers
            },
        ],
    }
    report_file = tmp_path / "pytest_report.json"
    with report_file.open("w", encoding="utf-8") as f:
        json.dump(report_data, f)

    candidates = adapter.parse_report_file(report_file)
    assert len(candidates) == 3

    # First candidate (passed, has covers)
    c1 = candidates[0]
    assert c1.source_type == "test"
    assert c1.source_path == "tests/test_ids_and_enums.py::test_req_id_valid"
    assert c1.covers == ["AC-VT-001-03"]
    assert c1.status == CoverageStatus.COVERED.value
    assert c1.error_code is None

    # Second candidate (failed, has covers)
    c2 = candidates[1]
    assert c2.source_type == "test"
    assert c2.source_path == "tests/test_cli_stub.py::test_cli_version"
    assert c2.covers == ["AC-VT-001-01"]
    assert c2.status == CoverageStatus.VIOLATED.value

    # Third candidate (no covers)
    c3 = candidates[2]
    assert c3.covers == []
    assert c3.status == CoverageStatus.COVERED.value


def test_pytest_report_execution_failed(
    tmp_path: Path, adapter: ToolEvidenceAdapter
) -> None:
    """covers: AC-VT-007-01, AC-VT-008-01"""
    report_data = {
        "tool": "pytest",
        "command": "pytest --json-report",
        "exit_code": 2,  # crashed/interrupted
        "stderr": "Pytest internal crash error",
        "tests": [],
    }
    report_file = tmp_path / "pytest_report.json"
    with report_file.open("w", encoding="utf-8") as f:
        json.dump(report_data, f)

    candidates = adapter.parse_report_file(report_file)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.source_type == "tool"
    assert c.status == CoverageStatus.BLOCKED.value
    assert c.error_code == ErrorCode.TOOL_EXECUTION_FAILED.value
    assert "crash" in c.stderr


def test_pytest_ast_fallback(tmp_path: Path, adapter: ToolEvidenceAdapter) -> None:
    """covers: AC-VT-001-02"""
    # Write dummy python test file to temp project root
    test_dir = tmp_path / "tests"
    test_dir.mkdir(exist_ok=True)
    test_file = test_dir / "test_dummy.py"
    test_file.write_text(
        "def test_foo():\n"
        '    """\n'
        "    This is a dummy test.\n"
        "    covers: AC-VT-009-01, REQ-VT-001\n"
        '    """\n'
        "    pass\n",
        encoding="utf-8",
    )

    report_data = {
        "tool": "pytest",
        "command": "pytest",
        "exit_code": 0,
        "tests": [
            {
                "nodeid": "tests/test_dummy.py::test_foo",
                "outcome": "passed",
                # docstring is missing from JSON
            }
        ],
    }
    report_file = tmp_path / "pytest_report.json"
    with report_file.open("w", encoding="utf-8") as f:
        json.dump(report_data, f)

    candidates = adapter.parse_report_file(report_file)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.covers == ["AC-VT-009-01", "REQ-VT-001"]
    assert c.status == CoverageStatus.COVERED.value


def test_coverage_report_success(tmp_path: Path, adapter: ToolEvidenceAdapter) -> None:
    """covers: AC-VT-001-02, AC-VT-002-01"""
    # 1. Compliant coverage (>= 80)
    report_data_1 = {
        "tool": "coverage",
        "command": "coverage json",
        "exit_code": 0,
        "covers": ["AC-VT-001-02"],
        "totals": {"percent_covered": 85.5},
    }
    report_file_1 = tmp_path / "coverage_report.json"
    with report_file_1.open("w", encoding="utf-8") as f:
        json.dump(report_data_1, f)

    candidates = adapter.parse_report_file(report_file_1)
    assert len(candidates) == 1
    c1 = candidates[0]
    assert c1.covers == ["AC-VT-001-02"]
    assert c1.status == CoverageStatus.COMPLIANT.value
    assert c1.details["percent_covered"] == 85.5

    # 2. Violated coverage (< 80)
    report_data_2 = {
        "tool": "coverage",
        "exit_code": 0,
        "percent_covered": 72.3,  # alternative key structure supported
    }
    report_file_2 = tmp_path / "coverage_report_2.json"
    with report_file_2.open("w", encoding="utf-8") as f:
        json.dump(report_data_2, f)

    candidates = adapter.parse_report_file(report_file_2)
    assert len(candidates) == 1
    c2 = candidates[0]
    assert c2.status == CoverageStatus.VIOLATED.value
    assert c2.details["percent_covered"] == 72.3


def test_coverage_report_failed(tmp_path: Path, adapter: ToolEvidenceAdapter) -> None:
    """covers: AC-VT-007-01, AC-VT-008-01"""
    report_data = {
        "tool": "coverage",
        "exit_code": 1,
        "stderr": "Coverage execution error",
    }
    report_file = tmp_path / "coverage_report.json"
    with report_file.open("w", encoding="utf-8") as f:
        json.dump(report_data, f)

    candidates = adapter.parse_report_file(report_file)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.status == CoverageStatus.BLOCKED.value
    assert c.error_code == ErrorCode.TOOL_EXECUTION_FAILED.value


def test_ruff_report_success(tmp_path: Path, adapter: ToolEvidenceAdapter) -> None:
    """covers: AC-VT-001-02, AC-VT-002-01"""
    # 1. Clean report (no violations)
    report_data_1 = {"tool": "ruff", "exit_code": 0, "data": []}
    report_file_1 = tmp_path / "ruff_clean.json"
    with report_file_1.open("w", encoding="utf-8") as f:
        json.dump(report_data_1, f)

    candidates = adapter.parse_report_file(report_file_1)
    assert len(candidates) == 1
    assert candidates[0].status == CoverageStatus.COMPLIANT.value

    # 2. Violation report
    report_data_2 = {
        "tool": "ruff",
        "exit_code": 1,  # exits with 1 on violations
        "data": [{"code": "F401", "message": "unused import"}],
    }
    report_file_2 = tmp_path / "ruff_violations.json"
    with report_file_2.open("w", encoding="utf-8") as f:
        json.dump(report_data_2, f)

    candidates = adapter.parse_report_file(report_file_2)
    assert len(candidates) == 1
    assert candidates[0].status == CoverageStatus.VIOLATED.value


def test_ruff_report_failed(tmp_path: Path, adapter: ToolEvidenceAdapter) -> None:
    """covers: AC-VT-007-01, AC-VT-008-01"""
    report_data = {
        "tool": "ruff",
        "exit_code": 2,  # configuration/usage error
        "stderr": "Invalid option --foo",
    }
    report_file = tmp_path / "ruff_report.json"
    with report_file.open("w", encoding="utf-8") as f:
        json.dump(report_data, f)

    candidates = adapter.parse_report_file(report_file)
    assert len(candidates) == 1
    assert candidates[0].status == CoverageStatus.BLOCKED.value
    assert candidates[0].error_code == ErrorCode.TOOL_EXECUTION_FAILED.value


def test_bandit_report_success(tmp_path: Path, adapter: ToolEvidenceAdapter) -> None:
    """covers: AC-VT-001-02, AC-VT-002-01"""
    # 1. Clean report
    report_data_1 = {"tool": "bandit", "exit_code": 0, "results": []}
    report_file_1 = tmp_path / "bandit_clean.json"
    with report_file_1.open("w", encoding="utf-8") as f:
        json.dump(report_data_1, f)

    candidates = adapter.parse_report_file(report_file_1)
    assert len(candidates) == 1
    assert candidates[0].status == CoverageStatus.COMPLIANT.value

    # 2. Violation report
    report_data_2 = {
        "tool": "bandit",
        "exit_code": 1,
        "results": [{"issue_severity": "HIGH", "issue_text": "Use of assert detected"}],
    }
    report_file_2 = tmp_path / "bandit_violations.json"
    with report_file_2.open("w", encoding="utf-8") as f:
        json.dump(report_data_2, f)

    candidates = adapter.parse_report_file(report_file_2)
    assert len(candidates) == 1
    assert candidates[0].status == CoverageStatus.VIOLATED.value


def test_bandit_report_failed(tmp_path: Path, adapter: ToolEvidenceAdapter) -> None:
    """covers: AC-VT-007-01, AC-VT-008-01"""
    report_data = {"tool": "bandit", "exit_code": -1, "stderr": "Process killed"}
    report_file = tmp_path / "bandit_report.json"
    with report_file.open("w", encoding="utf-8") as f:
        json.dump(report_data, f)

    candidates = adapter.parse_report_file(report_file)
    assert len(candidates) == 1
    assert candidates[0].status == CoverageStatus.BLOCKED.value
    assert candidates[0].error_code == ErrorCode.TOOL_EXECUTION_FAILED.value


def test_tool_type_detection(tmp_path: Path, adapter: ToolEvidenceAdapter) -> None:
    """covers: AC-VT-002-01"""
    # File named pytest_something.json without "tool" field
    report_data = {"exit_code": 0, "tests": []}
    report_file = tmp_path / "pytest_output.json"
    with report_file.open("w", encoding="utf-8") as f:
        json.dump(report_data, f)

    candidates = adapter.parse_report_file(report_file)
    # Exits successfully, gets parsed as pytest
    assert len(candidates) == 0  # no tests in JSON

    # Unrecognized tool fallback error
    report_file_bad = tmp_path / "unknown_tool.json"
    with report_file_bad.open("w", encoding="utf-8") as f:
        json.dump(report_data, f)

    candidates_bad = adapter.parse_report_file(report_file_bad)
    assert len(candidates_bad) == 1
    assert candidates_bad[0].status == CoverageStatus.BLOCKED.value
    assert candidates_bad[0].error_code == ErrorCode.TOOL_EXECUTION_FAILED.value
    assert "Unrecognized tool report" in candidates_bad[0].stderr


def test_missing_report_file_returns_error(
    tmp_path: Path, adapter: ToolEvidenceAdapter
) -> None:
    """covers: AC-VT-007-01, AC-VT-008-01"""
    report_file = tmp_path / "non_existent.json"
    candidates = adapter.parse_report_file(report_file)
    assert len(candidates) == 1
    assert candidates[0].status == CoverageStatus.BLOCKED.value
    assert candidates[0].error_code == ErrorCode.TOOL_EXECUTION_FAILED.value
    assert "Report file not found" in candidates[0].stderr


def test_invalid_json_report_file_returns_error(
    tmp_path: Path, adapter: ToolEvidenceAdapter
) -> None:
    """covers: AC-VT-007-01, AC-VT-008-01"""
    report_file = tmp_path / "bad_json.json"
    report_file.write_text("invalid json content", encoding="utf-8")

    candidates = adapter.parse_report_file(report_file)
    assert len(candidates) == 1
    assert candidates[0].status == CoverageStatus.BLOCKED.value
    assert candidates[0].error_code == ErrorCode.TOOL_EXECUTION_FAILED.value
    assert "Failed to parse JSON" in candidates[0].stderr
