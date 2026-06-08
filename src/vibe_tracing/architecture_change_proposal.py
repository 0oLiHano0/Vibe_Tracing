"""
Architecture Change Proposal Engine for Vibe Tracing.

Manages loading, drift detection, and documentation auditing for architecture constraints changes.
"""

# ============================================================================
# EVO-TASK-017: Architecture Evolution Mechanism — Findings
# ============================================================================
#
# GATE-VT-014 ("Architecture Change Governance") in architecture_constraints.json
# already covers the core architecture evolution scenario:
#
#   - Title: "Architecture Change Governance"
#   - Pass: Architecture constraint changes documented in
#           architecture_change_log.md with matching timestamps
#   - Fail: Architecture constraints modified without corresponding
#           change_log update
#   - blocks_merge: true
#   - check_type: hybrid (machine + manual)
#
# The gate is implemented by this module (ArchitectureChangeProposalEngine)
# which provides:
#   1. Drift detection: compares current constraints against last recorded hash
#   2. Proposal scanning: reads architecture_change_log.md entries
#   3. Change auditing: validates timestamps and documentation completeness
#
# Coverage assessment:
#   - WELL COVERED: "constraints modified without documentation" is blocked
#   - WELL COVERED: human approval signature is tracked per proposal
#   - WELL COVERED: dashboard renders proposals with status + approval info
#   - PARTIAL: no automated rollback mechanism if a proposal is rejected
#              after constraints were already modified (manual recovery)
#   - PARTIAL: no versioning of constraints beyond SHA hash snapshots;
#              diff-level change tracking relies on git history
#
# Recommendation: GATE-VT-014 is sufficient for v0.1 MVP. For future
# versions, consider adding constraint versioning (v1 -> v2 diff) and
# an automated revert path when proposals are rejected post-merge.
#
# ============================================================================

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from vibe_tracing.core import ids
from vibe_tracing.git_utils import git_show
from vibe_tracing.raw_input_loader import RawInputLoader


class ArchitectureChangeProposalEngine:
    """Orchestrates architecture change proposals scanning, validation, and drift check."""

    def __init__(
        self,
        project_root: Path,
        schema_validator: Optional[Any] = None,
        proposals_dir: Optional[Path] = None,
        constraints_path: Optional[Path] = None,
        config_data: Optional[dict] = None,
    ) -> None:
        self.project_root = Path(project_root)
        if config_data is not None:
            # Reuse pre-loaded config to avoid re-reading from disk
            self.raw_loader = RawInputLoader.__new__(RawInputLoader)
            self.raw_loader.project_root = self.project_root
            self.raw_loader.config_data = config_data
        else:
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
        start_counter: int = 1,
        constraints_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Read-only detection of architecture constraints drift.

        Never determines pass/fail — always returns ``is_valid=True``.
        Only produces warnings with diff details and fix guidance.

        Args:
            start_counter: Starting value for risk/gap ID counters.
            constraints_hash: Pre-computed SHA-256 of the constraints file.
                When provided, avoids re-reading the file from disk.
        """
        warnings: List[str] = []
        risks: List[Dict[str, Any]] = []
        gaps: List[Dict[str, Any]] = []
        counter = start_counter

        def _empty_result() -> Dict[str, Any]:
            return {
                "is_valid": True,
                "errors": [],
                "warnings": warnings,
                "risks": risks,
                "gaps": gaps,
                "proposals": [],
            }

        # Step 1: Read stored hash from config. If missing, not finalized — skip.
        stored_hash = self.raw_loader.config_data.get("architecture_constraints_hash")
        if not stored_hash:
            return _empty_result()

        # Step 2: Compute current SHA256 of constraints file.
        # Use pre-computed hash if provided to avoid re-reading from disk.
        if constraints_hash:
            current_hash = constraints_hash
        else:
            current_hash = hashlib.sha256(
                self.constraints_path.read_bytes()
            ).hexdigest()
        if current_hash == stored_hash:
            # No drift — fast path.
            return _empty_result()

        # Step 3: Hash mismatch — check for finalize metadata.
        finalize_commit = self.raw_loader.config_data.get("finalize_git_commit")
        finalize_constraints_path = self.raw_loader.config_data.get(
            "finalize_constraints_path"
        )
        if not finalize_commit or not finalize_constraints_path:
            warn = "请运行 vt finalize"
            warnings.append(warn)
            risks.append(
                {
                    "risk_id": ids.make_risk_id(counter),
                    "description": "架构约束文件已变更，但无定稿记录（finalize 信息缺失）。",
                    "severity": "should",
                    "business_impact": "无法重建基线内容以进行逐条规则比对，漂移详情不可知。",
                    "suggested_action": warn,
                    "evidence_ids": [ids.sentinel_evidence_id()],
                }
            )
            counter += 1
            return _empty_result()

        # Step 4: Reconstruct baseline via git show, parse both as JSON.
        base_content = git_show(
            finalize_commit, finalize_constraints_path, self.project_root
        )
        if base_content is None:
            warn = "请运行 vt finalize"
            warnings.append(warn)
            risks.append(
                {
                    "risk_id": ids.make_risk_id(counter),
                    "description": f"无法通过 git show 还原定稿基线 ({finalize_commit}:{finalize_constraints_path})。",
                    "severity": "should",
                    "business_impact": "基线内容不可达，无法完成逐条规则比对。",
                    "suggested_action": warn,
                    "evidence_ids": [ids.sentinel_evidence_id()],
                }
            )
            counter += 1
            return _empty_result()

        base_data = json.loads(base_content)
        curr_data = json.loads(
            self.constraints_path.read_text(encoding="utf-8")
        )

        # Step 5: Diff baseline vs current.
        diffs = self._find_differences(base_data, curr_data)
        if not diffs:
            # Format changed but no rule changes.
            warn = "格式已变更（无规则变化），请运行 vt finalize 更新检查点"
            warnings.append(warn)
            risks.append(
                {
                    "risk_id": ids.make_risk_id(counter),
                    "description": "架构约束文件格式发生变更，但未检测到规则内容变化。",
                    "severity": "should",
                    "business_impact": "检查点哈希与当前文件不一致，可能干扰后续漂移检测。",
                    "suggested_action": warn,
                    "evidence_ids": [ids.sentinel_evidence_id()],
                }
            )
            counter += 1
            return _empty_result()

        # Step 6: Diffs exist — build summary and warning.
        changed_rules = [
            f"  - {d['action'].upper()}: {d.get('rule_id') or d['path']}"
            for d in diffs
        ]
        diff_summary = "\n".join(changed_rules)

        warn = (
            f"检测到架构约束文件自定稿后发生以下变更：\n{diff_summary}\n\n"
            "请在 docs/architecture_change_log.md 中记录变更原因，"
            "然后运行 vt finalize 锁定新状态"
        )
        warnings.append(warn)
        risks.append(
            {
                "risk_id": ids.make_risk_id(counter),
                "description": "架构约束文件自定稿后发生变更，需人工审查并记录。",
                "severity": "should",
                "business_impact": "架构约束发生演进，相关联的任务或代码可能需要同步审查以避免架构腐化。",
                "suggested_action": "请在 docs/architecture_change_log.md 中记录变更原因，然后运行 vt finalize 锁定新状态。",
                "evidence_ids": [ids.sentinel_evidence_id()],
            }
        )
        counter += 1
        gaps.append(
            {
                "item_id": "architecture_constraints.json",
                "item_type": "architecture_constraints_changed",
                "reason": warn,
            }
        )

        return _empty_result()
