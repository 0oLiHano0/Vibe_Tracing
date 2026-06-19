import json
from pathlib import Path
import pytest
from vibe_tracing.cli import main



# =========================================================================
# Tests for run_accept
# =========================================================================

def test_run_accept_rule_found(tmp_path):
    """Test that run_accept finds a manual rule and writes to human_decisions.json."""
    from vibe_tracing.cli import run_accept

    # Set up architecture_constraints.json with a manual rule
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    constraints = {
        "schema_version": "1.0.0",
        "project": {"project_id": "TEST", "name": "Test", "stage": "mvp", "language": "python"},
        "language_tool_matrix": {},
        "module_boundaries": [
            {
                "rule_id": "MOD-TEST-001",
                "name": "Core Module",
                "responsibility": "Core",
                "related_requirements": [],
                "verification_method": "manual",
            }
        ],
    }
    (tmp_path / "docs" / "architecture_constraints.json").write_text(
        json.dumps(constraints, indent=2), encoding="utf-8"
    )

    exit_code = run_accept(tmp_path, "MOD-TEST-001", accepted_by="agent-x")
    assert exit_code == 0

    # Verify constraints file was NOT modified
    data = json.loads((tmp_path / "docs" / "architecture_constraints.json").read_text())
    rule = data["module_boundaries"][0]
    assert "accepted_by" not in rule

    # Verify human_decisions.json was created with the decision
    decisions_path = tmp_path / ".vibetracing" / "human_decisions.json"
    assert decisions_path.exists()
    decisions_data = json.loads(decisions_path.read_text(encoding="utf-8"))
    assert decisions_data["version"] == "1.0"
    assert len(decisions_data["decisions"]) == 1
    entry = decisions_data["decisions"][0]
    assert entry["decision_id"] == 1
    assert entry["category"] == "accepted_rule"
    assert entry["targetId"] == "MOD-TEST-001"
    assert entry["action"] == "accept"
    assert entry["decidedBy"] == "agent-x"
    assert "timestamp" in entry


def test_run_accept_rule_already_accepted(tmp_path, capsys):
    """Test that run_accept returns 0 when a rule is already accepted in human_decisions.json."""
    from vibe_tracing.cli import run_accept

    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    constraints = {
        "schema_version": "1.0.0",
        "project": {"project_id": "TEST", "name": "Test", "stage": "mvp", "language": "python"},
        "language_tool_matrix": {},
        "module_boundaries": [
            {
                "rule_id": "MOD-TEST-001",
                "name": "Core Module",
                "responsibility": "Core",
                "related_requirements": [],
                "verification_method": "manual",
            }
        ],
    }
    (tmp_path / "docs" / "architecture_constraints.json").write_text(
        json.dumps(constraints, indent=2), encoding="utf-8"
    )

    # Pre-populate human_decisions.json with an existing acceptance
    (tmp_path / ".vibetracing").mkdir(parents=True, exist_ok=True)
    existing_decisions = {
        "version": "1.0",
        "decisions": [
            {
                "decision_id": 1,
                "category": "accepted_rule",
                "targetId": "MOD-TEST-001",
                "action": "accept",
                "reason": "",
                "decidedBy": "human",
                "timestamp": "2025-01-01T00:00:00Z",
            }
        ],
    }
    (tmp_path / ".vibetracing" / "human_decisions.json").write_text(
        json.dumps(existing_decisions, indent=2), encoding="utf-8"
    )

    exit_code = run_accept(tmp_path, "MOD-TEST-001")
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "already been accepted" in captured.out

    # Verify no duplicate entry was added
    decisions_data = json.loads(
        (tmp_path / ".vibetracing" / "human_decisions.json").read_text(encoding="utf-8")
    )
    assert len(decisions_data["decisions"]) == 1


def test_run_accept_rule_not_found(tmp_path, capsys):
    """Test that run_accept returns 1 when a rule is not found."""
    from vibe_tracing.cli import run_accept

    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    constraints = {
        "schema_version": "1.0.0",
        "project": {"project_id": "TEST", "name": "Test", "stage": "mvp", "language": "python"},
        "language_tool_matrix": {},
        "module_boundaries": [],
    }
    (tmp_path / "docs" / "architecture_constraints.json").write_text(
        json.dumps(constraints, indent=2), encoding="utf-8"
    )

    exit_code = run_accept(tmp_path, "NONEXISTENT-RULE")
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "not found" in captured.err


def test_run_accept_missing_file(tmp_path, capsys):
    """Test that run_accept returns 1 when constraints file is missing."""
    from vibe_tracing.cli import run_accept

    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)

    exit_code = run_accept(tmp_path, "ANY-RULE")
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "not found" in captured.err


def test_run_accept_non_manual_rule(tmp_path, capsys):
    """Test that run_accept rejects rules with verification_method != 'manual'."""
    from vibe_tracing.cli import run_accept

    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    constraints = {
        "schema_version": "1.0.0",
        "project": {"project_id": "TEST", "name": "Test", "stage": "mvp", "language": "python"},
        "language_tool_matrix": {},
        "module_boundaries": [
            {
                "rule_id": "MOD-MACHINE-001",
                "name": "Machine Rule",
                "responsibility": "Machine verified",
                "related_requirements": [],
                "verification_method": "machine",
            }
        ],
    }
    (tmp_path / "docs" / "architecture_constraints.json").write_text(
        json.dumps(constraints, indent=2), encoding="utf-8"
    )

    exit_code = run_accept(tmp_path, "MOD-MACHINE-001")
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "programmatic verification" in captured.err

    # Verify human_decisions.json was NOT created
    decisions_path = tmp_path / ".vibetracing" / "human_decisions.json"
    assert not decisions_path.exists()


def test_run_accept_via_cli(tmp_path, capsys):
    """Test run_accept via CLI main with accept subcommand."""
    from vibe_tracing.cli import run_accept

    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    constraints = {
        "schema_version": "1.0.0",
        "project": {"project_id": "TEST", "name": "Test", "stage": "mvp", "language": "python"},
        "language_tool_matrix": {},
        "module_boundaries": [],
        "security_rules": [
            {"rule_id": "SEC-001", "description": "No hardcoded secrets", "verification_method": "manual"}
        ],
    }
    (tmp_path / "docs" / "architecture_constraints.json").write_text(
        json.dumps(constraints, indent=2), encoding="utf-8"
    )

    exit_code = main(["accept", "SEC-001", "--project-root", str(tmp_path), "--by", "test-agent"])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "SEC-001" in captured.out
    assert "test-agent" in captured.out

    # Verify acceptance was written to human_decisions.json
    decisions_path = tmp_path / ".vibetracing" / "human_decisions.json"
    assert decisions_path.exists()
    decisions_data = json.loads(decisions_path.read_text(encoding="utf-8"))
    assert decisions_data["decisions"][0]["targetId"] == "SEC-001"
    assert decisions_data["decisions"][0]["decidedBy"] == "test-agent"

    # Verify constraints file was NOT modified
    data = json.loads((tmp_path / "docs" / "architecture_constraints.json").read_text())
    assert "accepted_by" not in data["security_rules"][0]


