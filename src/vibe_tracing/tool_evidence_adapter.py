"""
Tool Output Evidence Adapter and Execution Engine for Vibe Tracing.

Converts outputs from tools (pytest, coverage, ruff, mypy, bandit) into normalized
evidence candidate structures. Provides tool execution capability based on the
language_tool_matrix from architecture_constraints.json.

MOD-VT-012: Tool Execution Engine - executes validation tools from whitelist only.
"""

import ast
import json
import re
import shlex
import subprocess
import tempfile
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from vibe_tracing.core.enums import CoverageStatus, ErrorCode


@dataclass
class ToolEvidenceCandidate:
    """Normalized evidence candidate parsed from a tool execution report."""

    source_type: str  # "test" (for pytest) or "tool" (for others)
    source_path: str  # Path to the source report file or test nodeid
    covers: List[str]  # AC or REQ IDs that this evidence covers
    status: str  # CoverageStatus enum value
    command: str = ""
    exit_code: int = 0
    stderr: str = ""
    error_code: Optional[str] = None  # ErrorCode value (e.g., tool_execution_failed)
    details: Dict[str, Any] = field(default_factory=dict)


# Allowed placeholder tokens for command template substitution.
# SEC-VT-001 / DEP-VT-008: only path placeholders may be substituted.
_ALLOWED_PLACEHOLDERS = {"{test_path}", "{source_path}", "{output_path}"}


