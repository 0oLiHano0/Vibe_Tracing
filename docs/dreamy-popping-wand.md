# 统一格式校验模块设计方案

> ⚠️ **过渡期文档**：本文档记录了 `infra/validation/` 模块的详细设计和实施过程。Phase 3-5 迁移完成后，本文档的内容将被 `architecture_vision.md` 和 `analyze_redesign.md` 完整覆盖，届时可删除。
>
> 当前状态：validation 模块已创建并实现（checks.py + ids.py + schema_validator.py + schemas/），但 Phase 3（test_result/coverage 校验注册）和 Phase 1（db.py validate_* 迁移）尚未执行。

## Context

当前 VT 的格式校验逻辑分散在三层：

- **Schema 层**：`schema_validator.py` + `schemas/*.schema.json`（JSON 结构校验）
- **Loader 层**：`claim_loader.py`、`task_loader.py` 中的 `validate_id()`、重复 ID 检测
- **基础设施层**：`db.py` 中的路径安全检查、`ids.py` 中的 ID 校验逻辑

存在以下问题：

- Schema 校验在 `_load_context` 和各 loader 中**重复执行**（loader 已经做了 schema 校验，`_load_context` 又做了一遍）
- `validate_id` 与 JSON Schema 的 `pattern` 约束**功能重叠**（都检查 ID 格式，但 `validate_id` 额外检查项目前缀）
- 路径安全检查只在 `db.py` 的 `validate_claim` 中有，loader 层没有
- `human_decisions.schema.json` 存在但**未接入运行时校验**
- 格式校验的职责分散在多个模块，没有统一入口

**目标**：创建一个独立的格式校验包，把所有"只看当前文件就能判断"的确定性校验收拢到一处。各 loader 只保留需要跨文件上下文的业务校验。

**设计原则**：

- **格式校验** = 不依赖其他文件，只看当前数据本身是否合法（结构、ID 格式、重复、路径安全）
- **业务校验** = 需要跨文件关联（task 引用的 requirement 在 PRD 里存不存在、claim 引用的 task 在 task_list 里存不存在）
- 格式校验由顶层调度层（`_load_context`）统一调用，loader 收到的数据**已被保证格式合法**

## 包结构

```
src/vibe_tracing/infra/validation/
├── __init__.py              # 暴露公共接口
├── checks.py                # 校验编排（调用 schema_validator 和 ids）
├── ids.py                   # ID 校验 + 生成 + 模式管理（从 infra/ids.py 迁入）
├── schema_validator.py      # JSON Schema 校验引擎（从 infra/schema_validator.py 迁入）
└── schemas/                 # JSON Schema 规则定义（从 src/schemas 迁入）
    ├── task_list.schema.json
    ├── agent_claims.schema.json
    ├── architecture_constraints.schema.json
    ├── human_decisions.schema.json
    ├── evidence_index.schema.json
    └── traceability_report.schema.json
```

### `validation/__init__.py`

暴露：

**格式校验入口：**
- `validate_inputs(manifest, project_prefix, schemas_dir=None) -> PreImportResult` — 唯一入口
- `ValidationIssue` — 单条校验错误
- `PreImportResult` — 校验结果聚合

**Schema 校验（从 `infra/schema_validator.py` 迁入）：**
- `SchemaValidator` — JSON Schema 校验引擎
- `ValidationResult` — 单次校验结果

**ID 相关（从 `infra/ids.py` 迁入）：**
- `validate_id(id_str) -> (bool, str)` — ID 格式 + 前缀校验
- `get_id_type(id_str) -> str` — 获取 ID 类型前缀
- `set_project_prefix(prefix)` — 设置项目前缀（全局状态）
- `get_project_prefix() -> str` — 获取当前项目前缀
- `make_risk_id(counter) -> str` — 生成风险 ID
- `make_evidence_id(counter) -> str` — 生成证据 ID
- `sentinel_evidence_id() -> str` — 生成哨兵证据 ID

### `validation/checks.py`

内部实现，不对外暴露。包含：

| 函数 | 职责 | 来源 |
|---|---|---|
| `_check_schemas()` | JSON Schema 校验（调用同包 `schema_validator.SchemaValidator`） | 从 `_load_context` 移入 |
| `_check_id_formats()` | ID 格式 + 项目前缀校验（调用同包 `ids.validate_id`） | 从各 loader 移入 |
| `_check_duplicate_ids()` | 同一文件内重复 ID 检测 | 从各 loader 移入 |
| `_check_path_safety()` | claims 的 `code_refs`/`test_refs` 路径安全 | 从 `db.py` 补入 |
| `_check_human_decisions()` | human_decisions 结构校验 | 新增 |

### `validation/ids.py`

从 `src/vibe_tracing/infra/ids.py` **整体迁入**，内容不变。包含：

- ID 模式定义（`_ID_PATTERNS`、`_VALID_PREFIXES`）
- 模式重建（`_rebuild_patterns`）
- 校验函数（`validate_id`、`get_id_type`）
- 状态管理（`set_project_prefix`、`get_project_prefix`）
- ID 生成（`make_risk_id`、`make_evidence_id`、`sentinel_evidence_id`）

迁入原因：ID 模式数据是校验的核心依赖，生成和状态管理也依赖同一份模式数据。拆分到两个包会制造不必要的跨包耦合。整文件移入，逻辑自洽。

### `validation/schema_validator.py`

