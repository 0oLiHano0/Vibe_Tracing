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

## 4. Loader 包判定逻辑清理

### 背景

loader 包当前包含三类判定逻辑，偏离了"只做加载与解析"的职责边界：

| 逻辑 | 位置 | 问题 |
|------|------|------|
| -9999 模板记录跳过 | task_loader.py / claim_loader.py | validation 层已有完整覆盖，是重复逻辑 |
| 孤立任务检测 | task_loader.py | 属于引用完整性校验，应与 `check_invalid_task_*` 统一 |
| 架构孤儿检测 | task_loader.py | 同上 |

> prd_parser.py 中的校验逻辑（ID 重复、父子关系、缺失字段）保留不动——PRD 是 Markdown 格式，解析与校验天然耦合，拆分无收益。

### 设计原则

1. **loader 只做加载与反序列化**：读取文件 → 转为领域对象，不做判定
2. **引用完整性校验下沉到 SQL 查询层**：与 `check_invalid_task_requirements`、`check_invalid_task_acs` 等统一管理
3. **格式校验由 validation 层统一处理**：-9999 过滤已在 `infra/validation/checks.py` 实现，loader 不重复

### 设计决策

**废弃 AND 模式（strict_link）**：`id_rules.all_tasks_must_link_requirements_and_acceptance_criteria` 的 AND 逻辑（必须同时有 REQ 和 AC）在实践中是过度约束。任务关联了 REQ 但尚未关联 AC 是正常的工作中间态，不应被阻断。该配置从 task_loader 删除后不再保留，SQL 查询层固定使用 OR 模式（至少有其一）。项目 `task_list.json` 中的 `id_rules` 字段保留但不再影响校验行为。

**孤立任务检测下沉为 dashboard 警告**：从 task_loader 删除孤立任务检测后，新增 `check_isolated_tasks()` SQL 查询，在 `_run_db_analysis()` 中调用，结果写入 `analysis_details["isolated_tasks"]`。不阻断门禁，不出现在 gate 判定中，但通过现有数据流自动呈现在 dashboard 的治理警告卡片中。架构孤儿检测暂不同步——它是更强的约束，留待后续评估。

### 变更清单

| 步骤 | 变更 | 涉及文件 |
|------|------|----------|
| 1 | 全量删除 -9999 机制（源码 + 模板 + 测试 + 数据） | 见步骤 1 详单 |
| 2 | 从 task_loader.py 删除全部判定逻辑并清理残留 | task_loader.py |
| 3 | 新增 check_isolated_tasks 并集成到 pipeline | queries.py, pipeline.py, reports.py |
| 4 | 更新测试 | tests/test_task_loader.py, tests/test_db_queries.py |
| 5 | 统一更新文档（收尾） | spec_infra_loader.md, spec_pipeline_stage_1.md, refactoring_design.md |
| 6 | 切断 loader 包 I/O 后路 | task_loader.py, claim_loader.py, prd_parser.py, doctor.py, prd_arch_validator.py |

---

### 步骤 1：全量删除 -9999 机制

-9999 是过时设计：模板的格式示例泄漏到了运行时，导致 4 个源文件 11 处过滤逻辑、5 个测试文件 17 处断言、生产数据中混入模板记录。根因是模板生成时未清理示例数据，用运行时过滤弥补。

删除原则：**从源头消除，不在运行时过滤。** 模板不再包含需要过滤的示例记录。

> 本步骤的所有变更必须在同一次提交中完成。

#### 1a. 模板文件：删除 -9999 示例记录

**`src/vibe_tracing/templates/prd.template.md`**（5 处）：

删除所有含 `-9999` 的示例行。保留标题层级结构的骨架（h3/h4/h5），但示例内容改为不含 ID 的占位文本：

```markdown
### REQ-{prefix}-{序号}：需求标题

#### 优先级
must

#### 类别
functional

##### AC-{prefix}-{序号}-{子序号}：验收标准名称

- 是否必须有测试：是
```

> PRD 模板的核心价值是展示标题层级结构（h3→优先级→类别→h5），而非具体的 ID 值。用户通过 JSON Schema 和 validation hints 获取 ID 格式规范。

**`src/vibe_tracing/templates/architecture_constraints.template.json`**（1 处）：

将 `"REQ-{{PROJECT_PREFIX}}-9999"` 改为 `"REQ-{{PROJECT_PREFIX}}-001"`（指向一个假设的首个需求，用户按实际情况替换）。

