"""Tests for vibe_tracing.infra.validation.checks — validate_inputs."""

import pytest
from pathlib import Path
from types import SimpleNamespace
from vibe_tracing.infra.validation import validate_inputs, PreImportResult


def _make_record(file_key, content, status="ok", file_path=None):
    """构造一个 manifest 记录对象。"""
    if file_path is None:
        file_path = f"docs/{file_key}.json"
    return SimpleNamespace(
        file_key=file_key,
        content=content,
        status=status,
        file_path=file_path,
    )


def _make_manifest(records):
    """构造一个 manifest 对象。"""
    return SimpleNamespace(inputs_used=records)


def _make_task_list(tasks):
    """构造合法的 task_list 数据（包含必填字段）。"""
    return {
        "schema_version": "0.1",
        "project": {"project_id": "PROJECT-VT", "name": "Test", "stage": "mvp"},
        "tasks": tasks,
    }


class TestValidateInputsAllValid:
    def test_all_valid(self):
        """全部合法数据应通过校验。"""
        records = [
            _make_record("task_list", _make_task_list([
                {
                    "task_id": "TASK-VT-001",
                    "title": "Test",
                    "phase_id": "PHASE-VT-001",
                    "priority": "must",
                    "status": "todo",
                    "owner_role": "AI",
                    "objective": "Test",
                    "related_requirements": ["REQ-VT-001"],
                    "related_acceptance_criteria": ["AC-VT-001-01"],
                    "definition_of_done": [{"dod_id": "DOD-VT-001-01", "description": "Done"}],
                }
            ])),
            _make_record("agent_claims", [
                {
                    "claim_id": "CLAIM-VT-001",
                    "related_task": "TASK-VT-001",
                    "code_refs": ["src/test.py"],
                    "test_refs": ["tests/test_test.py"],
                }
            ]),
        ]
        manifest = _make_manifest(records)
        result = validate_inputs(manifest, "VT")
        assert result.is_valid


class TestSchemaValidation:
    def test_missing_required_field(self, tmp_path):
        """task_list 缺必填字段应报 schema violation。"""
        records = [
            _make_record("task_list", {"tasks": []}),  # 缺少 schema_version, project
        ]
        manifest = _make_manifest(records)
        result = validate_inputs(manifest, "VT")
        assert not result.is_valid
        assert any("schema" in i.message.lower() or "required" in i.message.lower() for i in result.issues)


class TestIdFormat:
    def test_wrong_prefix(self):
        """task_id 前缀错误应报 INVALID_ID。"""
        records = [
            _make_record("task_list", _make_task_list([
                {
                    "task_id": "TASK-XX-001",
                    "title": "Test",
                    "phase_id": "PHASE-VT-001",
                    "priority": "must",
                    "status": "todo",
                    "owner_role": "AI",
                    "objective": "Test",
                    "related_requirements": [],
                    "related_acceptance_criteria": [],
                    "definition_of_done": [],
                }
            ])),
        ]
        manifest = _make_manifest(records)
        result = validate_inputs(manifest, "VT")
        assert not result.is_valid
        assert any(i.error_code == "INVALID_ID" for i in result.issues)