从 `src/vibe_tracing/infra/schema_validator.py` **整体迁入**，内容不变。包含：

- `ValidationResult` — 校验结果数据类
- `_deque_path_to_string()` — 路径格式化
- `_build_hint()` — 错误提示生成
- `SchemaValidator` 类 — 加载 schema、执行校验、返回结果

内部 `schemas/` 目录作为默认 schema 路径，`SchemaValidator.__init__` 的 `schemas_dir` 参数默认指向同包下的 `schemas/` 子目录。

### `validation/schemas/`

从 `src/vibe_tracing/schemas/` **整体迁入**，包含 6 个 schema 文件。作为 `SchemaValidator` 的默认规则定义目录。

### `validate_inputs` 接口设计

```python
def validate_inputs(
    manifest,                # RawInputLoader.load() 返回的 manifest 对象
    project_prefix: str,     # 项目前缀（如 "VT"），从 config 读取
    schemas_dir: Path = None # schema 文件目录（可选，有默认值）
) -> PreImportResult:
    """一次性执行所有确定性格式校验。"""
```

接收 `manifest` 对象而非 8 个散装参数，因为 `RawInputLoader` 已经把所有文件加载到 manifest 中了。

`PreImportResult` 的 `issues` 列表包含所有校验失败项，每项包含：`error_code`（错误类型）、`field_path`（JSON 指针）、`message`（描述）、`hint`（修复建议）、`source_file`（来源文件）。

## 实现步骤

### Phase 1：接入 human_decisions schema（无破坏性变更）

**文件：`src/vibe_tracing/infra/schema_validator.py`**

- 在 `KNOWN_SCHEMAS` 字典中添加 `"human_decisions": "human_decisions.schema.json"`

**文件：`tests/test_schema_validator.py`**

- 添加测试：用合法的 human_decisions dict 验证 `validate_dict("human_decisions")` 通过
- 添加测试：用非法结构验证报错

### Phase 2：创建格式校验包 + 迁移 ids.py + 迁移 schema_validator.py + 迁移 schemas/ + 修复 import 路径

**迁移文件：`src/vibe_tracing/infra/ids.py` → `src/vibe_tracing/infra/validation/ids.py`**

- 将 `infra/ids.py` 整体移动到 `validation/ids.py`，内容不变
- **删除** `src/vibe_tracing/infra/ids.py`（不保留 thin wrapper）
- 在 `validation/__init__.py` 中 re-export 所有公开函数

**迁移文件：`src/vibe_tracing/infra/schema_validator.py` → `src/vibe_tracing/infra/validation/schema_validator.py`**

- 将 `infra/schema_validator.py` 整体移动到 `validation/schema_validator.py`
- 修改 `SchemaValidator.__init__`：`schemas_dir` 默认值从 `Path(__file__).parent.parent / "schemas"` 改为 `Path(__file__).parent / "schemas"`（指向同包下的 `schemas/` 子目录）
- **删除** `src/vibe_tracing/infra/schema_validator.py`

**迁移文件：`src/vibe_tracing/schemas/` → `src/vibe_tracing/infra/validation/schemas/`**

- 将 `schemas/` 目录整体移动到 `validation/schemas/`
- **删除** `src/vibe_tracing/schemas/` 目录

**修复 ids.py import 路径**（14 个文件，`vibe_tracing.infra.ids` → `vibe_tracing.infra.validation`）：

源代码（10 个文件）：

| 文件 | 当前 import | 修改后 |
|---|---|---|
| `domain/task_loader.py:13` | `from vibe_tracing.infra.ids import validate_id` | 删除（Phase 4 移除 validate_id 调用） |
| `domain/task_loader.py:143` | `from vibe_tracing.infra import ids`（延迟导入） | `from vibe_tracing.infra import validation as ids` |
| `domain/claim_loader.py:14` | `from vibe_tracing.infra.ids import validate_id` | 删除（Phase 4 移除 validate_id 调用） |
| `domain/claim_loader.py:152` | `from vibe_tracing.infra import ids`（延迟导入） | `from vibe_tracing.infra import validation as ids` |
| `analyzers/claim_evidence_analyzer.py:36` | `from vibe_tracing.infra import ids` | `from vibe_tracing.infra import validation as ids` |
| `domain/risk_advisor.py:11` | `from vibe_tracing.infra import ids` | `from vibe_tracing.infra import validation as ids` |
| `domain/architecture_compliance_checker.py:14` | `from vibe_tracing.infra import ids` | `from vibe_tracing.infra import validation as ids` |
| `domain/architecture_change_proposal.py:48` | `from vibe_tracing.infra import ids` | `from vibe_tracing.infra import validation as ids` |
| `domain/prd_parser.py:159` | `from vibe_tracing.infra import ids`（延迟导入） | `from vibe_tracing.infra import validation as ids` |
| `infra/schema_validator.py:84` | `from vibe_tracing.infra import ids`（延迟导入） | 删除（文件迁入 validation 后改为内部导入） |
| `commands/common.py:40` | `from vibe_tracing.infra import ids`（延迟导入） | `from vibe_tracing.infra import validation as ids` |
| `commands/finalize.py:171` | `from vibe_tracing.infra import ids`（延迟导入） | `from vibe_tracing.infra import validation as ids` |

测试文件（4 个文件）：

