import json
from pathlib import Path
import pytest
from vibe_tracing.cli import main
from vibe_tracing.schema_validator import SchemaValidator


@pytest.fixture(autouse=True)
def mock_tool_execution(monkeypatch):
    from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine, ToolEvidenceCandidate
    from vibe_tracing.core.enums import CoverageStatus
    import json

    def mock_execute_all(self, execution_paths):
        opts_path = self.project_root / "test_opts.json"
        if not opts_path.exists():
            return []
        opts = json.loads(opts_path.read_text(encoding="utf-8"))
        docstring = opts.get("test_docstring", "")
        import re
        covers = re.findall(r"\b(AC-VT-\d+-\d+|REQ-VT-\d+)\b", docstring)
        return [
            ToolEvidenceCandidate(
                source_type="test",
                source_path="tests/test_ids_and_enums.py::test_req_id_valid",
                covers=covers,
                status=CoverageStatus.COVERED.value if opts.get("test_outcome") == "passed" else CoverageStatus.VIOLATED.value,
            )
        ]

    monkeypatch.setattr(ToolExecutionEngine, "execute_all", mock_execute_all)


def setup_mock_project(
    base: Path,
    task_status: str = "done",
    test_outcome: str = "passed",
    test_docstring: str = "covers: AC-VT-001-01, AC-VT-001-02",
    include_claims: bool = True,
    claim_has_evidence: bool = True,
    architecture_constraints: str = "{}",
    claim_timestamp: str = "2030-05-22T12:00:00Z",
) -> None:
    """Helper to set up a mock project structure with valid inputs."""
    # Create directories
    (base / "docs").mkdir(parents=True, exist_ok=True)
    (base / "output").mkdir(parents=True, exist_ok=True)
    (base / "schemas").mkdir(parents=True, exist_ok=True)
    (base / ".vibetracing").mkdir(parents=True, exist_ok=True)
    (base / "src" / "vibe_tracing" / "core").mkdir(parents=True, exist_ok=True)

    # Write a dummy dashboard.html to prevent DEP-VT-002 from being unclear/violated
    (base / "dashboard.html").write_text("<html></html>", encoding="utf-8")

    # Copy real schemas to mock project so schema validator can load them
    real_schemas = Path(__file__).parent.parent / "src" / "vibe_tracing" / "schemas"
    for schema_file in real_schemas.glob("*.json"):
        (base / "schemas" / schema_file.name).write_text(
            schema_file.read_text(encoding="utf-8")
        )

    # Write PRD
    prd_content = """# Vibe Tracing PRD
### REQ-VT-001: 全链路需求追踪
#### 优先级
must

##### AC-VT-001-01: 需求必须能关联任务
* 是否必须有测试：是

##### AC-VT-001-02: 验收标准必须能关联测试
* 是否必须有测试：是
"""
    (base / "docs" / "prd.md").write_text(prd_content, encoding="utf-8")
    (base / "docs" / "architecture_change_log.md").write_text(
        "# Architecture Change Log\n", encoding="utf-8"
    )

    # Create referenced code file to prevent claim validation errors
    (base / "src" / "vibe_tracing" / "core" / "ids.py").write_text(
        "# dummy file for testing", encoding="utf-8"
    )

    # Write Architecture Constraints
    try:
        data = json.loads(architecture_constraints)
        if isinstance(data, dict):
            if "schema_version" not in data:
                data["schema_version"] = "1.0.0"
            if "project" not in data:
                data["project"] = {
                    "project_id": "PROJECT-VT",
                    "name": "Vibe Tracing",
                    "stage": "mvp"
                }
            if "language" not in data["project"]:
                data["project"]["language"] = "python"
            if "language_tool_matrix" not in data:
                data["language_tool_matrix"] = {
                    "python": {
                        "test": {
                            "tool": "pytest",
                            "default_command": "pytest",
                            "output_format": "pytest_json",
                            "pass_condition": "exit_code == 0"
                        }
                    }
                }
            architecture_constraints = json.dumps(data)
    except Exception:
        pass
    (base / "docs" / "architecture_constraints.json").write_text(
        architecture_constraints, encoding="utf-8"
    )

    # Write base config.json (run_finalize will populate language, tools, hash)
    config_data = {
        "project_id": "PROJECT-VT",
        "project_prefix": "VT",
        "project_name": "Vibe Tracing",
    }
    (base / ".vibetracing" / "config.json").write_text(
        json.dumps(config_data, indent=2), encoding="utf-8"
    )

    # Finalize to populate language, validation_tools, architecture_constraints_hash, etc.
    from vibe_tracing.cli import run_finalize
    run_finalize(base)

    # Write test_opts.json for mocked tool execution
    opts = {
        "test_outcome": test_outcome,
        "test_docstring": test_docstring,
    }
    (base / "test_opts.json").write_text(json.dumps(opts), encoding="utf-8")

    # Write Task List
    task_list = {
        "schema_version": "0.1",
        "project": {"project_id": "PROJECT-VT", "name": "Vibe Tracing", "stage": "mvp"},
        "tasks": [
            {
                "task_id": "TASK-VT-001",
                "title": "Setup Core",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": task_status,
                "owner_role": "agent",
                "objective": "Setup codebase structure",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
            {
                "task_id": "TASK-VT-002",
                "title": "Write Tests",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": task_status,
                "owner_role": "agent",
                "objective": "Write core tests",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-02"],
                "definition_of_done": [],
            },
        ],
    }
    (base / "docs" / "task_list.json").write_text(
        json.dumps(task_list), encoding="utf-8"
    )

    # Write Agent Claims
    if include_claims:
        evidence_refs = ["EVIDENCE-VT-005"] if claim_has_evidence else []
        agent_claims = [
            {
                "claim_id": "CLAIM-VT-001",
                "related_task": "TASK-VT-001",
                "claimed_status": "covered",
                "evidence_refs": evidence_refs,
                "timestamp": claim_timestamp,
                "code_refs": ["src/vibe_tracing/core/ids.py#L1-L10"],
                "test_refs": [],
                "notes": "Core implemented successfully",
            }
        ]
        (base / ".vibetracing" / "agent_claims.json").write_text(
            json.dumps(agent_claims), encoding="utf-8"
        )
    else:
        (base / ".vibetracing" / "agent_claims.json").write_text("[]", encoding="utf-8")



def test_cli_analyze_pass(tmp_path, capsys):
    """
    covers: AC-VT-009-01, AC-VT-009-02, AC-VT-008-03
    Test a fully passing project: gate engine returns PASS, CLI exits 0.
    Ensures all three json output files are generated, schema-compliant, and contain the expected fields.
    """
    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01\ncovers: AC-VT-001-02",
        include_claims=True,
        claim_has_evidence=True,
    )

    exit_code = main(["analyze", "--project-root", str(tmp_path)])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Analysis complete. Gate decision: PASS" in captured.out

    # Check generated files
    evidence_index_path = tmp_path / "output" / "evidence_index.json"
    traceability_report_path = (
        tmp_path / "output" / "traceability_report.json"
    )
    run_metadata_path = tmp_path / "output" / "run_metadata.json"

    assert evidence_index_path.exists()
    assert traceability_report_path.exists()
    assert run_metadata_path.exists()

    # Validate schema compliance
    validator = SchemaValidator()
    val_ev = validator.validate_file(evidence_index_path, "evidence_index")
    assert val_ev.is_valid is True, val_ev.message

    val_rep = validator.validate_file(traceability_report_path, "traceability_report")
    assert val_rep.is_valid is True, val_rep.message

    # Validate run metadata structure
    meta = json.loads(run_metadata_path.read_text(encoding="utf-8"))
    assert "run_id" in meta
    assert meta["project_id"] == "PROJECT-VT"
    assert "scan_time" in meta
    assert meta["gate_decision"] == "pass"
    assert meta["exit_code"] == 0
    assert "input_files" in meta
    assert "output_files" in meta
    assert "summary" in meta