class ToolExecutionEngine:
    """
    Executes validation tools based on language_tool_matrix configuration.

    Only tools listed in the whitelist (language_tool_matrix) are permitted.
    Command templates are populated via placeholder substitution; arbitrary
    commands are rejected.
    """

    DEFAULT_TIMEOUT = 120  # seconds

    def __init__(
        self,
        language_tool_matrix: Dict[str, Dict[str, Any]],
        language: str,
        validation_tools: List[str],
        project_root: Path,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """
        Args:
            language_tool_matrix: Full matrix from architecture_constraints.json.
            language: Active language key (e.g., "python").
            validation_tools: List of tool categories to run (e.g., ["test", "lint"]).
            project_root: Absolute path to project workspace root.
            timeout: Subprocess timeout in seconds.
        """
        self.language_tool_matrix = language_tool_matrix
        self.language = language
        self.validation_tools = list(validation_tools)
        self.project_root = project_root
        self.timeout = timeout

        # Build the active tool config map: {category -> tool_config_dict}
        lang_matrix = self.language_tool_matrix.get(self.language, {})
        self._tool_configs: Dict[str, Dict[str, Any]] = {}
        for category in self.validation_tools:
            if category in lang_matrix:
                self._tool_configs[category] = lang_matrix[category]

    # ------------------------------------------------------------------
    # Whitelist enforcement
    # ------------------------------------------------------------------

    def is_allowed_tool(self, tool_category: str) -> bool:
        """Return True if tool_category is in the active validation_tools whitelist."""
        return tool_category in self._tool_configs

    def get_tool_config(self, tool_category: str) -> Optional[Dict[str, Any]]:
        """Return the tool config dict for a category, or None if not whitelisted."""
        return self._tool_configs.get(tool_category)

    # ------------------------------------------------------------------
    # Path validation
    # ------------------------------------------------------------------

    def _validate_path(self, path_str: str) -> Tuple[bool, str]:
        """
        Validate that a path resolves inside the project root.

        Returns:
            (is_valid, error_message)
        """
        try:
            resolved = (self.project_root / path_str).resolve()
            project_resolved = self.project_root.resolve()
            if not (resolved == project_resolved or project_resolved in resolved.parents):
                return False, f"Path '{path_str}' resolves outside project root: {resolved}"
        except (ValueError, OSError) as exc:
            return False, f"Invalid path '{path_str}': {exc}"
        return True, ""

    # ------------------------------------------------------------------
    # Command template substitution
    # ------------------------------------------------------------------

    # Characters allowed in path values (safe for shell contexts)
    _SAFE_PATH_PATTERN = re.compile(r'^[a-zA-Z0-9_./\-:]+$')

    def _sanitize_path_value(self, path_str: str) -> str:
        """
        Sanitize a path value for safe shell substitution.

        Rejects paths containing shell metacharacters that could enable
        command injection: |, ;, &, $, `, (, ), {, }, <, >, !, ~, etc.

        Then applies shlex.quote() as defense-in-depth.
        """
        if not path_str:
            return ""
        if not self._SAFE_PATH_PATTERN.match(path_str):
            raise ValueError(
                f"Path '{path_str}' contains unsafe characters. "
                f"Only alphanumeric, underscore, dot, slash, and hyphen are allowed."
            )
        return shlex.quote(path_str)

    def _build_command(
        self,
        template: str,
        test_path: str = "",
        source_path: str = "",
        output_path: str = "",
    ) -> str:
        """
        Substitute placeholders in a command template with sanitized path values.

        Only {test_path}, {source_path}, and {output_path} are replaced.
        Path values are validated against shell metacharacters and quoted via shlex.quote().
        Any remaining unresolved placeholders cause a ValueError.
        """
        safe_test = self._sanitize_path_value(test_path)
        safe_source = self._sanitize_path_value(source_path)
        safe_output = self._sanitize_path_value(output_path)

        cmd = template
        cmd = cmd.replace("{test_path}", safe_test)
        cmd = cmd.replace("{source_path}", safe_source)
        cmd = cmd.replace("{output_path}", safe_output)

        # Reject if any placeholder-like tokens remain
        remaining = re.findall(r"\{[a-z_]+\}", cmd)
        if remaining:
            raise ValueError(
                f"Unresolved placeholders in command: {remaining}. "
                f"Only {', '.join(sorted(_ALLOWED_PLACEHOLDERS))} are permitted."
            )
        return cmd

    # ------------------------------------------------------------------
    # Subprocess execution
    # ------------------------------------------------------------------

    def _run_subprocess(
        self, command: str
    ) -> Tuple[int, str, str, Optional[str]]:
        """
        Execute a command string via subprocess.

        Uses shell=True with strict template-based validation (no arbitrary
        commands reach this point).

        Returns:
            (exit_code, stdout, stderr, error_message_or_none)
        """
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            return result.returncode, result.stdout, result.stderr, None
        except subprocess.TimeoutExpired:
            return -1, "", f"Tool execution timed out after {self.timeout}s", "timeout"
        except FileNotFoundError:
            return -1, "", f"Tool binary not found: {command.split()[0]}", "not_found"
        except PermissionError:
            return -1, "", f"Permission denied executing: {command}", "permission"
        except OSError as exc:
            return -1, "", f"OS error executing tool: {exc}", "os_error"

    # ------------------------------------------------------------------
    # Output parsers
    # ------------------------------------------------------------------

    def _parse_pytest_output(
        self, stdout: str, stderr: str, exit_code: int, command: str, path: str
    ) -> List[ToolEvidenceCandidate]:
        """Parse pytest --json-report output."""
        candidates: List[ToolEvidenceCandidate] = []

        # Check for execution failure (not test failure)
        if exit_code not in (0, 1, 2):
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
        # The --json-report-file flag writes to a file, so we need to read it
        json_match = re.search(r"--json-report-file=(\S+)", command)
        if json_match:
            report_path = Path(json_match.group(1))
            if not report_path.is_absolute():
                report_path = self.project_root / report_path
            if report_path.exists():
                try:
                    with report_path.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                    return self._parse_pytest_json(data, command, path)
                except (json.JSONDecodeError, OSError):
                    pass

        # Fallback: try parsing stdout as JSON
        try:
            data = json.loads(stdout)
            return self._parse_pytest_json(data, command, path)
        except (json.JSONDecodeError, TypeError):
            pass

        # Last resort: return a single candidate based on exit code
        status = CoverageStatus.COVERED.value if exit_code == 0 else CoverageStatus.VIOLATED.value
        if exit_code == 2:
            status = CoverageStatus.BLOCKED.value

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

    def _parse_pytest_json(
        self, data: Any, command: str, path: str
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

            if docstring is None and nodeid:
                docstring = self._get_test_docstring(nodeid)

            covers = self._extract_covers_from_docstring(docstring)

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

    def _parse_coverage_output(
        self, stdout: str, stderr: str, exit_code: int, command: str, path: str
    ) -> List[ToolEvidenceCandidate]:
        """Parse coverage JSON output."""
        if exit_code != 0:
            return [
                ToolEvidenceCandidate(
                    source_type="tool",
                    source_path=path,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    command=command,
                    exit_code=exit_code,
                    stderr=stderr or f"Coverage failed with exit code {exit_code}",
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                )
            ]

        # Try reading the JSON output file
        percent_covered = None
        json_match = re.search(r"-o\s+(\S+)", command)
        if json_match:
            output_path = Path(json_match.group(1))
            if not output_path.is_absolute():
                output_path = self.project_root / output_path
            if output_path.exists():
                try:
                    with output_path.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        totals = data.get("totals")
                        if isinstance(totals, dict):
                            percent_covered = totals.get("percent_covered")
                        if percent_covered is None:
                            percent_covered = data.get("percent_covered")
                except (json.JSONDecodeError, OSError):
                    pass

        # Fallback: try parsing stdout
        if percent_covered is None:
            try:
                data = json.loads(stdout)
                if isinstance(data, dict):
                    totals = data.get("totals")
                    if isinstance(totals, dict):
                        percent_covered = totals.get("percent_covered")
                    if percent_covered is None:
                        percent_covered = data.get("percent_covered")
            except (json.JSONDecodeError, TypeError):
                pass

        if percent_covered is None:
            return [
                ToolEvidenceCandidate(
                    source_type="tool",
                    source_path=path,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    command=command,
                    exit_code=exit_code,
                    stderr="Coverage percentage not found in output",
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                )
            ]

        status = (
            CoverageStatus.COMPLIANT.value
            if float(percent_covered) >= 80.0
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
                details={"percent_covered": float(percent_covered)},
            )
        ]

    def _parse_ruff_output(
        self, stdout: str, stderr: str, exit_code: int, command: str, path: str
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

    def _parse_mypy_output(
        self, stdout: str, stderr: str, exit_code: int, command: str, path: str
    ) -> List[ToolEvidenceCandidate]:
        """Parse mypy output."""
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
                report_path = self.project_root / report_path
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

    def _parse_bandit_output(
        self, stdout: str, stderr: str, exit_code: int, command: str, path: str
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
                output_path = self.project_root / output_path
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

    # ------------------------------------------------------------------
    # Public execution API
    # ------------------------------------------------------------------

    def execute_tool(
        self,
        tool_category: str,
        path: str,
        tool_config: Optional[Dict[str, Any]] = None,
        test_path: str = "",
        source_path: str = "",
        output_path: str = "",
    ) -> List[ToolEvidenceCandidate]:
        """
        Execute a single tool for a given path and return evidence candidates.

        Args:
            tool_category: One of "test", "coverage", "lint", "type_check", "security".
            path: The primary path (test file or source directory).
            tool_config: Override tool config dict. If None, uses the whitelisted config.
            test_path: Explicit test_path placeholder value (defaults to `path`).
            source_path: Explicit source_path placeholder value (defaults to `path`).
            output_path: Explicit output_path placeholder value (auto-generated if empty).

        Returns:
            List of ToolEvidenceCandidate objects.
        """
        # Whitelist check
        if tool_config is None:
            tool_config = self.get_tool_config(tool_category)
        if tool_config is None:
            return [
                ToolEvidenceCandidate(
                    source_type="tool",
                    source_path=path,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                    stderr=f"Tool category '{tool_category}' is not in the whitelist. "
                    f"Allowed: {sorted(self._tool_configs.keys())}",
                )
            ]

        # Resolve paths
        effective_test = test_path or path
        effective_source = source_path or path

        # Validate paths are inside project root
        for label, p in [("test_path", effective_test), ("source_path", effective_source)]:
            if p:
                ok, err = self._validate_path(p)
                if not ok:
                    return [
                        ToolEvidenceCandidate(
                            source_type="tool",
                            source_path=path,
                            covers=[],
                            status=CoverageStatus.BLOCKED.value,
                            error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                            stderr=err,
                        )
                    ]

        # Generate a temporary output path if not provided
        effective_output = output_path
        if not effective_output and "{output_path}" in tool_config.get("default_command", ""):
            tmp_dir = self.project_root / ".vibetracing" / "tmp"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            suffix = ".json"
            tmp_file = tempfile.NamedTemporaryFile(
                dir=str(tmp_dir), suffix=suffix, delete=False, prefix=f"vt_{tool_category}_"
            )
            effective_output = tmp_file.name
            tmp_file.close()

        # Build command from template
        template = tool_config.get("default_command", "")
        try:
            command = self._build_command(
                template,
                test_path=effective_test,
                source_path=effective_source,
                output_path=effective_output or "",
            )
        except ValueError as exc:
            return [
                ToolEvidenceCandidate(
                    source_type="tool",
                    source_path=path,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                    stderr=str(exc),
                )
            ]

        # Execute the command
        exit_code, stdout, stderr, exec_error = self._run_subprocess(command)

        if exec_error == "timeout":
            return [
                ToolEvidenceCandidate(
                    source_type="tool",
                    source_path=path,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    command=command,
                    exit_code=-1,
                    stderr=stderr,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                    details={"error_type": "timeout", "timeout_seconds": self.timeout},
                )
            ]

        if exec_error == "not_found":
            return [
                ToolEvidenceCandidate(
                    source_type="tool",
                    source_path=path,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    command=command,
                    exit_code=-1,
                    stderr=stderr,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                    details={"error_type": "tool_not_found"},
                )
            ]

        if exec_error:
            return [
                ToolEvidenceCandidate(
                    source_type="tool",
                    source_path=path,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    command=command,
                    exit_code=exit_code,
                    stderr=stderr,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                    details={"error_type": exec_error},
                )
            ]

        # Parse output based on output_format
        output_format = tool_config.get("output_format", "")

        if output_format == "pytest_json":
            return self._parse_pytest_output(stdout, stderr, exit_code, command, path)
        elif output_format == "coverage_json":
            return self._parse_coverage_output(stdout, stderr, exit_code, command, path)
        elif output_format == "ruff_json":
            return self._parse_ruff_output(stdout, stderr, exit_code, command, path)
        elif output_format == "mypy_json":
            return self._parse_mypy_output(stdout, stderr, exit_code, command, path)
        elif output_format == "bandit_json":
            return self._parse_bandit_output(stdout, stderr, exit_code, command, path)
        else:
            return [
                ToolEvidenceCandidate(
                    source_type="tool",
                    source_path=path,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    command=command,
                    exit_code=exit_code,
                    stderr=f"Unsupported output format: {output_format}",
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                )
            ]

    def execute_all(
        self,
        paths: List[str],
    ) -> List[ToolEvidenceCandidate]:
        """
        Execute all whitelisted tools for the given paths.

        Args:
            paths: List of paths (test files or source directories).

        Returns:
            Flat list of all ToolEvidenceCandidate objects.
        """
        all_candidates: List[ToolEvidenceCandidate] = []

        for category, config in self._tool_configs.items():
            for path in paths:
                candidates = self.execute_tool(
                    tool_category=category,
                    path=path,
                    tool_config=config,
                )
                all_candidates.extend(candidates)

        return all_candidates

    # ------------------------------------------------------------------
    # Docstring / covers extraction (shared with legacy adapter)
    # ------------------------------------------------------------------

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


class ToolEvidenceAdapter:
    """
    Adapts tool outputs (pytest, coverage, ruff, bandit) to normalized evidence candidates.

    DEPRECATED: The primary interface is now ToolExecutionEngine.execute_tool().
    This class is kept for backward compatibility with pre-existing report files.
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize the adapter with a project root path."""
        self.project_root = project_root

    def parse_report_file(self, file_path: Path) -> List[ToolEvidenceCandidate]:
        """
        Parse a single tool report file and return a list of normalized evidence candidates.

        Handles missing files, malformed JSON, and tool execution failures gracefully.

        DEPRECATED: Use ToolExecutionEngine.execute_tool() for active tool execution.
        """
        warnings.warn(
            "parse_report_file() is deprecated. Use ToolExecutionEngine.execute_tool() "
            "for active tool execution based on language_tool_matrix.",
            DeprecationWarning,
            stacklevel=2,
        )

        path_str = str(file_path)
        if not file_path.exists():
            return [
                ToolEvidenceCandidate(
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
