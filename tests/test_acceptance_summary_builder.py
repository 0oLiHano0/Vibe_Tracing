"""AcceptanceSummaryBuilder + BusinessImpactResolver 单元测试。

覆盖 docs/design_channel_separation.md §2.3.2 / §3.2.1 + TASK-VT-193 DOD：
    - build_list 签名与返回结构（每 task 一份 summary dict）
    - recommendation 判定（severe_risks 为空 → accept / 非空 → reject）
    - resolved_block / resolved_warning / remaining_warning 三类计数
    - task 归属（related_task_id 优先；为空回退到 sorted 首个 task）
    - BusinessImpactResolver 双层查找（项目覆写 > field_hints 默认 > 'high' 兜底）
    - business_impacts.json 缺失 / 损坏 / 非法值的降级行为
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vibe_tracing.domain.gate.types import (
    DetectedIssue,
    IssueSignal,
    OutputState,
    Severity,
)
from vibe_tracing.domain.task.acceptance import AcceptanceSummaryBuilder
from vibe_tracing.domain.task.business_impact import BusinessImpactResolver
from vibe_tracing.domain.task.session import AcceptanceSummary, TaskSession


# ---------------------------------------------------------------------- #
# helpers
# ---------------------------------------------------------------------- #
def _issue(
    issue_id: str = "no_claim:TASK-1",
    issue_type: str = "no_claim",
    severity: Severity = Severity.BLOCK,
    item_id: str = "TASK-1",
    related_task_id: str = "TASK-VT-190",
    reason: str = "test reason",
) -> DetectedIssue:
    return DetectedIssue(
        issue_id=issue_id,
        issue_type=issue_type,
        severity=severity,
        reason=reason,
        related_task_id=related_task_id,
        gap_targets=["AC-1"],
        item_id=item_id,
    )


def _signal(
    task_id: str = "TASK-VT-190",
    severity: Severity = Severity.BLOCK,
    issue_id: str = "no_claim:TASK-1",
) -> IssueSignal:
    return IssueSignal(
        observed=True,
        activated=True,
        resolved=False,
        accepted=False,
        severity=severity,
        issue_id=issue_id,
        task_id=task_id,
        gap_targets=["AC-1"],
    )


def _session(
    task_id: str = "TASK-VT-190",
    delivery: str = "task title",
) -> TaskSession:
    return TaskSession(
        task_id=task_id,
        phase_id="PHASE-VT-016",
        status="CLOSED",
        first_seen="2026-07-04T08:00:00Z",
        closed_at="2026-07-04T10:30:00Z",
        iterations=2,
        model="claude-opus-4-8",
        acceptance_summary=AcceptanceSummary(delivery=delivery),
    )


def _triple(state, task_id="TASK-VT-190", severity=Severity.BLOCK,
            issue_type="no_claim", related_task_id="TASK-VT-190",
            item_id="TASK-1", issue_id=None, reason="test reason"):
    if issue_id is None:
        issue_id = f"{issue_type}:{item_id}"
    return (state, _signal(task_id, severity, issue_id),
            _issue(issue_id=issue_id, issue_type=issue_type, severity=severity,
                   item_id=item_id, related_task_id=related_task_id,
                   reason=reason))


# ---------------------------------------------------------------------- #
# DOD-VT-193-01: 签名与返回结构
# ---------------------------------------------------------------------- #
def test_build_list_length_matches_commit_set(tmp_path: Path) -> None:
    sessions = {"TASK-VT-190": _session("TASK-VT-190"), "TASK-VT-191": _session("TASK-VT-191")}
    result = AcceptanceSummaryBuilder.build_list(
        current_commit_task_set={"TASK-VT-190", "TASK-VT-191"},
        sessions=sessions,
        states_and_signals=[],
        project_root=tmp_path,
    )
    assert len(result) == 2
    assert [r["task_id"] for r in result] == ["TASK-VT-190", "TASK-VT-191"]


def test_build_list_empty_commit_set_returns_empty(tmp_path: Path) -> None:
    result = AcceptanceSummaryBuilder.build_list(
        current_commit_task_set=set(),
        sessions={},
        states_and_signals=[_triple(OutputState.RESOLVED)],
        project_root=tmp_path,
    )
    assert result == []


# ---------------------------------------------------------------------- #
# DOD-VT-193-02: summary dict 字段完整
# ---------------------------------------------------------------------- #
def test_summary_dict_fields_complete(tmp_path: Path) -> None:
    sessions = {"TASK-VT-190": _session("TASK-VT-190", delivery="unified action pipeline")}
    triples = [
        _triple(OutputState.RESOLVED, severity=Severity.BLOCK, related_task_id="TASK-VT-190"),
        _triple(OutputState.RESOLVED, severity=Severity.WARNING, related_task_id="TASK-VT-190"),
        _triple(OutputState.CURRENT_WARNING, severity=Severity.WARNING,
                issue_type="substandard", related_task_id="TASK-VT-190",
                item_id="coverage", issue_id="substandard:coverage:TASK-1"),
    ]
    result = AcceptanceSummaryBuilder.build_list(
        current_commit_task_set={"TASK-VT-190"},
        sessions=sessions,
        states_and_signals=triples,
        project_root=tmp_path,
    )
    assert len(result) == 1
    s = result[0]
    assert set(s.keys()) >= {
        "task_id", "recommendation", "delivery",
        "severe_risks", "resolved_block", "resolved_warning", "remaining_warning",
        "iterations",
    }
    assert s["task_id"] == "TASK-VT-190"
    assert s["delivery"] == "unified action pipeline"
    assert s["resolved_block"] == 1
    assert s["resolved_warning"] == 1
    assert s["remaining_warning"] == 1
    assert s["iterations"] == 2


def test_iterations_defaults_to_zero_when_session_missing(tmp_path: Path) -> None:
    """session 字典中不含对应 task 时，iterations 应默认为 0（§2.2 stdout 格式契约）。"""
    result = AcceptanceSummaryBuilder.build_list(
        current_commit_task_set={"TASK-VT-NEW"},
        sessions={},
        states_and_signals=[],
        project_root=tmp_path,
    )
    assert len(result) == 1
    assert result[0]["iterations"] == 0


# ---------------------------------------------------------------------- #
# DOD-VT-193-03: recommendation 判定
# ---------------------------------------------------------------------- #
def test_recommendation_accept_when_no_severe_risks(tmp_path: Path) -> None:
    sessions = {"TASK-VT-190": _session()}
    triples = [
        _triple(OutputState.RESOLVED, severity=Severity.BLOCK, related_task_id="TASK-VT-190"),
        _triple(OutputState.CURRENT_WARNING, severity=Severity.WARNING,
                issue_type="isolated_task", related_task_id="TASK-VT-190",
                item_id="TASK-1"),
    ]
    result = AcceptanceSummaryBuilder.build_list(
        {"TASK-VT-190"}, sessions, triples, project_root=tmp_path,
    )
    assert result[0]["recommendation"] == "accept"
    assert result[0]["severe_risks"] == []


def test_recommendation_reject_when_severe_risks_present(tmp_path: Path) -> None:
    sessions = {"TASK-VT-190": _session()}
    triples = [
        _triple(OutputState.CURRENT_WARNING, severity=Severity.WARNING,
                issue_type="no_claim", related_task_id="TASK-VT-190",
                reason="TASK-001 缺少 Claim 声明"),
    ]
    result = AcceptanceSummaryBuilder.build_list(
        {"TASK-VT-190"}, sessions, triples, project_root=tmp_path,
    )
    assert result[0]["recommendation"] == "reject"
    assert any("TASK-001 缺少 Claim 声明" in r for r in result[0]["severe_risks"])


# ---------------------------------------------------------------------- #
# DOD-VT-193-04: BusinessImpactResolver 优先级
# ---------------------------------------------------------------------- #
def test_resolver_project_override_exact_compound(tmp_path: Path) -> None:
    overrides = {"schema_version": "1.0.0", "overrides": {"task_failed:test_failed": "low"}}
    (tmp_path / ".vibetracing").mkdir(parents=True)
    (tmp_path / ".vibetracing" / "business_impacts.json").write_text(
        json.dumps(overrides), encoding="utf-8",
    )
    resolver = BusinessImpactResolver(tmp_path)
    assert resolver.resolve("task_failed", "test_failed") == "low"


def test_resolver_project_override_fallback_to_issue_type(tmp_path: Path) -> None:
    overrides = {"schema_version": "1.0.0", "overrides": {"substandard": "none"}}
    (tmp_path / ".vibetracing").mkdir(parents=True)
    (tmp_path / ".vibetracing" / "business_impacts.json").write_text(
        json.dumps(overrides), encoding="utf-8",
    )
    resolver = BusinessImpactResolver(tmp_path)
    assert resolver.resolve("substandard", "coverage") == "none"
    assert resolver.resolve("substandard") == "none"


def test_resolver_project_override_beats_field_hints(tmp_path: Path) -> None:
    overrides = {"schema_version": "1.0.0", "overrides": {"no_claim": "low"}}
    (tmp_path / ".vibetracing").mkdir(parents=True)
    (tmp_path / ".vibetracing" / "business_impacts.json").write_text(
        json.dumps(overrides), encoding="utf-8",
    )
    resolver = BusinessImpactResolver(tmp_path)
    # field_hints default for no_claim is 'high', but override wins
    assert resolver.resolve("no_claim") == "low"


def test_resolver_field_hints_default_when_no_override(tmp_path: Path) -> None:
    # No project overrides file
    resolver = BusinessImpactResolver(tmp_path)
    assert resolver.resolve("no_claim") == "high"
    assert resolver.resolve("isolated_task") == "low"
    assert resolver.resolve("substandard") == "low"


def test_resolver_high_fallback_for_unknown_issue_type(tmp_path: Path) -> None:
    resolver = BusinessImpactResolver(tmp_path)
    assert resolver.resolve("never_seen_type") == "high"


def test_resolver_compound_key_priority_over_issue_type(tmp_path: Path) -> None:
    overrides = {
        "schema_version": "1.0.0",
        "overrides": {
            "substandard:coverage": "none",
            "substandard": "high",
        },
    }
    (tmp_path / ".vibetracing").mkdir(parents=True)
    (tmp_path / ".vibetracing" / "business_impacts.json").write_text(
        json.dumps(overrides), encoding="utf-8",
    )
    resolver = BusinessImpactResolver(tmp_path)
    assert resolver.resolve("substandard", "coverage") == "none"
    assert resolver.resolve("substandard", "other_subtype") == "high"


# ---------------------------------------------------------------------- #
# DOD-VT-193-05: business_impacts.json 缺失 / 损坏 / 非法值
# ---------------------------------------------------------------------- #
def test_resolver_missing_file_equals_empty_overrides(tmp_path: Path) -> None:
    resolver = BusinessImpactResolver(tmp_path)
    assert resolver.resolve("no_claim") == "high"  # field_hints default


def test_resolver_corrupt_json_degrades_to_field_hints(tmp_path: Path) -> None:
    (tmp_path / ".vibetracing").mkdir(parents=True)
    (tmp_path / ".vibetracing" / "business_impacts.json").write_text(
        "{not valid json", encoding="utf-8",
    )
    resolver = BusinessImpactResolver(tmp_path)
    assert resolver.resolve("no_claim") == "high"
    assert resolver.resolve("substandard") == "low"


def test_resolver_invalid_impact_value_skipped(tmp_path: Path) -> None:
    overrides = {"schema_version": "1.0.0", "overrides": {"no_claim": "MEDIUM"}}
    (tmp_path / ".vibetracing").mkdir(parents=True)
    (tmp_path / ".vibetracing" / "business_impacts.json").write_text(
        json.dumps(overrides), encoding="utf-8",
    )
    resolver = BusinessImpactResolver(tmp_path)
    assert resolver.resolve("no_claim") == "high"  # override skipped → default


def test_resolver_overrides_not_dict_degrades(tmp_path: Path) -> None:
    (tmp_path / ".vibetracing").mkdir(parents=True)
    (tmp_path / ".vibetracing" / "business_impacts.json").write_text(
        json.dumps({"schema_version": "1.0.0", "overrides": ["not", "a", "dict"]}),
        encoding="utf-8",
    )
    resolver = BusinessImpactResolver(tmp_path)
    assert resolver.resolve("no_claim") == "high"


# ---------------------------------------------------------------------- #
# DOD-VT-193-06: task 归属策略（related_task_id 优先；为空回退 sorted 首个）
# ---------------------------------------------------------------------- #
def test_task_attribution_by_related_task_id(tmp_path: Path) -> None:
    sessions = {"TASK-VT-190": _session("TASK-VT-190"), "TASK-VT-191": _session("TASK-VT-191")}
    triples = [
        _triple(OutputState.RESOLVED, severity=Severity.BLOCK,
                related_task_id="TASK-VT-191", item_id="X1"),
        _triple(OutputState.RESOLVED, severity=Severity.WARNING,
                related_task_id="TASK-VT-190", item_id="X2"),
    ]
    result = AcceptanceSummaryBuilder.build_list(
        {"TASK-VT-190", "TASK-VT-191"}, sessions, triples, project_root=tmp_path,
    )
    by_id = {r["task_id"]: r for r in result}
    assert by_id["TASK-VT-190"]["resolved_warning"] == 1
    assert by_id["TASK-VT-190"]["resolved_block"] == 0
    assert by_id["TASK-VT-191"]["resolved_block"] == 1
    assert by_id["TASK-VT-191"]["resolved_warning"] == 0


def test_task_attribution_empty_related_falls_back_to_first_sorted(tmp_path: Path) -> None:
    sessions = {"TASK-VT-190": _session("TASK-VT-190"), "TASK-VT-191": _session("TASK-VT-191")}
    triples = [
        _triple(OutputState.RESOLVED, severity=Severity.BLOCK,
                related_task_id="", item_id="X1"),
    ]
    result = AcceptanceSummaryBuilder.build_list(
        {"TASK-VT-190", "TASK-VT-191"}, sessions, triples, project_root=tmp_path,
    )
    by_id = {r["task_id"]: r for r in result}
    # sorted-first = TASK-VT-190
    assert by_id["TASK-VT-190"]["resolved_block"] == 1
    assert by_id["TASK-VT-191"]["resolved_block"] == 0


def test_task_attribution_unmatched_related_falls_back(tmp_path: Path) -> None:
    sessions = {"TASK-VT-190": _session("TASK-VT-190")}
    triples = [
        _triple(OutputState.RESOLVED, severity=Severity.BLOCK,
                related_task_id="TASK-VT-999", item_id="X1"),
    ]
    result = AcceptanceSummaryBuilder.build_list(
        {"TASK-VT-190"}, sessions, triples, project_root=tmp_path,
    )
    assert result[0]["resolved_block"] == 1


# ---------------------------------------------------------------------- #
# DOD-VT-193-07: field_hints business_impact 默认标注
# ---------------------------------------------------------------------- #
def test_field_hints_issue_type_impacts_section_present() -> None:
    from vibe_tracing.infra.config.hint_loader import load_hints
    section = load_hints("issue_type_impacts")
    for issue_type in ("no_claim", "chain_broken", "chain_misaligned",
                       "task_failed", "isolated_task", "substandard"):
        entry = section.get(issue_type)
        assert isinstance(entry, dict), f"{issue_type} 缺失"
        assert entry.get("business_impact") in {"high", "low", "none"}


def test_field_hints_json_valid() -> None:
    path = Path("src/vibe_tracing/templates/field_hints.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "issue_type_impacts" in data


# ---------------------------------------------------------------------- #
# 综合：多 task 混合场景
# ---------------------------------------------------------------------- #
def test_multi_task_mixed_states(tmp_path: Path) -> None:
    sessions = {
        "TASK-VT-190": _session("TASK-VT-190", delivery="task A"),
        "TASK-VT-191": _session("TASK-VT-191", delivery="task B"),
    }
    triples = [
        # task A: 1 resolved BLOCK + 1 remaining WARNING (low impact, isolated_task) → accept
        _triple(OutputState.RESOLVED, severity=Severity.BLOCK,
                related_task_id="TASK-VT-190", item_id="A1"),
        _triple(OutputState.CURRENT_WARNING, severity=Severity.WARNING,
                issue_type="isolated_task", related_task_id="TASK-VT-190", item_id="A2"),
        # task B: 1 remaining WARNING (high impact, no_claim) → reject
        _triple(OutputState.CURRENT_WARNING, severity=Severity.WARNING,
                issue_type="no_claim", related_task_id="TASK-VT-191", item_id="B1"),
    ]
    result = AcceptanceSummaryBuilder.build_list(
        {"TASK-VT-190", "TASK-VT-191"}, sessions, triples, project_root=tmp_path,
    )
    by_id = {r["task_id"]: r for r in result}
    assert by_id["TASK-VT-190"]["recommendation"] == "accept"
    assert by_id["TASK-VT-190"]["resolved_block"] == 1
    assert by_id["TASK-VT-190"]["remaining_warning"] == 1
    assert by_id["TASK-VT-191"]["recommendation"] == "reject"
    assert by_id["TASK-VT-191"]["severe_risks"] != []


def test_session_missing_falls_back_to_empty_delivery(tmp_path: Path) -> None:
    result = AcceptanceSummaryBuilder.build_list(
        {"TASK-VT-190"},
        sessions={},
        states_and_signals=[],
        project_root=tmp_path,
    )
    assert result[0]["delivery"] == ""
    assert result[0]["recommendation"] == "accept"