| 文件 | 当前 import | 修改后 |
|---|---|---|
| `tests/test_ids_and_enums.py:9` | `from vibe_tracing.infra.ids import validate_id, get_id_type` | `from vibe_tracing.infra.validation import validate_id, get_id_type` |
| `tests/test_dynamic_prefix.py:7` | `from vibe_tracing.infra import ids` | `from vibe_tracing.infra import validation as ids` |
| `tests/conftest.py:43` | `from vibe_tracing.infra import ids`（延迟导入） | `from vibe_tracing.infra import validation as ids` |
| `tests/test_finalize.py`（8 处） | `from vibe_tracing.infra import ids`（延迟导入） | `from vibe_tracing.infra import validation as ids` |

**修复 schema_validator.py import 路径**（14 个文件，`vibe_tracing.infra.schema_validator` → `vibe_tracing.infra.validation.schema_validator`）：

源代码（6 个文件）：

| 文件 | 当前 import | 修改后 |
|---|---|---|
| `commands/common.py:14` | `from vibe_tracing.infra.schema_validator import SchemaValidator` | `from vibe_tracing.infra.validation.schema_validator import SchemaValidator` |
| `commands/analyze/pipeline.py:12` | `from vibe_tracing.infra.schema_validator import SchemaValidator` | `from vibe_tracing.infra.validation.schema_validator import SchemaValidator` |
| `domain/evidence_index_builder.py:17` | `from vibe_tracing.infra.schema_validator import SchemaValidator` | `from vibe_tracing.infra.validation.schema_validator import SchemaValidator` |
| `domain/task_loader.py:16` | `from vibe_tracing.infra.schema_validator import SchemaValidator` | 删除（Phase 4 移除 SchemaValidator 引用） |
| `domain/traceability_report_builder.py:11` | `from vibe_tracing.infra.schema_validator import SchemaValidator` | `from vibe_tracing.infra.validation.schema_validator import SchemaValidator` |
| `domain/claim_loader.py:16` | `from vibe_tracing.infra.schema_validator import SchemaValidator` | 删除（Phase 4 移除 SchemaValidator 引用） |

测试文件（8 个文件）：

| 文件 | 当前 import | 修改后 |
|---|---|---|
| `tests/test_cli_analyze.py:6` | `from vibe_tracing.infra.schema_validator import SchemaValidator` | `from vibe_tracing.infra.validation.schema_validator import SchemaValidator` |
| `tests/test_evidence_index_builder.py:9` | `from vibe_tracing.infra.schema_validator import SchemaValidator` | `from vibe_tracing.infra.validation.schema_validator import SchemaValidator` |
| `tests/test_dynamic_prefix.py:6` | `from vibe_tracing.infra.schema_validator import SchemaValidator` | `from vibe_tracing.infra.validation.schema_validator import SchemaValidator` |
| `tests/test_dynamic_hints.py:8` | `from vibe_tracing.infra.schema_validator import SchemaValidator` | `from vibe_tracing.infra.validation.schema_validator import SchemaValidator` |
| `tests/test_scaffolding.py:75` | `from vibe_tracing.infra.schema_validator import SchemaValidator` | `from vibe_tracing.infra.validation.schema_validator import SchemaValidator` |
| `tests/test_schema_validator.py:15` | `from vibe_tracing.infra.schema_validator import SchemaValidator, _build_hint` | `from vibe_tracing.infra.validation.schema_validator import SchemaValidator, _build_hint` |
| `tests/test_ac_vt_009_coverage.py`（3 处） | `from vibe_tracing.infra.schema_validator import SchemaValidator` | `from vibe_tracing.infra.validation.schema_validator import SchemaValidator` |
| `tests/test_e2e_samples.py:9` | `from vibe_tracing.infra.schema_validator import SchemaValidator` | `from vibe_tracing.infra.validation.schema_validator import SchemaValidator` |

**新建文件：`src/vibe_tracing/infra/validation/__init__.py`**

```python
from .checks import validate_inputs, ValidationIssue, PreImportResult
from .schema_validator import SchemaValidator, ValidationResult
from .ids import (
    validate_id, get_id_type,
    set_project_prefix, get_project_prefix,
    make_risk_id, make_evidence_id, sentinel_evidence_id,
)

__all__ = [
    "validate_inputs", "ValidationIssue", "PreImportResult",
    "SchemaValidator", "ValidationResult",
    "validate_id", "get_id_type",
    "set_project_prefix", "get_project_prefix",
    "make_risk_id", "make_evidence_id", "sentinel_evidence_id",
]
```

**新建文件：`src/vibe_tracing/infra/validation/checks.py`**

数据结构：

```python
@dataclass
class ValidationIssue:
    """单条校验错误。"""
    error_code: str       # 错误类型枚举值
    field_path: str       # JSON 指针，如 "tasks[0].task_id"
    message: str          # 人类可读描述
    hint: str = ""        # 修复建议
    source_file: str = "" # 来源文件

@dataclass
class PreImportResult:
    """格式校验的聚合结果。"""
    issues: List[ValidationIssue]

    @property
    def is_valid(self) -> bool:
        return len(self.issues) == 0

    def format_errors(self) -> str:
        """将所有 issue 格式化为可打印字符串。"""
```

主函数：

```python
def validate_inputs(
    manifest,
    project_prefix: str,
    schemas_dir: Path = None,
) -> PreImportResult:
    """一次性执行所有确定性格式校验。

    Args:
        manifest: RawInputLoader.load() 返回的 manifest 对象，
                  包含所有已加载的输入文件记录。
        project_prefix: 项目前缀（如 "VT"）。
        schemas_dir: schema 文件目录（可选）。

    Returns:
        PreImportResult，包含所有校验失败项。
    """
```

