"""Tests for operational logging in the doctor command."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vibe_tracing.operational_logger import OperationalLogger
from vibe_tracing.commands.doctor import run_doctor


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure singleton is reset before and after each test."""
    OperationalLogger.reset()
    yield
    OperationalLogger.reset()


def _read_log_lines(project_root: Path) -> list[dict]:
    """Read all JSON lines from the operational log file."""
    logs_dir = project_root / ".vibetracing" / "logs"
    log_files = sorted(logs_dir.glob("vt-*.jsonl"))
    assert log_files, "Expected at least one log file"
    lines = log_files[-1].read_text().strip().splitlines()
    return [json.loads(line) for line in lines]


def _log_events(project_root: Path) -> list[str]:
    """Extract event names from the log."""
    return [entry["event"] for entry in _read_log_lines(project_root)]


def _log_by_event(project_root: Path, event: str) -> list[dict]:
    """Get all log entries matching a given event."""
    return [e for e in _read_log_lines(project_root) if e["event"] == event]


class TestDoctorLoggingInit:
    """Test that logger is initialized at command entry."""

    def test_logger_initialized_on_run(self, tmp_path):
        """run_doctor should initialize operational logger and log doctor_start."""
        # Create minimal required dirs
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()

        run_doctor(tmp_path)

        events = _log_events(tmp_path)
        assert "doctor_start" in events
        assert "doctor_end" in events

    def test_logger_init_failure_does_not_block_doctor(self, tmp_path, monkeypatch):
        """If logger init fails, doctor must still complete and print report."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()

        # Force OperationalLogger.init to raise
        monkeypatch.setattr(
            OperationalLogger, "init",
            classmethod(lambda cls, *a, **kw: (_ for _ in ()).throw(PermissionError("no"))),
        )

        # Should not raise
        exit_code = run_doctor(tmp_path)
        assert exit_code == 0


class TestDoctorLoadLogging:
    """Test logging during governance data loading."""

    def test_claims_file_not_found_logs_warning(self, tmp_path):
        """Missing claims file should log a warning-level load entry."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()

        run_doctor(tmp_path)

        load_events = _log_by_event(tmp_path, "doctor_load")
        claims_logs = [e for e in load_events if e.get("file") == "claims"]
        assert len(claims_logs) == 1
        assert claims_logs[0]["result"] == "warning"

    def test_claims_file_loaded_successfully(self, tmp_path):
        """Valid claims file should log pass result."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()
        (tmp_path / ".vibetracing" / "claims").mkdir(parents=True)
        claims = [{"claim_id": "C-1", "code_refs": [], "test_refs": [], "evidence_refs": []}]
        (tmp_path / ".vibetracing" / "claims" / "current.json").write_text(json.dumps(claims))

        run_doctor(tmp_path)

        load_events = _log_by_event(tmp_path, "doctor_load")
        claims_logs = [e for e in load_events if e.get("file") == "claims"]
        assert len(claims_logs) == 1
        assert claims_logs[0]["result"] == "pass"
        assert claims_logs[0]["claims_count"] == 1

    def test_invalid_claims_json_logs_fail(self, tmp_path):
        """Malformed claims JSON should log fail with exception."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()
        (tmp_path / ".vibetracing" / "claims").mkdir(parents=True)
        (tmp_path / ".vibetracing" / "claims" / "current.json").write_text("not json!")

        run_doctor(tmp_path)

        load_events = _log_by_event(tmp_path, "doctor_load")
        claims_logs = [e for e in load_events if e.get("file") == "claims"]
        assert len(claims_logs) == 1
        assert claims_logs[0]["result"] == "fail"
        assert "exception" in claims_logs[0]

    def test_task_list_not_found_logs_warning(self, tmp_path):
        """Missing task list should log a warning."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()

        run_doctor(tmp_path)

        load_events = _log_by_event(tmp_path, "doctor_load")
        task_logs = [e for e in load_events if e.get("file") == "task_list"]
        assert len(task_logs) == 1
        assert task_logs[0]["result"] == "warning"

    def test_task_list_loaded_successfully(self, tmp_path):
        """Valid task list should log pass result with task count."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()
        tasks = {"tasks": [{"task_id": "T-1", "related_requirements": [], "related_acceptance_criteria": []}]}
        (tmp_path / "docs" / "task_list.json").write_text(json.dumps(tasks))

        run_doctor(tmp_path)

        load_events = _log_by_event(tmp_path, "doctor_load")
        task_logs = [e for e in load_events if e.get("file") == "task_list"]
        assert len(task_logs) == 1
        assert task_logs[0]["result"] == "pass"
        assert task_logs[0]["tasks_count"] == 1

    def test_constraints_not_found_logs_warning(self, tmp_path):
        """Missing constraints file should log a warning."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()

        run_doctor(tmp_path)

        load_events = _log_by_event(tmp_path, "doctor_load")
        constraints_logs = [e for e in load_events if e.get("file") == "constraints"]
        assert len(constraints_logs) == 1
        assert constraints_logs[0]["result"] == "warning"

    def test_evidence_index_not_found_logs_warning(self, tmp_path):
        """Missing evidence index should log a warning."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()

        run_doctor(tmp_path)

        load_events = _log_by_event(tmp_path, "doctor_load")
        ei_logs = [e for e in load_events if e.get("file") == "evidence_index"]
        assert len(ei_logs) == 1
        assert ei_logs[0]["result"] == "warning"


