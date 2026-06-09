"""
Tool Execution Engine for Vibe Tracing.

Executes validation tools (pytest, coverage, ruff, mypy, bandit) based on the
language_tool_matrix from architecture_constraints.json and converts their outputs
into normalized evidence candidate structures.

MOD-VT-012: Tool Execution Engine - executes validation tools from whitelist only.
"""

import ast
import json
import re
import shlex
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from vibe_tracing.core.enums import CoverageStatus, ErrorCode
from vibe_tracing.tool_resolver import ToolResolver

_HINTS_PATH = Path(__file__).parent / "templates" / "field_hints.json"


def _load_hints(category: str) -> Dict[str, Any]:
    try:
        data = json.loads(_HINTS_PATH.read_text(encoding="utf-8"))
        return data.get(category, {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _resolve_hint(hint_value: Any, level: str = "level1") -> str:
    if isinstance(hint_value, str):
        return hint_value
    if isinstance(hint_value, dict):
        return hint_value.get(level, hint_value.get("level3", ""))
    return ""


def _safe_format(template: str, **kwargs: Any) -> str:
    """Replace only known placeholders, leaving other {token} literals intact."""
    result = template
    for key, value in kwargs.items():
        result = result.replace("{" + key + "}", str(value))
    return result


_tool_hints = _load_hints("tool")


@dataclass
class ToolEvidenceCandidate:
    """Normalized evidence candidate parsed from a tool execution report."""

    source_type: str  # "test" (for pytest) or "tool" (for others)
    source_path: str  # Path to the source report file or test nodeid
    covers: List[str]  # AC or REQ IDs that this evidence covers
    status: str  # CoverageStatus enum value
    tool_category: str = ""  # Tool category (e.g., "test", "lint", "type_check", "security", "coverage")
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

    # Map of tool category -> set of file extensions the tool should run on.
    # Used by execute_all() to skip paths that a tool cannot handle.
    # An empty set or missing category means "run on all files" (no filtering).
    TOOL_FILE_TYPE_MAP: Dict[str, set] = {
        "test": {".py"},
        "lint": {".py"},
        "type_check": {".py"},
        "security": {".py"},
    }

    # Map of path type ("test" or "source") -> set of tool categories that
    # should run on that path type.  Used by execute_all() when typed paths
    # are provided, replacing the extension-based heuristic with a semantic
    # classification: pytest runs only on test files, while
    # ruff/mypy/bandit run only on source files.
    # Coverage is measured per-source-file from a baseline, not via subprocess.
    PATH_TYPE_TOOL_MAP: Dict[str, set] = {
        "test": {"test"},
        "source": {"lint", "type_check", "security"},
    }

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
                hint = _resolve_hint(_tool_hints.get("path_outside_root", {}), "level1")
                msg = _safe_format(hint, path_str=path_str, resolved=resolved) if hint else f"Path '{path_str}' resolves outside project root: {resolved}"
                return False, msg
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
            hint = _resolve_hint(_tool_hints.get("unsafe_path_chars", {}), "level1")
            msg = _safe_format(hint, path_str=path_str) if hint else f"Path '{path_str}' contains unsafe characters. Only alphanumeric, underscore, dot, slash, and hyphen are allowed."
            raise ValueError(msg)
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
            hint = _resolve_hint(_tool_hints.get("unresolved_placeholders", {}), "level1")
            msg = _safe_format(hint,
                remaining=remaining, allowed_placeholders=', '.join(sorted(_ALLOWED_PLACEHOLDERS)),
            ) if hint else f"Unresolved placeholders in command: {remaining}. Only {', '.join(sorted(_ALLOWED_PLACEHOLDERS))} are permitted."
            raise ValueError(msg)
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
            hint = _resolve_hint(_tool_hints.get("execution_timeout", {}), "level1")
            source_path = command.split()[0] if command else ""
            msg = _safe_format(hint, source_path=source_path, timeout_seconds=self.timeout) if hint else f"Tool execution timed out after {self.timeout}s"
            return -1, "", msg, "timeout"
        except FileNotFoundError:
            hint = _resolve_hint(_tool_hints.get("binary_not_found", {}), "level1")
            cmd_token = command.split()[0] if command else ""
            msg = _safe_format(hint, command=cmd_token, tool_name=cmd_token) if hint else f"Tool binary not found: {cmd_token}"
            return -1, "", msg, "not_found"
        except PermissionError:
            hint = _resolve_hint(_tool_hints.get("permission_denied", {}), "level1")
            msg = _safe_format(hint, command=command) if hint else f"Permission denied executing: {command}"
            return -1, "", msg, "permission"
        except OSError as exc:
            hint = _resolve_hint(_tool_hints.get("subprocess_os_error", {}), "level1")
            msg = _safe_format(hint, exc=exc) if hint else f"OS error executing tool: {exc}"
            return -1, "", msg, "os_error"

    # ------------------------------------------------------------------
    # Output parsers
    # ------------------------------------------------------------------

    # Exit codes that indicate "tool cannot handle this file" rather than real
    # failures.  When one of these is returned we produce no evidence at all.
    PYTEST_SKIP_EXIT_CODES = {2, 5}  # 2 = usage error, 5 = no tests collected
    MYPY_SKIP_EXIT_CODES = {2}  # 2 = usage error

    def _parse_pytest_output(
        self, stdout: str, stderr: str, exit_code: int, command: str, path: str
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
        if exit_code in self.PYTEST_SKIP_EXIT_CODES:
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
        # (exit_code is guaranteed to be 0 or 1 at this point due to early returns)
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
        """Parse mypy output.

        Exit code classification:
        - 0: success
        - 1: type errors found (real, record as evidence)
        - 2: usage error (skip, not a real failure)
        """
        # Return a "skipped" evidence candidate for exit codes that indicate
        # "tool cannot handle this file" rather than real failures.
        if exit_code in self.MYPY_SKIP_EXIT_CODES:
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

    @staticmethod
    def _stamp_category(
        candidates: List["ToolEvidenceCandidate"], tool_category: str
    ) -> List["ToolEvidenceCandidate"]:
        """Stamp tool_category on every candidate in the list."""
        for c in candidates:
            c.tool_category = tool_category
        return candidates

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
        candidates: List[ToolEvidenceCandidate] = []

        # Whitelist check
        if tool_config is None:
            tool_config = self.get_tool_config(tool_category)
        if tool_config is None:
            hint = _resolve_hint(_tool_hints.get("category_not_whitelisted", {}), "level1")
            allowed = sorted(self._tool_configs.keys())
            msg = _safe_format(hint,
                tool_category=tool_category, allowed_categories=', '.join(allowed),
                language=self.language,
            ) if hint else f"Tool category '{tool_category}' is not in the whitelist. Allowed: {allowed}"
            candidates = [
                ToolEvidenceCandidate(
                    source_type="tool",
                    source_path=path,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                    stderr=msg,
                )
            ]
            return self._stamp_category(candidates, tool_category)

        # Resolve paths
        effective_test = test_path or path
        effective_source = source_path or path

        # Validate paths are inside project root
        for label, p in [("test_path", effective_test), ("source_path", effective_source)]:
            if p:
                ok, err = self._validate_path(p)
                if not ok:
                    candidates = [
                        ToolEvidenceCandidate(
                            source_type="tool",
                            source_path=path,
                            covers=[],
                            status=CoverageStatus.BLOCKED.value,
                            error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                            stderr=err,
                        )
                    ]
                    return self._stamp_category(candidates, tool_category)

        # Generate a temporary output path if not provided
        effective_output = output_path
        if not effective_output and "{output_path}" in tool_config.get("default_command", ""):
            tmp_dir = self.project_root / ".vibetracing" / "tmp"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            suffix = ".json"
            unique_id = uuid.uuid4().hex
            effective_output = str(tmp_dir / f"vt_{tool_category}_{unique_id}{suffix}")

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
            candidates = [
                ToolEvidenceCandidate(
                    source_type="tool",
                    source_path=path,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                    stderr=str(exc),
                )
            ]
            return self._stamp_category(candidates, tool_category)

        # Fallback: if tool binary not on PATH, try python3 -m <tool>
        command = ToolResolver.resolve_command(command)

        # Execute the command
        exit_code, stdout, stderr, exec_error = self._run_subprocess(command)

        if exec_error == "timeout":
            candidates = [
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
            return self._stamp_category(candidates, tool_category)

        if exec_error == "not_found":
            candidates = [
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
            return self._stamp_category(candidates, tool_category)

        if exec_error:
            candidates = [
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
            return self._stamp_category(candidates, tool_category)

        # Parse output based on output_format
        output_format = tool_config.get("output_format", "")

        if output_format == "pytest_json":
            candidates = self._parse_pytest_output(stdout, stderr, exit_code, command, path)
        elif output_format == "ruff_json":
            candidates = self._parse_ruff_output(stdout, stderr, exit_code, command, path)
        elif output_format == "mypy_json":
            candidates = self._parse_mypy_output(stdout, stderr, exit_code, command, path)
        elif output_format == "bandit_json":
            candidates = self._parse_bandit_output(stdout, stderr, exit_code, command, path)
        else:
            hint = _resolve_hint(_tool_hints.get("unsupported_output_format", {}), "level1")
            msg = _safe_format(hint, output_format=output_format) if hint else f"Unsupported output format: {output_format}"
            candidates = [
                ToolEvidenceCandidate(
                    source_type="tool",
                    source_path=path,
                    covers=[],
                    status=CoverageStatus.BLOCKED.value,
                    command=command,
                    exit_code=exit_code,
                    stderr=msg,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                )
            ]

        return self._stamp_category(candidates, tool_category)

    def _measure_source_coverage(
        self,
        baseline_path: Optional[str] = None,
        pass_threshold: float = 80.0,
    ) -> List[ToolEvidenceCandidate]:
        """Measure per-source-file coverage from a pre-built baseline.

        Reads ``.vibetracing/coverage_baseline.json`` (produced by the
        ``vt coverage-baseline`` command) and emits one
        ``ToolEvidenceCandidate`` per source file listed in the baseline.

        Args:
            baseline_path: Override path to the baseline JSON file.
                Defaults to ``.vibetracing/coverage_baseline.json`` relative
                to the project root.
            pass_threshold: Minimum percent_covered to be considered
                ``compliant``.  Files below this threshold are ``violated``.

        Returns:
            List of ToolEvidenceCandidate objects, one per source file.
            Returns an empty list if the baseline file does not exist or
            cannot be parsed.
        """
        baseline_file = Path(baseline_path) if baseline_path else (
            self.project_root / ".vibetracing" / "coverage_baseline.json"
        )

        if not baseline_file.is_file():
            return []

        try:
            with baseline_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

        files = data.get("files")
        if not isinstance(files, dict):
            return []

        candidates: List[ToolEvidenceCandidate] = []
        for source_path, file_data in files.items():
            if not isinstance(file_data, dict):
                continue

            percent = file_data.get("percent_covered")
            num_stmts = file_data.get("num_statements", 0)
            if percent is None:
                continue

            percent_f = float(percent)
            status = (
                CoverageStatus.COMPLIANT.value
                if percent_f >= pass_threshold
                else CoverageStatus.VIOLATED.value
            )

            candidates.append(
                ToolEvidenceCandidate(
                    source_type="tool",
                    source_path=source_path,
                    covers=[],
                    status=status,
                    tool_category="coverage",
                    details={
                        "percent_covered": percent_f,
                        "num_statements": int(num_stmts),
                        "measurement": "baseline",
                    },
                )
            )

        return candidates

    def execute_all(
        self,
        paths,
        baseline_path: Optional[str] = None,
    ) -> List[ToolEvidenceCandidate]:
        """
        Execute all whitelisted tools for the given paths.

        Args:
            paths: Either:
                - A flat ``List[str]`` of paths (legacy, backward-compatible).
                  Tool/category filtering uses ``TOOL_FILE_TYPE_MAP``.
                - A ``Dict[str, List[str]]`` mapping path types ("test" or
                  "source") to path lists.  Tool/category filtering uses
                  ``PATH_TYPE_TOOL_MAP`` so that only semantically
                  appropriate tools run on each path type.
            baseline_path: Override path to coverage baseline JSON.  If
                ``None``, defaults to ``.vibetracing/coverage_baseline.json``.

        Returns:
            Flat list of all ToolEvidenceCandidate objects.
        """
        all_candidates: List[ToolEvidenceCandidate] = []

        # Normalise to a list of (category, path) pairs to execute.
        if isinstance(paths, dict):
            # Typed path dict -- use PATH_TYPE_TOOL_MAP for filtering.
            pairs: List[Tuple[str, str]] = []
            for path_type, path_list in paths.items():
                allowed_categories = self.PATH_TYPE_TOOL_MAP.get(path_type)
                if allowed_categories is None:
                    # Unknown path type -- skip entirely.
                    continue
                for path in path_list:
                    for category in allowed_categories:
                        if category in self._tool_configs:
                            pairs.append((category, path))
        else:
            # Flat list -- fall back to TOOL_FILE_TYPE_MAP (legacy mode).
            pairs = []
            for category, config in self._tool_configs.items():
                allowed_extensions = self.TOOL_FILE_TYPE_MAP.get(category)
                for path in paths:
                    if allowed_extensions is not None and len(allowed_extensions) > 0:
                        path_suffix = Path(path).suffix
                        if path_suffix not in allowed_extensions:
                            continue
                    pairs.append((category, path))

        for category, path in pairs:
            config = self._tool_configs[category]
            candidates = self.execute_tool(
                tool_category=category,
                path=path,
                tool_config=config,
            )
            all_candidates.extend(candidates)

        # Append per-source-file coverage evidence from the baseline.
        all_candidates.extend(self._measure_source_coverage(baseline_path))

        return all_candidates

    # ------------------------------------------------------------------
    # Docstring / covers extraction
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

            current_node: ast.AST = tree
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