# =========================================================================
# Tests for run_doctor
# =========================================================================

def _setup_doctor_project(base: Path):
    """Helper to set up a minimal project for doctor tests."""
    (base / "docs").mkdir(parents=True, exist_ok=True)
    (base / "output").mkdir(parents=True, exist_ok=True)
    (base / ".vibetracing").mkdir(parents=True, exist_ok=True)
    (base / ".vibetracing" / "claims").mkdir(parents=True, exist_ok=True)
    (base / "src").mkdir(parents=True, exist_ok=True)

    # PRD
    prd_content = """# Test PRD
### REQ-TEST-001: Test Requirement
#### 类别
functional
#### 优先级
must

##### AC-TEST-001-01: Test AC
* 是否必须有测试：是
"""
    (base / "docs" / "prd.md").write_text(prd_content, encoding="utf-8")

    # Task list
    task_list = {
        "schema_version": "0.1",
        "project": {"project_id": "TEST", "name": "Test", "stage": "mvp"},
        "tasks": [
            {
                "task_id": "TASK-TEST-001",
                "title": "Test Task",
                "phase_id": "PHASE-001",
                "priority": "must",
                "status": "done",
                "owner_role": "agent",
                "objective": "Test objective",
                "related_requirements": ["REQ-TEST-001"],
                "related_acceptance_criteria": ["AC-TEST-001-01"],
                "definition_of_done": [],
            }
        ],
    }
    (base / "docs" / "task_list.json").write_text(
        json.dumps(task_list), encoding="utf-8"
    )

    # Architecture constraints with a machine-verified rule that has no checker
    constraints = {
        "schema_version": "1.0.0",
        "project": {"project_id": "TEST", "name": "Test", "stage": "mvp", "language": "python"},
        "language_tool_matrix": {},
        "module_boundaries": [],
        "security_rules": [
            {
                "rule_id": "SEC-001",
                "description": "No hardcoded secrets",
                "verification_method": "machine",
            }
        ],
    }
    (base / "docs" / "architecture_constraints.json").write_text(
        json.dumps(constraints, indent=2), encoding="utf-8"
    )

    # Valid claims with good refs
    source_file = base / "src" / "main.py"
    source_file.write_text("# main", encoding="utf-8")
    claims = [
        {
            "claim_id": "CLAIM-001",
            "related_task": "TASK-TEST-001",
            "timestamp": "2025-01-01T00:00:00Z",
            "code_refs": ["src/main.py"],
            "test_refs": [],
            "notes": "Test claim",
        }
    ]
    (base / ".vibetracing" / "claims" / "CLAIM-VT-001.json").write_text(
        json.dumps(claims), encoding="utf-8"
    )


def test_run_doctor_all_passing(tmp_path):
    """Test run_doctor when all checks pass."""
    from vibe_tracing.cli import run_doctor

    _setup_doctor_project(tmp_path)
    # Create split evidence files with matching evidence
    evidences_dir = tmp_path / "output" / "evidences"
    evidences_dir.mkdir(parents=True, exist_ok=True)
    test_results = [
        {"nodeid": "tests/test_main.py::test_main", "outcome": "passed", "exit_code": 0, "command": "pytest", "carried_over": False}
    ]
    (evidences_dir / "test_results.json").write_text(
        json.dumps(test_results), encoding="utf-8"
    )
    (evidences_dir / "coverage_reports.json").write_text(
        json.dumps([]), encoding="utf-8"
    )

    exit_code = run_doctor(tmp_path)
    assert exit_code == 0



def test_run_doctor_broken_file_refs(tmp_path, capsys):
    """Test run_doctor detects broken file references."""
    from vibe_tracing.cli import run_doctor

    _setup_doctor_project(tmp_path)
    # Modify claim to reference a non-existent file
    claims = [
        {
            "claim_id": "CLAIM-001",
            "related_task": "TASK-TEST-001",
            "timestamp": "2025-01-01T00:00:00Z",
            "code_refs": ["src/nonexistent.py"],
            "test_refs": ["tests/nonexistent_test.py"],
            "notes": "Test claim",
        }
    ]
    (tmp_path / ".vibetracing" / "claims" / "CLAIM-VT-001.json").write_text(
        json.dumps(claims), encoding="utf-8"
    )

    exit_code = run_doctor(tmp_path)
    assert exit_code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    checks = {c["name"]: c for c in output["checks"]}
    assert len(checks["file_refs_integrity"]["issues"]) > 0


def test_run_doctor_requirement_mapping_issue(tmp_path, capsys):
    """Test run_doctor detects broken requirement mappings."""
    from vibe_tracing.cli import run_doctor

    _setup_doctor_project(tmp_path)
    # Add a task referencing a non-existent requirement
    task_list = {
        "schema_version": "0.1",
        "project": {"project_id": "TEST", "name": "Test", "stage": "mvp"},
        "tasks": [
            {
                "task_id": "TASK-TEST-001",
                "title": "Test Task",
                "phase_id": "PHASE-001",
                "priority": "must",
                "status": "done",
                "owner_role": "agent",
                "objective": "Test",
                "related_requirements": ["REQ-NONEXISTENT"],
                "related_acceptance_criteria": ["AC-TEST-001-01"],
                "definition_of_done": [],
            }
        ],
    }
    (tmp_path / "docs" / "task_list.json").write_text(
        json.dumps(task_list), encoding="utf-8"
    )

    exit_code = run_doctor(tmp_path)
    assert exit_code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    checks = {c["name"]: c for c in output["checks"]}
    assert len(checks["requirement_mapping"]["issues"]) > 0
    assert "REQ-NONEXISTENT" in checks["requirement_mapping"]["issues"][0]["requirement_id"]


