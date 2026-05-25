"""
Tests for RawInputLoader (TASK-VT-005).

All tests cover the pure file-loading layer only — no governance decisions.
"""

from pathlib import Path


from vibe_tracing.core.enums import ErrorCode
from vibe_tracing.raw_input_loader import RawInputManifest, RawInputLoader

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Actual project root — used for tests that load the real files.
PROJECT_ROOT = Path(__file__).parent.parent


def _make_required_files(base: Path) -> None:
    """Create minimal valid required files under *base*."""
    (base / "docs").mkdir(parents=True, exist_ok=True)

    (base / "docs" / "prd.md").write_text("# PRD\nSome content.", encoding="utf-8")
    (base / "docs" / "architecture_constraints.json").write_text(
        '{"constraints": []}', encoding="utf-8"
    )
    (base / "docs" / "task_list.json").write_text('{"tasks": []}', encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_load_all_valid_files_returns_ok_manifest():
    """
    AC-VT-001-01: Loading from actual project_root where all required files
    exist must produce a manifest with has_required_errors=False and every
    required InputFileRecord having status='ok'.
    """
    loader = RawInputLoader(PROJECT_ROOT)
    manifest = loader.load()

    assert manifest.has_required_errors is False

    required_keys = set(RawInputLoader.REQUIRED_FILES.keys())
    for record in manifest.inputs_used:
        if record.file_key in required_keys:
            assert record.status == "ok", (
                f"Expected status='ok' for required file '{record.file_key}', "
                f"got '{record.status}': {record.error_message}"
            )


def test_required_files_have_content():
    """
    AC-VT-001-01: After a successful load the prd content must be a str,
    and task_list / architecture_constraints must be dicts.
    """
    loader = RawInputLoader(PROJECT_ROOT)
    manifest = loader.load()

    records = {r.file_key: r for r in manifest.inputs_used}

    assert isinstance(records["prd"].content, str), (
        "prd content should be str (markdown)"
    )
    assert isinstance(records["task_list"].content, dict), (
        "task_list content should be dict"
    )
    assert isinstance(records["architecture_constraints"].content, dict), (
        "architecture_constraints content should be dict"
    )


def test_missing_required_file_sets_has_required_errors(tmp_path):
    """
    AC-VT-001-04: When the project_root has no raw/ files, has_required_errors
    must be True.
    """
    loader = RawInputLoader(tmp_path)
    manifest = loader.load()

    assert manifest.has_required_errors is True


def test_missing_required_file_record_has_error_code(tmp_path):
    """
    AC-VT-001-04: A missing required file's InputFileRecord must carry
    error_code == ErrorCode.MISSING_INPUT.
    """
    loader = RawInputLoader(tmp_path)
    manifest = loader.load()

    required_keys = set(RawInputLoader.REQUIRED_FILES.keys())
    missing_records = [
        r
        for r in manifest.inputs_used
        if r.file_key in required_keys and r.status == "missing"
    ]
    assert len(missing_records) > 0, (
        "Expected at least one missing required file record"
    )

    for record in missing_records:
        assert record.error_code == ErrorCode.MISSING_INPUT.value, (
            f"Expected error_code='{ErrorCode.MISSING_INPUT.value}' "
            f"for missing required file '{record.file_key}', got '{record.error_code}'"
        )


def test_missing_optional_file_does_not_set_has_required_errors(tmp_path):
    """
    AC-VT-001-04: When all required files are present but optional files are
    absent, has_required_errors must remain False.
    """
    _make_required_files(tmp_path)
    # Intentionally do NOT create optional agent_claims.json

    loader = RawInputLoader(tmp_path)
    manifest = loader.load()

    assert manifest.has_required_errors is False


def test_invalid_json_file_sets_parse_error(tmp_path):
    """
    AC-VT-002-01: A required JSON file containing invalid JSON must produce
    status='parse_error' and error_code=ErrorCode.INVALID_INPUT.
    """
    _make_required_files(tmp_path)

    # Overwrite task_list.json with bad JSON
    bad_json_path = tmp_path / "docs" / "task_list.json"
    bad_json_path.write_text("{ this is not valid json !!!}", encoding="utf-8")

    loader = RawInputLoader(tmp_path)
    manifest = loader.load()

    records = {r.file_key: r for r in manifest.inputs_used}
    task_record = records["task_list"]

    assert task_record.status == "parse_error", (
        f"Expected status='parse_error', got '{task_record.status}'"
    )
    assert task_record.error_code == ErrorCode.INVALID_INPUT.value, (
        f"Expected error_code='{ErrorCode.INVALID_INPUT.value}', got '{task_record.error_code}'"
    )


def test_raw_files_not_modified():
    """
    AC-VT-001-01: The loader must be read-only. No raw input file's mtime
    should change after calling load().
    """
    loader = RawInputLoader(PROJECT_ROOT)

    # Collect mtimes before loading
    docs_dir = PROJECT_ROOT / "docs"
    files_before: dict[Path, float] = {}
    if docs_dir.exists():
        for p in docs_dir.rglob("*"):
            if p.is_file():
                files_before[p] = p.stat().st_mtime

    loader.load()

    # Collect mtimes after loading
    for p, mtime_before in files_before.items():
        mtime_after = p.stat().st_mtime
        assert mtime_after == mtime_before, f"File was modified during load(): {p}"


def test_manifest_records_all_required_file_keys():
    """
    AC-VT-001-04: The manifest.inputs_used list must contain an InputFileRecord
    for every key in RawInputLoader.REQUIRED_FILES.
    """
    loader = RawInputLoader(PROJECT_ROOT)
    manifest = loader.load()

    found_keys = {r.file_key for r in manifest.inputs_used}
    for required_key in RawInputLoader.REQUIRED_FILES:
        assert required_key in found_keys, (
            f"No InputFileRecord found for required key '{required_key}'"
        )


def test_manifest_includes_tool_report_files(tmp_path):
    """
    AC-VT-002-01: When a file exists in tool_reports/, it must appear in
    manifest.tool_report_files.
    """
    _make_required_files(tmp_path)

    # Create a dummy tool_reports file
    tool_reports_dir = tmp_path / ".vibetracing" / "tool_reports"
    tool_reports_dir.mkdir(parents=True, exist_ok=True)
    dummy_report = tool_reports_dir / "dummy_report.json"
    dummy_report.write_text('{"tool": "dummy"}', encoding="utf-8")

    loader = RawInputLoader(tmp_path)
    manifest = loader.load()

    assert str(dummy_report) in manifest.tool_report_files, (
        f"Expected '{dummy_report}' in manifest.tool_report_files, "
        f"got: {manifest.tool_report_files}"
    )


def test_loader_has_no_gate_decision_attribute():
    """
    AC-VT-001-04: RawInputManifest must not have gate_decision, risk_decision,
    or coverage_decision attributes — this loader is a pure file-loading layer.
    """
    manifest = RawInputManifest()

    assert not hasattr(manifest, "gate_decision"), (
        "RawInputManifest must not have a 'gate_decision' attribute"
    )
    assert not hasattr(manifest, "risk_decision"), (
        "RawInputManifest must not have a 'risk_decision' attribute"
    )
    assert not hasattr(manifest, "coverage_decision"), (
        "RawInputManifest must not have a 'coverage_decision' attribute"
    )
