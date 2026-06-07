"""
CLI Entrypoint for Vibe Tracing.

Provides the `analyze` command to load raw inputs, parse requirements,
validate schemas, run analyzers, generate risks, evaluate quality gates,
and output the evidence index, traceability report, and run metadata.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
import importlib.resources as pkg_resources

from typing import Dict, List, Optional, Tuple, Union

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
                hook_script = f'#!/bin/sh\nset -e\n# Vibe Tracing Git Guard\n"{python_path}" -m vibe_tracing analyze --pre-commit --gates-only\n'
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

        tool_categories = list(ltm[language].keys())

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
    if task_list_record and task_list_record.status == "ok":
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

    if constraints_record and constraints_record.status == "ok":
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

    if claims_record and claims_record.status == "ok":
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

    # Parse PRD
    prd_parser = PrdParser()
    prd_res = prd_parser.parse_file(Path(prd_record.file_path))
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


def _run_integrity_gates(
    ctx: UnifiedContext,
    is_pre_commit: bool,
    project_root: Path,
    raw_loader: RawInputLoader,
    records_dict: Dict,
    config_prefix: str,
    prd_res: object,
) -> Optional[int]:
    """Run integrity gates 1, 1b, 1c, 2, and 2.5.

    Returns exit code (1) if any gate fails, or None if all pass.
    """
    import hashlib

    constraints_record = records_dict.get("architecture_constraints")
    prd_record = records_dict.get("prd")

    # Gate 1: Anti-Tampering (Architecture Baseline Check)
    if constraints_record and constraints_record.status == "ok":
        computed_hash = hashlib.sha256(Path(constraints_record.file_path).read_bytes()).hexdigest()
        stored_hash = raw_loader.config_data.get("architecture_constraints_hash")
        if stored_hash and stored_hash != computed_hash:
            print(
                "FATAL: 架构基线已被篡改！\n"
                f"预期 Hash: {stored_hash[:12]}...\n"
                f"实际 Hash: {computed_hash[:12]}...\n"
                "请恢复文件，或通过 `vt finalize` 提交合法的架构变更。",
                file=sys.stderr
            )
            return 1

    # Gate 1b: PRD drift detection
    prd_path = raw_loader.get_path("prd")
    if prd_path and Path(prd_path).exists():
        computed_p_hash = hashlib.sha256(Path(prd_path).read_bytes()).hexdigest()
        stored_p_hash = raw_loader.config_data.get("prd_hash")
        if stored_p_hash and stored_p_hash != computed_p_hash:
            print(
                "WARNING: PRD 已从基线漂移！\n"
                f"预期 Hash: {stored_p_hash[:12]}...\n"
                f"实际 Hash: {computed_p_hash[:12]}...\n"
                "将重新验证 PRD ↔ Architecture 映射关系。",
                file=sys.stderr
            )

    # Gate 1c: PRD ↔ Architecture mapping validation
    if constraints_record and constraints_record.status == "ok" and prd_record and prd_record.status == "ok":
        from vibe_tracing.prd_arch_validator import validate_prd_architecture_mapping
        if prd_res.is_valid:
            mapping_result = validate_prd_architecture_mapping(
                prd_res.requirements,
                constraints_record.content,
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

    # Gate 2: Ghost Code Reconciliation (pre-commit only)
    if is_pre_commit:
        from vibe_tracing.ghost_code_reconciler import GhostCodeReconciler
        reconciler = GhostCodeReconciler(project_root)
        success, error_msg = reconciler.reconcile()
        if not success:
            print(error_msg, file=sys.stderr)
            return 1

    # Gate 2.5: AC Freshness Detection (pre-commit only)
    if is_pre_commit:
        from vibe_tracing.ac_freshness_checker import AcFreshnessChecker
        freshness_checker = AcFreshnessChecker(project_root)
        success, warning_msg = freshness_checker.check()
        if warning_msg:
            print(warning_msg, file=sys.stderr)
        if not success:
            return 1

    # Gate 3: Semantic Audit (pre-commit only)
    if is_pre_commit:
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

    from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine

    # Pre-flight dependency check
    required_binaries = set()
    lang_tools = ltm.get(config_language, {})
    for category in config_validation_tools:
        tool_cfg = lang_tools.get(category, {})
        tool_name = tool_cfg.get("tool")
        if tool_name:
            required_binaries.add(tool_name)

    missing = sorted(t for t in required_binaries if not shutil.which(t))
    if missing:
        from vibe_tracing.tool_evidence_adapter import ToolEvidenceCandidate
        blocked_evidence = []
        for tool_name in missing:
            blocked_evidence.append(ToolEvidenceCandidate(
                source_type="tool",
                source_path=f"<dependency:{tool_name}>",
                covers=[],
                status="blocked",
                error_code="tool_not_found",
                stderr=f"Tool '{tool_name}' is not installed. Install with: pip install {tool_name}",
                details={"error_type": "tool_not_found", "tool": tool_name},
            ))
        print(f"\n[AI Agent Repair Guide]", file=sys.stderr)
        print(
            f"VT depends on tools that are missing in the environment: {', '.join(missing)}",
            file=sys.stderr,
        )
        print(f"Action Required: pip install {' '.join(missing)}", file=sys.stderr)
        return blocked_evidence

    engine = ToolExecutionEngine(
        language_tool_matrix=ltm,
        language=config_language,
        validation_tools=config_validation_tools,
        project_root=project_root,
    )

    # Collect paths to execute tools against
    execution_paths: List[str] = []
    for claim in claims_list:
        for ref in claim.test_refs:
            path_only = ref.split("#")[0]
            if path_only and path_only not in execution_paths:
                execution_paths.append(path_only)
        for ref in claim.code_refs:
            path_only = ref.split("#")[0]
            if path_only and path_only not in execution_paths:
                execution_paths.append(path_only)

    if task_res:
        for task in task_res.tasks:
            for ref in task.evidence_refs if hasattr(task, 'evidence_refs') else []:
                path_only = ref.split("#")[0]
                if path_only and path_only not in execution_paths:
                    execution_paths.append(path_only)

    if not execution_paths:
        return []

    print(f"Executing validation tools for {len(execution_paths)} path(s)...")
    tool_evidence_candidates = engine.execute_all(execution_paths)
    executed_count = len(tool_evidence_candidates)
    blocked_count = sum(1 for c in tool_evidence_candidates if c.error_code is not None)

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


def _run_analyzers(
    ctx: UnifiedContext,
    evidence_list: list,
    project_root: Path,
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
    if constraints_path.exists():
        compliance_checker = ArchitectureComplianceChecker(
            project_root, constraints_path=constraints_path
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

    return merged_gaps, final_risks, compliance_res, claim_res, req_res


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
) -> int:
    """Run MergeGateEngine, output all reports, and return exit code."""
    prd_res = ctx.prd
    manifest = ctx.manifest
    claims_list = ctx.claims_list
    task_res = ctx.task_result

    # Merge Gate Engine
    gate_engine = MergeGateEngine(project_root)
    gate_res = gate_engine.evaluate(
        merged_gaps, final_risks, compliance_res, prd_status=prd_res.status
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
    }

    # Build and save traceability report
    report_builder = TraceabilityReportBuilder(project_root)
    report_path = output_dir / "traceability_report.json"
    try:
        report_doc = report_builder.build(report_doc, output_path=report_path)
    except Exception as exc:
        print(f"Error building traceability report: {exc}", file=sys.stderr)
        raise _GateBlocked(1)

    # Write run_metadata.json
    run_id = report_doc.get("run_id")
    project_id = report_doc.get("project_id")
    scan_time = report_doc.get("scan_time")

    def rel_path_str(p: Path) -> str:
        try:
            if p.is_absolute() and (project_root in p.parents or p == project_root):
                return str(p.relative_to(project_root))
        except Exception:
            pass
        return str(p)

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

    exit_code = 2 if gate_decision == "blocked" else 0

    # Build evidence index path (already written by caller)
    index_path = output_dir / "evidence_index.json"

    # Render dashboard
    dashboard_path = output_dir / "dashboard.html"
    try:
        renderer = DashboardRenderer(project_root)
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

    metadata_path = output_dir / "run_metadata.json"
    try:
        with metadata_path.open("w", encoding="utf-8") as f:
            json.dump(metadata_doc, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"Error writing run metadata: {exc}", file=sys.stderr)
        raise _GateBlocked(1)

    # Print summary
    print(f"Analysis complete. Gate decision: {gate_decision.upper()}")
    for reason in gate_res["reasons"]:
        print(f"- {reason}")

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

    # Extract raw task_list dict from manifest
    records_dict_all = {r.file_key: r for r in manifest.inputs_used}
    task_list_record = records_dict_all.get("task_list")
    task_list_raw = task_list_record.content if task_list_record and task_list_record.status == "ok" else {"tasks": []}

    print(render_reflection_prompts(
        gate_decision=gate_decision,
        gaps=merged_gaps,
        risks=final_risks,
        task_list=task_list_raw,
        affected_files=affected_files,
        compliance_result=compliance_res,
    ))

    return exit_code


def run_analyze(project_root: Path, output_dir: Path, is_pre_commit: bool = False, gates_only: bool = False) -> int:
    """
    Execute the full Vibe Tracing analysis pipeline.

    Args:
        project_root: The workspace root path.
        output_dir: The target output directory.
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
        records_dict = {r.file_key: r for r in ctx.manifest.inputs_used}

        exit_code = _run_integrity_gates(
            ctx, is_pre_commit, project_root, raw_loader,
            records_dict, config_prefix, prd_res,
        )
        if exit_code is not None:
            return exit_code

        if gates_only:
            # Render reflection prompts with available data (no analysis results)
            from vibe_tracing.reflection_prompts import render_reflection_prompts
            affected_files_gs: List[str] = []
            for claim in ctx.claims_list:
                for ref in (claim.code_refs if hasattr(claim, "code_refs") else claim.get("code_refs", [])):
                    path = ref.split("#")[0]
                    if path and path not in affected_files_gs:
                        affected_files_gs.append(path)
            task_list_gs: Dict[str, Any] = {"tasks": []}
            if ctx.task_result and ctx.task_result.tasks:
                task_list_gs = {
                    "tasks": [
                        {"task_id": t.task_id, "related_requirements": t.related_requirements,
                         "related_acceptance_criteria": t.related_acceptance_criteria,
                         "category": getattr(t, "category", None)}
                        for t in ctx.task_result.tasks
                    ]
                }
            print(render_reflection_prompts(
                gate_decision="pass", gaps=[], risks=[],
                task_list=task_list_gs, affected_files=affected_files_gs,
            ))
            print("Gates-only mode: integrity gates passed. Skipping tool execution.")
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

        merged_gaps, final_risks, compliance_res, claim_res, req_res = _run_analyzers(
            ctx, evidence_list, project_root,
        )

        return _evaluate_and_output(
            ctx, merged_gaps, final_risks, compliance_res,
            output_dir, evidences_index, claim_res, req_res,
            project_root, is_draft,
        )

    except _GateBlocked as exc:
        return exc.exit_code
    except Exception as exc:
        print(f"Unexpected error running analyze command: {exc}", file=sys.stderr)
        return 1


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

    args = parser.parse_args(argv)

    if args.command == "analyze":
        project_root = Path(args.project_root).resolve()
        raw_loader = RawInputLoader(project_root)
        if args.out:
            output_dir = Path(args.out)
            if not output_dir.is_absolute():
                output_dir = (project_root / output_dir).resolve()
        else:
            output_dir = raw_loader.get_path("output_dir").resolve()

        return run_analyze(project_root, output_dir, is_pre_commit=args.pre_commit, gates_only=args.gates_only)
    elif args.command == "init":
        project_root = Path(args.project_root).resolve()
        return run_init(project_root, name=args.name, prefix=args.prefix)
    elif args.command == "finalize":
        project_root = Path(args.project_root).resolve()
        return run_finalize(project_root)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
