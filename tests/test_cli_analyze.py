import hashlib
import json
from pathlib import Path
import pytest
from vibe_tracing.cli import main
from vibe_tracing.schema_validator import SchemaValidator


@pytest.fixture(autouse=True)
def mock_tool_execution(request, monkeypatch):
    import shutil
    from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine, ToolEvidenceCandidate
    from vibe_tracing.core.enums import CoverageStatus
    import json

    # Mock shutil.which so the pre-flight dependency check passes
    # even when tools like pytest/mypy are not installed in the test env.
    # Skip this mock when test is marked with no_mock_which.
    if not request.node.get_closest_marker("no_mock_which"):
        _real_which = shutil.which
        def mock_which(cmd):
            return _real_which(cmd) or f"/usr/bin/{cmd}"
        monkeypatch.setattr(shutil, "which", mock_which)

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
#### 类别
functional
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
                        "extensions": [".py"],
                        "test": {
                            "tool": "pytest",
                            "default_command": "pytest",
                            "output_format": "pytest_json",
                            "pass_condition": "exit_code == 0"
                        }
                    }
                }
            if "module_boundaries" not in data:
                data["module_boundaries"] = [
                    {
                        "module_id": "MOD-VT-001",
                        "name": "Core Module",
                        "responsibility": "Core feature implementation",
                        "related_requirements": ["REQ-VT-001"],
                    }
                ]
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

    # Ensure finalize_git_commit is set (tmp dirs are not git repos, so run_finalize
    # writes null; the anti-corruption layer in run_analyze requires it when hash exists).
    cfg_path = base / ".vibetracing" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if not cfg.get("finalize_git_commit"):
        cfg["finalize_git_commit"] = "test_commit_hash"
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

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

    assert evidence_index_path.exists()
    assert traceability_report_path.exists()

    # Validate schema compliance
    validator = SchemaValidator()
    val_ev = validator.validate_file(evidence_index_path, "evidence_index")
    assert val_ev.is_valid is True, val_ev.message

    val_rep = validator.validate_file(traceability_report_path, "traceability_report")
    assert val_rep.is_valid is True, val_rep.message

    # Validate run metadata embedded in traceability report
    report = json.loads(traceability_report_path.read_text(encoding="utf-8"))
    assert "metadata" in report
    meta = report["metadata"]
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

    assert traceability_report_path.exists()

    rep = json.loads(traceability_report_path.read_text(encoding="utf-8"))
    assert rep["gate_decision"] == "blocked"

    meta = rep["metadata"]
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

    assert traceability_report_path.exists()

    rep = json.loads(traceability_report_path.read_text(encoding="utf-8"))
    assert rep["gate_decision"] == "fail"

    meta = rep["metadata"]
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


def test_prd_drift_detection(tmp_path, capsys):
    """
    Test that modifying PRD after finalize triggers a drift WARNING but does NOT block.
    Exit code must be 0 (warning only).
    """
    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01\ncovers: AC-VT-001-02",
        include_claims=True,
        claim_has_evidence=True,
    )

    # Compute the original PRD hash and store it in config.json (simulates finalize baseline)
    prd_path = tmp_path / "docs" / "prd.md"
    original_hash = hashlib.sha256(prd_path.read_bytes()).hexdigest()

    cfg_path = tmp_path / ".vibetracing" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["prd_hash"] = original_hash
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # Modify the PRD to trigger drift
    prd_path.write_text(
        prd_path.read_text(encoding="utf-8") + "\n<!-- drift -->\n",
        encoding="utf-8",
    )

    exit_code = main(["analyze", "--project-root", str(tmp_path)])

    # Warning only, must NOT block
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "PRD 已从基线漂移" in captured.err


