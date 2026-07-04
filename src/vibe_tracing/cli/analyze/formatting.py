"""
Action rendering and formatting for agent consumption.
"""

from typing import List, Optional

from vibe_tracing.cli.analyze.actions import _collect_issue_actions


def _render_actions(actions: list, coverage_summary: Optional[dict] = None) -> list:
    """Render action dicts to text lines for Agent consumption.

    Actions are sorted by urgency (descending) so that the most pressing
    items appear first in the output.

    Args:
        actions: List of action dicts.
        coverage_summary: Aggregate coverage info.
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
    pending_human_count = sum(
        1 for a in actions if a.get("type") == "human_decision_required"
    )
    lines.append(f"当前变更: {current_change_count} 项 | 预存债务: {pre_existing_count} 项 | 等待人类: {pending_human_count} 项")

    # If there are human decision items, add explicit Agent instructions
    human_decision_items = [
        a for a in actions if a.get("type") == "human_decision_required"
    ]
    if human_decision_items:
        dec_ids = [
            a.get("context", {}).get("issue_id", "") for a in human_decision_items
        ]
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
    if coverage_summary:
        pct = coverage_summary["aggregate_percent"]
        status = "PASS" if pct >= 80 else "BLOCKED"
        lines.append("")
        lines.append(f"Coverage: {pct}% ({status}, target: 80%)")

    return lines


def _format_agent_actions(gate_decision, states_and_signals,
                          prd_result=None, task_result=None,
                          claims_list=None, coverage_summary=None,
                          conn=None):
    """Format an Agent-executable action list from (OutputState, IssueSignal, DetectedIssue) triples."""
    lines = [f"GATE DECISION: {gate_decision.upper()}", ""]
    actions: list = _collect_issue_actions(
        states_and_signals,
        prd_result=prd_result,
        task_result=task_result,
        claims_list=claims_list,
        coverage_summary=coverage_summary,
        conn=conn,
    )
    lines.extend(_render_actions(actions, coverage_summary))
    return "\n".join(lines)
