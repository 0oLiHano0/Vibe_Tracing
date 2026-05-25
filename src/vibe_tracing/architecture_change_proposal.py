"""
Architecture Change Proposal Engine for Vibe Tracing.

Manages loading, drift detection, and documentation auditing for architecture constraints changes.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from vibe_tracing.raw_input_loader import RawInputLoader


class ArchitectureChangeProposalEngine:
    """Orchestrates architecture change proposals scanning, validation, and drift check."""

    def __init__(
        self,
        project_root: Path,
        schema_validator: Optional[Any] = None,
        proposals_dir: Optional[Path] = None,
        constraints_path: Optional[Path] = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.raw_loader = RawInputLoader(self.project_root)
        self.constraints_path = constraints_path or self.raw_loader.get_path(
            "architecture_constraints"
        )

        # Resolve change log path
        self.change_log_path = self.project_root / "docs/architecture_change_log.md"

    def _compare_lists_by_id(
        self, base_list: list, current_list: list, id_key: str, category_path: str
    ) -> List[Dict[str, Any]]:
        diffs = []
        base_dict = {
            item.get(id_key): item
            for item in base_list
            if isinstance(item, dict) and id_key in item
        }
        current_dict = {
            item.get(id_key): item
            for item in current_list
            if isinstance(item, dict) and id_key in item
        }

        # Check for additions and modifications
        for id_val, curr_item in current_dict.items():
            path_val = f"{category_path}.{id_val}" if category_path else str(id_val)
            if id_val not in base_dict:
                diffs.append(
                    {
                        "path": path_val,
                        "action": "add",
                        "value": curr_item,
                        "rule_id": id_val,
                    }
                )
            else:
                base_item = base_dict[id_val]
                if base_item != curr_item:
                    diffs.append(
                        {
                            "path": path_val,
                            "action": "modify",
                            "value": curr_item,
                            "rule_id": id_val,
                        }
                    )

        # Check for deletions
        for id_val, base_item in base_dict.items():
            path_val = f"{category_path}.{id_val}" if category_path else str(id_val)
            if id_val not in current_dict:
                diffs.append(
                    {
                        "path": path_val,
                        "action": "delete",
                        "value": base_item,
                        "rule_id": id_val,
                    }
                )

        return diffs

    def _find_differences(
        self, base: Any, current: Any, path: str = ""
    ) -> List[Dict[str, Any]]:
        """Recursively find differences between base and current JSON configs."""
        diffs = []
        if isinstance(base, dict) and isinstance(current, dict):
            all_keys = set(base.keys()) | set(current.keys())
            for k in all_keys:
                path_val = f"{path}.{k}" if path else k
                if k not in base:
                    diffs.append(
                        {"path": path_val, "action": "add", "value": current[k]}
                    )
                elif k not in current:
                    diffs.append(
                        {"path": path_val, "action": "delete", "value": base[k]}
                    )
                else:
                    diffs.extend(self._find_differences(base[k], current[k], path_val))
        elif isinstance(base, list) and isinstance(current, list):
            id_key = None
            for key in [
                "rule_id",
                "principle_id",
                "gate_id",
                "module_id",
                "pattern_id",
                "constraint_id",
            ]:
                all_have_key = True
                has_any = False
                for item in base + current:
                    if isinstance(item, dict):
                        if key in item:
                            has_any = True
                        else:
                            all_have_key = False
                            break
                    else:
                        all_have_key = False
                        break
                if all_have_key and has_any:
                    id_key = key
                    break

            if id_key:
                diffs.extend(self._compare_lists_by_id(base, current, id_key, path))
            else:
                if base != current:
                    diffs.append({"path": path, "action": "modify", "value": current})
        else:
            if base != current:
                diffs.append({"path": path, "action": "modify", "value": current})
        return diffs

    def check_governance(
        self,
        baseline_path: Optional[Path] = None,
        start_counter: int = 1,
    ) -> Dict[str, Any]:
        """Check for constraints drift, verify change logs, and report findings."""
        errors: List[str] = []
        warnings: List[str] = []
        risks: List[Dict[str, Any]] = []
        gaps: List[Dict[str, Any]] = []
        counter = start_counter

        # Resolve baseline path
        base_path = baseline_path
        if not base_path:
            paths = self.raw_loader.config_data.get("paths", {})
            if "architecture_constraints_base" in paths:
                base_path = self.project_root / paths["architecture_constraints_base"]
            else:
                base_path = (
                    self.project_root
                    / ".vibetracing/architecture_constraints.base.json"
                )

        if base_path.exists() and self.constraints_path.exists():
            try:
                with base_path.open("r", encoding="utf-8") as f:
                    base_data = json.load(f)
                with self.constraints_path.open("r", encoding="utf-8") as f:
                    curr_data = json.load(f)

                diffs = self._find_differences(base_data, curr_data)

                if diffs:
                    # Load change log
                    log_content = ""
                    log_exists = self.change_log_path.exists()
                    if log_exists:
                        try:
                            log_content = self.change_log_path.read_text(
                                encoding="utf-8"
                            )
                        except Exception:
                            pass

                    for diff in diffs:
                        ch_path = diff["path"]
                        ch_action = diff["action"]
                        # Extract rule ID or path segment
                        rule_id = diff.get("rule_id") or ch_path.split(".")[-1]

                        if not log_exists:
                            err = f"检测到架构约束被修改 ({ch_action} '{ch_path}')，但缺失 docs/architecture_change_log.md 变更日志。"
                            errors.append(err)
                            risks.append(
                                {
                                    "risk_id": f"RISK-VT-{counter:03d}",
                                    "description": err,
                                    "severity": "must",
                                    "business_impact": "违反架构规则修改记录准则，导致约束演进过程无法被审计追溯。",
                                    "suggested_action": "请在 docs/ 目录下创建 architecture_change_log.md 说明该变更合理性，或者撤销对架构文件的修改。",
                                    "evidence_ids": ["EVIDENCE-VT-999"],
                                }
                            )
                            counter += 1
                            gaps.append(
                                {
                                    "item_id": "architecture_constraints.json",
                                    "item_type": "missing_change_log",
                                    "reason": err,
                                }
                            )
                        elif rule_id not in log_content:
                            err = f"检测到架构规则 '{rule_id}' 发生变更 ({ch_action})，但在 docs/architecture_change_log.md 中未找到对应的变更说明。"
                            errors.append(err)
                            risks.append(
                                {
                                    "risk_id": f"RISK-VT-{counter:03d}",
                                    "description": err,
                                    "severity": "must",
                                    "business_impact": "架构变更未经记录与合理化阐述，可能隐藏未审计的技术债或规则降级风险。",
                                    "suggested_action": "请在 docs/architecture_change_log.md 中新增一条记录，阐述修改规则 '{rule_id}' 的原因与影响。",
                                    "evidence_ids": ["EVIDENCE-VT-999"],
                                }
                            )
                            counter += 1
                            gaps.append(
                                {
                                    "item_id": "architecture_constraints.json",
                                    "item_type": "undocumented_change",
                                    "reason": err,
                                }
                            )
                        else:
                            # Rule is change-logged! Approved but warn to show on dashboard
                            warn = f"检测到架构约束中 '{rule_id}' 的合理化变更 ({ch_action}) 已记录在 docs/architecture_change_log.md 中。"
                            warnings.append(warn)
                            risks.append(
                                {
                                    "risk_id": f"RISK-VT-{counter:03d}",
                                    "description": warn,
                                    "severity": "should",
                                    "business_impact": "架构约束发生演进，相关联的任务或代码可能需要同步审查以避免架构腐化。",
                                    "suggested_action": "项目经理应在 Dashboard 中审查此架构演进记录，并核对 docs/architecture_change_log.md 描述。",
                                    "evidence_ids": ["EVIDENCE-VT-999"],
                                }
                            )
                            counter += 1
            except Exception as exc:
                err = f"在进行架构约束漂移/变更比对时发生异常: {exc}"
                errors.append(err)
                risks.append(
                    {
                        "risk_id": f"RISK-VT-{counter:03d}",
                        "description": err,
                        "severity": "must",
                        "business_impact": "漂移校验中断，无法核实最终架构约束是否被静默篡改。",
                        "suggested_action": "请核对 architecture_constraints.json 及其 base 文件的可读性与完整性。",
                        "evidence_ids": ["EVIDENCE-VT-999"],
                    }
                )
                counter += 1

        is_valid = len(errors) == 0
        return {
            "is_valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "risks": risks,
            "gaps": gaps,
            "proposals": [],  # Deprecated list
        }
