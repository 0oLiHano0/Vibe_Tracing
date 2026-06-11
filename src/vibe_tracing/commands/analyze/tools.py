"""
Tool execution and staged-file checks.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Set

from vibe_tracing.context import UnifiedContext
from vibe_tracing.commands.common import _GateBlocked


def _execute_tools(
    ctx: UnifiedContext,
    project_root: Path,
    is_draft: bool,
) -> List:
    """Execute validation tools and return tool evidence candidates.

    Skips if project is in draft status or has no constraints.
    """
    constraints_record_content = ctx.constraints
    config_data = ctx.config
    claims_list = ctx.claims_list
    task_res = ctx.task_result

    config_language = config_data.get("language")
    config_validation_tools = config_data.get("validation_tools", [])

    if not constraints_record_content:
        return []

    if not config_language:
        print(
            "Error: Project not finalized. Run 'vibe-tracing finalize' first.",
            file=sys.stderr,
        )
        raise _GateBlocked(1)

    ltm = constraints_record_content.get("language_tool_matrix", {})
    if is_draft:
        print("Skipping tool execution: project is in draft status (no tasks or claims).", file=sys.stderr)
        return []
    if not (config_language and ltm):
        return []

    from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine, ToolEvidenceCandidate
    from vibe_tracing.tool_resolver import ToolResolver

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

    engine = ToolExecutionEngine(
        language_tool_matrix=ltm,
        language=config_language,
        validation_tools=config_validation_tools,
        project_root=project_root,
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

    if task_res:
        for task in task_res.tasks:
            for ref in task.evidence_refs if hasattr(task, 'evidence_refs') else []:
                path_only = ref.split("#")[0]
                if path_only and path_only not in seen_paths:
                    source_paths.append(path_only)
                    seen_paths.add(path_only)

    if not test_paths and not source_paths:
        return []

    # Filter to only staged files (EVO-TASK-016)
    try:
        staged_result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if staged_result.returncode == 0 and staged_result.stdout.strip():
            staged_files = set(
                f for f in staged_result.stdout.splitlines() if f.strip()
            )
            test_paths = [p for p in test_paths if p in staged_files]
            source_paths = [p for p in source_paths if p in staged_files]
    except Exception:
        pass  # If git is unavailable or fails, run on all paths (fallback)

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
    skipped_count = sum(1 for c in tool_evidence_candidates if hasattr(c, 'status') and c.status == "skipped")
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


def _check_staged_extensions(project_root: Path, constraints: Optional[dict], config_language: Optional[str] = None) -> None:
    """Warn about staged files whose extensions are not in the configured language_tool_matrix.

    This is a WARNING-only check: it does not block the analysis pipeline.
    """
    if not constraints:
        return

    ltm = constraints.get("language_tool_matrix", {})
    lang_config = ltm.get(config_language, {})
    configured_exts = set(lang_config.get("extensions", [".py"]))
    if not configured_exts:
        return

    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return
        staged_files = [f for f in result.stdout.splitlines() if f.strip()]
    except Exception:
        return

    if not staged_files:
        return

    unrecognized: Set[str] = set()
    for staged_file in staged_files:
        ext = Path(staged_file).suffix
        if ext and ext not in configured_exts:
            unrecognized.add(ext)

    for ext in sorted(unrecognized):
        print(
            f"WARNING: 发现未配置的代码文件类型 {ext}，"
            "请更新 architecture_constraints.json 的 language_tool_matrix 并通过 vt finalize 锁定。",
            file=sys.stderr,
        )


def _archive_claims(project_root: Path) -> None:
    """Archive current claims to commit-{hash}.json and clear current.json.

    Called after a successful pre-commit gate evaluation so that claims
    are preserved alongside the commit they belong to.
    """
    current_path = project_root / ".vibetracing" / "claims" / "current.json"
    archive_dir = project_root / ".vibetracing" / "claims" / "archive"

    # Nothing to archive if file doesn't exist
    if not current_path.exists():
        return

    try:
        with current_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    # Nothing to archive if list is empty
    if not data:
        return

    # Resolve archive filename: prefer short git commit hash, fallback to timestamp
    archive_name = None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            archive_name = f"commit-{result.stdout.strip()}"
    except (OSError, subprocess.TimeoutExpired):
        pass

    if archive_name is None:
        archive_name = f"commit-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    archive_path = archive_dir / f"{archive_name}.json"

    # Ensure archive directory exists
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Write archived claims
    with archive_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Clear current.json
    with current_path.open("w", encoding="utf-8") as f:
        json.dump([], f)
        f.write("\n")

    print(f"Claims archived to {archive_name}.json")
