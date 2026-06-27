"""
Tests for RawInputLoader (TASK-VT-005).

All tests cover the pure file-loading layer only — no governance decisions.
"""

from pathlib import Path

from vibe_tracing.infra.config.enums import ErrorCode
from vibe_tracing.infra.loader.config import REQUIRED_FILES, load_config
from vibe_tracing.infra.loader.raw_input import RawInputManifest, RawInputLoader

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Actual project root — used for tests that load the real files.
PROJECT_ROOT = Path(__file__).parent.parent

# Minimal complete paths config for tmp_path tests
_MINIMAL_PATHS = {
    "paths": {
        "prd": "docs/prd.md",
        "architecture_constraints": "docs/architecture_constraints.json",
        "task_list": "docs/task_list.json",
        "human_decisions": ".vibetracing/human_decisions.json",
        "output_dir": "output",
    }
}


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
    loader = RawInputLoader(PROJECT_ROOT, config_data=load_config(PROJECT_ROOT))
    manifest = loader.load()

    assert manifest.has_required_errors is False

    for record in manifest.inputs_used:
        if record.file_key in REQUIRED_FILES:
            assert record.status == "ok", (
                f"Expected status='ok' for required file '{record.file_key}', "
                f"got '{record.status}': {record.error_message}"
            )


def test_required_files_have_content():
    """
    AC-VT-001-01: After a successful load the prd content must be a str,
    and task_list / architecture_constraints must be dicts.
    """
    loader = RawInputLoader(PROJECT_ROOT, config_data=load_config(PROJECT_ROOT))
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
    loader = RawInputLoader(tmp_path, config_data=_MINIMAL_PATHS)
    manifest = loader.load()

    assert manifest.has_required_errors is True


def test_missing_required_file_record_has_error_code(tmp_path):
    """
    AC-VT-001-04: A missing required file's InputFileRecord must carry
    error_code == ErrorCode.MISSING_INPUT.
    """
    loader = RawInputLoader(tmp_path, config_data=_MINIMAL_PATHS)
    manifest = loader.load()

    missing_records = [
        r
        for r in manifest.inputs_used
        if r.file_key in REQUIRED_FILES and r.status == "missing"
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

    loader = RawInputLoader(tmp_path, config_data=_MINIMAL_PATHS)
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

    loader = RawInputLoader(tmp_path, config_data=_MINIMAL_PATHS)
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
    loader = RawInputLoader(PROJECT_ROOT, config_data=load_config(PROJECT_ROOT))

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
    for every key in REQUIRED_FILES.
    """
    loader = RawInputLoader(PROJECT_ROOT, config_data=load_config(PROJECT_ROOT))
    manifest = loader.load()

    found_keys = {r.file_key for r in manifest.inputs_used}
    for required_key in REQUIRED_FILES:
        assert required_key in found_keys, (
            f"No InputFileRecord found for required key '{required_key}'"
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


def test_config_json_path_overrides_and_safe_fallback(tmp_path):
    """
    covers: AC-VT-009-05
    Verify that RawInputLoader loads custom paths from config_data,
    and falls back to standard paths when config is empty.
    """
    import json

    # 1. Test fallback when config is empty
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "prd.md").write_text("# Default PRD", encoding="utf-8")
    (tmp_path / "docs" / "architecture_constraints.json").write_text(
        '{"constraints": []}', encoding="utf-8"
    )
    (tmp_path / "docs" / "task_list.json").write_text('{"tasks": []}', encoding="utf-8")

    loader = RawInputLoader(tmp_path, config_data=_MINIMAL_PATHS)
    manifest = loader.load()
    assert manifest.has_required_errors is False
    records = {r.file_key: r for r in manifest.inputs_used}
    assert records["prd"].content == "# Default PRD"

    # 2. Test custom config paths override
    custom_config = {
        "schema_version": "1.0.0",
        "project_id": "PROJECT-VT",
        "paths": {
            "prd": "custom_dir/custom_prd.md",
            "architecture_constraints": "docs/architecture_constraints.json",
            "task_list": "docs/task_list.json",
            "human_decisions": ".vibetracing/human_decisions.json",
            "output_dir": "output",
        },
    }

    # Create custom PRD file
    (tmp_path / "custom_dir").mkdir(parents=True, exist_ok=True)
    (tmp_path / "custom_dir" / "custom_prd.md").write_text(
        "# Custom PRD", encoding="utf-8"
    )

    loader_custom = RawInputLoader(tmp_path, config_data=custom_config)
    manifest_custom = loader_custom.load()
    assert manifest_custom.has_required_errors is False
    records_custom = {r.file_key: r for r in manifest_custom.inputs_used}
    assert records_custom["prd"].content == "# Custom PRD"


def test_load_human_decisions_file_exists(tmp_path):
    """
    Verify that RawInputLoader loads human_decisions.json successfully
    when it exists under .vibetracing/human_decisions.json.
    """
    import json
    _make_required_files(tmp_path)

    # Pre-populate human_decisions.json
    decisions_dir = tmp_path / ".vibetracing"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    decisions_data = {
        "version": "1.0",
        "decisions": [
            {
                "decision_id": 1,
                "category": "accepted_rule",
                "targetId": "RULE-VT-001",
                "action": "accept",
            }
        ]
    }
    (decisions_dir / "human_decisions.json").write_text(
        json.dumps(decisions_data), encoding="utf-8"
    )

    loader = RawInputLoader(tmp_path, config_data=_MINIMAL_PATHS)
    manifest = loader.load()
    assert manifest.has_required_errors is False

    records = {r.file_key: r for r in manifest.inputs_used}
    assert "human_decisions" in records
    record = records["human_decisions"]
    assert record.status == "ok"
    assert record.content == decisions_data


def test_load_human_decisions_file_missing(tmp_path):
    """
    Verify that RawInputLoader marks human_decisions.json as 'missing'
    when the file is absent, and this does not set has_required_errors.
    """
    _make_required_files(tmp_path)

    loader = RawInputLoader(tmp_path, config_data=_MINIMAL_PATHS)
    manifest = loader.load()
    assert manifest.has_required_errors is False

    records = {r.file_key: r for r in manifest.inputs_used}
    assert "human_decisions" in records
    record = records["human_decisions"]
    assert record.status == "missing"
    assert record.content is None
