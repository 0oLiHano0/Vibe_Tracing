"""Phase 1 MVP 端到端集成验证（T198）。

覆盖 docs/design_channel_separation.md §5.2 测试策略 + 一期交付验收：
    1. 完整 4 步编排（closed task 预检 → gate → session 更新 + 摘要 → 报告 + 渲染）
    2. 真实 TaskSessionManager ↔ AcceptanceSummaryBuilder 交互
    3. report_doc 新 key（acceptance_archive / rule_stats_table / governance_metrics / agent_capability_metrics）
    4. stdout 中不含反思提示（Channel 分离落地验证）
    5. 多次 analyze 不修改 CLOSED task 数据（immutability）
    6. Dashboard 模板含 4 个新 Tab 容器
"""

from __future__ import annotations

import io
import json
import re
import sys
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
from vibe_tracing.domain.task.acceptance import AcceptanceSummaryBuilder
from vibe_tracing.domain.governance.metrics import GovernanceMetricsAggregator
from vibe_tracing.domain.capability.metrics import AgentCapabilityMetricsAggregator
from vibe_tracing.cli.analyze.pipeline import _evaluate_and_output


_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF✅⚠️📋]")


def _ctx_stub():
    class _Manifest:
        has_required_errors = False
        inputs_used = []
    class _Prd:
        status = "review"
        requirements = []
    class _Ctx:
        manifest = _Manifest()
        human_decisions = {"version": "1.0", "decisions": []}
        claims_list = []
        prd = _Prd()
        constraints = None
        task_result = None
        config = {}
        config_prefix = "VT"
        governance_whitelist = set()
        governance_boundary = None
    return _Ctx()


def _issue(
    issue_type: str = "no_claim",
    issue_id: str = "no_claim:TASK-VT-190",
    task_id: str = "TASK-VT-190",
    severity: Severity = Severity.BLOCK,
    reason: str = "test reason",
) -> DetectedIssue:
    return DetectedIssue(
        issue_id=issue_id,
        issue_type=issue_type,
        item_id=task_id,
        related_task_id=task_id,
        severity=severity,
        reason=reason,
        gap_targets=[],
    )


def _signal(task_id: str = "TASK-VT-190") -> IssueSignal:
    return IssueSignal(
        issue_id="no_claim:" + task_id,
        task_id=task_id,
        observed=True,
        activated=True,
        resolved=False,
        accepted=False,
        severity=Severity.BLOCK,
        gap_targets=[],
    )


def _triple(
    state: OutputState,
    task_id: str = "TASK-VT-190",
    severity: Severity = Severity.BLOCK,
    issue_type: str = "no_claim",
):
    issue = _issue(
        issue_type=issue_type,
        issue_id=f"{issue_type}:{task_id}",
        task_id=task_id,
        severity=severity,
    )
    signal = _signal(task_id)
    return (state, signal, issue)


# -------------------------------------------------------------------- #
# E2E #1：gate=PASS + current_commit_task_set → stdout 含验收摘要
# -------------------------------------------------------------------- #
def test_e2e_gate_pass_produces_acceptance_summary_stdout(tmp_path: Path, capsys):
    mgr = TaskSessionManager(tmp_path, clock=lambda: "2026-07-04T08:00:00Z")
    gate_res = {"gate_decision": "pass", "historical_issues": [], "per_issue_states": []}

    # 模拟 gate 通过但有 1 个 RESOLVED BLOCK issue
    triples = [_triple(OutputState.RESOLVED, severity=Severity.BLOCK)]

    with patch(
        "vibe_tracing.cli.analyze.pipeline._run_gate_evaluation",
        return_value=(gate_res, triples),
    ), patch(
        "vibe_tracing.cli.analyze.pipeline._build_report_document",
        return_value={},
    ), patch(
        "vibe_tracing.cli.analyze.output._render_dashboard",
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
            task_name_lookup={"TASK-VT-190": "交付描述文本"},
            phase_id_lookup={"TASK-VT-190": "PHASE-VT-016"},
            model="claude-opus-4-8",
        )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "═══ 任务验收摘要 ═══" in out
    assert "TASK-VT-190" in out
    assert "[接受] accept" in out or "[驳回] reject" in out
    assert "交付描述文本" in out
    assert "已解决：BLOCK 1 项 / WARNING 0 项" in out
    assert "迭代次数：1" in out, "iterations 字段未传播到 stdout"
    # Channel 分离验证：stdout 中不含反思提示
    assert "反思" not in out


