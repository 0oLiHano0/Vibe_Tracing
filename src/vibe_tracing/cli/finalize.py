"""
Finalize command -- lock project configuration from architecture constraints.
"""

import hashlib
import json
import subprocess
import sys
import time
import uuid

from pathlib import Path

from vibe_tracing.infra.operational_logger import OperationalLogger


def _logged_subprocess_run(args: list, **kwargs):
    """Wrapper around subprocess.run that logs command, exit_code, and duration."""
    logger = OperationalLogger.get()
    t0 = time.perf_counter()
    try:
        result = subprocess.run(args, **kwargs)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        logger.info("subprocess", f"subprocess.run completed: {args[0] if args else '???'}",
                     command=args, exit_code=result.returncode, duration_ms=duration_ms)
        return result
    except subprocess.CalledProcessError as e:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        logger.error("subprocess_error", f"subprocess.run failed: {args[0] if args else '???'}",
                      command=args, exit_code=e.returncode, duration_ms=duration_ms)
        raise


def _print_post_finalize_guidance(project_root: Path) -> None:
    """Check for remaining uncommitted files and guide the agent."""
    logger = OperationalLogger.get()
    try:
        t0 = time.perf_counter()
        status_out = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=project_root, text=True
        )
        duration_ms = int((time.perf_counter() - t0) * 1000)
        logger.info("subprocess", "git status --porcelain completed",
                     command=["git", "status", "--porcelain"], duration_ms=duration_ms)
        dirty_files = []
        for line in status_out.splitlines():
            if not line.strip():
                continue
            dirty_files.append(line[3:])
        logger.debug("post_finalize_check", "Post-finalize dirty files check",
                     dirty_count=len(dirty_files))
        if dirty_files:
            print(
                "\n注意：设计基线已锁定，但工作目录中仍有未提交的变更。"
                "工作流规范：先定稿设计，再提交代码。请单独提交剩余变更。"
            )
    except Exception as exc:
        logger.warning("post_finalize_check_failed", "Post-finalize check failed", error=str(exc))


def _validate_constraints_change(project_root: Path, constraints_path: Path, config_data: dict) -> tuple:
    """Validate that architecture constraint changes are documented in change_log.md.

    Returns:
        (passed: bool, message: str)
    """
    from vibe_tracing.infra.git_utils import git_show, git_has_uncommitted_changes
    logger = OperationalLogger.get()

    finalize_commit = config_data.get("finalize_git_commit")
    finalize_constraints_path = config_data.get("finalize_constraints_path")

    # First finalization (no stored hash) — always pass
    if not finalize_commit or not finalize_constraints_path:
        logger.debug("constraints_change_check", "First finalization, skipping change validation")
        return True, "首次定稿"

    # Get baseline via git show
    t0 = time.perf_counter()
    base_content = git_show(finalize_commit, finalize_constraints_path, project_root)
    duration_ms = int((time.perf_counter() - t0) * 1000)
    logger.info("git_show", "Retrieved baseline constraints",
                finalize_commit=finalize_commit, duration_ms=duration_ms,
                found=base_content is not None)
    if base_content is None:
        return False, f"无法还原定稿版本 ({finalize_commit}:{finalize_constraints_path})"

    base_data = json.loads(base_content)
    curr_data = json.loads(constraints_path.read_text(encoding="utf-8"))

    # Import _find_differences from architecture_change_proposal
    from vibe_tracing.domain.architecture_change_proposal import ArchitectureChangeProposalEngine
    engine = ArchitectureChangeProposalEngine(project_root)
    diffs = engine._find_differences(base_data, curr_data)
    logger.debug("constraints_diff_result", "Constraints diff computed", diffs_count=len(diffs))

    # No structural diffs — format change only
    if not diffs:
        return True, "格式变化（无规则变更），直接更新检查点"

    # In V4, finalize creates the commit. We expect architecture_change_log.md to have uncommitted changes.
    change_log_rel = "docs/architecture_change_log.md"
    has_uncommitted = git_has_uncommitted_changes(change_log_rel, project_root)
    logger.debug("change_log_check", "Checked change_log uncommitted status",
                 has_uncommitted=has_uncommitted)
    if not has_uncommitted:
        changed = [f"  - {d['action'].upper()}: {d.get('rule_id') or d['path']}" for d in diffs]
        return False, (
            "检测到架构约束被修改，但 change_log.md 未同步更新。\n"
            "变更的规则：\n" + "\n".join(changed) + "\n"
            "请在 docs/architecture_change_log.md 中记录变更原因后重新运行 vt finalize。"
        )

    return True, "合规的架构变更"


