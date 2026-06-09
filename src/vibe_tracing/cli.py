"""
CLI Entrypoint for Vibe Tracing.

Provides the `analyze` command to load raw inputs, parse requirements,
validate schemas, run analyzers, generate risks, evaluate quality gates,
and output the evidence index, traceability report, and run metadata.
"""

import argparse
import fnmatch
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
import importlib.resources as pkg_resources

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from vibe_tracing import __version__
from vibe_tracing.raw_input_loader import RawInputLoader
from vibe_tracing.schema_validator import SchemaValidator
from vibe_tracing.prd_parser import PrdParser
from vibe_tracing.task_loader import TaskLoader
from vibe_tracing.claim_loader import ClaimLoader
from vibe_tracing.traceability.claim_credibility import assess_claim_credibility
from vibe_tracing.evidence_index_builder import EvidenceIndexBuilder
from vibe_tracing.traceability_report_builder import TraceabilityReportBuilder
from vibe_tracing.merge_gate_engine import MergeGateEngine
from vibe_tracing.architecture_compliance_checker import ArchitectureComplianceChecker
from vibe_tracing.traceability.requirement_task_analyzer import RequirementTaskAnalyzer
from vibe_tracing.traceability.ac_test_analyzer import AcTestAnalyzer
from vibe_tracing.traceability.claim_evidence_analyzer import ClaimEvidenceAnalyzer
from vibe_tracing.risk_advisor import RiskAdvisor
from vibe_tracing.dashboard_renderer import DashboardRenderer
from vibe_tracing.context import UnifiedContext
from vibe_tracing.tool_resolver import ToolResolver


def run_init(project_root: Path, name: Optional[str] = None, prefix: Optional[str] = None) -> int:
    """Initialize a Vibe Tracing project by creating directories and template files."""
    try:
        print(f"Initializing Vibe Tracing project at: {project_root}")

        if not name or not prefix:
            print("Error: --name 和 --prefix 是初始化项目必需的参数。\n\n用法示例:\n  vibe-tracing init --name \"Capacity Limit\" --prefix \"CapL\"", file=sys.stderr)
            return 1

        resolved_name = name
        resolved_prefix = prefix

        print(f"项目名称: {resolved_name}")
        print(f"项目前缀: {resolved_prefix}")

        # Directories to create (output/ is dynamically created during analyze)
        dirs = [
            project_root / ".vibetracing",
            project_root / "docs",
        ]
        for d in dirs:
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                print(
                    f"Created directory: {d.relative_to(project_root) if project_root in d.parents else d}"
                )

        from vibe_tracing import templates
        import datetime

        # Get current date
        today_str = datetime.date.today().strftime("%Y-%m-%d")

        # Load templates from package resources as text
        config_text = pkg_resources.read_text(templates, "config.template.json")
        claims_text = pkg_resources.read_text(templates, "agent_claims.template.json")
        task_list_text = pkg_resources.read_text(templates, "task_list.template.json")
        arch_text = pkg_resources.read_text(templates, "architecture_constraints.template.json")
        prd_text = pkg_resources.read_text(templates, "prd.template.md")
        prd_analysis_text = pkg_resources.read_text(templates, "prd_analysis.template.md")

        config_path = project_root / ".vibetracing" / "config.json"

        # 1. Determine configuration values (Read existing config or use resolved parameters)
        if config_path.exists():
            print("Skipped existing file: .vibetracing/config.json")
            try:
                with config_path.open("r", encoding="utf-8") as f:
                    config_data = json.load(f)
                config_name = config_data.get("project_name", resolved_name)
                config_prefix = config_data.get("project_prefix", resolved_prefix)
                config_project_id = config_data.get("project_id", f"PROJECT-{config_prefix}")
            except Exception as exc:
                print(f"Error loading existing config.json: {exc}", file=sys.stderr)
                return 1
        else:
            config_name = resolved_name
            config_prefix = resolved_prefix
            config_project_id = f"PROJECT-{resolved_prefix}"

        # 2. Unified placeholder replacement function
        def render_template(content: str) -> str:
            # 1. Translate legacy hardcoded -VT- references
            content = content.replace("PROJECT-VT", config_project_id)
            content = content.replace("-VT-", f"-{config_prefix}-")
            content = content.replace("-VT\\", f"-{config_prefix}\\")
            # 2. Replace explicit placeholders
            content = content.replace("{{PROJECT_NAME}}", config_name)
            content = content.replace("{{PROJECT_PREFIX}}", config_prefix)
            content = content.replace("{{TODAY}}", today_str)
            return content

        # 3. Write ALL template files except config.json first
        other_files = {
            ".vibetracing/agent_claims.json": render_template(claims_text),
            "docs/task_list.json": render_template(task_list_text),
            "docs/architecture_constraints.json": render_template(arch_text),
            "docs/prd.md": render_template(prd_text),
            ".vibetracing/prompts/prd_analysis.md": render_template(prd_analysis_text),
        }

        for rel_path, content in other_files.items():
            file_path = project_root / rel_path
            if file_path.exists():
                print(f"Skipped existing file: {rel_path}")
            else:
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with file_path.open("w", encoding="utf-8") as f:
                    f.write(content)
                print(f"Created file: {rel_path}")

        # 4. Write config.json LAST (if not exist) — prevents stale config on partial failure
        if not config_path.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_content = render_template(config_text)
            with config_path.open("w", encoding="utf-8") as f:
                f.write(config_content)
            print("Created file: .vibetracing/config.json")

        # 5. Install Git pre-commit hook (V4)
        git_hooks_dir = project_root / ".git" / "hooks"
        if git_hooks_dir.exists():
            pre_commit_path = git_hooks_dir / "pre-commit"
            if not pre_commit_path.exists():
                python_path = sys.executable
                hook_script = f'#!/bin/sh\nset -e\n# Vibe Tracing Git Guard\n"{python_path}" -m vibe_tracing analyze --pre-commit\n'
                pre_commit_path.write_text(hook_script)
                pre_commit_path.chmod(0o755)
                print("Installed Git pre-commit hook (vibe_tracing analyze --pre-commit)")
            else:
                print("Skipped Git pre-commit hook: file already exists.")

        print("Vibe Tracing initialization completed successfully.")
        return 0
    except Exception as exc:
        print(f"Error during initialization: {exc}", file=sys.stderr)
        return 1





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


class _GateBlocked(Exception):
    """Raised when an integrity gate blocks the analysis pipeline."""
    def __init__(self, exit_code: int = 1):
        self.exit_code = exit_code


def _load_context(
    project_root: Path,
    schemas_dir: Path,
    validator: SchemaValidator,
) -> Tuple[UnifiedContext, RawInputLoader, SchemaValidator]:
    """Load all input files, validate schemas, and build UnifiedContext.

    Raises _GateBlocked with exit_code=1 on any validation failure.
    """
    raw_loader = RawInputLoader(project_root)
    manifest = raw_loader.load()

    config_prefix = raw_loader.config_data.get("project_prefix", "VT")
    from vibe_tracing.core import ids
    ids.set_project_prefix(config_prefix)

    # Check for missing required files
    if manifest.has_required_errors:
        for record in manifest.inputs_used:
            if record.is_required and record.status != "ok":
                print(
                    f"Error loading required file {record.file_key} ({record.file_path}): {record.error_message}",
                    file=sys.stderr,
                )
        raise _GateBlocked(1)

    # Check for malformed files
    for record in manifest.inputs_used:
        if record.status not in ("ok", "missing"):
            print(
                f"Error loading file {record.file_key} ({record.file_path}): {record.error_message}",
                file=sys.stderr,
            )
            raise _GateBlocked(1)

    records_dict = {r.file_key: r for r in manifest.inputs_used}
    prd_record = records_dict.get("prd")
    task_list_record = records_dict.get("task_list")
    constraints_record = records_dict.get("architecture_constraints")
    claims_record = records_dict.get("agent_claims")

    # Schema validation
    if task_list_record and task_list_record.status == "ok" and task_list_record.content is not None:
        val_task = validator.validate_dict(
            task_list_record.content, "task_list",
            source_label=task_list_record.file_path,
        )
        if not val_task.is_valid:
            print(
                f"Schema validation failed for task list: {val_task.message} at {val_task.field_path}",
                file=sys.stderr,
            )
            if val_task.hint:
                print(val_task.hint, file=sys.stderr)
            raise _GateBlocked(1)

    if constraints_record and constraints_record.status == "ok" and constraints_record.content is not None:
        val_constraints = validator.validate_dict(
            constraints_record.content, "architecture_constraints",
            source_label=constraints_record.file_path,
        )
        if not val_constraints.is_valid:
            print(
                f"Schema validation failed for architecture constraints: {val_constraints.message} at {val_constraints.field_path}",
                file=sys.stderr,
            )
            if val_constraints.hint:
                print(val_constraints.hint, file=sys.stderr)
            raise _GateBlocked(1)

    if claims_record and claims_record.status == "ok" and claims_record.content is not None:
        val_claims = validator.validate_dict(
            claims_record.content, "agent_claims",
            source_label=claims_record.file_path,
        )
        if not val_claims.is_valid:
            print(
                f"Schema validation failed for agent claims: {val_claims.message} at {val_claims.field_path}",
                file=sys.stderr,
            )
            if val_claims.hint:
                print(val_claims.hint, file=sys.stderr)
            raise _GateBlocked(1)

    if not prd_record or prd_record.status != "ok":
        print("Error: PRD file missing or failed to load.", file=sys.stderr)
        raise _GateBlocked(1)

    # Parse PRD — use already-loaded content to avoid re-reading from disk
    prd_parser = PrdParser()
    prd_res = prd_parser.parse_text(prd_record.content)
    if not prd_res.is_valid:
        print(f"PRD parsing error: {'; '.join(prd_res.errors)}", file=sys.stderr)
        raise _GateBlocked(1)

    is_draft = (prd_res.status == "draft")

    # Verify required files exist if not draft
    if not is_draft:
        if not task_list_record or task_list_record.status != "ok":
            print(
                f"Error loading required file task_list ({raw_loader.get_path('task_list')}): File not found",
                file=sys.stderr,
            )
            raise _GateBlocked(1)
        if not constraints_record or constraints_record.status != "ok":
            print(
                f"Error loading required file architecture_constraints ({raw_loader.get_path('architecture_constraints')}): File not found",
                file=sys.stderr,
            )
            raise _GateBlocked(1)

    # Load tasks
    task_res = None
    if task_list_record and task_list_record.status == "ok":
        task_list_path = Path(task_list_record.file_path)
        task_loader = TaskLoader(schemas_dir)
        arch_data = constraints_record.content if constraints_record and constraints_record.status == "ok" else None
        task_res = task_loader.load_and_validate(
            task_list_path, prd_res, arch_data=arch_data, content=task_list_record.content
        )
        if not task_res.is_valid:
            print(
                f"Task list validation error: {'; '.join(task_res.errors)}",
                file=sys.stderr,
            )
            raise _GateBlocked(1)

    # Load claims
    claims_list = []
    if claims_record and claims_record.status == "ok" and task_res:
        claims_path = Path(claims_record.file_path)
        claim_loader = ClaimLoader(schemas_dir)
        claim_res_loader = claim_loader.load_and_validate(
            claims_path, task_res, content=claims_record.content
        )
        if not claim_res_loader.is_valid:
            print(
                f"Agent claims validation error: {'; '.join(claim_res_loader.errors)}",
                file=sys.stderr,
            )
            raise _GateBlocked(1)
        claims_list = claim_res_loader.claims

    ctx = UnifiedContext(
        config=raw_loader.config_data,
        prd=prd_res,
        constraints=constraints_record.content if constraints_record and constraints_record.status == "ok" else None,
        task_result=task_res,
        claims_list=claims_list,
        manifest=manifest,
        config_prefix=config_prefix,
    )
    return ctx, raw_loader, validator


