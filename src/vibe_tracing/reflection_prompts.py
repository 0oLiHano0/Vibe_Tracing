"""
Post-analyze reflection prompts for AI Agent self-improvement.

These prompts are printed at the end of every vt analyze run (non gates-only)
to trigger meta-cognitive reflection in the AI Agent, promoting architectural
self-awareness and continuous project evolution.
"""

from typing import Any, Dict, List, Optional


def render_reflection_prompts(
    gate_decision: str,
    gaps: List[Dict[str, Any]],
    risks: List[Dict[str, Any]],
    compliance_result: Optional[Dict[str, Any]] = None,
) -> str:
    """Render the 8-dimension reflection prompt block.

    Args:
        gate_decision: The final gate decision string.
        gaps: Identified gaps from analyzers.
        risks: Enriched risks from RiskAdvisor.
        compliance_result: Result from ArchitectureComplianceChecker.

    Returns:
        Formatted reflection prompt string for console output.
    """
    # Gather context for conditional prompts
    has_blocked = gate_decision == "blocked"
    has_fail = gate_decision == "fail"
    has_ac_gaps = any(g.get("item_type") == "ac" for g in gaps)
    has_req_gaps = any(g.get("item_type") == "requirement" for g in gaps)
    has_must_risks = any(r.get("severity") == "must" for r in risks)
    has_unclear = bool(compliance_result and compliance_result.get("unclear_constraints"))
    violation_count = len(compliance_result.get("architecture_violations", [])) if compliance_result else 0
    risk_count = len(risks)
    gap_count = len(gaps)

    lines = [
        "",
        "═══════════════════════════════════════════════════════════════",
        "  VT 架构自省 — 元认知反思提示 (Meta-Cognitive Reflection)",
        "═══════════════════════════════════════════════════════════════",
        "",
        "请基于本轮 vt analyze 的结果，对以下 8 个维度进行反思与优化：",
        "",
    ]

    # 1. Deficiencies
    deficiency_hint = ""
    if has_blocked:
        deficiency_hint = "（本轮 Gate 为 BLOCKED，需识别阻断根因）"
    elif has_fail:
        deficiency_hint = "（本轮 Gate 为 FAIL，需识别条件性缺陷）"
    lines.extend([
        "  1. 项目不足识别 (Deficiencies)",
        f"     本轮自管理暴露了项目哪些设计或功能缺陷？{deficiency_hint}",
        "",
    ])

    # 2. Simplicity
    lines.extend([
        "  2. 架构精简度评估 (Simplicity)",
        "     项目架构是否符合剃刀原则与第一性原理？是否存在过度工程？",
        "",
    ])

    # 3. Root-Cause Fix
    root_hint = ""
    if has_must_risks:
        root_hint = "（本轮存在 must 级风险，确认是否直击物理根因）"
    lines.extend([
        "  3. 彻底根因修复验证 (Root-Cause Fix)",
        f"     本轮修改是直击物理根因，还是引进了打补丁式的短路代码？{root_hint}",
        "",
    ])

    # 4. Redundancy
    redundancy_hint = ""
    if gap_count > 5 or risk_count > 10:
        redundancy_hint = f"（本轮 {gap_count} gaps + {risk_count} risks，检查是否存在冗余数据流转）"
    lines.extend([
        "  4. 计算与逻辑冗余 (Redundancy)",
        f"     是否存在重复 I/O、二次反序列化或冗余数据流转？{redundancy_hint}",
        "",
    ])

    # 5. Credibility
    cred_hint = ""
    low_conf_risks = [r for r in risks if r.get("confidence") == "low_confidence"]
    if low_conf_risks:
        cred_hint = f"（本轮存在 {len(low_conf_risks)} 个低可信度风险）"
    lines.extend([
        "  5. 凭证真实性 (Credibility)",
        f"     测试用例是否存在过度 Mock？凭证是否真实触达物理逻辑？{cred_hint}",
        "",
    ])

    # 6. Cognitive Complexity
    lines.extend([
        "  6. 代码认知复杂度 (Cognitive Complexity)",
        "     新增代码是否推高了认知复杂度？是否会阻碍下一轮 Agent 的上下文推理？",
        "",
    ])

    # 7. Exception & Bypass
    bypass_hint = ""
    if has_ac_gaps or has_req_gaps:
        bypass_hint = "（本轮存在覆盖缺口，确认是否存在绕过机制）"
    lines.extend([
        "  7. 豁免与绕过机制 (Exception & Bypass)",
        f"     是否使用了忽略规则或临时白名单绕过门禁？能否通过重构彻底消除？{bypass_hint}",
        "",
    ])

    # 8. Dead Code
    dead_hint = ""
    if has_unclear:
        dead_hint = f"（本轮 {len(compliance_result.get('unclear_constraints', []))} 条模糊约束，检查是否存在死代码或失效规则）"
    elif violation_count > 0:
        dead_hint = f"（本轮 {violation_count} 条架构违规，检查是否存在未清理的废弃代码）"
    lines.extend([
        "  8. 残留与死代码清理 (Dead Code)",
        f"     代码库中是否存在已被废弃的类、模板文件或失效测试未被完全清理？{dead_hint}",
        "",
    ])

    lines.extend([
        "═══════════════════════════════════════════════════════════════",
        "",
    ])

    return "\n".join(lines)
