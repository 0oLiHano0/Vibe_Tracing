"""
Git utility functions for Vibe Tracing.

Provides low-level helpers that read file history from Git,
replacing the need for a physical baseline file with Git-based
history tracking.
"""

import subprocess
from pathlib import Path
from typing import Optional

from vibe_tracing.infra.operational_logger import OperationalLogger


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
    except Exception as e:
        OperationalLogger.get().exception("git_utils_error", "Git operation failed: git_show", exc=e)
        return None


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
    except Exception as e:
        OperationalLogger.get().exception("git_utils_error", "Git operation failed: git_has_uncommitted_changes", exc=e)
        return False