def _gate1_constraints_hash(ctx: UnifiedContext, project_root: Path) -> Optional[int]:
    """Gate 1: Anti-Tampering (Architecture Baseline Check).

    Verifies that the architecture constraints file has not been modified
    since the baseline was finalized.  Compares the SHA-256 hash of the
    current file against the stored hash in the project config.

    Returns:
        None if the gate passes (hash matches or no baseline stored).
        1 (exit code) if the hash has been tampered with.
    """
    if not ctx.manifest:
        return None
    records_dict = {r.file_key: r for r in ctx.manifest.inputs_used}
    constraints_record = records_dict.get("architecture_constraints")
    if not (constraints_record and constraints_record.status == "ok"):
        return None

    # Use hash computed during loading instead of re-reading from disk
    computed_hash = constraints_record.sha256_hash
    if not computed_hash:
        return None
    stored_hash = ctx.config.get("architecture_constraints_hash")
    if stored_hash and stored_hash != computed_hash:
        print(
            "FATAL: 架构基线已被篡改！\n"
            f"预期 Hash: {stored_hash[:12]}...\n"
            f"实际 Hash: {computed_hash[:12]}...\n"
            "请恢复文件，或通过 `vt finalize` 提交合法的架构变更。",
            file=sys.stderr,
        )
        return 1

    return None


def _gate1b_prd_drift(ctx: UnifiedContext) -> None:
    """Gate 1b: PRD drift detection (WARNING only, never blocks).

    Compares the current PRD file hash against the baseline stored in config.
    If they differ, prints a warning to stderr but does not block the pipeline.
    """
    if not ctx.manifest:
        return

    # Resolve PRD record from manifest
    prd_record = None
    for r in ctx.manifest.inputs_used:
        if r.file_key == "prd":
            prd_record = r
            break

    if prd_record is None or prd_record.status != "ok":
        return

    # Use hash computed during loading instead of re-reading from disk
    computed_p_hash = prd_record.sha256_hash
    if not computed_p_hash:
        return
    stored_p_hash = ctx.config.get("prd_hash")
    if stored_p_hash and stored_p_hash != computed_p_hash:
        print(
            "WARNING: PRD 已从基线漂移！\n"
            f"预期 Hash: {stored_p_hash[:12]}...\n"
            f"实际 Hash: {computed_p_hash[:12]}...\n"
            "将重新验证 PRD ↔ Architecture 映射关系。",
            file=sys.stderr
        )


def _gate1c_mapping(ctx: UnifiedContext, config_prefix: str) -> Optional[int]:
    """Gate 1c: PRD <-> Architecture mapping validation.

    Returns 1 if dead links or MUST-uncovered requirements are found (blocks).
    Returns None if validation passes (including SHOULD-level warnings).
    """
    constraints_record_content = ctx.constraints
    prd_res = ctx.prd

    if not constraints_record_content or not prd_res or not prd_res.is_valid:
        return None

    from vibe_tracing.prd_arch_validator import validate_prd_architecture_mapping
    mapping_result = validate_prd_architecture_mapping(
        prd_res.requirements,
        constraints_record_content,
        config_prefix,
    )
    if mapping_result.has_dead_links:
        for link in mapping_result.dead_links:
            print(
                f"BLOCKED: 架构约束引用的 {link} 不存在于 PRD。\n"
                "请更新 architecture_constraints.json 或 PRD 以修复死链。",
                file=sys.stderr
            )
        return 1
    if mapping_result.has_must_uncovered:
        for req_id in mapping_result.must_uncovered:
            print(
                f"BLOCKED: MUST 级需求 {req_id} 无架构支撑。\n"
                "请在 architecture_constraints.json 中为该需求规划架构模块。",
                file=sys.stderr
            )
        return 1
    for req_id in mapping_result.should_uncovered:
        print(
            f"WARNING: SHOULD/COULD 级需求 {req_id} 缺失架构映射。",
            file=sys.stderr
        )
    return None


def _gate2_code_claim_alignment(
    ctx: UnifiedContext,
    project_root: Path,
    is_pre_commit: bool,
) -> Optional[int]:
    """Gate 2: Code-Claim Alignment (pre-commit only).

    Runs ghost code detection, task coverage check, and AC freshness check
    via GhostCodeReconciler.  Only executes when *is_pre_commit* is True.

    Returns:
        None if the gate passes or is skipped (not pre-commit).
        1 (exit code) if the gate fails.
    """
    if not is_pre_commit:
        return None

    from vibe_tracing.ghost_code_reconciler import GhostCodeReconciler
    reconciler = GhostCodeReconciler(project_root)
    success, error_msg = reconciler.reconcile()
    if error_msg:
        print(error_msg, file=sys.stderr)
    if not success:
        return 1

    return None


def _run_integrity_gates(
    ctx: UnifiedContext,
    project_root: Path,
    is_pre_commit: bool,
    config_prefix: str,
) -> Optional[int]:
    """Run integrity gates 1, 1b, 1c, 2, and 3.

    Returns exit code if any gate fails, or None if all pass.
    """
    # Gate 1: Anti-tampering
    result = _gate1_constraints_hash(ctx, project_root)
    if result is not None:
        return result

    # Gate 1b: PRD drift (warning only)
    _gate1b_prd_drift(ctx)

    # Gate 1c: PRD-Architecture mapping
    result = _gate1c_mapping(ctx, config_prefix)
    if result is not None:
        return result

    # Gate 2: Code-claim alignment (pre-commit only)
    result = _gate2_code_claim_alignment(ctx, project_root, is_pre_commit)
    if result is not None:
        return result

    # Gate 3: Semantic audit (pre-commit only)
    result = _gate3_semantic_audit(ctx, project_root, is_pre_commit)
    if result is not None:
        return result

    return None


