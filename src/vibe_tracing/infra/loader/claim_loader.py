"""
Agent Claim 加载器与校验器。

从文件系统加载 claim 文件（CLAIM-*.json 批量模式），
与 task_list 进行交叉引用校验。
"""

import glob as glob_mod
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from vibe_tracing.infra.loader.task_loader import TaskListLoadResult


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
class ClaimGap:
    """claim 列表校验过程中发现的覆盖缺口。"""

    item_id: str
    item_type: str = "claim"
    reason: str = ""


@dataclass
class ClaimListLoadResult:
    """加载和校验 agent claims 后的结果容器。"""

    claims: List[Claim] = field(default_factory=list)
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    gaps: List[ClaimGap] = field(default_factory=list)


class ClaimLoader:
    """加载并校验 agent claims，与 task_list 进行交叉引用校验。"""

    def __init__(self) -> None:
        pass

    def load(
        self,
        claims_path: Path,
        content: Optional[list] = None,
    ) -> ClaimListLoadResult:
        """
        加载 agent claims。

        claims_path 必须是目录（批量模式：加载目录下所有 CLAIM-*.json 文件并合并）。
        """
        if content is not None:
            # 直接使用外部传入的数据（测试或内存模式）
            data = content
            source_label = str(claims_path)
        elif claims_path.is_dir():
            # 批量模式：加载目录下所有 CLAIM-*.json 文件
            data = []
            claim_files = sorted(glob_mod.glob(str(claims_path / "CLAIM-*.json")))
            if not claim_files:
                return ClaimListLoadResult(
                    claims=[],
                    is_valid=False,
                    errors=[f"No CLAIM-*.json files found in {claims_path}"],
                )
            for fp in claim_files:
                p = Path(fp)
                try:
                    with p.open("r", encoding="utf-8") as f:
                        file_data = json.load(f)
                    items = file_data if isinstance(file_data, list) else [file_data]
                    data.extend(items)
                except Exception as exc:
                    return ClaimListLoadResult(
                        claims=[],
                        is_valid=False,
                        errors=[f"Failed to read/parse file {p}: {exc}"],
                    )
            source_label = str(claims_path)
        else:
            return ClaimListLoadResult(
                claims=[],
                is_valid=False,
                errors=[f"claims_path is not a directory: {claims_path}"],
            )

        return self.validate_data(data, source_label=source_label)

    def validate_data(
        self,
        data: List[Dict[str, Any]],
        source_label: str = "",
    ) -> ClaimListLoadResult:
        """
        直接校验 agent claims 数据（用于测试或内存校验场景）。
        """
        parsed_claims: List[Claim] = []
        errors: List[str] = []
        gaps: List[ClaimGap] = []
        is_valid = True

        for claim_dict in data:
            claim_id = claim_dict.get("claim_id", "")

            # 跳过模板记录（以 -9999 结尾的是示例占位，不参与校验）
            if claim_id.endswith("-9999"):
                continue

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

        return ClaimListLoadResult(
            claims=parsed_claims,
            is_valid=is_valid,
            errors=errors,
            gaps=gaps,
        )


