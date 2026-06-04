"""
Git utility functions for Vibe Tracing.

Provides low-level helpers that read file history from Git,
replacing the need for a physical baseline file with Git-based
history tracking.
"""

import subprocess
from pathlib import Path
from typing import Optional


def git_show(commit: str, path: str, cwd: Path) -> Optional[str]:
    """Read file content at a specific commit.

    Args:
        commit: Git commit hash or ref (e.g. ``HEAD~1``, ``abc1234``).
        path:   Relative path to the file inside the repository.
        cwd:    Project root to run git in.

    Returns:
        The file content as a string, or ``None`` if the command fails
        (e.g. file did not exist at that commit).
    """
    try:
        result = subprocess.run(
            ["git", "show", f"{commit}:{path}"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except Exception:
        return None


def git_last_commit_touching(path: str, cwd: Path) -> Optional[str]:
    """Find the last commit hash that modified a file.

    Args:
        path: Relative path to the file inside the repository.
        cwd:  Project root to run git in.

    Returns:
        The full commit hash as a string, or ``None`` if the file has
        no history or the command fails.
    """
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", path],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None
    except Exception:
        return None


def git_file_modified_after(path: str, after_commit: str, cwd: Path) -> bool:
    """Check if a file was modified after a specific commit.

    Args:
        path:        Relative path to the file inside the repository.
        after_commit: Commit hash or ref to compare against.
        cwd:         Project root to run git in.

    Returns:
        ``True`` if any commits touched the file after *after_commit*,
        ``False`` otherwise.
    """
    try:
        result = subprocess.run(
            ["git", "log", f"{after_commit}..HEAD", "--format=%H", "--", path],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return False


def git_has_uncommitted_changes(path: str, cwd: Path) -> bool:
    """Check if a file has uncommitted changes.

    Inspects both the working directory and the staging area.

    Args:
        path: Relative path to the file inside the repository.
        cwd:  Project root to run git in.

    Returns:
        ``True`` if the file has unstaged or staged changes,
        ``False`` otherwise.
    """
    try:
        # Unstaged changes
        result = subprocess.run(
            ["git", "diff", "--name-only", "--", path],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return True

        # Staged changes
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--", path],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return True

        return False
    except Exception:
        return False
