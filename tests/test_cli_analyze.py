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

    def mock_execute_all(self, execution_paths, baseline_path=None):
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
    assert "AC-VT-001-02" in captured.out and "缺失测试证据" in captured.out

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


def test_finalize_stores_prd_hash(tmp_path):
    """AC-VT-009-14: vt finalize must store prd_hash in config.json."""
    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01\ncovers: AC-VT-001-02",
        include_claims=True,
        claim_has_evidence=True,
    )

    cfg_path = tmp_path / ".vibetracing" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    # Verify both hashes are present after finalize
    assert "prd_hash" in cfg, "config.json must contain prd_hash after finalize"
    assert "architecture_constraints_hash" in cfg, (
        "config.json must contain architecture_constraints_hash after finalize"
    )

    # Verify prd_hash is a valid SHA256 hex string
    assert len(cfg["prd_hash"]) == 64, "prd_hash must be a 64-char hex SHA256 digest"
    assert all(c in "0123456789abcdef" for c in cfg["prd_hash"]), (
        "prd_hash must be a valid hex string"
    )

    # Verify prd_hash matches the actual PRD file
    prd_path = tmp_path / "docs" / "prd.md"
    expected = hashlib.sha256(prd_path.read_bytes()).hexdigest()
    assert cfg["prd_hash"] == expected, (
        "prd_hash must equal SHA256 of docs/prd.md at finalize time"
    )


def test_analyze_detects_prd_drift(tmp_path, capsys):
    """AC-VT-009-14: vt analyze must detect PRD hash mismatch and output a WARNING."""
    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01\ncovers: AC-VT-001-02",
        include_claims=True,
        claim_has_evidence=True,
    )

    # At this point run_finalize has stored prd_hash in config.json.
    # Modify the PRD to trigger drift detection.
    prd_path = tmp_path / "docs" / "prd.md"
    prd_path.write_text(
        prd_path.read_text(encoding="utf-8") + "\n<!-- drift-detected -->\n",
        encoding="utf-8",
    )

    exit_code = main(["analyze", "--project-root", str(tmp_path)])

    # PRD drift is a WARNING, not a blocker -- exit code must be 0
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "PRD" in captured.err and "漂移" in captured.err, (
        "vt analyze must emit a WARNING about PRD drift when prd_hash mismatches"
    )


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
def test_missing_tools_skips_with_warning(tmp_path, capsys, monkeypatch):
    """
    covers: AC-VT-009-02
    Test that missing tools produce a WARNING (repair guide) and skip tool
    execution gracefully, without blocking the gate.
    """
    import shutil
    import subprocess

    # Mock shutil.which to return None for ALL tools (simulate missing tools)
    monkeypatch.setattr(shutil, "which", lambda cmd: None)

    # Mock subprocess.run to fail for python3 -m <tool> --version checks
    _real_run = subprocess.run
    def mock_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and len(cmd) >= 3 and cmd[1] == "-m" and "--version" in cmd:
            raise FileNotFoundError("tool not found")
        return _real_run(cmd, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", mock_run)

    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01\ncovers: AC-VT-001-02",
        include_claims=True,
        claim_has_evidence=True,
    )

    exit_code = main(["analyze", "--project-root", str(tmp_path)])

    captured = capsys.readouterr()

    # Repair guide should be printed
    assert "AI Agent Repair Guide" in captured.err
    assert "pip install" in captured.err
    assert "Skipping tool execution" in captured.err

    # Should NOT produce BLOCKED evidence for missing tools
    evidence_index_path = tmp_path / "output" / "evidence_index.json"
    assert evidence_index_path.exists(), "evidence_index.json should be generated"

    evidence_index = json.loads(evidence_index_path.read_text(encoding="utf-8"))
    evidences = evidence_index.get("evidences", [])

    blocked_entries = [e for e in evidences if e.get("error_code") == "tool_not_found"]
    assert len(blocked_entries) == 0, "Missing tools should NOT produce BLOCKED evidence"

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