校验顺序（5 类，逐类收集错误，不短路）：

1. **JSON Schema 校验** — 从 manifest 中取出 `task_list`、`agent_claims`、`architecture_constraints`、`human_decisions` 的 content，逐个委托 `SchemaValidator.validate_dict()` 校验
2. **ID 格式 + 前缀校验** — Schema 通过后，遍历各 ID 字段调用 `ids.validate_id()` 检查项目前缀
3. **重复 ID 检测** — tasks 的 `task_id`、claims 的 `claim_id` 唯一性检查（排除 `-9999` 模板）
4. **路径安全检查** — claims 的 `code_refs`/`test_refs`：拒绝绝对路径（`/` 开头）和 `..` 穿越
5. **human_decisions 校验** — 校验 human_decisions 内容（如果文件存在）

**新建文件：`tests/test_validate_inputs.py`**

测试用例：
- 全部合法 → `is_valid=True`
- task_list 缺必填字段 → schema violation
- task_id 前缀错误（如 `TASK-XX-001`，prefix=`VT`）→ prefix error
- 重复 task_id → duplicate error
- 重复 claim_id → duplicate error
- code_refs 含 `..` → path safety error
- test_refs 含绝对路径 → path safety error
- human_decisions 结构非法 → schema violation
- 混合合法+非法 → 只报告非法部分
- `-9999` 模板排除在重复检测之外
- `format_errors()` 输出可读

### Phase 3：重构 `commands/common.py` 使用校验包

**文件：`src/vibe_tracing/commands/common.py`**

在 `_load_context` 中：
- 删除原来的内联 schema 校验（约 69-109 行的三段 `validate_dict` 调用）
- 加载 `human_decisions.json`（从 `analysis.py` 的 `_load_human_decisions` 提前到此处）
- 调用 `from vibe_tracing.infra.validation import validate_inputs`，传入 manifest + project_prefix
- 校验失败时 `print(result.format_errors(), file=sys.stderr)` + `raise _GateBlocked(1)`

### Phase 4：清理 Loader 中的冗余校验

**文件：`src/vibe_tracing/domain/claim_loader.py`**

- 删除：`validate_data()` 中的 schema 校验调用（第 125-142 行）
- 删除：重复 claim_id 检测循环（第 158-170 行）
- 删除：`validate_id(claim_id)` 和 `validate_id(related_task)` 调用（第 201-213 行）
- 删除：`self.schema_validator` 字段（`__init__` 不再需要 schemas_dir）
- 更新：`from vibe_tracing.infra.ids import validate_id` → 删除（不再需要）
- 保留：交叉引用校验（`related_task` 是否存在于 task_list）

**文件：`src/vibe_tracing/domain/task_loader.py`**

- 删除：`validate_data()` 中的 schema 校验调用（第 112-127 行）
- 删除：重复 task_id 检测循环（第 149-161 行）
- 删除：`validate_id(task_id)` 调用（第 246-253 行）
- 删除：`self.schema_validator` 字段
- 更新：`from vibe_tracing.infra.ids import validate_id` → 删除（不再需要）
- 保留：PRD 交叉引用、架构交叉引用、孤立任务检测、架构孤儿检测（业务规则）

**文件：`tests/test_claim_loader.py`**

- 删除测试 schema 校验和重复 ID 检测的用例
- 保留交叉引用校验的用例
- `ClaimLoader` 构造函数不再传 `schemas_dir`

**文件：`tests/test_task_loader.py`**

- 同上，删除格式校验相关用例，保留业务规则用例

### Phase 5：human_decisions 纳入 UnifiedContext

**文件：`src/vibe_tracing/domain/context.py`**

- 添加 `human_decisions: Optional[dict]` 字段

**文件：`src/vibe_tracing/commands/common.py`**

- 在 `_load_context` 中填充 `ctx.human_decisions`

**文件：`src/vibe_tracing/commands/analyze/analysis.py` 和 `pipeline.py`**

- 从 context 读取 `human_decisions`，移除独立的 `_load_human_decisions()` 调用

