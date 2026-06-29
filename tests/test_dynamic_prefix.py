import json
from pathlib import Path
from vibe_tracing.cli import run_init, run_analyze
from vibe_tracing.infra.loader.prd_parser import PrdParser
from vibe_tracing.infra.loader.task_loader import TaskLoader
from vibe_tracing.infra.validation.schema_validator import SchemaValidator
from vibe_tracing.infra import validation as ids


def test_dynamic_prefix_init_and_validation(tmp_path):
    """Test that project can be initialized with custom name/prefix and successfully validated."""
    # Initialize a new project with custom prefix "CapL"
    exit_code = run_init(tmp_path, name="Capacity Limit", prefix="CapL")
    assert exit_code == 0

    # Ensure directories exist
    assert (tmp_path / ".vibetracing").is_dir()
    assert (tmp_path / "docs").is_dir()

    config_path = tmp_path / ".vibetracing" / "config.json"
    prd_path = tmp_path / "docs" / "prd.md"
    task_list_path = tmp_path / "docs" / "task_list.json"
    agent_claims_dir = tmp_path / ".vibetracing" / "claims"

    assert config_path.is_file()
    assert prd_path.is_file()
    assert task_list_path.is_file()
    assert agent_claims_dir.is_dir()  # Claims directory exists (no current.json)

    # 1. Verify config.json values
    with config_path.open("r", encoding="utf-8") as f:
        config_data = json.load(f)
    assert config_data["project_id"] == "PROJECT-CapL"
    assert config_data["project_prefix"] == "CapL"
    assert config_data["project_name"] == "Capacity Limit"

    # 2. Parse prd.md and verify dynamic ID registration
    ids.set_project_prefix("CapL")
    parser = PrdParser()
    prd_res = parser.parse_text(prd_path.read_text())
    assert prd_res.is_valid is True
    assert len(prd_res.requirements) == 1
    
    req = prd_res.requirements[0]
    assert req.req_id == "REQ-CapL-001"
    assert req.priority == "must"
    assert len(req.acceptance_criteria) == 2
    assert req.acceptance_criteria[0].ac_id == "AC-CapL-001-01"

    # Ensure dynamic prefix is registered in ids module
    assert ids.get_project_prefix() == "CapL"
    assert ids.validate_id("REQ-CapL-123")[0] is True
    assert ids.validate_id("REQ-VT-123")[0] is False  # Legacy VT should now fail for this run

    # 3. Verify task_list schema validation passes
    schemas_dir = Path(__file__).parent.parent / "src" / "vibe_tracing" / "infra" / "validation" / "schemas"
    validator = SchemaValidator(schemas_dir)

    val_task = validator.validate_file(task_list_path, "task_list")
    assert val_task.is_valid is True, f"Failed task list validation: {val_task.message}"

    # 4. Load tasks using TaskLoader and verify no errors
    task_loader = TaskLoader()
    task_res = task_loader.deserialize(json.loads(task_list_path.read_text()))
    assert len(task_res.tasks) == 0
 
    # Ensure project_name and project_id are correctly stored on prd_res
    assert prd_res.project_name == "Capacity Limit"
    assert prd_res.project_id == "PROJECT-CapL"

    # Update config to mock finalization
    import hashlib
    constraints_path = tmp_path / "docs" / "architecture_constraints.json"
    with config_path.open("r", encoding="utf-8") as f:
        config_data = json.load(f)
    config_data["language"] = "python"
    config_data["language_tool_matrix"] = {
        "python": {
            "test": {
                "tool": "pytest",
                "default_command": "pytest {test_path} --tb=short -q --json-report --json-report-file={output_path}",
                "output_format": "pytest_json",
                "pass_condition": "exit_code == 0",
            }
        }
    }
    config_data["architecture_constraints_hash"] = hashlib.sha256(
        constraints_path.read_bytes()
    ).hexdigest()
    config_data["finalize_git_commit"] = "test_commit_hash"
    with config_path.open("w", encoding="utf-8") as f:
        json.dump(config_data, f)

    # Test CLI run_analyze execution and dynamic project ID propagation
    output_dir = tmp_path / "output"
    exit_code_analyze = run_analyze(tmp_path, output_dir)
    assert exit_code_analyze in (0, 2)
 
    # Read output evidences/test_results.json and traceability_report.json
    test_results_path = output_dir / "evidences" / "test_results.json"
    traceability_report_path = output_dir / "traceability_report.json"

    assert test_results_path.is_file()
    assert traceability_report_path.is_file()

    with test_results_path.open("r", encoding="utf-8") as f:
        ei_data = json.load(f)
    # test_results.json is a list of test result records
    assert isinstance(ei_data, list)

    with traceability_report_path.open("r", encoding="utf-8") as f:
        tr_data = json.load(f)
    assert tr_data["project_id"] == "PROJECT-CapL"
 
    # 5. Clean up prefix registration back to "VT" (for other test runs)
    ids.set_project_prefix("VT")
    assert ids.get_project_prefix() == "VT"


def test_init_params_required(tmp_path):
    """Test that vibe-tracing init fails if either name or prefix is not provided."""
    # 1. Name is missing
    exit_code_no_name = run_init(tmp_path, name=None, prefix="VT")
    assert exit_code_no_name == 1

    # 2. Prefix is missing
    exit_code_no_prefix = run_init(tmp_path, name="Capacity Limit", prefix=None)
    assert exit_code_no_prefix == 1

    # 3. Both are missing
    exit_code_none = run_init(tmp_path, name=None, prefix=None)
    assert exit_code_none == 1
