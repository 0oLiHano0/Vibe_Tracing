"""Tool output parsers.

Standalone parser functions for converting tool outputs into
ToolEvidenceCandidate structures. Each parser is a pure function
that takes the output data and returns a list of candidates.
"""

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from vibe_tracing.infra.config.enums import CoverageStatus, ErrorCode
from vibe_tracing.infra.tools.candidate import ToolEvidenceCandidate


def parse_pytest_output(
    stdout: str,
    stderr: str,
    exit_code: int,
    command: str,
    path: str,
    project_root: Path,
    skip_exit_codes: set,
    get_test_docstring: Optional[Callable[[str], Optional[str]]] = None,
    extract_covers: Optional[Callable[[Optional[str]], List[str]]] = None,
) -> List[ToolEvidenceCandidate]:
    """Parse pytest --json-report output.

    Exit code classification:
    - 0: success
    - 1: test failure (real, record as evidence)
    - 2: usage error (skip, not a real failure)
    - 5: no tests collected (skip, not a real failure)
    """
    # Return a "skipped" evidence candidate for exit codes that indicate
    # "tool cannot handle this file" rather than real failures.
    if exit_code in skip_exit_codes:
        reason = "no tests collected" if exit_code == 5 else "usage error"
        error_code = (
            ErrorCode.TOOL_NO_TESTS_COLLECTED.value if exit_code == 5
            else ErrorCode.TOOL_USAGE_ERROR.value
        )
        return [
            ToolEvidenceCandidate(
                source_type="tool",
                source_path=path,
                covers=[],
                status=CoverageStatus.SKIPPED.value,
                command=command,
                exit_code=exit_code,
                stderr=f"pytest {reason} (exit code {exit_code})",
                error_code=error_code,
                details={"skip_reason": reason},
            )
        ]

    # Check for execution failure (not test failure)
    if exit_code not in (0, 1):
        return [
            ToolEvidenceCandidate(
                source_type="tool",
                source_path=path,
                covers=[],
                status=CoverageStatus.BLOCKED.value,
                command=command,
                exit_code=exit_code,
                stderr=stderr or f"Pytest failed with exit code {exit_code}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
            )
        ]

    # Try to parse the JSON report from the output file
    json_match = re.search(r"--json-report-file=(\S+)", command)
    if json_match:
        report_path = Path(json_match.group(1))
        if not report_path.is_absolute():
            report_path = project_root / report_path
        if report_path.exists():
            try:
                with report_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                return parse_pytest_json(data, command, path, get_test_docstring, extract_covers)
            except (json.JSONDecodeError, OSError):
                pass

    # Fallback: try parsing stdout as JSON
    try:
        data = json.loads(stdout)
        return parse_pytest_json(data, command, path, get_test_docstring, extract_covers)
    except (json.JSONDecodeError, TypeError):
        pass

    # Last resort: return a single candidate based on exit code
    status = CoverageStatus.COVERED.value if exit_code == 0 else CoverageStatus.VIOLATED.value
    return [
        ToolEvidenceCandidate(
            source_type="test",
            source_path=path,
            covers=[],
            status=status,
            command=command,
            exit_code=exit_code,
            stderr=stderr,
            details={"outcome": "passed" if exit_code == 0 else "failed"},
        )
    ]


