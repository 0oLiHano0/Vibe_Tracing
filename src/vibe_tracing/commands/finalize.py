"""
Finalize command -- lock project configuration from architecture constraints.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path


def _print_post_finalize_guidance(project_root: Path) -> None:
    """Check for remaining uncommitted files and guide the agent."""
    try:
        status_out = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=project_root, text=True
        )
        dirty_files = []
        for line in status_out.splitlines():
            if not line.strip():
                continue
            dirty_files.append(line[3:])
        if dirty_files:
            print(
                "\n注意：设计基线已锁定，但工作目录中仍有未提交的变更。"
                "工作流规范：先定稿设计，再提交代码。请单独提交剩余变更。"
            )
    except Exception:
        pass


def _validate_constraints_change(project_root: Path, constraints_path: Path, config_data: dict) -> tuple:
    """Validate that architecture constraint changes are documented in change_log.md.

    Returns:
        (passed: bool, message: str)
    """
    from vibe_tracing.git_utils import git_show, git_has_uncommitted_changes

    finalize_commit = config_data.get("finalize_git_commit")
    finalize_constraints_path = config_data.get("finalize_constraints_path")

    # First finalization (no stored hash) — always pass
    if not finalize_commit or not finalize_constraints_path:
        return True, "首次定稿"

    # Get baseline via git show
    base_content = git_show(finalize_commit, finalize_constraints_path, project_root)
    if base_content is None:
        return False, f"无法还原定稿版本 ({finalize_commit}:{finalize_constraints_path})"

    base_data = json.loads(base_content)
    curr_data = json.loads(constraints_path.read_text(encoding="utf-8"))

    # Import _find_differences from architecture_change_proposal
    from vibe_tracing.architecture_change_proposal import ArchitectureChangeProposalEngine
    engine = ArchitectureChangeProposalEngine(project_root)
    diffs = engine._find_differences(base_data, curr_data)

    # No structural diffs — format change only
    if not diffs:
        return True, "格式变化（无规则变更），直接更新检查点"

    # In V4, finalize creates the commit. We expect architecture_change_log.md to have uncommitted changes.
    change_log_rel = "docs/architecture_change_log.md"
    if not git_has_uncommitted_changes(change_log_rel, project_root):
        changed = [f"  - {d['action'].upper()}: {d.get('rule_id') or d['path']}" for d in diffs]
        return False, (
            "检测到架构约束被修改，但 change_log.md 未同步更新。\n"
            "变更的规则：\n" + "\n".join(changed) + "\n"
            "请在 docs/architecture_change_log.md 中记录变更原因后重新运行 vt finalize。"
        )

    return True, "合规的架构变更"


def run_finalize(project_root: Path) -> int:
    """Finalize project configuration by reading language and tools from architecture constraints."""
    try:
        config_path = project_root / ".vibetracing" / "config.json"
        constraints_path = project_root / "docs" / "architecture_constraints.json"

        # 1. Check config.json exists
        if not config_path.exists():
            print("Error: config.json not found. Run 'vibe-tracing init' first.", file=sys.stderr)
            return 1

        # 2. Check architecture_constraints.json exists
        if not constraints_path.exists():
            print("Error: architecture_constraints.json not found. Agent must generate it before finalization.", file=sys.stderr)
            return 1

        # 3. Load both files
        with config_path.open("r", encoding="utf-8") as f:
            config_data = json.load(f)
        with constraints_path.open("r", encoding="utf-8") as f:
            constraints_data = json.load(f)

        # 4. Extract language from architecture constraints
        project_data = constraints_data.get("project", {})
        language = project_data.get("language")
        if not language:
            print("Error: project.language not set in architecture_constraints.json.", file=sys.stderr)
            return 1

        # 5. Check language_tool_matrix
        ltm = constraints_data.get("language_tool_matrix", {})
        if language not in ltm:
            print(f"Error: language \"{language}\" not found in language_tool_matrix.", file=sys.stderr)
            return 1

        tool_categories = [k for k, v in ltm[language].items() if isinstance(v, dict)]

        # Set project prefix for ID parsing (used by PrdParser)
        project_prefix = config_data.get("project_prefix", "VT")
        from vibe_tracing.core import ids
        ids.set_project_prefix(project_prefix)

        # 5.5. PRD <-> Architecture mapping validation (left-shift)
        from vibe_tracing.prd_arch_validator import validate_prd_architecture_mapping_from_path
        mapping_pvr = validate_prd_architecture_mapping_from_path(project_root, constraints_data)
        if mapping_pvr.message:
            if mapping_pvr.exit_code != 0:
                print(mapping_pvr.message, file=sys.stderr)
            else:
                print(mapping_pvr.message)
        if mapping_pvr.exit_code != 0:
            return mapping_pvr.exit_code

        # Compute SHA256 hash of constraints file
        computed_hash = hashlib.sha256(constraints_path.read_bytes()).hexdigest()

        # Compute SHA256 hash of PRD file
        prd_rel = config_data.get("paths", {}).get("prd", "docs/prd.md")
        prd_abs = project_root / prd_rel
        prd_hash = hashlib.sha256(prd_abs.read_bytes()).hexdigest() if prd_abs.exists() else ""

        # 6. Check if already finalized (language + tools + hash)
        existing_language = config_data.get("language")
        if existing_language:
            if existing_language != language:
                print(f"Error: config.json language \"{existing_language}\" conflicts with architecture_constraints language \"{language}\". Manual intervention required.", file=sys.stderr)
                return 1
            existing_tools = sorted(config_data.get("validation_tools", []))
            current_tools = sorted(tool_categories)
            stored_hash = config_data.get("architecture_constraints_hash")
            stored_prd_hash = config_data.get("prd_hash", "")

            hash_changed = stored_hash != computed_hash
            tools_changed = existing_tools != current_tools
            prd_hash_changed = stored_prd_hash != prd_hash

            if not hash_changed and not tools_changed and not prd_hash_changed:
                print(f"Already finalized: language={language}, tools={current_tools}")
                return 0

            # Hash changed -> validate change_log (always required, regardless of tool changes)
            message = ""
            if hash_changed:
                passed, message = _validate_constraints_change(project_root, constraints_path, config_data)
                if not passed:
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
                    subprocess.run(["git", "add"] + files_to_add, cwd=project_root, check=True)
                subprocess.run(
                    ["git", "commit", "-m", "chore: Vibe Tracing architecture baseline finalized", "--no-verify"],
                    cwd=project_root,
                    check=True
                )
                git_commit = subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=project_root, capture_output=True, text=True, check=True
                )
                config_data["finalize_git_commit"] = git_commit.stdout.strip()
                with config_path.open("w", encoding="utf-8") as f:
                    json.dump(config_data, f, indent=2, ensure_ascii=False)
                subprocess.run(["git", "add", ".vibetracing/config.json"], cwd=project_root, check=True)
                subprocess.run(["git", "commit", "--amend", "--no-edit", "--no-verify"], cwd=project_root, check=True)
            except Exception as e:
                print(f"Error: Failed to automatically commit architecture baseline: {e}", file=sys.stderr)
                return 1

            parts = []
            if hash_changed:
                parts.append(f"Constraints checkpoint updated (hash={computed_hash[:12]}...). {message}")
            if tools_changed:
                parts.append(f"Updated validation_tools: {existing_tools} → {current_tools}")
            print(" ".join(parts) if parts else "No changes detected.")
            _print_post_finalize_guidance(project_root)
            return 0

        # 7. First finalization or language not yet set — validate and write
        passed, message = _validate_constraints_change(project_root, constraints_path, config_data)
        if not passed:
            print(f"Error: {message}", file=sys.stderr)
            return 1

        config_data["language"] = language
        config_data["validation_tools"] = tool_categories
        config_data["architecture_constraints_hash"] = computed_hash
        config_data["finalize_constraints_path"] = str(constraints_path.relative_to(project_root))
        config_data["prd_hash"] = prd_hash

        with config_path.open("w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)

        # V4 Finalize-as-a-Committer: Automatically commit the initial architecture baseline
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
                subprocess.run(["git", "add"] + files_to_add, cwd=project_root, check=True)
            subprocess.run(
                ["git", "commit", "-m", "chore: Vibe Tracing initial architecture baseline finalized", "--no-verify"],
                cwd=project_root,
                check=True
            )
            git_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=project_root, capture_output=True, text=True, check=True
            )
            config_data["finalize_git_commit"] = git_commit.stdout.strip()
            with config_path.open("w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            subprocess.run(["git", "add", ".vibetracing/config.json"], cwd=project_root, check=True)
            subprocess.run(["git", "commit", "--amend", "--no-edit", "--no-verify"], cwd=project_root, check=True)
        except Exception as e:
            print(f"Error: Failed to automatically commit initial architecture baseline: {e}", file=sys.stderr)
            return 1

        print(f"Vibe Tracing finalized for project. {message}")
        _print_post_finalize_guidance(project_root)
        return 0

    except Exception as exc:
        print(f"Error during finalization: {exc}", file=sys.stderr)
        return 1
