"""Tests for vibe_tracing.git_utils module.

Covers all four functions with success, failure, and exception paths.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from vibe_tracing.git_utils import (
    git_show,
    git_last_commit_touching,
    git_file_modified_after,
    git_has_uncommitted_changes,
)

CWD = Path("/fake/project")


# ---------------------------------------------------------------------------
# git_show
# ---------------------------------------------------------------------------

class TestGitShow:
    """Tests for git_show()."""

    @patch("vibe_tracing.git_utils.subprocess.run")
    def test_returns_content_on_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="file content\n")
        result = git_show("abc123", "docs/prd.md", CWD)
        assert result == "file content\n"
        mock_run.assert_called_once_with(
            ["git", "show", "abc123:docs/prd.md"],
            cwd=CWD,
            capture_output=True,
            text=True,
        )

    @patch("vibe_tracing.git_utils.subprocess.run")
    def test_returns_none_on_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=128, stdout="")
        result = git_show("abc123", "nonexistent.txt", CWD)
        assert result is None

    @patch("vibe_tracing.git_utils.subprocess.run", side_effect=FileNotFoundError)
    def test_returns_none_on_exception(self, mock_run):
        result = git_show("abc123", "docs/prd.md", CWD)
        assert result is None


# ---------------------------------------------------------------------------
# git_last_commit_touching
# ---------------------------------------------------------------------------

class TestGitLastCommitTouching:
    """Tests for git_last_commit_touching()."""

    @patch("vibe_tracing.git_utils.subprocess.run")
    def test_returns_hash_on_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2\n"
        )
        result = git_last_commit_touching("docs/prd.md", CWD)
        assert result == "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
        mock_run.assert_called_once_with(
            ["git", "log", "-1", "--format=%H", "--", "docs/prd.md"],
            cwd=CWD,
            capture_output=True,
            text=True,
        )

    @patch("vibe_tracing.git_utils.subprocess.run")
    def test_returns_none_when_no_history(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = git_last_commit_touching("brand_new_file.txt", CWD)
        assert result is None

    @patch("vibe_tracing.git_utils.subprocess.run")
    def test_returns_none_on_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=128, stdout="")
        result = git_last_commit_touching("docs/prd.md", CWD)
        assert result is None

    @patch("vibe_tracing.git_utils.subprocess.run", side_effect=OSError)
    def test_returns_none_on_exception(self, mock_run):
        result = git_last_commit_touching("docs/prd.md", CWD)
        assert result is None


# ---------------------------------------------------------------------------
# git_file_modified_after
# ---------------------------------------------------------------------------

class TestGitFileModifiedAfter:
    """Tests for git_file_modified_after()."""

    @patch("vibe_tracing.git_utils.subprocess.run")
    def test_returns_true_when_modified(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="deadbeef12345678deadbeef12345678deadbeef\n"
        )
        result = git_file_modified_after("docs/prd.md", "abc123", CWD)
        assert result is True
        mock_run.assert_called_once_with(
            ["git", "log", "abc123..HEAD", "--format=%H", "--", "docs/prd.md"],
            cwd=CWD,
            capture_output=True,
            text=True,
        )

    @patch("vibe_tracing.git_utils.subprocess.run")
    def test_returns_false_when_not_modified(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = git_file_modified_after("docs/prd.md", "abc123", CWD)
        assert result is False

    @patch("vibe_tracing.git_utils.subprocess.run")
    def test_returns_false_on_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=128, stdout="")
        result = git_file_modified_after("docs/prd.md", "abc123", CWD)
        assert result is False

    @patch("vibe_tracing.git_utils.subprocess.run", side_effect=RuntimeError)
    def test_returns_false_on_exception(self, mock_run):
        result = git_file_modified_after("docs/prd.md", "abc123", CWD)
        assert result is False


# ---------------------------------------------------------------------------
# git_has_uncommitted_changes
# ---------------------------------------------------------------------------

class TestGitHasUncommittedChanges:
    """Tests for git_has_uncommitted_changes()."""

    @patch("vibe_tracing.git_utils.subprocess.run")
    def test_returns_true_on_unstaged_changes(self, mock_run):
        # First call (git diff) finds unstaged changes
        mock_run.return_value = MagicMock(returncode=0, stdout="docs/prd.md\n")
        result = git_has_uncommitted_changes("docs/prd.md", CWD)
        assert result is True

    @patch("vibe_tracing.git_utils.subprocess.run")
    def test_returns_true_on_staged_changes(self, mock_run):
        # First call (unstaged) returns empty, second call (staged) returns file
        unstaged = MagicMock(returncode=0, stdout="")
        staged = MagicMock(returncode=0, stdout="docs/prd.md\n")
        mock_run.side_effect = [unstaged, staged]
        result = git_has_uncommitted_changes("docs/prd.md", CWD)
        assert result is True

    @patch("vibe_tracing.git_utils.subprocess.run")
    def test_returns_false_when_clean(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = git_has_uncommitted_changes("docs/prd.md", CWD)
        assert result is False

    @patch("vibe_tracing.git_utils.subprocess.run", side_effect=PermissionError)
    def test_returns_false_on_exception(self, mock_run):
        result = git_has_uncommitted_changes("docs/prd.md", CWD)
        assert result is False

    @patch("vibe_tracing.git_utils.subprocess.run")
    def test_returns_false_when_diff_fails(self, mock_run):
        # First call (unstaged) returns non-zero
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = git_has_uncommitted_changes("docs/prd.md", CWD)
        assert result is False
