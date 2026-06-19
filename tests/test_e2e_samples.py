"""
End-to-End tests for Vibe Tracing using the mock projects under examples/ (TASK-VT-020).
"""

import json
import shutil
from pathlib import Path
from vibe_tracing.cli import main
from vibe_tracing.infra.validation.schema_validator import SchemaValidator

EXAMPLES_DIR = Path(__file__).parent / "fixtures" / "examples"


def _prepare_project(tmp_path, folder_name):
    src_dir = EXAMPLES_DIR / folder_name
    dest_dir = tmp_path / folder_name
    shutil.copytree(src_dir, dest_dir)
    return dest_dir


def test_e2e_good_project(tmp_path):
    """
    covers: AC-VT-001-01, AC-VT-001-02, AC-VT-001-03, AC-VT-001-04, AC-VT-002-01, AC-VT-002-02, AC-VT-002-03, AC-VT-006-01, AC-VT-006-02, AC-VT-008-03, AC-VT-009-01, AC-VT-009-02, AC-VT-009-03, AC-VT-009-04
    Verify sample_project_good produces a BLOCKED decision (due to low-confidence claim without tool evidence) and exit code 2.
    """
    project_root = _prepare_project(tmp_path, "sample_project_good")
    output_dir = project_root / "output"

    # Run analyzer
    exit_code = main(["analyze", "--project-root", str(project_root)])
    assert exit_code == 2

    # Verify output files exist
    test_results_path = output_dir / "evidences" / "test_results.json"
    traceability_report_path = output_dir / "traceability_report.json"
    dashboard_path = output_dir / "dashboard.html"

    assert test_results_path.exists()
    assert traceability_report_path.exists()
    assert dashboard_path.exists()

    # Validate output files schemas
    validator = SchemaValidator()
    val_rep = validator.validate_file(traceability_report_path, "traceability_report")
    assert val_rep.is_valid is True, val_rep.message

    # Validate run metadata embedded in traceability report
    report = json.loads(traceability_report_path.read_text(encoding="utf-8"))
    meta = report["metadata"]
    assert meta["gate_decision"] == "blocked"
    assert (
        "验收标准" in meta["summary"] and "缺失" in meta["summary"]
        or "低可信度" in meta["summary"]
        or "缺失测试证据" in meta["summary"]
    )


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

    traceability_report_path = output_dir / "traceability_report.json"
    report = json.loads(traceability_report_path.read_text(encoding="utf-8"))
    meta = report["metadata"]
    assert meta["gate_decision"] == "blocked"
    assert "缺失测试证据" in meta["summary"]


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

    traceability_report_path = output_dir / "traceability_report.json"
    report = json.loads(traceability_report_path.read_text(encoding="utf-8"))
    meta = report["metadata"]
    assert meta["gate_decision"] == "blocked"
    assert any(
        term in meta["summary"]
        for term in ("不自证违规", "自引用违规", "self-referential", "empty evidence")
    )


def test_e2e_arch_unclear(tmp_path):
    """
    covers: AC-VT-008-03, AC-VT-009-02, AC-VT-009-04
    Verify sample_project_arch_unclear produces a BLOCKED decision (due to low-confidence claim AND unclear constraints) and exit code 2.
    """
    project_root = _prepare_project(tmp_path, "sample_project_arch_unclear")
    output_dir = project_root / "output"

    # Run analyzer
    exit_code = main(["analyze", "--project-root", str(project_root)])
    assert exit_code == 2

    traceability_report_path = output_dir / "traceability_report.json"
    report = json.loads(traceability_report_path.read_text(encoding="utf-8"))
    meta = report["metadata"]
    assert meta["gate_decision"] == "blocked"
    assert (
        "存在不明确的架构约束规则" in meta["summary"]
        or "GATE-VT-008" in meta["summary"]
    )
