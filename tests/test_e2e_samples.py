"""
End-to-End tests for Vibe Tracing using the mock projects under examples/ (TASK-VT-020).
"""

import json
import shutil
from pathlib import Path
from vibe_tracing.cli import main
from vibe_tracing.schema_validator import SchemaValidator

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def test_e2e_good_project():
    """
    covers: AC-VT-001-01, AC-VT-001-02, AC-VT-001-03, AC-VT-001-04, AC-VT-002-01, AC-VT-002-02, AC-VT-002-03, AC-VT-006-01, AC-VT-006-02, AC-VT-008-03, AC-VT-009-01, AC-VT-009-02, AC-VT-009-03, AC-VT-009-04
    Verify sample_project_good produces a PASS decision, exit code 0, and all outputs are valid.
    """
    project_root = EXAMPLES_DIR / "sample_project_good"
    output_dir = project_root / ".vibetracing" / "output"

    # Clean up previous runs if any
    if output_dir.exists():
        shutil.rmtree(output_dir)

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
    validator = SchemaValidator(project_root / "schemas")
    val_ev = validator.validate_file(evidence_index_path, "evidence_index")
    assert val_ev.is_valid is True, val_ev.message

    val_rep = validator.validate_file(traceability_report_path, "traceability_report")
    assert val_rep.is_valid is True, val_rep.message

    # Validate run metadata
    meta = json.loads(run_metadata_path.read_text(encoding="utf-8"))
    assert meta["gate_decision"] == "pass"
    assert meta["exit_code"] == 0
    assert "所有质量门禁规则均已通过" in meta["summary"]


def test_e2e_missing_tests():
    """
    covers: AC-VT-008-01, AC-VT-008-03, AC-VT-009-02
    Verify sample_project_missing_tests produces a BLOCKED decision and exit code 2.
    """
    project_root = EXAMPLES_DIR / "sample_project_missing_tests"
    output_dir = project_root / ".vibetracing" / "output"

    # Clean up previous runs if any
    if output_dir.exists():
        shutil.rmtree(output_dir)

    # Run analyzer
    exit_code = main(["analyze", "--project-root", str(project_root)])
    assert exit_code == 2

    run_metadata_path = output_dir / "run_metadata.json"
    assert run_metadata_path.exists()

    meta = json.loads(run_metadata_path.read_text(encoding="utf-8"))
    assert meta["gate_decision"] == "blocked"
    assert meta["exit_code"] == 2
    assert "验收标准缺失测试证据" in meta["summary"]


def test_e2e_bad_claim():
    """
    covers: AC-VT-002-01, AC-VT-002-02, AC-VT-002-03, AC-VT-008-02, AC-VT-008-03, AC-VT-009-02
    Verify sample_project_bad_claim produces a BLOCKED decision and exit code 2.
    """
    project_root = EXAMPLES_DIR / "sample_project_bad_claim"
    output_dir = project_root / ".vibetracing" / "output"

    # Clean up previous runs if any
    if output_dir.exists():
        shutil.rmtree(output_dir)

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


def test_e2e_arch_unclear():
    """
    covers: AC-VT-008-03, AC-VT-009-02, AC-VT-009-04
    Verify sample_project_arch_unclear produces a FAIL decision (due to unclear constraints) and exit code 0.
    """
    project_root = EXAMPLES_DIR / "sample_project_arch_unclear"
    output_dir = project_root / ".vibetracing" / "output"

    # Clean up previous runs if any
    if output_dir.exists():
        shutil.rmtree(output_dir)

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