def test_mapping_dead_link_blocks(tmp_path, capsys):
    """
    Test that architecture constraints referencing a non-existent PRD requirement
    (dead link) blocks the analysis with exit code 1.
    """
    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01\ncovers: AC-VT-001-02",
        include_claims=True,
        claim_has_evidence=True,
    )

    # Remove stored hash so Gate 1 (tampering check) doesn't block on modified constraints
    cfg_path = tmp_path / ".vibetracing" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.pop("architecture_constraints_hash", None)
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # Modify architecture constraints to reference a REQ that doesn't exist in PRD
    arch_path = tmp_path / "docs" / "architecture_constraints.json"
    arch = json.loads(arch_path.read_text(encoding="utf-8"))
    arch["module_boundaries"][0]["related_requirements"] = ["REQ-VT-999"]
    arch_path.write_text(json.dumps(arch, indent=2), encoding="utf-8")

    exit_code = main(["analyze", "--project-root", str(tmp_path)])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "BLOCKED" in captured.err
    assert "死链" in captured.err


def test_mapping_must_uncovered_blocks(tmp_path, capsys):
    """
    Test that a MUST-level PRD requirement without architecture support
    blocks the analysis with exit code 1.
    """
    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01\ncovers: AC-VT-001-02",
        include_claims=True,
        claim_has_evidence=True,
    )

    # Remove stored hash so Gate 1 (tampering check) doesn't block
    cfg_path = tmp_path / ".vibetracing" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.pop("architecture_constraints_hash", None)
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # Add a new MUST requirement to PRD without a corresponding architecture module
    prd_path = tmp_path / "docs" / "prd.md"
    prd_path.write_text(
        prd_path.read_text(encoding="utf-8")
        + "\n### REQ-VT-002: 新增MUST需求\n#### 类别\nfunctional\n#### 优先级\nmust\n\n"
        "##### AC-VT-002-01: 验收标准\n* 是否必须有测试：是\n",
        encoding="utf-8",
    )

    exit_code = main(["analyze", "--project-root", str(tmp_path)])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "BLOCKED" in captured.err
    assert "MUST" in captured.err
    assert "无架构支撑" in captured.err


def test_mapping_should_uncovered_warns(tmp_path, capsys):
    """
    Test that a SHOULD-level PRD requirement without architecture mapping
    produces a WARNING but does NOT block (exit code 0).
    """
    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01\ncovers: AC-VT-001-02",
        include_claims=True,
        claim_has_evidence=True,
    )

    # Remove stored hash so Gate 1 (tampering check) doesn't block
    cfg_path = tmp_path / ".vibetracing" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.pop("architecture_constraints_hash", None)
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # Add a new SHOULD requirement to PRD without architecture mapping
    prd_path = tmp_path / "docs" / "prd.md"
    prd_path.write_text(
        prd_path.read_text(encoding="utf-8")
        + "\n### REQ-VT-002: 新增SHOULD需求\n#### 类别\nfunctional\n#### 优先级\nshould\n\n"
        "##### AC-VT-002-01: 验收标准\n* 是否必须有测试：否\n",
        encoding="utf-8",
    )

    exit_code = main(["analyze", "--project-root", str(tmp_path)])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "WARNING" in captured.err


def test_gates_only_skips_analysis(tmp_path, capsys):
    """
    Test that --gates-only runs only integrity gates and skips the full analysis.
    With --pre-commit, gates 2/2.5 also run; with --gates-only, the pipeline
    returns 0 immediately after gates complete.
    """
    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01\ncovers: AC-VT-001-02",
        include_claims=True,
        claim_has_evidence=True,
    )

    exit_code = main([
        "analyze", "--project-root", str(tmp_path),
        "--pre-commit", "--gates-only",
    ])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Gates-only mode: integrity gates passed. Skipping analysis." in captured.out
    # Full analysis output should NOT appear
    assert "Analysis complete. Gate decision:" not in captured.out

    # No output files should be generated (evidence_index, traceability_report, etc.)
    output_dir = tmp_path / "output"
    assert not (output_dir / "evidence_index.json").exists()
    assert not (output_dir / "traceability_report.json").exists()