def test_cli_analyze_blocked(tmp_path, capsys):
    """
    covers: AC-VT-008-01, AC-VT-008-02, AC-VT-009-02, AC-VT-008-03
    Test a blocked project: a MUST AC is missing test coverage. CLI exits with 2.
    """
    # AC-VT-001-02 needs a passing test, but the pytest report only covers AC-VT-001-01
    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01",
        include_claims=True,
        claim_has_evidence=True,
    )

    exit_code = main(["analyze", "--project-root", str(tmp_path)])
    assert exit_code == 2

    captured = capsys.readouterr()
    assert "Analysis complete. Gate decision: BLOCKED" in captured.out
    assert "验收标准缺失测试证据 (AC-VT-001-02)" in captured.out

    # Files should still be generated
    traceability_report_path = (
        tmp_path / "output" / "traceability_report.json"
    )
    run_metadata_path = tmp_path / "output" / "run_metadata.json"

    assert traceability_report_path.exists()
    assert run_metadata_path.exists()

    rep = json.loads(traceability_report_path.read_text(encoding="utf-8"))
    assert rep["gate_decision"] == "blocked"

    meta = json.loads(run_metadata_path.read_text(encoding="utf-8"))
    assert meta["gate_decision"] == "blocked"
    assert meta["exit_code"] == 2