def parse_pytest_json(
    data: Any,
    command: str,
    path: str,
    get_test_docstring: Optional[Callable[[str], Optional[str]]] = None,
    extract_covers: Optional[Callable[[Optional[str]], List[str]]] = None,
) -> List[ToolEvidenceCandidate]:
    """Parse a pytest JSON report dict into candidates."""
    candidates: List[ToolEvidenceCandidate] = []
    if not isinstance(data, dict):
        return candidates

    tests_data = data.get("tests", [])
    if not isinstance(tests_data, list):
        return candidates

    for test in tests_data:
        if not isinstance(test, dict):
            continue
        nodeid = test.get("nodeid", "")
        outcome = test.get("outcome", "")
        docstring = test.get("docstring")

        if (
            docstring is None
            and "metadata" in test
            and isinstance(test["metadata"], dict)
        ):
            docstring = test["metadata"].get("docstring")

        if docstring is None and nodeid and get_test_docstring:
            docstring = get_test_docstring(nodeid)

        covers = extract_covers(docstring) if extract_covers else []

        if outcome == "passed":
            status = CoverageStatus.COVERED.value
        elif outcome in ("failed", "error"):
            status = CoverageStatus.VIOLATED.value
        else:
            status = CoverageStatus.UNCLEAR.value

        candidates.append(
            ToolEvidenceCandidate(
                source_type="test",
                source_path=nodeid or path,
                covers=covers,
                status=status,
                command=command,
                exit_code=0,
                details={"nodeid": nodeid, "outcome": outcome},
            )
        )

    return candidates


def parse_ruff_output(
    stdout: str,
    stderr: str,
    exit_code: int,
    command: str,
    path: str,
) -> List[ToolEvidenceCandidate]:
    """Parse ruff check --output-format=json output."""
    # Ruff exits with 0 (clean) or 1 (violations found); other codes = crash
    if exit_code not in (0, 1):
        return [
            ToolEvidenceCandidate(
                source_type="tool",
                source_path=path,
                covers=[],
                status=CoverageStatus.BLOCKED.value,
                command=command,
                exit_code=exit_code,
                stderr=stderr or f"Ruff failed with exit code {exit_code}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
            )
        ]

    violations: List[Any] = []
    try:
        data = json.loads(stdout)
        if isinstance(data, list):
            violations = data
        elif isinstance(data, dict):
            for key in ("violations", "results", "issues"):
                if isinstance(data.get(key), list):
                    violations = data[key]
                    break
    except (json.JSONDecodeError, TypeError):
        pass

    status = (
        CoverageStatus.COMPLIANT.value
        if not violations
        else CoverageStatus.VIOLATED.value
    )

    return [
        ToolEvidenceCandidate(
            source_type="tool",
            source_path=path,
            covers=[],
            status=status,
            command=command,
            exit_code=exit_code,
            details={"violations_count": len(violations)},
        )
    ]


def parse_mypy_output(
    stdout: str,
    stderr: str,
    exit_code: int,
    command: str,
    path: str,
    project_root: Path,
    skip_exit_codes: set,
) -> List[ToolEvidenceCandidate]:
    """Parse mypy output.

    Exit code classification:
    - 0: success
    - 1: type errors found (real, record as evidence)
    - 2: usage error (skip, not a real failure)
    """
    # Return a "skipped" evidence candidate for exit codes that indicate
    # "tool cannot handle this file" rather than real failures.
    if exit_code in skip_exit_codes:
        return [
            ToolEvidenceCandidate(
                source_type="tool",
                source_path=path,
                covers=[],
                status=CoverageStatus.SKIPPED.value,
                command=command,
                exit_code=exit_code,
                stderr=f"mypy usage error (exit code {exit_code})",
                error_code=ErrorCode.TOOL_USAGE_ERROR.value,
                details={"skip_reason": "usage error"},
            )
        ]

    if exit_code not in (0, 1):
        return [
            ToolEvidenceCandidate(
                source_type="tool",
                source_path=path,
                covers=[],
                status=CoverageStatus.BLOCKED.value,
                command=command,
                exit_code=exit_code,
                stderr=stderr or f"Mypy failed with exit code {exit_code}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
            )
        ]

    errors_count = 0
    # Try JSON report
    json_match = re.search(r"--json-report\s+(\S+)", command)
    if json_match:
        report_path = Path(json_match.group(1))
        if not report_path.is_absolute():
            report_path = project_root / report_path
        if report_path.exists():
            try:
                with report_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    errors_count = data.get("summary", {}).get("error_count", 0)
            except (json.JSONDecodeError, OSError):
                pass

    # Fallback: count error lines in stdout
    if errors_count == 0 and exit_code == 1:
        for line in stdout.splitlines():
            if ": error:" in line:
                errors_count += 1

    status = (
        CoverageStatus.COMPLIANT.value
        if errors_count == 0
        else CoverageStatus.VIOLATED.value
    )

    return [
        ToolEvidenceCandidate(
            source_type="tool",
            source_path=path,
            covers=[],
            status=status,
            command=command,
            exit_code=exit_code,
            details={"errors_count": errors_count},
        )
    ]


