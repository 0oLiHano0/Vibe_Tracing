"""Tests for operational logging in vt init and vt accept commands.

Verifies that OperationalLogger is called at key points:
- run_start / run_end lifecycle events
- Phase logging (init_step, accept_step, accept_rule)
- Exception logging in except blocks
- Validation logging (accept_validation)
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vibe_tracing.operational_logger import OperationalLogger


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure singleton is reset before and after each test."""
    OperationalLogger.reset()
    yield
    OperationalLogger.reset()


@pytest.fixture
def mock_logger():
    """Provide a mock OperationalLogger.init() that returns a recording mock."""
    mock = MagicMock()
    with patch.object(OperationalLogger, "init", return_value=mock):
        yield mock


@pytest.fixture
def init_project(tmp_path):
    """Set up a minimal project root for init tests."""
    return tmp_path


@pytest.fixture
def accept_project(tmp_path):
    """Set up a project with constraints file for accept tests."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    constraints = {
        "schema_version": "1.0.0",
        "project": {"project_name": "Test", "project_id": "PROJECT-TEST"},
        "architecture_principles": [],
        "module_boundaries": [],
        "dependency_rules": [],
        "data_flow_rules": [],
        "storage_rules": [],
        "error_handling_rules": [],
        "logging_rules": [],
        "security_rules": [],
        "technology_constraints": [],
        "forbidden_patterns": [],
        "quality_gates": [],
        "interface_contracts": [],
        "performance_constraints": [],
        "deployment_constraints": [],
        "test_constraints": [
            {
                "rule_id": "RULE-MANUAL-001",
                "description": "A manual test constraint",
                "verification_method": "manual",
            },
            {
                "rule_id": "RULE-AUTO-001",
                "description": "An automated test constraint",
                "verification_method": "machine",
            },
        ],
    }
    (docs_dir / "architecture_constraints.json").write_text(
        json.dumps(constraints, indent=2), encoding="utf-8"
    )
    vib_dir = tmp_path / ".vibetracing"
    vib_dir.mkdir()
    return tmp_path


# ==========================================================================
# vt init logging tests
# ==========================================================================


class TestInitLogging:
    """run_init must log lifecycle events and phase steps."""

    def test_run_start_logged(self, mock_logger, init_project):
        from vibe_tracing.commands.init import run_init

        result = run_init(init_project, name="TestProject", prefix="TP")

        assert result == 0
        start_calls = [
            c for c in mock_logger.info.call_args_list if c[0][0] == "run_start"
        ]
        assert len(start_calls) == 1
        assert start_calls[0][0][1] == "Init command started"
        assert start_calls[0].kwargs["name"] == "TestProject"
        assert start_calls[0].kwargs["prefix"] == "TP"

    def test_run_end_logged(self, mock_logger, init_project):
        from vibe_tracing.commands.init import run_init

        result = run_init(init_project, name="TestProject", prefix="TP")

        assert result == 0
        end_calls = [
            c for c in mock_logger.info.call_args_list if c[0][0] == "run_end"
        ]
        assert len(end_calls) == 1
        assert end_calls[0][0][1] == "Init command completed"
        assert end_calls[0].kwargs["files_created"] >= 1
        assert end_calls[0].kwargs["total_duration_ms"] >= 0

    def test_init_step_logged_for_created_files(self, mock_logger, init_project):
        from vibe_tracing.commands.init import run_init

        result = run_init(init_project, name="TestProject", prefix="TP")

        assert result == 0
        step_calls = [
            c for c in mock_logger.info.call_args_list if c[0][0] == "init_step"
        ]
        created_files = [c.kwargs["file"] for c in step_calls]
        assert ".vibetracing/config.json" in created_files
        assert "docs/prd.md" in created_files
        assert "docs/task_list.json" in created_files
        assert "docs/architecture_constraints.json" in created_files

    def test_init_step_skipped_logged(self, mock_logger, init_project):
        from vibe_tracing.commands.init import run_init

        # Run init once to create files
        run_init(init_project, name="TestProject", prefix="TP")
        mock_logger.reset_mock()

        # Run again -- files should be skipped
        result = run_init(init_project, name="TestProject", prefix="TP")

        assert result == 0
        debug_calls = [
            c for c in mock_logger.debug.call_args_list if c[0][0] == "init_step"
        ]
        skipped_files = [c.kwargs["file"] for c in debug_calls]
        assert ".vibetracing/config.json" in skipped_files
        assert "docs/prd.md" in skipped_files

    def test_init_error_logged_on_invalid_config(self, mock_logger, init_project):
        from vibe_tracing.commands.init import run_init

        # Create a corrupt config.json
        config_dir = init_project / ".vibetracing"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text("NOT JSON", encoding="utf-8")

        result = run_init(init_project, name="TestProject", prefix="TP")

        assert result == 1
        exc_calls = [
            c for c in mock_logger.exception.call_args_list if c[0][0] == "init_error"
        ]
        assert len(exc_calls) == 1
        assert "config.json" in exc_calls[0][0][1]

    def test_init_fatal_logged_on_unexpected_error(self, mock_logger, init_project):
        from vibe_tracing.commands.init import run_init

        with patch(
            "vibe_tracing.commands.init.pkg_resources.read_text",
            side_effect=RuntimeError("boom"),
        ):
            result = run_init(init_project, name="TestProject", prefix="TP")

        assert result == 1
        exc_calls = [
            c for c in mock_logger.exception.call_args_list if c[0][0] == "init_fatal"
        ]
        assert len(exc_calls) == 1

    def test_init_works_when_logger_init_fails(self, init_project):
        """If OperationalLogger.init raises, init must still succeed."""
        from vibe_tracing.commands.init import run_init

        with patch.object(OperationalLogger, "init", side_effect=RuntimeError("no logger")):
            result = run_init(init_project, name="TestProject", prefix="TP")

        assert result == 0


# ==========================================================================
# vt accept logging tests
# ==========================================================================


class TestAcceptLogging:
    """run_accept must log lifecycle events, validation, and accept decisions."""

    def test_run_start_logged(self, mock_logger, accept_project):
        from vibe_tracing.commands.accept import run_accept

        result = run_accept(accept_project, rule_id="RULE-MANUAL-001", accepted_by="tester")

        assert result == 0
        start_calls = [
            c for c in mock_logger.info.call_args_list if c[0][0] == "run_start"
        ]
        assert len(start_calls) == 1
        assert start_calls[0][0][1] == "Accept command started"
        assert start_calls[0].kwargs["rule_id"] == "RULE-MANUAL-001"
        assert start_calls[0].kwargs["accepted_by"] == "tester"

    def test_accept_rule_logged(self, mock_logger, accept_project):
        from vibe_tracing.commands.accept import run_accept

        result = run_accept(accept_project, rule_id="RULE-MANUAL-001", accepted_by="tester")

        assert result == 0
        accept_calls = [
            c for c in mock_logger.info.call_args_list if c[0][0] == "accept_rule"
        ]
        assert len(accept_calls) == 1
        assert accept_calls[0][0][1] == "Architecture rule accepted"
        assert accept_calls[0].kwargs["rule_id"] == "RULE-MANUAL-001"
        assert accept_calls[0].kwargs["accepted_by"] == "tester"
        assert accept_calls[0].kwargs["decision_id"] == 1

    def test_run_end_logged(self, mock_logger, accept_project):
        from vibe_tracing.commands.accept import run_accept

        result = run_accept(accept_project, rule_id="RULE-MANUAL-001", accepted_by="tester")

        assert result == 0
        end_calls = [
            c for c in mock_logger.info.call_args_list if c[0][0] == "run_end"
        ]
        assert len(end_calls) == 1
        assert end_calls[0][0][1] == "Accept command completed"
        assert end_calls[0].kwargs["exit_code"] == 0
        assert end_calls[0].kwargs["total_duration_ms"] >= 0

    def test_accept_step_constraints_loaded(self, mock_logger, accept_project):
        from vibe_tracing.commands.accept import run_accept

        result = run_accept(accept_project, rule_id="RULE-MANUAL-001", accepted_by="tester")

        assert result == 0
        step_calls = [
            c for c in mock_logger.info.call_args_list
            if c[0][0] == "accept_step" and c[0][1] == "Loaded architecture constraints"
        ]
        assert len(step_calls) == 1
        assert step_calls[0].kwargs["sections"] > 0

    def test_accept_step_rule_found(self, mock_logger, accept_project):
        from vibe_tracing.commands.accept import run_accept

        result = run_accept(accept_project, rule_id="RULE-MANUAL-001", accepted_by="tester")

        assert result == 0
        step_calls = [
            c for c in mock_logger.info.call_args_list
            if c[0][0] == "accept_step" and c[0][1] == "Rule found in constraints"
        ]
        assert len(step_calls) == 1
        assert step_calls[0].kwargs["verification_method"] == "manual"

    def test_accept_validation_rule_not_found(self, mock_logger, accept_project):
        from vibe_tracing.commands.accept import run_accept

        result = run_accept(accept_project, rule_id="NONEXISTENT", accepted_by="tester")

        assert result == 1
        warn_calls = [
            c for c in mock_logger.warning.call_args_list if c[0][0] == "accept_validation"
        ]
        assert len(warn_calls) == 1
        assert "Rule not found" in warn_calls[0][0][1]
        assert warn_calls[0].kwargs["rule_id"] == "NONEXISTENT"

    def test_accept_validation_not_manual(self, mock_logger, accept_project):
        from vibe_tracing.commands.accept import run_accept

        result = run_accept(accept_project, rule_id="RULE-AUTO-001", accepted_by="tester")

        assert result == 1
        warn_calls = [
            c for c in mock_logger.warning.call_args_list if c[0][0] == "accept_validation"
        ]
        assert len(warn_calls) == 1
        assert "not manual" in warn_calls[0][0][1]
        assert warn_calls[0].kwargs["verification_method"] == "machine"

    def test_accept_already_accepted_logs_run_end(self, mock_logger, accept_project):
        from vibe_tracing.commands.accept import run_accept

        # Accept once
        run_accept(accept_project, rule_id="RULE-MANUAL-001", accepted_by="tester")
        mock_logger.reset_mock()

        # Accept again -- should log already_accepted
        result = run_accept(accept_project, rule_id="RULE-MANUAL-001", accepted_by="tester")

        assert result == 0
        end_calls = [
            c for c in mock_logger.info.call_args_list if c[0][0] == "run_end"
        ]
        assert len(end_calls) == 1
        assert end_calls[0].kwargs["already_accepted"] is True

    def test_accept_error_on_missing_constraints(self, mock_logger, tmp_path):
        from vibe_tracing.commands.accept import run_accept

        result = run_accept(tmp_path, rule_id="RULE-001", accepted_by="tester")

        assert result == 1
        error_calls = [
            c for c in mock_logger.error.call_args_list if c[0][0] == "accept_error"
        ]
        assert len(error_calls) == 1
        assert "not found" in error_calls[0][0][1].lower()

    def test_accept_error_on_corrupt_constraints(self, mock_logger, tmp_path):
        from vibe_tracing.commands.accept import run_accept

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "architecture_constraints.json").write_text("NOT JSON", encoding="utf-8")

        result = run_accept(tmp_path, rule_id="RULE-001", accepted_by="tester")

        assert result == 1
        exc_calls = [
            c for c in mock_logger.exception.call_args_list if c[0][0] == "accept_error"
        ]
        assert len(exc_calls) == 1
        assert "constraints" in exc_calls[0][0][1].lower()

    def test_accept_works_when_logger_init_fails(self, accept_project):
        """If OperationalLogger.init raises, accept must still succeed."""
        from vibe_tracing.commands.accept import run_accept

        with patch.object(OperationalLogger, "init", side_effect=RuntimeError("no logger")):
            result = run_accept(accept_project, rule_id="RULE-MANUAL-001", accepted_by="tester")

        assert result == 0

    def test_accept_write_error_logged(self, mock_logger, accept_project):
        from vibe_tracing.commands.accept import run_accept

        # Patch decisions_path.write_text to fail
        decisions_path = accept_project / ".vibetracing" / "human_decisions.json"
        with patch.object(type(decisions_path), "write_text", side_effect=OSError("disk full")):
            result = run_accept(accept_project, rule_id="RULE-MANUAL-001", accepted_by="tester")

        assert result == 1
        exc_calls = [
            c for c in mock_logger.exception.call_args_list if c[0][0] == "accept_error"
        ]
        assert len(exc_calls) == 1
        assert "human_decisions" in exc_calls[0][0][1].lower()

    def test_accept_step_decisions_loaded(self, mock_logger, accept_project):
        """When human_decisions.json exists, loading it is logged."""
        from vibe_tracing.commands.accept import run_accept

        # Pre-create decisions file
        vib_dir = accept_project / ".vibetracing"
        vib_dir.mkdir(parents=True, exist_ok=True)
        (vib_dir / "human_decisions.json").write_text(
            json.dumps({"version": "1.0", "decisions": []}), encoding="utf-8"
        )

        result = run_accept(accept_project, rule_id="RULE-MANUAL-001", accepted_by="tester")

        assert result == 0
        debug_calls = [
            c for c in mock_logger.debug.call_args_list
            if c[0][0] == "accept_step" and c[0][1] == "Loaded existing human decisions"
        ]
        assert len(debug_calls) == 1
        assert debug_calls[0].kwargs["existing_count"] == 0

    def test_accept_step_write_logged(self, mock_logger, accept_project):
        """Successful write of human_decisions.json is logged."""
        from vibe_tracing.commands.accept import run_accept

        result = run_accept(accept_project, rule_id="RULE-MANUAL-001", accepted_by="tester")

        assert result == 0
        step_calls = [
            c for c in mock_logger.info.call_args_list
            if c[0][0] == "accept_step" and c[0][1] == "Wrote human_decisions.json"
        ]
        assert len(step_calls) == 1
        assert step_calls[0].kwargs["decision_id"] == 1
        assert step_calls[0].kwargs["total_decisions"] == 1
