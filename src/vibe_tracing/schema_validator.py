"""
Schema validation utility for Vibe Tracing JSON documents.

Validates JSON files and dicts against the JSON Schema contracts defined
in the schemas/ directory. This module is a pure utility layer — it does
NOT perform business analysis, gate decisions, or dashboard generation.
"""

import json
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

from jsonschema import SchemaError, ValidationError, validate

from vibe_tracing.core.enums import ErrorCode


@dataclass
class ValidationResult:
    """Result of a schema validation operation."""

    is_valid: bool
    error_code: Optional[str] = None  # Use ErrorCode enum values
    file_path: str = ""
    field_path: str = ""  # JSON pointer to the failed field, e.g. "tasks[0].task_id"
    message: str = ""
    hint: str = ""  # Human-readable fix suggestion
    errors: List["ValidationResult"] = field(
        default_factory=list
    )  # For multi-error collection


def _deque_path_to_string(path: deque) -> str:
    """Convert a jsonschema ValidationError.path deque to a readable string.

    Examples:
        deque(['tasks', 0, 'task_id']) -> 'tasks[0].task_id'
        deque(['project', 'project_id']) -> 'project.project_id'
        deque([]) -> ''
    """
    if not path:
        return ""
    parts = list(path)
    result = str(parts[0]) if parts else ""
    for part in parts[1:]:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result += f".{part}"
    return result


def _build_hint(error: ValidationError) -> str:
    """Build a human-readable fix suggestion from a ValidationError."""
    validator = error.validator
    path_str = _deque_path_to_string(error.absolute_path)
    field_label = f"Field '{path_str}'" if path_str else "Value"

    if validator == "required":
        missing = error.validator_value
        # jsonschema puts the missing property name in the message; extract it
        return f"Add the required field(s): {missing}."
    elif validator == "type":
        expected = error.validator_value
        return f"{field_label} must be of type '{expected}'."
    elif validator == "enum":
        allowed = error.validator_value
        return f"{field_label} must be one of: {allowed}."
    elif validator == "pattern":
        pattern = error.validator_value
        return f"{field_label} must match pattern: {pattern}."
    elif validator == "minLength":
        return f"{field_label} must have a minimum length of {error.validator_value}."
    elif validator == "maxLength":
        return f"{field_label} must have a maximum length of {error.validator_value}."
    elif validator == "minimum":
        return f"{field_label} must be >= {error.validator_value}."
    elif validator == "maximum":
        return f"{field_label} must be <= {error.validator_value}."
    elif validator == "additionalProperties":
        return f"Remove unexpected additional properties from {field_label}."
    else:
        return f"Fix the value at '{path_str}': {error.message}"


