"""TaskSessionManager 单元测试。

覆盖 docs/design/phase_channel_separation.md §3.3.2 + TASK-VT-192 DOD：
    - schema 读写、文件不存在时的加载行为
    - OPEN → IN_PROGRESS → CLOSED 状态机
    - CLOSED task immutability
    - find_closed_references 非空 / 空
    - issue_counts 累加、复合 key、related_task_id 归属（sorted-first 回退）
    - phase_id / delivery 写入
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vibe_tracing.domain.gate.types import (
    DetectedIssue,
    IssueSignal,
    OutputState,
    Severity,
)
from vibe_tracing.domain.task.session import (
    SCHEMA_VERSION,
    AcceptanceSummary,
    TaskSession,
    TaskSessionManager,
)


# ---------------------------------------------------------------------- #
# helpers
# ---------------------------------------------------------------------- #
def _signal(
    issue_id: str = "no_claim:AC-1",
    task_id: str = "TASK-VT-190",
    severity: Severity = Severity.BLOCK,
    observed: bool = True,
    activated: bool = True,
    resolved: bool = False,
) -> IssueSignal:
    return IssueSignal(
        observed=observed,
        activated=activated,
        resolved=resolved,
        accepted=False,
        severity=severity,
        issue_id=issue_id,
        task_id=task_id,
        gap_targets=["AC-1"],
    )


def _issue(
    issue_id: str = "no_claim:AC-1",
    issue_type: str = "no_claim",
    severity: Severity = Severity.BLOCK,
    item_id: str = "AC-1",
    related_task_id: str = "",
) -> DetectedIssue:
    return DetectedIssue(
        issue_id=issue_id,
        issue_type=issue_type,
        severity=severity,
        reason="test reason",
        related_task_id=related_task_id,
        gap_targets=["AC-1"],
        item_id=item_id,
    )


def _mgr(project_root: Path, fixed_time: str = "2026-07-04T10:00:00Z") -> TaskSessionManager:
    return TaskSessionManager(project_root, clock=lambda: fixed_time)


def _sessions_file(project_root: Path) -> Path:
    return project_root / ".vibetracing" / "task_sessions.json"


# ---------------------------------------------------------------------- #
# DOD-VT-192-06: 文件不存在时加载为空
# ---------------------------------------------------------------------- #
def test_load_when_file_missing(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    assert mgr.sessions == {}


def test_load_when_file_corrupt(tmp_path: Path) -> None:
    target = _sessions_file(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text("{not valid json", encoding="utf-8")

    # 确保 OperationalLogger 已初始化，并捕获其 warning 调用
    from unittest.mock import patch, MagicMock
    from vibe_tracing.infra.logging.logger import OperationalLogger

    OperationalLogger.get_or_init(run_id="test", project_root=tmp_path)
    mock_warning = MagicMock()
    with patch.object(
        OperationalLogger.get(), "warning", mock_warning
    ):
        mgr = _mgr(tmp_path)
    assert mgr.sessions == {}
    assert mock_warning.called
    event = mock_warning.call_args[0][0]
    assert event == "task_sessions_parse_failed"


# ---------------------------------------------------------------------- #
# DOD-VT-192-01/02: schema 完整 + OPEN → IN_PROGRESS
# ---------------------------------------------------------------------- #
def test_create_session_on_first_seen(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path, fixed_time="2026-07-04T08:00:00Z")
    mgr.update_sessions(
        current_commit_task_set={"TASK-VT-190"},
        states_and_signals=[],
        gate_decision="blocked",
        task_name_lookup={"TASK-VT-190": "task title"},
        phase_id_lookup={"TASK-VT-190": "PHASE-VT-016"},
        model="claude-opus-4-8",
    )

    session = mgr.get_session("TASK-VT-190")
    assert session is not None
    assert session.task_id == "TASK-VT-190"
    assert session.phase_id == "PHASE-VT-016"
    assert session.status == "IN_PROGRESS"
    assert session.first_seen == "2026-07-04T08:00:00Z"
    assert session.closed_at == ""
    assert session.iterations == 1
    assert session.issue_counts == {}
    assert session.model == "claude-opus-4-8"
    assert session.acceptance_summary is None


def test_save_creates_file_on_first_update(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    assert not _sessions_file(tmp_path).exists()
    mgr.update_sessions(
        current_commit_task_set={"TASK-VT-190"},
        states_and_signals=[],
        gate_decision="blocked",
        task_name_lookup={},
        phase_id_lookup={},
        model="unknown",
    )
    assert _sessions_file(tmp_path).exists()


def test_schema_version_persisted(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    mgr.update_sessions({"TASK-VT-190"}, [], "blocked", {}, {}, "unknown")
    import json
    raw = json.loads(_sessions_file(tmp_path).read_text(encoding="utf-8"))
    assert raw["schema_version"] == SCHEMA_VERSION


# ---------------------------------------------------------------------- #
# DOD-VT-192-02/07: IN_PROGRESS → CLOSED（gate=PASS）+ delivery + closed_at
# ---------------------------------------------------------------------- #
def test_close_session_on_pass(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path, fixed_time="2026-07-04T10:30:00Z")
    mgr.update_sessions({"TASK-VT-190"}, [], "blocked", {}, {"TASK-VT-190": "PHASE-VT-016"}, "claude-opus-4-8")
    mgr.update_sessions(
        {"TASK-VT-190"}, [], "pass",
        task_name_lookup={"TASK-VT-190": "unified action pipeline"},
        phase_id_lookup={"TASK-VT-190": "PHASE-VT-016"},
        model="claude-opus-4-8",
    )

    session = mgr.get_session("TASK-VT-190")
    assert session is not None
    assert session.status == "CLOSED"
    assert session.closed_at == "2026-07-04T10:30:00Z"
    assert session.iterations == 2
    assert session.acceptance_summary is not None
    assert session.acceptance_summary.delivery == "unified action pipeline"
    assert session.acceptance_summary.recommendation == "accept"


def test_no_close_when_task_not_in_commit_set(tmp_path: Path) -> None:
    """gate=PASS 但 task 不在 current_commit_task_set 中 → 不 CLOSED（仍 IN_PROGRESS）"""
    mgr = _mgr(tmp_path)
    mgr.update_sessions({"TASK-VT-190"}, [], "blocked", {}, {"TASK-VT-190": "PHASE-VT-016"}, "m")
    # gate=PASS，但 current_commit_task_set 是另一个 task（不在 set 中的 TASK-VT-190 不应被关闭）
    mgr.update_sessions({"TASK-VT-191"}, [], "pass", {}, {"TASK-VT-191": "PHASE-VT-016"}, "m")

    s190 = mgr.get_session("TASK-VT-190")
    s191 = mgr.get_session("TASK-VT-191")
    assert s190 is not None and s190.status == "IN_PROGRESS"
    assert s191 is not None and s191.status == "CLOSED"


# ---------------------------------------------------------------------- #
# DOD-VT-192-04: immutability
# ---------------------------------------------------------------------- #
def test_closed_session_is_immutable(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path, fixed_time="2026-07-04T10:00:00Z")
    mgr.update_sessions(
        {"TASK-VT-190"},
        [
            (OutputState.CURRENT_BLOCK, _signal(severity=Severity.BLOCK), _issue(severity=Severity.BLOCK)),
        ],
        "pass",
        task_name_lookup={"TASK-VT-190": "original delivery"},
        phase_id_lookup={"TASK-VT-190": "PHASE-VT-016"},
        model="claude-opus-4-8",
    )

    snapshot = mgr.get_session("TASK-VT-190")
    assert snapshot is not None
    original_iterations = snapshot.iterations
    original_issue_counts = dict(snapshot.issue_counts)
    original_delivery = snapshot.acceptance_summary.delivery if snapshot.acceptance_summary else ""

    # 第二次调用：CLOSED 后应被跳过
    mgr.update_sessions(
        {"TASK-VT-190"},
        [
            (OutputState.CURRENT_BLOCK, _signal(severity=Severity.BLOCK), _issue(severity=Severity.BLOCK)),
            (OutputState.CURRENT_BLOCK, _signal(severity=Severity.BLOCK, issue_id="x:2"), _issue(severity=Severity.BLOCK)),
        ],
        "pass",
        task_name_lookup={"TASK-VT-190": "new delivery (must be ignored)"},
        phase_id_lookup={"TASK-VT-190": "PHASE-VT-NEW"},
        model="new-model",
    )

    updated = mgr.get_session("TASK-VT-190")
    assert updated is not None
    assert updated.iterations == original_iterations
    assert updated.issue_counts == original_issue_counts
    assert updated.acceptance_summary is not None
    assert updated.acceptance_summary.delivery == original_delivery
    assert updated.phase_id == "PHASE-VT-016"  # 不变
    assert updated.model == "claude-opus-4-8"  # 不变


# ---------------------------------------------------------------------- #
# DOD-VT-192-03: find_closed_references
# ---------------------------------------------------------------------- #
def test_find_closed_references_empty(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    assert mgr.find_closed_references({"TASK-VT-190"}) == []


def test_find_closed_references_nonempty(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    mgr.update_sessions({"TASK-VT-190", "TASK-VT-191"}, [], "pass", {}, {}, "m")

    refs = mgr.find_closed_references({"TASK-VT-190", "TASK-VT-192"})
    assert refs == ["TASK-VT-190"]


def test_find_closed_references_sorted_output(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    mgr.update_sessions({"TASK-VT-200", "TASK-VT-190", "TASK-VT-195"}, [], "pass", {}, {}, "m")
    refs = mgr.find_closed_references({"TASK-VT-200", "TASK-VT-190", "TASK-VT-195"})
    assert refs == ["TASK-VT-190", "TASK-VT-195", "TASK-VT-200"]


def test_is_closed_helper(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    assert mgr.is_closed("TASK-VT-190") is False
    mgr.update_sessions({"TASK-VT-190"}, [], "pass", {}, {}, "m")
    assert mgr.is_closed("TASK-VT-190") is True


# ---------------------------------------------------------------------- #
# DOD-VT-192-05: issue_counts 累加 + 复合 key
# ---------------------------------------------------------------------- #
def test_issue_counts_accumulate_per_task(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    sigs = [
        (OutputState.CURRENT_BLOCK, _signal(severity=Severity.BLOCK, task_id="TASK-VT-190"), _issue(severity=Severity.BLOCK)),
        (OutputState.CURRENT_BLOCK, _signal(severity=Severity.BLOCK, task_id="TASK-VT-190", issue_id="no_claim:AC-2"), _issue(severity=Severity.BLOCK)),
        (OutputState.CURRENT_WARNING, _signal(severity=Severity.WARNING, task_id="TASK-VT-190", issue_id="substandard:coverage"), _issue(issue_type="substandard", severity=Severity.WARNING, item_id="coverage")),
    ]
    mgr.update_sessions(
        {"TASK-VT-190"}, sigs, "blocked", {}, {"TASK-VT-190": "PHASE-VT-016"}, "m",
    )

    session = mgr.get_session("TASK-VT-190")
    assert session is not None
    assert session.issue_counts["no_claim"]["BLOCK"] == 2
    assert session.issue_counts["substandard:coverage"]["WARNING"] == 1


def test_issue_counts_arch_compliance_key(tmp_path: Path) -> None:
    """chain_broken / substandard / chain_misaligned → issue_type:item_id 复合 key"""
    mgr = _mgr(tmp_path)
    sigs = [
        (OutputState.CURRENT_BLOCK, _signal(task_id="TASK-VT-190", issue_id="chain_broken:GATE-VT-006"),
         _issue(issue_type="chain_broken", item_id="GATE-VT-006")),
    ]
    mgr.update_sessions({"TASK-VT-190"}, sigs, "blocked", {}, {}, "m")

    session = mgr.get_session("TASK-VT-190")
    assert session is not None
    assert "chain_broken:GATE-VT-006" in session.issue_counts
    assert session.issue_counts["chain_broken:GATE-VT-006"]["BLOCK"] == 1


def test_issue_counts_accumulate_across_iterations(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    sig = [(OutputState.CURRENT_BLOCK, _signal(severity=Severity.BLOCK, task_id="TASK-VT-190"), _issue(severity=Severity.BLOCK))]
    mgr.update_sessions({"TASK-VT-190"}, sig, "blocked", {}, {}, "m")
    mgr.update_sessions({"TASK-VT-190"}, sig, "blocked", {}, {}, "m")
    mgr.update_sessions({"TASK-VT-190"}, sig, "blocked", {}, {}, "m")

    session = mgr.get_session("TASK-VT-190")
    assert session is not None
    assert session.issue_counts["no_claim"]["BLOCK"] == 3
    assert session.iterations == 3


def test_issue_counts_related_task_id_fallback_to_first_sorted(tmp_path: Path) -> None:
    """signal.task_id 为空或不在 set 中时，归入 sorted(set) 首个 task"""
    mgr = _mgr(tmp_path)
    # 空 task_id
    sigs_empty = [
        (OutputState.CURRENT_BLOCK, _signal(task_id="", severity=Severity.BLOCK), _issue(severity=Severity.BLOCK)),
    ]
    mgr.update_sessions({"TASK-VT-195", "TASK-VT-190"}, sigs_empty, "blocked", {}, {}, "m")
    s190 = mgr.get_session("TASK-VT-190")
    s195 = mgr.get_session("TASK-VT-195")
    assert s190 is not None and s190.issue_counts.get("no_claim", {}).get("BLOCK", 0) == 1
    assert s195 is not None and s195.issue_counts == {}

    # task_id 不在 set 中
    mgr2 = _mgr(tmp_path / "sub2")
    sigs_other = [
        (OutputState.CURRENT_BLOCK, _signal(task_id="TASK-VT-999", severity=Severity.BLOCK), _issue(severity=Severity.BLOCK)),
    ]
    mgr2.update_sessions({"TASK-VT-195", "TASK-VT-190"}, sigs_other, "blocked", {}, {}, "m")
    s190 = mgr2.get_session("TASK-VT-190")
    s195 = mgr2.get_session("TASK-VT-195")
    assert s190 is not None and s190.issue_counts.get("no_claim", {}).get("BLOCK", 0) == 1
    assert s195 is not None and s195.issue_counts == {}


# ---------------------------------------------------------------------- #
# DOD-VT-192-07: phase_id 写入规则
# ---------------------------------------------------------------------- #
def test_phase_id_written_on_creation_not_updated(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    mgr.update_sessions({"TASK-VT-190"}, [], "blocked", {}, {"TASK-VT-190": "PHASE-VT-016"}, "m")
    # 第二次用不同的 phase_id_lookup，不应更新
    mgr.update_sessions({"TASK-VT-190"}, [], "blocked", {}, {"TASK-VT-190": "PHASE-VT-NEW"}, "m")

    session = mgr.get_session("TASK-VT-190")
    assert session is not None
    assert session.phase_id == "PHASE-VT-016"


# ---------------------------------------------------------------------- #
# DOD-VT-192-08: 持久化 round-trip
# ---------------------------------------------------------------------- #
def test_persistence_roundtrip(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path, fixed_time="2026-07-04T10:00:00Z")
    mgr.update_sessions(
        {"TASK-VT-190"},
        [(OutputState.CURRENT_BLOCK, _signal(severity=Severity.BLOCK, task_id="TASK-VT-190"), _issue(severity=Severity.BLOCK))],
        "pass",
        task_name_lookup={"TASK-VT-190": "delivery text"},
        phase_id_lookup={"TASK-VT-190": "PHASE-VT-016"},
        model="claude-opus-4-8",
    )

    mgr2 = TaskSessionManager(tmp_path)
    session = mgr2.get_session("TASK-VT-190")
    assert session is not None
    assert session.status == "CLOSED"
    assert session.closed_at == "2026-07-04T10:00:00Z"
    assert session.iterations == 1
    assert session.issue_counts["no_claim"]["BLOCK"] == 1
    assert session.acceptance_summary is not None
    assert session.acceptance_summary.delivery == "delivery text"


def test_empty_commit_set_is_noop(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    mgr.update_sessions(set(), [], "pass", {}, {}, "m")
    assert mgr.sessions == {}
    assert not _sessions_file(tmp_path).exists()
