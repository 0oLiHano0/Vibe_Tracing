"""
Validator for Claude Code bootstrap configuration files in Vibe Tracing.

Validates schemas, files presence, and governance checks (like researcher having edit skills).
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import json

from vibe_tracing.schema_validator import SchemaValidator


class ClaudeBootstrapValidator:
    """Validates Claude Code bootstrap manifest, subagent, and skill definitions."""

    def __init__(
        self, project_root: Path, schema_validator: Optional[SchemaValidator] = None
    ) -> None:
        self.project_root = Path(project_root)
        self.schemas_dir = self.project_root / "schemas"
        if not self.schemas_dir.is_dir():
            self.schemas_dir = Path(__file__).parent / "schemas"
        self.schema_validator = schema_validator or SchemaValidator(self.schemas_dir)

        from vibe_tracing.raw_input_loader import RawInputLoader

        raw_loader = RawInputLoader(self.project_root)
        self.bootstrap_dir = raw_loader.get_path("claude_bootstrap")

    def _resolve_path(self, relative_path: str) -> Path:
        """Resolve definition file path relative to bootstrap folder or project root."""
        # Try relative to project root first
        path_proj = self.project_root / relative_path
        if path_proj.exists():
            return path_proj
        # Try relative to bootstrap directory
        path_boot = self.bootstrap_dir / relative_path
        if path_boot.exists():
            return path_boot
        # Return path relative to project root as default
        return path_proj

    def validate(self) -> Dict[str, Any]:
        """
        Validate all bootstrap configuration files.

        Returns:
            A dict with keys:
                "is_valid": bool
                "errors": list of error strings
                "warnings": list of warning strings
                "manifest": parsed manifest dict or None
                "subagents": dict of subagent_id -> subagent definition dict
                "skills": dict of skill_id -> skill definition dict
        """
        errors: List[str] = []
        warnings: List[str] = []
        manifest_data: Optional[Dict[str, Any]] = None
        subagents: Dict[str, Dict[str, Any]] = {}
        skills: Dict[str, Dict[str, Any]] = {}

        manifest_path = self.bootstrap_dir / "bootstrap_manifest.json"
        if not manifest_path.exists():
            errors.append(
                f"Claude Code bootstrap manifest not found at: {manifest_path}"
            )
            return {
                "is_valid": False,
                "errors": errors,
                "warnings": warnings,
                "manifest": None,
                "subagents": subagents,
                "skills": skills,
            }

        # 1. Validate manifest file schema
        res = self.schema_validator.validate_file(
            manifest_path, "claude_bootstrap_manifest"
        )
        if not res.is_valid:
            errors.append(
                f"Bootstrap manifest schema violation: {res.message} at '{res.field_path}'"
            )
            return {
                "is_valid": False,
                "errors": errors,
                "warnings": warnings,
                "manifest": None,
                "subagents": subagents,
                "skills": skills,
            }

        try:
            with manifest_path.open("r", encoding="utf-8") as f:
                manifest_data = json.load(f)
        except Exception as exc:
            errors.append(f"Failed to read bootstrap manifest: {exc}")
            return {
                "is_valid": False,
                "errors": errors,
                "warnings": warnings,
                "manifest": None,
                "subagents": subagents,
                "skills": skills,
            }

        # 2. Validate each subagent definition
        manifest_subagents = manifest_data.get("subagents", [])
        for sa in manifest_subagents:
            sa_id = sa.get("id")
            def_file = sa.get("definition_file", "")
            sa_path = self._resolve_path(def_file)

            if not sa_path.exists():
                errors.append(f"Subagent definition file not found: {def_file}")
                continue

            # Schema validate subagent
            sa_res = self.schema_validator.validate_file(
                sa_path, "claude_subagent_definition"
            )
            if not sa_res.is_valid:
                errors.append(
                    f"Subagent '{sa_id}' definition schema violation: {sa_res.message} at '{sa_res.field_path}'"
                )
                continue

            try:
                with sa_path.open("r", encoding="utf-8") as f:
                    subagents[sa_id] = json.load(f)
            except Exception as exc:
                errors.append(
                    f"Failed to read subagent definition for '{sa_id}': {exc}"
                )

        # 3. Validate each skill definition
        manifest_skills = manifest_data.get("skills", [])
        for sk in manifest_skills:
            sk_id = sk.get("id")
            def_file = sk.get("definition_file", "")
            sk_path = self._resolve_path(def_file)

            if not sk_path.exists():
                errors.append(f"Skill definition file not found: {def_file}")
                continue

            # Schema validate skill
            sk_res = self.schema_validator.validate_file(
                sk_path, "claude_skill_definition"
            )
            if not sk_res.is_valid:
                errors.append(
                    f"Skill '{sk_id}' definition schema violation: {sk_res.message} at '{sk_res.field_path}'"
                )
                continue

            try:
                with sk_path.open("r", encoding="utf-8") as f:
                    skills[sk_id] = json.load(f)
            except Exception as exc:
                errors.append(f"Failed to read skill definition for '{sk_id}': {exc}")

        if errors:
            return {
                "is_valid": False,
                "errors": errors,
                "warnings": warnings,
                "manifest": manifest_data,
                "subagents": subagents,
                "skills": skills,
            }

        # 4. Semantic / Governance rules check
        # Rule A: Subagents can only request allowed skills defined in the manifest
        manifest_skill_ids = {sk.get("id") for sk in manifest_skills}
        for sa_id, sa_def in subagents.items():
            allowed_skills = sa_def.get("allowed_skills", [])
            for skill_id in allowed_skills:
                if skill_id not in manifest_skill_ids:
                    errors.append(
                        f"Subagent '{sa_id}' requests skill '{skill_id}' which is not registered in manifest."
                    )
                if skill_id not in skills:
                    errors.append(
                        f"Subagent '{sa_id}' requests skill '{skill_id}' whose definition file is missing or invalid."
                    )

        # Rule B: Conflicting skills (e.g., Codebase Researcher subagent must not have write/edit permissions)
        for sa_id, sa_def in subagents.items():
            role = sa_def.get("role", "").lower()
            allowed_skills = sa_def.get("allowed_skills", [])

            # Check if researcher has edit_file or write skills
            if "researcher" in role or sa_id == "SUBAGENT-VT-001":
                # Check if any skill in allowed_skills represents write/edit
                # edit_file skill is typically SKILL-VT-002
                for sk_id in allowed_skills:
                    sk_def = skills.get(sk_id, {})
                    sk_name = sk_def.get("name", "").lower()
                    if (
                        "edit" in sk_name
                        or "write" in sk_name
                        or sk_id == "SKILL-VT-002"
                    ):
                        warnings.append(
                            f"Governance warning: Researcher subagent '{sa_id}' has write permission via skill '{sk_id}' ({sk_name})."
                        )

        is_valid = len(errors) == 0
        return {
            "is_valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "manifest": manifest_data,
            "subagents": subagents,
            "skills": skills,
        }
