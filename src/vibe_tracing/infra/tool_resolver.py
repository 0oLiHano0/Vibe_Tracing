"""
Unified tool availability detection and command resolution.

Consolidates scattered shutil.which / sys.executable fallback logic
from cli.py and tool_evidence_adapter.py into a single module.
"""

import importlib
import shutil
import subprocess
import sys
from typing import Optional


class ToolResolver:
    """Unified tool availability detection and command resolution."""

    @staticmethod
    def is_available(tool_name: str) -> bool:
        """Check if a tool is available as a binary or Python module."""
        if shutil.which(tool_name):
            return True
        try:
            subprocess.run(
                [sys.executable, "-m", tool_name, "--version"],
                capture_output=True, timeout=10,
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    @staticmethod
    def resolve_command(command_template: str) -> str:
        """Resolve tool commands, falling back to python3 -m for modules.

        Handles semicolon-separated compound commands.
        """
        segments = command_template.split(";")
        resolved = []
        for seg in segments:
            seg = seg.strip()
            if not seg:
                resolved.append(seg)
                continue
            tool_name = seg.split()[0]
            if tool_name and not shutil.which(tool_name):
                seg = f"{sys.executable} -m {seg}"
            resolved.append(seg)
        return " ; ".join(resolved)