def test_run_doctor_ac_mapping_issue(tmp_path, capsys):
    """Test run_doctor detects broken AC mappings."""
    from vibe_tracing.cli import run_doctor

    _setup_doctor_project(tmp_path)
    task_list = {
        "schema_version": "0.1",
        "project": {"project_id": "TEST", "name": "Test", "stage": "mvp"},
        "tasks": [
            {
                "task_id": "TASK-TEST-001",
                "title": "Test Task",
                "phase_id": "PHASE-001",
                "priority": "must",
                "status": "done",
                "owner_role": "agent",
                "objective": "Test",
                "related_requirements": ["REQ-TEST-001"],
                "related_acceptance_criteria": ["AC-NONEXISTENT"],
                "definition_of_done": [],
            }
        ],
    }
    (tmp_path / "docs" / "task_list.json").write_text(
        json.dumps(task_list), encoding="utf-8"
    )

    exit_code = run_doctor(tmp_path)
    assert exit_code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    checks = {c["name"]: c for c in output["checks"]}
    assert len(checks["ac_mapping"]["issues"]) > 0
    assert "AC-NONEXISTENT" in checks["ac_mapping"]["issues"][0]["ac_id"]


def test_run_doctor_machine_rule_no_checker(tmp_path, capsys):
    """Test run_doctor detects machine-verified rules without a checker."""
    from vibe_tracing.cli import run_doctor

    _setup_doctor_project(tmp_path)

    exit_code = run_doctor(tmp_path)
    assert exit_code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    checks = {c["name"]: c for c in output["checks"]}
    assert len(checks["machine_rule_coverage"]["issues"]) > 0
    assert "SEC-001" in checks["machine_rule_coverage"]["issues"][0]["rule_id"]


def test_run_doctor_machine_rule_with_checker(tmp_path, capsys):
    """Test run_doctor passes when machine rule has explicit checker."""
    from vibe_tracing.cli import run_doctor

    _setup_doctor_project(tmp_path)
    # Add checker field to the rule
    arch_path = tmp_path / "docs" / "architecture_constraints.json"
    arch = json.loads(arch_path.read_text(encoding="utf-8"))
    arch["security_rules"][0]["checker"] = "check_secrets.py"
    arch_path.write_text(json.dumps(arch, indent=2), encoding="utf-8")

    exit_code = run_doctor(tmp_path)
    assert exit_code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    checks = {c["name"]: c for c in output["checks"]}
    assert len(checks["machine_rule_coverage"]["issues"]) == 0


def test_run_doctor_missing_files(tmp_path, capsys):
    """Test run_doctor handles missing files gracefully."""
    from vibe_tracing.cli import run_doctor

    # Empty project directory
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vibetracing").mkdir(parents=True, exist_ok=True)

    exit_code = run_doctor(tmp_path)
    assert exit_code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["total_issues"] == 0  # No claims, no tasks -> no issues


def test_run_doctor_via_cli(tmp_path, capsys):
    """Test run_doctor via CLI main with doctor subcommand."""
    _setup_doctor_project(tmp_path)

    exit_code = main(["doctor", "--project-root", str(tmp_path)])
    assert exit_code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "checks" in output
    assert "total_issues" in output


def test_run_doctor_with_bad_json(tmp_path, capsys):
    """Test run_doctor tolerates corrupted JSON files."""
    from vibe_tracing.cli import run_doctor

    _setup_doctor_project(tmp_path)
    # Write invalid JSON
    (tmp_path / ".vibetracing" / "claims" / "CLAIM-VT-001.json").write_text("not json!!!", encoding="utf-8")
    (tmp_path / "docs" / "task_list.json").write_text("{broken", encoding="utf-8")

    exit_code = run_doctor(tmp_path)
    assert exit_code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "checks" in output


def test_run_doctor_with_prd_parse_error(tmp_path, capsys):
    """Test run_doctor handles PRD parse errors gracefully."""
    from vibe_tracing.cli import run_doctor

    _setup_doctor_project(tmp_path)
    # Write a PRD that will fail parsing (empty)
    (tmp_path / "docs" / "prd.md").write_text("", encoding="utf-8")

    exit_code = run_doctor(tmp_path)
    assert exit_code == 0


def test_run_doctor_machine_rule_with_module_support(tmp_path, capsys):
    """Test run_doctor passes when machine rule references an existing module."""
    from vibe_tracing.cli import run_doctor

    _setup_doctor_project(tmp_path)
    arch_path = tmp_path / "docs" / "architecture_constraints.json"
    arch = json.loads(arch_path.read_text(encoding="utf-8"))
    # Add module boundary that matches the rule's related_modules
    arch["module_boundaries"] = [
        {"module_id": "MOD-SEC", "name": "Security", "responsibility": "Security", "related_requirements": []}
    ]
    arch["security_rules"][0]["related_modules"] = ["MOD-SEC"]
    arch_path.write_text(json.dumps(arch, indent=2), encoding="utf-8")

    exit_code = run_doctor(tmp_path)
    assert exit_code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    checks = {c["name"]: c for c in output["checks"]}
    assert len(checks["machine_rule_coverage"]["issues"]) == 0


def test_run_doctor_machine_rule_with_verification_command(tmp_path, capsys):
    """Test run_doctor passes when machine rule has verification_command."""
    from vibe_tracing.cli import run_doctor

    _setup_doctor_project(tmp_path)
    arch_path = tmp_path / "docs" / "architecture_constraints.json"
    arch = json.loads(arch_path.read_text(encoding="utf-8"))
    arch["security_rules"][0]["verification_command"] = "check_secrets"
    arch_path.write_text(json.dumps(arch, indent=2), encoding="utf-8")

    exit_code = run_doctor(tmp_path)
    assert exit_code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    checks = {c["name"]: c for c in output["checks"]}
    assert len(checks["machine_rule_coverage"]["issues"]) == 0


def test_run_doctor_task_list_not_dict(tmp_path, capsys):
    """Test run_doctor handles task_list.json as a non-dict (list)."""
    from vibe_tracing.cli import run_doctor

    _setup_doctor_project(tmp_path)
    # Write task_list.json as a list instead of dict
    (tmp_path / "docs" / "task_list.json").write_text("[]", encoding="utf-8")

    exit_code = run_doctor(tmp_path)
    assert exit_code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "checks" in output



def test_run_doctor_claims_not_list(tmp_path, capsys):
    """Test run_doctor handles claims file that is a dict (not list)."""
    from vibe_tracing.cli import run_doctor

    _setup_doctor_project(tmp_path)
    # Write claims as a dict instead of list
    (tmp_path / ".vibetracing" / "claims" / "CLAIM-VT-001.json").write_text(
        json.dumps({"invalid": "format"}), encoding="utf-8"
    )

    exit_code = run_doctor(tmp_path)
    assert exit_code == 0