#### 1b. 源码：删除所有 -9999 过滤逻辑

| 文件 | 位置 | 删除内容 |
|------|------|----------|
| `infra/loader/task_loader.py` | L134-135 | `if task_id.endswith("-9999"): continue` |
| `infra/loader/claim_loader.py` | L114-115 | `if claim_id.endswith("-9999"): continue` |
| `infra/governance/loader.py` | L34-35 | `if item.get("claim_id", "").endswith("-9999"): continue` |
| `infra/validation/checks.py` | L112 | `if not id_str or id_str.endswith("-9999"): return` → 改为 `if not id_str: return` |
| `infra/validation/checks.py` | L138 | `if task.get("task_id", "").endswith("-9999"): continue` → 删除 |
| `infra/validation/checks.py` | L150 | `if claim.get("claim_id", "").endswith("-9999"): continue` → 删除 |
| `infra/validation/checks.py` | L161 | docstring 中"排除 -9999 模板"描述 → 删除 |
| `infra/validation/checks.py` | L177 | `if tid.endswith("-9999") or not tid: continue` → 改为 `if not tid: continue` |
| `infra/validation/checks.py` | L198 | `if cid.endswith("-9999") or not cid: continue` → 改为 `if not cid: continue` |

#### 1c. 测试：删除 -9999 相关测试用例

| 文件 | 删除内容 |
|------|----------|
| `tests/test_dynamic_hints.py` | 删除 `-9999` 模板过滤测试（约 L146-217）：该测试验证 loader 跳过 -9999 记录，机制删除后测试无意义 |
| `tests/test_validate_inputs.py` | 删除 `-9999` 重复检测排除测试（约 L154-160）：该测试验证 validation 跳过 -9999 记录，机制删除后测试无意义 |
| `tests/test_dynamic_prefix.py` | L66：删除 `# Legacy templates -9999 are silently ignored in TaskLoader!` 注释，更新断言（如果模板不再生成 -9999 记录，task_res 的断言值需同步调整） |
| `tests/test_ghost_code_reconciler.py` | 删除 `-9999` 过滤测试（约 L261-262）：该测试验证 governance/loader 跳过 -9999 记录，机制删除后测试无意义 |
| `tests/test_scaffolding.py` | L56：将 `"REQ-VT-9999"` 断言改为 `"REQ-VT-001"`（与模板改动同步） |

#### 1d. 生产数据：清理 task_list.json 中的模板记录

**`docs/task_list.json`**（约 L2286-2305）：

删除 `TASK-VT-9999` 模板任务记录及其关联的 REQ-VT-9999、AC-VT-9999-99、DOD-VT-9999-99。这是一条嵌入在生产数据中的占位记录，不应存在。

同时更新 L2274 的 DoD 描述：删除"静默过滤掉以 -9999 结尾的模板项目"的描述。

同时更新 L6351 的 AI coding 指引：删除"保留 ClaimLoader 中的模板记录跳过逻辑（-9999）"。

#### 1e. 验证

```bash
# 全项目零 -9999 引用（排除本文件和 git 历史）
grep -rn "\-9999" src/ tests/ docs/ --include="*.py" --include="*.json" --include="*.md" | grep -v "loader_refactoring_plan" | grep -v ".venv"
# 预期：0 结果

# 模板文件不含 -9999
grep -n "\-9999" src/vibe_tracing/templates/*.json src/vibe_tracing/templates/*.md
# 预期：0 结果

# 测试通过
pytest tests/ -q
```

---

### 步骤 2：从 task_loader.py 删除全部判定逻辑并清理残留

删除 `validate_data()` 中的所有判定逻辑（孤立任务检测、架构孤儿检测、strict_link 配置读取）及关联残留代码。

#### 2a. 删除判定逻辑

删除 `validate_data()` 中以下代码块：

| 代码块 | 位置 | 内容 |
|--------|------|------|
| `strict_link` 配置读取 | L130-133 | `id_rules = data.get("id_rules", {})` + `strict_link = ...` |
| 孤立任务检测 | L142-167 | AND/OR 模式的 `if not related_requirements ...` 分支 |
| 架构孤儿检测 | L169-177 | `if not related_modules and status != "done"` 分支 |

#### 2b. 清理关联残留

