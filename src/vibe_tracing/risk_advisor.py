"""
Risk and Suggested Action Advisor for Vibe Tracing.

Generates structured risks and suggested remediation actions from gaps,
claim inconsistencies, and architecture compliance results.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from vibe_tracing.core import ids
from vibe_tracing.hint_loader import load_hints, resolve_hint

_risk_hints = load_hints("risk")


class RiskAdvisor:
    """Systematically evaluates project facts and generates human-readable risk logs."""

    def __init__(self, project_root: Path) -> None:
        """Initialize the advisor with project root."""
        self.project_root = project_root

    def generate_risks(
        self,
        gaps: List[Dict[str, Any]],
        claims_analysis: List[Dict[str, Any]],
        claim_risks: List[Dict[str, Any]],
        compliance_result: Optional[Dict[str, Any]] = None,
        claims_list: Optional[List[Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Evaluate project gaps, claims, and architecture status to build enriched risks.

        Args:
            gaps: Identified gaps from coverage.
            claims_analysis: Checked claims analysis results.
            claim_risks: Existing risks identified by the ClaimEvidenceAnalyzer.
            compliance_result: Optional output from ArchitectureComplianceChecker.check.
            claims_list: Deprecated. No longer used (credibility check removed).

        Returns:
            A list of unified risk dictionaries conforming to the report schema.
        """
        enriched_risks: List[Dict[str, Any]] = []

        # 1. Enrich existing claim-based risks
        for orig_risk in claim_risks:
            r = dict(orig_risk)  # copy to avoid mutability side-effects

            # Default values
            default_hint = _risk_hints.get("default_inconsistency", {})
            impact = resolve_hint(default_hint, "level1") if default_hint else "该不一致可能表明开发状态与证据事实存在冲突，影响门禁评级。"
            action = "请核对该 Agent Claim 的内容以及外部证据记录，修正不一致的字段。"
            evidence_ids: list[str] = []

            # Match on structured risk_category (set by ClaimEvidenceAnalyzer)
            # Falls back to defaults if category is absent or unrecognised.
            category = r.get("risk_category", "")

            if category == "self_referential_claim":
                hint = _risk_hints.get("self_referential_claim", {})
                impact = resolve_hint(hint, "level1") if hint else "违反 Agent 不能自证原则，可能掩盖未经外部工具或人类审查的低质量代码。"
                action = "为关联的开发任务提供独立的外部证据，例如单元测试或人类 Review 记录，并在 Claim 的 `evidence_refs` 中引用该证据 ID。"
            elif category == "non_existent_evidence":
                hint = _risk_hints.get("non_existent_evidence", {})
                impact = resolve_hint(hint, "level1") if hint else "证据链中断，导致声称的完成状态无法被客观核查。"
                action = "核对 `evidence_index.json` 或工具报告输出，确保被引用的证据项已正确生成并包含在索引中。"
            elif category == "stale_file":
                hint = _risk_hints.get("stale_file", {})
                impact = resolve_hint(hint, "level1") if hint else "文件在此次 Claim 签发后发生了修改，声称的覆盖状态已失效，属于推测性风险。"
                action = "重新验证该任务以生成包含最新时间戳的 Agent Claim 记录。"
                r["confidence"] = "low_confidence"
                r["type"] = "suggestion"
            elif category == "non_existent_task":
                hint = _risk_hints.get("non_existent_task", {})
                impact = resolve_hint(hint, "level1") if hint else "Claim 关联到了不存在的任务，可能由于任务 ID 写错或任务列表未同步。"
                action = "检查该 Claim 的 `related_task` 字段是否与 `task_list.json` 中的任务 ID 一致。"
            elif category == "no_test_coverage":
                hint = _risk_hints.get("no_test_coverage", {})
                impact = resolve_hint(hint, "level1") if hint else "关联的验收标准没有通过测试或测试执行失败，导致无法提供客观的合格证明。"
                action = "针对该验收标准补充测试用例，并在测试函数的 docstring 中声明 `covers: <ac_id>`。"
            elif category in ("failed_tests", "violated_evidence"):
                hint = _risk_hints.get("failed_tests", {})
                impact = resolve_hint(hint, "level1") if hint else "关联的验收标准测试执行失败，导致无法提供合格证明。"
                action = "运行并修复该验收标准关联的失败测试用例。"

            r["business_impact"] = r.get("business_impact", impact)
            r["suggested_action"] = r.get("suggested_action", action)
            if "evidence_ids" not in r:
                r["evidence_ids"] = evidence_ids

            enriched_risks.append(r)

        # 2. Determine starting counter for new risks
        existing_nums = []
        for r in enriched_risks:
            r_id = r.get("risk_id", "")
            if r_id.startswith(f"RISK-{ids.get_project_prefix()}-"):
                try:
                    num = int(r_id.split("-")[-1])
                    existing_nums.append(num)
                except ValueError:
                    pass
        next_counter = max(existing_nums) + 1 if existing_nums else 1

        # 3. Process Gaps into Risks
        for gap in gaps:
            item_id = gap.get("item_id", "")
            item_type = gap.get("item_type", "")
            reason = gap.get("reason", "")

            if item_type == "requirement":
                hint = _risk_hints.get("requirement_no_task", {})
                desc = f"需求 {item_id} 缺少关联的开发任务。"
                impact = resolve_hint(hint, "level1").format(item_id=item_id) if hint else "需求没有对应的开发任务覆盖，可能导致功能遗漏或开发偏离方向。"
                action = f"在 `task_list.json` 中为需求 `{item_id}` 规划并关联开发任务。"
                enriched_risks.append(
                    {
                        "risk_id": ids.make_risk_id(next_counter),
                        "description": desc,
                        "severity": "must",
                        "business_impact": impact,
                        "suggested_action": action,
                        "evidence_ids": [ids.sentinel_evidence_id()],
                    }
                )
                next_counter += 1
            elif item_type == "ac":
                hint = _risk_hints.get("ac_no_evidence", {})
                desc = f"验收标准 {item_id} 缺失通过的测试证据。"
                impact = resolve_hint(hint, "level1").format(item_id=item_id) if hint else "验收标准缺失测试证据，无法静态或动态证明该标准已被合规实现。"
                action = f"针对验收标准 `{item_id}` 补充测试用例，并在测试函数的 docstring 中声明 `covers: {item_id}`。"
                enriched_risks.append(
                    {
                        "risk_id": ids.make_risk_id(next_counter),
                        "description": desc,
                        "severity": "must",
                        "business_impact": impact,
                        "suggested_action": action,
                        "evidence_ids": [ids.sentinel_evidence_id()],
                    }
                )
                next_counter += 1
            elif item_type == "task":
                hint = _risk_hints.get("task_no_claim", {})
                desc = f"任务 {item_id} 缺少 Agent Claim 声明或状态不完整。"
                impact = resolve_hint(hint, "level1").format(item_id=item_id) if hint else "任务已规划但缺乏执行实体的状态声明，影响合并门禁判定。"
                action = f"为任务 `{item_id}` 签发相应的 Agent Claim 并记录其完成状态和关联证据。"
                enriched_risks.append(
                    {
                        "risk_id": ids.make_risk_id(next_counter),
                        "description": desc,
                        "severity": "should",
                        "business_impact": impact,
                        "suggested_action": action,
                        "evidence_ids": [ids.sentinel_evidence_id()],
                    }
                )
                next_counter += 1

        # 4. Process Architecture Compliance Results into Risks
        if compliance_result:
            # Add violations (must severity)
            for v in compliance_result.get("architecture_violations", []):
                rule_id = v.get("rule_id", "GATE-VT-006")
                msg = v.get("message", "")

                # Deduplicate if we somehow already have a violation for this rule_id
                if any(
                    r.get("description", "").startswith(
                        f"架构约束违反 (规则 {rule_id})"
                    )
                    for r in enriched_risks
                ):
                    continue

                hint = _risk_hints.get("arch_violation", {})
                desc = f"架构约束违反 (规则 {rule_id}): {msg}"
                impact = resolve_hint(hint, "level1").format(rule_id=rule_id, msg=msg) if hint else "破坏了既定的架构约束与模块隔离边界，可能导致非预期依赖或代码架构混乱。"
                action = f"根据规则 `{rule_id}` 的定义，重构相关文件以移除禁用的依赖或外部资源引用。"
                enriched_risks.append(
                    {
                        "risk_id": ids.make_risk_id(next_counter),
                        "description": desc,
                        "severity": "must",
                        "business_impact": impact,
                        "suggested_action": action,
                        "evidence_ids": [v.get("evidence_id", ids.sentinel_evidence_id())],
                    }
                )
                next_counter += 1

            # Add unclear constraints (should severity, speculative)
            for uc in compliance_result.get("unclear_constraints", []):
                rule_id = uc.get("rule_id", "")
                reason = uc.get("reason", "")

                hint = _risk_hints.get("unclear_constraint", {})
                desc = f"架构约束 {rule_id} 状态不明确：{reason}"
                impact = resolve_hint(hint, "level1").format(rule_id=rule_id, reason=reason) if hint else "该架构约束无法由机器自动核对，存在未知的合规性隐患，可能需要人工审计。"
                action = f"由架构师或人类项目经理对约束 `{rule_id}` 进行人工核对，并在 Review 流程中确认合规。"
                enriched_risks.append(
                    {
                        "risk_id": ids.make_risk_id(next_counter),
                        "description": desc,
                        "severity": "should",
                        "business_impact": impact,
                        "suggested_action": action,
                        "evidence_ids": [ids.sentinel_evidence_id()],
                        "confidence": "low_confidence",
                        "type": "suggestion",
                    }
                )
                next_counter += 1

        return enriched_risks