## 关键文件清单

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `src/vibe_tracing/infra/validation/__init__.py` | 新建 | 包入口，暴露公共接口 |
| `src/vibe_tracing/infra/validation/checks.py` | 新建 | 校验编排逻辑 |
| `src/vibe_tracing/infra/validation/ids.py` | 新建（从 infra 迁入） | ID 校验 + 生成 + 模式管理 |
| `src/vibe_tracing/infra/validation/schema_validator.py` | 新建（从 infra 迁入） | JSON Schema 校验引擎 |
| `src/vibe_tracing/infra/validation/schemas/` | 新建（从 src/schemas 迁入） | JSON Schema 规则定义（6 个文件） |
| `src/vibe_tracing/infra/ids.py` | **删除** | 迁入 validation 包后删除 |
| `src/vibe_tracing/infra/schema_validator.py` | **删除** | 迁入 validation 包后删除 |
| `src/vibe_tracing/schemas/` | **删除** | 迁入 validation 包后删除 |
| `src/vibe_tracing/commands/common.py` | 修改 | 使用校验包；修复 ids + schema_validator import |
| `src/vibe_tracing/commands/finalize.py` | 修改 | 修复 ids import |
| `src/vibe_tracing/commands/analyze/pipeline.py` | 修改 | 修复 schema_validator import |
| `src/vibe_tracing/domain/claim_loader.py` | 修改 | 删除格式校验；修复 ids + schema_validator import |
| `src/vibe_tracing/domain/task_loader.py` | 修改 | 删除格式校验；修复 ids + schema_validator import |
| `src/vibe_tracing/domain/context.py` | 修改 | 添加 human_decisions 字段 |
| `src/vibe_tracing/domain/prd_parser.py` | 修改 | 修复 ids import |
| `src/vibe_tracing/domain/risk_advisor.py` | 修改 | 修复 ids import |
| `src/vibe_tracing/domain/architecture_compliance_checker.py` | 修改 | 修复 ids import |
| `src/vibe_tracing/domain/architecture_change_proposal.py` | 修改 | 修复 ids import |
| `src/vibe_tracing/domain/evidence_index_builder.py` | 修改 | 修复 schema_validator import |
| `src/vibe_tracing/domain/traceability_report_builder.py` | 修改 | 修复 schema_validator import |
| `src/vibe_tracing/analyzers/claim_evidence_analyzer.py` | 修改 | 修复 ids import |
| `src/vibe_tracing/commands/analyze/analysis.py` | 修改 | 从 context 读取 human_decisions |
| `tests/test_validate_inputs.py` | 新建 | 格式校验包的测试 |
| `tests/test_claim_loader.py` | 修改 | 删除格式校验用例 |
| `tests/test_task_loader.py` | 修改 | 删除格式校验用例 |
| `tests/test_schema_validator.py` | 修改 | 修复 import；添加 human_decisions 测试 |
| `tests/test_ids_and_enums.py` | 修改 | 修复 ids import |
| `tests/test_dynamic_prefix.py` | 修改 | 修复 ids + schema_validator import |
| `tests/test_dynamic_hints.py` | 修改 | 修复 schema_validator import |
| `tests/test_scaffolding.py` | 修改 | 修复 schema_validator import |
| `tests/test_cli_analyze.py` | 修改 | 修复 schema_validator import |
| `tests/test_evidence_index_builder.py` | 修改 | 修复 schema_validator import |
| `tests/test_e2e_samples.py` | 修改 | 修复 schema_validator import |
| `tests/test_ac_vt_009_coverage.py` | 修改 | 修复 schema_validator import（3 处） |
| `tests/conftest.py` | 修改 | 修复 ids import |
| `tests/test_finalize.py` | 修改 | 修复 ids import（8 处） |

## 职责边界

```
格式校验包 (infra/validation/)              业务校验 (各 loader)
─────────────────────────            ──────────────────────
Schema 校验                           TaskLoader:
  - 必填字段                              - PRD 交叉引用（task → requirement）
  - 类型                                  - 架构交叉引用（task → module/constraint）
  - 枚举                                  - 孤立任务检测
  - 正则                                  - 架构孤儿检测
  - 嵌套结构
ID 格式 + 前缀                       ClaimLoader:
重复 ID 检测                             - task 存在性检查（claim → task）
路径安全检查
human_decisions 结构校验
```

## 验证方式

每个 Phase 完成后：

1. `python3 -c "import ast; ast.parse(...)"` 验证语法
2. `python3 -m pytest tests/test_validate_inputs.py -x -q` 验证新模块
3. `python3 -m pytest tests/test_claim_loader.py tests/test_task_loader.py tests/test_schema_validator.py -x -q` 验证 loader 清理
4. `python3 -m pytest -x -q --ignore=tests/test_acceptance.py` 全量回归（排除已知的 acceptance 失败）

Phase 2 额外验证：

5. `python3 -c "from vibe_tracing.infra.validation import validate_id, SchemaValidator, set_project_prefix; print('OK')"` — 确认直接导入可用
6. `grep -r "vibe_tracing.infra.ids" src/ tests/` — 确认无残留 ids 旧路径
7. `grep -r "vibe_tracing.infra.schema_validator" src/ tests/` — 确认无残留 schema_validator 旧路径
8. `ls src/vibe_tracing/schemas/ 2>/dev/null && echo "STILL EXISTS" || echo "DELETED"` — 确认旧 schemas 目录已删除

## 原子化任务清单

> 每个任务独立可执行、独立可验证。subagent 无需额外上下文即可开始。
> 执行顺序见依赖关系图，无依赖的任务可并行。

### 依赖关系图

```
T1 ──────────────────────────────────────────────────────┐
T2 → T3 → T4 ──→ T6 → T8 → T9 → T10 → T11 → T12 → T13
              └→ T5 ─┘     └→ T7 ┘                      │
T14 → T15 ← ─────────────────────────────────────────────┘
```

无依赖可立即开始：T1, T2
T2 完成后：T3, T4, T5 可并行
T3 完成后：T4, T5 可并行
T4+T5 完成后：T6, T7 可并行
T6 完成后：T8, T9 可并行
T8+T9 完成后：T10
T10 完成后：T11
T11 完成后：T12
T12 完成后：T13, T14 可并行
T13+T14 完成后：T15

---

### T1：接入 human_decisions schema

**目标**：在 SchemaValidator 的 KNOWN_SCHEMAS 中注册 human_decisions schema。

**前置依赖**：无