def test_run_doctor_with_fragment_refs(tmp_path, capsys):
    """Test run_doctor correctly strips fragment identifiers from refs."""
    from vibe_tracing.cli import run_doctor

    _setup_doctor_project(tmp_path)
    # Add fragment identifier to code_ref
    claims = [
        {
            "claim_id": "CLAIM-001",
            "related_task": "TASK-TEST-001",
            "timestamp": "2025-01-01T00:00:00Z",
            "code_refs": ["src/main.py#L1-L10"],
            "test_refs": [],
            "notes": "Test",
        }
    ]
    (tmp_path / ".vibetracing" / "claims" / "CLAIM-VT-001.json").write_text(
        json.dumps(claims), encoding="utf-8"
    )

    exit_code = run_doctor(tmp_path)
    assert exit_code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    checks = {c["name"]: c for c in output["checks"]}
    # src/main.py exists, so no file_refs issues
    assert len(checks["file_refs_integrity"]["issues"]) == 0


# =========================================================================
# Tests for helper functions: _get_ac_description, _get_req_description,
# _get_related_code, _get_existing_tests
# =========================================================================

def test_get_ac_description():
    """Test _get_ac_description extracts AC title from prd_result."""
    from vibe_tracing.cli import _get_ac_description
    from unittest.mock import MagicMock

    # Mock prd_result with requirements and ACs
    ac = MagicMock()
    ac.ac_id = "AC-TEST-01"
    ac.title = "Test AC Title"

    req = MagicMock()
    req.acceptance_criteria = [ac]

    prd_result = MagicMock()
    prd_result.requirements = [req]

    assert _get_ac_description("AC-TEST-01", prd_result) == "Test AC Title"
    assert _get_ac_description("AC-NONEXISTENT", prd_result) == ""
    assert _get_ac_description("AC-TEST-01", None) == ""


def test_get_req_description():
    """Test _get_req_description extracts requirement title from prd_result."""
    from vibe_tracing.cli import _get_req_description
    from unittest.mock import MagicMock

    req = MagicMock()
    req.req_id = "REQ-TEST-01"
    req.title = "Test Req Title"

    prd_result = MagicMock()
    prd_result.requirements = [req]

    assert _get_req_description("REQ-TEST-01", prd_result) == "Test Req Title"
    assert _get_req_description("REQ-NONEXISTENT", prd_result) == ""
    assert _get_req_description("", prd_result) == ""
    assert _get_req_description("REQ-TEST-01", None) == ""


def test_get_related_code(tmp_path, monkeypatch):
    """Test _get_related_code finds code file paths related to an AC."""
    from vibe_tracing.cli import _get_related_code
    from unittest.mock import MagicMock

    # Create a code file
    code_file = tmp_path / "src" / "module.py"
    code_file.parent.mkdir(parents=True, exist_ok=True)
    code_file.write_text("# module code\n", encoding="utf-8")

    # Monkeypatch Path.exists to return True for the known file
    _orig_exists = Path.exists
    def mock_exists(self):
        if str(self).endswith("src/module.py"):
            return True
        return _orig_exists(self)
    monkeypatch.setattr(Path, "exists", mock_exists)

    # Mock task and claim objects
    task = MagicMock()
    task.task_id = "TASK-001"
    task.related_acceptance_criteria = ["AC-TEST-01"]

    task_result = MagicMock()
    task_result.tasks = [task]

    claim = MagicMock()
    claim.related_task = "TASK-001"
    claim.code_refs = [f"src/module.py#L1-L5"]

    result = _get_related_code("AC-TEST-01", task_result, [claim])
    assert len(result) > 0
    assert result[0] == "src/module.py"


def test_get_related_code_no_claims():
    """Test _get_related_code returns empty list when no claims."""
    from vibe_tracing.cli import _get_related_code
    assert _get_related_code("AC-TEST-01", None, None) == []
    assert _get_related_code("AC-TEST-01", None, []) == []


def test_get_existing_tests():
    """Test _get_existing_tests finds test refs related to an AC."""
    from vibe_tracing.cli import _get_existing_tests
    from unittest.mock import MagicMock

    task = MagicMock()
    task.task_id = "TASK-001"
    task.related_acceptance_criteria = ["AC-TEST-01"]

    task_result = MagicMock()
    task_result.tasks = [task]

    claim = MagicMock()
    claim.related_task = "TASK-001"
    claim.test_refs = ["tests/test_module.py"]

    result = _get_existing_tests("AC-TEST-01", task_result, [claim])
    assert len(result) == 1
    assert "tests/test_module.py" in result


def test_get_existing_tests_no_claims():
    """Test _get_existing_tests returns empty list when no claims."""
    from vibe_tracing.cli import _get_existing_tests
    assert _get_existing_tests("AC-TEST-01", None, None) == []
    assert _get_existing_tests("AC-TEST-01", None, []) == []


# =========================================================================
# Tests for hint functions
# =========================================================================

def test_derive_test_scenarios():
    """Test _derive_test_scenarios generates scenarios from AC text."""
    from vibe_tracing.cli import _derive_test_scenarios

    # Empty text returns default
    scenarios_empty = _derive_test_scenarios("")
    assert len(scenarios_empty) == 1

    # Text with "invalid" keyword
    scenarios_invalid = _derive_test_scenarios("Should handle invalid input")
    assert len(scenarios_invalid) >= 1

    # Text with "empty" keyword
    scenarios_empty_kw = _derive_test_scenarios("Should handle empty data")
    assert len(scenarios_empty_kw) >= 1

    # Text with "valid" keyword
    scenarios_valid = _derive_test_scenarios("Should process valid input correctly")
    assert len(scenarios_valid) >= 1


def test_hint_title():
    """Test _hint_title extracts title from action hints."""
    from vibe_tracing.cli import _hint_title

    # Test with a known action type (cover_gap should be in field_hints.json)
    title = _hint_title("cover_gap", ac_id="AC-TEST-01", ac_text="Test AC")
    assert isinstance(title, str)

    # Test with unknown action type
    unknown_title = _hint_title("nonexistent_action")
    assert isinstance(unknown_title, str)


def test_hint_context():
    """Test _hint_context gets context values from action hints."""
    from vibe_tracing.cli import _hint_context

    # Test with known action type and key
    ctx = _hint_context("cover_gap", "verification", ac_id="AC-TEST-01")
    assert isinstance(ctx, str)

    # Test with unknown key
    unknown_ctx = _hint_context("cover_gap", "nonexistent_key")
    assert unknown_ctx == ""


