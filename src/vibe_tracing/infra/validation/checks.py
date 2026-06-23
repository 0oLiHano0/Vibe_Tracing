"""
统一格式校验模块。

执行所有"只看当前文件就能判断"的确定性校验：
JSON Schema、ID 格式、重复 ID、路径安全、human_decisions 结构。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from vibe_tracing.infra.logging.logger import OperationalLogger
from vibe_tracing.infra.validation.schema_validator import SchemaValidator


@dataclass
class ValidationIssue:
    """单条校验错误。"""
    error_code: str       # 错误类型枚举值
    field_path: str       # JSON 指针，如 "tasks[0].task_id"
    message: str          # 人类可读描述
    hint: str = ""        # 修复建议
    source_file: str = "" # 来源文件


@dataclass
class PreImportResult:
    """格式校验的聚合结果。"""
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.issues) == 0

    def format_errors(self) -> str:
        """将所有 issue 格式化为可打印字符串。"""
        lines = []
        for issue in self.issues:
            parts = []
            if issue.source_file:
                parts.append(f"[{issue.source_file}]")
            if issue.field_path:
                parts.append(f"Field '{issue.field_path}'")
            parts.append(issue.message)
            if issue.hint:
                parts.append(f"Hint: {issue.hint}")
            lines.append(" ".join(parts))
        return "\n".join(lines)


def _check_schemas(
    manifest: Any,
    schemas_dir: Optional[Path] = None,
) -> List[ValidationIssue]:
    """JSON Schema 校验：逐个文件委托 SchemaValidator 校验。"""
    vt_logger = OperationalLogger.get()
    issues = []
    validator = SchemaValidator(schemas_dir)

    # manifest.inputs_used 是加载记录列表
    schema_map = {
        "task_list": "task_list",
        "agent_claims": "agent_claims",
        "test_results": "test_results",
        "coverage_reports": "coverage_reports",
        "architecture_constraints": "architecture_constraints",
    }

    for record in manifest.inputs_used:
        file_key = record.file_key
        if file_key not in schema_map:
            continue
        if record.status != "ok" or record.content is None:
            continue

        schema_name = schema_map[file_key]
        result = validator.validate_dict(
            record.content, schema_name,
            source_label=record.file_path,
        )
        if not result.is_valid:
            vt_logger.debug("schema_violation", result.message,
                error_code="SCHEMA_VIOLATION",
                field_path=result.field_path,
                source_file=record.file_path,
            )
            issues.append(ValidationIssue(
                error_code="SCHEMA_VIOLATION",
                field_path=result.field_path,
                message=result.message,
                hint=result.hint,
                source_file=record.file_path,
            ))

    return issues


def _check_id_formats(
    manifest: Any,
    project_prefix: str,
) -> List[ValidationIssue]:
    """ID 格式 + 项目前缀校验：遍历各 ID 字段调用 validate_id。"""
    vt_logger = OperationalLogger.get()
    from vibe_tracing.infra.validation.ids import validate_id, set_project_prefix

    # 先设置项目前缀，确保 validate_id 使用正确的前缀
    set_project_prefix(project_prefix)

    issues = []

    def _check_id(id_str: str, field_path: str, source_file: str):
        if not id_str or id_str.endswith("-9999"):
            return
        is_valid, err_msg = validate_id(id_str)
        if not is_valid:
            vt_logger.debug("invalid_id", f"Invalid ID format: {err_msg}",
                error_code="INVALID_ID",
                field_path=field_path,
                source_file=source_file,
            )
            issues.append(ValidationIssue(
                error_code="INVALID_ID",
                field_path=field_path,
                message=f"Invalid ID format: {err_msg}",
                source_file=source_file,
            ))

    for record in manifest.inputs_used:
        if record.status != "ok" or record.content is None:
            continue

        content = record.content
        source = record.file_path

        # task_list: 检查 task_id, phase_id, related_requirements, related_acceptance_criteria
        if record.file_key == "task_list" and isinstance(content, dict):
            for i, task in enumerate(content.get("tasks", [])):
                if task.get("task_id", "").endswith("-9999"):
                    continue
                _check_id(task.get("task_id", ""), f"tasks[{i}].task_id", source)
                _check_id(task.get("phase_id", ""), f"tasks[{i}].phase_id", source)
                for j, req_id in enumerate(task.get("related_requirements", [])):
                    _check_id(req_id, f"tasks[{i}].related_requirements[{j}]", source)
                for j, ac_id in enumerate(task.get("related_acceptance_criteria", [])):
                    _check_id(ac_id, f"tasks[{i}].related_acceptance_criteria[{j}]", source)

        # claims: 检查 claim_id, related_task
        elif record.file_key == "agent_claims" and isinstance(content, list):
            for i, claim in enumerate(content):
                if claim.get("claim_id", "").endswith("-9999"):
                    continue
                _check_id(claim.get("claim_id", ""), f"[{i}].claim_id", source)
                _check_id(claim.get("related_task", ""), f"[{i}].related_task", source)

    return issues


def _check_duplicate_ids(
    manifest: Any,
) -> List[ValidationIssue]:
    """同一文件内重复 ID 检测（排除 -9999 模板）。"""
    vt_logger = OperationalLogger.get()
    issues = []

    for record in manifest.inputs_used:
        if record.status != "ok" or record.content is None:
            continue

        content = record.content
        source = record.file_path

        # task_list: 检查 task_id 唯一性
        if record.file_key == "task_list" and isinstance(content, dict):
            seen = set()
            for i, task in enumerate(content.get("tasks", [])):
                tid = task.get("task_id", "")
                if tid.endswith("-9999") or not tid:
                    continue
                if tid in seen:
                    vt_logger.debug("duplicate_id", f"Duplicate task_id: {tid}",
                        error_code="DUPLICATE_ID",
                        field_path=f"tasks[{i}].task_id",
                        source_file=source,
                    )
                    issues.append(ValidationIssue(
                        error_code="DUPLICATE_ID",
                        field_path=f"tasks[{i}].task_id",
                        message=f"Duplicate task_id: {tid}",
                        source_file=source,
                    ))
                seen.add(tid)

        # claims: 检查 claim_id 唯一性
        elif record.file_key == "agent_claims" and isinstance(content, list):
            seen = set()
            for i, claim in enumerate(content):
                cid = claim.get("claim_id", "")
                if cid.endswith("-9999") or not cid:
                    continue
                if cid in seen:
                    vt_logger.debug("duplicate_id", f"Duplicate claim_id: {cid}",
                        error_code="DUPLICATE_ID",
                        field_path=f"[{i}].claim_id",
                        source_file=source,
                    )
                    issues.append(ValidationIssue(
                        error_code="DUPLICATE_ID",
                        field_path=f"[{i}].claim_id",
                        message=f"Duplicate claim_id: {cid}",
                        source_file=source,
                    ))
                seen.add(cid)

    return issues


def _check_path_safety(
    manifest: Any,
) -> List[ValidationIssue]:
    """claims 的 code_refs/test_refs 路径安全检查。"""
    vt_logger = OperationalLogger.get()
    issues = []

    for record in manifest.inputs_used:
        if record.file_key != "agent_claims":
            continue
        if record.status != "ok" or record.content is None:
            continue

        content = record.content
        source = record.file_path

        if not isinstance(content, list):
            continue

        for i, claim in enumerate(content):
            for ref_field in ("code_refs", "test_refs"):
                refs = claim.get(ref_field, [])
                if not isinstance(refs, list):
                    continue
                for j, ref in enumerate(refs):
                    if not isinstance(ref, str):
                        continue
                    path = ref.split("#")[0]  # 去掉 fragment
                    if not path:
                        continue
                    if path.startswith("/"):
                        vt_logger.debug("unsafe_path", f"Absolute path not allowed: {path}",
                            error_code="UNSAFE_PATH",
                            field_path=f"[{i}].{ref_field}[{j}]",
                            source_file=source,
                        )
                        issues.append(ValidationIssue(
                            error_code="UNSAFE_PATH",
                            field_path=f"[{i}].{ref_field}[{j}]",
                            message=f"Absolute path not allowed: {path}",
                            source_file=source,
                        ))
                    if ".." in path.split("/"):
                        vt_logger.debug("unsafe_path", f"Path traversal not allowed: {path}",
                            error_code="UNSAFE_PATH",
                            field_path=f"[{i}].{ref_field}[{j}]",
                            source_file=source,
                        )
                        issues.append(ValidationIssue(
                            error_code="UNSAFE_PATH",
                            field_path=f"[{i}].{ref_field}[{j}]",
                            message=f"Path traversal not allowed: {path}",
                            source_file=source,
                        ))

    return issues


def _check_human_decisions(
    manifest: Any,
    schemas_dir: Optional[Path] = None,
) -> List[ValidationIssue]:
    """human_decisions 结构校验（如果文件存在）。"""
    issues = []
    validator = SchemaValidator(schemas_dir)

    for record in manifest.inputs_used:
        if record.file_key != "human_decisions":
            continue
        if record.status != "ok" or record.content is None:
            continue

        result = validator.validate_dict(
            record.content, "human_decisions",
            source_label=record.file_path,
        )
        if not result.is_valid:
            issues.append(ValidationIssue(
                error_code="SCHEMA_VIOLATION",
                field_path=result.field_path,
                message=result.message,
                hint=result.hint,
                source_file=record.file_path,
            ))

    return issues


def validate_inputs(
    manifest: Any,
    project_prefix: str,
    schemas_dir: Path = None,
) -> PreImportResult:
    """一次性执行所有确定性格式校验。

    Args:
        manifest: RawInputLoader.load() 返回的 manifest 对象。
        project_prefix: 项目前缀（如 "VT"）。
        schemas_dir: schema 文件目录（可选）。

    Returns:
        PreImportResult，包含所有校验失败项。
    """
    vt_logger = OperationalLogger.get()
    vt_logger.info("validation_start", "Pre-import format validation started",
        project_prefix=project_prefix,
        inputs_count=len(manifest.inputs_used),
    )
    issues = []
    issues.extend(_check_schemas(manifest, schemas_dir))
    issues.extend(_check_id_formats(manifest, project_prefix))
    issues.extend(_check_duplicate_ids(manifest))
    issues.extend(_check_path_safety(manifest))
    issues.extend(_check_human_decisions(manifest, schemas_dir))
    result = PreImportResult(issues=issues)
    vt_logger.info("validation_complete", "Pre-import format validation finished",
        issue_count=len(result.issues),
        is_valid=result.is_valid,
        error_codes=[i.error_code for i in result.issues],
    )
    return result
