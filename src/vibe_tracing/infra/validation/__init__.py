"""
格式校验包 — 统一的确定性格式校验入口。

对外暴露 validate_inputs 作为唯一校验入口，
同时 re-export SchemaValidator 和 ids 相关函数供其他模块使用。
"""

from .checks import validate_inputs, ValidationIssue, PreImportResult
from .schema_validator import SchemaValidator, ValidationResult
from .ids import (
    validate_id, get_id_type,
    set_project_prefix, get_project_prefix,
    make_risk_id, make_evidence_id, sentinel_evidence_id,
)

__all__ = [
    "validate_inputs", "ValidationIssue", "PreImportResult",
    "SchemaValidator", "ValidationResult",
    "validate_id", "get_id_type",
    "set_project_prefix", "get_project_prefix",
    "make_risk_id", "make_evidence_id", "sentinel_evidence_id",
]
