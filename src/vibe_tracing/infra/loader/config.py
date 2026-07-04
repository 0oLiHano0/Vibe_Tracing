"""配置加载与路径解析。

职责：
- load_config(): 从 .vibetracing/config.json 加载项目配置
- resolve_path(): 根据配置解析文件路径（config 必须包含对应 key）
- REQUIRED_FILES: 必需文件定义（RawInputLoader.load() 从此驱动）

契约：
- load_config(): config.json 不存在时抛出 FileNotFoundError，格式损坏时抛出 ValueError
- resolve_path(): config 缺少 paths 字段或指定 key 时抛出 ValueError

被依赖：
- infra/loader/raw_input.py
- cli/analyze/pipeline.py
- cli/finalize.py
- domain/governance/change_proposal.py
- domain/governance/ghost_code.py
"""

import json
from pathlib import Path
from typing import Any, Dict

# 必需文件定义（RawInputLoader.load() 从此驱动）
REQUIRED_FILES = ("prd", "architecture_constraints")


def load_config(project_root: Path) -> Dict[str, Any]:
    """加载 .vibetracing/config.json 配置文件。

    Raises:
        FileNotFoundError: config.json 不存在
        ValueError: config.json 格式损坏或读取失败
    """
    config_path = project_root / ".vibetracing" / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(
            f"config.json not found at {config_path}. Run 'vibe-tracing init' first."
        )
    try:
        with config_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"config.json format error: {exc}. Run 'vibe-tracing init' to regenerate."
        ) from exc
    except OSError as exc:
        raise ValueError(
            f"config.json read error: {exc}"
        ) from exc


def resolve_path(project_root: Path, config: Dict[str, Any], key: str) -> Path:
    """解析文件路径：从 config.json paths 中读取。

    agent_claims 固定为 .vibetracing/claims/ 目录（VT 规范定义，不受 config 覆盖）。
    其他 key 必须在 config["paths"] 中定义，否则抛出 ValueError。
    """
    if key == "agent_claims":
        return project_root / ".vibetracing" / "claims"

    if "paths" not in config:
        raise ValueError(
            "config.json missing 'paths' field. Run 'vibe-tracing init' to regenerate."
        )

    paths = config["paths"]
    if key not in paths:
        raise ValueError(
            f"Path key '{key}' not found in config.json paths. "
            f"Available keys: {list(paths.keys())}"
        )
    return project_root / paths[key]


_TARGET_SCHEMA = "1.1.0"


def migrate_config(project_root: Path) -> Dict[str, Any]:
    """将 config.json 迁移到当前目标 schema 版本。

    当前迁移：1.0.0 → 1.1.0（补 model 字段）。
    幂等：已是目标版本时不修改文件。
    返回迁移后的 config dict。
    """
    config_path = project_root / ".vibetracing" / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"config.json not found at {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if data.get("schema_version") == _TARGET_SCHEMA:
        return data

    data.setdefault("model", "")
    data["schema_version"] = _TARGET_SCHEMA
    with config_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return data
