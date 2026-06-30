"""
Unit tests for incremental mode (TASK-VT-096).
"""

import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from vibe_tracing.domain.gate.engine import MergeGateEngine


class TestIncrementalMode:
    """Test incremental_only mode in MergeGateEngine."""

    @patch.dict(os.environ, {"VT_INCREMENTAL_ONLY": "1"})
    def test_environment_variable_enables_incremental(self):
        """Test that VT_INCREMENTAL_ONLY=1 enables incremental mode."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        assert engine.incremental_only is True

    @patch.dict(os.environ, {"VT_SHOW_HISTORICAL_DEBT": "0"})
    def test_environment_variable_disables_show_debt(self):
        """Test that VT_SHOW_HISTORICAL_DEBT=0 disables show historical debt."""
        engine = MergeGateEngine(Path("/dummy/project/root"))

        assert engine.show_historical_debt is False

    def test_config_json_incremental_only(self):
        """Test that config.json gate.incremental_only is respected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".vibetracing" / "config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps({
                "gate": {
                    "incremental_only": True,
                    "show_historical_debt": False,
                }
            }))

            engine = MergeGateEngine(Path(tmpdir))

            assert engine.incremental_only is True
            assert engine.show_historical_debt is False

    def test_priority_parameter_over_env(self):
        """Test that parameter overrides environment variable."""
        with patch.dict(os.environ, {"VT_INCREMENTAL_ONLY": "0"}):
            engine = MergeGateEngine(
                Path("/dummy/project/root"),
                incremental_only=True,
            )

            assert engine.incremental_only is True

    def test_priority_env_over_config(self):
        """Test that environment variable overrides config.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".vibetracing" / "config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps({
                "gate": {
                    "incremental_only": False,
                }
            }))

            with patch.dict(os.environ, {"VT_INCREMENTAL_ONLY": "1"}):
                engine = MergeGateEngine(Path(tmpdir))

                assert engine.incremental_only is True

    def test_print_gate_summary_filters_historical_debt(self, capsys):
        """Test that _print_gate_summary filters historical debt when show_historical_debt is False."""
        from vibe_tracing.cli.analyze.output import _print_gate_summary

        gate_res = {
            "gate_decision": "pass",
            "reasons": [
                "[当前] Ghost code in new_file.py",
                "[预存] Ghost code in old_file.py",
            ],
            "show_historical_debt": False,
        }
        staged_items = {"new_file.py"}

        _print_gate_summary(gate_res, staged_items)
        captured = capsys.readouterr()

        assert "CURRENT ISSUES" in captured.out
        assert "Ghost code in new_file.py" in captured.out
        assert "PRE-EXISTING DEBT" not in captured.out
        assert "Ghost code in old_file.py" not in captured.out

    def test_print_gate_summary_shows_historical_debt(self, capsys):
        """Test that _print_gate_summary shows historical debt when show_historical_debt is True."""
        from vibe_tracing.cli.analyze.output import _print_gate_summary

        gate_res = {
            "gate_decision": "pass",
            "reasons": [
                "[当前] Ghost code in new_file.py",
                "[预存] Ghost code in old_file.py",
            ],
            "show_historical_debt": True,
        }
        staged_items = {"new_file.py"}

        _print_gate_summary(gate_res, staged_items)
        captured = capsys.readouterr()

        assert "CURRENT ISSUES" in captured.out
        assert "Ghost code in new_file.py" in captured.out
        assert "PRE-EXISTING DEBT" in captured.out
        assert "Ghost code in old_file.py" in captured.out