| 内容 | 位置 | 原因 |
|------|------|------|
| `TaskGap` 数据类 | L62-66 | 仅判定逻辑使用 |
| `TaskListLoadResult.gaps` 字段 | L74 | 仅 `TaskGap` 使用 |
| `get_err_msg()` 函数 | L102-110 | 仅判定逻辑使用 |
| `load_hints` / `resolve_hint` import | L8 | 仅 `get_err_msg()` 使用 |
| `_task_field_hints` 延迟加载 | L13-20 | 仅 `get_err_msg()` 使用 |

清理后 `task_loader.py` 只保留：`Task`、`DodItem` 数据类 + `TaskLoader` 的反序列化逻辑。

#### 2c. 验证

```bash
grep -n "isolated\|orphan\|strict_link\|TaskGap\|gaps\|get_err_msg\|load_hints" src/vibe_tracing/infra/loader/task_loader.py  # 0 结果
grep -n "id_rules" src/vibe_tracing/infra/loader/task_loader.py  # 0 结果
python3 -c "from vibe_tracing.infra.loader.task_loader import TaskLoader, Task, DodItem"  # 无报错
```

---

### 步骤 3：新增 check_isolated_tasks 并集成到 pipeline

在 SQL 查询层新增孤立任务检测，作为 dashboard 警告呈现，不阻断门禁。

#### 3a. 在 infra/db/queries.py 新增查询函数

```python
def check_isolated_tasks(conn: sqlite3.Connection) -> List[dict]:
    """检查孤立任务：未关联任何 REQ 或 AC 的任务（OR 模式）。

    返回格式：[{"task_id": "TASK-VT-001", "reason": "no linked requirements or ACs"}]
    """
```

SQL 逻辑：

```sql
SELECT t.task_id
FROM tasks t
LEFT JOIN task_requirements tr ON t.task_id = tr.task_id
LEFT JOIN task_acs ta ON t.task_id = ta.task_id
WHERE tr.task_id IS NULL AND ta.task_id IS NULL
```

在 `infra/db/__init__.py` 中导出该函数。

#### 3b. 在 pipeline.py _run_db_analysis() 中调用

在 `_run_db_analysis()` 中（与其他 `check_*` 调用并列），添加：

```python
isolated_tasks = check_isolated_tasks(conn)
```

将结果写入 `analysis_details["isolated_tasks"]`。

#### 3c. 打通数据流到 dashboard

`analysis_details` 不会自动传递到 dashboard——`_build_report_document()` 和 `_render_output()` 均不接收 `analysis_details` 参数。需要显式打通。

**关键设计**：不修改 dashboard 模板。将 isolated_tasks 格式化为 warning 字符串，注入到 `report_doc["warnings"]` 列表中。现有治理警告卡片已经渲染 `warnings` 数组，自动生效。

**pipeline.py `_evaluate_and_output()`**：
- 从 `analysis_details` 中提取 `isolated_tasks`
- 传递给 `_build_report_document()` 的新增参数

**reports.py `_build_report_document()`**：
- 函数签名新增 `isolated_tasks: Optional[list] = None` 参数
- 将 isolated_tasks 格式化为 warning 字符串列表：`[f"孤立任务 {t['task_id']}: {t['reason']}" for t in isolated_tasks]`
- 追加到 `report_doc["warnings"]` 列表中（与现有 warnings 合并）

**数据流路径**：
```
_run_db_analysis()
  → analysis_details["isolated_tasks"]
    → _evaluate_and_output() 提取
      → _build_report_document(isolated_tasks=...)
        → report_doc["warnings"].extend(格式化的孤立任务警告)
          → DashboardRenderer.render(traceability_report=report_doc)
            → 治理警告卡片自动渲染（现有 propData.warnings 逻辑）
```

**不需要修改门禁引擎**——`isolated_tasks` 不参与 `gate_engine.evaluate()` 的判定。
**不需要修改 dashboard 模板**——现有治理警告卡片已渲染 `warnings` 数组。

#### 3d. 验证

```python
# 函数存在且可调用
from vibe_tracing.infra.db.queries import check_isolated_tasks
# 函数从 __init__.py 正确导出
from vibe_tracing.infra.db import check_isolated_tasks
```

```bash
grep -n "check_isolated_tasks" src/vibe_tracing/infra/db/queries.py src/vibe_tracing/infra/db/__init__.py src/vibe_tracing/cli/analyze/pipeline.py  # 有结果
```

---

### 步骤 4：更新测试

#### 4a. loader 测试清理（`tests/test_task_loader.py`）

以下测试用例验证已删除的判定逻辑，直接删除：