def test_cli_analyze_fail_conditional(tmp_path, capsys):
    """
    covers: AC-VT-008-03, AC-VT-009-02
    Test a conditional project: contains Should-level issues, CLI exits with 0 but decision is FAIL.
    """
    # Make tasks SHOULD instead of MUST so gaps are Should-level, causing a conditional fail decision
    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01\ncovers: AC-VT-001-02",
        include_claims=True,
        claim_has_evidence=True,
        claim_timestamp="2020-05-22T12:00:00Z",
    )

    exit_code = main(["analyze", "--project-root", str(tmp_path)])
    assert exit_code == 0  # Conditional fail exits with 0

    captured = capsys.readouterr()
    assert "Analysis complete. Gate decision: FAIL" in captured.out

    # Files should still be generated
    traceability_report_path = (
        tmp_path / "output" / "traceability_report.json"
    )
    run_metadata_path = tmp_path / "output" / "run_metadata.json"

    assert traceability_report_path.exists()
    assert run_metadata_path.exists()

    rep = json.loads(traceability_report_path.read_text(encoding="utf-8"))
    assert rep["gate_decision"] == "fail"

    meta = json.loads(run_metadata_path.read_text(encoding="utf-8"))
    assert meta["gate_decision"] == "fail"
    assert meta["exit_code"] == 0


def test_cli_analyze_missing_required_file(tmp_path, capsys):
    """
    covers: AC-VT-009-02
    Test CLI behavior when a required input file is missing. CLI must exit with 1.
    """
    setup_mock_project(tmp_path)
    # Remove the PRD file
    prd_file = tmp_path / "docs" / "prd.md"
    prd_file.unlink()

    exit_code = main(["analyze", "--project-root", str(tmp_path)])
    assert exit_code == 1

    captured = capsys.readouterr()
    # Expect error message about missing file
    assert "Error loading required file prd" in captured.err


def test_cli_analyze_invalid_schema(tmp_path, capsys):
    """
    covers: AC-VT-009-02
    Test CLI behavior when an input file violates its JSON schema. CLI must exit with 1.
    """
    setup_mock_project(tmp_path)
    # Write invalid task list that violates task_list schema (missing project field)
    invalid_task_list = {"schema_version": "0.1", "tasks": []}
    task_list_path = tmp_path / "docs" / "task_list.json"
    task_list_path.write_text(json.dumps(invalid_task_list), encoding="utf-8")

    exit_code = main(["analyze", "--project-root", str(tmp_path)])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "Schema validation failed for task list" in captured.err


def test_cli_analyze_custom_output_dir(tmp_path):
    """
    covers: AC-VT-009-02
    Test CLI analyze command with a custom output directory flag `--out`.
    """
    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01\ncovers: AC-VT-001-02",
    )

    custom_out = tmp_path / "custom_output"
    exit_code = main(
        ["analyze", "--project-root", str(tmp_path), "--out", str(custom_out)]
    )
    assert exit_code == 0

    assert (custom_out / "evidence_index.json").exists()
    assert (custom_out / "traceability_report.json").exists()
    assert (custom_out / "run_metadata.json").exists()
