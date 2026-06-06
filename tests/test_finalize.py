"""Tests for the `vibe-tracing finalize` CLI command (TASK-VT-038)."""

import hashlib
import json
import subprocess
import pytest
from pathlib import Path
from typing import Optional

from vibe_tracing.cli import main


def _setup_project(base: Path, config_data: Optional[dict] = None, constraints_data: Optional[dict] = None) -> None:
    """Helper to set up minimal project structure for finalize tests."""
    (base / ".vibetracing").mkdir(parents=True, exist_ok=True)
    (base / "docs").mkdir(parents=True, exist_ok=True)

    config = config_data if config_data is not None else {
        "project_id": "PROJECT-TEST",
        "project_prefix": "TEST",
        "project_name": "Test Project",
        "paths": {
            "prd": "docs/prd.md",
            "architecture_constraints": "docs/architecture_constraints.json",
            "task_list": "docs/task_list.json",
            "agent_claims": ".vibetracing/agent_claims.json",
            "output_dir": "output",
        },
    }
    (base / ".vibetracing" / "config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )

    constraints = constraints_data if constraints_data is not None else {
        "schema_version": "1.0.0",
        "project": {
            "project_id": "PROJECT-TEST",
            "name": "Test Project",
            "stage": "mvp",
            "language": "python",
        },
        "language_tool_matrix": {
            "python": {
                "test": {"tool": "pytest", "command": "pytest"},
                "coverage": {"tool": "coverage", "command": "coverage run"},
                "lint": {"tool": "ruff", "command": "ruff check"},
                "type_check": {"tool": "mypy", "command": "mypy"},
                "security": {"tool": "bandit", "command": "bandit -r"},
            },
            "go": {
                "test": {"tool": "go test", "command": "go test ./..."},
                "lint": {"tool": "golangci-lint", "command": "golangci-lint run"},
            },
        },
    }
    (base / "docs" / "architecture_constraints.json").write_text(
        json.dumps(constraints, indent=2), encoding="utf-8"
    )


def _init_git_repo(base: Path) -> str:
    """Initialize a git repo in *base*, add all files, and return the HEAD commit hash."""
    subprocess.run(["git", "init"], cwd=base, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@test.com",
         "add", "."], cwd=base, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@test.com",
         "commit", "-m", "initial"], cwd=base, check=True, capture_output=True,
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=base, capture_output=True, text=True
    )
    return result.stdout.strip()


def test_finalize_happy_path(tmp_path, capsys):
    """Happy path: finalize writes language and validation_tools to config.json."""
    _setup_project(tmp_path)

    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Vibe Tracing finalized for project." in captured.out

    config = json.loads((tmp_path / ".vibetracing" / "config.json").read_text(encoding="utf-8"))
    assert config["language"] == "python"
    assert config["validation_tools"] == ["test", "coverage", "lint", "type_check", "security"]


def test_finalize_already_finalized_same_language(tmp_path, capsys):
    """Running finalize again with the same language prints 'Already finalized' and exits 0."""
    _setup_project(tmp_path)

    # First run
    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 0

    # Second run
    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Already finalized: language=python" in captured.out

    # Config should be unchanged
    config = json.loads((tmp_path / ".vibetracing" / "config.json").read_text(encoding="utf-8"))
    assert config["language"] == "python"
    assert config["validation_tools"] == ["test", "coverage", "lint", "type_check", "security"]


def test_finalize_updates_tools_when_matrix_changes(tmp_path, capsys):
    """When language_tool_matrix gains a new tool category, re-finalize updates validation_tools."""
    _setup_project(tmp_path)

    # First run
    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 0

    # Simulate Agent adding a new tool to the matrix
    constraints_path = tmp_path / "docs" / "architecture_constraints.json"
    constraints = json.loads(constraints_path.read_text(encoding="utf-8"))
    constraints["language_tool_matrix"]["python"]["formatter"] = {
        "tool": "black",
        "command": "black --check",
    }
    constraints_path.write_text(json.dumps(constraints, indent=2), encoding="utf-8")

    # Second run — should detect tools changed
    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Updated validation_tools" in captured.out

    config = json.loads((tmp_path / ".vibetracing" / "config.json").read_text(encoding="utf-8"))
    assert "formatter" in config["validation_tools"]
    assert len(config["validation_tools"]) == 6


