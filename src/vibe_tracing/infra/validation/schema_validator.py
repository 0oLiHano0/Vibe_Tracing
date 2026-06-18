"""
Schema 校验工具 — 用于 Vibe Tracing 的 JSON 文档校验。

根据 schemas/ 目录下的 JSON Schema 契约，校验 JSON 文件和字典。
本模块是纯工具层，不执行业务分析、门禁判定或 Dashboard 生成。
"""

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

from jsonschema import SchemaError, ValidationError, validate

from vibe_tracing.infra.enums import ErrorCode
from vibe_tracing.infra.operational_logger import OperationalLogger


@dataclass
class ValidationResult:
    """Schema 校验结果。"""

    is_valid: bool
    error_code: Optional[str] = None  # 使用 ErrorCode 枚举值
    file_path: str = ""
    field_path: str = ""  # JSON 指针，指向校验失败的字段，如 "tasks[0].task_id"
    message: str = ""
    hint: str = ""  # 人类可读的修复建议
    errors: List["ValidationResult"] = field(
        default_factory=list
    )  # 用于收集多条校验错误


def _deque_path_to_string(path: deque) -> str:
    """将 jsonschema.ValidationError.path 的 deque 转换为可读字符串。

    示例:
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
    """从 ValidationError 构建人类可读的修复建议。"""
    validator = error.validator
    path_str = _deque_path_to_string(error.absolute_path)
    field_label = f"字段 '{path_str}'" if path_str else "值"

    # 优先尝试从 schema description 中提取中文修复指南
    if validator == "pattern":
        if path_str.endswith("task_id"):
            return "【修复指南】任务ID，必须符合正则格式"
        elif path_str.endswith("related_task"):
            return "【修复指南】关联任务ID，必须符合正则格式"

    desc = None
    if isinstance(error.schema, dict):
        desc = error.schema.get("description")

    # required 校验失败时，error.schema 指向父对象，
    # 需要从 error.instance 中找到缺失的字段并提取其 description
    if not desc and validator == "required" and isinstance(error.schema, dict):
        if isinstance(error.instance, dict):
            for field_name in error.validator_value:
                if field_name not in error.instance:
                    prop_schema = error.schema.get("properties", {}).get(field_name, {})
                    desc = prop_schema.get("description")
                    if desc:
                        break

    if desc:
        from vibe_tracing.infra.validation import ids
        desc_resolved = desc.replace("{PROJECT_PREFIX}", ids.get_project_prefix())
        return f"【修复指南】{desc_resolved}"

    # 兜底：英文修复建议
    if validator == "required":
        missing = error.validator_value
        return f"请添加必填字段: {missing}。"
    elif validator == "type":
        expected = error.validator_value
        return f"{field_label} 必须为类型 '{expected}'。"
    elif validator == "enum":
        allowed = error.validator_value
        return f"{field_label} 必须为以下值之一: {allowed}。"
    elif validator == "pattern":
        pattern = error.validator_value
        return f"{field_label} 必须匹配正则: {pattern}。"
    elif validator == "minLength":
        return f"{field_label} 最小长度为 {error.validator_value}。"
    elif validator == "maxLength":
        return f"{field_label} 最大长度为 {error.validator_value}。"
    elif validator == "minimum":
        return f"{field_label} 必须 >= {error.validator_value}。"
    elif validator == "maximum":
        return f"{field_label} 必须 <= {error.validator_value}。"
    elif validator == "additionalProperties":
        return f"请移除 {field_label} 中的多余属性。"
    else:
        return f"请修复 '{path_str}' 处的值: {error.message}"


class SchemaValidator:
    """根据 Vibe Tracing JSON Schema 契约校验 JSON 文档。"""

    KNOWN_SCHEMAS = {
        "task_list": "task_list.schema.json",
        "agent_claims": "agent_claims.schema.json",
        "test_results": "test_results.schema.json",
        "coverage_reports": "coverage_reports.schema.json",
        "traceability_report": "traceability_report.schema.json",
        "architecture_constraints": "architecture_constraints.schema.json",
        "human_decisions": "human_decisions.schema.json",
    }

    def __init__(self, schemas_dir: Optional[Path] = None):
        """初始化，接收 schema 文件目录路径。默认使用包内自带的 schemas。"""
        self.schemas_dir = schemas_dir or (Path(__file__).parent / "schemas")
        self._schema_cache: dict = {}

    def _load_schema(self, schema_name: str) -> dict:
        """按名称加载并缓存 schema。

        Args:
            schema_name: KNOWN_SCHEMAS 中的键名。

        Returns:
            解析后的 schema 字典。

        Raises:
            FileNotFoundError: schema 文件不存在。
            json.JSONDecodeError: schema 文件包含无效 JSON。
            SchemaError: schema 本身格式不合法。
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
        """校验 JSON 文件是否符合指定 schema。

        Args:
            file_path: 待校验的 JSON 文件路径。
            schema_name: KNOWN_SCHEMAS 中的键名。

        Returns:
            校验成功返回 is_valid=True，失败时返回 error_code、field_path、message、hint。
        """
        # 步骤 1：校验 schema_name 是否合法
        if schema_name not in self.KNOWN_SCHEMAS:
            known = list(self.KNOWN_SCHEMAS.keys())
            OperationalLogger.get().warning("unknown_schema_name", f"Unknown schema name '{schema_name}'",
                schema_name=schema_name,
                source_label=str(file_path),
            )
            return ValidationResult(
                is_valid=False,
                error_code=ErrorCode.INVALID_INPUT,
                file_path=str(file_path),
                field_path="",
                message=f"Unknown schema name '{schema_name}'. Known schemas: {known}.",
                hint=f"Use one of the known schema names: {known}.",
            )

        # 步骤 2：检查文件是否存在
        if not Path(file_path).exists():
            OperationalLogger.get().warning("file_not_found", f"File not found: {file_path}",
                file_path=str(file_path),
                schema_name=schema_name,
            )
            return ValidationResult(
                is_valid=False,
                error_code=ErrorCode.MISSING_INPUT,
                file_path=str(file_path),
                field_path="",
                message=f"File not found: {file_path}",
                hint="Check that the file path is correct and the file exists.",
            )

        # 步骤 3：加载并解析 JSON
        try:
            with Path(file_path).open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            OperationalLogger.get().error("json_parse_error", f"Invalid JSON in file '{file_path}': {exc}",
                file_path=str(file_path),
                schema_name=schema_name,
            )
            return ValidationResult(
                is_valid=False,
                error_code=ErrorCode.INVALID_INPUT,
                file_path=str(file_path),
                field_path="",
                message=f"Invalid JSON in file '{file_path}': {exc}",
                hint="Ensure the file contains valid JSON (check for trailing commas, missing quotes, etc.).",
            )

        # 步骤 4-5：加载 schema 并执行校验
        return self._run_validation(data, schema_name, source_label=str(file_path))

    def validate_dict(
        self,
        data: Union[dict, list],
        schema_name: str,
        source_label: str = "",
    ) -> ValidationResult:
        """校验已解析的 dict/list 是否符合指定 schema。

        Args:
            data: 待校验的 JSON 数据（已解析为 dict 或 list）。
            schema_name: KNOWN_SCHEMAS 中的键名。
            source_label: 来源标识，用于填充结果中的 file_path。

        Returns:
            校验成功返回 is_valid=True，失败时返回 error_code、field_path、message、hint。
        """
        # 校验 schema_name 是否合法
        if schema_name not in self.KNOWN_SCHEMAS:
            known = list(self.KNOWN_SCHEMAS.keys())
            OperationalLogger.get().warning("unknown_schema_name", f"Unknown schema name '{schema_name}'",
                schema_name=schema_name,
                source_label=source_label,
            )
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
        """执行 jsonschema 校验并返回 ValidationResult。

        Args:
            data: 已解析的 JSON 数据。
            schema_name: KNOWN_SCHEMAS 中的键名（已由调用方校验）。
            source_label: 来源标识，用于填充结果中的 file_path。

        Returns:
            ValidationResult。
        """
        try:
            schema = self._load_schema(schema_name)
        except (FileNotFoundError, json.JSONDecodeError, SchemaError) as exc:
            OperationalLogger.get().error("schema_load_error", f"Failed to load schema '{schema_name}': {exc}",
                schema_name=schema_name,
                source_label=source_label,
            )
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
            OperationalLogger.get().debug("schema_validation_failed", exc.message,
                schema_name=schema_name,
                source_label=source_label,
                field_path=field_path,
            )
            return ValidationResult(
                is_valid=False,
                error_code=ErrorCode.SCHEMA_VIOLATION,
                file_path=source_label,
                field_path=field_path,
                message=exc.message,
                hint=hint,
            )

        return ValidationResult(is_valid=True, file_path=source_label)
