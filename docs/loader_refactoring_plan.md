# Loader 包重构计划

> 目标架构与实施步骤。参考：`docs/spec_pipeline_stage_1.md`、`docs/refactoring_design.md`。

---

## 1. 目标架构

### 设计原则

1. **配置解析与文件加载分离**：`load_config()` 和 `resolve_path()` 是独立函数，loader 实例不持有隐式 I/O 能力
2. **manifest 只描述文件加载结果**：不承载调用方自己的数据（如 config）
3. **路径配置唯一权威**：`config.py` 是所有默认路径的单一来源，消除重复定义
4. **零历史债务**：不保留废弃字段、不保留绕过构造函数的 hack

### 模块职责

```
infra/loader/
├── config.py          ← 新增（路径配置唯一权威）
│   ├── load_config(project_root) → dict       # I/O，由 pipeline 显式调用
│   ├── resolve_path(project_root, config, key) → Path  # 纯计算
│   └── REQUIRED_FILES                           # 必需文件定义（从 raw_input.py 迁移）
│
├── raw_input.py       ← 重构
│   ├── InputFileRecord                        # 单文件加载结果
│   ├── RawInputManifest                       # 文件加载结果（不含 config）
│   └── RawInputLoader(project_root, config_data)
│       └── load() → RawInputManifest          # 唯一 I/O 入口
│
├── prd_parser.py      ← 补充中文注释
├── task_loader.py     ← 清理无用 import + 延迟加载
├── claim_loader.py    ← docstring 补充
└── __init__.py        ← 更新导出（含 __all__）
```

### 数据流

```
pipeline._load_context(project_root)
│
├── config = load_config(project_root)          # 显式 I/O
├── loader = RawInputLoader(project_root, config)
├── manifest = loader.load()                    # 显式 I/O
│   manifest 只包含：inputs_used, has_required_errors, error_count
│
├── 从 manifest 读取文件加载结果
├── config 由 pipeline 直接持有，不经 manifest 中转
│
└── ctx = UnifiedContext(config=config, ...)     # 直接用 config
```

### RawInputManifest 结构

```yaml
inputs_used: List[InputFileRecord]   # 所有文件的加载记录
has_required_errors: bool            # 是否有必需文件加载失败
error_count: int                     # 加载失败的文件总数
```

### RawInputLoader 构造函数

```python
def __init__(self, project_root: Path, config_data: dict) -> None:
    """config_data 必须由调用方显式传入（通过 load_config() 获取）。"""
```

### change_proposal.py 解耦

`ArchitectureChangeProposalEngine` 不再依赖 `RawInputLoader`，直接接收 `config_data`：

```python
def __init__(
    self,
    project_root: Path,
    config_data: dict,
    constraints_path: Optional[Path] = None,
    ...
) -> None:
    self.constraints_path = constraints_path or resolve_path(
        project_root, config_data, "architecture_constraints"
    )
```

---

## 2. 修复总览

| 优先级 | 变更 | 涉及文件 |
|--------|------|----------|
| P0 | 删除 `tool_reports` 死字段和扫描逻辑 | raw_input.py, conftest.py, spec |
| P1 | 配置解析从 loader 剥离 + 路径统一 | config.py(新), raw_input.py, pipeline.py, change_proposal.py, finalize.py |
| P1 | 消除所有硬编码路径 | pipeline.py, finalize.py, governance/loader.py, ghost_code.py |
| P1 | 测试文件清理与适配 | conftest.py, test_raw_input_loader.py, test_task_loader.py, test_architecture_change_proposal.py |
| P2 | 中文注释 + docstring | prd_parser.py, claim_loader.py |
| P2 | task_loader 延迟加载 `load_hints` | task_loader.py |

---

## 3. 实施步骤

### 步骤 1：删除 tool_reports 残留 + conftest 清理

> 本步骤的所有变更必须在同一次提交中完成。