def test_finalize_conflict_language(tmp_path, capsys):
    """Config has a different language than architecture_constraints -> error and exit 1."""
    _setup_project(tmp_path, config_data={
        "project_id": "PROJECT-TEST",
        "project_prefix": "TEST",
        "project_name": "Test Project",
        "language": "go",
        "paths": {},
    })

    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert 'conflicts with architecture_constraints language "python"' in captured.err


def test_finalize_missing_architecture_constraints(tmp_path, capsys):
    """Missing architecture_constraints.json -> error and exit 1."""
    _setup_project(tmp_path)
    (tmp_path / "docs" / "architecture_constraints.json").unlink()

    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "architecture_constraints.json not found" in captured.err


def test_finalize_no_language_in_constraints(tmp_path, capsys):
    """Architecture constraints have no project.language -> error and exit 1."""
    _setup_project(tmp_path, constraints_data={
        "schema_version": "1.0.0",
        "project": {
            "project_id": "PROJECT-TEST",
            "name": "Test Project",
            "stage": "mvp",
        },
        "language_tool_matrix": {
            "python": {"test": {"tool": "pytest"}},
        },
    })

    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "project.language not set" in captured.err


def test_finalize_language_not_in_matrix(tmp_path, capsys):
    """Language set to 'rust' but not in language_tool_matrix -> error and exit 1."""
    _setup_project(tmp_path, constraints_data={
        "schema_version": "1.0.0",
        "project": {
            "project_id": "PROJECT-TEST",
            "name": "Test Project",
            "stage": "mvp",
            "language": "rust",
        },
        "language_tool_matrix": {
            "python": {"test": {"tool": "pytest"}},
        },
    })

    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert 'language "rust" not found in language_tool_matrix' in captured.err


def test_finalize_missing_config_json(tmp_path, capsys):
    """Missing config.json -> error and exit 1."""
    (tmp_path / ".vibetracing").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    # No config.json written
    (tmp_path / "docs" / "architecture_constraints.json").write_text(
        json.dumps({"project": {"language": "python"}}), encoding="utf-8"
    )

    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "config.json not found" in captured.err


def test_finalize_cli_help_shows_finalize(capsys):
    """The top-level help output should list the finalize subcommand."""
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "finalize" in captured.out


def test_finalize_writes_hash_commit_path(tmp_path, capsys):
    """First finalize in a git repo writes architecture_constraints_hash,
    finalize_git_commit, and finalize_constraints_path to config.json."""
    _setup_project(tmp_path)
    head_commit = _init_git_repo(tmp_path)

    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 0

    config = json.loads((tmp_path / ".vibetracing" / "config.json").read_text(encoding="utf-8"))

    constraints_path = tmp_path / "docs" / "architecture_constraints.json"
    expected_hash = hashlib.sha256(constraints_path.read_bytes()).hexdigest()

    assert config["architecture_constraints_hash"] == expected_hash
    assert config["finalize_git_commit"] != head_commit
    assert config["finalize_constraints_path"] == "docs/architecture_constraints.json"


def test_finalize_re_finalize_hash_match(tmp_path, capsys):
    """Re-finalize with unchanged constraints prints 'Already finalized' (hash matches)."""
    _setup_project(tmp_path)
    _init_git_repo(tmp_path)

    # First finalize
    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 0

    # Second finalize — constraints unchanged
    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Already finalized" in captured.out