**操作**：
1. 读取 `src/vibe_tracing/infra/schema_validator.py`，找到 `KNOWN_SCHEMAS` 字典（约第 118-124 行）
2. 在字典中添加一行：`"human_decisions": "human_decisions.schema.json"`
3. 确认 `src/vibe_tracing/schemas/human_decisions.schema.json` 文件已存在

**涉及文件**：
- `src/vibe_tracing/infra/schema_validator.py`（修改）

**验证命令**：
```bash
python3 -c "from vibe_tracing.infra.schema_validator import SchemaValidator; v = SchemaValidator(); assert 'human_decisions' in v.KNOWN_SCHEMAS; print('T1 OK')"
```

---

### T2：创建 validation 包目录结构

**目标**：创建 `src/vibe_tracing/infra/validation/` 包的基础目录。

**前置依赖**：无

**操作**：
1. 创建目录 `src/vibe_tracing/infra/validation/`
2. 创建空文件 `src/vibe_tracing/infra/validation/__init__.py`（占位，后续 T8 填充内容）

**涉及文件**：
- `src/vibe_tracing/infra/validation/__init__.py`（新建）

**验证命令**：
```bash
python3 -c "import os; assert os.path.isdir('src/vibe_tracing/infra/validation'); print('T2 OK')"
```

---

### T3：迁移 ids.py 到 validation 包

**目标**：将 `infra/ids.py` 整体移动到 `infra/validation/ids.py`，更新内部 import，删除旧文件。

**前置依赖**：T2

**操作**：
1. 复制 `src/vibe_tracing/infra/ids.py` 到 `src/vibe_tracing/infra/validation/ids.py`，内容不变
2. 删除 `src/vibe_tracing/infra/ids.py`

**涉及文件**：
- `src/vibe_tracing/infra/validation/ids.py`（新建，从 infra 迁入）
- `src/vibe_tracing/infra/ids.py`（删除）

**验证命令**：
```bash
python3 -c "from vibe_tracing.infra.validation.ids import validate_id, get_id_type, set_project_prefix, get_project_prefix, make_risk_id, sentinel_evidence_id; print('T3 OK')"
```

---

### T4：迁移 schema_validator.py 到 validation 包

**目标**：将 `infra/schema_validator.py` 整体移动到 `infra/validation/schema_validator.py`，修复内部 ids import，删除旧文件。

**前置依赖**：T2

**操作**：
1. 复制 `src/vibe_tracing/infra/schema_validator.py` 到 `src/vibe_tracing/infra/validation/schema_validator.py`
2. 在新文件中，将第 84 行 `from vibe_tracing.infra import ids` 改为 `from vibe_tracing.infra.validation import ids`
3. 将 `SchemaValidator.__init__` 中 `schemas_dir` 默认值从 `Path(__file__).parent.parent / "schemas"` 改为 `Path(__file__).parent / "schemas"`
4. 删除 `src/vibe_tracing/infra/schema_validator.py`

**涉及文件**：
- `src/vibe_tracing/infra/validation/schema_validator.py`（新建，从 infra 迁入）
- `src/vibe_tracing/infra/schema_validator.py`（删除）

**验证命令**：
```bash
python3 -c "from vibe_tracing.infra.validation.schema_validator import SchemaValidator, ValidationResult; print('T4 OK')"
```

---

### T5：迁移 schemas/ 目录到 validation 包

**目标**：将 `src/vibe_tracing/schemas/` 整体移动到 `src/vibe_tracing/infra/validation/schemas/`。

**前置依赖**：T2

**操作**：
1. 复制 `src/vibe_tracing/schemas/` 目录下所有文件到 `src/vibe_tracing/infra/validation/schemas/`
2. 删除 `src/vibe_tracing/schemas/` 目录

**涉及文件**：
- `src/vibe_tracing/infra/validation/schemas/*.schema.json`（新建，从 src/schemas 迁入）
- `src/vibe_tracing/schemas/`（删除）

**验证命令**：
```bash
python3 -c "from pathlib import Path; s=Path('src/vibe_tracing/infra/validation/schemas'); assert s.exists(); assert len(list(s.glob('*.schema.json')))==6; print('T5 OK')"
```

---

### T6：创建 __init__.py 和 checks.py（校验包核心）

**目标**：实现校验包的公共接口和校验编排逻辑。

**前置依赖**：T3, T4, T5

**操作**：

**步骤 1**：创建 `src/vibe_tracing/infra/validation/checks.py`，包含：
- `ValidationIssue` 数据类（error_code, field_path, message, hint, source_file）
- `PreImportResult` 数据类（issues 列表 + is_valid 属性 + format_errors 方法）
- `validate_inputs(manifest, project_prefix, schemas_dir=None)` 函数，按以下顺序执行 5 类校验：
  1. JSON Schema 校验（委托 `SchemaValidator.validate_dict()`）
  2. ID 格式 + 前缀校验（委托 `ids.validate_id()`）
  3. 重复 ID 检测（tasks 的 task_id、claims 的 claim_id，排除 `-9999` 模板）
  4. 路径安全检查（claims 的 code_refs/test_refs，拒绝绝对路径和 `..`）
  5. human_decisions 结构校验（委托 `SchemaValidator.validate_dict()`）

