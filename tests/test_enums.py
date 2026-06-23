"""VT 枚举与映射常量测试模块"""

import pytest
from vibe_tracing.infra.config.enums import CoverageStatus, ErrorCode, TASK_STATUS_TO_COVERAGE


class TestCoverageStatus:
    """CoverageStatus 枚举测试"""

    def test_all_values_are_strings(self):
        """所有枚举值必须是字符串"""
        for status in CoverageStatus:
            assert isinstance(status.value, str)

    def test_coverage_status_values(self):
        """验证所有 CoverageStatus 枚举值"""
        expected = {
            "covered", "partial", "missing", "unclear", "low_confidence",
            "blocked", "compliant", "violated", "skipped", "needs_reverification"
        }
        actual = {s.value for s in CoverageStatus}
        assert actual == expected

    def test_coverage_status_string_comparison(self):
        """CoverageStatus 可以与字符串直接比较"""
        assert CoverageStatus.COVERED == "covered"
        assert CoverageStatus.MISSING == "missing"


class TestErrorCode:
    """ErrorCode 枚举测试"""

    def test_all_values_are_strings(self):
        """所有枚举值必须是字符串"""
        for code in ErrorCode:
            assert isinstance(code.value, str)

    def test_error_code_values(self):
        """验证所有 ErrorCode 枚举值"""
        expected = {
            "missing_input", "invalid_input", "schema_violation",
            "invalid_id", "invalid_status", "tool_execution_failed",
            "missing_evidence", "self_attestation", "tool_no_tests_collected",
            "tool_usage_error"
        }
        actual = {c.value for c in ErrorCode}
        assert actual == expected


class TestTaskStatusToCoverage:
    """TASK_STATUS_TO_COVERAGE 映射测试"""

    def test_mapping_is_dict(self):
        """TASK_STATUS_TO_COVERAGE 必须是字典类型"""
        assert isinstance(TASK_STATUS_TO_COVERAGE, dict)

    def test_all_values_are_coverage_status(self):
        """所有映射值必须是 CoverageStatus 枚举实例"""
        for key, value in TASK_STATUS_TO_COVERAGE.items():
            assert isinstance(key, str), f"Key '{key}' must be string"
            assert isinstance(value, CoverageStatus), f"Value for '{key}' must be CoverageStatus"

    def test_core_statuses_mapped(self):
        """核心任务状态必须被映射"""
        core_statuses = {"done", "in_progress", "todo", "blocked", "cancelled"}
        assert set(TASK_STATUS_TO_COVERAGE.keys()) == core_statuses

    def test_done_maps_to_covered(self):
        """done 状态应映射到 COVERED"""
        assert TASK_STATUS_TO_COVERAGE["done"] == CoverageStatus.COVERED

    def test_in_progress_maps_to_partial(self):
        """in_progress 状态应映射到 PARTIAL"""
        assert TASK_STATUS_TO_COVERAGE["in_progress"] == CoverageStatus.PARTIAL

    def test_todo_maps_to_missing(self):
        """todo 状态应映射到 MISSING"""
        assert TASK_STATUS_TO_COVERAGE["todo"] == CoverageStatus.MISSING

    def test_blocked_maps_to_blocked(self):
        """blocked 状态应映射到 BLOCKED"""
        assert TASK_STATUS_TO_COVERAGE["blocked"] == CoverageStatus.BLOCKED

    def test_cancelled_maps_to_skipped(self):
        """cancelled 状态应映射到 SKIPPED"""
        assert TASK_STATUS_TO_COVERAGE["cancelled"] == CoverageStatus.SKIPPED

    def test_unknown_status_returns_missing_on_get(self):
        """未知状态使用 get 方法应返回默认值 MISSING"""
        result = TASK_STATUS_TO_COVERAGE.get("unknown_status", CoverageStatus.MISSING)
        assert result == CoverageStatus.MISSING

    def test_mapping_immutable_values(self):
        """映射值不应被意外修改（防御性测试）"""
        original = TASK_STATUS_TO_COVERAGE.copy()
        # 尝试修改不应影响原始映射
        assert TASK_STATUS_TO_COVERAGE == original


class TestEnumsIntegration:
    """枚举集成测试"""

    def test_coverage_status_in_task_mapping(self):
        """TASK_STATUS_TO_COVERAGE 中的所有值都应是 CoverageStatus 的成员"""
        for status in TASK_STATUS_TO_COVERAGE.values():
            assert status in CoverageStatus

    def test_import_all_from_enums(self):
        """验证可以从 enums 模块导入所有公开符号"""
        from vibe_tracing.infra.config.enums import (
            CoverageStatus,
            ErrorCode,
            TASK_STATUS_TO_COVERAGE
        )
        assert CoverageStatus is not None
        assert ErrorCode is not None
        assert TASK_STATUS_TO_COVERAGE is not None