| 测试函数 | 行号 | 删除原因 |
|----------|------|----------|
| `test_isolated_task_fails` | L74-103 | 验证孤立任务检测（已删除） |
| `test_strict_link_rejects_req_only_task` | L121-152 | 验证 AND 模式（已废弃） |
| `test_or_logic_allows_req_only_task` | L155-189 | 验证 OR 模式（已删除判定逻辑） |
| `test_architectural_orphan_rejection` | L192-220 | 验证架构孤儿检测（已删除） |

保留的测试用例需同步更新：

| 测试函数 | 变更 |
|----------|------|
| `test_valid_task_list_passes` | L68：删除 `assert len(res.gaps) == 0`（`gaps` 字段已移除） |

清理后 `test_task_loader.py` 只保留：`test_valid_task_list_passes` + `test_validate_real_files_load`。

#### 4b. SQL 查询测试新增（`tests/test_db_queries.py`）

| 测试函数 | 覆盖 |
|----------|------|
| `test_check_isolated_tasks_no_links` | 无 REQ 且无 AC 的任务被检出 |
| `test_check_isolated_tasks_with_req_pass` | 有 REQ 无 AC 的任务不被检出 |
| `test_check_isolated_tasks_with_ac_pass` | 有 AC 无 REQ 的任务不被检出 |
| `test_check_isolated_tasks_empty_db` | 空数据库返回空列表 |

#### 4c. 验证

```bash
grep -n "isolated\|orphan\|strict_link\|TaskGap\|gaps" tests/test_task_loader.py  # 0 结果
grep -n "check_isolated_tasks" tests/test_db_queries.py  # 有结果
pytest tests/test_task_loader.py tests/test_db_queries.py -q
```

---

### 步骤 5：统一更新文档（收尾）

> 所有代码、模板、数据、测试变更完成后，在最后一步统一更新文档。

#### 5a. docs/spec_infra_loader.md

| 位置 | 变更 |
|------|------|
| §2 输入结构 `TaskListLoadResult` | 删除 `gaps` 字段；删除"以 -9999 结尾的模板记录会被跳过"注释 |
| §2 输入结构 `ClaimListLoadResult` | 删除"以 -9999 结尾的模板记录会被跳过"注释 |
| §3 处理逻辑 步骤 4 | 删除"孤立任务检测"和"架构孤儿检测"及"strict_link 双模式"描述，改为"反序列化为 Task 实体列表，不含判定逻辑" |
| §3 处理逻辑 步骤 5 | 删除"跳过以 -9999 结尾的模板记录"描述 |
| §4 输出结构 `TaskListLoadResult` | 同步删除 `gaps` 相关描述 |

#### 5b. docs/spec_pipeline_stage_1.md

| 位置 | 变更 |
|------|------|
| §2 config.json | 模块位置从 `raw_input.py:RawInputLoader._load_config()` 改为 `config.py:load_config()` |
| §2 `TaskListLoadResult` 结构 | 删除 `gaps` 字段 |
| §3 阶段 3 步骤 2 | 删除"如孤立任务检测"描述，改为"纯反序列化" |
| §5 异常表 | 删除"任务自洽校验失败（task_res.is_valid 为 false）"行 |

#### 5c. docs/refactoring_design.md

| 位置 | 变更 |
|------|------|
| §4.2 目标包结构 | task_loader.py 注释更新：删除"校验"描述，改为"反序列化" |

#### 5d. docs/loader_refactoring_plan.md（自身）

- §4 步骤 1-5 标记为已完成
- §5 状态跟踪表更新

#### 5e. 验证

```bash
grep -rn "\-9999" docs/ --include="*.md" | grep -v "loader_refactoring_plan"  # 0 结果
grep -n "gaps" docs/spec_infra_loader.md  # 0 结果（TaskListLoadResult 上下文中）
```

---

### 步骤 6：切断 loader 包的 I/O 后路

loader 包的反序列化层（task_loader、claim_loader、prd_parser）当前仍保留磁盘读取能力，违反"loader 只做内存反序列化"的原则。

#### 6a. 删除 TaskLoader.load_and_validate() 的 content=None 回退

**当前代码**（task_loader.py L89-100）：`content is None` 时调用 `json.load()` 读磁盘。

**改为**：删除 `content` 参数和 `task_list_path` 参数，方法签名改为 `load_and_validate(self, data: dict) -> TaskListLoadResult`。调用方必须传入已解析的字典。