**步骤 2**：更新 `src/vibe_tracing/infra/validation/__init__.py`，re-export 所有公开符号：
- 来自 checks.py：validate_inputs, ValidationIssue, PreImportResult
- 来自 schema_validator.py：SchemaValidator, ValidationResult
- 来自 ids.py：validate_id, get_id_type, set_project_prefix, get_project_prefix, make_risk_id, make_evidence_id, sentinel_evidence_id

**涉及文件**：
- `src/vibe_tracing/infra/validation/checks.py`（新建）
- `src/vibe_tracing/infra/validation/__init__.py`（修改）

**验证命令**：
```bash
python3 -c "from vibe_tracing.infra.validation import validate_inputs, SchemaValidator, validate_id, set_project_prefix; print('T6 OK')"
```

---

### T7：修复所有外部 import 路径

**目标**：将所有引用 `vibe_tracing.infra.ids` 和 `vibe_tracing.infra.schema_validator` 的 import 更新为新路径。

**前置依赖**：T3, T4, T6

**操作**：

**ids.py import 修复**（12 个文件）：

| 文件 | 修改内容 |
|---|---|
| `analyzers/claim_evidence_analyzer.py:36` | `from vibe_tracing.infra import ids` → `from vibe_tracing.infra import validation as ids` |
| `domain/risk_advisor.py:11` | 同上 |
| `domain/architecture_compliance_checker.py:14` | 同上 |
| `domain/architecture_change_proposal.py:48` | 同上 |
| `domain/prd_parser.py:159` | 同上（延迟导入） |
| `commands/common.py:40` | 同上（延迟导入） |
| `commands/finalize.py:171` | 同上（延迟导入） |
| `domain/task_loader.py:143` | 同上（延迟导入） |
| `domain/claim_loader.py:152` | 同上（延迟导入） |
| `tests/test_dynamic_prefix.py:7` | `from vibe_tracing.infra import ids` → `from vibe_tracing.infra import validation as ids` |
| `tests/conftest.py:43` | 同上（延迟导入） |
| `tests/test_finalize.py`（8 处） | 同上（延迟导入） |

**schema_validator.py import 修复**（12 个文件）：

| 文件 | 修改内容 |
|---|---|
| `commands/common.py:14` | `from vibe_tracing.infra.schema_validator import SchemaValidator` → `from vibe_tracing.infra.validation.schema_validator import SchemaValidator` |
| `commands/analyze/pipeline.py:12` | 同上 |
| `domain/evidence_index_builder.py:17` | 同上 |
| `domain/traceability_report_builder.py:11` | 同上 |
| `tests/test_cli_analyze.py:6` | 同上 |
| `tests/test_evidence_index_builder.py:9` | 同上 |
| `tests/test_dynamic_prefix.py:6` | 同上 |
| `tests/test_dynamic_hints.py:8` | 同上 |
| `tests/test_scaffolding.py:75` | 同上（延迟导入） |
| `tests/test_schema_validator.py:15` | 同上 |
| `tests/test_ac_vt_009_coverage.py`（3 处） | 同上 |
| `tests/test_e2e_samples.py:9` | 同上 |

**ids direct import 修复**（1 个文件）：

| 文件 | 修改内容 |
|---|---|
| `tests/test_ids_and_enums.py:9` | `from vibe_tracing.infra.ids import validate_id, get_id_type` → `from vibe_tracing.infra.validation import validate_id, get_id_type` |

**涉及文件**：25 个文件（仅修改 import 行）

**验证命令**：
```bash
grep -r "from vibe_tracing.infra.ids" src/ tests/ && echo "FAIL: old ids path found" || echo "T7 ids OK"
grep -r "from vibe_tracing.infra.schema_validator" src/ tests/ && echo "FAIL: old schema_validator path found" || echo "T7 schema_validator OK"
python3 -m pytest tests/test_ids_and_enums.py tests/test_dynamic_prefix.py -x -q 2>&1 | tail -3
```

---

### T8：重构 common.py 使用校验包

**目标**：将 `_load_context` 中的内联 schema 校验替换为统一的 `validate_inputs` 调用，并加载 human_decisions。

**前置依赖**：T6, T7

**操作**：

**步骤 1**：删除 `_load_context` 中的内联 schema 校验（约第 69-109 行的三段 `validate_dict` 调用）

**步骤 2**：在 `_load_context` 中（删除内联校验后的位置），添加：
```python
from vibe_tracing.infra.validation import validate_inputs

# 加载 human_decisions（从 manifest 中获取，或从文件读取）
# ...

# 统一格式校验
validation_result = validate_inputs(manifest, config_prefix)
if not validation_result.is_valid:
    print(validation_result.format_errors(), file=sys.stderr)
    raise _GateBlocked(1)
```

**步骤 3**：移除不再需要的 import（`SchemaValidator` 的 import 可能不再需要）

**涉及文件**：
- `src/vibe_tracing/commands/common.py`（修改）

**验证命令**：
```bash
python3 -c "from vibe_tracing.commands.common import _load_context; print('T8 import OK')"
python3 -m pytest tests/test_cli_analyze.py -x -q 2>&1 | tail -3
```

---

### T9：human_decisions 纳入 UnifiedContext + 读取链路

**目标**：将 human_decisions 数据纳入 UnifiedContext，并更新下游从 context 读取。

**前置依赖**：T8

**操作**：

**步骤 1**：修改 `src/vibe_tracing/domain/context.py`，在 UnifiedContext 中添加字段：
```python
human_decisions: Optional[dict] = None
```

