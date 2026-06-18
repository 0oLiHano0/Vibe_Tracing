"""
Init command -- initialize a Vibe Tracing project with template files.
"""

import json
import sys
import time
import uuid
from pathlib import Path
import importlib.resources as pkg_resources
from typing import Optional


def run_init(project_root: Path, name: Optional[str] = None, prefix: Optional[str] = None) -> int:
    """Initialize a Vibe Tracing project by creating directories and template files."""
    try:
        # Initialize operational logger (safe: if it fails, init continues)
        vt_logger = None
        try:
            from vibe_tracing.infra.operational_logger import OperationalLogger
            vt_logger = OperationalLogger.init(
                run_id=f"INIT-{uuid.uuid4()}",
                project_root=project_root,
            )
            vt_logger.info("run_start", "Init command started",
                           project_root=str(project_root), name=name, prefix=prefix)
        except Exception:
            vt_logger = None

        _run_start_t = time.perf_counter()
        _files_created: list[str] = []
        _files_skipped: list[str] = []

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
            _files_skipped.append(".vibetracing/config.json")
            if vt_logger:
                vt_logger.debug("init_step", "Skipped existing config.json",
                                file=".vibetracing/config.json")
            try:
                with config_path.open("r", encoding="utf-8") as f:
                    config_data = json.load(f)
                config_name = config_data.get("project_name", resolved_name)
                config_prefix = config_data.get("project_prefix", resolved_prefix)
                config_project_id = config_data.get("project_id", f"PROJECT-{config_prefix}")
            except Exception as exc:
                print(f"Error loading existing config.json: {exc}", file=sys.stderr)
                if vt_logger:
                    vt_logger.exception("init_error", "Failed to load existing config.json",
                                        exc=exc)
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

        # Create claims directory structure
        claims_dir = project_root / ".vibetracing" / "claims"
        claims_archive_dir = claims_dir / "archive"
        for d in [claims_dir, claims_archive_dir]:
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                print(f"Created directory: {d.relative_to(project_root)}")

        # 3. Write ALL template files except config.json first
        # Note: claims are now stored as individual CLAIM-*.json files, not current.json
        other_files = {
            "docs/task_list.json": render_template(task_list_text),
            "docs/architecture_constraints.json": render_template(arch_text),
            "docs/prd.md": render_template(prd_text),
            ".vibetracing/prompts/prd_analysis.md": render_template(prd_analysis_text),
        }

        for rel_path, content in other_files.items():
            file_path = project_root / rel_path
            if file_path.exists():
                print(f"Skipped existing file: {rel_path}")
                _files_skipped.append(rel_path)
                if vt_logger:
                    vt_logger.debug("init_step", f"Skipped existing {rel_path}",
                                    file=rel_path)
            else:
                _t_step = time.perf_counter()
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with file_path.open("w", encoding="utf-8") as f:
                    f.write(content)
                print(f"Created file: {rel_path}")
                _files_created.append(rel_path)
                if vt_logger:
                    vt_logger.info("init_step", f"Created {rel_path}",
                                   file=rel_path,
                                   duration_ms=int((time.perf_counter() - _t_step) * 1000))

        # 4. Write config.json LAST (if not exist) — prevents stale config on partial failure
        if not config_path.exists():
            _t_step = time.perf_counter()
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_content = render_template(config_text)
            with config_path.open("w", encoding="utf-8") as f:
                f.write(config_content)
            print("Created file: .vibetracing/config.json")
            _files_created.append(".vibetracing/config.json")
            if vt_logger:
                vt_logger.info("init_step", "Created config.json",
                               file=".vibetracing/config.json",
                               duration_ms=int((time.perf_counter() - _t_step) * 1000))

        # 5. Install Git pre-commit hook (V4)
        git_hooks_dir = project_root / ".git" / "hooks"
        if git_hooks_dir.exists():
            pre_commit_path = git_hooks_dir / "pre-commit"
            if not pre_commit_path.exists():
                _t_step = time.perf_counter()
                python_path = sys.executable
                hook_script = f'#!/bin/sh\nset -e\n# Vibe Tracing Git Guard\n"{python_path}" -m vibe_tracing analyze --pre-commit\n'
                pre_commit_path.write_text(hook_script)
                pre_commit_path.chmod(0o755)
                print("Installed Git pre-commit hook (vibe_tracing analyze --pre-commit)")
                if vt_logger:
                    vt_logger.info("init_step", "Installed git pre-commit hook",
                                   file=".git/hooks/pre-commit",
                                   duration_ms=int((time.perf_counter() - _t_step) * 1000))
            else:
                print("Skipped Git pre-commit hook: file already exists.")
                if vt_logger:
                    vt_logger.debug("init_step", "Skipped existing git pre-commit hook",
                                    file=".git/hooks/pre-commit")

        print("Vibe Tracing initialization completed successfully.")
        if vt_logger:
            total_duration_ms = int((time.perf_counter() - _run_start_t) * 1000)
            vt_logger.info("run_end", "Init command completed",
                           total_duration_ms=total_duration_ms,
                           files_created=len(_files_created),
                           files_skipped=len(_files_skipped),
                           created=_files_created,
                           skipped=_files_skipped)
        return 0
    except Exception as exc:
        print(f"Error during initialization: {exc}", file=sys.stderr)
        if vt_logger:
            vt_logger.exception("init_fatal", "Init command failed with exception",
                                exc=exc)
        return 1
