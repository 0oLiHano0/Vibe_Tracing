"""
Tool execution for validation tools.
"""

import sys
from pathlib import Path
from typing import List

from vibe_tracing.domain.context import UnifiedContext
from vibe_tracing.infra.logging.logger import OperationalLogger


def _execute_tools(
    ctx: UnifiedContext,
    project_root: Path,
) -> List:
    """Execute validation tools and return tool evidence candidates.

    Pre-conditions guaranteed by finalize:
        - config["language"] exists and is non-empty
        - config["language_tool_matrix"] exists and has language key
    """
    vt_logger = OperationalLogger.get()
    config_data = ctx.config
    claims_list = ctx.claims_list

    config_language = config_data["language"]
    ltm = config_data["language_tool_matrix"]
    lang_tools = ltm.get(config_language, {})
    config_validation_tools = [k for k, v in lang_tools.items() if isinstance(v, dict)]

    from vibe_tracing.infra.tools.executor import ToolExecutionEngine
    from vibe_tracing.infra.tools.resolver import ToolResolver

    # Pre-flight dependency check
    required_binaries = set()
    for category in config_validation_tools:
        tool_cfg = lang_tools.get(category, {})
        tool_name = tool_cfg.get("tool")
        if tool_name:
            required_binaries.add(tool_name)

    missing = sorted(t for t in required_binaries if not ToolResolver.is_available(t))
    if missing:
        vt_logger.warning("tool_precheck_failed", "Tool dependency pre-check failed",
                          missing_tools=missing)
        print("\n[AI Agent Repair Guide]", file=sys.stderr)
        print(
            f"VT depends on tools that are missing in the environment: {', '.join(missing)}",
            file=sys.stderr,
        )
        print(f"Action Required: pip install {' '.join(missing)}", file=sys.stderr)
        print("Skipping tool execution. Install tools to enable full evidence collection.", file=sys.stderr)
        return []

    coverage_baseline_path = str(project_root / "coverage.json")
    engine = ToolExecutionEngine(
        language_tool_matrix=ltm,
        language=config_language,
        validation_tools=config_validation_tools,
        project_root=project_root,
        coverage_baseline_path=coverage_baseline_path,
    )

    # Collect paths to execute tools against (code files only), separated
    # into test paths and source paths for semantic tool routing.
    lang_config = ltm.get(config_language, {})
    code_extensions = set(lang_config.get("extensions", [".py"]))
    if not code_extensions:
        vt_logger.warning("no_code_extensions", "No code extensions defined in language_tool_matrix")
        print("Skipping tool execution: no file extensions defined in language_tool_matrix.", file=sys.stderr)
        return []
    test_paths: List[str] = []
    source_paths: List[str] = []
    seen_paths = set()

    for claim in claims_list:
        for ref in claim.test_refs:
            path_only = ref.split("#")[0]
            if path_only and Path(path_only).suffix in code_extensions and path_only not in seen_paths and (project_root / path_only).exists():
                test_paths.append(path_only)
                seen_paths.add(path_only)
        for ref in claim.code_refs:
            path_only = ref.split("#")[0]
            if path_only and Path(path_only).suffix in code_extensions and path_only not in seen_paths and (project_root / path_only).exists():
                source_paths.append(path_only)
                seen_paths.add(path_only)

    if not test_paths and not source_paths:
        vt_logger.warning("no_code_files", "No code files found in claims")
        print("Skipping tool execution: no code files found in claims.", file=sys.stderr)
        return []

    total_paths = len(test_paths) + len(source_paths)
    vt_logger.info("tool_execution_start", "Starting tool execution",
                   total_paths=total_paths,
                   test_paths=len(test_paths),
                   source_paths=len(source_paths))
    print(f"Executing validation tools for {total_paths} path(s)...")
    typed_paths = {"test": test_paths, "source": source_paths}
    tool_evidence_candidates = engine.execute_all(typed_paths)

    executed_count = len(tool_evidence_candidates)
    blocked_count = sum(1 for c in tool_evidence_candidates if c.error_code is not None)
    skipped_count = sum(1 for c in tool_evidence_candidates if c.status == "skipped")
    if skipped_count > 0:
        vt_logger.info("tool_files_skipped", "Some files skipped by tool engine",
                       skipped_count=skipped_count)
        print(f"  ({skipped_count} files skipped -- no tests collected or usage error)", file=sys.stderr)

    for c in tool_evidence_candidates:
        if c.error_code is not None:
            details = c.details or {}
            error_type = details.get("error_type", "unknown")
            vt_logger.warning("tool_execution_error", "Tool execution error",
                              source_path=c.source_path,
                              error_type=error_type,
                              exit_code=c.exit_code)
            if error_type == "timeout":
                print(
                    f"Error: {c.source_path} timed out after {details.get('timeout_seconds', '?')}s. "
                    f"Increase timeout or simplify the test.",
                    file=sys.stderr,
                )
            elif error_type == "tool_not_found":
                print(
                    f"Error: tool not found for {c.source_path}. "
                    f"Ensure the required tool is installed.",
                    file=sys.stderr,
                )
            else:
                print(
                    f"Error: {c.source_path} failed (exit code {c.exit_code}). {c.stderr}",
                    file=sys.stderr,
                )
    vt_logger.info("tool_execution_complete", "Tool execution completed",
                   executed_count=executed_count,
                   blocked_count=blocked_count,
                   skipped_count=skipped_count)
    print(f"Tool execution complete: {executed_count} evidence candidates ({blocked_count} blocked)")
    return tool_evidence_candidates
