"""
VT CLI 包初始化

本包包含 Vibe Tracing 的所有 CLI 命令实现。
调度逻辑（argparse + 命令路由）位于 cli/main.py。

子命令分布：
  - cli/main.py     → main()         CLI 入口与调度
  - cli/init.py     → run_init()     项目初始化
  - cli/finalize.py → run_finalize() 锁定设计基线
  - cli/accept.py   → run_accept()   人类接受手动规则
  - cli/doctor.py   → run_doctor()   治理数据健康扫描
  - cli/analyze/    → run_analyze()  核心分析流水线
"""

import subprocess  # re-exported so test mocks on vibe_tracing.cli.subprocess work

# ---------------------------------------------------------------------------
# Re-export command entry points
# ---------------------------------------------------------------------------
from vibe_tracing.cli.main import main
from vibe_tracing.cli.init import run_init
from vibe_tracing.cli.finalize import run_finalize
from vibe_tracing.cli.analyze import run_analyze
from vibe_tracing.cli.doctor import run_doctor
from vibe_tracing.cli.accept import run_accept

# ---------------------------------------------------------------------------
# Re-export internal helpers used by tests
# ---------------------------------------------------------------------------
from vibe_tracing.cli.common import (
    _GateBlocked,
    _load_context,
    _rel_path_str,
    _get_staged_files,
    _determine_affected_items,
    _file_sha256,
)
from vibe_tracing.cli.finalize import (
    _validate_constraints_change,
    _print_post_finalize_guidance,
)
from vibe_tracing.cli.analyze.gates import (
    _gate1_constraints_hash,
    _gate1b_prd_drift,
    _gate1c_mapping,
    _gate2_code_claim_alignment,
    _run_integrity_gates,
)
from vibe_tracing.cli.analyze.tools import (
    _execute_tools,
    _check_staged_extensions,
)
from vibe_tracing.cli.analyze.analysis import (
    _run_analyzers,
    _load_human_decisions,
    _result_hash,
)
from vibe_tracing.cli.analyze.helpers import (
    _action_hints,
    _hint_title,
    _hint_context,
    _derive_test_scenarios,
    _get_ac_description,
    _get_req_description,
    _get_related_code,
    _get_existing_tests,
)
from vibe_tracing.cli.analyze.actions import (
    _compute_gap_urgency,
    _collect_gap_actions,
    _compute_risk_urgency,
    _collect_risk_actions,
    _collect_violation_actions,
    _collect_gate_reason_actions,
)
from vibe_tracing.cli.analyze.formatting import (
    _render_actions,
    _format_agent_actions,
)
from vibe_tracing.cli.analyze.reports import (
    _build_report_document,
    _build_metadata,
    _render_dashboard,
)
from vibe_tracing.cli.analyze.output import (
    _print_gate_summary,
    _print_agent_actions,
    _print_reflection_prompts,
    _render_output,
)
from vibe_tracing.cli.analyze.pipeline import (
    _run_analysis_phase,
    _run_gate_evaluation,
    _evaluate_and_output,
)
