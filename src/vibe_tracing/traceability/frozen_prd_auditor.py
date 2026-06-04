"""
Frozen PRD drift auditor for Vibe Tracing.

Detects drift between a frozen PRD baseline and the current PRD.
"""

from pathlib import Path
from typing import Any, List

from vibe_tracing.core import ids


class FrozenPrdAuditor:
    """Checks for PRD drift when status is frozen."""

    def __init__(self, project_root: Path, prd_parser: Any):
        self.project_root = project_root
        self.prd_parser = prd_parser

    def audit(self, prd_status: str, prd_requirements: list) -> List[dict]:
        """Return list of risk dicts for frozen PRD drift. Empty if not frozen."""
        if prd_status != "frozen":
            return []

        frozen_risks: List[dict] = []
        baseline_path = self.project_root / ".vibetracing/prd.base.md"

        if not baseline_path.exists():
            frozen_risks.append({
                "risk_id": ids.make_risk_id(901),
                "description": "项目 PRD 处于 frozen 状态，但缺少基准 PRD 文件 .vibetracing/prd.base.md。",
                "severity": "must",
                "business_impact": "无法对已定稿需求进行防漂移审计，存在未经授权或未记录变更的风险。",
                "suggested_action": "请在 .vibetracing/ 目录下创建 prd.base.md 作为基准需求文件。",
                "evidence_ids": [ids.sentinel_evidence_id()]
            })
            return frozen_risks

        baseline_res = self.prd_parser.parse_file(baseline_path)
        if not baseline_res.is_valid:
            frozen_risks.append({
                "risk_id": ids.make_risk_id(902),
                "description": f"基准 PRD 文件解析失败: {'; '.join(baseline_res.errors)}",
                "severity": "must",
                "business_impact": "基准 PRD 格式不合规，导致无法正常进行防漂移审计。",
                "suggested_action": "请核对并修正 .vibetracing/prd.base.md 文件的格式。",
                "evidence_ids": [ids.sentinel_evidence_id()]
            })
            return frozen_risks

        # Compare baseline and current
        drift_ids = []
        base_reqs = {r.req_id: r for r in baseline_res.requirements}
        curr_reqs = {r.req_id: r for r in prd_requirements}

        for req_id, curr_req in curr_reqs.items():
            if req_id not in base_reqs:
                drift_ids.append(req_id)
                for ac in curr_req.acceptance_criteria:
                    drift_ids.append(ac.ac_id)
            else:
                base_req = base_reqs[req_id]
                if base_req.title != curr_req.title or base_req.priority != curr_req.priority:
                    drift_ids.append(req_id)

                base_acs = {a.ac_id: a for a in base_req.acceptance_criteria}
                curr_acs = {a.ac_id: a for a in curr_req.acceptance_criteria}

                for ac_id, curr_ac in curr_acs.items():
                    if ac_id not in base_acs:
                        drift_ids.append(ac_id)
                    else:
                        base_ac = base_acs[ac_id]
                        if (base_ac.title != curr_ac.title or
                            base_ac.is_testing_required != curr_ac.is_testing_required):
                            drift_ids.append(ac_id)

                for ac_id in base_acs:
                    if ac_id not in curr_acs:
                        drift_ids.append(ac_id)

        for req_id in base_reqs:
            if req_id not in curr_reqs:
                drift_ids.append(req_id)

        drift_ids = sorted(list(set(drift_ids)))

        if drift_ids:
            change_log_path = self.project_root / "docs/architecture_change_log.md"
            log_content = ""
            if change_log_path.exists():
                try:
                    log_content = change_log_path.read_text(encoding="utf-8")
                except Exception:
                    pass

            risk_counter = 910
            for u_id in drift_ids:
                if u_id not in log_content:
                    frozen_risks.append({
                        "risk_id": ids.make_risk_id(risk_counter),
                        "description": f"检测到已定稿的 PRD 需求/验收标准 '{u_id}' 发生变更，但未在 docs/architecture_change_log.md 中进行显式备案。",
                        "severity": "must",
                        "business_impact": "已定稿需求在未经审计记录的情况下发生静默漂移，可能导致实现与业务目标脱节，且无法追溯变更原因。",
                        "suggested_action": f"请在 docs/architecture_change_log.md 中记录 '{u_id}' 的变更说明，或撤销对 docs/prd.md 中该项的修改。",
                        "evidence_ids": [ids.sentinel_evidence_id()]
                    })
                    risk_counter += 1

        return frozen_risks
