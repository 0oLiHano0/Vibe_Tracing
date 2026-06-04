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
    Verify that RawInputLoader loads custom paths from .vibetracing/config.json,
    and falls back to standard paths when config is missing.
    """
    import json

    # 1. Test fallback when config is missing
    # Create default structure
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "prd.md").write_text("# Default PRD", encoding="utf-8")
    (tmp_path / "docs" / "architecture_constraints.json").write_text(
        '{"constraints": []}', encoding="utf-8"
    )
    (tmp_path / "docs" / "task_list.json").write_text('{"tasks": []}', encoding="utf-8")

    loader = RawInputLoader(tmp_path)
    manifest = loader.load()
    assert manifest.has_required_errors is False
    records = {r.file_key: r for r in manifest.inputs_used}
    assert records["prd"].content == "# Default PRD"

    # 2. Test custom config paths override
    config_dir = tmp_path / ".vibetracing"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"

    config_data = {
        "schema_version": "1.0.0",
        "project_id": "PROJECT-VT",
        "paths": {
            "prd": "custom_dir/custom_prd.md",
            "architecture_constraints": "docs/architecture_constraints.json",
            "task_list": "docs/task_list.json",
        },
    }
    config_file.write_text(json.dumps(config_data), encoding="utf-8")

    # Create custom PRD file
    (tmp_path / "custom_dir").mkdir(parents=True, exist_ok=True)
    (tmp_path / "custom_dir" / "custom_prd.md").write_text(
        "# Custom PRD", encoding="utf-8"
    )

    loader_custom = RawInputLoader(tmp_path)
    manifest_custom = loader_custom.load()
    assert manifest_custom.has_required_errors is False
    records_custom = {r.file_key: r for r in manifest_custom.inputs_used}
    assert records_custom["prd"].content == "# Custom PRD"


def test_self_governance_rules_contract(tmp_path):
    """
    covers: AC-VT-009-06
    Verify that architecture constraints drift is detected via hash comparison
    and reported as warnings (read-only). check_governance always returns
    is_valid=True — it never blocks, only exposes drift for human review.
    """
    import hashlib
    import json
    from unittest.mock import patch

    from vibe_tracing.architecture_change_proposal import (
        ArchitectureChangeProposalEngine,
    )

    # Set up basic required files
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vibetracing").mkdir(parents=True, exist_ok=True)

    base_constraints = {"schema_version": "1.0.0", "quality_gates": []}
    modified_constraints = {
        "schema_version": "1.0.0",
        "quality_gates": [{"gate_id": "GATE-VT-099", "severity": "must"}],
    }

    # Write modified constraints (current state)
    (tmp_path / "docs" / "architecture_constraints.json").write_text(
        json.dumps(modified_constraints), encoding="utf-8"
    )
    (tmp_path / "docs" / "prd.md").write_text("# PRD", encoding="utf-8")
    (tmp_path / "docs" / "task_list.json").write_text('{"tasks": []}', encoding="utf-8")

    # 1. No stored hash -> check_governance skips, is_valid=True, no warnings
    config = {"project_id": "PROJECT-VT", "paths": {}}
    (tmp_path / ".vibetracing" / "config.json").write_text(
        json.dumps(config), encoding="utf-8"
    )

    proposal = ArchitectureChangeProposalEngine(tmp_path)
    res = proposal.check_governance()
    assert res["is_valid"] is True
    assert len(res["warnings"]) == 0
    assert len(res["errors"]) == 0

    # 2. Hash mismatch (drift detected) + git_show reveals rule change
    #    -> is_valid=True, warnings with diff details
    config["architecture_constraints_hash"] = "old_stored_hash"
    config["finalize_git_commit"] = "abc123"
    config["finalize_constraints_path"] = "docs/architecture_constraints.json"
    (tmp_path / ".vibetracing" / "config.json").write_text(
        json.dumps(config), encoding="utf-8"
    )

    with patch(
        "vibe_tracing.architecture_change_proposal.git_show",
        return_value=json.dumps(base_constraints),
    ):
        proposal = ArchitectureChangeProposalEngine(tmp_path)
        res = proposal.check_governance()

    # check_governance is read-only: always is_valid=True
    assert res["is_valid"] is True
    assert len(res["errors"]) == 0
    assert len(res["warnings"]) > 0
    # Diff details should mention GATE-VT-099
    assert any("GATE-VT-099" in w for w in res["warnings"])