**步骤 2**：修改 `src/vibe_tracing/commands/common.py` 的 `_load_context`，在构建 ctx 时填充 `human_decisions`

**步骤 3**：修改 `src/vibe_tracing/commands/analyze/analysis.py`，从 `ctx.human_decisions` 读取（移除独立的 `_load_human_decisions()` 调用）

**步骤 4**：修改 `src/vibe_tracing/commands/analyze/pipeline.py`，从 context 传递 human_decisions

**涉及文件**：
- `src/vibe_tracing/domain/context.py`（修改）
- `src/vibe_tracing/commands/common.py`（修改）
- `src/vibe_tracing/commands/analyze/analysis.py`（修改）
- `src/vibe_tracing/commands/analyze/pipeline.py`（修改）

**验证命令**：
```bash
python3 -c "from vibe_tracing.domain.context import UnifiedContext; ctx = UnifiedContext(config={}, prd=None, task_result=None, claims_list=[], manifest=None, config_prefix='VT'); assert hasattr(ctx, 'human_decisions'); print('T9 context OK')"
python3 -m pytest tests/test_cli_analyze.py -x -q 2>&1 | tail -3
```

---

### T10：清理 claim_loader.py 格式校验

**目标**：从 ClaimLoader 中移除所有格式校验逻辑，只保留交叉引用校验。

**前置依赖**：T7

**操作**：
1. 删除 `validate_data()` 中的 schema 校验调用（约第 125-142 行）
2. 删除重复 claim_id 检测循环（约第 158-170 行）
3. 删除 `validate_id(claim_id)` 和 `validate_id(related_task)` 调用（约第 201-213 行）
4. 删除 `self.schema_validator` 字段（`__init__` 中第 57-58 行，不再需要 schemas_dir 参数）
5. 删除 `from vibe_tracing.infra.ids import validate_id` import（第 14 行）
6. 删除 `from vibe_tracing.infra.validation.schema_validator import SchemaValidator` import（第 16 行，如果 T7 未修复）
7. **保留**：交叉引用校验（related_task 是否存在于 task_list）

**涉及文件**：
- `src/vibe_tracing/domain/claim_loader.py`（修改）

**验证命令**：
```bash
python3 -c "from vibe_tracing.domain.claim_loader import ClaimLoader; cl = ClaimLoader(); print('T10 OK')"
```

---

### T11：清理 task_loader.py 格式校验

**目标**：从 TaskLoader 中移除所有格式校验逻辑，只保留业务校验。

**前置依赖**：T7

**操作**：
1. 删除 `validate_data()` 中的 schema 校验调用（约第 112-127 行）
2. 删除重复 task_id 检测循环（约第 149-161 行）
3. 删除 `validate_id(task_id)` 调用（约第 246-253 行）
4. 删除 `self.schema_validator` 字段（`__init__` 中第 72-73 行）
5. 删除 `from vibe_tracing.infra.ids import validate_id` import（第 13 行）
6. 删除 `from vibe_tracing.infra.validation.schema_validator import SchemaValidator` import（第 16 行，如果 T7 未修复）
7. **保留**：PRD 交叉引用、架构交叉引用、孤立任务检测、架构孤儿检测

**涉及文件**：
- `src/vibe_tracing/domain/task_loader.py`（修改）

**验证命令**：
```bash
python3 -c "from vibe_tracing.domain.task_loader import TaskLoader; tl = TaskLoader(); print('T11 OK')"
```

---

### T12：编写校验包测试 + loader 测试清理 + 全量回归

**目标**：为新校验包编写测试，清理 loader 的旧测试用例，运行全量回归。

**前置依赖**：T8, T9, T10, T11

**操作**：

**步骤 1**：创建 `tests/test_validate_inputs.py`，包含以下测试用例：
- 全部合法数据 → is_valid=True
- task_list 缺必填字段 → schema violation
- task_id 前缀错误（如 `TASK-XX-001`，prefix=`VT`）→ prefix error
- 重复 task_id → duplicate error
- 重复 claim_id → duplicate error
- code_refs 含 `..` → path safety error
- test_refs 含绝对路径 → path safety error
- human_decisions 结构非法 → schema violation
- 混合合法+非法 → 只报告非法部分
- `-9999` 模板排除在重复检测之外
- format_errors() 输出可读

**步骤 2**：清理 `tests/test_claim_loader.py`：
- 删除测试 schema 校验和重复 ID 检测的用例
- 保留交叉引用校验的用例
- ClaimLoader 构造函数不再传 schemas_dir

**步骤 3**：清理 `tests/test_task_loader.py`：
- 删除格式校验相关用例
- 保留业务规则用例
- TaskLoader 构造函数不再传 schemas_dir

**步骤 4**：更新 `tests/test_schema_validator.py` 的 import 路径（T7 已处理，此处确认）

**步骤 5**：运行全量回归：
```bash
python3 -m pytest -x -q --ignore=tests/test_acceptance.py
```

**涉及文件**：
- `tests/test_validate_inputs.py`（新建）
- `tests/test_claim_loader.py`（修改）
- `tests/test_task_loader.py`（修改）
- `tests/test_schema_validator.py`（确认 import）

**验证命令**：
```bash
python3 -m pytest tests/test_validate_inputs.py -x -q
python3 -m pytest tests/test_claim_loader.py tests/test_task_loader.py tests/test_schema_validator.py -x -q
python3 -m pytest -x -q --ignore=tests/test_acceptance.py
```