@pytest.mark.no_mock_which
def test_missing_tools_produces_blocked_evidence(tmp_path, capsys, monkeypatch):
    """
    covers: AC-VT-009-02
    Test that missing tools produce BLOCKED evidence entries in the evidence index
    instead of hard-exiting with exit code 1. The exit code should be determined
    by the gate engine based on the blocked evidence.
    """
    import shutil

    # Mock shutil.which to return None for ALL tools (simulate missing tools)
    monkeypatch.setattr(shutil, "which", lambda cmd: None)

    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01\ncovers: AC-VT-001-02",
        include_claims=True,
        claim_has_evidence=True,
    )

    # Should NOT exit 1 (that was the old hard-exit behavior).
    # Exit code is determined by gate engine (0 for pass/fail, 2 for blocked).
    exit_code = main(["analyze", "--project-root", str(tmp_path)])

    captured = capsys.readouterr()

    # Repair guide should still be printed
    assert "AI Agent Repair Guide" in captured.err

    # Evidence index should exist and contain BLOCKED entries for missing tools
    evidence_index_path = tmp_path / "output" / "evidence_index.json"
    assert evidence_index_path.exists(), "evidence_index.json should be generated"

    evidence_index = json.loads(evidence_index_path.read_text(encoding="utf-8"))
    evidences = evidence_index.get("evidences", [])

    blocked_entries = [e for e in evidences if e.get("status") == "blocked"]
    assert len(blocked_entries) > 0, "Should have at least one BLOCKED evidence entry for missing tools"

    # Verify blocked entries have the expected structure
    for entry in blocked_entries:
        assert entry["source_type"] == "tool"
        assert entry["source_path"].startswith("<dependency:")
        assert entry["error_code"] == "tool_not_found"
        # stderr is stored inside details by EvidenceIndexBuilder
        assert "is not installed" in entry.get("details", {}).get("stderr", "")
        assert entry.get("details", {}).get("error_type") == "tool_not_found"


def test_staged_extension_warning(tmp_path, capsys, monkeypatch):
    """
    covers: EVO-TASK-012d
    Test that staging a file with an extension not in the configured
    language_tool_matrix produces a WARNING but does NOT block.
    """
    import subprocess as sp

    # Initialize a git repo in tmp_path so git diff --cached works
    sp.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    sp.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    sp.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, capture_output=True, check=True,
    )

    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01\ncovers: AC-VT-001-02",
        include_claims=True,
        claim_has_evidence=True,
    )

    # Stage all files so git diff --cached sees them
    sp.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)

    # Create and stage a file with an unrecognized extension (.rb)
    rb_file = tmp_path / "src" / "something.rb"
    rb_file.write_text("# Ruby file", encoding="utf-8")
    sp.run(["git", "add", str(rb_file)], cwd=tmp_path, capture_output=True, check=True)

    exit_code = main(["analyze", "--project-root", str(tmp_path)])

    captured = capsys.readouterr()
    # Must NOT block — warning only
    assert "Analysis complete. Gate decision:" in captured.out
    # Must warn about the unrecognized extension
    assert "WARNING: 发现未配置的代码文件类型 .rb" in captured.err