def test_finalize_re_finalize_format_change_only(tmp_path, capsys):
    """Re-finalize when constraints changed but no rule diff (format change only)
    should update hash without requiring change_log validation."""
    _setup_project(tmp_path)
    _init_git_repo(tmp_path)

    # First finalize
    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 0

    first_config = json.loads(
        (tmp_path / ".vibetracing" / "config.json").read_text(encoding="utf-8")
    )
    first_hash = first_config["architecture_constraints_hash"]

    # Modify constraints: reformat (change key order, same semantic content)
    constraints_path = tmp_path / "docs" / "architecture_constraints.json"
    data = json.loads(constraints_path.read_text(encoding="utf-8"))
    # Rewrite with different indentation (2 -> 4 spaces) to change hash
    constraints_path.write_text(json.dumps(data, indent=4), encoding="utf-8")

    new_hash = hashlib.sha256(constraints_path.read_bytes()).hexdigest()
    assert new_hash != first_hash, "Reformatting must change the raw hash"

    # Second finalize — format changed, but rule diff is empty
    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 0

    second_config = json.loads(
        (tmp_path / ".vibetracing" / "config.json").read_text(encoding="utf-8")
    )
    assert second_config["architecture_constraints_hash"] == new_hash


def test_finalize_re_finalize_rule_change_no_change_log(tmp_path, capsys):
    """Re-finalize when constraints have rule changes but change_log is not updated
    should reject (exit 1)."""
    _setup_project(tmp_path)
    _init_git_repo(tmp_path)

    # First finalize
    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 0

    # Modify constraints: add a structural rule change WITHOUT changing tool categories
    constraints_path = tmp_path / "docs" / "architecture_constraints.json"
    data = json.loads(constraints_path.read_text(encoding="utf-8"))
    # Add storage_rules — a new top-level key that creates a structural diff
    data["storage_rules"] = [
        {
            "rule_id": "STORE-VT-001",
            "title": "MVP no database",
            "severity": "must",
            "description": "No database allowed in MVP",
        }
    ]
    constraints_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # Commit the change so there are no uncommitted changes
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@test.com",
         "add", "."], cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@test.com",
         "commit", "-m", "modify constraints"], cwd=tmp_path, check=True, capture_output=True,
    )

    # Second finalize — rule changed, no change_log update
    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "change_log.md" in captured.err


def test_finalize_re_finalize_rule_change_with_change_log(tmp_path, capsys):
    """Re-finalize when constraints have rule changes AND change_log is updated
    should accept and update hash."""
    _setup_project(tmp_path)
    _init_git_repo(tmp_path)

    # First finalize
    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 0

    first_config = json.loads(
        (tmp_path / ".vibetracing" / "config.json").read_text(encoding="utf-8")
    )

    # Modify constraints: add a real rule change
    constraints_path = tmp_path / "docs" / "architecture_constraints.json"
    data = json.loads(constraints_path.read_text(encoding="utf-8"))
    data["storage_rules"] = [
        {
            "rule_id": "STORE-VT-001",
            "title": "MVP no database",
            "severity": "must",
            "description": "No database allowed in MVP",
        }
    ]
    constraints_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # Also update change_log.md
    change_log_path = tmp_path / "docs" / "architecture_change_log.md"
    change_log_path.write_text(
        "# Architecture Change Log\n\n## [2026-06-04]\n* Added STORE-VT-001\n",
        encoding="utf-8",
    )

    # Commit both changes together (same commit = passes validation)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@test.com",
         "add", "."], cwd=tmp_path, check=True, capture_output=True,
    )
    # Removed manual commit to let vt finalize create it in V4

    # Second finalize — rule changed + change_log updated in same commit
    exit_code = main(["finalize", "--project-root", str(tmp_path)])
    assert exit_code == 0

    second_config = json.loads(
        (tmp_path / ".vibetracing" / "config.json").read_text(encoding="utf-8")
    )
    assert second_config["architecture_constraints_hash"] != first_config["architecture_constraints_hash"]