def _gate3_semantic_audit(ctx: UnifiedContext, project_root: Path, is_pre_commit: bool) -> Optional[int]:
    """Run Gate 3: Semantic Audit (pre-commit only).

    Returns None if passed, or 2 if blocked.
    """
    if not is_pre_commit:
        return None

    from vibe_tracing.semantic_auditor import SemanticAuditor
    auditor = SemanticAuditor(project_root)
    staged_code_files = auditor.get_staged_code_files()
    if staged_code_files:
        # Convert Task objects and Requirement objects to dicts for the auditor
        tasks_as_dicts = []
        if ctx.task_result and ctx.task_result.tasks:
            for t in ctx.task_result.tasks:
                tasks_as_dicts.append({
                    "task_id": t.task_id,
                    "related_requirements": t.related_requirements,
                    "related_acceptance_criteria": t.related_acceptance_criteria,
                    "category": getattr(t, "category", None),
                })
        reqs_as_dicts = []
        if ctx.prd and ctx.prd.requirements:
            for r in ctx.prd.requirements:
                reqs_as_dicts.append({
                    "req_id": r.req_id,
                    "category": r.category,
                })
        claims_as_dicts = []
        for c in ctx.claims_list:
            claims_as_dicts.append({
                "claim_id": c.claim_id if hasattr(c, "claim_id") else c.get("claim_id", ""),
                "related_task": c.related_task if hasattr(c, "related_task") else c.get("related_task", ""),
                "code_refs": c.code_refs if hasattr(c, "code_refs") else c.get("code_refs", []),
            })

        new_tickets = auditor.generate_tickets(
            staged_code_files, claims_as_dicts, tasks_as_dicts, reqs_as_dicts,
        )
        if new_tickets:
            print(
                f"Semantic Audit: 生成 {len(new_tickets)} 个审计单，等待 Agent 填充理由。",
                file=sys.stderr,
            )
        success, audit_msg = auditor.verify_tickets(staged_code_files)
        if audit_msg:
            print(audit_msg, file=sys.stderr)
        if not success:
            return 2

    return None


def _get_code_extensions(ltm: Dict) -> Set[str]:
    """Collect all file extensions from every language entry in the language_tool_matrix.

    Iterates over all language entries in *ltm*, merges every ``extensions``
    array into a single set and returns it.  If no language declares an
    ``extensions`` field, an empty set is returned (meaning no tools will
    execute for unknown languages).
    """
    extensions: Set[str] = set()
    for lang_entry in ltm.values():
        if isinstance(lang_entry, dict):
            exts = lang_entry.get("extensions")
            if isinstance(exts, list):
                extensions.update(exts)
    return extensions


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
    code_extensions = _get_code_extensions(ltm)
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
    baseline_path = str(project_root / ".vibetracing" / "coverage_baseline.json")
    tool_evidence_candidates = engine.execute_all(typed_paths, baseline_path=baseline_path)

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