**raw_input.py**：
- 删除 `RawInputManifest.tool_report_files` 字段
- 删除 `load()` 中 `.vibetracing/tool_reports/` 扫描逻辑

**tests/conftest.py**：
- 删除 `_patch_loader` fixture（第 9-38 行）——该 fixture 注入已废弃的 `tool_report_files`

**docs/spec_pipeline_stage_1.md**：
- 删除 `tool_report_files: []` 字段说明

```bash
grep -rn "tool_report_files" src/ tests/ docs/spec_pipeline_stage_1.md  # 应返回 0
```

---

### 步骤 2：配置解析从 loader 剥离 + 路径统一

> 本步骤的所有变更必须在同一次提交中完成。

#### 2a. 新增 `src/vibe_tracing/infra/loader/config.py`

路径配置的唯一权威来源。`REQUIRED_FILES` 从 `raw_input.py` 迁移到此处。

```python
"""配置加载与路径解析。

所有文件路径的默认值在此定义。其他模块不得硬编码路径。
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict


# 必需文件定义（RawInputLoader.load() 从此驱动）
REQUIRED_FILES = ("prd",)


# 默认路径映射（resolve_path() 在 config.json 未指定时使用）
_DEFAULT_PATHS: Dict[str, str] = {
    "prd": "docs/prd.md",
    "architecture_constraints": "docs/architecture_constraints.json",
    "task_list": "docs/task_list.json",
    "human_decisions": ".vibetracing/human_decisions.json",
    "output_dir": "output",
}


def load_config(project_root: Path) -> Dict[str, Any]:
    """加载 .vibetracing/config.json。不存在或解析失败时返回空字典。"""
    config_path = project_root / ".vibetracing" / "config.json"
    if not config_path.exists():
        return {}
    try:
        with config_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        logging.getLogger(__name__).warning(
            "config.json 格式错误，已忽略: %s — %s", config_path, exc
        )
        return {}
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "config.json 读取失败，已忽略: %s — %s", config_path, exc
        )
        return {}


def resolve_path(project_root: Path, config: Dict[str, Any], key: str) -> Path:
    """解析文件路径：优先从 config.json paths 读取，否则使用默认路径。"""
    if key == "agent_claims":
        return project_root / ".vibetracing" / "claims"

    custom_paths = config.get("paths", {})
    if key in custom_paths:
        return project_root / custom_paths[key]

    default_rel = _DEFAULT_PATHS.get(key)
    if not default_rel:
        raise ValueError(f"Unknown path key: {key}")
    return project_root / default_rel
```

#### 2b. 重构 `raw_input.py`

- 删除 `_load_config()` 方法和 `get_path()` 方法
- 删除 `REQUIRED_FILES` 类常量（迁移到 `config.py`）
- `__init__` 接收 `config_data: dict` 参数（无 I/O）
- `load()` 从 `config.REQUIRED_FILES` 驱动，调用 `resolve_path()` 解析路径
- `RawInputManifest` 不增加 `config` 字段（pipeline 直接持有 config，不经 manifest 中转）

```python
from vibe_tracing.infra.loader.config import REQUIRED_FILES, resolve_path

class RawInputLoader:
    def __init__(self, project_root: Path, config_data: dict) -> None:
        self.project_root = Path(project_root)
        self._config_data = config_data

    def load(self) -> RawInputManifest:
        manifest = RawInputManifest()
        for file_key in REQUIRED_FILES:
            resolved = resolve_path(self.project_root, self._config_data, file_key)
            record = self._load_file(file_key, resolved, is_required=True)
            manifest.inputs_used.append(record)
            if record.status != "ok":
                manifest.has_required_errors = True
                manifest.error_count += 1
        for file_key in ["architecture_constraints", "task_list", "agent_claims", "human_decisions"]:
            resolved = resolve_path(self.project_root, self._config_data, file_key)
            record = self._load_file(file_key, resolved, is_required=False)
            manifest.inputs_used.append(record)
            if record.status not in ("ok", "missing"):
                manifest.error_count += 1
        return manifest
```