class SchemaValidator:
    """Validates JSON documents against Vibe Tracing JSON Schema contracts."""

    KNOWN_SCHEMAS = {
        "task_list": "task_list.schema.json",
        "agent_claims": "agent_claims.schema.json",
        "evidence_index": "evidence_index.schema.json",
        "traceability_report": "traceability_report.schema.json",
        "claude_bootstrap_manifest": "claude_bootstrap_manifest.schema.json",
        "claude_subagent_definition": "claude_subagent_definition.schema.json",
        "claude_skill_definition": "claude_skill_definition.schema.json",
        "architecture_change_proposal": "architecture_change_proposal.schema.json",
        "architecture_constraints": "architecture_constraints.schema.json",
    }

    def __init__(self, schemas_dir: Optional[Path] = None):
        """Initialize with path to schemas directory. Defaults to internal packaged schemas."""
        self.schemas_dir = schemas_dir or (Path(__file__).parent / "schemas")
        self._schema_cache: dict = {}

    def _load_schema(self, schema_name: str) -> dict:
        """Load and cache a schema by name.

        Args:
            schema_name: One of KNOWN_SCHEMAS keys.

        Returns:
            Parsed schema dict.

        Raises:
            FileNotFoundError: If the schema file does not exist.
            json.JSONDecodeError: If the schema file contains invalid JSON.
            SchemaError: If the schema itself is invalid.
        """
        if schema_name in self._schema_cache:
            return self._schema_cache[schema_name]

        schema_filename = self.KNOWN_SCHEMAS[schema_name]
        schema_path = self.schemas_dir / schema_filename
        with schema_path.open("r", encoding="utf-8") as f:
            schema = json.load(f)

        self._schema_cache[schema_name] = schema
        return schema

    def validate_file(self, file_path: Path, schema_name: str) -> ValidationResult:
        """Validate a JSON file against a named schema.

        Args:
            file_path: Path to the JSON file to validate.
            schema_name: One of KNOWN_SCHEMAS keys.

        Returns:
            ValidationResult with is_valid=True on success,
            or is_valid=False with error_code, field_path, message, hint populated.
        """
        # Step 1: Check schema_name is valid
        if schema_name not in self.KNOWN_SCHEMAS:
            known = list(self.KNOWN_SCHEMAS.keys())
            return ValidationResult(
                is_valid=False,
                error_code=ErrorCode.INVALID_INPUT,
                file_path=str(file_path),
                field_path="",
                message=f"Unknown schema name '{schema_name}'. Known schemas: {known}.",
                hint=f"Use one of the known schema names: {known}.",
            )

        # Step 2: Check file exists
        if not Path(file_path).exists():
            return ValidationResult(
                is_valid=False,
                error_code=ErrorCode.MISSING_INPUT,
                file_path=str(file_path),
                field_path="",
                message=f"File not found: {file_path}",
                hint="Check that the file path is correct and the file exists.",
            )

        # Step 3: Load and parse JSON
        try:
            with Path(file_path).open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            return ValidationResult(
                is_valid=False,
                error_code=ErrorCode.INVALID_INPUT,
                file_path=str(file_path),
                field_path="",
                message=f"Invalid JSON in file '{file_path}': {exc}",
                hint="Ensure the file contains valid JSON (check for trailing commas, missing quotes, etc.).",
            )

        # Step 4 & 5: Load schema and validate
        return self._run_validation(data, schema_name, source_label=str(file_path))

    def validate_dict(
        self,
        data: Union[dict, list],
        schema_name: str,
        source_label: str = "",
    ) -> ValidationResult:
        """Validate an already-parsed dict/list against a named schema.

        Args:
            data: The parsed JSON data to validate.
            schema_name: One of KNOWN_SCHEMAS keys.
            source_label: Used to populate file_path in results.

        Returns:
            ValidationResult with is_valid=True on success,
            or is_valid=False with error_code, field_path, message, hint populated.
        """
        # Check schema_name is valid
        if schema_name not in self.KNOWN_SCHEMAS:
            known = list(self.KNOWN_SCHEMAS.keys())
            return ValidationResult(
                is_valid=False,
                error_code=ErrorCode.INVALID_INPUT,
                file_path=source_label,
                field_path="",
                message=f"Unknown schema name '{schema_name}'. Known schemas: {known}.",
                hint=f"Use one of the known schema names: {known}.",
            )

        return self._run_validation(data, schema_name, source_label=source_label)

    def _run_validation(
        self, data: Union[dict, list], schema_name: str, source_label: str
    ) -> ValidationResult:
        """Run jsonschema validation and return a ValidationResult.

        Args:
            data: Parsed JSON data.
            schema_name: One of KNOWN_SCHEMAS keys (already validated by caller).
            source_label: Used as file_path in the result.

        Returns:
            ValidationResult.
        """
        try:
            schema = self._load_schema(schema_name)
        except (FileNotFoundError, json.JSONDecodeError, SchemaError) as exc:
            return ValidationResult(
                is_valid=False,
                error_code=ErrorCode.INVALID_INPUT,
                file_path=source_label,
                field_path="",
                message=f"Failed to load schema '{schema_name}': {exc}",
                hint="Ensure the schema file exists and is valid JSON Schema.",
            )

        try:
            validate(instance=data, schema=schema)
        except ValidationError as exc:
            field_path = _deque_path_to_string(exc.absolute_path)
            hint = _build_hint(exc)
            custom_hint = self.resolve_field_hint(
                data=data,
                schema_name=schema_name,
                absolute_path=list(exc.absolute_path),
                validator=exc.validator,
                message=exc.message,
            )
            if custom_hint:
                hint = f"【修复指南】{custom_hint}"
            return ValidationResult(
                is_valid=False,
                error_code=ErrorCode.SCHEMA_VIOLATION,
                file_path=source_label,
                field_path=field_path,
                message=exc.message,
                hint=hint,
            )

        return ValidationResult(is_valid=True, file_path=source_label)

    def resolve_field_hint(
        self,
        data: Union[dict, list],
        schema_name: str,
        absolute_path: list,
        validator: str,
        message: str = "",
    ) -> Optional[str]:
        """Extract dynamic field hint from the template data in the JSON structure."""
        field_name = None
        if validator == "required":
            match = re.search(r"'([^']+)' is a required property", message)
            if match:
                field_name = match.group(1)
        else:
            if absolute_path:
                field_name = str(absolute_path[-1])

        if not field_name:
            return None

        # 1. Special case: data itself is a list and absolute_path is empty or points to a list element
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "__field_hints__" in item:
                    hint = item["__field_hints__"].get(field_name)
                    if hint:
                        return hint

        # 2. Determine container path where the field is expected to live
        if validator == "required":
            container_path = absolute_path
        else:
            container_path = absolute_path[:-1] if absolute_path else []

        # 3. Helper to walk up the ancestor chain of container paths
        curr_path = list(container_path)
        while True:
            # Resolve the container at the current path level
            curr_container = data
            valid_path = True
            for p in curr_path:
                try:
                    if isinstance(curr_container, list) and isinstance(p, int):
                        curr_container = curr_container[p]
                    elif isinstance(curr_container, dict):
                        curr_container = curr_container[p]
                    else:
                        valid_path = False
                        break
                except (IndexError, KeyError):
                    valid_path = False
                    break

            if valid_path:
                # Case A: If container is a dict, check its __field_hints__
                if isinstance(curr_container, dict):
                    hints = curr_container.get("__field_hints__", {})
                    if isinstance(hints, dict) and field_name in hints:
                        return hints[field_name]

                # Case B: If container's parent is a list, check sibling items in that list (homogeneous array items)
                if curr_path:
                    parent_path = curr_path[:-1]
                    parent = data
                    for p in parent_path:
                        try:
                            if isinstance(parent, list) and isinstance(p, int):
                                parent = parent[p]
                            elif isinstance(parent, dict):
                                parent = parent[p]
                            else:
                                break
                        except (IndexError, KeyError):
                            break

                    if isinstance(parent, list):
                        for item in parent:
                            if isinstance(item, dict) and "__field_hints__" in item:
                                hints = item["__field_hints__"]
                                if isinstance(hints, dict) and field_name in hints:
                                    return hints[field_name]

            if not curr_path:
                break
            curr_path.pop()

        return None

