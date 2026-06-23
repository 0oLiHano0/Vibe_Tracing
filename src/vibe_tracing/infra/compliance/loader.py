"""Compliance data loaders.

I/O operations for loading compliance data from filesystem.
Extracted from domain/compliance/checker.py to maintain
proper layer separation (domain = pure logic, infra = I/O).
"""

import ast
from pathlib import Path
from typing import List, Optional, Set, Tuple

from vibe_tracing.infra.logging.logger import OperationalLogger


def get_python_imports(file_path: Path) -> List[Tuple[str, int]]:
    """Extract import names and line numbers from a Python file.

    Args:
        file_path: Path to the Python file.

    Returns:
        List of (module_name, line_number) tuples.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except (SyntaxError, OSError) as exc:
        OperationalLogger.get().debug(
            "python_parse_failed",
            f"Could not parse Python file {file_path}",
            exc=exc,
        )
        return []

    imports: List[Tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append((node.module, node.lineno))
    return imports


def find_python_files(src_dir: Path) -> List[Path]:
    """Find all Python files in a directory recursively.

    Args:
        src_dir: Source directory to search.

    Returns:
        List of Python file paths.
    """
    if not src_dir.exists():
        return []
    return list(src_dir.rglob("*.py"))


def find_dashboard_files(project_root: Path) -> List[Path]:
    """Find all dashboard.html files in project.

    Args:
        project_root: Project root directory.

    Returns:
        List of dashboard.html file paths.
    """
    return list(project_root.rglob("dashboard.html"))


def read_dashboard_content(dash_file: Path) -> Optional[str]:
    """Read dashboard HTML content.

    Args:
        dash_file: Path to dashboard.html.

    Returns:
        File content or None on error.
    """
    try:
        return dash_file.read_text(encoding="utf-8")
    except OSError as exc:
        OperationalLogger.get().warning(
            "dashboard_read_failed",
            f"Could not read dashboard file {dash_file}",
            exc=exc,
        )
        return None


def check_file_exists(path: Path) -> bool:
    """Check if a file exists.

    Args:
        path: File path to check.

    Returns:
        True if file exists.
    """
    return path.exists()
