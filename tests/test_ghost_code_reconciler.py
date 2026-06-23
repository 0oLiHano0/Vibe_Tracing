"""Tests for GhostCodeReconciler warning on malformed claims CLAIM-*.json files."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from vibe_tracing.domain.governance.ghost_code import GhostCodeReconciler
from vibe_tracing.infra.db import init_in_memory_db


@pytest.fixture
def project(tmp_path: Path):
    """Create a minimal project structure with .vibetracing directory."""
    vibetracing_dir = tmp_path / ".vibetracing"
    claims_dir = vibetracing_dir / "claims"
    claims_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def conn():
    """Create an in-memory SQLite connection for GhostCodeReconciler."""
    return init_in_memory_db()


class TestMalformedClaimsWarning:
    """L7: malformed CLAIM-*.json must not crash the reconciler."""

    def test_malformed_claims_json_does_not_crash(self, project, conn, capsys):
        """When a STAGED claims file contains invalid JSON, it is skipped gracefully."""
        # Init git repo so git show :path works
        subprocess.run(["git", "init"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=project, capture_output=True, check=True)
        (project / "placeholder.txt").write_text("init")
        subprocess.run(["git", "add", "placeholder.txt"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=project, capture_output=True, check=True)

        # Stage a malformed claims file
        claims_path = project / ".vibetracing" / "claims" / "CLAIM-VT-001.json"
        claims_path.write_text("{not valid json!!", encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project, conn)

        # Mock _get_staged_files so reconcile() exercises the claims path
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}):
            ok, msg = reconciler.reconcile()

        # No crash, malformed file is simply skipped
        captured = capsys.readouterr()

    def test_no_claims_file_does_not_warn(self, project, capsys, conn):
        """When claims directory has no files, no format-warning is printed."""
        # Ensure no claims files exist
        claims_dir = project / ".vibetracing" / "claims"
        assert not list(claims_dir.glob("CLAIM-*.json"))

        reconciler = GhostCodeReconciler(project, conn)

        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}):
            ok, msg = reconciler.reconcile()

        captured = capsys.readouterr()
        assert "格式解析失败" not in captured.err

    def test_valid_claims_passes(self, project, capsys, conn):
        """Valid claims with matching code_refs should pass the gate."""
        reconciler = GhostCodeReconciler(project, conn)

        # Mock _get_staged_files and _read_claims_from_filesystem directly
        # to isolate the reconcile gate from git subprocess complexity.
        # Also mock the new Gate 2.5 checks to avoid git repo dependency.
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}), \
             patch.object(reconciler, "_read_claims_from_filesystem", return_value=[
                 {"claim_id": "C-0001", "related_task": "T-0001", "code_refs": ["src/foo.py"]}
             ]), \
             patch.object(reconciler, "_check_task_coverage", return_value=([], [])), \
             patch.object(reconciler, "_check_ac_freshness", return_value=[]):
            ok, msg = reconciler.reconcile()

        assert ok is True
        assert msg == ""

        captured = capsys.readouterr()
        assert "格式解析失败" not in captured.err


class TestNoStagedCodeFiles:
    """When no business code files are staged, the gate must pass."""

    def test_no_staged_files_passes(self, project, conn):
        reconciler = GhostCodeReconciler(project, conn)
        with patch.object(reconciler, "_get_staged_files", return_value=set()):
            ok, msg = reconciler.reconcile()
        assert ok is True
        assert msg == ""

    def test_only_whitelisted_files_passes(self, project, conn):
        """Staging only whitelisted files (e.g. claims, config, output) should pass."""
        reconciler = GhostCodeReconciler(project, conn)
        staged = {
            ".vibetracing/config.json",
            "docs/task_list.json",
            "output/report.json",
            ".git/config",
        }
        with patch.object(reconciler, "_get_staged_files", return_value=staged):
            ok, msg = reconciler.reconcile()
        assert ok is True
        assert msg == ""


class TestNoClaimsFile:
    """Staging code files with no claims file at all must block."""

    def test_no_claims_blocks(self, project, conn):
        """No claims files and staged code files should produce ghost code error."""
        claims_dir = project / ".vibetracing" / "claims"
        assert not list(claims_dir.glob("CLAIM-*.json"))
        reconciler = GhostCodeReconciler(project, conn)
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}):
            ok, msg = reconciler.reconcile()
        assert ok is False
        assert "幽灵代码" in msg or "ghost" in msg.lower() or "src/foo.py" in msg


class TestClaimsCoverCodeRefs:
    """Claims with matching code_refs should let the gate pass."""

    def test_exact_match_passes(self, project, conn):
        claims = [{"claim_id": "C-0001", "related_task": "T-0001", "code_refs": ["src/foo.py", "src/bar.py"]}]
        (project / ".vibetracing" / "claims" / "CLAIM-VT-001.json").write_text(
            json.dumps(claims), encoding="utf-8"
        )
        reconciler = GhostCodeReconciler(project, conn)
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py", "src/bar.py"}), \
             patch.object(reconciler, "_read_claims_from_filesystem", return_value=[
                 {"claim_id": "C-0001", "related_task": "T-0001", "code_refs": ["src/foo.py", "src/bar.py"]}
             ]), \
             patch.object(reconciler, "_check_task_coverage", return_value=([], [])), \
             patch.object(reconciler, "_check_ac_freshness", return_value=[]):
            ok, msg = reconciler.reconcile()
        assert ok is True
        assert msg == ""

    def test_superset_refs_passes(self, project, conn):
        """Claims covering MORE files than staged should still pass."""
        claims = [{"claim_id": "C-0001", "related_task": "T-0001", "code_refs": ["src/foo.py", "src/bar.py", "src/baz.py"]}]
        (project / ".vibetracing" / "claims" / "CLAIM-VT-001.json").write_text(
            json.dumps(claims), encoding="utf-8"
        )
        reconciler = GhostCodeReconciler(project, conn)
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}), \
             patch.object(reconciler, "_read_claims_from_filesystem", return_value=[
                 {"claim_id": "C-0001", "related_task": "T-0001", "code_refs": ["src/foo.py", "src/bar.py", "src/baz.py"]}
             ]), \
             patch.object(reconciler, "_check_task_coverage", return_value=([], [])), \
             patch.object(reconciler, "_check_ac_freshness", return_value=[]):
            ok, msg = reconciler.reconcile()
        assert ok is True
        assert msg == ""

    def test_partial_match_blocks(self, project, conn):
        """Only some staged files covered -- uncovered ones are ghost code."""
        claims = [{"claim_id": "C-0001", "related_task": "T-0001", "code_refs": ["src/foo.py"]}]
        (project / ".vibetracing" / "claims" / "CLAIM-VT-001.json").write_text(
            json.dumps(claims), encoding="utf-8"
        )
        reconciler = GhostCodeReconciler(project, conn)
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py", "src/bar.py"}), \
             patch.object(reconciler, "_read_claims_from_filesystem", return_value=[
                 {"claim_id": "C-0001", "related_task": "T-0001", "code_refs": ["src/foo.py"]}
             ]):
            ok, msg = reconciler.reconcile()
        assert ok is False
        assert "src/bar.py" in msg
        assert "src/foo.py" not in msg


class TestClaimsReferenceNonExistentFile:
    """Claims pointing to files not staged -- permissive, gate still passes."""

    def test_extra_refs_passes(self, project, conn):
        """Claims reference a file not in staged set; gate still passes."""
        claims = [{"claim_id": "C-0001", "related_task": "T-0001", "code_refs": ["src/foo.py", "src/ghost.py"]}]
        (project / ".vibetracing" / "claims" / "CLAIM-VT-001.json").write_text(
            json.dumps(claims), encoding="utf-8"
        )
        reconciler = GhostCodeReconciler(project, conn)
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}), \
             patch.object(reconciler, "_read_claims_from_filesystem", return_value=[
                 {"claim_id": "C-0001", "related_task": "T-0001", "code_refs": ["src/foo.py", "src/ghost.py"]}
             ]), \
             patch.object(reconciler, "_check_task_coverage", return_value=([], [])), \
             patch.object(reconciler, "_check_ac_freshness", return_value=[]):
            ok, msg = reconciler.reconcile()
        assert ok is True
        assert msg == ""


class TestEmptyClaimsArray:
    """Empty claims array means no active refs -- any staged code is ghost."""

    def test_empty_claims_blocks(self, project, conn):
        # Empty directory -- no CLAIM-*.json files
        reconciler = GhostCodeReconciler(project, conn)
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}), \
             patch.object(reconciler, "_read_claims_from_filesystem", return_value=[]):
            ok, msg = reconciler.reconcile()
        assert ok is False
        assert "src/foo.py" in msg


class TestReadClaimsFromFilesystem:
    """Tests for _read_claims_from_filesystem: reading CLAIM-*.json from disk."""

    def test_valid_claims_read(self, project, conn):
        """Claims on disk are returned."""
        claims = [{"claim_id": "C-0001", "related_task": "T-0001", "code_refs": ["src/foo.py"]}]
        claims_path = project / ".vibetracing" / "claims" / "CLAIM-VT-001.json"
        claims_path.write_text(json.dumps(claims), encoding="utf-8")

        reconciler = GhostCodeReconciler(project, conn)
        result = reconciler._read_claims_from_filesystem()
        assert len(result) == 1
        assert result[0]["claim_id"] == "C-0001"
        assert result[0]["code_refs"] == ["src/foo.py"]

    def test_malformed_json_skipped(self, project, conn):
        """Malformed JSON files are skipped gracefully."""
        claims_path = project / ".vibetracing" / "claims" / "CLAIM-VT-001.json"
        claims_path.write_text("{not valid json!!", encoding="utf-8")

        reconciler = GhostCodeReconciler(project, conn)
        result = reconciler._read_claims_from_filesystem()
        assert result == []

    def test_empty_directory(self, project, conn):
        """Empty claims dir returns empty list."""
        reconciler = GhostCodeReconciler(project, conn)
        result = reconciler._read_claims_from_filesystem()
        assert result == []

    def test_template_record_skipped(self, project, conn):
        """claim_id ending in -9999 is filtered out."""
        template = {"claim_id": "C-9999", "related_task": "T-0001", "code_refs": ["src/template.py"]}
        claims_path = project / ".vibetracing" / "claims" / "CLAIM-VT-001.json"
        claims_path.write_text(json.dumps([template]), encoding="utf-8")

        reconciler = GhostCodeReconciler(project, conn)
        result = reconciler._read_claims_from_filesystem()
        assert len(result) == 0

    def test_missing_required_fields_skipped(self, project, conn):
        """Claims without claim_id or related_task are skipped."""
        # Missing claim_id
        no_id = {"related_task": "T-0001", "code_refs": ["src/a.py"]}
        # Missing related_task
        no_task = {"claim_id": "C-0001", "code_refs": ["src/b.py"]}
        # Valid
        valid = {"claim_id": "C-0002", "related_task": "T-0002", "code_refs": ["src/c.py"]}

        claims_path = project / ".vibetracing" / "claims" / "CLAIM-VT-001.json"
        claims_path.write_text(json.dumps([no_id, no_task, valid]), encoding="utf-8")

        reconciler = GhostCodeReconciler(project, conn)
        result = reconciler._read_claims_from_filesystem()
        assert len(result) == 1
        assert result[0]["claim_id"] == "C-0002"

    def test_single_claim_file(self, project, conn):
        """Single claim file with a list of claims."""
        claims = [
            {"claim_id": "C-0001", "related_task": "T-0001", "code_refs": ["src/a.py"]},
            {"claim_id": "C-0002", "related_task": "T-0002", "code_refs": ["src/b.py"]},
        ]
        claims_path = project / ".vibetracing" / "claims" / "CLAIM-VT-001.json"
        claims_path.write_text(json.dumps(claims), encoding="utf-8")

        reconciler = GhostCodeReconciler(project, conn)
        result = reconciler._read_claims_from_filesystem()
        assert len(result) == 2

    def test_multiple_claim_files(self, project, conn):
        """Multiple CLAIM-*.json files are all read."""
        claims1 = [{"claim_id": "C-0001", "related_task": "T-0001", "code_refs": ["src/a.py"]}]
        claims2 = [{"claim_id": "C-0002", "related_task": "T-0002", "code_refs": ["src/b.py"]}]
        (project / ".vibetracing" / "claims" / "CLAIM-VT-001.json").write_text(
            json.dumps(claims1), encoding="utf-8"
        )
        (project / ".vibetracing" / "claims" / "CLAIM-VT-002.json").write_text(
            json.dumps(claims2), encoding="utf-8"
        )

        reconciler = GhostCodeReconciler(project, conn)
        result = reconciler._read_claims_from_filesystem()
        assert len(result) == 2
        claim_ids = {r["claim_id"] for r in result}
        assert claim_ids == {"C-0001", "C-0002"}


class TestWhitelistLogic:
    """Verify _is_whitelisted correctly identifies whitelisted paths."""

    def test_exact_whitelist_paths(self, project, conn):
        reconciler = GhostCodeReconciler(project, conn)
        for path in [".vibetracing/claims/CLAIM-VT-001.json", ".vibetracing/config.json", "docs/task_list.json"]:
            assert reconciler._is_whitelisted(path) is True

    def test_prefix_whitelist(self, project, conn):
        reconciler = GhostCodeReconciler(project, conn)
        assert reconciler._is_whitelisted(".git/config") is True
        assert reconciler._is_whitelisted("output/report.html") is True

    def test_non_whitelisted(self, project, conn):
        reconciler = GhostCodeReconciler(project, conn)
        assert reconciler._is_whitelisted("src/main.py") is False
        assert reconciler._is_whitelisted("README.md") is False


class TestMalformedFilesystemClaims:
    """When claims files on disk have malformed JSON, they are silently skipped."""

    def test_malformed_claims_on_disk_silently_skipped(self, project, conn):
        """If a CLAIM-*.json on disk contains invalid JSON, it is silently skipped."""
        claims_path = project / ".vibetracing" / "claims" / "CLAIM-VT-001.json"
        claims_path.write_text("{invalid", encoding="utf-8")

        reconciler = GhostCodeReconciler(project, conn)
        result = reconciler._read_claims_from_filesystem()
        assert result == []


class TestGitNotInstalled:
    """L6: FileNotFoundError from subprocess.run must be caught gracefully."""

    @patch("vibe_tracing.infra.git.utils.subprocess.run", side_effect=FileNotFoundError)
    def test_git_not_installed_graceful(self, mock_run, project, conn):
        """When git is not on PATH, reconcile() returns gracefully without crashing."""
        reconciler = GhostCodeReconciler(project, conn)
        ok, msg = reconciler.reconcile()

        assert ok is True
        assert msg == ""


# ------------------------------------------------------------------
# Helper to create a real git repo for integration-style tests
# ------------------------------------------------------------------

def _init_git_repo(project: Path):
    """Initialize a git repo with an initial commit so HEAD exists."""
    subprocess.run(["git", "init"], cwd=project, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=project, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=project, capture_output=True, check=True,
    )
    (project / "docs").mkdir(exist_ok=True)
    (project / ".vibetracing").mkdir(exist_ok=True)
    (project / ".vibetracing" / "claims").mkdir(exist_ok=True)
    (project / "src").mkdir(exist_ok=True)
    (project / "placeholder.txt").write_text("init")
    subprocess.run(["git", "add", "placeholder.txt"], cwd=project, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=project, capture_output=True, check=True)


# ------------------------------------------------------------------
# EVO-TASK-011a: Reverse coverage check tests
# ------------------------------------------------------------------

class TestTaskCoverageCheck:
    """Tests for _check_task_coverage: staged code vs covering tasks."""

    def test_task_missing_blocks(self, project, conn):
        """Claim references a task that does not exist in task_list.json -> BLOCKED."""
        # Write claims on disk referencing a task
        claims = [{"claim_id": "C-0001", "related_task": "TASK-MISSING", "code_refs": ["src/foo.py"]}]
        claims_path = project / ".vibetracing" / "claims" / "CLAIM-VT-001.json"
        claims_path.parent.mkdir(parents=True, exist_ok=True)
        claims_path.write_text(json.dumps(claims), encoding="utf-8")

        # Write task_list.json WITHOUT the referenced task
        (project / "docs").mkdir(parents=True, exist_ok=True)
        task_list = {"tasks": [{"task_id": "TASK-OTHER", "title": "Other"}]}
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")

        reconciler = GhostCodeReconciler(project, conn)
        blocked, warnings = reconciler._check_task_coverage({"src/foo.py"})
        assert len(blocked) == 1
        assert "TASK-MISSING" in blocked[0]
        assert len(warnings) == 0

    def test_file_not_covered_skipped(self, project, conn):
        """File not covered by any claim is skipped (ghost code check handles it)."""
        reconciler = GhostCodeReconciler(project, conn)
        blocked, warnings = reconciler._check_task_coverage({"src/uncovered.py"})
        assert len(blocked) == 0
        assert len(warnings) == 0

    def test_task_exists_no_blocks(self, project, conn):
        """Claim references a task that exists in task_list.json -> no block."""
        claims = [{"claim_id": "C-0001", "related_task": "TASK-001", "code_refs": ["src/foo.py"]}]
        claims_path = project / ".vibetracing" / "claims" / "CLAIM-VT-001.json"
        claims_path.parent.mkdir(parents=True, exist_ok=True)
        claims_path.write_text(json.dumps(claims), encoding="utf-8")

        (project / "docs").mkdir(parents=True, exist_ok=True)
        task_list = {"tasks": [{"task_id": "TASK-001", "title": "T1"}]}
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")

        reconciler = GhostCodeReconciler(project, conn)
        blocked, warnings = reconciler._check_task_coverage({"src/foo.py"})
        assert len(blocked) == 0
        assert len(warnings) == 0

    def test_code_ref_with_line_range(self, project, conn):
        """code_refs with #L1-L10 suffix should be stripped for matching."""
        claims = [{"claim_id": "C-001", "related_task": "TASK-001", "code_refs": ["src/foo.py#L1-L10"]}]
        claims_path = project / ".vibetracing" / "claims" / "CLAIM-VT-001.json"
        claims_path.parent.mkdir(parents=True, exist_ok=True)
        claims_path.write_text(json.dumps(claims), encoding="utf-8")

        (project / "docs").mkdir(parents=True, exist_ok=True)
        task_list = {"tasks": [{"task_id": "TASK-001", "title": "Modified"}]}
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")

        reconciler = GhostCodeReconciler(project, conn)
        # src/foo.py should match despite line range in claim
        blocked, warnings = reconciler._check_task_coverage({"src/foo.py"})
        assert len(blocked) == 0
        assert len(warnings) == 0

    def test_no_task_list_file_blocks(self, project, conn):
        """When task_list.json doesn't exist, tasks are treated as missing -> BLOCKED."""
        claims = [{"claim_id": "C-0001", "related_task": "TASK-001", "code_refs": ["src/foo.py"]}]
        claims_path = project / ".vibetracing" / "claims" / "CLAIM-VT-001.json"
        claims_path.parent.mkdir(parents=True, exist_ok=True)
        claims_path.write_text(json.dumps(claims), encoding="utf-8")

        # No task_list.json on disk
        reconciler = GhostCodeReconciler(project, conn)
        blocked, warnings = reconciler._check_task_coverage({"src/foo.py"})
        assert len(blocked) == 1
        assert "TASK-001" in blocked[0]

    def test_reconcile_blocks_on_task_coverage_failure(self, project, conn):
        """reconcile() returns False when _check_task_coverage returns BLOCKED."""
        _init_git_repo(project)

        # Write claims on disk referencing TASK-MISSING
        claims = [{"claim_id": "C-0001", "related_task": "TASK-MISSING", "code_refs": ["src/foo.py"]}]
        claims_path = project / ".vibetracing" / "claims" / "CLAIM-VT-001.json"
        claims_path.write_text(json.dumps(claims), encoding="utf-8")

        # Write task_list WITHOUT TASK-MISSING
        task_list = {"tasks": [{"task_id": "TASK-EXISTING", "title": "Existing"}]}
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")

        # Write and stage the code file
        (project / "src" / "foo.py").write_text("print('modified')", encoding="utf-8")
        subprocess.run(["git", "add", "src/foo.py"], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project, conn)
        ok, msg = reconciler.reconcile()
        assert ok is False
        assert "TASK-MISSING" in msg


