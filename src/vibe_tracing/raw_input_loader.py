"""
Raw Input Loader for Vibe Tracing.

IMPORTANT: This module is a PURE file-loading layer.
It does NOT make any governance, gate, coverage, or risk decisions.
It only reads files and reports their load status.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from vibe_tracing.core.enums import ErrorCode


@dataclass
class InputFileRecord:
    """Record of a single input file's load result."""

    file_key: str  # e.g. "prd", "task_list", "agent_claims"
    file_path: str  # absolute or relative path
    is_required: bool
    status: str  # "ok", "missing", "parse_error", "read_error"
    error_code: Optional[str] = None  # ErrorCode value if failed
    error_message: str = ""
    content: Optional[Any] = None  # parsed content (dict, list, or str for md)
    sha256_hash: Optional[str] = None  # SHA-256 of raw file bytes


@dataclass
class RawInputManifest:
    """Summary of all attempted raw input loads."""

    inputs_used: List[InputFileRecord] = field(default_factory=list)
    has_required_errors: bool = False  # True if any required file failed
    error_count: int = 0
    tool_report_files: List[str] = field(default_factory=list)


class RawInputLoader:
    """Loads all raw input files for a Vibe Tracing analysis run.

    IMPORTANT: This loader does NOT make any governance, gate, coverage, or risk decisions.
    It only reads files and reports their load status.
    """

    REQUIRED_FILES = {
        "prd": "docs/prd.md",
    }

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.config_data = self._load_config()

    def _load_config(self) -> dict:
        config_path = self.project_root / ".vibetracing/config.json"
        if config_path.exists():
            try:
                with config_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def get_path(self, key: str) -> Path:
        """Resolve absolute path for a key with config check and defaults fallback."""
        # 1. Check config.json first
        paths = self.config_data.get("paths", {})
        if key in paths:
            return self.project_root / paths[key]

        # 2. Fall back to standard defaults
        defaults = {
            "prd": "docs/prd.md",
            "architecture_constraints": "docs/architecture_constraints.json",
            "task_list": "docs/task_list.json",
            "agent_claims": ".vibetracing/claims/current.json",
            "output_dir": "output",
        }
        fallback_rel = defaults.get(key)
        if not fallback_rel:
            raise ValueError(f"Unknown path key: {key}")
        resolved = self.project_root / fallback_rel
        return resolved

    def load(self) -> RawInputManifest:
        """
        Load all required and optional input files.

        Returns a RawInputManifest. Never raises exceptions — all errors
        are captured in InputFileRecord entries.
        """
        manifest = RawInputManifest()

        # Load PRD (always required at loader level)
        prd_path = self.get_path("prd")
        prd_record = self._load_file("prd", prd_path, is_required=True)
        manifest.inputs_used.append(prd_record)
        if prd_record.status != "ok":
            manifest.has_required_errors = True
            manifest.error_count += 1

        # Load other governance files (always optional at loader level)
        optional_keys = ["architecture_constraints", "task_list", "agent_claims"]
        for file_key in optional_keys:
            resolved_path = self.get_path(file_key)
            record = self._load_file(file_key, resolved_path, is_required=False)
            manifest.inputs_used.append(record)
            if record.status not in ("ok", "missing"):
                manifest.error_count += 1

        # Populate tool report files
        tool_reports_dir = self.project_root / ".vibetracing" / "tool_reports"
        if tool_reports_dir.is_dir():
            for f in sorted(tool_reports_dir.glob("*.json")):
                manifest.tool_report_files.append(str(f))

        return manifest


    def _load_file(
        self, file_key: str, abs_path: Path, is_required: bool
    ) -> InputFileRecord:
        """
        Load a single file. For .json files, parse JSON. For .md files, read as text.
        Returns an InputFileRecord with status and content.
        """
        path_str = str(abs_path)

        if not abs_path.exists():
            error_code = ErrorCode.MISSING_INPUT.value if is_required else None
            return InputFileRecord(
                file_key=file_key,
                file_path=path_str,
                is_required=is_required,
                status="missing",
                error_code=error_code,
                error_message=f"File not found: {path_str}" if is_required else "",
            )

        try:
            raw_bytes = abs_path.read_bytes()
            file_hash = hashlib.sha256(raw_bytes).hexdigest()
            raw_text = raw_bytes.decode("utf-8")
        except Exception as exc:
            return InputFileRecord(
                file_key=file_key,
                file_path=path_str,
                is_required=is_required,
                status="read_error",
                error_code=ErrorCode.INVALID_INPUT.value,
                error_message=f"Could not read file: {exc}",
            )

        # Parse according to file extension
        suffix = abs_path.suffix.lower()
        if suffix == ".json":
            try:
                content = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                return InputFileRecord(
                    file_key=file_key,
                    file_path=path_str,
                    is_required=is_required,
                    status="parse_error",
                    error_code=ErrorCode.INVALID_INPUT.value,
                    error_message=f"JSON parse error: {exc}",
                )
        else:
            # Treat all non-JSON files (e.g., .md) as plain text
            content = raw_text

        return InputFileRecord(
            file_key=file_key,
            file_path=path_str,
            is_required=is_required,
            status="ok",
            content=content,
            sha256_hash=file_hash,
        )

