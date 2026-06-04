"""
Tests for Vibe Tracing project initialization command (vt init) (TASK-VT-035).
"""

import json
from pathlib import Path
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
