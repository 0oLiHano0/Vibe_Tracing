"""GovernanceMetricsAggregator (5 分类) + _build_acceptance_archive + report_doc。

覆盖 docs/design/phase_channel_separation.md §2.3.4 / §3.2.3 + TASK-VT-195 DOD：
    - 5 分类验收链条汇总（aggregate_category_summary）
    - 衍生 task 比例（命中 / 未命中 / 空 task 列表）
    - 按 PHASE 分组的平均迭代次数（仅 CLOSED task）
    - reports._build_report_document 新增 acceptance_archive / category_summary / governance_metrics
    - Dashboard 模板新增 Tab 5 / Tab 8（容器存在 + 数据非空）
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from vibe_tracing.domain.task.session import AcceptanceSummary, TaskSession
from vibe_tracing.domain.governance.metrics import GovernanceMetricsAggregator
from vibe_tracing.domain.governance.category_mapper import CATEGORIES
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


def _find_cat(result: list, category: str) -> dict:
    return next(r for r in result if r["category"] == category)


# ---------------------------------------------------------------------- #
# aggregate_category_summary: 基本结构
# ---------------------------------------------------------------------- #
def test_category_summary_returns_five_entries() -> None:
    result = GovernanceMetricsAggregator.aggregate_category_summary({})
    assert len(result) == 5
    cat_ids = [r["category"] for r in result]
    expected = [c["id"] for c in CATEGORIES]
    assert cat_ids == expected


def test_category_summary_empty_sessions_all_passed() -> None:
    result = GovernanceMetricsAggregator.aggregate_category_summary({})
    assert all(r["status"] == "passed" for r in result)
    assert all(r["block_count"] == 0 for r in result)
    assert all(r["warning_count"] == 0 for r in result)
    assert all(r["details"] == [] for r in result)


def test_category_summary_entry_fields_complete() -> None:
    sessions = {
        "T1": _session("T1", issue_counts={
            "chain_broken:GATE-VT-006": {"BLOCK": 3, "WARNING": 1},
        }),
    }
    result = GovernanceMetricsAggregator.aggregate_category_summary(sessions)
    quality = _find_cat(result, "交付质量")
    assert quality["status"] == "failed"
    assert quality["gate_level"] == "WARNING"
    assert quality["block_count"] == 3
    assert quality["warning_count"] == 1
    assert len(quality["details"]) == 1
    assert quality["details"][0]["rule_id"] == "chain_broken:GATE-VT-006"


# ---------------------------------------------------------------------- #
# aggregate_category_summary: 分类映射正确性
# ---------------------------------------------------------------------- #
def test_category_summary_maps_to_correct_categories() -> None:
    sessions = {
        "T1": _session("T1", issue_counts={
            "no_claim": {"BLOCK": 2, "WARNING": 0},
            "task_failed": {"BLOCK": 1, "WARNING": 0},
            "isolated_task": {"BLOCK": 0, "WARNING": 3},
            "chain_broken:GATE-VT-006": {"BLOCK": 1, "WARNING": 0},
            "chain_broken:proposal:r1": {"BLOCK": 1, "WARNING": 0},
        }),
    }
    result = GovernanceMetricsAggregator.aggregate_category_summary(sessions)

    assert _find_cat(result, "交付凭证")["block_count"] == 2
    assert _find_cat(result, "证据验证")["block_count"] == 1
    assert _find_cat(result, "链路完整性")["warning_count"] == 3
    assert _find_cat(result, "交付质量")["block_count"] == 1
    assert _find_cat(result, "过程合规")["block_count"] == 1


def test_category_summary_status_failed_when_block() -> None:
    sessions = {"T1": _session("T1", issue_counts={
        "no_claim": {"BLOCK": 1, "WARNING": 0},
    })}
    result = GovernanceMetricsAggregator.aggregate_category_summary(sessions)
    assert _find_cat(result, "交付凭证")["status"] == "failed"


def test_category_summary_status_warning_when_only_warning() -> None:
    sessions = {"T1": _session("T1", issue_counts={
        "isolated_task": {"BLOCK": 0, "WARNING": 2},
    })}
    result = GovernanceMetricsAggregator.aggregate_category_summary(sessions)
    assert _find_cat(result, "链路完整性")["status"] == "warning"


def test_category_summary_status_passed_when_no_issues() -> None:
    sessions = {"T1": _session("T1", issue_counts={
        "no_claim": {"BLOCK": 1, "WARNING": 0},
    })}
    result = GovernanceMetricsAggregator.aggregate_category_summary(sessions)
    assert _find_cat(result, "链路完整性")["status"] == "passed"
    assert _find_cat(result, "证据验证")["status"] == "passed"


# ---------------------------------------------------------------------- #
# aggregate_category_summary: 多 session 聚合
# ---------------------------------------------------------------------- #
def test_category_summary_aggregates_across_sessions() -> None:
    sessions = {
        "T1": _session("T1", issue_counts={
            "no_claim": {"BLOCK": 2, "WARNING": 1},
        }),
        "T2": _session("T2", issue_counts={
            "no_claim": {"BLOCK": 3, "WARNING": 0},
        }),
    }
    result = GovernanceMetricsAggregator.aggregate_category_summary(sessions)
    proof = _find_cat(result, "交付凭证")
    assert proof["block_count"] == 5
    assert proof["warning_count"] == 1


def test_category_summary_details_sorted_by_block_desc() -> None:
    sessions = {"T1": _session("T1", issue_counts={
        "chain_broken:GATE-VT-006": {"BLOCK": 1, "WARNING": 0},
        "chain_broken:GATE-VT-001": {"BLOCK": 5, "WARNING": 0},
    })}
    result = GovernanceMetricsAggregator.aggregate_category_summary(sessions)
    quality = _find_cat(result, "交付质量")
    assert quality["details"][0]["rule_id"] == "chain_broken:GATE-VT-001"
    assert quality["details"][1]["rule_id"] == "chain_broken:GATE-VT-006"


# ---------------------------------------------------------------------- #
# aggregate_category_summary: phase_filter / task_filter
# ---------------------------------------------------------------------- #
def test_category_summary_phase_filter() -> None:
    sessions = {
        "T1": _session("T1", phase_id="PHASE-VT-015", issue_counts={
            "no_claim": {"BLOCK": 5, "WARNING": 0},
        }),
        "T2": _session("T2", phase_id="PHASE-VT-016", issue_counts={
            "no_claim": {"BLOCK": 3, "WARNING": 1},
        }),
    }
    r15 = GovernanceMetricsAggregator.aggregate_category_summary(sessions, phase_filter="PHASE-VT-015")
    assert _find_cat(r15, "交付凭证")["block_count"] == 5

    r16 = GovernanceMetricsAggregator.aggregate_category_summary(sessions, phase_filter="PHASE-VT-016")
    assert _find_cat(r16, "交付凭证")["block_count"] == 3
    assert _find_cat(r16, "交付凭证")["warning_count"] == 1


def test_category_summary_task_filter() -> None:
    sessions = {
        "T1": _session("T1", issue_counts={"no_claim": {"BLOCK": 5, "WARNING": 0}}),
        "T2": _session("T2", issue_counts={"no_claim": {"BLOCK": 2, "WARNING": 3}}),
    }
    r1 = GovernanceMetricsAggregator.aggregate_category_summary(sessions, task_filter="T1")
    assert _find_cat(r1, "交付凭证")["block_count"] == 5

    r2 = GovernanceMetricsAggregator.aggregate_category_summary(sessions, task_filter="T2")
    assert _find_cat(r2, "交付凭证")["block_count"] == 2
    assert _find_cat(r2, "交付凭证")["warning_count"] == 3


def test_category_summary_phase_filter_no_match() -> None:
    sessions = {
        "T1": _session("T1", phase_id="PHASE-VT-015", issue_counts={
            "no_claim": {"BLOCK": 5, "WARNING": 0},
        }),
    }
    result = GovernanceMetricsAggregator.aggregate_category_summary(sessions, phase_filter="PHASE-VT-999")
    assert all(r["status"] == "passed" for r in result)


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
        "T3": _session("T3", phase_id="PHASE-VT-015", iterations=10, status="IN_PROGRESS"),
        "T4": _session("T4", phase_id="PHASE-VT-016", iterations=3, status="CLOSED"),
    }
    result = GovernanceMetricsAggregator.aggregate_avg_iterations_by_phase(sessions)
    assert result == {"PHASE-VT-015": 3.0, "PHASE-VT-016": 3.0}


def test_avg_iterations_by_phase_empty_sessions() -> None:
    result = GovernanceMetricsAggregator.aggregate_avg_iterations_by_phase({})
    assert result == {}


# ---------------------------------------------------------------------- #
# DOD-VT-195-05: acceptance_archive 聚合 + report_doc 新 key
# ---------------------------------------------------------------------- #
def test_acceptance_archive_filters_closed_and_sorts_by_closed_at_desc() -> None:
    sessions = {
        "T1": _session("T1", phase_id="PHASE-1", status="CLOSED",
                       closed_at="2026-07-01T08:00:00Z",
                       acceptance_summary=AcceptanceSummary(
                           recommendation="accept", delivery="task 1 交付",
                           resolved_block=1, resolved_warning=2, remaining_warning=0,
                       )),
        "T2": _session("T2", phase_id="PHASE-1", status="IN_PROGRESS"),
        "T3": _session("T3", phase_id="PHASE-1", status="CLOSED",
                       closed_at="2026-07-04T10:30:00Z",
                       acceptance_summary=AcceptanceSummary(
                           recommendation="reject", delivery="task 3 交付",
                           severe_risks=["risk A"], resolved_block=0,
                           resolved_warning=1, remaining_warning=1,
                       )),
        "T4": _session("T4", phase_id="PHASE-1", status="CLOSED",
                       closed_at="2026-07-03T09:00:00Z",
                       acceptance_summary=None),
    }
    archive = _build_acceptance_archive(sessions)
    assert len(archive) == 2
    assert archive[0]["task_id"] == "T3"
    assert archive[1]["task_id"] == "T1"
    assert archive[0]["recommendation"] == "reject"
    assert archive[0]["severe_risks"] == ["risk A"]
    assert archive[1]["delivery"] == "task 1 交付"


def test_acceptance_archive_empty_when_no_closed() -> None:
    assert _build_acceptance_archive({}) == []
    assert _build_acceptance_archive(
        {"T1": _session("T1", status="IN_PROGRESS")}
    ) == []


def test_build_report_document_adds_category_keys(tmp_path: Path) -> None:
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
    assert "category_summary" in doc
    assert "category_by_phase" in doc
    assert "category_by_task" in doc
    assert "governance_metrics" in doc
    assert isinstance(doc["acceptance_archive"], list)
    assert isinstance(doc["category_summary"], list)
    assert len(doc["category_summary"]) == 5
    assert isinstance(doc["category_by_phase"], dict)
    assert isinstance(doc["category_by_task"], dict)
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
    assert len(doc["category_summary"]) == 5
    assert all(c["status"] == "passed" for c in doc["category_summary"])
    assert doc["category_by_phase"] == {}
    assert doc["category_by_task"] == {}
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
    assert 'id="category-summary-body"' in html
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


def test_dashboard_template_category_multi_view_elements() -> None:
    path = Path("src/vibe_tracing/templates/dashboard.template.html")
    html = path.read_text(encoding="utf-8")
    assert 'id="category-view-switcher"' in html
    assert 'id="category-view-global"' in html
    assert 'id="category-view-phase"' in html
    assert 'id="category-view-task"' in html
    assert 'id="category-phase-container"' in html
    assert 'id="category-task-selector"' in html
    assert 'switchCategoryView' in html


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
        "category_summary": [
            {
                "category": "链路完整性",
                "description": "PRD→Task→Claim 链路是否完整",
                "status": "passed",
                "gate_level": "BLOCK",
                "block_count": 0,
                "warning_count": 0,
                "details": [],
            },
            {
                "category": "交付凭证",
                "description": "代码是否交付并声明",
                "status": "failed",
                "gate_level": "BLOCK",
                "block_count": 3,
                "warning_count": 0,
                "details": [{"rule_id": "no_claim", "block_count": 3, "warning_count": 0}],
            },
        ],
        "governance_metrics": {
            "derived_task_ratio": 0.25,
            "avg_iterations_by_phase": {"PHASE-VT-016": 3.0},
        },
    }

    renderer.render(
        evidence_index={"run_id": "RUN-T195", "project_id": "PROJECT-VT",
                        "scan_time": "2026-07-04T12:00:00Z", "full_chain": []},
        traceability_report=trace_report,
        output_path=output_path,
    )
    html = output_path.read_text(encoding="utf-8")
    assert 'id="tab-acceptance"' in html
    assert 'id="tab-governance"' in html
    assert "TASK-VT-190" in html
    assert "交付凭证" in html