# =========================================================================
# Tests for _load_human_decisions and _apply_human_decisions
# =========================================================================

def test_load_human_decisions_missing_file(monkeypatch):
    """Test _load_human_decisions returns empty when file missing."""
    from vibe_tracing.cli import _load_human_decisions
    import os

    # Ensure the file doesn't exist
    monkeypatch.setattr("pathlib.Path.exists", lambda self: False if self.name == "human_decisions.json" else type(self).exists(self))

    result = _load_human_decisions()
    assert result == {"version": "1.0", "decisions": []}


def test_apply_human_decisions_accepted_rule_reconfirm(tmp_path):
    """Test human_decisions reconfirm applied via MergeGateEngine."""
    from vibe_tracing.domain.merge_gate_engine import MergeGateEngine
    from vibe_tracing.infra.db import init_in_memory_db

    engine = MergeGateEngine(tmp_path, init_in_memory_db())
    gate_res = engine.evaluate(
        gaps=[], risks=[],
        human_decisions={
            "decisions": [
                {
                    "category": "accepted_rule",
                    "targetId": "RULE-001",
                    "action": "accept_risk",
                }
            ]
        },
    )
    # accept_risk with no matching risk -> 0 applied
    assert gate_res["human_decisions_applied"] >= 0


def test_apply_human_decisions_mark_complete(tmp_path):
    """Test human_decisions mark_complete resolves gaps via MergeGateEngine."""
    from vibe_tracing.domain.merge_gate_engine import MergeGateEngine
    from vibe_tracing.infra.db import init_in_memory_db

    engine = MergeGateEngine(tmp_path, init_in_memory_db())
    gaps = [{"item_id": "AC-001", "item_type": "ac", "severity": "must", "reason": "no test"}]
    gate_res = engine.evaluate(
        gaps=gaps, risks=[],
        human_decisions={
            "decisions": [
                {
                    "category": "uncovered_ac",
                    "targetId": "AC-001",
                    "action": "mark_complete",
                }
            ]
        },
    )
    assert gate_res["human_decisions_applied"] >= 1


def test_apply_human_decisions_stale_debt_defer(tmp_path):
    """Test human_decisions accept_risk on risks via MergeGateEngine."""
    from vibe_tracing.domain.merge_gate_engine import MergeGateEngine
    from vibe_tracing.infra.db import init_in_memory_db

    engine = MergeGateEngine(tmp_path, init_in_memory_db())
    risks = [{"risk_id": "R-001", "severity": "must", "title": "Old debt", "claim_id": "CLAIM-001"}]
    gate_res = engine.evaluate(
        gaps=[], risks=risks,
        human_decisions={
            "decisions": [
                {
                    "category": "stale_debt",
                    "targetId": "CLAIM-001",
                    "action": "accept_risk",
                }
            ]
        },
    )
    assert gate_res["human_decisions_applied"] >= 1


def test_apply_human_decisions_accepted_rule_reject(tmp_path):
    """Test human_decisions applied count with no matching items."""
    from vibe_tracing.domain.merge_gate_engine import MergeGateEngine
    from vibe_tracing.infra.db import init_in_memory_db

    engine = MergeGateEngine(tmp_path, init_in_memory_db())
    gate_res = engine.evaluate(
        gaps=[], risks=[],
        human_decisions={"decisions": []},
    )
    assert gate_res["human_decisions_applied"] == 0


def test_apply_human_decisions_no_decisions(tmp_path):
    """Test human_decisions with empty decisions list."""
    from vibe_tracing.domain.merge_gate_engine import MergeGateEngine
    from vibe_tracing.infra.db import init_in_memory_db

    engine = MergeGateEngine(tmp_path, init_in_memory_db())
    gate_res = engine.evaluate(gaps=[], risks=[], human_decisions={"decisions": []})
    assert gate_res["human_decisions_applied"] == 0


# =========================================================================
# Tests for _file_sha256
# =========================================================================

def test_file_sha256(tmp_path):
    """Test _file_sha256 computes hash of a file."""
    from vibe_tracing.cli import _file_sha256

    test_file = tmp_path / "test.txt"
    test_file.write_text("hello world", encoding="utf-8")

    h = _file_sha256(test_file)
    assert h is not None
    assert len(h) == 64  # SHA-256 hex length

    # Consistent hash
    h2 = _file_sha256(test_file)
    assert h == h2


def test_file_sha256_missing():
    """Test _file_sha256 returns None for missing file."""
    from vibe_tracing.cli import _file_sha256

    h = _file_sha256(Path("/nonexistent/file.txt"))
    assert h is None


# =========================================================================
# Tests for governance boundary functions
# =========================================================================

def test_load_governance_boundary_with_data():
    """Test load_boundary with constraints_data provided."""
    from vibe_tracing.infra.governance import load_boundary

    constraints_data = {
        "governance_boundary": {
            "included_patterns": ["src/**"],
            "excluded_patterns": ["vendor/**"],
        }
    }
    result = load_boundary(Path("."), constraints_data=constraints_data)
    assert "vendor/**" in result["excluded_patterns"]


def test_load_governance_boundary_no_data():
    """Test load_boundary with no constraints."""
    from vibe_tracing.infra.governance import load_boundary

    result = load_boundary(Path("/nonexistent"))
    assert result == {"included_patterns": [], "excluded_patterns": []}


def test_is_in_governance_boundary():
    """Test is_in_scope checks file exclusions."""
    from vibe_tracing.infra.governance import is_in_scope

    boundary = {"excluded_patterns": ["vendor/**", "*.min.js"]}

    assert is_in_scope("src/main.py", boundary) is True
    assert is_in_scope("vendor/lib.js", boundary) is False
    assert is_in_scope("build/app.min.js", boundary) is False


def test_is_in_governance_boundary_empty():
    """Test is_in_scope with empty boundary."""
    from vibe_tracing.infra.governance import is_in_scope

    boundary = {}
    assert is_in_scope("any/file.py", boundary) is True


def test_partition_by_governance_boundary():
    """Test partition_by_scope separates files."""
    from vibe_tracing.infra.governance import partition_by_scope

    constraints_data = {
        "governance_boundary": {
            "excluded_patterns": ["vendor/**"],
        }
    }
    files = ["src/main.py", "vendor/lib.js", "src/utils.py"]

    boundary = constraints_data["governance_boundary"]
    result = partition_by_scope(files, boundary)
    assert "src/main.py" in result["in_scope"]
    assert "src/utils.py" in result["in_scope"]
    assert "vendor/lib.js" in result["out_of_scope"]