# -------------------------------------------------------------------- #
# E2E #2：gate=BLOCKED → stdout 无验收摘要
# -------------------------------------------------------------------- #
def test_e2e_gate_blocked_no_acceptance_summary(tmp_path: Path, capsys):
    mgr = TaskSessionManager(tmp_path, clock=lambda: "2026-07-04T08:00:00Z")
    gate_res = {"gate_decision": "blocked", "historical_issues": [], "per_issue_states": []}
    triples = [_triple(OutputState.CURRENT_BLOCK)]

    with patch(
        "vibe_tracing.cli.analyze.pipeline._run_gate_evaluation",
        return_value=(gate_res, triples),
    ), patch(
        "vibe_tracing.cli.analyze.pipeline._build_report_document",
        return_value={},
    ), patch(
        "vibe_tracing.cli.analyze.output._render_dashboard",
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
    out = capsys.readouterr().out
    assert "═══ 任务验收摘要 ═══" not in out
    # session 保持 IN_PROGRESS
    session = mgr.get_session("TASK-VT-190")
    assert session is not None
    assert session.status == "IN_PROGRESS"


# -------------------------------------------------------------------- #
# E2E #3：closed task 引用 → exit 3（与 exit 2 隔离）
# -------------------------------------------------------------------- #
def test_e2e_closed_task_reference_returns_3(tmp_path: Path, capsys):
    mgr = TaskSessionManager(tmp_path, clock=lambda: "2026-07-04T08:00:00Z")
    mgr.update_sessions(
        {"TASK-VT-190"}, [], "pass",
        {"TASK-VT-190": "title"},
        {"TASK-VT-190": "PHASE-VT-016"},
        "unknown",
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
    captured = capsys.readouterr()
    assert "CLOSED" in captured.err
    assert "TASK-VT-190" in captured.err


# -------------------------------------------------------------------- #
# E2E #4：immutability — CLOSED task 数据在后续 analyze 中不被修改
# -------------------------------------------------------------------- #
def test_e2e_closed_task_immutability(tmp_path: Path):
    mgr = TaskSessionManager(tmp_path, clock=lambda: "2026-07-04T08:00:00Z")
    gate_res = {"gate_decision": "pass", "historical_issues": [], "per_issue_states": []}

    # 第一次：PASS → CLOSED
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
            task_name_lookup={"TASK-VT-190": "original"},
            phase_id_lookup={"TASK-VT-190": "PHASE-VT-016"},
            model="claude-opus-4-8",
        )
    assert exit_code == 0
    first_session = mgr.get_session("TASK-VT-190")
    assert first_session.status == "CLOSED"
    closed_at_original = first_session.closed_at
    iterations_original = first_session.iterations

    # 第二次：同一 task → exit 3，数据未被修改
    exit_code2 = _evaluate_and_output(
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
    assert exit_code2 == 3
    second_session = mgr.get_session("TASK-VT-190")
    assert second_session.status == "CLOSED"
    assert second_session.closed_at == closed_at_original
    assert second_session.iterations == iterations_original


# -------------------------------------------------------------------- #
# E2E #5：report_doc 新 key 全链路
# -------------------------------------------------------------------- #
def test_e2e_report_doc_contains_new_top_level_keys(tmp_path: Path):
    """TaskSessionManager → _build_report_document → 新 key 存在。"""
    from vibe_tracing.cli.analyze.reports import _build_acceptance_archive

    mgr = TaskSessionManager(tmp_path, clock=lambda: "2026-07-04T08:00:00Z")
    gate_res = {"gate_decision": "pass", "historical_issues": [], "per_issue_states": []}

    with patch(
        "vibe_tracing.cli.analyze.pipeline._run_gate_evaluation",
        return_value=(gate_res, []),
    ), patch(
        "vibe_tracing.cli.analyze.pipeline._render_output",
        return_value=None,
    ), patch(
        "vibe_tracing.cli.analyze.output._render_dashboard",
        return_value=None,
    ), patch(
        "vibe_tracing.infra.report.traceability.TraceabilityReportBuilder.build",
        side_effect=lambda doc, **kwargs: doc,
    ):
        # 让 _build_report_document 真实运行
        captured_report = {}

        def fake_build(ctx, gr, em, mg, fr, cr, od, pr, **kw):
            from vibe_tracing.cli.analyze.reports import _build_report_document as real_build
            od.mkdir(parents=True, exist_ok=True)
            doc = real_build(ctx, gr, em, mg, fr, cr, od, pr, **kw)
            captured_report.update(doc)
            return doc

        with patch(
            "vibe_tracing.cli.analyze.pipeline._build_report_document",
            side_effect=fake_build,
        ):
            exit_code = _evaluate_and_output(
                ctx=_ctx_stub(),
                merged_gaps=[],
                final_risks=[],
                compliance_res=None,
                output_dir=tmp_path / "output",
                evidence_meta={"run_id": "R1", "project_id": "P1", "scan_time": "2026-07-04T08:00:00Z"},
                project_root=tmp_path,
                current_commit_task_set={"TASK-VT-190"},
                session_mgr=mgr,
                task_name_lookup={"TASK-VT-190": "title"},
                phase_id_lookup={"TASK-VT-190": "PHASE-VT-016"},
                model="claude-opus-4-8",
            )

    assert exit_code == 0
    assert "acceptance_archive" in captured_report
    assert "rule_stats_table" in captured_report
    assert "governance_metrics" in captured_report
    assert "agent_capability_metrics" in captured_report
    assert isinstance(captured_report["acceptance_archive"], list)
    assert isinstance(captured_report["rule_stats_table"], list)
    assert isinstance(captured_report["governance_metrics"], dict)
    assert isinstance(captured_report["agent_capability_metrics"], dict)
    # CLOSED task 应出现在 acceptance_archive
    assert any(a["task_id"] == "TASK-VT-190" for a in captured_report["acceptance_archive"])


# -------------------------------------------------------------------- #
# E2E #6：Dashboard 模板含 4 个新 Tab 容器
# -------------------------------------------------------------------- #
def test_dashboard_template_contains_new_tabs():
    """dashboard.template.html 必须含 T195/T196 新增的 4 个 Tab 容器。"""
    tpl_path = Path(__file__).parents[1] / "src" / "vibe_tracing" / "templates" / "dashboard.template.html"
    text = tpl_path.read_text(encoding="utf-8")
    for tab_id in (
        "tab-acceptance",
        "tab-governance",
        "tab-capability",
        "rule-stats-table-body",
        "acceptance-table-body",
        "block-concentration-body",
        "avg-iterations-table-body",
    ):
        assert tab_id in text, f"missing tab id: {tab_id}"
    # Channel 分离验证：模板中无 stdout 反思提示标记
    assert "render_reflection_prompts" not in text


# -------------------------------------------------------------------- #
# E2E #7：stdout 中不含反思提示（Channel 分离落地验证）
# -------------------------------------------------------------------- #
def test_stdout_no_reflection_prompts_in_render_output(tmp_path: Path, capsys, monkeypatch):
    """_render_output 的 stdout 中不得包含 8 维度反思文本。"""
    from vibe_tracing.cli.analyze.output import _render_output

    gate_res = {"gate_decision": "pass", "historical_issues": [], "per_issue_states": []}
    monkeypatch.setattr(
        "vibe_tracing.cli.analyze.output._render_dashboard",
        lambda *a, **kw: None,
    )

    _render_output(
        ctx=_ctx_stub(),
        gate_res=gate_res,
        report_doc={},
        evidence_meta={},
        active_gaps=[],
        active_risks=[],
        merged_gaps=[],
        final_risks=[],
        compliance_res=None,
        current_commit_task_set=set(),
        output_dir=tmp_path / "output",
        project_root=tmp_path,
    )

    out = capsys.readouterr().out
    # 反思文本的典型中文关键词（来自 infra/report/reflection.py）
    for kw in ("8 维度", "深度反思", "Phase Reflection", "反思提示"):
        assert kw not in out, f"reflection text leaked into stdout: {kw}"


# -------------------------------------------------------------------- #
# E2E #8：规则触发表排序（block 降序 + 从未触发沉底）
# -------------------------------------------------------------------- #
def test_e2e_rule_stats_table_sort_order(tmp_path: Path):
    from vibe_tracing.domain.task.session import TaskSession
    sessions = {
        "A": TaskSession(
            task_id="A", phase_id="P1", status="CLOSED",
            first_seen="2026-07-04T08:00:00Z", closed_at="2026-07-04T09:00:00Z",
            iterations=1,
            issue_counts={"no_claim": {"BLOCK": 10, "WARNING": 0}},
        ),
        "B": TaskSession(
            task_id="B", phase_id="P1", status="CLOSED",
            first_seen="2026-07-04T08:00:00Z", closed_at="2026-07-04T09:00:00Z",
            iterations=1,
            issue_counts={"substandard:linter": {"BLOCK": 0, "WARNING": 5}},
        ),
        "C": TaskSession(
            task_id="C", phase_id="P1", status="CLOSED",
            first_seen="2026-07-04T08:00:00Z", closed_at="2026-07-04T09:00:00Z",
            iterations=1,
            issue_counts={"task_failed": {"BLOCK": 1, "WARNING": 0}},
        ),
        "D": TaskSession(
            task_id="D", phase_id="P1", status="CLOSED",
            first_seen="2026-07-04T08:00:00Z", closed_at="2026-07-04T09:00:00Z",
            iterations=1,
            issue_counts={},  # 从未触发
        ),
    }
    rows = GovernanceMetricsAggregator.aggregate_rule_stats_table(sessions)
    rule_ids = [r["rule_id"] for r in rows]
    # no_claim (BLOCK=10) 首位；task_failed (BLOCK=1) 其次；substandard (WARNING=5) 第三；D 从未触发末位
    assert rule_ids[0] == "no_claim"
    assert rule_ids[1] == "task_failed"
    assert rule_ids[-1] in ("", ) or rows[-1]["block_count"] == 0
    # 从未触发一定在最后
    never_rows = [r for r in rows if r["block_count"] == 0 and r["warning_count"] == 0]
    if never_rows:
        assert rows[-1]["block_count"] == 0
        assert rows[-1]["warning_count"] == 0


# -------------------------------------------------------------------- #
# E2E #9：Agent 能力警告不出现在 stdout（仅 Dashboard 徽章）
# -------------------------------------------------------------------- #
def test_e2e_capability_warnings_not_in_stdout(tmp_path: Path, capsys):
    """Agent 能力警告仅存在于 agent_capability_metrics，不打印到 stdout。"""
    mgr = TaskSessionManager(tmp_path, clock=lambda: "2026-07-04T08:00:00Z")
    gate_res = {"gate_decision": "pass", "historical_issues": [], "per_issue_states": []}

    with patch(
        "vibe_tracing.cli.analyze.pipeline._run_gate_evaluation",
        return_value=(gate_res, []),
    ), patch(
        "vibe_tracing.cli.analyze.pipeline._build_report_document",
        return_value={},
    ), patch(
        "vibe_tracing.cli.analyze.output._render_dashboard",
        return_value=None,
    ):
        _evaluate_and_output(
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

    out = capsys.readouterr().out
    assert "首次通过率偏低" not in out
    assert "平均迭代次数偏高" not in out
    assert "同类重复" not in out


# -------------------------------------------------------------------- #
# E2E #10：stdout 中无 emoji
# -------------------------------------------------------------------- #
def test_e2e_stdout_no_emoji_in_acceptance_summary(tmp_path: Path, capsys):
    mgr = TaskSessionManager(tmp_path, clock=lambda: "2026-07-04T08:00:00Z")
    gate_res = {"gate_decision": "pass", "historical_issues": [], "per_issue_states": []}

    with patch(
        "vibe_tracing.cli.analyze.pipeline._run_gate_evaluation",
        return_value=(gate_res, []),
    ), patch(
        "vibe_tracing.cli.analyze.pipeline._build_report_document",
        return_value={},
    ), patch(
        "vibe_tracing.cli.analyze.output._render_dashboard",
        return_value=None,
    ):
        _evaluate_and_output(
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

    out = capsys.readouterr().out
    assert not _EMOJI_RE.search(out), f"emoji leaked into stdout: {out}"
