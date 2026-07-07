"""5 分类验收链条模型 — issue_counts key → 验收节点映射。

人类验收一条 task 的思维路径：
  1. 链路完整性 — PRD→Task→Claim 链完整吗？
  2. 交付凭证   — 代码写了吗？Claim 声明了吗？
  3. 证据验证   — 测试跑过了吗？结果可信吗？
  4. 交付质量   — 覆盖率/lint/架构约束达标吗？
  5. 过程合规   — 架构变更有提案吗？约束清晰吗？

基于 docs/design/phase_channel_separation.md 业务规范。
"""

from __future__ import annotations

from typing import Dict, List

CATEGORY_CHAIN_INTEGRITY = "链路完整性"
CATEGORY_DELIVERY_PROOF = "交付凭证"
CATEGORY_EVIDENCE_VERIFICATION = "证据验证"
CATEGORY_DELIVERY_QUALITY = "交付质量"
CATEGORY_PROCESS_COMPLIANCE = "过程合规"

CATEGORIES: List[Dict[str, str]] = [
    {"id": CATEGORY_CHAIN_INTEGRITY,       "gate": "BLOCK",   "description": "PRD→Task→Claim 链路是否完整"},
    {"id": CATEGORY_DELIVERY_PROOF,        "gate": "BLOCK",   "description": "代码是否交付并声明"},
    {"id": CATEGORY_EVIDENCE_VERIFICATION, "gate": "BLOCK",   "description": "测试证据是否合格"},
    {"id": CATEGORY_DELIVERY_QUALITY,      "gate": "WARNING", "description": "覆盖率/lint/架构约束是否达标"},
    {"id": CATEGORY_PROCESS_COMPLIANCE,    "gate": "WARNING", "description": "架构变更治理是否合规"},
]

_CATEGORY_IDS = [c["id"] for c in CATEGORIES]


def categorize(issue_counts_key: str) -> str:
    """将 issue_counts key 映射到 5 分类之一。"""
    issue_type = issue_counts_key.split(":")[0]

    if issue_type == "no_claim":
        return CATEGORY_DELIVERY_PROOF
    if issue_type == "task_failed":
        return CATEGORY_EVIDENCE_VERIFICATION
    if issue_type == "isolated_task":
        return CATEGORY_CHAIN_INTEGRITY
    if issue_type == "chain_misaligned":
        return CATEGORY_CHAIN_INTEGRITY

    if issue_type == "chain_broken":
        if ":proposal" in issue_counts_key:
            return CATEGORY_PROCESS_COMPLIANCE
        if ":GATE-VT-" in issue_counts_key:
            return CATEGORY_DELIVERY_QUALITY
        if ":RISK-VT-" in issue_counts_key:
            return CATEGORY_PROCESS_COMPLIANCE
        return CATEGORY_CHAIN_INTEGRITY

    if issue_type == "substandard":
        if ":unclear" in issue_counts_key:
            return CATEGORY_PROCESS_COMPLIANCE
        return CATEGORY_DELIVERY_QUALITY

    return CATEGORY_CHAIN_INTEGRITY