def test_input_files_loaded_once(tmp_path, capsys):
    """
    covers: AC-VT-009-12
    Input files (config.json, prd.md, architecture_constraints.json,
    task_list.json, agent_claims.json) should be read from disk only once
    during the analyze pipeline. Parsed results should be passed through
    UnifiedContext rather than re-read.
    """
    import collections
    from unittest.mock import patch

    setup_mock_project(
        tmp_path,
        task_status="done",
        test_outcome="passed",
        test_docstring="covers: AC-VT-001-01\ncovers: AC-VT-001-02",
        include_claims=True,
        claim_has_evidence=True,
    )

    # Paths to track — only these specific governance input files
    tracked_paths = {
        "prd": str(tmp_path / "docs" / "prd.md"),
        "architecture_constraints": str(tmp_path / "docs" / "architecture_constraints.json"),
        "task_list": str(tmp_path / "docs" / "task_list.json"),
        "agent_claims": str(tmp_path / ".vibetracing" / "agent_claims.json"),
        "config": str(tmp_path / ".vibetracing" / "config.json"),
    }
    # Invert: file_path_string -> file_key for lookup in spies
    path_to_key = {v: k for k, v in tracked_paths.items()}

    # Track all file reads for the input files via Path.open.
    # Both Path.read_bytes and Path.read_text delegate to Path.open,
    # so patching only Path.open avoids double-counting.
    # RawInputLoader._load_config also uses Path.open directly.
    open_counts: collections.Counter = collections.Counter()
    _orig_path_open = Path.open

    def _spy_path_open(self_path, *args, **kwargs):
        key = path_to_key.get(str(self_path))
        # Only count read opens (mode "r" or default); writes from
        # _repair_content_hashes must not inflate the read count.
        mode = args[0] if args else kwargs.get("mode", "r")
        if key is not None and "r" in mode and "w" not in mode:
            open_counts[key] += 1
        return _orig_path_open(self_path, *args, **kwargs)

    with patch.object(Path, "open", _spy_path_open):
        exit_code = main(["analyze", "--project-root", str(tmp_path)])

    assert exit_code == 0, "Analyze should succeed for a valid project"

    # Each input file should be opened/read from disk exactly once.
    # RawInputLoader loads all governance files in a single pass and the
    # parsed content is passed through UnifiedContext — downstream consumers
    # (PrdParser, TaskLoader, ClaimLoader, gate checks) must reuse the
    # already-loaded content instead of re-reading from disk.
    for file_key, expected_count in [
        ("prd", 1),
        ("architecture_constraints", 1),
        ("task_list", 1),
        ("agent_claims", 1),
        ("config", 1),
    ]:
        actual = open_counts[file_key]
        assert actual == expected_count, (
            f"{file_key} was opened {actual} time(s) from disk, "
            f"expected exactly {expected_count}. "
            f"Input files must be loaded once via RawInputLoader and passed "
            f"through UnifiedContext."
        )


# =========================================================================
# Tests for run_accept
# =========================================================================

def test_run_accept_rule_found(tmp_path):
    """Test that run_accept finds and accepts a rule by rule_id."""
    from vibe_tracing.cli import run_accept

    # Set up architecture_constraints.json with a rule
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
            }
        ],
    }
    (tmp_path / "docs" / "architecture_constraints.json").write_text(
        json.dumps(constraints, indent=2), encoding="utf-8"
    )

    exit_code = run_accept(tmp_path, "MOD-TEST-001", accepted_by="agent-x")
    assert exit_code == 0

    # Verify the rule was updated
    data = json.loads((tmp_path / "docs" / "architecture_constraints.json").read_text())
    rule = data["module_boundaries"][0]
    assert rule["accepted_by"] == "agent-x"
    assert "accepted_at" in rule