#### 2c. 重构 `pipeline.py`

- `_load_context()`：显式调用 `load_config()`，config 不经 manifest 中转
- `run_analyze()` L235：`output_dir` 改为 `resolve_path()`
- `_run_db_analysis()` L574：`constraints_path` 改为 `resolve_path()`

```python
from vibe_tracing.infra.loader.config import load_config, resolve_path

def _load_context(project_root: Path) -> UnifiedContext:
    config = load_config(project_root)
    manifest = RawInputLoader(project_root, config_data=config).load()
    # ...
    ctx = UnifiedContext(config=config, ...)  # 直接用 config，不经 manifest

def run_analyze(...):
    # L235
    output_dir = resolve_path(project_root, ctx.config, "output_dir")

def _run_db_analysis(...):
    # L574
    constraints_path = resolve_path(project_root, ctx.config, "architecture_constraints")
```

#### 2d. 重构 `change_proposal.py`

- 删除 `from vibe_tracing.infra.loader.raw_input import RawInputLoader`
- 导入 `from vibe_tracing.infra.loader.config import resolve_path`
- `config_data` 改为必填参数
- `self.config_data` 直接访问（不再通过 `self.raw_loader.config_data`）

#### 2e. 更新调用方（消除硬编码路径）

| 调用方 | 位置 | 变更 |
|--------|------|------|
| `finalize.py` | L132 | `constraints_path = resolve_path(project_root, config_data, "architecture_constraints")` |
| `finalize.py` | L201 | `prd_abs = resolve_path(project_root, config_data, "prd")` |
| `finalize.py` | L269-270 | `git add` 文件列表改用 `resolve_path()` 的相对路径 |
| `finalize.py` | L341-342 | 同上 |
| `pipeline.py` | L235 | `output_dir = resolve_path(project_root, ctx.config, "output_dir")` |
| `pipeline.py` | L574 | `constraints_path = resolve_path(project_root, ctx.config, "architecture_constraints")` |
| `reports.py` | — | 已传 `config_data`，无需变更 |
| `checker.py` | — | 已传 `config_data`，无需变更 |

#### 2f. 测试文件清理与适配

**`tests/test_raw_input_loader.py`**：
- 约 16 处 `RawInputLoader(...)` 需传入 `config_data`
  - `tmp_path` 型隔离测试：`RawInputLoader(tmp_path, config_data={})`（不引入无意义 I/O）
  - `PROJECT_ROOT` 型集成测试：`RawInputLoader(PROJECT_ROOT, config_data=load_config(PROJECT_ROOT))`
- `test_self_governance_rules_contract`（L261）：测试 `ArchitectureChangeProposalEngine`，不属于 loader 测试。迁移到 `test_architecture_change_proposal.py`

**`tests/test_architecture_change_proposal.py`**：
- 13 处 `ArchitectureChangeProposalEngine(proj)` 需传入 `config_data=load_config(proj)`
- 接收从 `test_raw_input_loader.py` 迁移来的 `test_self_governance_rules_contract`

**`tests/test_task_loader.py`**：
- 删除第 10 行无用 import：`from vibe_tracing.infra.loader.prd_parser import PrdParseResult, Requirement, AcceptanceCriteria`
- 删除 `get_mock_prd_result()` 函数（L53-90）：定义但从未被调用

验证：

```bash
grep -n "tool_report_files" tests/conftest.py  # 0 结果
grep -n "PrdParseResult\|get_mock_prd_result" tests/test_task_loader.py  # 0 结果
grep -n "ArchitectureChangeProposalEngine" tests/test_raw_input_loader.py  # 0 结果
grep -n "raw_loader\." src/vibe_tracing/cli/analyze/pipeline.py  # 仅 2 行（实例化 + load）
grep -rn "RawInputLoader" src/vibe_tracing/domain/governance/change_proposal.py  # 0 结果
grep -rn "docs/prd.md\|docs/task_list.json\|docs/architecture_constraints.json" src/vibe_tracing/cli/analyze/pipeline.py  # 0 结果
pytest tests/ -q
```

