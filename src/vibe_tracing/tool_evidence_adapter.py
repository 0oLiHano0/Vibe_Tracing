"""
Tool Output Evidence Adapter for Vibe Tracing.

Converts outputs from tools (pytest, coverage, ruff, bandit) into normalized
evidence candidate structures. Handles tool execution failures, parses covers tags
from test docstrings (with AST fallback), and validates compliance status.
"""

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from vibe_tracing.core.enums import CoverageStatus, ErrorCode


@dataclass
class ToolEvidenceCandidate:
    """Normalized evidence candidate parsed from a tool execution report."""

    evidence_id: str
    source_type: str  # "test" (for pytest) or "tool" (for others)
    source_path: str  # Path to the source report file or test nodeid
    covers: List[str]  # AC or REQ IDs that this evidence covers
    status: str  # CoverageStatus enum value
    command: str = ""
    exit_code: int = 0
    stderr: str = ""
    error_code: Optional[str] = None  # ErrorCode value (e.g., tool_execution_failed)
    details: Dict[str, Any] = field(default_factory=dict)


class ToolEvidenceAdapter:
    """Adapts tool outputs (pytest, coverage, ruff, bandit) to normalized evidence candidates."""

    def __init__(self, project_root: Path) -> None:
        """Initialize the adapter with a project root path."""
        self.project_root = project_root
        self._evidence_counter = 1

    def _next_evidence_id(self) -> str:
        """Generate the next sequential evidence ID matching the Vibe Tracing schema."""
        ev_id = f"EVIDENCE-VT-{self._evidence_counter:03d}"
        self._evidence_counter += 1
        return ev_id

    def parse_report_file(self, file_path: Path) -> List[ToolEvidenceCandidate]:
        """
        Parse a single tool report file and return a list of normalized evidence candidates.

        Handles missing files, malformed JSON, and tool execution failures gracefully.
        """
        path_str = str(file_path)
        if not file_path.exists():
            return [
                ToolEvidenceCandidate(
                    evidence_id=self._next_evidence_id(),
                    source_type="tool",
                    source_path=path_str,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                    stderr=f"Report file not found: {path_str}",
                )
            ]

        try:
            with file_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            return [
                ToolEvidenceCandidate(
                    evidence_id=self._next_evidence_id(),
                    source_type="tool",
                    source_path=path_str,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                    stderr=f"Failed to parse JSON report: {exc}",
                )
            ]

        # Detect tool type
        tool_type = None
        if isinstance(data, dict):
            tool_type = data.get("tool")

        if not tool_type:
            # Fallback to filename detection
            filename_lower = file_path.name.lower()
            if "pytest" in filename_lower:
                tool_type = "pytest"
            elif "coverage" in filename_lower:
                tool_type = "coverage"
            elif "ruff" in filename_lower:
                tool_type = "ruff"
            elif "bandit" in filename_lower:
                tool_type = "bandit"

        if not tool_type:
            return [
                ToolEvidenceCandidate(
                    evidence_id=self._next_evidence_id(),
                    source_type="tool",
                    source_path=path_str,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                    stderr=f"Unrecognized tool report type for file: {path_str}",
                )
            ]

        # Route to specific parser
        if tool_type == "pytest":
            return self._parse_pytest(data, path_str)
        elif tool_type == "coverage":
            return self._parse_coverage(data, path_str)
        elif tool_type == "ruff":
            return self._parse_ruff(data, path_str)
        elif tool_type == "bandit":
            return self._parse_bandit(data, path_str)
        else:
            return [
                ToolEvidenceCandidate(
                    evidence_id=self._next_evidence_id(),
                    source_type="tool",
                    source_path=path_str,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                    stderr=f"Unsupported tool type '{tool_type}'",
                )
            ]

    def _parse_pytest(self, data: Any, path_str: str) -> List[ToolEvidenceCandidate]:
        """Parse pytest report data."""
        if not isinstance(data, dict):
            return [
                ToolEvidenceCandidate(
                    evidence_id=self._next_evidence_id(),
                    source_type="tool",
                    source_path=path_str,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                    stderr="Pytest report must be a JSON object",
                )
            ]

        command = data.get("command", "pytest")
        exit_code = data.get("exit_code", 0)
        stderr = data.get("stderr", "")

        # Check if pytest failed to execute (exit code not in 0 or 1)
        if exit_code not in (0, 1):
            return [
                ToolEvidenceCandidate(
                    evidence_id=self._next_evidence_id(),
                    source_type="tool",
                    source_path=path_str,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    command=command,
                    exit_code=exit_code,
                    stderr=stderr
                    or f"Pytest execution failed with exit code {exit_code}",
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                )
            ]

        tests_data = data.get("tests", [])
        if not isinstance(tests_data, list):
            return [
                ToolEvidenceCandidate(
                    evidence_id=self._next_evidence_id(),
                    source_type="tool",
                    source_path=path_str,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    command=command,
                    exit_code=exit_code,
                    stderr="Pytest report missing 'tests' array or invalid format",
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                )
            ]

        candidates = []
        for test in tests_data:
            if not isinstance(test, dict):
                continue
            nodeid = test.get("nodeid", "")
            outcome = test.get("outcome", "")
            docstring = test.get("docstring")

            # Fallback to metadata
            if (
                docstring is None
                and "metadata" in test
                and isinstance(test["metadata"], dict)
            ):
                docstring = test["metadata"].get("docstring")

            # Fallback to AST extraction
            if docstring is None and nodeid:
                docstring = self._get_test_docstring(nodeid)

            covers = self._extract_covers_from_docstring(docstring)

            # Map outcomes
            if outcome == "passed":
                status = CoverageStatus.COVERED.value
            elif outcome in ("failed", "error"):
                status = CoverageStatus.VIOLATED.value
            else:
                status = CoverageStatus.UNCLEAR.value

            candidates.append(
                ToolEvidenceCandidate(
                    evidence_id=self._next_evidence_id(),
                    source_type="test",
                    source_path=nodeid or path_str,
                    covers=covers,
                    status=status,
                    command=command,
                    exit_code=exit_code,
                    stderr=stderr,
                    details={"nodeid": nodeid, "outcome": outcome},
                )
            )

        return candidates

    def _parse_coverage(self, data: Any, path_str: str) -> List[ToolEvidenceCandidate]:
        """Parse coverage report data."""
        if not isinstance(data, dict):
            return [
                ToolEvidenceCandidate(
                    evidence_id=self._next_evidence_id(),
                    source_type="tool",
                    source_path=path_str,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                    stderr="Coverage report must be a JSON object",
                )
            ]

        command = data.get("command", "coverage")
        exit_code = data.get("exit_code", 0)
        stderr = data.get("stderr", "")

        if exit_code != 0:
            return [
                ToolEvidenceCandidate(
                    evidence_id=self._next_evidence_id(),
                    source_type="tool",
                    source_path=path_str,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    command=command,
                    exit_code=exit_code,
                    stderr=stderr
                    or f"Coverage execution failed with exit code {exit_code}",
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                )
            ]

        inner_data = data.get("data", data)
        percent_covered = None

        if isinstance(inner_data, dict):
            totals = inner_data.get("totals")
            if isinstance(totals, dict):
                percent_covered = totals.get("percent_covered")
            else:
                percent_covered = inner_data.get("percent_covered")

        if percent_covered is None:
            return [
                ToolEvidenceCandidate(
                    evidence_id=self._next_evidence_id(),
                    source_type="tool",
                    source_path=path_str,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    command=command,
                    exit_code=exit_code,
                    stderr="Coverage percentage not found in report",
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                )
            ]

        covers = data.get("covers", [])
        if not isinstance(covers, list):
            covers = []

        # Default coverage compliance threshold is 80.0%
        status = (
            CoverageStatus.COMPLIANT.value
            if float(percent_covered) >= 80.0
            else CoverageStatus.VIOLATED.value
        )

        return [
            ToolEvidenceCandidate(
                evidence_id=self._next_evidence_id(),
                source_type="tool",
                source_path=path_str,
                covers=covers,
                status=status,
                command=command,
                exit_code=exit_code,
                stderr=stderr,
                details={"percent_covered": float(percent_covered)},
            )
        ]

    def _parse_ruff(self, data: Any, path_str: str) -> List[ToolEvidenceCandidate]:
        """Parse Ruff lint report data."""
        if not isinstance(data, dict):
            # Ruff might output list directly if raw JSON check output is provided
            if isinstance(data, list):
                data = {"data": data}
            else:
                return [
                    ToolEvidenceCandidate(
                        evidence_id=self._next_evidence_id(),
                        source_type="tool",
                        source_path=path_str,
                        covers=[],
                        status=CoverageStatus.BLOCKED.value,
                        error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                        stderr="Ruff report must be a JSON object or array",
                    )
                ]

        command = data.get("command", "ruff check")
        exit_code = data.get("exit_code", 0)
        stderr = data.get("stderr", "")

        # Ruff exits with 1 on violations found, other non-zeros indicate crash/failures
        if exit_code not in (0, 1):
            return [
                ToolEvidenceCandidate(
                    evidence_id=self._next_evidence_id(),
                    source_type="tool",
                    source_path=path_str,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    command=command,
                    exit_code=exit_code,
                    stderr=stderr
                    or f"Ruff execution failed with exit code {exit_code}",
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                )
            ]

        inner_data = data.get("data", data)
        violations = []
        if isinstance(inner_data, list):
            violations = inner_data
        elif isinstance(inner_data, dict):
            for key in ("violations", "results", "issues"):
                if isinstance(inner_data.get(key), list):
                    violations = inner_data[key]
                    break

        covers = data.get("covers", [])
        if not isinstance(covers, list):
            covers = []

        status = (
            CoverageStatus.COMPLIANT.value
            if not violations
            else CoverageStatus.VIOLATED.value
        )

        return [
            ToolEvidenceCandidate(
                evidence_id=self._next_evidence_id(),
                source_type="tool",
                source_path=path_str,
                covers=covers,
                status=status,
                command=command,
                exit_code=exit_code,
                stderr=stderr,
                details={"violations_count": len(violations)},
            )
        ]

    def _parse_bandit(self, data: Any, path_str: str) -> List[ToolEvidenceCandidate]:
        """Parse Bandit security report data."""
        if not isinstance(data, dict):
            return [
                ToolEvidenceCandidate(
                    evidence_id=self._next_evidence_id(),
                    source_type="tool",
                    source_path=path_str,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                    stderr="Bandit report must be a JSON object",
                )
            ]

        command = data.get("command", "bandit")
        exit_code = data.get("exit_code", 0)
        stderr = data.get("stderr", "")

        # Bandit exits with 1 on issues found
        if exit_code not in (0, 1):
            return [
                ToolEvidenceCandidate(
                    evidence_id=self._next_evidence_id(),
                    source_type="tool",
                    source_path=path_str,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    command=command,
                    exit_code=exit_code,
                    stderr=stderr
                    or f"Bandit execution failed with exit code {exit_code}",
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                )
            ]

        inner_data = data.get("data", data)
        results = []
        if isinstance(inner_data, dict):
            results = inner_data.get("results", [])
            if not isinstance(results, list):
                results = []
        elif isinstance(inner_data, list):
            results = inner_data

        covers = data.get("covers", [])
        if not isinstance(covers, list):
            covers = []

        status = (
            CoverageStatus.COMPLIANT.value
            if not results
            else CoverageStatus.VIOLATED.value
        )

        return [
            ToolEvidenceCandidate(
                evidence_id=self._next_evidence_id(),
                source_type="tool",
                source_path=path_str,
                covers=covers,
                status=status,
                command=command,
                exit_code=exit_code,
                stderr=stderr,
                details={"results_count": len(results)},
            )
        ]

    def _get_test_docstring(self, nodeid: str) -> Optional[str]:
        """Extract docstring of a test function/method from Python source file using AST."""
        try:
            parts = nodeid.split("::")
            file_rel_path = parts[0]
            file_path = self.project_root / file_rel_path
            if not file_path.is_file():
                return None

            with file_path.open("r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(file_path))

            current_node = tree
            target_names = parts[1:]

            for name in target_names:
                # Remove parameterized test arguments, e.g., test_func[arg1] -> test_func
                clean_name = name.split("[")[0]
                found = False
                for node in ast.iter_child_nodes(current_node):
                    if (
                        isinstance(
                            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                        )
                        and node.name == clean_name
                    ):
                        current_node = node
                        found = True
                        break
                if not found:
                    return None

            if isinstance(current_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return ast.get_docstring(current_node)
        except Exception:
            pass
        return None

    def _extract_covers_from_docstring(self, docstring: Optional[str]) -> List[str]:
        """Extract covers AC or REQ IDs from docstring lines containing 'covers'."""
        if not docstring:
            return []
        covers_ids = []
        for line in docstring.splitlines():
            if "covers" in line.lower():
                matches = re.findall(
                    r"\b(AC-VT-\d+-\d+|REQ-VT-\d+)\b", line, re.IGNORECASE
                )
                for m in matches:
                    val = m.upper()
                    if val not in covers_ids:
                        covers_ids.append(val)
        return covers_ids
