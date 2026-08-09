"""Business impact resolver — 双层查找：项目覆写 > field_hints 默认 > 'high' 兜底。

基于 docs/design/phase_channel_separation.md §2.3.2 / §3.3.4 / §3.3.5。

查找优先级：
    1. 项目覆写 .vibetracing/business_impacts.json
        a. 精确匹配 issue_type:subtype（如 'task_failed:test_failed'）
        b. 回退到 issue_type（如 'no_claim'）
    2. 系统默认 src/vibe_tracing/templates/field_hints.json
       的 issue_type_impacts[issue_type].business_impact
    3. 兜底 'high'（不确定默认有业务影响）

项目覆写文件由人类（业务方 / Agent）维护，VT 仅校验 JSON 格式；
格式损坏时 warning 并降级到 field_hints 默认。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from vibe_tracing.infra.config.hint_loader import load_hints
from vibe_tracing.infra.logging.logger import OperationalLogger

_VALID_IMPACTS = {"high", "low", "none"}


class BusinessImpactResolver:
    """判定 issue 的业务影响级别。

    构造时加载两个数据源；resolve() 按优先级查找。
    """

    def __init__(self, project_root: Path) -> None:
        self._project_root = Path(project_root)
        self._overrides: Dict[str, str] = self._load_overrides()
        self._defaults: Dict[str, str] = self._load_defaults()

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def resolve(self, issue_type: str, subtype: Optional[str] = None) -> str:
        """返回 'high' | 'low' | 'none'。

        Args:
            issue_type: 六类 issue 之一（如 'no_claim'）。
            subtype: 可选子分类（如 'coverage'、'test_failed'、'GATE-VT-006'）。
        """
        # 1a. 精确匹配 issue_type:subtype
        if subtype:
            compound = f"{issue_type}:{subtype}"
            value = self._overrides.get(compound)
            if value is not None:
                return value

        # 1b. 回退 issue_type
        value = self._overrides.get(issue_type)
        if value is not None:
            return value

        # 2. field_hints 默认
        value = self._defaults.get(issue_type)
        if value is not None:
            return value

        # 3. 兜底
        return "high"

    # ------------------------------------------------------------------ #
    # 加载
    # ------------------------------------------------------------------ #
    def _load_overrides(self) -> Dict[str, str]:
        path = self._project_root / ".vibetracing" / "business_impacts.json"
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            OperationalLogger.get().warning(
                "business_impacts_parse_failed",
                f"business_impacts.json 格式损坏，降级到 field_hints 默认：{path}",
                path=str(path),
            )
            return {}

        overrides = data.get("overrides", {})
        if not isinstance(overrides, dict):
            OperationalLogger.get().warning(
                "business_impacts_invalid_shape",
                "business_impacts.json 缺少 overrides 字典，降级到 field_hints 默认",
                path=str(path),
            )
            return {}

        cleaned: Dict[str, str] = {}
        for key, impact in overrides.items():
            if isinstance(impact, str) and impact in _VALID_IMPACTS:
                cleaned[str(key)] = impact
        return cleaned

    def _load_defaults(self) -> Dict[str, str]:
        """从 field_hints.json 的 issue_type_impacts 节加载默认 business_impact。"""
        section: Dict[str, Any] = load_hints("issue_type_impacts")
        defaults: Dict[str, str] = {}
        for issue_type, entry in section.items():
            if issue_type.startswith("_"):
                continue
            if isinstance(entry, dict):
                impact = entry.get("business_impact")
            else:
                impact = entry
            if isinstance(impact, str) and impact in _VALID_IMPACTS:
                defaults[issue_type] = impact
        return defaults
