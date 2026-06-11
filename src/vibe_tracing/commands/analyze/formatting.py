"""
Action rendering and formatting for agent consumption.
"""

from pathlib import Path
from typing import List, Optional

from vibe_tracing.commands.analyze.actions import (
    _collect_gap_actions,
    _collect_risk_actions,
    _collect_violation_actions,
    _collect_gate_reason_actions,
)


def _render_actions(actions: list, coverage_summary: Optional[dict] = None, project_root: Optional[Path] = None, coverage_violations: Optional[list] = None, evidence_index: Optional[dict] = None) -> list:
    """Render action dicts to text lines for Agent consumption.

    Actions are sorted by urgency (descending) so that the most pressing
    items appear first in the output.

    Args:
        actions: List of action dicts.
        coverage_summary: Aggregate coverage info (informational only).
        project_root: Project root path for reading coverage baseline.
        coverage_violations: Per-file coverage violations from evidence index.
            Each item is a dict with 'file' and 'percent' keys.
            Used for BLOCKED/PASS decision instead of aggregate percent.
    """
    lines: List[str] = []
    if not actions:
        lines.append("NO ACTION REQUIRED. Gate passed.")
        return lines

    # Sort actions by urgency descending (highest urgency first)
    sorted_actions = sorted(actions, key=lambda a: a.get("urgency", 0), reverse=True)

    for i, action in enumerate(sorted_actions, 1):
        lines.append(f"{'=' * 70}")
        lines.append(f"ACTION {i} [{action['priority']}] {action['title']}")
        lines.append(f"{'=' * 70}")
        ctx = action.get("context", {})
        for key, value in ctx.items():
            if isinstance(value, list):
                lines.append(f"  {key}:")
                for item in value:
                    if isinstance(item, dict):
                        lines.append(f"    - {item.get('path', '')}")
                    else:
                        lines.append(f"    - {item}")
            else:
                lines.append(f"  {key}: {value}")
        lines.append("")

    # Summary section
    lines.append("=" * 70)
    lines.append("SUMMARY")
    lines.append("=" * 70)

    high_count = sum(1 for a in actions if a.get("priority") == "HIGH")
    medium_count = sum(1 for a in actions if a.get("priority") == "MEDIUM")
    low_count = sum(1 for a in actions if a.get("priority") == "LOW")

    lines.append(f"HIGH: {high_count} | MEDIUM: {medium_count} | LOW: {low_count}")

    # Category breakdown by urgency
    current_change_count = sum(1 for a in actions if a.get("urgency", 0) >= 80)
    pre_existing_count = sum(1 for a in actions if 20 <= a.get("urgency", 0) < 80)
    pending_human_count = sum(1 for a in actions if a.get("pending_human_decision"))
    lines.append(f"当前变更: {current_change_count} 项 | 预存债务: {pre_existing_count} 项 | 等待人类: {pending_human_count} 项")

    # If there are human decision items, add explicit Agent instructions
    human_decision_items = [a for a in actions if a.get("type") == "human_decision"]
    if human_decision_items:
        dec_ids = [a.get("id", "") for a in human_decision_items]
        lines.append("")
        lines.append("⚠ 存在待人类决策的事项。请执行以下操作：")
        lines.append(f"1. 通知人类打开 dashboard: output/dashboard.html")
        lines.append(f"2. 在\"待决策\"标签页中查看 {', '.join(dec_ids)}")
        lines.append("3. 等待人类做出决策后，重新运行 vt analyze")
        if high_count > 0:
            lines.append("4. 在等待期间，可继续执行 HIGH 优先级的行动项")
    elif high_count == 0 and medium_count == 0:
        lines.append("NO ACTION REQUIRED. Gate passed.")

    # Add coverage info to agent output
    # Gate decision uses per-file violations from evidence index, NOT aggregate percent.
    if coverage_violations is not None:
        # Per-file violations from evidence index determine BLOCKED/PASS
        if coverage_violations:
            lines.append("")
            lines.append(f"Coverage: {len(coverage_violations)} file(s) below 80% (BLOCKED, target: 80%)")
            for cv in sorted(coverage_violations, key=lambda x: x.get("percent", 0)):
                lines.append(f"  {cv['file']}: {cv['percent']}%")
        else:
            lines.append("")
            lines.append("Coverage: all files >= 80% (PASS, target: 80%)")
        # Show aggregate as informational if available
        if coverage_summary:
            pct = coverage_summary["aggregate_percent"]
            lines.append(f"  (aggregate: {pct}% — informational only)")
    elif coverage_summary:
        # Fallback: use aggregate percent only when per-file data not available
        pct = coverage_summary["aggregate_percent"]
        status = "PASS" if pct >= 80 else "BLOCKED"
        lines.append("")
        lines.append(f"Coverage: {pct}% ({status}, target: 80%)")
        if pct < 80:
            # List files below threshold from evidence_index coverage_baseline
            cb = (evidence_index or {}).get("coverage_baseline", {})
            if cb:
                below = [(f, d["percent_covered"]) for f, d in cb.items()
                         if isinstance(d, dict) and d.get("percent_covered", 100) < 80]
                below.sort(key=lambda x: x[1])
                for f, p in below[:5]:
                    lines.append(f"  {f}: {p}%")

    return lines


def _format_agent_actions(gate_decision, active_gaps, active_risks, violations,
                          accepted_rules, prd_result=None, task_result=None,
                          claims_list=None, gate_reasons=None, merged_gaps=None,
                          compliance_status=None, coverage_summary=None,
                          project_root=None, coverage_violations=None,
                          staged_items=None, evidence_index=None):
    """Format an Agent-executable action list with full inline context."""
    lines = [f"GATE DECISION: {gate_decision.upper()}", ""]
    gaps_for_actions = merged_gaps if merged_gaps is not None else active_gaps
    actions: list = []
    actions.extend(_collect_gap_actions(
        gaps_for_actions, prd_result, task_result, claims_list,
        staged_items=staged_items, evidence_index=evidence_index,
    ))
    actions.extend(_collect_risk_actions(
        active_risks, merged_gaps or [],
        staged_items=staged_items, evidence_index=evidence_index,
    ))
    actions.extend(_collect_violation_actions(violations, compliance_status or []))
    actions.extend(_collect_gate_reason_actions(
        gate_decision, gate_reasons or [], actions,
    ))
    lines.extend(_render_actions(actions, coverage_summary, project_root, coverage_violations=coverage_violations, evidence_index=evidence_index))
    return "\n".join(lines)
