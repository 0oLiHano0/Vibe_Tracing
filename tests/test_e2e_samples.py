"""
End-to-End tests for Vibe Tracing using the mock projects under examples/ (TASK-VT-020).
"""

import json
import shutil
from pathlib import Path
from vibe_tracing.cli import main
from vibe_tracing.schema_validator import SchemaValidator

EXAMPLES_DIR = Path(__file__).parent / "fixtures" / "examples"


def _prepare_project(tmp_path, folder_name):
    src_dir = EXAMPLES_DIR / folder_name
    dest_dir = tmp_path / folder_name
    shutil.copytree(src_dir, dest_dir)

    # Write a finalized config.json
    config_dir = dest_dir / ".vibetracing"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_data = {
        "project_id": "PROJECT-VT",
        "project_prefix": "VT",
        "project_name": "E2E Project",
        "language": "python",
        "validation_tools": ["test", "coverage", "lint", "type_check", "security"],
        "paths": {
            "prd": "docs/prd.md",
            "architecture_constraints": "docs/architecture_constraints.json",
            "task_list": "docs/task_list.json",
            "agent_claims": ".vibetracing/agent_claims.json",
            "output_dir": "output",
        },
    }
    (config_dir / "config.json").write_text(
        json.dumps(config_data, indent=2), encoding="utf-8"
    )

    # Fix evidence_refs in agent_claims.json to refer to the test report (EVIDENCE-VT-003)
    # instead of the task (EVIDENCE-VT-001) for projects expected to pass credibility checks
    if folder_name in ("sample_project_good", "sample_project_arch_unclear"):
        claims_file = config_dir / "agent_claims.json"
        if claims_file.exists():
            claims_data = json.loads(claims_file.read_text(encoding="utf-8"))
            for claim in claims_data:
                if claim.get("evidence_refs") == ["EVIDENCE-VT-001"]:
                    claim["evidence_refs"] = ["EVIDENCE-VT-003"]
            claims_file.write_text(
                json.dumps(claims_data, indent=2), encoding="utf-8"
            )

    return dest_dir


def test_e2e_good_project(tmp_path):
    """
    covers: AC-VT-001-01, AC-VT-001-02, AC-VT-001-03, AC-VT-001-04, AC-VT-002-01, AC-VT-002-02, AC-VT-002-03, AC-VT-006-01, AC-VT-006-02, AC-VT-008-03, AC-VT-009-01, AC-VT-009-02, AC-VT-009-03, AC-VT-009-04
    Verify sample_project_good produces a PASS decision, exit code 0, and all outputs are valid.
    """
    project_root = _prepare_project(tmp_path, "sample_project_good")
    output_dir = project_root / "output"

    # Run analyzer
    exit_code = main(["analyze", "--project-root", str(project_root)])
    assert exit_code == 0

    # Verify output files exist
    evidence_index_path = output_dir / "evidence_index.json"
    traceability_report_path = output_dir / "traceability_report.json"
    run_metadata_path = output_dir / "run_metadata.json"
    dashboard_path = output_dir / "dashboard.html"

    assert evidence_index_path.exists()
    assert traceability_report_path.exists()
    assert run_metadata_path.exists()
    assert dashboard_path.exists()

    # Validate output files schemas
    validator = SchemaValidator()
    val_ev = validator.validate_file(evidence_index_path, "evidence_index")
    assert val_ev.is_valid is True, val_ev.message

    val_rep = validator.validate_file(traceability_report_path, "traceability_report")
    assert val_rep.is_valid is True, val_rep.message

    # Validate run metadata
    meta = json.loads(run_metadata_path.read_text(encoding="utf-8"))
    assert meta["gate_decision"] == "pass"
    assert meta["exit_code"] == 0
    assert "所有质量门禁规则均已通过" in meta["summary"]


def test_e2e_missing_tests(tmp_path):
    """
    covers: AC-VT-008-01, AC-VT-008-03, AC-VT-009-02
    Verify sample_project_missing_tests produces a BLOCKED decision and exit code 2.
    """
    project_root = _prepare_project(tmp_path, "sample_project_missing_tests")
    output_dir = project_root / "output"

    # Run analyzer
    exit_code = main(["analyze", "--project-root", str(project_root)])
    assert exit_code == 2

    run_metadata_path = output_dir / "run_metadata.json"
    assert run_metadata_path.exists()

    meta = json.loads(run_metadata_path.read_text(encoding="utf-8"))
    assert meta["gate_decision"] == "blocked"
    assert meta["exit_code"] == 2
    assert "验收标准缺失测试证据" in meta["summary"]


def test_e2e_bad_claim(tmp_path):
    """
    covers: AC-VT-002-01, AC-VT-002-02, AC-VT-002-03, AC-VT-008-02, AC-VT-008-03, AC-VT-009-02
    Verify sample_project_bad_claim produces a BLOCKED decision and exit code 2.
    """
    project_root = _prepare_project(tmp_path, "sample_project_bad_claim")
    output_dir = project_root / "output"

    # Run analyzer
    exit_code = main(["analyze", "--project-root", str(project_root)])
    assert exit_code == 2

    run_metadata_path = output_dir / "run_metadata.json"
    assert run_metadata_path.exists()

    meta = json.loads(run_metadata_path.read_text(encoding="utf-8"))
    assert meta["gate_decision"] == "blocked"
    assert meta["exit_code"] == 2
    assert any(
        term in meta["summary"]
        for term in ("不自证违规", "self-referential", "empty evidence")
    )


def test_e2e_arch_unclear(tmp_path):
    """
    covers: AC-VT-008-03, AC-VT-009-02, AC-VT-009-04
    Verify sample_project_arch_unclear produces a FAIL decision (due to unclear constraints) and exit code 0.
    """
    project_root = _prepare_project(tmp_path, "sample_project_arch_unclear")
    output_dir = project_root / "output"

    # Run analyzer
    exit_code = main(["analyze", "--project-root", str(project_root)])
    assert exit_code == 0

    run_metadata_path = output_dir / "run_metadata.json"
    assert run_metadata_path.exists()

    meta = json.loads(run_metadata_path.read_text(encoding="utf-8"))
    assert meta["gate_decision"] == "fail"
    assert meta["exit_code"] == 0
    assert (
        "存在不明确的架构约束规则" in meta["summary"]
        or "GATE-VT-008" in meta["summary"]
    )