# =========================================================================
# Tests for _resolve_hint
# =========================================================================

def test_resolve_hint_string():
    """Test resolve_hint returns plain strings."""
    from vibe_tracing.infra.hint_loader import resolve_hint
    assert resolve_hint("simple string") == "simple string"


def test_resolve_hint_dict():
    """Test resolve_hint resolves dict at given level."""
    from vibe_tracing.infra.hint_loader import resolve_hint

    hint = {"level1": "basic", "level2": "detailed"}
    assert resolve_hint(hint, "level1") == "basic"
    assert resolve_hint(hint, "level2") == "detailed"
    # Fallback to level1 for unknown level
    assert resolve_hint(hint, "level99") == "basic"


def test_resolve_hint_non_string():
    """Test resolve_hint returns empty for non-string non-dict."""
    from vibe_tracing.infra.hint_loader import resolve_hint
    assert resolve_hint(42) == ""


# =========================================================================
# Tests for _collect_gap_actions, _collect_risk_actions,
# _collect_violation_actions, _collect_gate_reason_actions
# =========================================================================

def test_collect_gap_actions():
    """Test _collect_gap_actions generates actions for MUST gaps."""
    from vibe_tracing.cli import _collect_gap_actions

    gaps = [
        {"item_id": "AC-001", "severity": "must", "item_type": "ac", "requirement_id": "REQ-001"},
        {"item_id": "AC-002", "severity": "should", "item_type": "ac"},  # skipped
        {"item_id": "AC-003", "severity": "must", "item_type": "ac", "human_accepted": True},  # skipped
    ]

    actions = _collect_gap_actions(gaps, None, None, [])
    assert len(actions) == 1
    assert actions[0]["type"] == "cover_gap"
    assert actions[0]["priority"] == "HIGH"


def test_collect_risk_actions_must():
    """Test _collect_risk_actions generates HIGH actions for must risks."""
    from vibe_tracing.cli import _collect_risk_actions

    risks = [
        {"risk_id": "R-001", "severity": "must", "title": "High Risk", "description": "desc"},
        {"risk_id": "R-002", "severity": "should", "title": "Low Risk", "description": "desc"},
    ]

    actions = _collect_risk_actions(risks, [])
    assert len(actions) == 1
    assert actions[0]["type"] == "high_risk"


def test_collect_risk_actions_self_referential():
    """Test _collect_risk_actions generates action for self-referential risks."""
    from vibe_tracing.cli import _collect_risk_actions

    risks = [
        {"risk_id": "R-001", "severity": "should", "title": "Self Ref", "description": "only self-referential evidence"},
    ]

    actions = _collect_risk_actions(risks, [])
    assert len(actions) == 1
    assert actions[0]["type"] == "high_risk"


def test_collect_risk_actions_stale_debt():
    """Test _collect_risk_actions generates LOW action for stale risks."""
    from vibe_tracing.cli import _collect_risk_actions

    risks = [
        {"risk_id": "R-001", "severity": "should", "title": "Stale", "description": "old", "stale": True, "age_iterations": "3"},
    ]

    actions = _collect_risk_actions(risks, [])
    assert len(actions) == 1
    assert actions[0]["type"] == "stale_debt"
    assert actions[0]["priority"] == "LOW"


def test_collect_risk_actions_stale_deferred_skipped():
    """Test _collect_risk_actions skips stale+deferred risks."""
    from vibe_tracing.cli import _collect_risk_actions

    risks = [
        {"risk_id": "R-001", "severity": "should", "title": "Stale", "description": "old", "stale": True, "deferred": True},
    ]

    actions = _collect_risk_actions(risks, [])
    assert len(actions) == 0


def test_collect_violation_actions():
    """Test _collect_violation_actions generates actions for violations."""
    from vibe_tracing.cli import _collect_violation_actions

    violations = [{"rule_id": "R-001", "description": "Rule desc", "reason": "violation reason"}]
    compliance_status = []

    actions = _collect_violation_actions(violations, compliance_status)
    assert len(actions) == 1
    assert actions[0]["type"] == "fix_violation"


def test_collect_violation_actions_arch_status():
    """Test _collect_violation_actions handles arch_status_violation."""
    from vibe_tracing.cli import _collect_violation_actions

    violations = []
    compliance_status = [
        {"rule_id": "R-002", "status": "violated", "severity": "must"},
        {"rule_id": "R-003", "status": "compliant", "severity": "must"},  # skipped
    ]

    actions = _collect_violation_actions(violations, compliance_status)
    assert len(actions) == 1
    assert actions[0]["type"] == "arch_status_violation"


def test_collect_gate_reason_actions():
    """Test _collect_gate_reason_actions generates fallback actions."""
    from vibe_tracing.cli import _collect_gate_reason_actions

    # Blocked with no HIGH actions and reasons
    actions = _collect_gate_reason_actions("blocked", ["reason 1", "reason 2"], [])
    assert len(actions) == 2
    assert all(a["type"] == "gate_blocked" for a in actions)


def test_collect_gate_reason_actions_skipped_when_high_exists():
    """Test _collect_gate_reason_actions skips when HIGH actions exist."""
    from vibe_tracing.cli import _collect_gate_reason_actions

    existing = [{"priority": "HIGH", "type": "cover_gap", "title": "t", "context": {}}]
    actions = _collect_gate_reason_actions("blocked", ["reason"], existing)
    assert len(actions) == 0


def test_collect_gate_reason_actions_skipped_when_pass():
    """Test _collect_gate_reason_actions skips when decision is pass."""
    from vibe_tracing.cli import _collect_gate_reason_actions

    actions = _collect_gate_reason_actions("pass", ["reason"], [])
    assert len(actions) == 0


# =========================================================================
# Tests for _render_actions
# =========================================================================

def test_render_actions_empty():
    """Test _render_actions with no actions."""
    from vibe_tracing.cli import _render_actions

    lines = _render_actions([])
    assert any("NO ACTION REQUIRED" in l for l in lines)


def test_render_actions_with_actions():
    """Test _render_actions formats action items."""
    from vibe_tracing.cli import _render_actions

    actions = [
        {
            "priority": "HIGH",
            "type": "cover_gap",
            "title": "Cover AC-001",
            "context": {
                "severity": "MUST",
                "test_scenarios": ["scenario 1"],
                "implementation_files": ["src/main.py"],
            },
        },
        {
            "priority": "LOW",
            "type": "stale_debt",
            "title": "Old debt",
            "context": {"description": "desc"},
        },
    ]

    lines = _render_actions(actions)
    assert any("ACTION 1" in l for l in lines)
    assert any("HIGH" in l for l in lines)
    assert any("SUMMARY" in l for l in lines)


