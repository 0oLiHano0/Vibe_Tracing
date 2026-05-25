"""
Claude Code Bootstrap Adapter for Vibe Tracing.

Orchestrates configuration loading and translates validator findings into standardized risks.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from vibe_tracing.claude_bootstrap_validator import ClaudeBootstrapValidator


class ClaudeCodeBootstrapAdapter:
    """Orchestrates Claude Code bootstrap loading and translates validation findings to risks."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.validator = ClaudeBootstrapValidator(self.project_root)
        self._cached_result: Optional[Dict[str, Any]] = None

    def get_validation_result(self) -> Dict[str, Any]:
        """Load and cache the validation result from the validator."""
        if self._cached_result is None:
            self._cached_result = self.validator.validate()
        return self._cached_result

    def check_governance_rules(self, start_counter: int = 1) -> Dict[str, Any]:
        """
        Run checks and return formatted lists of gaps, risks, and compliance status.

        Args:
            start_counter: The starting integer for generating risk IDs.

        Returns:
            A dict with:
                "is_valid": bool
                "errors": list of string errors
                "warnings": list of string warnings
                "risks": list of risk dicts conforming to report schema
                "gaps": list of gap dicts conforming to report schema
        """
        res = self.get_validation_result()
        errors = res.get("errors", [])
        warnings = res.get("warnings", [])

        risks: List[Dict[str, Any]] = []
        gaps: List[Dict[str, Any]] = []
        counter = start_counter

        # Translate errors into MUST severity risks
        for err in errors:
            risks.append(
                {
                    "risk_id": f"RISK-VT-{counter:03d}",
                    "description": err,
                    "severity": "must",
                    "business_impact": "Claude Code 自举配置校验失败或不完整，导致 AI 工作流缺乏可信的审计底座，影响 Merge Gate 决策。",
                    "suggested_action": "请检查 `claude_bootstrap/` 下的配置文件及其与 schemas 的匹配度，修正 JSON Schema 校验错误。",
                    "evidence_ids": ["EVIDENCE-VT-999"],
                }
            )
            counter += 1

            # In addition to risks, let's treat configuration validation errors as gaps in traceability
            gaps.append(
                {
                    "item_id": "CLAUDE-BOOTSTRAP",
                    "item_type": "bootstrap_config",
                    "reason": err,
                }
            )

        # Translate warnings into SHOULD severity risks
        for warn in warnings:
            risks.append(
                {
                    "risk_id": f"RISK-VT-{counter:03d}",
                    "description": warn,
                    "severity": "should",
                    "business_impact": "Subagent 职责与其被授予的 Skill 权限越级（如 Researcher 被赋予 Edit 写入权限），产生提权或非授权变更风险。",
                    "suggested_action": "收敛 Subagent 权限，在定义 JSON 的 `allowed_skills` 中移除敏感权限，或调整其 role 使其职责分明。",
                    "evidence_ids": ["EVIDENCE-VT-999"],
                }
            )
            counter += 1

        is_valid = res.get("is_valid", False) and len(errors) == 0

        return {
            "is_valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "risks": risks,
            "gaps": gaps,
        }