def _get_staged_files(project_root: Path) -> Set[str]:
    """Get the set of staged file paths from ``git diff --cached``.

    Returns an empty set if git is unavailable or no files are staged.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return {f for f in result.stdout.splitlines() if f.strip()}
    except Exception:
        pass
    return set()


def _determine_affected_items(
    staged_files: Set[str],
    claims_list: list,
    ctx: UnifiedContext,
) -> Tuple[Set[str], Set[str], Set[str]]:
    """Determine which claims, requirements, and ACs are affected by staged changes.

    A claim is *affected* if any of its ``code_refs`` or ``test_refs`` paths
    appear in *staged_files*.  A requirement / AC is affected when it is
    covered by a task that has at least one affected claim.

    Returns ``(affected_claim_ids, affected_req_ids, affected_ac_ids)``.
    """
    affected_claims: Set[str] = set()
    affected_reqs: Set[str] = set()
    affected_acs: Set[str] = set()

    for claim in claims_list:
        claim_id = claim.claim_id
        for ref in (claim.code_refs or []) + (claim.test_refs or []):
            path = ref.split("#")[0]
            if path in staged_files:
                affected_claims.add(claim_id)
                break

    # Map affected claims -> tasks -> requirements / ACs
    if affected_claims and ctx.task_result and ctx.task_result.tasks:
        affected_task_ids = {
            claim.related_task
            for claim in claims_list
            if claim.claim_id in affected_claims
        }
        for task in ctx.task_result.tasks:
            if task.task_id in affected_task_ids:
                for req_id in (task.related_requirements or []):
                    affected_reqs.add(req_id)
                for ac_id in (task.related_acceptance_criteria or []):
                    affected_acs.add(ac_id)

    return affected_claims, affected_reqs, affected_acs


def _run_analyzers(
    ctx: UnifiedContext,
    evidence_list: list,
    project_root: Path,
    staged_files: Optional[Set[str]] = None,
) -> Tuple[list, list, Optional[dict], dict, dict]:
    """Run all analyzers and return (merged_gaps, final_risks, compliance_res, claim_res, req_res)."""
    prd_res = ctx.prd
    claims_list = ctx.claims_list

    req_analyzer = RequirementTaskAnalyzer()
    req_res = req_analyzer.analyze(prd_res.requirements, evidence_list)
    req_gaps = req_res.get("gaps", [])

    ac_analyzer = AcTestAnalyzer()
    ac_res = ac_analyzer.analyze(prd_res.requirements, evidence_list)
    ac_gaps = ac_res.get("gaps", [])

    claim_analyzer = ClaimEvidenceAnalyzer(project_root)
    claim_res = claim_analyzer.analyze(claims_list, evidence_list)
    claim_gaps = claim_res.get("gaps", [])
    claim_risks = claim_res.get("risks", [])

    # Merge gaps
    seen_gaps = set()
    merged_gaps = []
    for gap in req_gaps + ac_gaps + claim_gaps:
        key = (gap.get("item_id"), gap.get("item_type"))
        if key not in seen_gaps:
            seen_gaps.add(key)
            merged_gaps.append(gap)

    # Architecture compliance check
    compliance_res = None
    constraints_path = project_root / "docs" / "architecture_constraints.json"
    if constraints_path.exists() and ctx.constraints is not None:
        # Extract pre-computed hash from manifest to avoid re-reading file
        _constraints_hash = None
        if ctx.manifest:
            for _r in ctx.manifest.inputs_used:
                if _r.file_key == "architecture_constraints" and _r.sha256_hash:
                    _constraints_hash = _r.sha256_hash
                    break
        compliance_checker = ArchitectureComplianceChecker(
            project_root,
            constraints_path=constraints_path,
            constraints_hash=_constraints_hash,
            config_data=ctx.config,
        )
        compliance_res = compliance_checker.check(
            evidence_list, constraints_data=ctx.constraints
        )

    # Risk Advisor
    risk_advisor = RiskAdvisor(project_root)
    final_risks = risk_advisor.generate_risks(
        gaps=merged_gaps,
        claims_analysis=claim_res.get("claims_analysis", []),
        claim_risks=claim_risks,
        compliance_result=compliance_res,
        claims_list=claims_list,
    )

    if compliance_res:
        final_risks.extend(compliance_res.get("proposal_risks", []))
        for gap in compliance_res.get("proposal_gaps", []):
            key = (gap.get("item_id"), gap.get("item_type"))
            if key not in seen_gaps:
                seen_gaps.add(key)
                merged_gaps.append(gap)

    # ------------------------------------------------------------------
    # Incremental staleness tracking: mark gaps / risks from unchanged
    # items as ``stale`` so that gate evaluation can skip them while the
    # report still includes them for full visibility.
    # ------------------------------------------------------------------
    has_staged = staged_files is not None and len(staged_files) > 0
    if has_staged and staged_files is not None:
        affected_claims, affected_reqs, affected_acs = _determine_affected_items(
            staged_files, claims_list, ctx,
        )

        for gap in merged_gaps:
            item_type = gap.get("item_type")
            item_id = gap.get("item_id")
            if item_type == "claim" and item_id not in affected_claims:
                gap["stale"] = True
            elif item_type == "requirement" and item_id not in affected_reqs:
                gap["stale"] = True
            elif item_type == "ac" and item_id not in affected_acs:
                gap["stale"] = True

        for risk in final_risks:
            claim_id = risk.get("claim_id")
            if claim_id is not None and claim_id not in affected_claims:
                risk["stale"] = True

        stale_gap_count = sum(1 for g in merged_gaps if g.get("stale"))
        stale_risk_count = sum(1 for r in final_risks if r.get("stale"))
        if stale_gap_count > 0 or stale_risk_count > 0:
            print(f"  Note: {stale_gap_count} gaps and {stale_risk_count} risks from unchanged files (marked stale).", file=sys.stderr)

    # Staged file extension coverage check (WARNING only)
    _check_staged_extensions(project_root, ctx.constraints)

    return merged_gaps, final_risks, compliance_res, claim_res, req_res


def _get_ac_description(ac_id: str, prd_result) -> str:
    """Extract AC title from PrdParseResult."""
    if not prd_result or not hasattr(prd_result, "requirements"):
        return ""
    for req in prd_result.requirements:
        for ac in req.acceptance_criteria:
            if ac.ac_id == ac_id:
                return ac.title
    return ""


def _get_req_description(req_id: str, prd_result) -> str:
    """Extract requirement title from PrdParseResult."""
    if not prd_result or not hasattr(prd_result, "requirements") or not req_id:
        return ""
    for req in prd_result.requirements:
        if req.req_id == req_id:
            return req.title
    return ""


def _get_related_code(ac_id: str, task_result, claims_list=None) -> list:
    """Extract code file paths related to an AC from claims (not tasks)."""
    code_refs = []
    if not claims_list:
        return code_refs

    # Collect task IDs that reference this AC
    task_ids = set()
    if task_result and hasattr(task_result, "tasks"):
        for task in task_result.tasks:
            if ac_id in (task.related_acceptance_criteria or []):
                task_ids.add(task.task_id)

    # Find claims referencing those tasks and collect their code_refs
    for claim in claims_list:
        related = getattr(claim, "related_task", None)
        if related in task_ids:
            for ref in (getattr(claim, "code_refs", None) or []):
                path_only = ref.split("#")[0]
                if path_only and Path(path_only).exists():
                    try:
                        content = Path(path_only).read_text()[:500]
                        code_refs.append({"path": path_only, "content": content})
                    except Exception:
                        pass
                    if len(code_refs) >= 3:
                        break
    return code_refs


def _get_existing_tests(ac_id: str, task_result, claims_list=None) -> list:
    """Get test file paths related to an AC from claims (not tasks)."""
    test_refs = []
    if not claims_list:
        return test_refs

    # Collect task IDs that reference this AC
    task_ids = set()
    if task_result and hasattr(task_result, "tasks"):
        for task in task_result.tasks:
            if ac_id in (task.related_acceptance_criteria or []):
                task_ids.add(task.task_id)

    # Find claims referencing those tasks and collect their test_refs
    for claim in claims_list:
        related = getattr(claim, "related_task", None)
        if related in task_ids:
            for ref in (getattr(claim, "test_refs", None) or []):
                test_refs.append(ref)
                if len(test_refs) >= 2:
                    break
    return test_refs


# ---------------------------------------------------------------------------
# Hint loading for action messages (mirrors task_loader.py pattern)
# ---------------------------------------------------------------------------
_HINTS_PATH = Path(__file__).parent / "templates" / "field_hints.json"


def _load_hints(category: str = "action") -> Dict[str, Any]:
    """Load hints from field_hints.json for the given category."""
    with _HINTS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f).get(category, {})


def _resolve_hint(hint_value: Any, level: str = "level1") -> str:
    """Resolve a hint value to a string at the given verbosity level.

    Backward compatible: if hint_value is a plain string, returns it directly.
    """
    if isinstance(hint_value, str):
        return hint_value
    if isinstance(hint_value, dict):
        return hint_value.get(level, hint_value.get("level1", ""))
    return ""


# Module-level cache for action hints
_action_hints: Dict[str, Any] = _load_hints("action")


def _hint_title(action_type: str, **kwargs: Any) -> str:
    """Extract the title portion from the first sentence of a level1 hint."""
    hint = _action_hints.get(action_type, {})
    template = _resolve_hint(hint, "level1")
    # Extract first sentence (before Chinese period 。)
    idx = template.find("。")
    if idx > 0:
        template = template[:idx]
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def _hint_context(action_type: str, key: str, **kwargs: Any) -> str:
    """Get a context value from action hints and format with variables."""
    hint = _action_hints.get(action_type, {})
    template = hint.get(key, "")
    if not template:
        return ""
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def _derive_test_scenarios(ac_text: str) -> list:
    """Derive test scenarios from AC title text using hints."""
    hints = _action_hints.get("test_scenarios", {})
    default = hints.get("default", "")
    if not ac_text:
        return [default]
    scenarios = []
    if any(kw in ac_text for kw in ["无效", "错误", "invalid", "error"]):
        scenarios.append(hints.get("invalid_input", ""))
    if any(kw in ac_text for kw in ["空", "empty"]):
        scenarios.append(hints.get("empty_input", ""))
    if any(kw in ac_text for kw in ["正常", "valid", "正确"]):
        scenarios.append(hints.get("valid_input", ""))
    if not scenarios:
        scenarios.append(default)
    return scenarios


# ---------------------------------------------------------------------------
# Split action collectors (each returns a list of action dicts)
# ---------------------------------------------------------------------------

def _collect_gap_actions(
    merged_gaps: list,
    prd_result: Any,
    task_result: Any,
    claims_list: list,
) -> list:
    """Collect gap-related actions for MUST-level gaps."""
    actions = []
    for gap in merged_gaps:
        if gap.get("severity") != "must" or gap.get("human_accepted"):
            continue
        ac_id = gap.get("item_id", "")
        ac_text = _get_ac_description(ac_id, prd_result) or gap.get("title", "")
        related_code = _get_related_code(ac_id, task_result, claims_list)
        existing_tests = _get_existing_tests(ac_id, task_result, claims_list)
        test_scenarios = _derive_test_scenarios(ac_text)

        ctx: Dict[str, Any] = {
            "ac_description": ac_text,
            "severity": gap.get("severity", "MUST"),
            "requirement_id": gap.get("requirement_id", ""),
            "requirement_text": _get_req_description(
                gap.get("requirement_id"), prd_result,
            ),
            "test_scenarios": test_scenarios,
            "verification": _hint_context("cover_gap", "verification", ac_id=ac_id),
        }
        if gap.get("stale"):
            ctx["note"] = _hint_context("cover_gap", "stale_note")
        if related_code:
            ctx["implementation_files"] = [r["path"] for r in related_code]
        if existing_tests:
            ctx["existing_tests"] = existing_tests

        actions.append({
            "priority": "HIGH",
            "type": "cover_gap",
            "title": _hint_title("cover_gap", ac_id=ac_id, ac_text=ac_text),
            "context": ctx,
        })
    return actions


def _collect_risk_actions(active_risks: list, merged_gaps: list) -> list:
    """Collect risk-related actions (MUST risks and stale debts)."""
    actions = []
    for risk in active_risks:
        severity = risk.get("severity")
        desc = risk.get("description", "")
        is_self_ref = "only self-referential" in desc or "self-referential" in desc
        if severity == "must" or is_self_ref:
            actions.append({
                "priority": "HIGH",
                "type": "high_risk",
                "title": _hint_title(
                    "high_risk",
                    risk_id=risk.get("risk_id", ""),
                    title=risk.get("title", ""),
                ),
                "context": {
                    "risk_id": risk.get("risk_id", ""),
                    "severity": severity,
                    "description": desc,
                    "claim_id": risk.get("claim_id", ""),
                    "suggested_action": risk.get("suggested_action", ""),
                    "fix_via": _hint_context("high_risk", "fix_via"),
                },
            })

    for risk in active_risks:
        if risk.get("stale") and not risk.get("deferred"):
            age_val = risk.get("age_iterations", "多个")
            actions.append({
                "priority": "LOW",
                "type": "stale_debt",
                "title": _hint_title("stale_debt", title=risk.get("title", "")),
                "context": {
                    "description": risk.get("description", ""),
                    "age": _hint_context(
                        "stale_debt", "age_format", age_iterations=age_val,
                    ),
                },
            })
    return actions


def _collect_violation_actions(violations: list, compliance_status: list) -> list:
    """Collect architecture violation actions."""
    actions = []
    for v in violations:
        actions.append({
            "priority": "HIGH",
            "type": "fix_violation",
            "title": _hint_title("fix_violation", rule_id=v.get("rule_id", "")),
            "context": {
                "rule_text": v.get("description", ""),
                "violation_reason": v.get("reason", ""),
                "fix_via": _hint_context("fix_violation", "fix_via"),
            },
        })

    for status_item in compliance_status:
        rule_id = status_item.get("rule_id", "")
        status = status_item.get("status")
        item_severity = status_item.get("severity", "must")
        if status == "violated" and item_severity == "must":
            if not any(v.get("rule_id") == rule_id for v in violations):
                actions.append({
                    "priority": "HIGH",
                    "type": "arch_status_violation",
                    "title": _hint_title(
                        "arch_status_violation", rule_id=rule_id,
                    ),
                    "context": {
                        "rule_id": rule_id,
                        "severity": item_severity,
                        "fix_via": _hint_context("arch_status_violation", "fix_via"),
                    },
                })
    return actions


def _collect_gate_reason_actions(
    gate_decision: str,
    gate_reasons: list,
    existing_actions: list,
) -> list:
    """Generate fallback actions from gate reasons when no HIGH actions exist."""
    has_high = any(a["priority"] == "HIGH" for a in existing_actions)
    if gate_decision not in ("blocked", "fail") or has_high or not gate_reasons:
        return []
    actions = []
    for reason in gate_reasons:
        actions.append({
            "priority": "HIGH",
            "type": "gate_blocked",
            "title": _hint_title("gate_blocked", reason=reason[:80]),
            "context": {
                "reason": reason,
                "fix_via": _hint_context("gate_blocked", "fix_via"),
            },
        })
    return actions


def _render_actions(actions: list, coverage_summary: Optional[dict] = None, project_root: Optional[Path] = None) -> list:
    """Render action dicts to text lines for Agent consumption."""
    lines: List[str] = []
    if not actions:
        lines.append("NO ACTION REQUIRED. Gate passed.")
        return lines
    for i, action in enumerate(actions, 1):
        lines.append(f"{'=' * 70}")
        lines.append(f"ACTION {i} [{action['priority']}] {action['title']}")
        lines.append(f"{'=' * 70}")
        ctx = action.get("context", {})
        for key, value in ctx.items():
            if isinstance(value, list):
                lines.append(f"  {key}:")
                for item in value:
                    if isinstance(item, dict):
                        lines.append(f"    - {item.get('path', '')}")
                    else:
                        lines.append(f"    - {item}")
            else:
                lines.append(f"  {key}: {value}")
        lines.append("")

    # Summary section
    lines.append("=" * 70)
    lines.append("SUMMARY")
    lines.append("=" * 70)

    high_count = sum(1 for a in actions if a.get("priority") == "HIGH")
    medium_count = sum(1 for a in actions if a.get("priority") == "MEDIUM")
    low_count = sum(1 for a in actions if a.get("priority") == "LOW")

    lines.append(f"HIGH: {high_count} | MEDIUM: {medium_count} | LOW: {low_count}")

    # If there are human decision items, add explicit Agent instructions
    human_decision_items = [a for a in actions if a.get("type") == "human_decision"]
    if human_decision_items:
        dec_ids = [a.get("id", "") for a in human_decision_items]
        lines.append("")
        lines.append("⚠ 存在待人类决策的事项。请执行以下操作：")
        lines.append(f"1. 通知人类打开 dashboard: output/dashboard.html")
        lines.append(f"2. 在\"待决策\"标签页中查看 {', '.join(dec_ids)}")
        lines.append("3. 等待人类做出决策后，重新运行 vt analyze")
        if high_count > 0:
            lines.append("4. 在等待期间，可继续执行 HIGH 优先级的行动项")
    elif high_count == 0 and medium_count == 0:
        lines.append("NO ACTION REQUIRED. Gate passed.")

    # Add coverage info to agent output
    if coverage_summary:
        pct = coverage_summary["aggregate_percent"]
        status = "PASS" if pct >= 80 else "BLOCKED"
        lines.append("")
        lines.append(f"Coverage: {pct}% ({status}, target: 80%)")
        if pct < 80:
            # List files below threshold
            baseline_file = (project_root / ".vibetracing" / "coverage_baseline.json") if project_root else Path(".vibetracing") / "coverage_baseline.json"
            if baseline_file.exists():
                try:
                    baseline = json.loads(baseline_file.read_text(encoding="utf-8"))
                    below = [(f, d["percent_covered"]) for f, d in baseline.get("files", {}).items()
                             if d["percent_covered"] < 80]
                    below.sort(key=lambda x: x[1])
                    for f, p in below[:5]:
                        lines.append(f"  {f}: {p}%")
                except Exception:
                    pass

    return lines


def _format_agent_actions(gate_decision, active_gaps, active_risks, violations,
                          accepted_rules, prd_result=None, task_result=None,
                          claims_list=None, gate_reasons=None, merged_gaps=None,
                          compliance_status=None, coverage_summary=None,
                          project_root=None):
    """Format an Agent-executable action list with full inline context."""
    lines = [f"GATE DECISION: {gate_decision.upper()}", ""]
    gaps_for_actions = merged_gaps if merged_gaps is not None else active_gaps
    actions: list = []
    actions.extend(_collect_gap_actions(
        gaps_for_actions, prd_result, task_result, claims_list,
    ))
    actions.extend(_collect_risk_actions(active_risks, merged_gaps or []))
    actions.extend(_collect_violation_actions(violations, compliance_status or []))
    actions.extend(_collect_gate_reason_actions(
        gate_decision, gate_reasons or [], actions,
    ))
    lines.extend(_render_actions(actions, coverage_summary, project_root))
    return "\n".join(lines)


def _check_staged_extensions(project_root: Path, constraints: Optional[dict]) -> None:
    """Warn about staged files whose extensions are not in the configured language_tool_matrix.

    This is a WARNING-only check: it does not block the analysis pipeline.
    """
    if not constraints:
        return

    ltm = constraints.get("language_tool_matrix", {})
    configured_exts = _get_code_extensions(ltm)
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


def _load_governance_boundary(
    project_root: Path, constraints_data: Optional[dict] = None,
) -> dict:
    """Load governance_boundary from already-loaded constraints data.

    If *constraints_data* is provided (the parsed dict from UnifiedContext),
    the file is NOT re-read from disk.
    """
    if constraints_data is not None:
        return constraints_data.get("governance_boundary", {"included_patterns": [], "excluded_patterns": []})
    constraints_path = project_root / "docs" / "architecture_constraints.json"
    if not constraints_path.exists():
        return {"included_patterns": [], "excluded_patterns": []}
    try:
        data = json.loads(constraints_path.read_text(encoding="utf-8"))
        return data.get("governance_boundary", {"included_patterns": [], "excluded_patterns": []})
    except Exception:
        return {"included_patterns": [], "excluded_patterns": []}


def _is_in_governance_boundary(file_path: str, boundary: dict) -> bool:
    """Check if a file is within the governance boundary.

    Files matching any excluded_pattern are considered outside the boundary.
    """
    excluded = boundary.get("excluded_patterns", [])
    for pattern in excluded:
        if fnmatch.fnmatch(file_path, pattern) or fnmatch.fnmatch(file_path, f"*/{pattern}"):
            return False
    return True


def _partition_by_governance_boundary(
    affected_files: List[str], project_root: Path,
    constraints_data: Optional[dict] = None,
) -> Tuple[Set[str], Set[str]]:
    """Partition files into in-scope and out-of-scope sets.

    Returns (in_scope, out_of_scope).
    """
    boundary = _load_governance_boundary(project_root, constraints_data=constraints_data)
    in_scope: Set[str] = set()
    out_of_scope: Set[str] = set()
    for f in affected_files:
        if _is_in_governance_boundary(f, boundary):
            in_scope.add(f)
        else:
            out_of_scope.add(f)
    return in_scope, out_of_scope


def _load_human_decisions() -> dict:
    """读取人类决策日志"""
    decisions_path = Path(".vibetracing/human_decisions.json")
    if not decisions_path.exists():
        return {"version": "1.0", "decisions": []}
    try:
        return json.loads(decisions_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": "1.0", "decisions": []}


def _apply_human_decisions(report_doc: dict, decisions: dict) -> dict:
    """将人类决策应用到报告中"""
    for decision in decisions.get("decisions", []):
        category = decision.get("category")
        target_id = decision.get("target_id")
        action = decision.get("action")

        if category == "accepted_rule" and action == "reconfirm":
            for rule in report_doc.get("accepted_rules", []):
                if rule.get("rule_id") == target_id:
                    rule["accepted_at"] = decision.get("timestamp", "")
                    rule["stale_acceptance"] = False

        elif category == "uncovered_ac" and action == "accept_gap":
            for gap in report_doc.get("gaps", []):
                if gap.get("item_id") == target_id:
                    gap["human_accepted"] = True

        elif category == "stale_debt" and action == "defer":
            for risk in report_doc.get("risks", []):
                if risk.get("claim_id") == target_id:
                    risk["deferred"] = True

        elif category == "accepted_rule" and action == "reject":
            for rule in report_doc.get("accepted_rules", []):
                if rule.get("rule_id") == target_id:
                    rule["rejected"] = True

    return report_doc


def _compute_claim_hash(claim: dict) -> str:
    """Compute content hash of a claim (excluding hash and timestamp fields)."""
    content = {k: v for k, v in claim.items() if k not in ("content_hash", "timestamp")}
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]


def _get_directly_modified_claims(
    old_claims: list,
    new_claims: list,
) -> set:
    """Detect which claims were actually modified by comparing content hashes."""
    old_hashes = {}
    for c in old_claims:
        cid = c.get("claim_id")
        if cid:
            old_hashes[cid] = c.get("content_hash")

    new_hashes = {}
    for c in new_claims:
        cid = c.get("claim_id")
        if cid:
            new_hashes[cid] = c.get("content_hash")

    modified = set()
    for claim_id, new_hash in new_hashes.items():
        old_hash = old_hashes.get(claim_id)
        if old_hash is None:
            modified.add(claim_id)  # new claim
        elif old_hash != new_hash:
            modified.add(claim_id)  # content changed
    return modified


def _file_sha256(path: Path) -> Optional[str]:
    """Compute SHA-256 hex digest of a file."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, IOError):
        return None


