"""Tests for GhostCodeReconciler warning on malformed claims/current.json."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from vibe_tracing.ghost_code_reconciler import GhostCodeReconciler


@pytest.fixture
def project(tmp_path: Path):
    """Create a minimal project structure with .vibetracing directory."""
    vibetracing_dir = tmp_path / ".vibetracing"
    claims_dir = vibetracing_dir / "claims"
    claims_dir.mkdir(parents=True)
    return tmp_path


class TestMalformedClaimsWarning:
    """L7: malformed claims/current.json must print a warning to stderr."""

    def test_malformed_claims_json_prints_warning(self, project, capsys):
        """When STAGED claims file contains invalid JSON, a warning appears on stderr."""
        # Init git repo so git show :path works
        subprocess.run(["git", "init"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=project, capture_output=True, check=True)
        (project / "placeholder.txt").write_text("init")
        subprocess.run(["git", "add", "placeholder.txt"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=project, capture_output=True, check=True)

        # Stage a malformed claims file
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        claims_path.write_text("{not valid json!!", encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)

        # Mock _get_staged_files so reconcile() exercises the claims path
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}):
            ok, msg = reconciler.reconcile()

        captured = capsys.readouterr()
        assert "claims/current.json" in captured.err
        assert "格式解析失败" in captured.err

    def test_no_claims_file_does_not_warn(self, project, capsys):
        """When claims file does not exist, no format-warning is printed."""
        # Ensure claims file does NOT exist
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        assert not claims_path.exists()

        reconciler = GhostCodeReconciler(project)

        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}):
            ok, msg = reconciler.reconcile()

        captured = capsys.readouterr()
        assert "格式解析失败" not in captured.err

    def test_valid_claims_passes(self, project, capsys):
        """Valid claims with matching code_refs should pass the gate."""
        # Write valid claims
        claims = [
            {
                "claim_id": "CLAIM-0001",
                "code_refs": ["src/foo.py"],
                "description": "foo change",
            }
        ]
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        claims_path.write_text(json.dumps(claims), encoding="utf-8")

        reconciler = GhostCodeReconciler(project)

        # Mock _get_staged_files and _get_active_claims_code_refs directly
        # to isolate the reconcile gate from git subprocess complexity.
        # Also mock the new Gate 2.5 checks to avoid git repo dependency.
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}), \
             patch.object(reconciler, "_get_active_claims_code_refs", return_value={"src/foo.py"}), \
             patch.object(reconciler, "_check_task_coverage", return_value=([], [])), \
             patch.object(reconciler, "_check_ac_freshness", return_value=[]):
            ok, msg = reconciler.reconcile()

        assert ok is True
        assert msg == ""

        captured = capsys.readouterr()
        assert "格式解析失败" not in captured.err


class TestNoStagedCodeFiles:
    """When no business code files are staged, the gate must pass."""

    def test_no_staged_files_passes(self, project):
        reconciler = GhostCodeReconciler(project)
        with patch.object(reconciler, "_get_staged_files", return_value=set()):
            ok, msg = reconciler.reconcile()
        assert ok is True
        assert msg == ""

    def test_only_whitelisted_files_passes(self, project):
        """Staging only whitelisted files (e.g. claims, config, output) should pass."""
        reconciler = GhostCodeReconciler(project)
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

    def test_no_claims_blocks(self, project):
        """No claims file and staged code files should produce ghost code error."""
        assert not (project / ".vibetracing" / "claims" / "current.json").exists()
        reconciler = GhostCodeReconciler(project)
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}):
            ok, msg = reconciler.reconcile()
        assert ok is False
        assert "幽灵代码" in msg or "ghost" in msg.lower() or "src/foo.py" in msg


class TestClaimsCoverCodeRefs:
    """Claims with matching code_refs should let the gate pass."""

    def test_exact_match_passes(self, project):
        claims = [{"claim_id": "C-0001", "code_refs": ["src/foo.py", "src/bar.py"]}]
        (project / ".vibetracing" / "claims" / "current.json").write_text(
            json.dumps(claims), encoding="utf-8"
        )
        reconciler = GhostCodeReconciler(project)
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py", "src/bar.py"}), \
             patch.object(reconciler, "_get_active_claims_code_refs", return_value={"src/foo.py", "src/bar.py"}), \
             patch.object(reconciler, "_check_task_coverage", return_value=([], [])), \
             patch.object(reconciler, "_check_ac_freshness", return_value=[]):
            ok, msg = reconciler.reconcile()
        assert ok is True
        assert msg == ""

    def test_superset_refs_passes(self, project):
        """Claims covering MORE files than staged should still pass."""
        claims = [{"claim_id": "C-0001", "code_refs": ["src/foo.py", "src/bar.py", "src/baz.py"]}]
        (project / ".vibetracing" / "claims" / "current.json").write_text(
            json.dumps(claims), encoding="utf-8"
        )
        reconciler = GhostCodeReconciler(project)
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}), \
             patch.object(reconciler, "_get_active_claims_code_refs", return_value={"src/foo.py", "src/bar.py", "src/baz.py"}), \
             patch.object(reconciler, "_check_task_coverage", return_value=([], [])), \
             patch.object(reconciler, "_check_ac_freshness", return_value=[]):
            ok, msg = reconciler.reconcile()
        assert ok is True
        assert msg == ""

    def test_partial_match_blocks(self, project):
        """Only some staged files covered -- uncovered ones are ghost code."""
        claims = [{"claim_id": "C-0001", "code_refs": ["src/foo.py"]}]
        (project / ".vibetracing" / "claims" / "current.json").write_text(
            json.dumps(claims), encoding="utf-8"
        )
        reconciler = GhostCodeReconciler(project)
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py", "src/bar.py"}), \
             patch.object(reconciler, "_get_active_claims_code_refs", return_value={"src/foo.py"}):
            ok, msg = reconciler.reconcile()
        assert ok is False
        assert "src/bar.py" in msg
        assert "src/foo.py" not in msg


class TestClaimsReferenceNonExistentFile:
    """Claims pointing to files not staged -- permissive, gate still passes."""

    def test_extra_refs_passes(self, project):
        """Claims reference a file not in staged set; gate still passes."""
        claims = [{"claim_id": "C-0001", "code_refs": ["src/foo.py", "src/ghost.py"]}]
        (project / ".vibetracing" / "claims" / "current.json").write_text(
            json.dumps(claims), encoding="utf-8"
        )
        reconciler = GhostCodeReconciler(project)
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}), \
             patch.object(reconciler, "_get_active_claims_code_refs", return_value={"src/foo.py", "src/ghost.py"}), \
             patch.object(reconciler, "_check_task_coverage", return_value=([], [])), \
             patch.object(reconciler, "_check_ac_freshness", return_value=[]):
            ok, msg = reconciler.reconcile()
        assert ok is True
        assert msg == ""


class TestEmptyClaimsArray:
    """Empty claims array means no active refs -- any staged code is ghost."""

    def test_empty_claims_blocks(self, project):
        (project / ".vibetracing" / "claims" / "current.json").write_text("[]", encoding="utf-8")
        reconciler = GhostCodeReconciler(project)
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}), \
             patch.object(reconciler, "_get_active_claims_code_refs", return_value=set()):
            ok, msg = reconciler.reconcile()
        assert ok is False
        assert "src/foo.py" in msg


class TestDeltaCalculation:
    """Tests for the 'State is Delta' logic in _get_active_claims_code_refs."""

    def _init_git_repo(self, project: Path):
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
        (project / ".vibetracing" / "claims").mkdir(parents=True, exist_ok=True)

    def test_new_claim_in_staged_not_in_head_is_active(self, project):
        """A claim present in the staged file but absent from HEAD is 'new' and active."""
        self._init_git_repo(project)
        # Initial commit with no claims file
        (project / "placeholder.txt").write_text("init")
        subprocess.run(["git", "add", "placeholder.txt"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=project, capture_output=True, check=True)

        # Now write a new claims file and stage it
        new_claim = {"claim_id": "C-0001", "code_refs": ["src/new.py"]}
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        claims_path.write_text(json.dumps([new_claim]), encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)
        refs = reconciler._get_active_claims_code_refs()
        assert "src/new.py" in refs

    def test_identical_claim_in_staged_and_head_is_not_active(self, project):
        """A claim identical in staged and HEAD is NOT active (already committed)."""
        self._init_git_repo(project)
        existing_claim = {"claim_id": "C-0001", "code_refs": ["src/old.py"]}
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        claims_path.write_text(json.dumps([existing_claim]), encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "add claims"], cwd=project, capture_output=True, check=True)

        # Claims file is unchanged in working tree
        reconciler = GhostCodeReconciler(project)
        refs = reconciler._get_active_claims_code_refs()
        assert "src/old.py" not in refs

    def test_modified_claim_is_active(self, project):
        """A claim modified between HEAD and staged is active."""
        self._init_git_repo(project)
        old_claim = {"claim_id": "C-0001", "code_refs": ["src/old.py"]}
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        claims_path.write_text(json.dumps([old_claim]), encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "add claims"], cwd=project, capture_output=True, check=True)

        # Modify the claim's code_refs and stage it
        modified_claim = {"claim_id": "C-0001", "code_refs": ["src/updated.py"]}
        claims_path.write_text(json.dumps([modified_claim]), encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)
        refs = reconciler._get_active_claims_code_refs()
        assert "src/updated.py" in refs
        assert "src/old.py" not in refs

    def test_template_record_skipped(self, project):
        """Claims ending with -9999 are template records and should be ignored."""
        self._init_git_repo(project)
        (project / "placeholder.txt").write_text("init")
        subprocess.run(["git", "add", "placeholder.txt"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=project, capture_output=True, check=True)

        template = {"claim_id": "C-9999", "code_refs": ["src/template.py"]}
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        claims_path.write_text(json.dumps([template]), encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)
        refs = reconciler._get_active_claims_code_refs()
        assert "src/template.py" not in refs

    def test_unstaged_claims_are_not_seen(self, project):
        """Claims written to working directory but NOT staged must be invisible to the reconciler.

        This is the core bypass fix: an AI agent writes a claim file but forgets
        to `git add` it.  The reconciler must NOT pick up that unstaged claim.
        """
        self._init_git_repo(project)
        (project / "placeholder.txt").write_text("init")
        subprocess.run(["git", "add", "placeholder.txt"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=project, capture_output=True, check=True)

        # Write claims to working directory only -- do NOT git add
        claim = {"claim_id": "C-0001", "code_refs": ["src/ghost.py"]}
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        claims_path.write_text(json.dumps([claim]), encoding="utf-8")

        reconciler = GhostCodeReconciler(project)
        refs = reconciler._get_active_claims_code_refs()
        # Unstaged claims must be invisible
        assert "src/ghost.py" not in refs
        assert refs == set()

    def test_staged_claims_are_seen(self, project):
        """Claims that are properly `git add`-ed must be visible to the reconciler."""
        self._init_git_repo(project)
        (project / "placeholder.txt").write_text("init")
        subprocess.run(["git", "add", "placeholder.txt"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=project, capture_output=True, check=True)

        # Write claims AND stage them
        claim = {"claim_id": "C-0001", "code_refs": ["src/visible.py"]}
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        claims_path.write_text(json.dumps([claim]), encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)
        refs = reconciler._get_active_claims_code_refs()
        assert "src/visible.py" in refs


class TestWhitelistLogic:
    """Verify _is_whitelisted correctly identifies whitelisted paths."""

    def test_exact_whitelist_paths(self, project):
        reconciler = GhostCodeReconciler(project)
        for path in [".vibetracing/claims/current.json", ".vibetracing/config.json", "docs/task_list.json"]:
            assert reconciler._is_whitelisted(path) is True

    def test_prefix_whitelist(self, project):
        reconciler = GhostCodeReconciler(project)
        assert reconciler._is_whitelisted(".git/config") is True
        assert reconciler._is_whitelisted("output/report.html") is True

    def test_non_whitelisted(self, project):
        reconciler = GhostCodeReconciler(project)
        assert reconciler._is_whitelisted("src/main.py") is False
        assert reconciler._is_whitelisted("README.md") is False


class TestMalformedHeadClaims:
    """When HEAD has malformed claims JSON, warning is printed and treated as empty."""

    def test_malformed_head_claims_warns(self, project, capsys):
        """If git show HEAD:... returns garbage, a warning is printed."""
        reconciler = GhostCodeReconciler(project)

        # Set up a real git repo
        subprocess.run(["git", "init"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=project, capture_output=True, check=True)

        # Commit with valid claims
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        claims_path.write_text(json.dumps([{"claim_id": "C-0001", "code_refs": ["a.py"]}]), encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=project, capture_output=True, check=True)

        # Overwrite working copy with garbage
        claims_path.write_text("{invalid", encoding="utf-8")

        # Patch subprocess.run so `git show HEAD:...` returns garbage too
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            if isinstance(cmd, list) and "show" in cmd:
                r = MagicMock()
                r.stdout = "bad json"
                return r
            return original_run(cmd, **kwargs)

        with patch("vibe_tracing.ghost_code_reconciler.subprocess.run", side_effect=fake_run):
            refs = reconciler._get_active_claims_code_refs()

        assert refs == set()
        captured = capsys.readouterr()
        assert "格式解析失败" in captured.err


class TestGitNotInstalled:
    """L6: FileNotFoundError from subprocess.run must be caught gracefully."""

    @patch("vibe_tracing.ghost_code_reconciler.subprocess.run", side_effect=FileNotFoundError)
    def test_git_not_installed_graceful(self, mock_run, project):
        """When git is not on PATH, reconcile() returns gracefully without crashing."""
        reconciler = GhostCodeReconciler(project)
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

    def test_task_missing_blocks(self, project):
        """Claim references a task that does not exist in task_list.json -> BLOCKED."""
        _init_git_repo(project)

        # Write staged claims referencing a task
        claims = [{"claim_id": "C-0001", "related_task": "TASK-MISSING", "code_refs": ["src/foo.py"]}]
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        claims_path.parent.mkdir(parents=True, exist_ok=True)
        claims_path.write_text(json.dumps(claims), encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        # Write staged task_list.json WITHOUT the referenced task
        task_list = {"tasks": [{"task_id": "TASK-OTHER", "title": "Other"}]}
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
        subprocess.run(["git", "add", "docs/task_list.json"], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)
        blocked, warnings = reconciler._check_task_coverage({"src/foo.py"}, {"src/foo.py"})
        assert len(blocked) == 1
        assert "TASK-MISSING" in blocked[0]
        assert len(warnings) == 0

    def test_task_not_modified_warns(self, project):
        """Claim references a task that exists but was not modified -> WARNING."""
        _init_git_repo(project)

        # Commit task_list with TASK-001
        task_list = {"tasks": [{"task_id": "TASK-001", "title": "Original"}]}
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
        subprocess.run(["git", "add", "docs/task_list.json"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "add tasks"], cwd=project, capture_output=True, check=True)

        # Stage claims referencing TASK-001
        claims = [{"claim_id": "C-0001", "related_task": "TASK-001", "code_refs": ["src/foo.py"]}]
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        claims_path.parent.mkdir(parents=True, exist_ok=True)
        claims_path.write_text(json.dumps(claims), encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        # Stage task_list WITHOUT modifying TASK-001 (same content)
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
        subprocess.run(["git", "add", "docs/task_list.json"], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)
        blocked, warnings = reconciler._check_task_coverage({"src/foo.py"}, {"src/foo.py"})
        assert len(blocked) == 0
        assert len(warnings) == 1
        assert "TASK-001" in warnings[0]

    def test_task_modified_no_warning(self, project):
        """Claim references a task that WAS modified -> no warning."""
        _init_git_repo(project)

        # Commit task_list with TASK-001
        task_list_old = {"tasks": [{"task_id": "TASK-001", "title": "Original"}]}
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list_old), encoding="utf-8")
        subprocess.run(["git", "add", "docs/task_list.json"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "add tasks"], cwd=project, capture_output=True, check=True)

        # Stage claims referencing TASK-001
        claims = [{"claim_id": "C-0001", "related_task": "TASK-001", "code_refs": ["src/foo.py"]}]
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        claims_path.parent.mkdir(parents=True, exist_ok=True)
        claims_path.write_text(json.dumps(claims), encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        # Modify TASK-001 in staged task_list
        task_list_new = {"tasks": [{"task_id": "TASK-001", "title": "Modified"}]}
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list_new), encoding="utf-8")
        subprocess.run(["git", "add", "docs/task_list.json"], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)
        blocked, warnings = reconciler._check_task_coverage({"src/foo.py"}, {"src/foo.py"})
        assert len(blocked) == 0
        assert len(warnings) == 0

    def test_file_not_covered_skipped(self, project):
        """File not covered by any claim is skipped (ghost code check handles it)."""
        _init_git_repo(project)

        reconciler = GhostCodeReconciler(project)
        blocked, warnings = reconciler._check_task_coverage({"src/uncovered.py"}, set())
        assert len(blocked) == 0
        assert len(warnings) == 0

    def test_new_task_no_warning(self, project):
        """A new task (not in HEAD) is treated as modified, so no warning."""
        _init_git_repo(project)

        # Stage claims referencing TASK-NEW
        claims = [{"claim_id": "C-0001", "related_task": "TASK-NEW", "code_refs": ["src/foo.py"]}]
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        claims_path.parent.mkdir(parents=True, exist_ok=True)
        claims_path.write_text(json.dumps(claims), encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        # Stage task_list with TASK-NEW (does not exist in HEAD)
        task_list = {"tasks": [{"task_id": "TASK-NEW", "title": "New Task"}]}
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
        subprocess.run(["git", "add", "docs/task_list.json"], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)
        blocked, warnings = reconciler._check_task_coverage({"src/foo.py"}, {"src/foo.py"})
        assert len(blocked) == 0
        assert len(warnings) == 0

    def test_code_ref_with_line_range(self, project):
        """code_refs with #L1-L10 suffix should be stripped for matching."""
        _init_git_repo(project)

        # Stage claims with line range
        claims = [{"claim_id": "C-001", "related_task": "TASK-001", "code_refs": ["src/foo.py#L1-L10"]}]
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        claims_path.parent.mkdir(parents=True, exist_ok=True)
        claims_path.write_text(json.dumps(claims), encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        # Stage task_list with TASK-001 (modified)
        task_list = {"tasks": [{"task_id": "TASK-001", "title": "Modified"}]}
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
        subprocess.run(["git", "add", "docs/task_list.json"], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)
        # src/foo.py should match despite line range in claim
        blocked, warnings = reconciler._check_task_coverage({"src/foo.py"}, {"src/foo.py"})
        assert len(blocked) == 0
        assert len(warnings) == 0

    def test_no_task_list_file_blocks(self, project):
        """When task_list.json doesn't exist, tasks are treated as missing -> BLOCKED."""
        _init_git_repo(project)

        # Stage claims referencing TASK-001
        claims = [{"claim_id": "C-0001", "related_task": "TASK-001", "code_refs": ["src/foo.py"]}]
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        claims_path.parent.mkdir(parents=True, exist_ok=True)
        claims_path.write_text(json.dumps(claims), encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        # No task_list.json staged
        reconciler = GhostCodeReconciler(project)
        blocked, warnings = reconciler._check_task_coverage({"src/foo.py"}, {"src/foo.py"})
        assert len(blocked) == 1
        assert "TASK-001" in blocked[0]

    def test_reconcile_blocks_on_task_coverage_failure(self, project):
        """reconcile() returns False when _check_task_coverage returns BLOCKED.

        The ghost code check and _check_task_coverage read from different git
        states (index vs HEAD), so we must commit the claims file first, then
        modify it to reference a missing task. The ghost code check sees the
        staged (modified) claims and passes; _check_task_coverage sees the
        staged claims (via HEAD comparison) and finds the missing task.
        """
        _init_git_repo(project)

        # Commit initial claims referencing TASK-EXISTING (so HEAD has claims)
        claims_old = [{"claim_id": "C-0001", "related_task": "TASK-EXISTING", "code_refs": ["src/foo.py"]}]
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        claims_path.write_text(json.dumps(claims_old), encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        # Commit code file
        (project / "src" / "foo.py").write_text("print('hello')", encoding="utf-8")
        subprocess.run(["git", "add", "src/foo.py"], cwd=project, capture_output=True, check=True)

        task_list = {"tasks": [{"task_id": "TASK-EXISTING", "title": "Existing"}]}
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
        subprocess.run(["git", "add", "docs/task_list.json"], cwd=project, capture_output=True, check=True)

        subprocess.run(["git", "commit", "-m", "initial claims, tasks, and code"], cwd=project, capture_output=True, check=True)

        # Now modify claims to reference TASK-MISSING and stage
        claims_new = [{"claim_id": "C-0001", "related_task": "TASK-MISSING", "code_refs": ["src/foo.py"]}]
        claims_path.write_text(json.dumps(claims_new), encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        # Stage task_list WITHOUT TASK-MISSING
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
        subprocess.run(["git", "add", "docs/task_list.json"], cwd=project, capture_output=True, check=True)

        # Modify and stage the code file so ghost code check sees it as active
        (project / "src" / "foo.py").write_text("print('modified')", encoding="utf-8")
        subprocess.run(["git", "add", "src/foo.py"], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)
        ok, msg = reconciler.reconcile()
        assert ok is False
        assert "TASK-MISSING" in msg

    def test_reconcile_warns_on_unchanged_task(self, project):
        """reconcile() returns True with warning when task is not modified.

        The ghost code check reads claims from the index, while _check_task_coverage
        reads from HEAD. We commit claims+tasks first, then stage a modified claims
        file (adding a second claim for the same code file) to make the ghost code
        check pass. The coverage check then validates all claims' tasks.
        """
        _init_git_repo(project)

        # Commit initial claims referencing TASK-001
        claims_old = [{"claim_id": "C-0001", "related_task": "TASK-001", "code_refs": ["src/foo.py"]}]
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        claims_path.write_text(json.dumps(claims_old), encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        # Commit code file
        (project / "src" / "foo.py").write_text("print('hello')", encoding="utf-8")
        subprocess.run(["git", "add", "src/foo.py"], cwd=project, capture_output=True, check=True)

        # Commit task_list with TASK-001
        task_list = {"tasks": [{"task_id": "TASK-001", "title": "Original"}]}
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
        subprocess.run(["git", "add", "docs/task_list.json"], cwd=project, capture_output=True, check=True)

        subprocess.run(["git", "commit", "-m", "initial state"], cwd=project, capture_output=True, check=True)

        # Stage modified claims (add a second claim for the same code file)
        claims_new = [
            {"claim_id": "C-0001", "related_task": "TASK-001", "code_refs": ["src/foo.py"]},
            {"claim_id": "C-0002", "related_task": "TASK-001", "code_refs": ["src/foo.py"]},
        ]
        claims_path.write_text(json.dumps(claims_new), encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        # Stage task_list WITHOUT modifying TASK-001 (same content as HEAD)
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
        subprocess.run(["git", "add", "docs/task_list.json"], cwd=project, capture_output=True, check=True)

        # Modify and stage the code file so ghost code check sees it as active
        (project / "src" / "foo.py").write_text("print('modified')", encoding="utf-8")
        subprocess.run(["git", "add", "src/foo.py"], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)
        ok, msg = reconciler.reconcile()
        assert ok is True
        assert "TASK-001" in msg
        assert "未在本次提交中修改" in msg


# ------------------------------------------------------------------
# EVO-TASK-011b: Forward AC freshness check tests
# ------------------------------------------------------------------

class TestACFreshnessCheck:
    """Tests for _check_ac_freshness: new tasks referencing ACs not in staged PRD."""

    def test_new_task_with_stale_ac_warns(self, project):
        """New task referencing an AC not in staged PRD -> WARNING."""
        _init_git_repo(project)

        # Stage task_list with a new task referencing AC-VT-999-01
        task_list = {
            "tasks": [
                {"task_id": "TASK-001", "title": "T1", "related_acceptance_criteria": ["AC-VT-999-01"]}
            ]
        }
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
        subprocess.run(["git", "add", "docs/task_list.json"], cwd=project, capture_output=True, check=True)

        # Stage PRD WITHOUT AC-VT-999-01
        prd = "# PRD\n### REQ-VT-001\n##### AC-VT-001-01: Basic\n"
        (project / "docs" / "prd.md").write_text(prd, encoding="utf-8")
        subprocess.run(["git", "add", "docs/prd.md"], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)
        warnings = reconciler._check_ac_freshness()
        assert len(warnings) == 1
        assert "TASK-001" in warnings[0]
        assert "AC-VT-999-01" in warnings[0]

    def test_new_task_with_fresh_ac_no_warning(self, project):
        """New task referencing an AC present in staged PRD -> no warning."""
        _init_git_repo(project)

        # Stage task_list with a new task referencing AC-VT-001-01
        task_list = {
            "tasks": [
                {"task_id": "TASK-001", "title": "T1", "related_acceptance_criteria": ["AC-VT-001-01"]}
            ]
        }
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
        subprocess.run(["git", "add", "docs/task_list.json"], cwd=project, capture_output=True, check=True)

        # Stage PRD WITH AC-VT-001-01
        prd = "# PRD\n### REQ-VT-001\n##### AC-VT-001-01: Basic\n"
        (project / "docs" / "prd.md").write_text(prd, encoding="utf-8")
        subprocess.run(["git", "add", "docs/prd.md"], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)
        warnings = reconciler._check_ac_freshness()
        assert len(warnings) == 0

    def test_no_new_tasks_no_warning(self, project):
        """When all tasks already exist in HEAD, no warnings."""
        _init_git_repo(project)

        # Commit task_list
        task_list = {"tasks": [{"task_id": "TASK-001", "title": "T1", "related_acceptance_criteria": ["AC-VT-999-01"]}]}
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
        subprocess.run(["git", "add", "docs/task_list.json"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "add tasks"], cwd=project, capture_output=True, check=True)

        # Stage same task_list (no new tasks)
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
        subprocess.run(["git", "add", "docs/task_list.json"], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)
        warnings = reconciler._check_ac_freshness()
        assert len(warnings) == 0

    def test_prd_not_staged_warns(self, project):
        """When PRD is not staged but new tasks reference ACs -> WARNING."""
        _init_git_repo(project)

        # Stage task_list with a new task referencing AC-VT-001-01
        task_list = {
            "tasks": [
                {"task_id": "TASK-001", "title": "T1", "related_acceptance_criteria": ["AC-VT-001-01"]}
            ]
        }
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
        subprocess.run(["git", "add", "docs/task_list.json"], cwd=project, capture_output=True, check=True)

        # PRD exists but NOT staged
        (project / "docs" / "prd.md").write_text("# PRD\n", encoding="utf-8")

        reconciler = GhostCodeReconciler(project)
        warnings = reconciler._check_ac_freshness()
        assert len(warnings) == 1
        assert "未更新 PRD" in warnings[0]

    def test_task_without_ac_no_warning(self, project):
        """New task with empty related_acceptance_criteria -> no warning."""
        _init_git_repo(project)

        task_list = {
            "tasks": [
                {"task_id": "TASK-001", "title": "T1", "related_acceptance_criteria": []}
            ]
        }
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
        subprocess.run(["git", "add", "docs/task_list.json"], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)
        warnings = reconciler._check_ac_freshness()
        assert len(warnings) == 0

    def test_no_task_list_no_warning(self, project):
        """When task_list.json doesn't exist, no warnings."""
        _init_git_repo(project)

        reconciler = GhostCodeReconciler(project)
        warnings = reconciler._check_ac_freshness()
        assert len(warnings) == 0

    def test_reconcile_appends_ac_warnings(self, project):
        """reconcile() appends AC freshness warnings to the result message."""
        _init_git_repo(project)

        # Stage claims that pass ghost code check
        claims = [{"claim_id": "C-0001", "related_task": "TASK-001", "code_refs": ["src/foo.py"]}]
        claims_path = project / ".vibetracing" / "claims" / "current.json"
        claims_path.parent.mkdir(parents=True, exist_ok=True)
        claims_path.write_text(json.dumps(claims), encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        # Stage task_list with new TASK-001 referencing AC-VT-999-01
        task_list = {
            "tasks": [
                {"task_id": "TASK-001", "title": "T1", "related_acceptance_criteria": ["AC-VT-999-01"]}
            ]
        }
        (project / "docs" / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
        subprocess.run(["git", "add", "docs/task_list.json"], cwd=project, capture_output=True, check=True)

        # Stage PRD WITHOUT AC-VT-999-01
        prd = "# PRD\n### REQ-VT-001\n##### AC-VT-001-01: Basic\n"
        (project / "docs" / "prd.md").write_text(prd, encoding="utf-8")
        subprocess.run(["git", "add", "docs/prd.md"], cwd=project, capture_output=True, check=True)

        # Stage the code file
        (project / "src" / "foo.py").write_text("print('hello')", encoding="utf-8")
        subprocess.run(["git", "add", "src/foo.py"], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)
        # Mock _get_staged_files to only report business code files (not PRD/docs)
        # so the ghost code check passes, while PRD stays staged for AC freshness
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}):
            ok, msg = reconciler.reconcile()
        assert ok is True
        assert "AC-VT-999-01" in msg
        assert "AC 新鲜度提醒" in msg