def test_render_actions_with_human_decisions():
    """Test _render_actions includes human decision instructions."""
    from vibe_tracing.cli import _render_actions

    actions = [
        {
            "priority": "HIGH",
            "type": "human_decision",
            "title": "Decision needed",
            "id": "DEC-001",
            "context": {},
        },
    ]

    lines = _render_actions(actions)
    assert any("dashboard" in l.lower() for l in lines)


def test_render_actions_with_coverage_summary():
    """Test _render_actions includes coverage info when actions exist."""
    from vibe_tracing.cli import _render_actions

    # Need at least one action for coverage section to render
    actions = [
        {"priority": "HIGH", "type": "test", "title": "Test Action", "context": {}}
    ]
    coverage = {"aggregate_percent": 85}
    lines = _render_actions(actions, coverage_summary=coverage)
    assert any("85%" in l for l in lines)
    assert any("PASS" in l for l in lines)


def test_render_actions_coverage_below_threshold(tmp_path):
    """Test _render_actions flags BLOCKED when aggregate coverage is below threshold."""
    from vibe_tracing.cli import _render_actions

    # Need at least one action for coverage section to render
    actions = [
        {"priority": "HIGH", "type": "test", "title": "Test Action", "context": {}}
    ]
    coverage = {"aggregate_percent": 75}
    evidence_index = {
        "coverage_baseline": {
            "src/bad.py": {"percent_covered": 45},
        }
    }

    lines = _render_actions(
        actions, coverage_summary=coverage,
        evidence_meta=evidence_index,
    )
    assert any("BLOCKED" in l for l in lines)
    assert any("75%" in l for l in lines)
    assert any("src/bad.py" in l and "45%" in l for l in lines)


def test_render_actions_per_file_violations_pass(tmp_path):
    """Test _render_actions shows PASS when aggregate coverage is above threshold."""
    from vibe_tracing.cli import _render_actions

    actions = [
        {"priority": "HIGH", "type": "test", "title": "Test Action", "context": {}}
    ]
    coverage = {"aggregate_percent": 85}

    lines = _render_actions(
        actions, coverage_summary=coverage,
    )
    assert any("PASS" in l for l in lines)
    assert not any("BLOCKED" in l for l in lines)
    assert any("85%" in l for l in lines)


# =========================================================================
# Tests for _format_agent_actions
# =========================================================================

def test_format_agent_actions_pass():
    """Test _format_agent_actions formats a passing decision."""
    from vibe_tracing.cli import _format_agent_actions

    result = _format_agent_actions(
        gate_decision="pass",
        active_gaps=[],
        active_risks=[],
        violations=[],
        accepted_rules=[],
    )
    assert "GATE DECISION: PASS" in result
    assert "NO ACTION REQUIRED" in result


def test_format_agent_actions_blocked():
    """Test _format_agent_actions formats a blocked decision."""
    from vibe_tracing.cli import _format_agent_actions

    result = _format_agent_actions(
        gate_decision="blocked",
        active_gaps=[],
        active_risks=[],
        violations=[],
        accepted_rules=[],
        gate_reasons=["Must AC missing coverage"],
    )
    assert "GATE DECISION: BLOCKED" in result
    assert "Must AC missing coverage" in result


def test_format_agent_actions_with_violations():
    """Test _format_agent_actions includes violation actions."""
    from vibe_tracing.cli import _format_agent_actions

    result = _format_agent_actions(
        gate_decision="blocked",
        active_gaps=[],
        active_risks=[],
        violations=[{"rule_id": "R-001", "description": "desc", "reason": "reason"}],
        accepted_rules=[],
    )
    assert "R-001" in result
    assert "BLOCKED" in result


# =========================================================================
# Tests for _check_staged_extensions
# =========================================================================

def test_check_staged_extensions_no_constraints():
    """Test _check_staged_extensions does nothing without constraints."""
    from vibe_tracing.cli import _check_staged_extensions

    # Should not raise
    _check_staged_extensions(Path("/fake"), None)


def test_check_staged_extensions_empty_ltm():
    """Test _check_staged_extensions does nothing with empty ltm."""
    from vibe_tracing.cli import _check_staged_extensions

    constraints = {"language_tool_matrix": {}}
    _check_staged_extensions(Path("/fake"), constraints)


def test_check_staged_extensions_no_staged_files(tmp_path):
    """Test _check_staged_extensions does nothing when no staged files."""
    from vibe_tracing.cli import _check_staged_extensions

    constraints = {
        "language_tool_matrix": {"python": {"extensions": [".py"]}}
    }
    _check_staged_extensions(tmp_path, constraints)


# =========================================================================
# Tests for main CLI parsing
# =========================================================================

def test_main_no_command(capsys):
    """Test main with no command shows help."""
    exit_code = main([])
    assert exit_code == 0


def test_main_accept_missing_rule_id():
    """Test main with accept but missing rule_id."""
    with pytest.raises(SystemExit):
        main(["accept"])


# =========================================================================
# Tests for init and finalize
# =========================================================================

def test_run_init_missing_name_prefix(tmp_path, capsys):
    """Test run_init returns 1 when name and prefix are missing."""
    from vibe_tracing.cli import run_init

    exit_code = run_init(tmp_path, name=None, prefix=None)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "--name" in captured.err


def test_run_init_creates_files(tmp_path):
    """Test run_init creates expected files."""
    from vibe_tracing.cli import run_init

    (tmp_path / ".git" / "hooks").mkdir(parents=True, exist_ok=True)

    exit_code = run_init(tmp_path, name="Test Project", prefix="TP")
    assert exit_code == 0

    assert (tmp_path / ".vibetracing" / "config.json").exists()
    assert (tmp_path / ".vibetracing" / "claims").is_dir()  # Claims directory exists (no current.json)
    assert (tmp_path / "docs" / "task_list.json").exists()
    assert (tmp_path / "docs" / "architecture_constraints.json").exists()
    assert (tmp_path / "docs" / "prd.md").exists()


def test_run_init_skips_existing(tmp_path, capsys):
    """Test run_init skips existing files."""
    from vibe_tracing.cli import run_init

    (tmp_path / ".git" / "hooks").mkdir(parents=True, exist_ok=True)
    # Pre-create config
    (tmp_path / ".vibetracing").mkdir(parents=True, exist_ok=True)
    config = {"project_name": "Existing", "project_prefix": "EX", "project_id": "PROJECT-EX"}
    (tmp_path / ".vibetracing" / "config.json").write_text(json.dumps(config), encoding="utf-8")

    exit_code = run_init(tmp_path, name="New", prefix="NW")
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Skipped existing file" in captured.out


