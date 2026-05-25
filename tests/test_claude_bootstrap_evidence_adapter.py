"""
Tests for ClaudeBootstrapEvidenceAdapter.

Covers:
  AC-VT-009-02 — Self-bootstrap must generate traceable governance outputs.
"""

import json

from vibe_tracing.claude_bootstrap_evidence_adapter import (
    ClaudeBootstrapEvidenceAdapter,
)
from vibe_tracing.core.enums import CoverageStatus


def test_parse_missing_file(tmp_path):
    """covers: AC-VT-009-02"""
    adapter = ClaudeBootstrapEvidenceAdapter(tmp_path)
    candidates = adapter.parse_log_file(tmp_path / "nonexistent.json")
    assert len(candidates) == 0


def test_parse_corrupt_or_text_file(tmp_path):
    """covers: AC-VT-009-02"""
    log_file = tmp_path / "chat_dialogue.txt"
    log_file.write_text(
        "Hello agent, please implement task 23. Sure, doing that now.", encoding="utf-8"
    )

    adapter = ClaudeBootstrapEvidenceAdapter(tmp_path)
    candidates = adapter.parse_log_file(log_file)

    assert len(candidates) == 1
    assert candidates[0].status == CoverageStatus.LOW_CONFIDENCE.value
    assert "Corrupt or unstructured" in candidates[0].details["error"]


def test_parse_unstructured_dialogue_json(tmp_path):
    """covers: AC-VT-009-02"""
    log_file = tmp_path / "dialogue_only.json"
    log_data = {
        "subagent_id": "SUBAGENT-VT-001",
        "task_id": "TASK-VT-023",
        "dialogue": "We discussed the project requirements in natural language only.",
        "actions": [],
        "produced_claims": [],
    }
    log_file.write_text(json.dumps(log_data), encoding="utf-8")

    adapter = ClaudeBootstrapEvidenceAdapter(tmp_path)
    candidates = adapter.parse_log_file(log_file)

    assert len(candidates) == 1
    assert candidates[0].status == CoverageStatus.LOW_CONFIDENCE.value
    assert candidates[0].details["type"] == "unstructured_dialogue"


def test_parse_valid_structured_run(tmp_path):
    """covers: AC-VT-009-02"""
    log_file = tmp_path / "structured_run.json"
    log_data = {
        "runs": [
            {
                "subagent_id": "SUBAGENT-VT-002",
                "task_id": "TASK-VT-025",
                "dialogue": "",
                "actions": [{"skill_id": "SKILL-VT-001", "status": "success"}],
                "produced_claims": [
                    {
                        "claim_id": "CLAIM-VT-025",
                        "claimed_status": "covered",
                        "evidence_refs": ["AC-VT-009-03"],
                    }
                ],
            }
        ]
    }
    log_file.write_text(json.dumps(log_data), encoding="utf-8")

    adapter = ClaudeBootstrapEvidenceAdapter(tmp_path)
    candidates = adapter.parse_log_file(log_file)

    assert len(candidates) == 1
    assert candidates[0].status == CoverageStatus.COVERED.value
    assert candidates[0].covers == ["AC-VT-009-03"]
    assert candidates[0].details["type"] == "structured_subagent_run"
    assert candidates[0].details["actions_count"] == 1


def test_parse_failed_actions_run(tmp_path):
    """covers: AC-VT-009-02"""
    log_file = tmp_path / "failed_run.json"
    log_data = {
        "subagent_id": "SUBAGENT-VT-002",
        "task_id": "TASK-VT-025",
        "actions": [
            {"skill_id": "SKILL-VT-001", "status": "success"},
            {"skill_id": "SKILL-VT-002", "status": "failed"},
        ],
        "produced_claims": [],
    }
    log_file.write_text(json.dumps(log_data), encoding="utf-8")

    adapter = ClaudeBootstrapEvidenceAdapter(tmp_path)
    candidates = adapter.parse_log_file(log_file)

    assert len(candidates) == 1
    assert candidates[0].status == CoverageStatus.PARTIAL.value
    assert candidates[0].details["actions_count"] == 2
