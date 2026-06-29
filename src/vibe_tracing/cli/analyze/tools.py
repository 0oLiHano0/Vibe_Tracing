"""
Tool execution and staged-file checks.
"""

import sys
from pathlib import Path
from typing import List, Optional, Set

from vibe_tracing.domain.context import UnifiedContext


def _execute_tools(
    ctx: UnifiedContext,
    project_root: Path,
    staged_files: Optional[Set[str]] = None,
) -> List:
    """Execute validation tools and return tool evidence candidates.

    Pre-conditions guaranteed by finalize + Stage 1:
        - config["language"] exists and is non-empty
        - ctx.constraints is non-empty (constraints file is required)
    """
    config_data = ctx.config
    claims_list = ctx.claims_list

    config_language = config_data["language"]
    config_validation_tools = config_data.get("validation_tools", [])
    ltm = ctx.constraints.get("language_tool_matrix", {})

    from vibe_tracing.infra.tools.executor import ToolExecutionEngine, ToolEvidenceCandidate
    from vibe_tracing.infra.tools.resolver import ToolResolver

    # Pre-flight dependency check
    required_binaries = set()
    lang_tools = ltm.get(config_language, {})
    for category in config_validation_tools:
        tool_cfg = lang_tools.get(category, {})
        tool_name = tool_cfg.get("tool")
        if tool_name:
            required_binaries.add(tool_name)

    missing = sorted(t for t in required_binaries if not ToolResolver.is_available(t))
    if missing:
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
        print("Skipping tool execution: no file extensions defined in language_tool_matrix.", file=sys.stderr)
        return []
    test_paths: List[str] = []
    source_paths: List[str] = []
    seen_paths: Set[str] = set()

    # Collect non-code file references for skipped evidence
    non_code_refs: Set[str] = set()
    for claim in claims_list:
        for ref in list(claim.test_refs or []) + list(claim.code_refs or []):
            path_only = ref.split("#")[0]
            if path_only and Path(path_only).suffix and Path(path_only).suffix not in code_extensions:
                non_code_refs.add(path_only)

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
        return []

    # Filter to only staged files (EVO-TASK-016)
    if staged_files is not None:
        test_paths = [p for p in test_paths if p in staged_files]
        source_paths = [p for p in source_paths if p in staged_files]

    total_paths = len(test_paths) + len(source_paths)
    if total_paths == 0:
        print("Skipping tool execution: no staged files match claim references.", file=sys.stderr)
        return []

    print(f"Executing validation tools for {total_paths} staged path(s)...")
    typed_paths = {"test": test_paths, "source": source_paths}
    tool_evidence_candidates = engine.execute_all(typed_paths)

    # Generate skipped evidence for non-code files
    for ref_path in non_code_refs:
        tool_evidence_candidates.append(
            ToolEvidenceCandidate(
                source_type="tool",
                source_path=ref_path,
                covers=[],
                status="skipped",
                command="",
                exit_code=0,
                stderr="",
                details={"skip_reason": "non-code file, tools not applicable"},
            )
        )

    executed_count = len(tool_evidence_candidates)
    blocked_count = sum(1 for c in tool_evidence_candidates if c.error_code is not None)
    skipped_count = sum(1 for c in tool_evidence_candidates if c.status == "skipped")
    if skipped_count > 0:
        print(f"  ({skipped_count} files skipped -- no tests collected or usage error)", file=sys.stderr)

    for c in tool_evidence_candidates:
        if c.error_code is not None:
            details = c.details or {}
            error_type = details.get("error_type", "unknown")
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
    print(f"Tool execution complete: {executed_count} evidence candidates ({blocked_count} blocked)")
    return tool_evidence_candidates
