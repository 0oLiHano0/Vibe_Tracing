"""
Baseline 快照机制 — observed 信号的数据来源。

Baseline 是 VT 首次接管项目时生成的一次性认知快照，
记录当时系统能发现的所有 issue fingerprint。不滚动更新。

design_historical_debt_mechanism.md §3.1 认知约束。
"""

import hashlib
import json
from pathlib import Path
from typing import List


def compute_fingerprint(issue_type: str, gap_targets: List[str]) -> str:
    """计算 issue fingerprint。纯函数，确定性。

    算法：sha256(issue_type + ':' + '|'.join(sorted(gap_targets)))[:16]
    """
    raw = f"{issue_type}:{'|'.join(sorted(gap_targets))}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class BaselineManager:
    """管理 Baseline 快照的生命周期和查询。"""

    def __init__(self, project_root: Path) -> None:
        self._baseline_path = project_root / ".vibetracing" / "baseline.json"
        self._fingerprints: set = set()
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self._baseline_path.exists():
            try:
                data = json.loads(self._baseline_path.read_text(encoding="utf-8"))
                self._fingerprints = set(data.get("fingerprints", []))
            except (json.JSONDecodeError, OSError):
                self._fingerprints = set()
        self._loaded = True

    def generate_snapshot(self, fingerprints: List[str]) -> bool:
        """首次调用创建快照，二次调用不覆盖。返回是否成功创建。"""
        if self._baseline_path.exists():
            self._ensure_loaded()
            return False

        self._baseline_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "fingerprints": list(set(fingerprints)),
        }
        self._baseline_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._fingerprints = set(data["fingerprints"])
        self._loaded = True
        return True

    def is_observed(self, fingerprint: str) -> bool:
        """查询 fingerprint 是否存在于 Baseline 快照中。"""
        self._ensure_loaded()
        return fingerprint in self._fingerprints
