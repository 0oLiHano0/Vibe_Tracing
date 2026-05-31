"""
End-to-End tests for Claude Code self-bootstrapping and quality gates (TASK-VT-028).
"""

import json
import shutil
from pathlib import Path
from vibe_tracing.cli import main
from vibe_tracing.schema_validator import SchemaValidator

EXAMPLES_DIR = Path(__file__).parent / "fixtures" / "examples"


def test_e2e_claude_bootstrap_good():
    """
    covers: GATE-VT-013, GATE-VT-014
    Verify sample_project_claude_bootstrap_good produces a PASS decision, exit code 0, and all outputs are valid.
    """
    project_root = EXAMPLES_DIR / "sample_project_claude_bootstrap_good"
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
    validator = SchemaValidator()
    val_ev = validator.validate_file(evidence_index_path, "evidence_index")
    assert val_ev.is_valid is True, val_ev.message

    val_rep = validator.validate_file(traceability_report_path, "traceability_report")
    assert val_rep.is_valid is True, val_rep.message

    # Validate run metadata
    meta = json.loads(run_metadata_path.read_text(encoding="utf-8"))
    assert meta["gate_decision"] == "pass"
    assert meta["exit_code"] == 0


def test_e2e_claude_bootstrap_missing_config():
    """
    covers: GATE-VT-013
    Verify sample_project_claude_bootstrap_missing_config produces exit code 1 due to missing bootstrap config.
    """
    project_root = EXAMPLES_DIR / "sample_project_claude_bootstrap_missing_config"
    output_dir = project_root / ".vibetracing" / "output"

    # Clean up previous runs if any
    if output_dir.exists():
        shutil.rmtree(output_dir)

    # Run analyzer - expected exit code 1
    exit_code = main(["analyze", "--project-root", str(project_root)])
    assert exit_code == 1


def test_e2e_claude_bootstrap_bad_arch_change():
    """
    covers: GATE-VT-014
    Verify sample_project_claude_bootstrap_bad_arch_change produces a BLOCKED decision and exit code 2.
    """
    project_root = EXAMPLES_DIR / "sample_project_claude_bootstrap_bad_arch_change"
    output_dir = project_root / ".vibetracing" / "output"

    # Clean up previous runs if any
    if output_dir.exists():
        shutil.rmtree(output_dir)

    # Run analyzer - expected exit code 2 due to silent architecture drift (gate blocked)
    exit_code = main(["analyze", "--project-root", str(project_root)])
    assert exit_code == 2

    # Verify run metadata reflects blocked decision
    run_metadata_path = output_dir / "run_metadata.json"
    assert run_metadata_path.exists()

    meta = json.loads(run_metadata_path.read_text(encoding="utf-8"))
    assert meta["gate_decision"] == "blocked"
    assert meta["exit_code"] == 2