def _save_claim_fingerprints(claims_list, project_root: Path):
    """Save SHA-256 fingerprints of all files referenced by claims."""
    fingerprints = {}
    for claim in claims_list:
        cid = claim.claim_id if hasattr(claim, 'claim_id') else claim.get('claim_id')
        refs = set()
        for ref in (getattr(claim, 'code_refs', None) or []) + \
                   (getattr(claim, 'test_refs', None) or []) + \
                   (getattr(claim, 'evidence_refs', None) or []):
            path = ref.split("#")[0]
            if path:
                refs.add(path)

        file_hashes = {}
        for ref_path in refs:
            full_path = project_root / ref_path
            if full_path.exists():
                h = _file_sha256(full_path)
                if h:
                    file_hashes[ref_path] = h

        if file_hashes:
            fingerprints[cid] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "fingerprints": file_hashes,
            }

    fp_path = project_root / ".vibetracing" / "claim_fingerprints.json"
    fp_path.write_text(json.dumps(fingerprints, indent=2, ensure_ascii=False), encoding="utf-8")


def _evaluate_and_output(
    ctx: UnifiedContext,
    merged_gaps: list,
    final_risks: list,
    compliance_res: Optional[dict],
    output_dir: Path,
    evidence_index: dict,
    claim_res: dict,
    req_res: dict,
    project_root: Path,
    is_draft: bool,
    staged_files: Optional[Set[str]] = None,
) -> int:
    """Run MergeGateEngine, output all reports, and return exit code."""
    prd_res = ctx.prd
    manifest = ctx.manifest
    if not manifest:
        return 1
    claims_list = ctx.claims_list
    task_res = ctx.task_result

    # Filter out stale gaps / risks for gate evaluation.  Stale items are
    # still included in the full report for visibility.
    active_gaps = [g for g in merged_gaps if not g.get("stale")]
    active_risks = [r for r in final_risks if not r.get("stale")]

    # Build staged_items for debt awareness (EVO-TASK-025 / EVO-TASK-012).
    # staged_items contains all identifiers that are provably affected by
    # the current staged changes: claim IDs, task IDs, AC IDs, and
    # requirement IDs.  The gate engine uses this set to decide whether an
    # issue should block (current) or merely be displayed (pre-existing).
    staged_items: Optional[Set[str]] = None
    directly_staged_items: Optional[Set[str]] = None
    if staged_files:
        affected_claims, affected_reqs, affected_acs = _determine_affected_items(
            staged_files, claims_list, ctx,
        )
        staged_items = set(affected_claims)
        # Also include related task IDs
        if ctx.task_result and ctx.task_result.tasks:
            affected_task_ids = {
                claim.related_task
                for claim in claims_list
                if claim.claim_id in affected_claims
            }
            staged_items.update(affected_task_ids)
        # Include affected AC and requirement IDs so the gate engine can
        # match AC-level gaps directly to staged changes.
        staged_items.update(affected_acs)
        staged_items.update(affected_reqs)

        # Build directly_staged_items: only items whose definitions were
        # directly modified in this commit.  Claims are included only when
        # the claims JSON file itself is staged (i.e. the claim was edited),
        # NOT when merely a referenced code/test file was modified.  Tasks,
        # ACs, and requirements are always included since their coverage is
        # directly impacted by code changes.
        claims_file_rel = ".vibetracing/agent_claims.json"
        if claims_file_rel in staged_files:
            # Compare per-claim content hashes to find actually modified claims
            from vibe_tracing.git_utils import git_show
            try:
                old_json = git_show("HEAD", ".vibetracing/agent_claims.json", project_root)
                old_claims = json.loads(old_json) if old_json else []
            except Exception:
                old_claims = []
            new_claims_raw = []
            for c in claims_list:
                if hasattr(c, '__dict__'):
                    new_claims_raw.append(c.__dict__)
                elif isinstance(c, dict):
                    new_claims_raw.append(c)
                else:
                    new_claims_raw.append(asdict(c) if hasattr(c, '__dataclass_fields__') else {})
            directly_staged_claims = _get_directly_modified_claims(old_claims, new_claims_raw)
        else:
            # Only code/test files were modified — claims are indirectly affected
            directly_staged_claims = set()
        # directly_staged_items only contains claims whose content_hash
        # actually changed. Tasks/ACs/reqs stay in staged_items (superset)
        # but NOT in directly_staged_items, so old claims referencing
        # modified code files are correctly tagged as [预存].
        directly_staged_items = set(directly_staged_claims)

    # Merge Gate Engine
    gate_engine = MergeGateEngine(project_root)
    gate_res = gate_engine.evaluate(
        active_gaps, active_risks, compliance_res,
        prd_status=prd_res.status, staged_items=staged_items,
        directly_staged_items=directly_staged_items,
    )
    gate_decision = gate_res["gate_decision"]

    # Assemble report document
    report_doc = {
        "run_id": evidence_index.get("run_id"),
        "project_id": evidence_index.get("project_id"),
        "scan_time": evidence_index.get("scan_time"),
        "gate_decision": gate_decision,
        "requirement_coverage": req_res.get("requirement_coverage", []),
        "gaps": merged_gaps,
        "risks": final_risks,
        "architecture_compliance_status": compliance_res.get(
            "architecture_compliance_status", []
        ) if compliance_res else [],
        "architecture_violations": compliance_res.get(
            "architecture_violations", []
        ) if compliance_res else [],
        "unclear_constraints": compliance_res.get("unclear_constraints", [])
        if compliance_res else [],
        "accepted_rules": compliance_res.get("accepted_rules", [])
        if compliance_res else [],
    }

    # Add coverage summary to report
    coverage_baseline_path = project_root / ".vibetracing" / "coverage_baseline.json"
    if coverage_baseline_path.exists():
        try:
            baseline = json.loads(coverage_baseline_path.read_text(encoding="utf-8"))
            report_doc["coverage_summary"] = {
                "aggregate_percent": baseline.get("aggregate_percent", 0),
                "total_statements": baseline.get("total_statements", 0),
                "total_covered": baseline.get("total_covered", 0),
                "file_count": len(baseline.get("files", {})),
                "timestamp": baseline.get("timestamp", ""),
            }
        except Exception:
            pass

    # Apply human decisions
    human_decisions = _load_human_decisions()
    if human_decisions.get("decisions"):
        report_doc = _apply_human_decisions(report_doc, human_decisions)
        print(f"  Applied {len(human_decisions['decisions'])} human decision(s).", file=sys.stderr)

    # Build evidence index path (already written by caller)
    index_path = output_dir / "evidence_index.json"
    exit_code = 2 if gate_decision == "blocked" else 0

    def rel_path_str(p: Path) -> str:
        try:
            if p.is_absolute() and (project_root in p.parents or p == project_root):
                return str(p.relative_to(project_root))
        except Exception:
            pass
        return str(p)

    # Build and save traceability report
    report_builder = TraceabilityReportBuilder(project_root)
    report_path = output_dir / "traceability_report.json"
    try:
        report_doc = report_builder.build(report_doc, output_path=report_path)
    except Exception as exc:
        print(f"Error building traceability report: {exc}", file=sys.stderr)
        raise _GateBlocked(1)

    # Render dashboard
    dashboard_path = output_dir / "dashboard.html"
    try:
        # Extract pre-computed hash from manifest to avoid re-reading file
        _dash_constraints_hash = None
        if manifest:
            for _r in manifest.inputs_used:
                if _r.file_key == "architecture_constraints" and _r.sha256_hash:
                    _dash_constraints_hash = _r.sha256_hash
                    break
        renderer = DashboardRenderer(
            project_root,
            constraints_hash=_dash_constraints_hash,
            config_data=ctx.config,
        )
        prd_reqs_serialized = []
        for req in prd_res.requirements:
            ac_list = [
                {
                    "ac_id": ac.ac_id,
                    "title": ac.title,
                    "is_testing_required": ac.is_testing_required,
                }
                for ac in req.acceptance_criteria
            ]
            prd_reqs_serialized.append(
                {
                    "req_id": req.req_id,
                    "title": req.title,
                    "priority": req.priority,
                    "acceptance_criteria": ac_list,
                }
            )
        renderer.render(
            evidence_index=evidence_index,
            traceability_report=report_doc,
            output_path=dashboard_path,
            prd_requirements=prd_reqs_serialized,
        )
    except Exception as exc:
        print(f"Error rendering dashboard: {exc}", file=sys.stderr)
        raise _GateBlocked(1)

    # Build metadata section and embed in traceability_report.json
    run_id = report_doc.get("run_id")
    project_id = report_doc.get("project_id")
    scan_time = report_doc.get("scan_time")

    # Reconstruct input_files metadata from manifest
    records_dict = {r.file_key: r for r in manifest.inputs_used}
    prd_record = records_dict.get("prd")
    constraints_path = project_root / "docs" / "architecture_constraints.json"
    task_list_path = project_root / "docs" / "task_list.json"
    claims_record = records_dict.get("agent_claims")

    input_files_meta = {
        "prd": rel_path_str(Path(prd_record.file_path)) if prd_record else "",
        "architecture_constraints": rel_path_str(constraints_path) if constraints_path.exists() else "",
        "task_list": rel_path_str(task_list_path),
    }
    if claims_list and claims_record:
        input_files_meta["agent_claims"] = rel_path_str(Path(claims_record.file_path))

    metadata_doc = {
        "run_id": run_id,
        "project_id": project_id,
        "scan_time": scan_time,
        "input_files": input_files_meta,
        "output_files": {
            "evidence_index": rel_path_str(index_path),
            "traceability_report": rel_path_str(report_path),
            "dashboard": rel_path_str(dashboard_path),
        },
        "gate_decision": gate_decision,
        "exit_code": exit_code,
        "summary": "; ".join(gate_res["reasons"]),
    }

    # Write metadata section into traceability_report.json
    report_doc["metadata"] = metadata_doc
    try:
        with report_path.open("w", encoding="utf-8") as f:
            json.dump(report_doc, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"Error writing traceability report with metadata: {exc}", file=sys.stderr)
        raise _GateBlocked(1)

    # Print summary -- when staged_items is provided (pre-commit mode),
    # separate current issues from pre-existing debt for clarity.
    print(f"Analysis complete. Gate decision: {gate_decision.upper()}")
    if staged_items is not None:
        current_reasons = [r for r in gate_res["reasons"] if r.startswith("[当前]")]
        pre_existing_reasons = [r for r in gate_res["reasons"] if r.startswith("[预存]")]
        unprefixed = [r for r in gate_res["reasons"] if not r.startswith("[当前]") and not r.startswith("[预存]")]
        if current_reasons:
            print("\nCURRENT ISSUES (blocks commit):")
            for reason in current_reasons:
                print(f"- {reason}")
        if pre_existing_reasons:
            print("\nPRE-EXISTING DEBT (does not block):")
            for reason in pre_existing_reasons:
                print(f"- {reason}")
        if unprefixed:
            for reason in unprefixed:
                print(f"- {reason}")
    else:
        for reason in gate_res["reasons"]:
            print(f"- {reason}")

    # Format and print Agent action list (additional output for Agent consumption)
    violations = compliance_res.get("architecture_violations", []) if compliance_res else []
    accepted_rules = compliance_res.get("accepted_rules", []) if compliance_res else []
    compliance_status = compliance_res.get("architecture_compliance_status", []) if compliance_res else []
    agent_output = _format_agent_actions(
        gate_decision=gate_decision,
        active_gaps=active_gaps,
        active_risks=active_risks,
        violations=violations,
        accepted_rules=accepted_rules,
        prd_result=prd_res,
        task_result=task_res,
        claims_list=claims_list,
        gate_reasons=gate_res["reasons"],
        merged_gaps=merged_gaps,
        compliance_status=compliance_status,
        coverage_summary=report_doc.get("coverage_summary"),
        project_root=project_root,
    )
    print(agent_output)

    if is_draft and (not task_res or not task_res.tasks) and not claims_list:
        print("\n【零提示词引导】当前项目处于 PRD 草稿阶段（draft），且未发现任何开发任务。请让 AI Agent 读取项目内的 .vibetracing/prompts/prd_analysis.md 并按照其中的 7 步分析法对 PRD 进行分析与补充，逐步生成对应的架构约束和任务列表。")

    from vibe_tracing.reflection_prompts import render_reflection_prompts

    # Extract affected_files from the analysis context
    affected_files: List[str] = []
    for claim in claims_list:
        for ref in claim.code_refs:
            path = ref.split("#")[0]
            if path and path not in affected_files:
                affected_files.append(path)
        for ref in claim.test_refs:
            path = ref.split("#")[0]
            if path and path not in affected_files:
                affected_files.append(path)

    # Partition affected files by governance boundary
    in_scope_files, out_of_scope_files = _partition_by_governance_boundary(
        affected_files, project_root, constraints_data=ctx.constraints,
    )

    # Extract raw task_list dict from manifest
    records_dict_all = {r.file_key: r for r in manifest.inputs_used}
    task_list_record = records_dict_all.get("task_list")
    task_list_raw = task_list_record.content if task_list_record and task_list_record.status == "ok" else {"tasks": []}

    # Only pass in-scope files to reflection prompts so that out-of-scope
    # files do not trigger coverage warnings.
    print(render_reflection_prompts(
        gate_decision=gate_decision,
        gaps=merged_gaps,
        risks=final_risks,
        task_list=task_list_raw,
        affected_files=sorted(in_scope_files),
        compliance_result=compliance_res,
        governance_in_scope_count=len(in_scope_files),
        governance_out_of_scope_count=len(out_of_scope_files),
    ))

    # Save claim fingerprints for tamper detection
    _save_claim_fingerprints(claims_list, project_root)

    return exit_code


