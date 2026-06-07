"""
Post-analyze reflection prompts for AI Agent self-improvement.

These prompts are printed at the end of every vt analyze run (non gates-only)
to trigger meta-cognitive reflection in the AI Agent, promoting architectural
self-awareness and continuous project evolution.

Reflection dimensions are loaded from a JSON template file, allowing
customization without code changes.
"""

import json
import os
from typing import Any, Dict, List, Optional


def load_dimensions(template_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load reflection dimensions from the JSON template.

    Args:
        template_path: Optional explicit path to the template JSON file.
            Defaults to templates/reflection_prompts.template.json adjacent
            to this module.

    Returns:
        List of dimension dicts, each with keys: id, index, title, prompt,
        conditional_hints.
    """
    if template_path is None:
        template_path = os.path.join(
            os.path.dirname(__file__), "templates", "reflection_prompts.template.json"
        )
    with open(template_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["dimensions"]


def _evaluate_condition(
    condition: str,
    *,
    has_blocked: bool,
    has_fail: bool,
    has_must_risks: bool,
    gap_count: int,
    risk_count: int,
    low_conf_count: int,
    has_coverage_gaps: bool,
    unclear_count: int,
    violation_count: int,
    uncovered_scope_count: int,
) -> bool:
    """Evaluate a named condition against the analysis context."""
    if condition == "gate_blocked":
        return has_blocked
    if condition == "gate_fail":
        return has_fail
    if condition == "has_must_risks":
        return has_must_risks
    if condition == "high_gap_risk_count":
        return gap_count > 5 or risk_count > 10
    if condition == "has_low_confidence":
        return low_conf_count > 0
    if condition == "has_coverage_gaps":
        return has_coverage_gaps
    if condition == "has_unclear_constraints":
        return unclear_count > 0
    if condition == "has_violations":
        return violation_count > 0
    if condition == "has_uncovered_evolution_scope":
        return uncovered_scope_count > 0
    return False


def check_uncovered_scopes(
    affected_files: List[str],
    task_list: Dict[str, Any],
) -> List[str]:
    """Return files in *affected_files* that are not covered by any task's code_refs.

    Extracts all file paths from ``task_list["tasks"][*]["code_refs"]`` (and any
    nested task structure), then returns the subset of *affected_files* that are
    missing from that set.

    Args:
        affected_files: File paths referenced by the current analysis context.
        task_list: Raw task_list.json dict (must contain ``"tasks"`` key).

    Returns:
        Sorted list of uncovered file paths.
    """
    covered_files: set = set()
    for task in task_list.get("tasks", []):
        for ref in task.get("code_refs", []):
            # Strip line-range suffix (e.g. "src/foo.py#L1-L10" -> "src/foo.py")
            path = ref.split("#")[0]
            if path:
                covered_files.add(path)
    uncovered = [f for f in affected_files if f not in covered_files]
    return sorted(uncovered)


def render_reflection_prompts(
    gate_decision: str,
    gaps: List[Dict[str, Any]],
    risks: List[Dict[str, Any]],
    task_list: Dict[str, Any],
    affected_files: List[str],
    compliance_result: Optional[Dict[str, Any]] = None,
    dimensions: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Render the 8-dimension reflection prompt block.

    Args:
        gate_decision: The final gate decision string.
        gaps: Identified gaps from analyzers.
        risks: Enriched risks from RiskAdvisor.
        task_list: Raw task_list.json dict (required, not Optional).
        affected_files: File paths from the analysis context (required).
        compliance_result: Result from ArchitectureComplianceChecker.
        dimensions: Optional list of dimension dicts to render. When None,
            loads from the default JSON template via ``load_dimensions()``.

    Returns:
        Formatted reflection prompt string for console output.
    """
    if dimensions is None:
        dimensions = load_dimensions()

    # Gather context for conditional prompts
    has_blocked = gate_decision == "blocked"
    has_fail = gate_decision == "fail"
    has_ac_gaps = any(g.get("item_type") == "ac" for g in gaps)
    has_req_gaps = any(g.get("item_type") == "requirement" for g in gaps)
    has_must_risks = any(r.get("severity") == "must" for r in risks)
    unclear_count = (
        len(compliance_result.get("unclear_constraints", []))
        if compliance_result
        else 0
    )
    violation_count = (
        len(compliance_result.get("architecture_violations", []))
        if compliance_result
        else 0
    )
    risk_count = len(risks)
    gap_count = len(gaps)
    low_conf_risks = [r for r in risks if r.get("confidence") == "low_confidence"]
    low_conf_count = len(low_conf_risks)
    has_coverage_gaps = has_ac_gaps or has_req_gaps

    uncovered_files = check_uncovered_scopes(affected_files, task_list)
    uncovered_scope_count = len(uncovered_files)

    lines = [
        "",
        "═══════════════════════════════════════════════════════════════",
        "  VT 架构自省 — 元认知反思提示 (Meta-Cognitive Reflection)",
        "═══════════════════════════════════════════════════════════════",
        "",
        "请基于本轮 vt analyze 的结果，对以下 8 个维度进行反思与优化：",
        "",
    ]

    for dim in dimensions:
        idx = dim["index"]
        title = dim["title"]
        prompt = dim["prompt"]

        # Resolve the first matching conditional hint
        hint_text = ""
        for hint in dim.get("conditional_hints", []):
            if _evaluate_condition(
                hint["condition"],
                has_blocked=has_blocked,
                has_fail=has_fail,
                has_must_risks=has_must_risks,
                gap_count=gap_count,
                risk_count=risk_count,
                low_conf_count=low_conf_count,
                has_coverage_gaps=has_coverage_gaps,
                unclear_count=unclear_count,
                violation_count=violation_count,
                uncovered_scope_count=uncovered_scope_count,
            ):
                hint_text = hint["text"]
                # Format template placeholders in hint text
                hint_text = hint_text.format(
                    gap_count=gap_count,
                    risk_count=risk_count,
                    low_conf_count=low_conf_count,
                    unclear_count=unclear_count,
                    violation_count=violation_count,
                    uncovered_count=uncovered_scope_count,
                )
                break

        lines.append(f"  {idx}. {title}")
        lines.append(f"     {prompt}{hint_text}")
        lines.append("")

    # Append uncovered-scope governance warning if applicable
    if uncovered_files:
        lines.append("⚠ 治理覆盖警告 (Coverage Warning)")
        lines.append("以下反思诊断涉及的文件未被任何 Task/AC 覆盖：")
        for f in uncovered_files:
            lines.append(f"  - {f}")
        lines.append("请在 docs/task_list.json 中补充对应 Task，并关联 REQ/AC。")
        lines.append("")

    lines.extend([
        "═══════════════════════════════════════════════════════════════",
        "",
    ])

    return "\n".join(lines)
