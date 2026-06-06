"""
Tests for Vibe Tracing project initialization command (vt init) (TASK-VT-035).
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from vibe_tracing.cli import run_init


def test_run_init_creates_scaffolding(tmp_path):
    """Test that run_init creates all directories and template files with appropriate field hints.
    Covers: AC-VT-009-07
    """
    # Execute run_init on tmp_path
    exit_code = run_init(tmp_path, name="Vibe Tracing", prefix="VT")
    assert exit_code == 0

    # Check directory structure (output/ is not created during init)
    assert (tmp_path / ".vibetracing").is_dir()
    assert (tmp_path / "docs").is_dir()
    assert not (tmp_path / "output").exists()

    # Check files existence
    config_path = tmp_path / ".vibetracing" / "config.json"
    claims_path = tmp_path / ".vibetracing" / "agent_claims.json"
    tasks_path = tmp_path / "docs" / "task_list.json"
    constraints_path = tmp_path / "docs" / "architecture_constraints.json"
    prd_path = tmp_path / "docs" / "prd.md"
    prd_analysis_path = tmp_path / ".vibetracing" / "prompts" / "prd_analysis.md"

    assert config_path.is_file()
    assert claims_path.is_file()
    assert tasks_path.is_file()
    assert constraints_path.is_file()
    assert prd_path.is_file()
    assert prd_analysis_path.is_file()

    # Verify agent_claims.json content
    with claims_path.open("r", encoding="utf-8") as f:
        claims_data = json.load(f)
    assert isinstance(claims_data, list)
    assert len(claims_data) == 0

    # Verify task_list.json content
    with tasks_path.open("r", encoding="utf-8") as f:
        tasks_data = json.load(f)
    assert isinstance(tasks_data, dict)
    assert tasks_data["schema_version"] == "1.0.0"
    assert "__field_hints__" not in tasks_data
    assert isinstance(tasks_data["tasks"], list)
    assert len(tasks_data["tasks"]) == 0

    # Verify architecture_constraints.json content (pure empty rule lists)
    with constraints_path.open("r", encoding="utf-8") as f:
        constraints_data = json.load(f)
    assert isinstance(constraints_data, dict)
    assert constraints_data["schema_version"] == "1.0.0"
    assert constraints_data["project"]["project_id"] == "PROJECT-VT"
    assert len(constraints_data["architecture_principles"]) == 0
    assert len(constraints_data["module_boundaries"]) == 0
    assert len(constraints_data["dependency_rules"]) == 0

    # Verify config.json content
    with config_path.open("r", encoding="utf-8") as f:
        config_data = json.load(f)
    assert config_data["paths"]["prd"] == "docs/prd.md"
    assert config_data["project_name"] == "Vibe Tracing"
    assert config_data["project_prefix"] == "VT"

    # Verify both generated files pass schema validation
    from vibe_tracing.schema_validator import SchemaValidator
    schemas_dir = Path(__file__).parent.parent / "src" / "vibe_tracing" / "schemas"
    validator = SchemaValidator(schemas_dir)
    
    val_task = validator.validate_file(tasks_path, "task_list")
    assert val_task.is_valid is True, f"Generated task list schema validation failed: {val_task.message}"
    
    val_claims = validator.validate_file(claims_path, "agent_claims")
    assert val_claims.is_valid is True, f"Generated agent claims schema validation failed: {val_claims.message}"

    val_constraints = validator.validate_file(constraints_path, "architecture_constraints")
    assert val_constraints.is_valid is True, f"Generated architecture constraints schema validation failed: {val_constraints.message}"

    # Verify language_tool_matrix is present with python tools
    assert "language_tool_matrix" in constraints_data
    ltm = constraints_data["language_tool_matrix"]
    assert "python" in ltm
    python_tools = ltm["python"]
    for category in ("test", "coverage", "lint", "type_check", "security"):
        assert category in python_tools, f"Missing tool category: {category}"
        entry = python_tools[category]
        assert "tool" in entry
        assert "default_command" in entry
        assert "output_format" in entry
        assert "pass_condition" in entry

    # Verify run_init skips existing files
    # Modify one of the files
    with config_path.open("w", encoding="utf-8") as f:
        f.write('{"custom": true}')

    # Run init again
    exit_code_again = run_init(tmp_path, name="Vibe Tracing", prefix="VT")
    assert exit_code_again == 0

    # Ensure it wasn't overwritten
    with config_path.open("r", encoding="utf-8") as f:
        config_data_again = json.load(f)
    assert config_data_again == {"custom": True}


def test_run_init_pre_commit_hook_uses_sys_executable(tmp_path):
    """Test that the generated pre-commit hook uses sys.executable instead of hardcoded python3."""
    import sys

    # Create a fake .git/hooks directory
    git_hooks_dir = tmp_path / ".git" / "hooks"
    git_hooks_dir.mkdir(parents=True, exist_ok=True)

    exit_code = run_init(tmp_path, name="Hook Test", prefix="HT")
    assert exit_code == 0

    hook_path = git_hooks_dir / "pre-commit"
    assert hook_path.is_file()
    content = hook_path.read_text(encoding="utf-8")

    # Must NOT contain hardcoded python3 -m
    assert "python3 -m" not in content, (
        f"Pre-commit hook should not hardcode 'python3 -m', got: {content}"
    )
    # Must contain the actual interpreter path
    assert sys.executable in content, (
        f"Pre-commit hook should use sys.executable ({sys.executable}), got: {content}"
    )


def test_init_partial_failure_retry_uses_new_params(tmp_path):
    """Test that partial init failure does NOT leave config.json behind,
    so retrying with different --name/--prefix uses the new values.

    Covers: L12 bug -- config.json written last prevents stale config on retry.
    """
    original_open = Path.open
    call_count = {"new_writes": 0}

    def failing_open(self, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if "w" in str(mode):
            call_count["new_writes"] += 1
            # Fail on the 3rd new write (1=agent_claims, 2=task_list, 3=arch_constraints)
            if call_count["new_writes"] == 3:
                raise OSError("No space left on device")
        return original_open(self, *args, **kwargs)

    with patch.object(Path, "open", failing_open):
        exit_code = run_init(tmp_path, name="Foo", prefix="FO")

    # Init should have failed
    assert exit_code == 1

    # config.json must NOT exist (it is written last, after the failing point)
    config_path = tmp_path / ".vibetracing" / "config.json"
    assert not config_path.exists(), "config.json should not exist after partial failure"

    # Some earlier template files should have been created
    assert (tmp_path / ".vibetracing" / "agent_claims.json").exists()
    assert (tmp_path / "docs" / "task_list.json").exists()

    # Retry with DIFFERENT params -- config.json does not exist so new params are used
    exit_code2 = run_init(tmp_path, name="Bar", prefix="BR")
    assert exit_code2 == 0

    # Verify config.json now uses the NEW params ("Bar"/"BR"), not old ("Foo"/"FO")
    with config_path.open("r", encoding="utf-8") as f:
        config_data = json.load(f)
    assert config_data["project_name"] == "Bar", "Retry should use new name"
    assert config_data["project_prefix"] == "BR", "Retry should use new prefix"

    # Verify other files also use new prefix
    constraints_path = tmp_path / "docs" / "architecture_constraints.json"
    with constraints_path.open("r", encoding="utf-8") as f:
        constraints_data = json.load(f)
    assert constraints_data["project"]["project_id"] == "PROJECT-BR"