def run_analyze(project_root: Path, output_dir: Optional[Path] = None, is_pre_commit: bool = False, gates_only: bool = False) -> int:
    """
    Execute the full Vibe Tracing analysis pipeline.

    Args:
        project_root: The workspace root path.
        output_dir: The target output directory. If None, resolved from
            config.json paths.output_dir (default: "output").
        is_pre_commit: Whether running in pre-commit hook mode.
        gates_only: If True, run only integrity gates (1, 2, 2.5) and skip
            tool execution and full analysis (fast mode for pre-commit).

    Returns:
        Exit code:
            0: Gate decision is 'pass' or 'fail' (conditional).
            1: Execution error, invalid inputs, schema errors.
            2: Gate decision is 'blocked'.
    """
    try:
        schemas_dir = project_root / "schemas"
        if not schemas_dir.is_dir():
            schemas_dir = Path(__file__).parent / "schemas"
        validator = SchemaValidator(schemas_dir)

        ctx, raw_loader, validator = _load_context(project_root, schemas_dir, validator)
        prd_res = ctx.prd
        is_draft = (prd_res.status == "draft")
        config_prefix = ctx.config_prefix

        # Resolve output_dir from config if not explicitly provided
        if output_dir is None:
            _out_rel = ctx.config.get("paths", {}).get("output_dir", "output")
            output_dir = (project_root / _out_rel).resolve()

        exit_code = _run_integrity_gates(
            ctx, project_root, is_pre_commit, config_prefix,
        )
        if exit_code is not None:
            return exit_code

        if gates_only:
            print("Gates-only mode: integrity gates passed. Skipping analysis.")
            return 0

        tool_evidence = _execute_tools(ctx, project_root, is_draft)
        ctx.tool_evidence = tool_evidence

        # Build evidence index
        index_builder = EvidenceIndexBuilder(project_root)
        index_path = output_dir / "evidence_index.json"
        try:
            evidences_index = index_builder.build(
                output_path=index_path,
                ctx=ctx,
                tool_evidence_candidates=tool_evidence,
                prd_record=prd_res,
                task_result=ctx.task_result,
                claims_list=ctx.claims_list,
                manifest=ctx.manifest,
                config_prefix=config_prefix,
            )
        except Exception as exc:
            print(f"Error building evidence index: {exc}", file=sys.stderr)
            return 1

        evidence_list = evidences_index.get("evidences", [])

        # Assess claim credibility
        if ctx.claims_list:
            credibility_warnings = assess_claim_credibility(
                ctx.claims_list, evidence_list,
                task_result=ctx.task_result, project_root=project_root,
            )
            for warning in credibility_warnings:
                print(f"Warning: {warning}", file=sys.stderr)

        staged_files = _get_staged_files(project_root)

        merged_gaps, final_risks, compliance_res, claim_res, req_res = _run_analyzers(
            ctx, evidence_list, project_root,
            staged_files=staged_files,
        )

        return _evaluate_and_output(
            ctx, merged_gaps, final_risks, compliance_res,
            output_dir, evidences_index, claim_res, req_res,
            project_root, is_draft, staged_files=staged_files,
        )

    except _GateBlocked as exc:
        return exc.exit_code
    except Exception as exc:
        print(f"Unexpected error running analyze command: {exc}", file=sys.stderr)
        return 1