def parse_bandit_output(
    stdout: str,
    stderr: str,
    exit_code: int,
    command: str,
    path: str,
    project_root: Path,
) -> List[ToolEvidenceCandidate]:
    """Parse bandit -f json output."""
    if exit_code not in (0, 1):
        return [
            ToolEvidenceCandidate(
                source_type="tool",
                source_path=path,
                covers=[],
                status=CoverageStatus.BLOCKED.value,
                command=command,
                exit_code=exit_code,
                stderr=stderr or f"Bandit failed with exit code {exit_code}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
            )
        ]

    results: List[Any] = []

    # Try reading the output file
    json_match = re.search(r"-o\s+(\S+)", command)
    if json_match:
        output_path = Path(json_match.group(1))
        if not output_path.is_absolute():
            output_path = project_root / output_path
        if output_path.exists():
            try:
                with output_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    results = data.get("results", [])
                    if not isinstance(results, list):
                        results = []
            except (json.JSONDecodeError, OSError):
                pass

    # Fallback: try parsing stdout
    if not results:
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                results = data.get("results", [])
                if not isinstance(results, list):
                    results = []
            elif isinstance(data, list):
                results = data
        except (json.JSONDecodeError, TypeError):
            pass

    status = (
        CoverageStatus.COMPLIANT.value
        if not results
        else CoverageStatus.VIOLATED.value
    )

    return [
        ToolEvidenceCandidate(
            source_type="tool",
            source_path=path,
            covers=[],
            status=status,
            command=command,
            exit_code=exit_code,
            details={"results_count": len(results)},
        )
    ]


def parse_coverage_json_output(
    stdout: str,
    stderr: str,
    exit_code: int,
    command: str,
    path: str,
) -> List[ToolEvidenceCandidate]:
    """Parse coverage JSON output into evidence candidates.

    Expects the ``coverage.json`` format produced by ``coverage json``::

        {"files": {"/abs/path/to/file.py": {"summary": {"percent_covered": X, "num_statements": Y}}}}

    Files whose ``percent_covered`` is ``None`` are skipped.
    """
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return [
            ToolEvidenceCandidate(
                source_type="tool",
                source_path=path,
                covers=[],
                status=CoverageStatus.BLOCKED.value,
                command=command,
                exit_code=exit_code,
                stderr=stderr or "Failed to parse coverage JSON output",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
            )
        ]

    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        return [
            ToolEvidenceCandidate(
                source_type="tool",
                source_path=path,
                covers=[],
                status=CoverageStatus.BLOCKED.value,
                command=command,
                exit_code=exit_code,
                stderr=stderr or "Coverage JSON missing 'files' key",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
            )
        ]

    candidates: List[ToolEvidenceCandidate] = []
    for file_path, file_data in files.items():
        if not isinstance(file_data, dict):
            continue
        summary = file_data.get("summary", file_data)
        if not isinstance(summary, dict):
            continue
        percent = summary.get("percent_covered")
        num_stmts = summary.get("num_statements", 0)
        if percent is None:
            continue
        percent_f = float(percent)
        status = CoverageStatus.COMPLIANT.value  # Individual file parse result
        candidates.append(
            ToolEvidenceCandidate(
                source_type="tool",
                source_path=file_path,
                covers=[],
                status=status,
                command=command,
                exit_code=exit_code,
                details={
                    "percent_covered": percent_f,
                    "num_statements": num_stmts,
                },
            )
        )

    return candidates
