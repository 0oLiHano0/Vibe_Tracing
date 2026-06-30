"""Compliance data loaders.

I/O operations for loading compliance data from filesystem.
Extracted from domain/compliance/checker.py to maintain
proper layer separation (domain = pure logic, infra = I/O).
"""

import ast
from pathlib import Path
from typing import List, Tuple

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