# ------------------------------------------------------------------
# EVO-TASK-011b: Forward AC freshness check tests
# ------------------------------------------------------------------

class TestACFreshnessCheck:
    """Tests for _check_ac_freshness: tasks referencing ACs not in PRD."""

    def test_task_with_stale_ac_warns(self, project, conn):
        """Task referencing an AC not in PRD -> WARNING."""
        (project / "docs").mkdir(parents=True, exist_ok=True)
        task_list = {
            "tasks": [
                {"task_id": "TASK-001", "title": "T1", "related_acceptance_criteria": ["AC-VT-999-01"]}
            ]
        }
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")

        # PRD WITHOUT AC-VT-999-01
        prd = "# PRD\n### REQ-VT-001\n##### AC-VT-001-01: Basic\n"
        (project / "docs" / "prd.md").write_text(prd, encoding="utf-8")

        reconciler = GhostCodeReconciler(project, conn)
        warnings = reconciler._check_ac_freshness()
        assert len(warnings) == 1
        assert "TASK-001" in warnings[0]
        assert "AC-VT-999-01" in warnings[0]

    def test_task_with_fresh_ac_no_warning(self, project, conn):
        """Task referencing an AC present in PRD -> no warning."""
        (project / "docs").mkdir(parents=True, exist_ok=True)
        task_list = {
            "tasks": [
                {"task_id": "TASK-001", "title": "T1", "related_acceptance_criteria": ["AC-VT-001-01"]}
            ]
        }
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")

        # PRD WITH AC-VT-001-01
        prd = "# PRD\n### REQ-VT-001\n##### AC-VT-001-01: Basic\n"
        (project / "docs" / "prd.md").write_text(prd, encoding="utf-8")

        reconciler = GhostCodeReconciler(project, conn)
        warnings = reconciler._check_ac_freshness()
        assert len(warnings) == 0

    def test_prd_not_found_warns(self, project, conn):
        """When PRD file does not exist on disk but tasks reference ACs -> WARNING."""
        (project / "docs").mkdir(parents=True, exist_ok=True)
        task_list = {
            "tasks": [
                {"task_id": "TASK-001", "title": "T1", "related_acceptance_criteria": ["AC-VT-001-01"]}
            ]
        }
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")

        # No PRD file on disk
        reconciler = GhostCodeReconciler(project, conn)
        warnings = reconciler._check_ac_freshness()
        assert len(warnings) == 1
        assert "PRD" in warnings[0]

    def test_task_without_ac_no_warning(self, project, conn):
        """Task with empty related_acceptance_criteria -> no warning."""
        (project / "docs").mkdir(parents=True, exist_ok=True)
        task_list = {
            "tasks": [
                {"task_id": "TASK-001", "title": "T1", "related_acceptance_criteria": []}
            ]
        }
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")

        reconciler = GhostCodeReconciler(project, conn)
        warnings = reconciler._check_ac_freshness()
        assert len(warnings) == 0

    def test_no_task_list_no_warning(self, project, conn):
        """When task_list.json doesn't exist, no warnings."""
        reconciler = GhostCodeReconciler(project, conn)
        warnings = reconciler._check_ac_freshness()
        assert len(warnings) == 0

    def test_reconcile_appends_ac_warnings(self, project, conn):
        """reconcile() appends AC freshness warnings to the result message."""
        _init_git_repo(project)

        # Write claims on disk that pass ghost code check
        claims = [{"claim_id": "C-0001", "related_task": "TASK-001", "code_refs": ["src/foo.py"]}]
        claims_path = project / ".vibetracing" / "claims" / "CLAIM-VT-001.json"
        claims_path.parent.mkdir(parents=True, exist_ok=True)
        claims_path.write_text(json.dumps(claims), encoding="utf-8")

        # Write task_list with TASK-001 referencing AC-VT-999-01
        task_list = {
            "tasks": [
                {"task_id": "TASK-001", "title": "T1", "related_acceptance_criteria": ["AC-VT-999-01"]}
            ]
        }
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")

        # Write PRD WITHOUT AC-VT-999-01
        prd = "# PRD\n### REQ-VT-001\n##### AC-VT-001-01: Basic\n"
        (project / "docs" / "prd.md").write_text(prd, encoding="utf-8")

        # Stage the code file
        (project / "src" / "foo.py").write_text("print('hello')", encoding="utf-8")
        subprocess.run(["git", "add", "src/foo.py"], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project, conn)
        # Mock _get_staged_files to only report business code files (not PRD/docs)
        # so the ghost code check passes
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}):
            ok, msg = reconciler.reconcile()
        assert ok is True
        assert "AC-VT-999-01" in msg
        assert "AC 新鲜度提醒" in msg
