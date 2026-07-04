"""GovernanceMetricsAggregator + _build_acceptance_archive + report_doc 三个新 key。

覆盖 docs/design_channel_separation.md §2.3.4 / §3.2.3 + TASK-VT-195 DOD：
    - 规则触发表聚合 + 降序 + 从未触发沉底
    - 衍生 task 比例（命中 / 未命中 / 空 task 列表）
    - 按 PHASE 分组的平均迭代次数（仅 CLOSED task）
    - reports._build_report_document 新增 acceptance_archive / rule_stats_table / governance_metrics
    - Dashboard 模板新增 Tab 5 / Tab 8（容器存在 + 数据非空）
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from vibe_tracing.domain.task.session import AcceptanceSummary, TaskSession
from vibe_tracing.domain.governance.metrics import GovernanceMetricsAggregator
from vibe_tracing.cli.analyze.reports import _build_acceptance_archive


# ---------------------------------------------------------------------- #
# helpers
# ---------------------------------------------------------------------- #
def _session(
    task_id: str = "TASK-VT-190",
    phase_id: str = "PHASE-VT-016",
    status: str = "CLOSED",
    iterations: int = 2,
    issue_counts: dict = None,
    closed_at: str = "2026-07-04T10:30:00Z",
    first_seen: str = "2026-07-04T08:00:00Z",
    acceptance_summary: AcceptanceSummary = None,
) -> TaskSession:
    return TaskSession(
        task_id=task_id,
        phase_id=phase_id,
        status=status,
        iterations=iterations,
        issue_counts=issue_counts or {},
        closed_at=closed_at,
        first_seen=first_seen,
        model="claude-opus-4-8",
        acceptance_summary=acceptance_summary,
    )


# ---------------------------------------------------------------------- #
# DOD-VT-195-01: 规则触发表降序 + 从未触发沉底
# ---------------------------------------------------------------------- #
def test_rule_stats_table_sorted_by_block_desc() -> None:
    sessions = {
        "T1": _session("T1", issue_counts={
            "no_claim": {"BLOCK": 1, "WARNING": 0},
            "chain_broken": {"BLOCK": 5, "WARNING": 2},
        }),
        "T2": _session("T2", issue_counts={
            "substandard:coverage": {"BLOCK": 0, "WARNING": 3},
        }),
    }
    rows = GovernanceMetricsAggregator.aggregate_rule_stats_table(sessions)
    # chain_broken (5) > no_claim (1) > substandard:coverage (0 block but 3 warn, not sunk)
    rule_ids = [r["rule_id"] for r in rows]
    assert rule_ids[0] == "chain_broken"
    assert rule_ids[1] == "no_claim"


def test_rule_stats_table_warning_only_sunk_below_block() -> None:
    """0-block+N-warn 条目排在正 block 条目之下；(0,0) 沉底。"""
    sessions = {
        "T1": _session("T1", issue_counts={
            "high_block": {"BLOCK": 10, "WARNING": 0},
            "warn_only": {"BLOCK": 0, "WARNING": 5},
            "low_block": {"BLOCK": 1, "WARNING": 0},
            "never": {"BLOCK": 0, "WARNING": 0},
        }),
    }
    rows = GovernanceMetricsAggregator.aggregate_rule_stats_table(sessions)
    rule_ids = [r["rule_id"] for r in rows]
    # 正 block 在前（high_block > low_block）；warn_only (0 block) 在它们之后；never 沉底
    assert rule_ids.index("high_block") < rule_ids.index("low_block")
    assert rule_ids.index("low_block") < rule_ids.index("warn_only")
    assert rule_ids[-1] == "never"


# ---------------------------------------------------------------------- #
# DOD-VT-195-02: 规则条目字段完整
# ---------------------------------------------------------------------- #
def test_rule_stats_table_entry_fields_complete() -> None:
    sessions = {
        "T1": _session("T1", issue_counts={
            "chain_broken:GATE-VT-006": {"BLOCK": 3, "WARNING": 1},
        }),
    }
    rows = GovernanceMetricsAggregator.aggregate_rule_stats_table(sessions)
    assert len(rows) == 1
    r = rows[0]
    assert r["rule_id"] == "chain_broken:GATE-VT-006"
    assert r["block_count"] == 3
    assert r["warning_count"] == 1
    assert r["last_triggered"] != ""
    assert isinstance(r["description"], str) and r["description"]


def test_rule_stats_table_description_includes_subtype() -> None:
    sessions = {
        "T1": _session("T1", issue_counts={
            "chain_broken:GATE-VT-006": {"BLOCK": 1, "WARNING": 0},
        }),
    }
    rows = GovernanceMetricsAggregator.aggregate_rule_stats_table(sessions)
    assert "GATE-VT-006" in rows[0]["description"]


# ---------------------------------------------------------------------- #
# DOD-VT-195-03: 衍生 task 比例
# ---------------------------------------------------------------------- #
def test_derived_task_ratio_matches_keywords() -> None:
    class _T:
        def __init__(self, title): self.title = title
    tasks = [
        _T("实现新功能 TASK-VT-100"),
        _T("修复 TASK-VT-101 的 bug"),
        _T("优化 TASK-VT-102 的性能"),
        _T("调整 TASK-VT-103 的接口"),
        _T("新增测试 TASK-VT-104"),
    ]
    ratio = GovernanceMetricsAggregator.aggregate_derived_task_ratio(tasks)
    assert ratio == pytest.approx(0.6)  # 3/5


def test_derived_task_ratio_no_match() -> None:
    class _T:
        title = "实现新功能 TASK-VT-100"
    ratio = GovernanceMetricsAggregator.aggregate_derived_task_ratio([_T()])
    assert ratio == 0.0


def test_derived_task_ratio_empty_tasks() -> None:
    ratio = GovernanceMetricsAggregator.aggregate_derived_task_ratio([])
    assert ratio == 0.0


def test_derived_task_ratio_empty_titles_skipped() -> None:
    class _T:
        title = ""
    ratio = GovernanceMetricsAggregator.aggregate_derived_task_ratio([_T(), _T()])
    assert ratio == 0.0


# ---------------------------------------------------------------------- #
# DOD-VT-195-04: 按 PHASE 平均迭代次数（仅 CLOSED task）
# ---------------------------------------------------------------------- #
def test_avg_iterations_by_phase_closed_only() -> None:
    sessions = {
        "T1": _session("T1", phase_id="PHASE-VT-015", iterations=2, status="CLOSED"),
        "T2": _session("T2", phase_id="PHASE-VT-015", iterations=4, status="CLOSED"),
        "T3": _session("T3", phase_id="PHASE-VT-015", iterations=10, status="IN_PROGRESS"),  # skipped
        "T4": _session("T4", phase_id="PHASE-VT-016", iterations=3, status="CLOSED"),
    }
    result = GovernanceMetricsAggregator.aggregate_avg_iterations_by_phase(sessions)
    assert result == {"PHASE-VT-015": 3.0, "PHASE-VT-016": 3.0}


def test_avg_iterations_by_phase_empty_sessions() -> None:
    result = GovernanceMetricsAggregator.aggregate_avg_iterations_by_phase({})
    assert result == {}


# ---------------------------------------------------------------------- #
# DOD-VT-195-05: acceptance_archive 聚合 + report_doc 三个新 key
# ---------------------------------------------------------------------- #
def test_acceptance_archive_filters_closed_and_sorts_by_closed_at_desc() -> None:
    sessions = {
        "T1": _session("T1", phase_id="PHASE-1", status="CLOSED",
                       closed_at="2026-07-01T08:00:00Z",
                       acceptance_summary=AcceptanceSummary(
                           recommendation="accept", delivery="task 1 交付",
                           resolved_block=1, resolved_warning=2, remaining_warning=0,
                       )),
        "T2": _session("T2", phase_id="PHASE-1", status="IN_PROGRESS"),  # excluded
        "T3": _session("T3", phase_id="PHASE-1", status="CLOSED",
                       closed_at="2026-07-04T10:30:00Z",
                       acceptance_summary=AcceptanceSummary(
                           recommendation="reject", delivery="task 3 交付",
                           severe_risks=["risk A"], resolved_block=0,
                           resolved_warning=1, remaining_warning=1,
                       )),
        "T4": _session("T4", phase_id="PHASE-1", status="CLOSED",
                       closed_at="2026-07-03T09:00:00Z",
                       acceptance_summary=None),  # excluded
    }
    archive = _build_acceptance_archive(sessions)
    assert len(archive) == 2
    assert archive[0]["task_id"] == "T3"  # most recent closed_at
    assert archive[1]["task_id"] == "T1"
    assert archive[0]["recommendation"] == "reject"
    assert archive[0]["severe_risks"] == ["risk A"]
    assert archive[1]["delivery"] == "task 1 交付"


def test_acceptance_archive_empty_when_no_closed() -> None:
    assert _build_acceptance_archive({}) == []
    assert _build_acceptance_archive(
        {"T1": _session("T1", status="IN_PROGRESS")}
    ) == []


def test_build_report_document_adds_three_keys(tmp_path: Path) -> None:
    from vibe_tracing.cli.analyze.reports import _build_report_document
    from vibe_tracing.domain.context import UnifiedContext

    class _Manifest:
        inputs_used = []
        has_required_errors = False

    ctx = UnifiedContext.__new__(UnifiedContext)
    ctx.manifest = _Manifest()
    ctx.claims_list = []
    ctx.prd = None
    ctx.constraints = None
    ctx.task_result = None
    ctx.config = {}
    ctx.config_prefix = "VT"
    ctx.governance_whitelist = set()
    ctx.governance_boundary = None

    gate_res = {"gate_decision": "pass", "per_issue_states": [], "historical_issues": []}
    sessions = {
        "T1": _session("T1", issue_counts={"no_claim": {"BLOCK": 2, "WARNING": 0}},
                       acceptance_summary=AcceptanceSummary(delivery="task 1")),
    }
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True)

    class _FakeBuilder:
        def __init__(self, *a, **kw): pass
        def build(self, doc, output_path=None): return doc

    with patch(
        "vibe_tracing.infra.report.traceability.TraceabilityReportBuilder", _FakeBuilder
    ), patch(
        "vibe_tracing.cli.analyze.reports._build_metadata", return_value={},
    ):
        doc = _build_report_document(
            ctx=ctx,
            gate_res=gate_res,
            evidence_meta={},
            merged_gaps=[],
            final_risks=[],
            compliance_res=None,
            output_dir=out_dir,
            project_root=tmp_path,
            sessions=sessions,
            task_list_for_governance=[],
        )

    assert "acceptance_archive" in doc
    assert "rule_stats_table" in doc
    assert "governance_metrics" in doc
    assert isinstance(doc["acceptance_archive"], list)
    assert isinstance(doc["rule_stats_table"], list)
    assert "derived_task_ratio" in doc["governance_metrics"]
    assert "avg_iterations_by_phase" in doc["governance_metrics"]


def test_build_report_document_default_empty_when_no_sessions(tmp_path: Path) -> None:
    from vibe_tracing.cli.analyze.reports import _build_report_document
    from vibe_tracing.domain.context import UnifiedContext

    class _Manifest:
        inputs_used = []
        has_required_errors = False

    ctx = UnifiedContext.__new__(UnifiedContext)
    ctx.manifest = _Manifest()
    ctx.claims_list = []
    ctx.prd = None
    ctx.constraints = None
    ctx.task_result = None
    ctx.config = {}
    ctx.config_prefix = "VT"
    ctx.governance_whitelist = set()
    ctx.governance_boundary = None

    gate_res = {"gate_decision": "pass", "per_issue_states": [], "historical_issues": []}
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True)

    class _FakeBuilder:
        def __init__(self, *a, **kw): pass
        def build(self, doc, output_path=None): return doc

    with patch(
        "vibe_tracing.infra.report.traceability.TraceabilityReportBuilder", _FakeBuilder
    ), patch(
        "vibe_tracing.cli.analyze.reports._build_metadata", return_value={},
    ):
        doc = _build_report_document(
            ctx=ctx, gate_res=gate_res, evidence_meta={}, merged_gaps=[],
            final_risks=[], compliance_res=None, output_dir=out_dir,
            project_root=tmp_path,
        )

    assert doc["acceptance_archive"] == []
    assert doc["rule_stats_table"] == []
    assert doc["governance_metrics"] == {
        "derived_task_ratio": 0.0, "avg_iterations_by_phase": {},
    }


# ---------------------------------------------------------------------- #
# DOD-VT-195-06/07: Dashboard Tab 5 / Tab 8 容器存在 + 近似指标标注
# ---------------------------------------------------------------------- #
def test_dashboard_template_has_tab_5_and_tab_8_containers() -> None:
    path = Path("src/vibe_tracing/templates/dashboard.template.html")
    html = path.read_text(encoding="utf-8")
    assert 'id="tab-acceptance"' in html
    assert 'id="tab-governance"' in html
    assert 'id="acceptance-table-body"' in html
    assert 'id="rule-stats-table-body"' in html
    assert 'id="avg-iterations-table-body"' in html


def test_dashboard_template_approximate_metric_disclaimer() -> None:
    """Tab 8 中'衍生 task 比例'旁必须显式标注'近似指标，仅作参考'（§2.3.4）。"""
    path = Path("src/vibe_tracing/templates/dashboard.template.html")
    html = path.read_text(encoding="utf-8")
    assert "近似指标" in html
    assert "仅作参考" in html


def test_dashboard_template_existing_tabs_intact() -> None:
    path = Path("src/vibe_tracing/templates/dashboard.template.html")
    html = path.read_text(encoding="utf-8")
    for tab_id in ("tab-overview", "tab-traceability", "tab-debts", "tab-evidences"):
        assert f'id="{tab_id}"' in html


def test_dashboard_renderer_produces_html_with_new_tabs(tmp_path: Path) -> None:
    """验证 DashboardRenderer 渲染后的 dashboard.html 含新 Tab 容器 + 数据非空。"""
    from vibe_tracing.infra.report.dashboard import DashboardRenderer

    renderer = DashboardRenderer(tmp_path)
    output_path = tmp_path / "output" / "dashboard.html"

    trace_report = {
        "run_id": "RUN-T195",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-07-04T12:00:00Z",
        "gate_decision": "pass",
        "per_issue_states": [],
        "historical_issues": [],
        "requirement_coverage": [],
        "gaps": [],
        "risks": [],
        "architecture_compliance_status": [],
        "architecture_violations": [],
        "unclear_constraints": [],
        "acceptance_archive": [
            {
                "task_id": "TASK-VT-190",
                "phase_id": "PHASE-VT-016",
                "closed_at": "2026-07-04T10:30:00Z",
                "iterations": 2,
                "model": "claude-opus-4-8",
                "recommendation": "accept",
                "delivery": "unified action pipeline",
                "severe_risks": [],
                "resolved_block": 5,
                "resolved_warning": 7,
                "remaining_warning": 1,
            },
        ],
        "rule_stats_table": [
            {
                "rule_id": "no_claim",
                "description": "任务缺少 Agent Claim 声明",
                "block_count": 3,
                "warning_count": 0,
                "last_triggered": "2026-07-04T10:30:00Z",
            },
        ],
        "governance_metrics": {
            "derived_task_ratio": 0.25,
            "avg_iterations_by_phase": {"PHASE-VT-016": 3.0},
        },
    }

    renderer.render(
        evidence_index={"run_id": "RUN-T195", "project_id": "PROJECT-VT",
                        "scan_time": "2026-07-04T12:00:00Z", "evidences": []},
        traceability_report=trace_report,
        output_path=output_path,
    )
    html = output_path.read_text(encoding="utf-8")
    assert 'id="tab-acceptance"' in html
    assert 'id="tab-governance"' in html
    assert "TASK-VT-190" in html
    assert "no_claim" in html
