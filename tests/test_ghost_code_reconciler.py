"""Tests for GhostCodeReconciler warning on malformed agent_claims.json."""

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
    vibetracing_dir.mkdir(parents=True)
    return tmp_path


class TestMalformedClaimsWarning:
    """L7: malformed agent_claims.json must print a warning to stderr."""

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
        claims_path = project / ".vibetracing" / "agent_claims.json"
        claims_path.write_text("{not valid json!!", encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)

        # Mock _get_staged_files so reconcile() exercises the claims path
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}):
            ok, msg = reconciler.reconcile()

        captured = capsys.readouterr()
        assert "agent_claims.json" in captured.err
        assert "格式解析失败" in captured.err

    def test_no_claims_file_does_not_warn(self, project, capsys):
        """When claims file does not exist, no format-warning is printed."""
        # Ensure claims file does NOT exist
        claims_path = project / ".vibetracing" / "agent_claims.json"
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
        claims_path = project / ".vibetracing" / "agent_claims.json"
        claims_path.write_text(json.dumps(claims), encoding="utf-8")

        reconciler = GhostCodeReconciler(project)

        # Mock _get_staged_files and _get_active_claims_code_refs directly
        # to isolate the reconcile gate from git subprocess complexity
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}), \
             patch.object(reconciler, "_get_active_claims_code_refs", return_value={"src/foo.py"}):
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
            ".vibetracing/agent_claims.json",
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
        assert not (project / ".vibetracing" / "agent_claims.json").exists()
        reconciler = GhostCodeReconciler(project)
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}):
            ok, msg = reconciler.reconcile()
        assert ok is False
        assert "幽灵代码" in msg or "ghost" in msg.lower() or "src/foo.py" in msg


class TestClaimsCoverCodeRefs:
    """Claims with matching code_refs should let the gate pass."""

    def test_exact_match_passes(self, project):
        claims = [{"claim_id": "C-0001", "code_refs": ["src/foo.py", "src/bar.py"]}]
        (project / ".vibetracing" / "agent_claims.json").write_text(
            json.dumps(claims), encoding="utf-8"
        )
        reconciler = GhostCodeReconciler(project)
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py", "src/bar.py"}), \
             patch.object(reconciler, "_get_active_claims_code_refs", return_value={"src/foo.py", "src/bar.py"}):
            ok, msg = reconciler.reconcile()
        assert ok is True
        assert msg == ""

    def test_superset_refs_passes(self, project):
        """Claims covering MORE files than staged should still pass."""
        claims = [{"claim_id": "C-0001", "code_refs": ["src/foo.py", "src/bar.py", "src/baz.py"]}]
        (project / ".vibetracing" / "agent_claims.json").write_text(
            json.dumps(claims), encoding="utf-8"
        )
        reconciler = GhostCodeReconciler(project)
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}), \
             patch.object(reconciler, "_get_active_claims_code_refs", return_value={"src/foo.py", "src/bar.py", "src/baz.py"}):
            ok, msg = reconciler.reconcile()
        assert ok is True
        assert msg == ""

    def test_partial_match_blocks(self, project):
        """Only some staged files covered -- uncovered ones are ghost code."""
        claims = [{"claim_id": "C-0001", "code_refs": ["src/foo.py"]}]
        (project / ".vibetracing" / "agent_claims.json").write_text(
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
        (project / ".vibetracing" / "agent_claims.json").write_text(
            json.dumps(claims), encoding="utf-8"
        )
        reconciler = GhostCodeReconciler(project)
        with patch.object(reconciler, "_get_staged_files", return_value={"src/foo.py"}), \
             patch.object(reconciler, "_get_active_claims_code_refs", return_value={"src/foo.py", "src/ghost.py"}):
            ok, msg = reconciler.reconcile()
        assert ok is True
        assert msg == ""


class TestEmptyClaimsArray:
    """Empty claims array means no active refs -- any staged code is ghost."""

    def test_empty_claims_blocks(self, project):
        (project / ".vibetracing" / "agent_claims.json").write_text("[]", encoding="utf-8")
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

    def test_new_claim_in_staged_not_in_head_is_active(self, project):
        """A claim present in the staged file but absent from HEAD is 'new' and active."""
        self._init_git_repo(project)
        # Initial commit with no claims file
        (project / "placeholder.txt").write_text("init")
        subprocess.run(["git", "add", "placeholder.txt"], cwd=project, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=project, capture_output=True, check=True)

        # Now write a new claims file and stage it
        new_claim = {"claim_id": "C-0001", "code_refs": ["src/new.py"]}
        claims_path = project / ".vibetracing" / "agent_claims.json"
        claims_path.write_text(json.dumps([new_claim]), encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)
        refs = reconciler._get_active_claims_code_refs()
        assert "src/new.py" in refs

    def test_identical_claim_in_staged_and_head_is_not_active(self, project):
        """A claim identical in staged and HEAD is NOT active (already committed)."""
        self._init_git_repo(project)
        existing_claim = {"claim_id": "C-0001", "code_refs": ["src/old.py"]}
        claims_path = project / ".vibetracing" / "agent_claims.json"
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
        claims_path = project / ".vibetracing" / "agent_claims.json"
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
        claims_path = project / ".vibetracing" / "agent_claims.json"
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
        claims_path = project / ".vibetracing" / "agent_claims.json"
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
        claims_path = project / ".vibetracing" / "agent_claims.json"
        claims_path.write_text(json.dumps([claim]), encoding="utf-8")
        subprocess.run(["git", "add", str(claims_path)], cwd=project, capture_output=True, check=True)

        reconciler = GhostCodeReconciler(project)
        refs = reconciler._get_active_claims_code_refs()
        assert "src/visible.py" in refs


class TestWhitelistLogic:
    """Verify _is_whitelisted correctly identifies whitelisted paths."""

    def test_exact_whitelist_paths(self, project):
        reconciler = GhostCodeReconciler(project)
        for path in [".vibetracing/agent_claims.json", ".vibetracing/config.json", "docs/task_list.json"]:
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
        claims_path = project / ".vibetracing" / "agent_claims.json"
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
