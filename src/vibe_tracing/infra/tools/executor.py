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
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from vibe_tracing.infra.config.enums import CoverageStatus, ErrorCode
from vibe_tracing.infra.config.hint_loader import load_hints, resolve_hint
from vibe_tracing.infra.logging.logger import OperationalLogger
from vibe_tracing.infra.tools.resolver import ToolResolver
from vibe_tracing.domain.evidence.candidate import ToolEvidenceCandidate, ToolExecutionResult
from vibe_tracing.infra.tools.parsers import (
    parse_pytest_output,
    parse_pytest_json,
    parse_ruff_output,
    parse_mypy_output,
    parse_bandit_output,
    parse_coverage_json_output,
)


def _safe_format(template: str, **kwargs: Any) -> str:
    """Replace only known placeholders, leaving other {token} literals intact."""
    result = template
    for key, value in kwargs.items():
        result = result.replace("{" + key + "}", str(value))
    return result


_tool_hints = load_hints("tool")


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
        coverage_baseline_path: Optional[str] = None,
    ) -> None:
        """
        Args:
            language_tool_matrix: Full matrix from architecture_constraints.json.
            language: Active language key (e.g., "python").
            validation_tools: List of tool categories to run (e.g., ["test", "lint"]).
            project_root: Absolute path to project workspace root.
            timeout: Subprocess timeout in seconds.
            coverage_baseline_path: Optional path to a coverage.json baseline file.
        """
        self.language_tool_matrix = language_tool_matrix
        self.language = language
        self.validation_tools = list(validation_tools)
        self.project_root = project_root
        self.timeout = timeout
        self.coverage_baseline_path = coverage_baseline_path

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
                hint = resolve_hint(_tool_hints.get("path_outside_root", {}), "level1")
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
            hint = resolve_hint(_tool_hints.get("unsafe_path_chars", {}), "level1")
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
            hint = resolve_hint(_tool_hints.get("unresolved_placeholders", {}), "level1")
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
            cmd_name = command.split()[0] if command else ""
            _t = time.perf_counter()
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            duration_ms = int((time.perf_counter() - _t) * 1000)
            try:
                from vibe_tracing.infra.logging.logger import OperationalLogger
                vt_logger = OperationalLogger.get()
                vt_logger.info("subprocess_exec", "Tool subprocess completed",
                               command=cmd_name,
                               duration_ms=duration_ms,
                               exit_code=result.returncode,
                               stdout_size=len(result.stdout or ""),
                               stderr_size=len(result.stderr or ""))
                vt_logger.debug("subprocess_output", "Subprocess stdout/stderr",
                                command=cmd_name,
                                stdout_preview=(result.stdout or "")[:500],
                                stderr_preview=(result.stderr or "")[:500])
            except Exception:
                pass  # Never block on logging
            return result.returncode, result.stdout, result.stderr, None
        except subprocess.TimeoutExpired:
            hint = resolve_hint(_tool_hints.get("execution_timeout", {}), "level1")
            source_path = command.split()[0] if command else ""
            msg = _safe_format(hint, source_path=source_path, timeout_seconds=self.timeout) if hint else f"Tool execution timed out after {self.timeout}s"
            return -1, "", msg, "timeout"
        except FileNotFoundError:
            hint = resolve_hint(_tool_hints.get("binary_not_found", {}), "level1")
            cmd_token = command.split()[0] if command else ""
            msg = _safe_format(hint, command=cmd_token, tool_name=cmd_token) if hint else f"Tool binary not found: {cmd_token}"
            return -1, "", msg, "not_found"
        except PermissionError:
            hint = resolve_hint(_tool_hints.get("permission_denied", {}), "level1")
            msg = _safe_format(hint, command=command) if hint else f"Permission denied executing: {command}"
            return -1, "", msg, "permission"
        except OSError as exc:
            hint = resolve_hint(_tool_hints.get("subprocess_os_error", {}), "level1")
            msg = _safe_format(hint, exc=exc) if hint else f"OS error executing tool: {exc}"
            return -1, "", msg, "os_error"

    # ------------------------------------------------------------------
    # Public execution API
    # ------------------------------------------------------------------

    # Exit codes that indicate "tool cannot handle this file" rather than real
    # failures.  When one of these is returned we produce no evidence at all.
    PYTEST_SKIP_EXIT_CODES = {2, 5}  # 2 = usage error, 5 = no tests collected
    MYPY_SKIP_EXIT_CODES = {2}  # 2 = usage error

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
            hint = resolve_hint(_tool_hints.get("category_not_whitelisted", {}), "level1")
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
            candidates = parse_pytest_output(
                stdout, stderr, exit_code, command, path,
                self.project_root, self.PYTEST_SKIP_EXIT_CODES,
                self._get_test_docstring, self._extract_covers_from_docstring,
            )
        elif output_format == "ruff_json":
            candidates = parse_ruff_output(stdout, stderr, exit_code, command, path)
        elif output_format == "mypy_json":
            candidates = parse_mypy_output(
                stdout, stderr, exit_code, command, path,
                self.MYPY_SKIP_EXIT_CODES,
            )
        elif output_format == "bandit_json":
            candidates = parse_bandit_output(
                stdout, stderr, exit_code, command, path,
                self.project_root,
            )
        elif output_format == "coverage_json":
            candidates = parse_coverage_json_output(stdout, stderr, exit_code, command, path)
        else:
            hint = resolve_hint(_tool_hints.get("unsupported_output_format", {}), "level1")
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
        evidence_index: Optional[Dict[str, Any]] = None,
    ) -> List[ToolEvidenceCandidate]:
        """Measure per-source-file coverage from a pre-built baseline.

        Reads per-file coverage data and emits one ``ToolEvidenceCandidate``
        per source file.  The primary data source is the ``coverage_baseline``
        field in the evidence index (if provided).  An explicit
        ``baseline_path`` can also point to a JSON file with per-file data.

        Args:
            baseline_path: Optional path to a coverage baseline JSON file.
                Only used when ``evidence_index`` has no ``coverage_baseline``.
            pass_threshold: Minimum percent_covered to be considered
                ``compliant``.  Files below this threshold are ``violated``.
            evidence_index: Pre-loaded evidence index dict.  If it contains
                a ``coverage_baseline`` key, that data is used directly.

        Returns:
            List of ToolEvidenceCandidate objects, one per source file.
            Returns an empty list if no baseline data is available.
        """
        # Try evidence_index first (primary path)
        if evidence_index and isinstance(evidence_index.get("coverage_baseline"), dict):
            files = evidence_index["coverage_baseline"]
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

        # Fallback: read from explicit file path only.
        # No default path — if baseline_path is None, no data is available.
        if baseline_path is None:
            return []

        baseline_file = Path(baseline_path)

        if not baseline_file.is_file():
            return []

        try:
            with baseline_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            OperationalLogger.get().debug("tool_output_parse_failed", "Could not parse coverage baseline file", path=str(baseline_path))
            return []

        files = data.get("files")
        if not isinstance(files, dict):
            return []

        candidates = []
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

    def execute_from_claims(
        self,
        claims_list: List[Any],
        project_root: Path,
    ) -> ToolExecutionResult:
        """Execute tools from claims: precheck → path collection → execution → stats.

        This is the sole entry point for tool execution. All logic is internal:
        precheck, path collection, per-file execution, coverage baseline, logging.
        No print() calls — only vt_logger. Callers use the structured result
        to decide what to print.

        Args:
            claims_list: List of Claim objects with test_refs and code_refs.
            project_root: Project root directory.

        Returns:
            ToolExecutionResult with candidates and metadata.
        """
        vt_logger = OperationalLogger.get()

        # --- 1. Precheck: verify required tool binaries are available ---
        lang_config = self.language_tool_matrix.get(self.language, {})
        code_extensions = set(lang_config.get("extensions", [".py"]))
        if not code_extensions:
            vt_logger.warning("no_code_extensions", "No code extensions defined in language_tool_matrix")
            return ToolExecutionResult(candidates=[], skipped=True, skip_reason="no_extensions")

        required_binaries: set = set()
        for category in self.validation_tools:
            tool_cfg = self._tool_configs.get(category, {})
            tool_name = tool_cfg.get("tool")
            if tool_name:
                required_binaries.add(tool_name)

        missing = sorted(t for t in required_binaries if not ToolResolver.is_available(t))
        if missing:
            vt_logger.warning("tool_precheck_failed", "Tool dependency pre-check failed",
                              missing_tools=missing)
            return ToolExecutionResult(candidates=[], skipped=True,
                                      skip_reason="precheck_failed", missing_tools=missing)

        # --- 2. Collect paths from claims (test vs source) ---
        test_paths: List[str] = []
        source_paths: List[str] = []
        seen_paths: set = set()

        for claim in claims_list:
            for ref in claim.test_refs:
                path_only = ref.split("#")[0]
                if (path_only and Path(path_only).suffix in code_extensions
                        and path_only not in seen_paths
                        and (project_root / path_only).exists()):
                    test_paths.append(path_only)
                    seen_paths.add(path_only)
            for ref in claim.code_refs:
                path_only = ref.split("#")[0]
                if (path_only and Path(path_only).suffix in code_extensions
                        and path_only not in seen_paths
                        and (project_root / path_only).exists()):
                    source_paths.append(path_only)
                    seen_paths.add(path_only)

        if not test_paths and not source_paths:
            vt_logger.warning("no_code_files", "No code files found in claims")
            return ToolExecutionResult(candidates=[], skipped=True, skip_reason="no_code_files")

        total_paths = len(test_paths) + len(source_paths)
        vt_logger.info("tool_execution_start", "Starting tool execution",
                       total_paths=total_paths,
                       test_paths=len(test_paths),
                       source_paths=len(source_paths))

        # --- 3. Execute tools per path, route by test/source ---
        all_candidates: List[ToolEvidenceCandidate] = []
        typed_paths = [(p, "test") for p in test_paths] + [(p, "source") for p in source_paths]

        for path, path_type in typed_paths:
            for category in self.validation_tools:
                if category == "coverage":
                    continue  # batch tool, handled below
                config = self._tool_configs.get(category)
                if config is None:
                    continue
                if path_type == "test" and category != "test":
                    continue
                if path_type == "source" and category == "test":
                    continue

                candidates = self.execute_tool(
                    tool_category=category,
                    path=path,
                    tool_config=config,
                )
                all_candidates.extend(candidates)

        # --- 4. Append per-source-file coverage evidence from baseline ---
        all_candidates.extend(self._measure_source_coverage(
            baseline_path=self.coverage_baseline_path,
        ))

        # --- 5. Log statistics ---
        executed_count = len(all_candidates)
        blocked_count = sum(1 for c in all_candidates if c.error_code is not None)
        skipped_count = sum(1 for c in all_candidates if c.status == "skipped")

        if skipped_count > 0:
            vt_logger.info("tool_files_skipped", "Some files skipped by tool engine",
                           skipped_count=skipped_count)

        for c in all_candidates:
            if c.error_code is not None:
                details = c.details or {}
                error_type = details.get("error_type", "unknown")
                vt_logger.warning("tool_execution_error", "Tool execution error",
                                  source_path=c.source_path,
                                  error_type=error_type,
                                  exit_code=c.exit_code)

        vt_logger.info("tool_execution_complete", "Tool execution completed",
                       executed_count=executed_count,
                       blocked_count=blocked_count,
                       skipped_count=skipped_count)

        return ToolExecutionResult(candidates=all_candidates)

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