class TestDoctorCheckLogging:
    """Test logging for each diagnostic check."""

    def test_evidence_refs_check_logged(self, tmp_path):
        """evidence_refs_integrity check should be logged with result."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()

        run_doctor(tmp_path)

        check_events = _log_by_event(tmp_path, "doctor_check")
        ev_check = [e for e in check_events if e.get("check") == "evidence_refs_integrity"]
        assert len(ev_check) == 1
        assert ev_check[0]["result"] == "pass"
        assert "duration_ms" in ev_check[0]

    def test_file_refs_check_logged(self, tmp_path):
        """file_refs_integrity check should be logged with result."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()

        run_doctor(tmp_path)

        check_events = _log_by_event(tmp_path, "doctor_check")
        fr_check = [e for e in check_events if e.get("check") == "file_refs_integrity"]
        assert len(fr_check) == 1
        assert fr_check[0]["result"] == "pass"

    def test_requirement_mapping_check_logged(self, tmp_path):
        """requirement_mapping check should be logged."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()

        run_doctor(tmp_path)

        check_events = _log_by_event(tmp_path, "doctor_check")
        rm_check = [e for e in check_events if e.get("check") == "requirement_mapping"]
        assert len(rm_check) == 1
        assert rm_check[0]["result"] == "pass"

    def test_ac_mapping_check_logged(self, tmp_path):
        """ac_mapping check should be logged."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()

        run_doctor(tmp_path)

        check_events = _log_by_event(tmp_path, "doctor_check")
        ac_check = [e for e in check_events if e.get("check") == "ac_mapping"]
        assert len(ac_check) == 1
        assert ac_check[0]["result"] == "pass"

    def test_machine_rule_coverage_check_logged(self, tmp_path):
        """machine_rule_coverage check should be logged."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()

        run_doctor(tmp_path)

        check_events = _log_by_event(tmp_path, "doctor_check")
        mr_check = [e for e in check_events if e.get("check") == "machine_rule_coverage"]
        assert len(mr_check) == 1
        assert mr_check[0]["result"] == "pass"

    def test_check_with_issues_logs_fail(self, tmp_path):
        """Check that finds issues should log result=fail."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()
        (tmp_path / ".vibetracing" / "claims").mkdir(parents=True)
        # Claim references a non-existent file
        claims = [{
            "claim_id": "C-1",
            "code_refs": ["src/nonexistent.py"],
            "test_refs": [],
            "evidence_refs": [],
        }]
        (tmp_path / ".vibetracing" / "claims" / "current.json").write_text(json.dumps(claims))

        run_doctor(tmp_path)

        check_events = _log_by_event(tmp_path, "doctor_check")
        fr_check = [e for e in check_events if e.get("check") == "file_refs_integrity"]
        assert len(fr_check) == 1
        assert fr_check[0]["result"] == "fail"
        assert fr_check[0]["issues_count"] == 1