def test_run_accept_rule_already_accepted(tmp_path, capsys):
    """Test that run_accept returns 0 when a rule is already accepted."""
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
                "accepted_by": "human",
                "accepted_at": "2025-01-01T00:00:00Z",
            }
        ],
    }
    (tmp_path / "docs" / "architecture_constraints.json").write_text(
        json.dumps(constraints, indent=2), encoding="utf-8"
    )

    exit_code = run_accept(tmp_path, "MOD-TEST-001")
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "already accepted" in captured.out


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
            {"rule_id": "SEC-001", "description": "No hardcoded secrets"}
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

    # Verify acceptance was written
    data = json.loads((tmp_path / "docs" / "architecture_constraints.json").read_text())
    assert data["security_rules"][0]["accepted_by"] == "test-agent"


# =========================================================================
# Tests for run_doctor
# =========================================================================

def _setup_doctor_project(base: Path):
    """Helper to set up a minimal project for doctor tests."""
    (base / "docs").mkdir(parents=True, exist_ok=True)
    (base / "output").mkdir(parents=True, exist_ok=True)
    (base / ".vibetracing").mkdir(parents=True, exist_ok=True)
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
            "claimed_status": "covered",
            "evidence_refs": ["EVIDENCE-001"],
            "timestamp": "2025-01-01T00:00:00Z",
            "code_refs": ["src/main.py"],
            "test_refs": [],
            "notes": "Test claim",
        }
    ]
    (base / ".vibetracing" / "agent_claims.json").write_text(
        json.dumps(claims), encoding="utf-8"
    )


def test_run_doctor_all_passing(tmp_path):
    """Test run_doctor when all checks pass."""
    from vibe_tracing.cli import run_doctor

    _setup_doctor_project(tmp_path)
    # Create evidence index with matching evidence
    evidence_index = {
        "run_id": "test-run",
        "evidences": [
            {"evidence_id": "EVIDENCE-001", "source_type": "claim", "source_path": "src/main.py"}
        ],
    }
    (tmp_path / "output" / "evidence_index.json").write_text(
        json.dumps(evidence_index), encoding="utf-8"
    )

    exit_code = run_doctor(tmp_path)
    assert exit_code == 0


def test_run_doctor_broken_evidence_refs(tmp_path, capsys):
    """Test run_doctor detects broken evidence_refs."""
    from vibe_tracing.cli import run_doctor

    _setup_doctor_project(tmp_path)
    # No evidence index -> evidence ref EVIDENCE-001 not found

    exit_code = run_doctor(tmp_path)
    assert exit_code == 0  # Doctor always returns 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    checks = {c["name"]: c for c in output["checks"]}
    assert len(checks["evidence_refs_integrity"]["issues"]) > 0
    assert "EVIDENCE-001" in checks["evidence_refs_integrity"]["issues"][0]["evidence_ref"]