**调用方变更**：
- `pipeline.py` L138：`task_loader.load_and_validate(task_list_record.content)` （已传 dict，无需改）
- `test_task_loader.py` `test_validate_real_files_load`：改为 `task_loader.validate_data(json.load(open(...)))` 或直接删除该测试（集成测试职责不在 loader 层）

#### 6b. 删除 ClaimLoader.load() 的 content=None 回退

**当前代码**（claim_loader.py L61-94）：`content is None` 时调用 `glob.glob()` + `json.load()` 读磁盘。

**改为**：删除 `content` 参数和 `claims_path` 参数，方法签名改为 `load(self, data: list) -> ClaimListLoadResult`。调用方必须传入已解析的列表。

**调用方变更**：
- `pipeline.py` L153：`claim_loader.load(claims_record.content)` （已传 list，无需改）
- `test_claim_loader.py` `test_validate_real_files_load`：改为 `claim_loader.validate_data(json.load(open(...)))` 或直接删除该测试

#### 6c. 删除 PrdParser.parse_file()

**当前代码**（prd_parser.py L167-177）：`parse_file()` 是 `read_text()` + `parse_text()` 的薄包装。

**改为**：删除 `parse_file()` 方法。调用方自行读文件后调用 `parse_text()`。

**调用方变更**：
- `doctor.py` L112：`text = prd_path.read_text(encoding="utf-8"); prd_res = prd_parser.parse_text(text)`
- `prd_arch_validator.py` L139：同上

#### 6d. 验证

```bash
grep -n "def parse_file\|def load_and_validate\|def load" src/vibe_tracing/infra/loader/task_loader.py src/vibe_tracing/infra/loader/claim_loader.py src/vibe_tracing/infra/loader/prd_parser.py
# task_loader: load_and_validate(self, data: dict) — 无 path/content 参数
# claim_loader: load(self, data: list) — 无 path/content 参数
# prd_parser: parse_file 已删除，只剩 parse_text

grep -n "parse_file\|\.load(" src/vibe_tracing/cli/doctor.py src/vibe_tracing/domain/compliance/prd_arch_validator.py
# 只有 parse_text 调用，无 parse_file

grep -n "json\.load\|glob\.glob\|read_text\|\.open(" src/vibe_tracing/infra/loader/task_loader.py src/vibe_tracing/infra/loader/claim_loader.py
# 0 结果（I/O 已全部移除）
```

---

### 变更后 loader 包职责

清理后 loader 包只做**纯内存反序列化**，零 I/O：

| 模块 | 职责 | I/O |
|------|------|-----|
| config.py | 配置加载与路径解析 | ✅ 有（唯一的 I/O 入口） |
| raw_input.py | 文件物理读取 + SHA-256 哈希 | ✅ 有（pipeline 显式调用） |
| prd_parser.py | Markdown 文本 → 领域模型 | ❌ 无（只接收文本） |
| task_loader.py | JSON dict → Task 实体列表 | ❌ 无（只接收 dict） |
| claim_loader.py | JSON list → Claim 实体列表 | ❌ 无（只接收 list） |

所有文件读取由 `RawInputLoader`（pipeline 阶段 1）统一完成，所有判定逻辑由 validation 层和 SQL 查询层统一管理。

---

## 5. 不在本次范围（状态跟踪）

| 项目 | 状态 | 说明 |
|------|------|------|
| `change_proposal.py` loader 解耦 | ✅ 已完成 | 不再依赖 `RawInputLoader`，通过 `config_data` + `resolve_path()` 获取路径 |
| `ghost_code.py` 硬编码路径修复 | ✅ 已完成 | 全部路径通过 `resolve_path()` 动态解析 |
| `governance/loader.py` 硬编码路径修复 | ✅ 已完成 | 所有函数接收 `Path` 参数，无硬编码路径 |
| `pipeline.py` 阶段 2-9 重构 | ✅ 已完成 | 9 个阶段各自独立函数，含计时和日志 |
| `claim_loader.py` 文件读取路径删除 | ⚠️ 部分完成 | pipeline 已使用 `content` 参数传入，但 `load()` 仍保留 `content=None` 的文件读取回退路径（独立使用模式）。`content` 参数仍为 `Optional[list]` |
| `prd_parser.py:parse_file()` 删除 | ❌ 未完成 | 方法仍存在，被 `doctor.py` 和 `prd_arch_validator.py` 调用 |
