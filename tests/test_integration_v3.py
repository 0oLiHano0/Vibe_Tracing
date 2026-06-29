"""
Integration tests for Vibe Tracing v3 features.

Covers:
- ToolExecutionEngine.execute_from_claims: Language-based file filtering
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vibe_tracing.infra.tools.executor import ToolExecutionEngine


def _make_claim(code_refs=None, test_refs=None):
    """Helper to create a mock Claim with given refs."""
    claim = MagicMock()
    claim.code_refs = code_refs or []
    claim.test_refs = test_refs or []
    return claim


class TestExecuteFromClaimsLanguageFilter:
    """Integration test for execute_from_claims filtering by file extension."""

    @patch("vibe_tracing.infra.tools.executor.ToolResolver.is_available", return_value=True)
    @patch("vibe_tracing.infra.tools.executor.subprocess.run")
    def test_execute_from_claims_filters_by_language(
        self, mock_run: MagicMock, mock_avail: MagicMock, tmp_path: Path
    ) -> None:
        """Only .py files should be executed; .md files should be skipped."""
        py_file = tmp_path / "src" / "module.py"
        py_file.parent.mkdir(parents=True, exist_ok=True)
        py_file.write_text("x = 1\n", encoding="utf-8")

        md_file = tmp_path / "docs" / "readme.md"
        md_file.parent.mkdir(parents=True, exist_ok=True)
        md_file.write_text("# Hello\n", encoding="utf-8")

        mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")

        engine = ToolExecutionEngine(
            language_tool_matrix={
                "python": {
                    "extensions": [".py"],
                    "lint": {
                        "tool": "ruff",
                        "default_command": "ruff check {source_path}",
                        "output_format": "ruff_json",
                        "pass_condition": "violations == 0",
                    },
                }
            },
            language="python",
            validation_tools=["lint"],
            project_root=tmp_path,
        )

        claims = [_make_claim(code_refs=["src/module.py", "docs/readme.md"])]
        result = engine.execute_from_claims(claims, tmp_path)

        # .py file should have been processed (subprocess called once for lint)
        assert mock_run.call_count == 1
        called_cmd = mock_run.call_args[0][0]
        assert "module.py" in called_cmd

        # .md file should not appear in any candidate
        source_paths = [c.source_path for c in result.candidates]
        assert "docs/readme.md" not in source_paths

    @patch("vibe_tracing.infra.tools.executor.ToolResolver.is_available", return_value=True)
    @patch("vibe_tracing.infra.tools.executor.subprocess.run")
    def test_execute_from_claims_skips_all_non_matching(
        self, mock_run: MagicMock, mock_avail: MagicMock, tmp_path: Path
    ) -> None:
        """Only .py files are configured; .json and .md files produce no candidates."""
        engine = ToolExecutionEngine(
            language_tool_matrix={
                "python": {
                    "extensions": [".py"],
                    "lint": {
                        "tool": "ruff",
                        "default_command": "ruff check {source_path}",
                        "output_format": "ruff_json",
                        "pass_condition": "violations == 0",
                    },
                }
            },
            language="python",
            validation_tools=["lint"],
            project_root=tmp_path,
        )

        claims = [_make_claim(code_refs=["docs/notes.md", "config.json"])]
        result = engine.execute_from_claims(claims, tmp_path)
        assert result.skipped
        assert result.skip_reason == "no_code_files"
        mock_run.assert_not_called()