def test_incremental_analysis_marks_stale_gaps(tmp_path, capsys, monkeypatch):
    """
    covers: EVO-TASK-020
    Test that when staged files are present, gaps/risks from unchanged claims
    are marked as ``stale`` and do not affect the gate decision.
    """
    import subprocess as sp

    # Initialize a git repo so git diff --cached works
    sp.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    sp.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    sp.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, capture_output=True, check=True,
    )

    # Set up a project with a CLAIM that references a file we will NOT stage.
    # The claim has code_refs pointing to src/vibe_tracing/core/ids.py.
    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01\ncovers: AC-VT-001-02",
        include_claims=True,
        claim_has_evidence=True,
    )

    # Stage only a README (not referenced by any claim) so the claim is
    # considered "unchanged" and its gaps/risks should be marked stale.
    readme = tmp_path / "README.md"
    readme.write_text("# Test", encoding="utf-8")
    sp.run(["git", "add", str(readme)], cwd=tmp_path, capture_output=True, check=True)

    exit_code = main(["analyze", "--project-root", str(tmp_path)])

    # The analysis should still produce a report
    assert exit_code == 0 or exit_code == 2  # depends on coverage

    traceability_report_path = tmp_path / "output" / "traceability_report.json"
    assert traceability_report_path.exists()

    report = json.loads(traceability_report_path.read_text(encoding="utf-8"))

    # Gaps and risks should be present in the report
    gaps = report.get("gaps", [])
    risks = report.get("risks", [])

    # At least some gaps/risks should be marked stale
    stale_gaps = [g for g in gaps if g.get("stale")]
    stale_risks = [r for r in risks if r.get("stale")]

    # Since we only staged README.md (not referenced by any claim), all
    # claim-related gaps/risks should be stale.
    if gaps:
        assert len(stale_gaps) > 0, (
            "Expected at least one stale gap when only unrelated files are staged"
        )
    if risks:
        # Risks with claim_id from unchanged claims should be stale
        claim_risks = [r for r in risks if r.get("claim_id")]
        stale_claim_risks = [r for r in claim_risks if r.get("stale")]
        if claim_risks:
            assert len(stale_claim_risks) > 0, (
                "Expected at least one stale risk from unchanged claims"
            )


def test_incremental_analysis_no_stale_without_staged(tmp_path, capsys):
    """
    covers: EVO-TASK-020
    Test that when no files are staged (non-git repo), no gaps/risks are
    marked as stale (full analysis mode).
    """
    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01\ncovers: AC-VT-001-02",
        include_claims=True,
        claim_has_evidence=True,
    )

    # No git repo, no staged files -> nothing should be stale
    exit_code = main(["analyze", "--project-root", str(tmp_path)])
    assert exit_code == 0

    traceability_report_path = tmp_path / "output" / "traceability_report.json"
    assert traceability_report_path.exists()

    report = json.loads(traceability_report_path.read_text(encoding="utf-8"))
    gaps = report.get("gaps", [])
    risks = report.get("risks", [])

    # Nothing should be marked stale
    stale_gaps = [g for g in gaps if g.get("stale")]
    stale_risks = [r for r in risks if r.get("stale")]
    assert len(stale_gaps) == 0, "No gaps should be stale without staged files"
    assert len(stale_risks) == 0, "No risks should be stale without staged files"


def test_incremental_analysis_affected_files_not_stale(tmp_path, capsys, monkeypatch):
    """
    covers: EVO-TASK-020
    Test that gaps/risks from claims whose files ARE staged are NOT marked stale.
    """
    import subprocess as sp

    # Initialize a git repo
    sp.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    sp.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    sp.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, capture_output=True, check=True,
    )

    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01\ncovers: AC-VT-001-02",
        include_claims=True,
        claim_has_evidence=True,
    )

    # Stage the file referenced by the claim's code_refs
    code_file = tmp_path / "src" / "vibe_tracing" / "core" / "ids.py"
    sp.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

    exit_code = main(["analyze", "--project-root", str(tmp_path)])

    traceability_report_path = tmp_path / "output" / "traceability_report.json"
    assert traceability_report_path.exists()

    report = json.loads(traceability_report_path.read_text(encoding="utf-8"))
    gaps = report.get("gaps", [])
    risks = report.get("risks", [])

    # No gaps/risks should be stale since the staged file IS referenced by the claim
    stale_gaps = [g for g in gaps if g.get("stale")]
    stale_risks = [r for r in risks if r.get("stale")]
    assert len(stale_gaps) == 0, "No gaps should be stale when claim files are staged"
    assert len(stale_risks) == 0, "No risks should be stale when claim files are staged"