def run_finalize(project_root: Path) -> int:
    """Finalize project configuration by reading language and tools from architecture constraints."""
    # 获取 main() 已初始化的日志实例；若直接调用（非 main 路径），则自动初始化
    # 若日志初始化失败，finalize 仍须继续运行（LOG-VT-011 约束）
    try:
        vt_logger = OperationalLogger.get_or_init(
            run_id=f"RUN-{uuid.uuid4()}", project_root=project_root,
        )
    except Exception:
        vt_logger = OperationalLogger.get()  # 返回空日志器，不阻断命令
    vt_logger.info("run_start", "vt finalize started")
    _run_start_t = time.perf_counter()

    try:
        config_path = project_root / ".vibetracing" / "config.json"
        constraints_path = project_root / "docs" / "architecture_constraints.json"

        # 1. Check config.json exists
        if not config_path.exists():
            vt_logger.error("config_missing", "config.json not found")
            print("Error: config.json not found. Run 'vibe-tracing init' first.", file=sys.stderr)
            return 1

        # 2. Check architecture_constraints.json exists
        if not constraints_path.exists():
            vt_logger.error("constraints_missing", "architecture_constraints.json not found")
            print("Error: architecture_constraints.json not found. Agent must generate it before finalization.", file=sys.stderr)
            return 1

        # 3. Load both files
        _t = time.perf_counter()
        with config_path.open("r", encoding="utf-8") as f:
            config_data = json.load(f)
        with constraints_path.open("r", encoding="utf-8") as f:
            constraints_data = json.load(f)
        vt_logger.info("phase_end", "Loaded config and constraints",
                       phase="load_files", duration_ms=int((time.perf_counter() - _t) * 1000))

        # 4. Extract language from architecture constraints
        project_data = constraints_data.get("project", {})
        language = project_data.get("language")
        if not language:
            vt_logger.error("no_language", "project.language not set in architecture_constraints.json")
            print("Error: project.language not set in architecture_constraints.json.", file=sys.stderr)
            return 1

        # 5. Check language_tool_matrix
        ltm = constraints_data.get("language_tool_matrix", {})
        if language not in ltm:
            vt_logger.error("language_not_in_matrix", f"Language '{language}' not in language_tool_matrix",
                            language=language)
            print(f"Error: language \"{language}\" not found in language_tool_matrix.", file=sys.stderr)
            return 1

        tool_categories = [k for k, v in ltm[language].items() if isinstance(v, dict)]
        vt_logger.debug("language_extracted", "Extracted language and tool categories",
                        language=language, tool_categories=tool_categories)

        # Set project prefix for ID parsing (used by PrdParser)
        project_prefix = config_data.get("project_prefix", "VT")
        from vibe_tracing.infra import validation as ids
        ids.set_project_prefix(project_prefix)

        # 5.5. PRD <-> Architecture mapping validation (left-shift)
        _t = time.perf_counter()
        from vibe_tracing.domain.prd_arch_validator import validate_prd_architecture_mapping_from_path
        mapping_pvr = validate_prd_architecture_mapping_from_path(project_root, constraints_data)
        vt_logger.info("phase_end", "PRD-Architecture mapping validation completed",
                       phase="prd_arch_mapping",
                       duration_ms=int((time.perf_counter() - _t) * 1000),
                       exit_code=mapping_pvr.exit_code)
        if mapping_pvr.message:
            if mapping_pvr.exit_code != 0:
                print(mapping_pvr.message, file=sys.stderr)
            else:
                print(mapping_pvr.message)
        if mapping_pvr.exit_code != 0:
            return mapping_pvr.exit_code

        # Compute SHA256 hash of constraints file
        _t = time.perf_counter()
        computed_hash = hashlib.sha256(constraints_path.read_bytes()).hexdigest()

        # Compute SHA256 hash of PRD file
        prd_rel = config_data.get("paths", {}).get("prd", "docs/prd.md")
        prd_abs = project_root / prd_rel
        prd_hash = hashlib.sha256(prd_abs.read_bytes()).hexdigest() if prd_abs.exists() else ""
        vt_logger.debug("hashes_computed", "Computed SHA256 hashes",
                        constraints_hash=computed_hash[:16], prd_hash=prd_hash[:16] if prd_hash else "",
                        prd_exists=prd_abs.exists(),
                        duration_ms=int((time.perf_counter() - _t) * 1000))

        # 6. Check if already finalized (language + tools + hash)
        existing_language = config_data.get("language")
        if existing_language:
            if existing_language != language:
                vt_logger.error("language_conflict",
                                f"Config language '{existing_language}' conflicts with constraints language '{language}'",
                                config_language=existing_language, constraints_language=language)
                print(f"Error: config.json language \"{existing_language}\" conflicts with architecture_constraints language \"{language}\". Manual intervention required.", file=sys.stderr)
                return 1
            existing_tools = sorted(config_data.get("validation_tools", []))
            current_tools = sorted(tool_categories)
            stored_hash = config_data.get("architecture_constraints_hash")
            stored_prd_hash = config_data.get("prd_hash", "")

            hash_changed = stored_hash != computed_hash
            tools_changed = existing_tools != current_tools
            prd_hash_changed = stored_prd_hash != prd_hash

            vt_logger.debug("re_finalize_check", "Re-finalize change detection",
                            hash_changed=hash_changed, tools_changed=tools_changed,
                            prd_hash_changed=prd_hash_changed)

            if not hash_changed and not tools_changed and not prd_hash_changed:
                vt_logger.info("already_finalized", "No changes detected, already finalized",
                               language=language, tools=current_tools,
                               total_duration_ms=int((time.perf_counter() - _run_start_t) * 1000))
                print(f"Already finalized: language={language}, tools={current_tools}")
                return 0

            # Hash changed -> validate change_log (always required, regardless of tool changes)
            message = ""
            if hash_changed:
                passed, message = _validate_constraints_change(project_root, constraints_path, config_data)
                if not passed:
                    vt_logger.warning("constraints_change_rejected", "Constraints change validation failed",
                                      detail=message)
                    print(f"Error: {message}", file=sys.stderr)
                    return 1
                config_data["architecture_constraints_hash"] = computed_hash
                config_data["finalize_constraints_path"] = str(constraints_path.relative_to(project_root))

            # PRD hash changed -> update config
            if prd_hash_changed:
                config_data["prd_hash"] = prd_hash

            # Tools changed -> update config
            if tools_changed:
                config_data["validation_tools"] = tool_categories

            # Write config and commit if anything was updated
            with config_path.open("w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            vt_logger.debug("config_written", "Updated config.json",
                            hash_changed=hash_changed, tools_changed=tools_changed,
                            prd_hash_changed=prd_hash_changed)

            # Git operations
            _t = time.perf_counter()
            try:
                files_to_add = [
                    "docs/prd.md",
                    "docs/architecture_constraints.json",
                    ".vibetracing/config.json",
                ]
                change_log = project_root / "docs" / "architecture_change_log.md"
                if change_log.exists():
                    files_to_add.append("docs/architecture_change_log.md")
                files_to_add = [f for f in files_to_add if (project_root / f).exists()]
                if files_to_add:
                    _logged_subprocess_run(["git", "add"] + files_to_add, cwd=project_root, check=True)
                _logged_subprocess_run(
                    ["git", "commit", "-m", "chore: Vibe Tracing architecture baseline finalized", "--no-verify"],
                    cwd=project_root,
                    check=True
                )
                git_commit = _logged_subprocess_run(
                    ["git", "rev-parse", "HEAD"], cwd=project_root, capture_output=True, text=True, check=True
                )
                config_data["finalize_git_commit"] = git_commit.stdout.strip()
                with config_path.open("w", encoding="utf-8") as f:
                    json.dump(config_data, f, indent=2, ensure_ascii=False)
                _logged_subprocess_run(["git", "add", ".vibetracing/config.json"], cwd=project_root, check=True)
                _logged_subprocess_run(["git", "commit", "--amend", "--no-edit", "--no-verify"], cwd=project_root, check=True)
            except Exception as e:
                vt_logger.exception("git_commit_failed", "Failed to commit architecture baseline", exc=e)
                print(f"Error: Failed to automatically commit architecture baseline: {e}", file=sys.stderr)
                return 1

            vt_logger.info("phase_end", "Git operations completed (re-finalize)",
                           phase="git_operations",
                           duration_ms=int((time.perf_counter() - _t) * 1000),
                           git_commit=config_data.get("finalize_git_commit", ""))

            parts = []
            if hash_changed:
                parts.append(f"Constraints checkpoint updated (hash={computed_hash[:12]}...). {message}")
            if tools_changed:
                parts.append(f"Updated validation_tools: {existing_tools} → {current_tools}")
            print(" ".join(parts) if parts else "No changes detected.")
            _print_post_finalize_guidance(project_root)
            vt_logger.info("run_end", "vt finalize completed (re-finalize)",
                           total_duration_ms=int((time.perf_counter() - _run_start_t) * 1000), exit_code=0)
            return 0

        # 7. First finalization or language not yet set — validate and write
        _t = time.perf_counter()
        passed, message = _validate_constraints_change(project_root, constraints_path, config_data)
        vt_logger.info("phase_end", "Constraints change validation (first finalize)",
                       phase="constraints_validation",
                       duration_ms=int((time.perf_counter() - _t) * 1000), passed=passed)
        if not passed:
            vt_logger.warning("constraints_change_rejected", "Constraints change validation failed",
                              detail=message)
            print(f"Error: {message}", file=sys.stderr)
            return 1

        config_data["language"] = language
        config_data["validation_tools"] = tool_categories
        config_data["architecture_constraints_hash"] = computed_hash
        config_data["finalize_constraints_path"] = str(constraints_path.relative_to(project_root))
        config_data["prd_hash"] = prd_hash

        with config_path.open("w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        vt_logger.debug("config_written", "Wrote initial config.json",
                        language=language, tool_categories=tool_categories,
                        constraints_hash=computed_hash[:16])

        # V4 Finalize-as-a-Committer: Automatically commit the initial architecture baseline
        _t = time.perf_counter()
        try:
            files_to_add = [
                "docs/prd.md",
                "docs/architecture_constraints.json",
                ".vibetracing/config.json",
            ]
            change_log = project_root / "docs" / "architecture_change_log.md"
            if change_log.exists():
                files_to_add.append("docs/architecture_change_log.md")
            # Only add files that actually exist
            files_to_add = [f for f in files_to_add if (project_root / f).exists()]
            if files_to_add:
                _logged_subprocess_run(["git", "add"] + files_to_add, cwd=project_root, check=True)
            _logged_subprocess_run(
                ["git", "commit", "-m", "chore: Vibe Tracing initial architecture baseline finalized", "--no-verify"],
                cwd=project_root,
                check=True
            )
            git_commit = _logged_subprocess_run(
                ["git", "rev-parse", "HEAD"], cwd=project_root, capture_output=True, text=True, check=True
            )
            config_data["finalize_git_commit"] = git_commit.stdout.strip()
            with config_path.open("w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            _logged_subprocess_run(["git", "add", ".vibetracing/config.json"], cwd=project_root, check=True)
            _logged_subprocess_run(["git", "commit", "--amend", "--no-edit", "--no-verify"], cwd=project_root, check=True)
        except Exception as e:
            vt_logger.exception("git_commit_failed", "Failed to commit initial architecture baseline", exc=e)
            print(f"Error: Failed to automatically commit initial architecture baseline: {e}", file=sys.stderr)
            return 1

        vt_logger.info("phase_end", "Git operations completed (first finalize)",
                       phase="git_operations",
                       duration_ms=int((time.perf_counter() - _t) * 1000),
                       git_commit=config_data.get("finalize_git_commit", ""))

        print(f"Vibe Tracing finalized for project. {message}")
        _print_post_finalize_guidance(project_root)
        vt_logger.info("run_end", "vt finalize completed (first finalize)",
                       total_duration_ms=int((time.perf_counter() - _run_start_t) * 1000), exit_code=0)
        return 0

    except Exception as exc:
        vt_logger.exception("unexpected_error", f"Unexpected error during finalization: {exc}", exc=exc)
        print(f"Error during finalization: {exc}", file=sys.stderr)
        return 1