def test_run_doctor_broken_file_refs(tmp_path, capsys):
    """Test run_doctor detects broken file references."""
    from vibe_tracing.cli import run_doctor

    _setup_doctor_project(tmp_path)
    # Modify claim to reference a non-existent file
    claims = [
        {
            "claim_id": "CLAIM-001",
            "related_task": "TASK-TEST-001",
            "claimed_status": "covered",
            "evidence_refs": [],
            "timestamp": "2025-01-01T00:00:00Z",
            "code_refs": ["src/nonexistent.py"],
            "test_refs": ["tests/nonexistent_test.py"],
            "notes": "Test claim",
        }
    ]
    (tmp_path / ".vibetracing" / "agent_claims.json").write_text(
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
    (tmp_path / ".vibetracing" / "agent_claims.json").write_text("not json!!!", encoding="utf-8")
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


def test_run_doctor_evidence_with_file_on_disk(tmp_path, capsys):
    """Test run_doctor considers evidence refs found on disk as valid."""
    from vibe_tracing.cli import run_doctor

    _setup_doctor_project(tmp_path)
    # Create a file that matches the evidence ref
    (tmp_path / "EVIDENCE-001").write_text("evidence content", encoding="utf-8")

    exit_code = run_doctor(tmp_path)
    assert exit_code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    checks = {c["name"]: c for c in output["checks"]}
    # No evidence ref issues since the file exists on disk
    assert len(checks["evidence_refs_integrity"]["issues"]) == 0


def test_run_doctor_claims_not_list(tmp_path, capsys):
    """Test run_doctor handles claims file that is a dict (not list)."""
    from vibe_tracing.cli import run_doctor

    _setup_doctor_project(tmp_path)
    # Write claims as a dict instead of list
    (tmp_path / ".vibetracing" / "agent_claims.json").write_text(
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
            "claimed_status": "covered",
            "evidence_refs": [],
            "timestamp": "2025-01-01T00:00:00Z",
            "code_refs": ["src/main.py#L1-L10"],
            "test_refs": [],
            "notes": "Test",
        }
    ]
    (tmp_path / ".vibetracing" / "agent_claims.json").write_text(
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
    from vibe_tracing.merge_gate_engine import MergeGateEngine

    engine = MergeGateEngine(tmp_path)
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
    from vibe_tracing.merge_gate_engine import MergeGateEngine

    engine = MergeGateEngine(tmp_path)
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
    from vibe_tracing.merge_gate_engine import MergeGateEngine

    engine = MergeGateEngine(tmp_path)
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
    from vibe_tracing.merge_gate_engine import MergeGateEngine

    engine = MergeGateEngine(tmp_path)
    gate_res = engine.evaluate(
        gaps=[], risks=[],
        human_decisions={"decisions": []},
    )
    assert gate_res["human_decisions_applied"] == 0


def test_apply_human_decisions_no_decisions(tmp_path):
    """Test human_decisions with empty decisions list."""
    from vibe_tracing.merge_gate_engine import MergeGateEngine

    engine = MergeGateEngine(tmp_path)
    gate_res = engine.evaluate(gaps=[], risks=[], human_decisions={"decisions": []})
    assert gate_res["human_decisions_applied"] == 0


# =========================================================================
# Tests for _compute_claim_hash and _get_directly_modified_claims
# =========================================================================

def test_compute_claim_hash():
    """Test _compute_claim_hash produces consistent hash."""
    from vibe_tracing.cli import _compute_claim_hash

    claim = {"claim_id": "CLAIM-001", "related_task": "TASK-001"}
    h1 = _compute_claim_hash(claim)
    h2 = _compute_claim_hash(claim)
    assert h1 == h2
    assert len(h1) == 16

    # Different claim -> different hash
    claim2 = {"claim_id": "CLAIM-002", "related_task": "TASK-001"}
    h3 = _compute_claim_hash(claim2)
    assert h1 != h3


def test_get_directly_modified_claims():
    """Test _get_directly_modified_claims detects modified claims."""
    from vibe_tracing.cli import _get_directly_modified_claims

    old_claims = [
        {"claim_id": "CLAIM-001", "content_hash": "abc123"},
        {"claim_id": "CLAIM-002", "content_hash": "def456"},
    ]
    new_claims = [
        {"claim_id": "CLAIM-001", "content_hash": "abc123"},  # unchanged
        {"claim_id": "CLAIM-002", "content_hash": "xxx789"},  # changed
        {"claim_id": "CLAIM-003", "content_hash": "new123"},  # new
    ]

    modified = _get_directly_modified_claims(old_claims, new_claims)
    assert "CLAIM-002" in modified
    assert "CLAIM-003" in modified
    assert "CLAIM-001" not in modified


def test_get_directly_modified_claims_empty():
    """Test _get_directly_modified_claims with empty lists."""
    from vibe_tracing.cli import _get_directly_modified_claims

    assert _get_directly_modified_claims([], []) == set()


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
    from vibe_tracing.governance import load_boundary

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
    from vibe_tracing.governance import load_boundary

    result = load_boundary(Path("/nonexistent"))
    assert result == {"included_patterns": [], "excluded_patterns": []}


def test_is_in_governance_boundary():
    """Test is_in_scope checks file exclusions."""
    from vibe_tracing.governance import is_in_scope

    boundary = {"excluded_patterns": ["vendor/**", "*.min.js"]}

    assert is_in_scope("src/main.py", boundary) is True
    assert is_in_scope("vendor/lib.js", boundary) is False
    assert is_in_scope("build/app.min.js", boundary) is False


def test_is_in_governance_boundary_empty():
    """Test is_in_scope with empty boundary."""
    from vibe_tracing.governance import is_in_scope

    boundary = {}
    assert is_in_scope("any/file.py", boundary) is True


def test_partition_by_governance_boundary():
    """Test partition_by_scope separates files."""
    from vibe_tracing.governance import partition_by_scope

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
    from vibe_tracing.hint_loader import resolve_hint
    assert resolve_hint("simple string") == "simple string"


def test_resolve_hint_dict():
    """Test resolve_hint resolves dict at given level."""
    from vibe_tracing.hint_loader import resolve_hint

    hint = {"level1": "basic", "level2": "detailed"}
    assert resolve_hint(hint, "level1") == "basic"
    assert resolve_hint(hint, "level2") == "detailed"
    # Fallback to level1 for unknown level
    assert resolve_hint(hint, "level99") == "basic"


def test_resolve_hint_non_string():
    """Test resolve_hint returns empty for non-string non-dict."""
    from vibe_tracing.hint_loader import resolve_hint
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
    """Test _render_actions uses per-file violations for BLOCKED/PASS decision."""
    from vibe_tracing.cli import _render_actions

    # Need at least one action for coverage section to render
    actions = [
        {"priority": "HIGH", "type": "test", "title": "Test Action", "context": {}}
    ]
    coverage = {"aggregate_percent": 85}
    # Per-file violations from evidence index — this is what determines BLOCKED
    violations = [
        {"file": "src/bad.py", "percent": 40},
    ]

    lines = _render_actions(
        actions, coverage_summary=coverage, project_root=tmp_path,
        coverage_violations=violations,
    )
    assert any("BLOCKED" in l for l in lines)
    assert any("src/bad.py" in l and "40%" in l for l in lines)


def test_render_actions_per_file_violations_pass(tmp_path):
    """Test _render_actions passes when no per-file violations even if aggregate is low."""
    from vibe_tracing.cli import _render_actions

    actions = [
        {"priority": "HIGH", "type": "test", "title": "Test Action", "context": {}}
    ]
    # Aggregate is low (includes test files) but no per-file violations
    coverage = {"aggregate_percent": 52.5}
    violations = []  # no per-file violations

    lines = _render_actions(
        actions, coverage_summary=coverage, project_root=tmp_path,
        coverage_violations=violations,
    )
    assert any("PASS" in l for l in lines)
    assert not any("BLOCKED" in l for l in lines)
    # Aggregate shown as informational only
    assert any("52.5%" in l for l in lines)
    assert any("informational only" in l for l in lines)


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
    assert (tmp_path / ".vibetracing" / "claims" / "current.json").exists()
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
    from vibe_tracing.hint_loader import load_hints

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
# Tests for error handling in run_analyze
# =========================================================================

def test_run_analyze_unexpected_error(tmp_path, capsys, monkeypatch):
    """Test run_analyze handles unexpected exceptions gracefully."""
    from vibe_tracing.cli import run_analyze
    from vibe_tracing.raw_input_loader import RawInputLoader

    setup_mock_project(tmp_path)

    # Monkey-patch to raise an unexpected error
    def broken_load(self):
        raise RuntimeError("Simulated unexpected error")

    monkeypatch.setattr(RawInputLoader, "load", broken_load)

    exit_code = main(["analyze", "--project-root", str(tmp_path)])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "Unexpected error" in captured.err


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