def run_accept(project_root: Path, rule_id: str, accepted_by: str = "human") -> int:
    """Accept a manual architecture constraint rule.

    Reads architecture_constraints.json, finds the rule by rule_id across
    all sections, sets ``accepted_by`` and ``accepted_at``, and writes back.
    """
    import datetime

    constraints_path = project_root / "docs" / "architecture_constraints.json"
    if not constraints_path.exists():
        print(f"Error: {constraints_path} not found.", file=sys.stderr)
        return 1

    try:
        with constraints_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"Error reading {constraints_path}: {exc}", file=sys.stderr)
        return 1

    # All rule array keys to search
    rule_keys = [
        "architecture_principles",
        "module_boundaries",
        "dependency_rules",
        "data_flow_rules",
        "storage_rules",
        "error_handling_rules",
        "logging_rules",
        "security_rules",
        "technology_constraints",
        "forbidden_patterns",
        "quality_gates",
        "interface_contracts",
        "performance_constraints",
        "deployment_constraints",
        "test_constraints",
    ]

    found = False
    for key in rule_keys:
        for rule in data.get(key, []):
            r_id = (
                rule.get("rule_id")
                or rule.get("principle_id")
                or rule.get("constraint_id")
                or rule.get("pattern_id")
                or rule.get("gate_id")
                or rule.get("contract_id")
            )
            if r_id == rule_id:
                # Check if already accepted
                if rule.get("accepted_by"):
                    print(
                        f"Rule {rule_id} is already accepted by "
                        f"{rule['accepted_by']} at {rule.get('accepted_at', 'N/A')}."
                    )
                    return 0

                # Set acceptance fields
                rule["accepted_by"] = accepted_by
                rule["accepted_at"] = datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat()
                found = True
                break
        if found:
            break

    if not found:
        print(
            f"Error: Rule {rule_id} not found in architecture_constraints.json.",
            file=sys.stderr,
        )
        return 1

    # Write back
    try:
        with constraints_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except Exception as exc:
        print(f"Error writing {constraints_path}: {exc}", file=sys.stderr)
        return 1

    print(
        f"Rule {rule_id} accepted by '{accepted_by}' at "
        f"{rule['accepted_at']}."
    )
    return 0