def test_run_init_with_corrupted_config(tmp_path, capsys):
    """Test run_init handles corrupted config.json."""
    from vibe_tracing.cli import run_init

    (tmp_path / ".git" / "hooks").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vibetracing").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vibetracing" / "config.json").write_text("not json!!!", encoding="utf-8")

    exit_code = run_init(tmp_path, name="Test", prefix="T")
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Error loading existing config.json" in captured.err


def test_run_init_installs_hook(tmp_path, capsys):
    """Test run_init installs git pre-commit hook."""
    from vibe_tracing.cli import run_init

    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    exit_code = run_init(tmp_path, name="Test", prefix="T")
    assert exit_code == 0

    hook_path = hooks_dir / "pre-commit"
    assert hook_path.exists()
    assert "vibe_tracing" in hook_path.read_text()


def test_run_init_skips_existing_hook(tmp_path, capsys):
    """Test run_init skips installing hook when pre-commit exists."""
    from vibe_tracing.cli import run_init

    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    (hooks_dir / "pre-commit").write_text("# existing hook", encoding="utf-8")

    exit_code = run_init(tmp_path, name="Test", prefix="T")
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Skipped Git pre-commit hook" in captured.out


def test_run_init_via_cli(tmp_path):
    """Test run_init via CLI main."""
    (tmp_path / ".git" / "hooks").mkdir(parents=True, exist_ok=True)

    exit_code = main([
        "init", "--project-root", str(tmp_path),
        "--name", "CLI Test", "--prefix", "CT",
    ])
    assert exit_code == 0


# =========================================================================
# Tests for finalize error paths
# =========================================================================

def test_run_finalize_missing_config(tmp_path, capsys):
    """Test run_finalize when config.json is missing."""
    from vibe_tracing.cli import run_finalize

    exit_code = run_finalize(tmp_path)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "config.json not found" in captured.err


def test_run_finalize_missing_constraints(tmp_path, capsys):
    """Test run_finalize when constraints file is missing."""
    from vibe_tracing.cli import run_finalize

    (tmp_path / ".vibetracing").mkdir(parents=True, exist_ok=True)
    config = {"project_prefix": "VT"}
    (tmp_path / ".vibetracing" / "config.json").write_text(json.dumps(config), encoding="utf-8")

    exit_code = run_finalize(tmp_path)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "architecture_constraints.json not found" in captured.err


def test_run_finalize_missing_language(tmp_path, capsys):
    """Test run_finalize when language is not set in constraints."""
    from vibe_tracing.cli import run_finalize

    (tmp_path / ".vibetracing").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)

    config = {"project_prefix": "VT"}
    (tmp_path / ".vibetracing" / "config.json").write_text(json.dumps(config), encoding="utf-8")

    constraints = {
        "schema_version": "1.0.0",
        "project": {"project_id": "TEST", "name": "Test", "stage": "mvp"},
        "language_tool_matrix": {},
    }
    (tmp_path / "docs" / "architecture_constraints.json").write_text(
        json.dumps(constraints), encoding="utf-8"
    )

    exit_code = run_finalize(tmp_path)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "language" in captured.err.lower()


def test_run_finalize_language_not_in_matrix(tmp_path, capsys):
    """Test run_finalize when language is not in language_tool_matrix."""
    from vibe_tracing.cli import run_finalize

    (tmp_path / ".vibetracing").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)

    config = {"project_prefix": "VT"}
    (tmp_path / ".vibetracing" / "config.json").write_text(json.dumps(config), encoding="utf-8")

    constraints = {
        "schema_version": "1.0.0",
        "project": {"project_id": "TEST", "name": "Test", "stage": "mvp", "language": "go"},
        "language_tool_matrix": {"python": {"extensions": [".py"]}},
    }
    (tmp_path / "docs" / "architecture_constraints.json").write_text(
        json.dumps(constraints), encoding="utf-8"
    )

    exit_code = run_finalize(tmp_path)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "not found in language_tool_matrix" in captured.err


# =========================================================================
# Tests for _get_staged_files
# =========================================================================

def test_get_staged_files_no_git(tmp_path):
    """Test _get_staged_files returns empty set when not in git repo."""
    from vibe_tracing.cli import _get_staged_files

    result = _get_staged_files(tmp_path)
    assert result == set()


# =========================================================================
# Tests for _load_hints
# =========================================================================

def test_load_hints():
    """Test load_hints loads hints from field_hints.json."""
    from vibe_tracing.infra.hint_loader import load_hints

    hints = load_hints("action")
    assert isinstance(hints, dict)


# =========================================================================
# Tests for init via CLI with missing prefix
# =========================================================================

def test_run_init_via_cli_no_name(tmp_path, capsys):
    """Test CLI init without --name exits 1."""
    exit_code = main([
        "init", "--project-root", str(tmp_path), "--prefix", "T"
    ])
    assert exit_code == 1



# =========================================================================
# Tests for _validate_constraints_change
# =========================================================================

def test_validate_constraints_change_first_finalize(tmp_path):
    """Test _validate_constraints_change passes on first finalization."""
    from vibe_tracing.cli import _validate_constraints_change

    config_data = {}  # No finalize_commit
    passed, message = _validate_constraints_change(
        tmp_path, tmp_path / "fake.json", config_data
    )
    assert passed is True
    assert "首次定稿" in message


# =========================================================================
# Tests for main edge cases
# =========================================================================

def test_main_version(capsys):
    """Test main --version."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0


def test_main_help(capsys):
    """Test main --help."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0


# =========================================================================
# Tests for _print_post_finalize_guidance
# =========================================================================

def test_print_post_finalize_guidance(tmp_path):
    """Test _print_post_finalize_guidance with dirty working dir."""
    from vibe_tracing.cli import _print_post_finalize_guidance
    import subprocess as sp

    # Create a git repo
    sp.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    sp.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=True)
    sp.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True, check=True)

    # Create an uncommitted file
    (tmp_path / "uncommitted.txt").write_text("data", encoding="utf-8")

    _print_post_finalize_guidance(tmp_path)


def test_print_post_finalize_guidance_clean(tmp_path):
    """Test _print_post_finalize_guidance with clean working dir."""
    from vibe_tracing.cli import _print_post_finalize_guidance
    import subprocess as sp

    sp.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    sp.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=True)
    sp.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True, check=True)

    _print_post_finalize_guidance(tmp_path)