#### 2g. 更新 `__init__.py`

```python
from vibe_tracing.infra.loader.config import load_config, resolve_path, REQUIRED_FILES
from vibe_tracing.infra.loader.raw_input import RawInputLoader
from vibe_tracing.infra.loader.prd_parser import PrdParser, PrdParseResult
from vibe_tracing.infra.loader.task_loader import TaskLoader, TaskListLoadResult
from vibe_tracing.infra.loader.claim_loader import ClaimLoader, ClaimListLoadResult

__all__ = [
    "load_config",
    "resolve_path",
    "REQUIRED_FILES",
    "RawInputLoader",
    "PrdParser",
    "PrdParseResult",
    "TaskLoader",
    "TaskListLoadResult",
    "ClaimLoader",
    "ClaimListLoadResult",
]
```

---

### 步骤 3：清理 task_loader.py

源文件：
- 删除无用 import：`from vibe_tracing.infra.loader.prd_parser import PrdParseResult, get_parent_req_id`
- 修正模块 docstring（删除"cross-reference validation against the parsed PRD"描述）
- `load_hints("input")` 改为延迟加载（模块级 `_task_field_hints = None` + `_get_task_field_hints()` 函数）
- 删除空 `__init__` 方法

测试文件（在步骤 2f 中已完成）：
- `test_task_loader.py`：删除无用 import + 删除死代码 `get_mock_prd_result()`

```bash
grep -n "PrdParseResult\|get_parent_req_id" src/vibe_tracing/infra/loader/task_loader.py  # 0 结果
grep -n "PrdParseResult\|get_mock_prd_result" tests/test_task_loader.py  # 0 结果
pytest tests/test_task_loader.py -q
```

---

### 步骤 4：P2 清理

- **claim_loader.py**：补充 `load()` docstring；删除空 `__init__`
- **prd_parser.py**：补充模块级中文 docstring + 公共类中文 docstring

---

### 步骤 5：修复 governance/loader.py 硬编码路径

`domain/governance/ghost_code.py` 通过 `infra/governance/loader.py` 的函数读取文件，这些函数内部硬编码了路径。

| 函数 | 修复方式 |
|------|----------|
| `read_task_list()` | 接收 `task_list_path: Path` 参数 |
| `read_prd_ac_ids()` | 接收 `prd_path: Path` 参数 |
| `check_prd_exists()` | 接收 `prd_path: Path` 参数 |
| `read_constraints_file()` | 接收 `constraints_path: Path` 参数 |
| `read_constraints_json()` | 接收 `constraints_path: Path` 参数 |

调用方通过 `resolve_path()` 获取路径后传入。

```bash
grep -n "docs/prd.md\|docs/task_list.json\|docs/architecture_constraints.json" src/vibe_tracing/infra/governance/loader.py  # 0 结果
```

---

### 步骤 6：更新 spec

在所有代码变更完成后，统一更新 `docs/spec_pipeline_stage_1.md`：
- `RawInputManifest` 结构：删除 `tool_report_files`，不增加 `config`
- 阶段 1 描述：pipeline 通过 `load_config()` 显式获取 config，不经过 manifest
- `RawInputLoader` 构造函数：需传入 `config_data`

---

## 4. 不在本次范围

- `change_proposal.py` 核心逻辑重构（本次只解耦 loader 依赖）
- `claim_loader.py` 文件读取路径删除（保留作为独立使用入口）
- `prd_parser.py:parse_file()` 删除（保留作为独立使用入口）
- `ghost_code.py` 核心逻辑重构（本次只修复硬编码路径）
- `init.py` 模板路径（`vt init` 创建初始目录结构，使用默认路径是正确的）
- `pipeline.py` 阶段 2-9 重构