def run_doctor(project_root: Path) -> int:
    """Run governance data health checks and output a JSON report.

    Checks:
      1. evidence_refs_integrity -- each claim's evidence_refs exist in evidence index or on disk
      2. file_refs_integrity -- each claim's code_refs and test_refs exist on disk
      3. requirement_mapping -- each task's related_requirements exist in the PRD
      4. ac_mapping -- each task's related_acceptance_criteria exist in the PRD
      5. machine_rule_coverage -- architecture rules with verification_method=="machine" have no obvious checker
    """
    checks: List[Dict[str, Any]] = []

    # ---- Load governance data ----
    claims_path = project_root / ".vibetracing" / "agent_claims.json"
    task_list_path = project_root / "docs" / "task_list.json"
    prd_path = project_root / "docs" / "prd.md"
    constraints_path = project_root / "docs" / "architecture_constraints.json"
    evidence_index_path = project_root / "output" / "evidence_index.json"

    # Load claims (tolerate missing files)
    claims_data: List[Dict[str, Any]] = []
    if claims_path.exists():
        try:
            with claims_path.open("r", encoding="utf-8") as f:
                claims_data = json.load(f)
            if not isinstance(claims_data, list):
                claims_data = []
        except Exception:
            claims_data = []

    # Load tasks
    tasks_data: List[Dict[str, Any]] = []
    if task_list_path.exists():
        try:
            with task_list_path.open("r", encoding="utf-8") as f:
                tldata = json.load(f)
            tasks_data = tldata.get("tasks", []) if isinstance(tldata, dict) else []
        except Exception:
            tasks_data = []

    # Load PRD requirement and AC IDs
    prd_req_ids: Set[str] = set()
    prd_ac_ids: Set[str] = set()
    if prd_path.exists():
        try:
            from vibe_tracing.prd_parser import PrdParser
            prd_parser = PrdParser()
            prd_res = prd_parser.parse_file(prd_path)
            for req in prd_res.requirements:
                prd_req_ids.add(req.req_id)
                for ac in req.acceptance_criteria:
                    prd_ac_ids.add(ac.ac_id)
        except Exception:
            pass

    # Load architecture constraints
    constraints_data: Dict[str, Any] = {}
    if constraints_path.exists():
        try:
            with constraints_path.open("r", encoding="utf-8") as f:
                constraints_data = json.load(f)
        except Exception:
            constraints_data = {}

    # Load evidence index (optional)
    evidence_index: Dict[str, Any] = {}
    if evidence_index_path.exists():
        try:
            with evidence_index_path.open("r", encoding="utf-8") as f:
                evidence_index = json.load(f)
        except Exception:
            evidence_index = {}

    # Collect all evidence_ids from the index
    evidence_ids_in_index: Set[str] = set()
    for ev in evidence_index.get("evidences", []):
        eid = ev.get("evidence_id", "")
        if eid:
            evidence_ids_in_index.add(eid)

    # ---- Check 1: evidence_refs_integrity ----
    issues_1: List[Dict[str, Any]] = []
    for claim in claims_data:
        claim_id = claim.get("claim_id", "")
        for ref in claim.get("evidence_refs", []):
            # Check if the ref is in the evidence index
            if ref in evidence_ids_in_index:
                continue
            # Check if a file with that name exists on disk
            ref_path = project_root / ref
            if ref_path.exists():
                continue
            issues_1.append({
                "claim_id": claim_id,
                "evidence_ref": ref,
                "message": f"Evidence ref '{ref}' not found in evidence index or on disk",
            })
    checks.append({"name": "evidence_refs_integrity", "issues": issues_1})

    # ---- Check 2: file_refs_integrity ----
    issues_2: List[Dict[str, Any]] = []
    for claim in claims_data:
        claim_id = claim.get("claim_id", "")
        for ref_type in ("code_refs", "test_refs"):
            for ref in claim.get(ref_type, []):
                # Strip fragment identifiers (e.g., "#L1-L10")
                path_part = ref.split("#")[0]
                if not path_part:
                    continue
                ref_path = project_root / path_part
                if not ref_path.exists():
                    issues_2.append({
                        "claim_id": claim_id,
                        "ref_type": ref_type,
                        "ref": ref,
                        "message": f"Referenced file '{path_part}' does not exist on disk",
                    })
    checks.append({"name": "file_refs_integrity", "issues": issues_2})

    # ---- Check 3: requirement_mapping ----
    issues_3: List[Dict[str, Any]] = []
    for task in tasks_data:
        task_id = task.get("task_id", "")
        for req_id in task.get("related_requirements", []):
            if req_id not in prd_req_ids:
                issues_3.append({
                    "task_id": task_id,
                    "requirement_id": req_id,
                    "message": f"Requirement '{req_id}' referenced by task '{task_id}' not found in PRD",
                })
    checks.append({"name": "requirement_mapping", "issues": issues_3})

    # ---- Check 4: ac_mapping ----
    issues_4: List[Dict[str, Any]] = []
    for task in tasks_data:
        task_id = task.get("task_id", "")
        for ac_id in task.get("related_acceptance_criteria", []):
            if ac_id not in prd_ac_ids:
                issues_4.append({
                    "task_id": task_id,
                    "ac_id": ac_id,
                    "message": f"AC '{ac_id}' referenced by task '{task_id}' not found in PRD",
                })
    checks.append({"name": "ac_mapping", "issues": issues_4})

    # ---- Check 5: machine_rule_coverage ----
    issues_5: List[Dict[str, Any]] = []
    if constraints_data:
        rule_keys = [
            "architecture_principles",
            "module_boundaries",
            "dependency_rules",
            "data_flow_rules",
            "storage_rules",
            "error_handling_rules",
            "logging_rules",
            "security_rules",
            "technology_constraints",
            "forbidden_patterns",
            "quality_gates",
            "interface_contracts",
            "performance_constraints",
            "deployment_constraints",
            "test_constraints",
        ]
        # Collect all module_ids from module_boundaries for heuristic matching
        module_ids: Set[str] = set()
        for mod in constraints_data.get("module_boundaries", []):
            mid = mod.get("module_id", "")
            if mid:
                module_ids.add(mid)

        for key in rule_keys:
            for rule in constraints_data.get(key, []):
                if rule.get("verification_method") != "machine":
                    continue
                rule_id = (
                    rule.get("rule_id")
                    or rule.get("principle_id")
                    or rule.get("constraint_id")
                    or rule.get("pattern_id")
                    or rule.get("gate_id")
                    or rule.get("contract_id")
                    or "unknown"
                )
                # Heuristic: if the rule references a module that exists in
                # module_boundaries, assume there *may* be a checker.  Otherwise
                # flag it.  Also check for common verification keywords.
                related_modules = rule.get("related_modules", [])
                has_module_support = any(m in module_ids for m in related_modules)

                # Check for explicit checker references
                has_checker = has_module_support or bool(
                    rule.get("checker") or rule.get("verification_command")
                )

                if not has_checker:
                    issues_5.append({
                        "rule_id": rule_id,
                        "section": key,
                        "message": (
                            f"Rule '{rule_id}' in '{key}' has verification_method=machine "
                            "but no obvious checker implementation found"
                        ),
                    })
    checks.append({"name": "machine_rule_coverage", "issues": issues_5})

    # ---- Assemble report ----
    total_issues = sum(len(c["issues"]) for c in checks)
    report = {
        "checks": checks,
        "total_issues": total_issues,
    }

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def main(argv=None):
    """CLI main execution function."""
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        description="Vibe Tracing (VT) - Consistency validation framework for agent coding"
    )
    parser.add_argument(
        "--version", action="version", version=f"vibe-tracing {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="sub-command help")

    analyze_parser = subparsers.add_parser(
        "analyze", help="Analyze project consistency and compliance"
    )
    analyze_parser.add_argument(
        "--project-root",
        default=".",
        help="Path to the project workspace root (default: current working directory)",
    )
    analyze_parser.add_argument(
        "--out", help="Path to the output directory (default: <project-root>/output)"
    )
    analyze_parser.add_argument(
        "--pre-commit", action="store_true", help="Run in Git pre-commit hook mode (enables ghost code reconciliation)"
    )
    analyze_parser.add_argument(
        "--gates-only", action="store_true",
        help="Run only integrity gates (1, 2, 2.5), skip tool execution and analysis (fast mode for pre-commit)"
    )

    init_parser = subparsers.add_parser(
        "init", help="Initialize a new Vibe Tracing project with template files"
    )
    init_parser.add_argument(
        "--project-root",
        default=".",
        help="Path to the project workspace root (default: current working directory)",
    )
    init_parser.add_argument(
        "--name",
        help="Human-readable name of the project",
    )
    init_parser.add_argument(
        "--prefix",
        help="Project prefix abbreviation (e.g. CapL, VT)",
    )

    finalize_parser = subparsers.add_parser(
        "finalize", help="Finalize project config from architecture constraints"
    )
    finalize_parser.add_argument(
        "--project-root",
        default=".",
        help="Path to the project workspace root (default: current working directory)",
    )

    accept_parser = subparsers.add_parser(
        "accept", help="Accept a manual architecture constraint rule"
    )
    accept_parser.add_argument(
        "rule_id",
        help="The rule ID to accept (e.g. PRINCIPLE-VT-001)",
    )
    accept_parser.add_argument(
        "--project-root",
        default=".",
        help="Path to the project workspace root (default: current working directory)",
    )
    accept_parser.add_argument(
        "--by",
        default="human",
        help="Accepter identifier (default: 'human')",
    )

    doctor_parser = subparsers.add_parser(
        "doctor", help="Scan governance data health and report issues"
    )
    doctor_parser.add_argument(
        "--project-root",
        default=".",
        help="Path to the project workspace root (default: current working directory)",
    )

    args = parser.parse_args(argv)

    if args.command == "analyze":
        project_root = Path(args.project_root).resolve()
        if args.out:
            output_dir = Path(args.out)
            if not output_dir.is_absolute():
                output_dir = (project_root / output_dir).resolve()
        else:
            output_dir = None  # Resolved inside run_analyze from config

        return run_analyze(project_root, output_dir, is_pre_commit=args.pre_commit, gates_only=args.gates_only)
    elif args.command == "init":
        project_root = Path(args.project_root).resolve()
        return run_init(project_root, name=args.name, prefix=args.prefix)
    elif args.command == "finalize":
        project_root = Path(args.project_root).resolve()
        return run_finalize(project_root)
    elif args.command == "accept":
        project_root = Path(args.project_root).resolve()
        return run_accept(project_root, args.rule_id, accepted_by=args.by)
    elif args.command == "doctor":
        project_root = Path(args.project_root).resolve()
        return run_doctor(project_root)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
