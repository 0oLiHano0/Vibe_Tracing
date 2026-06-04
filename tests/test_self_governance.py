"""
Self-governance E2E test: VT must be able to analyze itself.
"""
import json
from pathlib import Path
from vibe_tracing.cli import main

PROJECT_ROOT = Path(__file__).parent.parent


def test_vt_can_analyze_itself():
    """VT must produce a valid traceability report when analyzing its own project."""
    exit_code = main(["analyze", "--project-root", str(PROJECT_ROOT)])

    # VT should not crash (exit code 0 or 2, never 1)
    assert exit_code in (0, 2), f"vt analyze crashed with exit code {exit_code}"

    # Output files must exist
    output_dir = PROJECT_ROOT / "output"
    assert (output_dir / "evidence_index.json").exists()
    assert (output_dir / "traceability_report.json").exists()
    assert (output_dir / "run_metadata.json").exists()
    assert (output_dir / "dashboard.html").exists()

    # Gate decision must be a valid value
    meta = json.loads((output_dir / "run_metadata.json").read_text(encoding="utf-8"))
    assert meta["gate_decision"] in ("pass", "fail", "blocked")
    assert meta["exit_code"] in (0, 2)

    # Traceability report must be valid JSON with required fields
    report = json.loads((output_dir / "traceability_report.json").read_text(encoding="utf-8"))
    assert "gate_decision" in report
    assert "requirement_coverage" in report
    assert "risks" in report
