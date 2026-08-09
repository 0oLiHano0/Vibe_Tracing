"""_evaluate_and_output 4 步编排 + --task-status + config.model 读取 — 单元测试。

覆盖 docs/design/phase_channel_separation.md §3.2.1 + TASK-VT-194 DOD：
    - closed task 预检查 → exit 3（短路）
    - gate=PASS 时 session CLOSED + acceptance_summary 生成
    - gate=BLOCKED 时 session 保持 IN_PROGRESS
    - _read_config_model 缺失 / 损坏 / 正常
    - _print_task_status 存在 / 不存在
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from vibe_tracing.domain.gate.types import (
    DetectedIssue,
    IssueSignal,
    OutputState,
    Severity,
)
from vibe_tracing.domain.task.session import TaskSessionManager
from vibe_tracing.cli.analyze.pipeline import (
    _evaluate_and_output,
    _print_task_status,
    _read_config_model,
)


# ---------------------------------------------------------------------- #
# helpers
# ---------------------------------------------------------------------- #
def _write_config(project_root: Path, data: dict) -> None:
    path = project_root / ".vibetracing" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _ctx_stub():
    """最小可用的 UnifiedContext stub（manifest + 几个字段）。"""
    class _Manifest:
        has_required_errors = False
        inputs_used = []
    class _Ctx:
        manifest = _Manifest()
        human_decisions = {"version": "1.0", "decisions": []}
        claims_list = []
        prd = None
        constraints = None
        task_result = None
        config = {}
        config_prefix = "VT"
        governance_whitelist = set()
        governance_boundary = None
    return _Ctx()


# ---------------------------------------------------------------------- #
# DOD-VT-194-01/02: closed task 预检查 → exit 3
# ---------------------------------------------------------------------- #
def test_closed_task_precheck_returns_exit_3(tmp_path: Path) -> None:
    mgr = TaskSessionManager(tmp_path, clock=lambda: "2026-07-04T08:00:00Z")
    mgr.update_sessions(
        current_commit_task_set={"TASK-VT-190"},
        states_and_signals=[],
        gate_decision="pass",
        task_name_lookup={"TASK-VT-190": "title"},
        phase_id_lookup={"TASK-VT-190": "PHASE-VT-016"},
        model="unknown",
    )
    assert mgr.is_closed("TASK-VT-190")

    exit_code = _evaluate_and_output(
        ctx=_ctx_stub(),
        merged_gaps=[],
        final_risks=[],
        compliance_res=None,
        output_dir=tmp_path / "output",
        evidence_meta={},
        project_root=tmp_path,
        current_commit_task_set={"TASK-VT-190"},
        session_mgr=mgr,
    )
    assert exit_code == 3


def test_no_closed_task_skips_precheck(tmp_path: Path) -> None:
    """没有 session_mgr 时不执行预检查，走常规 gate 路径。"""
    gate_res = {"gate_decision": "pass", "historical_issues": [], "per_issue_states": []}
    with patch(
        "vibe_tracing.cli.analyze.pipeline._run_gate_evaluation",
        return_value=(gate_res, []),
    ), patch(
        "vibe_tracing.cli.analyze.pipeline._build_report_document",
        return_value={},
    ), patch(
        "vibe_tracing.cli.analyze.pipeline._render_output",
        return_value=None,
    ):
        exit_code = _evaluate_and_output(
            ctx=_ctx_stub(),
            merged_gaps=[],
            final_risks=[],
            compliance_res=None,
            output_dir=tmp_path / "output",
            evidence_meta={},
            project_root=tmp_path,
            current_commit_task_set={"TASK-VT-190"},
        )
    assert exit_code == 0


# ---------------------------------------------------------------------- #
# DOD-VT-194-03/04/05: gate 检测后 session 更新 + PASS 时生成摘要
# ---------------------------------------------------------------------- #
def test_gate_pass_closes_session_and_builds_summaries(tmp_path: Path) -> None:
    mgr = TaskSessionManager(tmp_path, clock=lambda: "2026-07-04T08:00:00Z")
    gate_res = {"gate_decision": "pass", "historical_issues": [], "per_issue_states": []}

    with patch(
        "vibe_tracing.cli.analyze.pipeline._run_gate_evaluation",
        return_value=(gate_res, []),
    ), patch(
        "vibe_tracing.cli.analyze.pipeline._build_report_document",
        return_value={},
    ), patch(
        "vibe_tracing.cli.analyze.pipeline._render_output",
        return_value=None,
    ):
        exit_code = _evaluate_and_output(
            ctx=_ctx_stub(),
            merged_gaps=[],
            final_risks=[],
            compliance_res=None,
            output_dir=tmp_path / "output",
            evidence_meta={},
            project_root=tmp_path,
            current_commit_task_set={"TASK-VT-190"},
            session_mgr=mgr,
            task_name_lookup={"TASK-VT-190": "unified action pipeline"},
            phase_id_lookup={"TASK-VT-190": "PHASE-VT-016"},
            model="claude-opus-4-8",
        )

    assert exit_code == 0
    session = mgr.get_session("TASK-VT-190")
    assert session is not None
    assert session.status == "CLOSED"
    assert session.acceptance_summary is not None
    assert session.acceptance_summary.delivery == "unified action pipeline"


def test_gate_blocked_keeps_session_in_progress(tmp_path: Path) -> None:
    mgr = TaskSessionManager(tmp_path, clock=lambda: "2026-07-04T08:00:00Z")
    gate_res = {"gate_decision": "blocked", "historical_issues": [], "per_issue_states": []}

    with patch(
        "vibe_tracing.cli.analyze.pipeline._run_gate_evaluation",
        return_value=(gate_res, []),
    ), patch(
        "vibe_tracing.cli.analyze.pipeline._build_report_document",
        return_value={},
    ), patch(
        "vibe_tracing.cli.analyze.pipeline._render_output",
        return_value=None,
    ):
        exit_code = _evaluate_and_output(
            ctx=_ctx_stub(),
            merged_gaps=[],
            final_risks=[],
            compliance_res=None,
            output_dir=tmp_path / "output",
            evidence_meta={},
            project_root=tmp_path,
            current_commit_task_set={"TASK-VT-190"},
            session_mgr=mgr,
            task_name_lookup={"TASK-VT-190": "title"},
            phase_id_lookup={"TASK-VT-190": "PHASE-VT-016"},
            model="unknown",
        )

    assert exit_code == 2
    session = mgr.get_session("TASK-VT-190")
    assert session is not None
    assert session.status == "IN_PROGRESS"
    assert session.acceptance_summary is None


def test_gate_pass_without_commit_set_skips_summary(tmp_path: Path) -> None:
    mgr = TaskSessionManager(tmp_path, clock=lambda: "2026-07-04T08:00:00Z")
    gate_res = {"gate_decision": "pass", "historical_issues": [], "per_issue_states": []}

    with patch(
        "vibe_tracing.cli.analyze.pipeline._run_gate_evaluation",
        return_value=(gate_res, []),
    ), patch(
        "vibe_tracing.cli.analyze.pipeline._build_report_document",
        return_value={},
    ), patch(
        "vibe_tracing.cli.analyze.pipeline._render_output",
        return_value=None,
    ):
        exit_code = _evaluate_and_output(
            ctx=_ctx_stub(),
            merged_gaps=[],
            final_risks=[],
            compliance_res=None,
            output_dir=tmp_path / "output",
            evidence_meta={},
            project_root=tmp_path,
            current_commit_task_set=set(),
            session_mgr=mgr,
        )

    assert exit_code == 0
    assert mgr.sessions == {}


# ---------------------------------------------------------------------- #
# DOD-VT-194-07: _read_config_model 降级
# ---------------------------------------------------------------------- #
def test_read_config_model_missing_file(tmp_path: Path) -> None:
    assert _read_config_model(tmp_path) == "unknown"


def test_read_config_model_corrupt_json(tmp_path: Path) -> None:
    (tmp_path / ".vibetracing").mkdir(parents=True)
    (tmp_path / ".vibetracing" / "config.json").write_text("{bad", encoding="utf-8")
    assert _read_config_model(tmp_path) == "unknown"


def test_read_config_model_no_model_field(tmp_path: Path) -> None:
    _write_config(tmp_path, {"schema_version": "1.0.0"})
    assert _read_config_model(tmp_path) == "unknown"


def test_read_config_model_normal(tmp_path: Path) -> None:
    _write_config(tmp_path, {"schema_version": "1.1.0", "model": "claude-opus-4-8"})
    assert _read_config_model(tmp_path) == "claude-opus-4-8"


def test_read_config_model_empty_string(tmp_path: Path) -> None:
    _write_config(tmp_path, {"model": ""})
    assert _read_config_model(tmp_path) == "unknown"


# ---------------------------------------------------------------------- #
# DOD-VT-194-06: --task-status 行为（_print_task_status）
# ---------------------------------------------------------------------- #
def test_print_task_status_session_missing(tmp_path: Path, capsys) -> None:
    rc = _print_task_status(tmp_path, "TASK-VT-190")
    assert rc == 1
    err = capsys.readouterr().err
    assert "不存在" in err


def test_print_task_status_session_present(tmp_path: Path, capsys) -> None:
    mgr = TaskSessionManager(tmp_path, clock=lambda: "2026-07-04T08:00:00Z")
    mgr.update_sessions(
        {"TASK-VT-190"}, [], "pass",
        {"TASK-VT-190": "unified action pipeline"},
        {"TASK-VT-190": "PHASE-VT-016"},
        "claude-opus-4-8",
    )
    rc = _print_task_status(tmp_path, "TASK-VT-190")
    assert rc == 0
    out = capsys.readouterr().out
    assert "TASK-VT-190" in out
    assert "CLOSED" in out
    assert "PHASE-VT-016" in out
    assert "claude-opus-4-8" in out


def test_cli_analyze_task_status_short_circuit(tmp_path: Path, capsys) -> None:
    """从 main._dispatch 入口走 --task-status 短路路径，验证 argparse 到 run_analyze 的完整链路。"""
    from vibe_tracing.cli.main import _dispatch
    import argparse

    mgr = TaskSessionManager(tmp_path, clock=lambda: "2026-07-04T08:00:00Z")
    mgr.update_sessions(
        {"TASK-VT-190"}, [], "pass",
        {"TASK-VT-190": "title"},
        {"TASK-VT-190": "PHASE-VT-016"},
        "claude-opus-4-8",
    )

    args = argparse.Namespace(command="analyze", out=None, task_status="TASK-VT-190")
    rc = _dispatch(args, tmp_path)
    assert rc == 0
    out = capsys.readouterr().out
    assert "TASK-VT-190" in out
    assert "CLOSED" in out


def test_cli_analyze_task_status_unknown_returns_1(tmp_path: Path, capsys) -> None:
    from vibe_tracing.cli.main import _dispatch
    import argparse

    args = argparse.Namespace(command="analyze", out=None, task_status="TASK-VT-999")
    rc = _dispatch(args, tmp_path)
    assert rc == 1