class TestDuplicateIds:
    def test_duplicate_task_id(self):
        """重复 task_id 应报 DUPLICATE_ID。"""
        records = [
            _make_record("task_list", _make_task_list([
                {
                    "task_id": "TASK-VT-001",
                    "title": "A",
                    "phase_id": "PHASE-VT-001",
                    "priority": "must",
                    "status": "todo",
                    "owner_role": "AI",
                    "objective": "A",
                    "related_requirements": [],
                    "related_acceptance_criteria": [],
                    "definition_of_done": [],
                },
                {
                    "task_id": "TASK-VT-001",
                    "title": "B",
                    "phase_id": "PHASE-VT-001",
                    "priority": "should",
                    "status": "todo",
                    "owner_role": "AI",
                    "objective": "B",
                    "related_requirements": [],
                    "related_acceptance_criteria": [],
                    "definition_of_done": [],
                },
            ])),
        ]
        manifest = _make_manifest(records)
        result = validate_inputs(manifest, "VT")
        assert not result.is_valid
        assert any(i.error_code == "DUPLICATE_ID" for i in result.issues)

    def test_duplicate_claim_id(self):
        """重复 claim_id 应报 DUPLICATE_ID。"""
        records = [
            _make_record("agent_claims", [
                {"claim_id": "CLAIM-VT-001", "related_task": "TASK-VT-001"},
                {"claim_id": "CLAIM-VT-001", "related_task": "TASK-VT-002"},
            ]),
        ]
        manifest = _make_manifest(records)
        result = validate_inputs(manifest, "VT")
        assert not result.is_valid
        assert any(i.error_code == "DUPLICATE_ID" for i in result.issues)

    def test_template_excluded(self):
        """-9999 模板应排除在重复检测之外。"""
        records = [
            _make_record("task_list", _make_task_list([
                {"task_id": "TASK-VT-9999", "title": "A", "phase_id": "PHASE-VT-001",
                 "priority": "must", "status": "todo", "owner_role": "AI", "objective": "A",
                 "related_requirements": [], "related_acceptance_criteria": [], "definition_of_done": []},
                {"task_id": "TASK-VT-9999", "title": "B", "phase_id": "PHASE-VT-001",
                 "priority": "should", "status": "todo", "owner_role": "AI", "objective": "B",
                 "related_requirements": [], "related_acceptance_criteria": [], "definition_of_done": []},
            ])),
        ]
        manifest = _make_manifest(records)
        result = validate_inputs(manifest, "VT")
        # 不应有 DUPLICATE_ID 错误
        assert not any(i.error_code == "DUPLICATE_ID" for i in result.issues)


class TestPathSafety:
    def test_absolute_path(self):
        """绝对路径应报 UNSAFE_PATH。"""
        records = [
            _make_record("agent_claims", [
                {"claim_id": "CLAIM-VT-001", "related_task": "TASK-VT-001",
                 "code_refs": ["/etc/passwd"], "test_refs": []},
            ]),
        ]
        manifest = _make_manifest(records)
        result = validate_inputs(manifest, "VT")
        assert not result.is_valid
        assert any(i.error_code == "UNSAFE_PATH" for i in result.issues)

    def test_path_traversal(self):
        """路径穿越应报 UNSAFE_PATH。"""
        records = [
            _make_record("agent_claims", [
                {"claim_id": "CLAIM-VT-001", "related_task": "TASK-VT-001",
                 "code_refs": [], "test_refs": ["../../secret.py"]},
            ]),
        ]
        manifest = _make_manifest(records)
        result = validate_inputs(manifest, "VT")
        assert not result.is_valid
        assert any(i.error_code == "UNSAFE_PATH" for i in result.issues)


class TestMixedValidInvalid:
    def test_mixed(self):
        """混合合法+非法应只报告非法部分。"""
        records = [
            _make_record("task_list", _make_task_list([
                {
                    "task_id": "TASK-VT-001",
                    "title": "Good",
                    "phase_id": "PHASE-VT-001",
                    "priority": "must",
                    "status": "todo",
                    "owner_role": "AI",
                    "objective": "Good",
                    "related_requirements": [],
                    "related_acceptance_criteria": [],
                    "definition_of_done": [],
                },
                {
                    "task_id": "TASK-XX-002",
                    "title": "Bad prefix",
                    "phase_id": "PHASE-VT-001",
                    "priority": "must",
                    "status": "todo",
                    "owner_role": "AI",
                    "objective": "Bad",
                    "related_requirements": [],
                    "related_acceptance_criteria": [],
                    "definition_of_done": [],
                },
            ])),
        ]
        manifest = _make_manifest(records)
        result = validate_inputs(manifest, "VT")
        assert not result.is_valid
        assert any("TASK-XX-002" in i.field_path or "TASK-XX-002" in i.message for i in result.issues)


class TestFormatErrors:
    def test_format_output(self):
        """format_errors 应输出可读字符串。"""
        records = [
            _make_record("agent_claims", [
                {"claim_id": "CLAIM-VT-001", "related_task": "TASK-VT-001",
                 "code_refs": ["/bad"], "test_refs": []},
            ]),
        ]
        manifest = _make_manifest(records)
        result = validate_inputs(manifest, "VT")
        output = result.format_errors()
        assert isinstance(output, str)
        assert len(output) > 0
