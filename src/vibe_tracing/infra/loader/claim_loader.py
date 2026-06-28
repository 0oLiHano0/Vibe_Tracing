"""
Agent Claim 加载器与校验器。

从已解析的 list 加载 claim 数据。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Claim:
    """从 claim 列表中解析出的单个 Agent Claim 数据对象。"""

    claim_id: str
    related_task: str
    code_refs: List[str] = field(default_factory=list)
    test_refs: List[str] = field(default_factory=list)
    notes: str = ""
    timestamp: str = ""


@dataclass
class ClaimListLoadResult:
    """加载 agent claims 后的结果容器。"""

    claims: List[Claim] = field(default_factory=list)


class ClaimLoader:
    """加载并反序列化 agent claims。"""

    def deserialize(
        self,
        data: List[Dict[str, Any]],
    ) -> ClaimListLoadResult:
        """反序列化 agent claims 数据为结构化对象。"""
        parsed_claims: List[Claim] = []

        for claim_dict in data:
            claim_id = claim_dict.get("claim_id", "")
            related_task = claim_dict.get("related_task", "")
            code_refs = claim_dict.get("code_refs", [])
            test_refs = claim_dict.get("test_refs", [])
            notes = claim_dict.get("notes", "")
            timestamp = claim_dict.get("timestamp", "")

            claim_obj = Claim(
                claim_id=claim_id,
                related_task=related_task,
                code_refs=list(code_refs),
                test_refs=list(test_refs),
                notes=notes,
                timestamp=timestamp,
            )

            parsed_claims.append(claim_obj)

        return ClaimListLoadResult(claims=parsed_claims)