class TestDoctorEndLogging:
    """Test the run_end summary logging."""

    def test_end_event_contains_summary(self, tmp_path):
        """doctor_end should contain check summary and total counts."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()

        run_doctor(tmp_path)

        end_events = _log_by_event(tmp_path, "doctor_end")
        assert len(end_events) == 1
        end = end_events[0]
        assert end["total_checks"] == 5
        assert end["total_issues"] == 0
        assert "check_summary" in end
        assert isinstance(end["check_summary"], dict)
        assert "total_duration_ms" in end

    def test_end_summary_reflects_actual_results(self, tmp_path):
        """doctor_end summary should show fail for checks with issues."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()
        (tmp_path / ".vibetracing" / "claims").mkdir(parents=True)
        claims = [{
            "claim_id": "C-1",
            "code_refs": ["src/nonexistent.py"],
            "test_refs": [],
            "evidence_refs": [],
        }]
        (tmp_path / ".vibetracing" / "claims" / "current.json").write_text(json.dumps(claims))

        run_doctor(tmp_path)

        end_events = _log_by_event(tmp_path, "doctor_end")
        assert len(end_events) == 1
        summary = end_events[0]["check_summary"]
        assert summary["file_refs_integrity"] == "fail"
        assert summary["evidence_refs_integrity"] == "pass"

    def test_duration_ms_is_non_negative(self, tmp_path):
        """All logged durations should be non-negative."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()

        run_doctor(tmp_path)

        all_entries = _read_log_lines(tmp_path)
        for entry in all_entries:
            if "duration_ms" in entry:
                assert entry["duration_ms"] >= 0, f"Negative duration in {entry['event']}"


class TestDoctorLoggingDoesNotAffectOutput:
    """Test that logging does not change the command's behavior or output."""

    def test_exit_code_unchanged(self, tmp_path):
        """run_doctor should return 0 regardless of logging."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()

        exit_code = run_doctor(tmp_path)
        assert exit_code == 0

    def test_json_report_still_printed(self, tmp_path, capsys):
        """The JSON report should still be printed to stdout."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()

        run_doctor(tmp_path)

        captured = capsys.readouterr()
        report = json.loads(captured.out)
        assert "checks" in report
        assert "total_issues" in report
        assert len(report["checks"]) == 5

    def test_all_five_checks_present_in_report(self, tmp_path, capsys):
        """Report should contain all 5 check names."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()

        run_doctor(tmp_path)

        captured = capsys.readouterr()
        report = json.loads(captured.out)
        check_names = [c["name"] for c in report["checks"]]
        expected = [
            "evidence_refs_integrity",
            "file_refs_integrity",
            "requirement_mapping",
            "ac_mapping",
            "machine_rule_coverage",
        ]
        assert check_names == expected


class TestDoctorLoggingRunId:
    """Test that doctor logs use a DOCTOR- prefixed run_id."""

    def test_run_id_has_doctor_prefix(self, tmp_path):
        """Log entries should have a DOCTOR- prefixed run_id."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "output").mkdir()

        run_doctor(tmp_path)

        all_entries = _read_log_lines(tmp_path)
        for entry in all_entries:
            assert entry["run_id"].startswith("DOCTOR-"), \
                f"Expected DOCTOR- prefix in run_id, got: {entry['run_id']}"
