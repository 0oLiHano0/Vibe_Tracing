# Pipeline Stage 3 重构方案

## 问题定义

Stage 3（执行验证工具）的 `_execute_tools()` 包含 4 项前置条件检查，其中 3 项与 `finalize` 的契约重复，1 项暴露了 `finalize` 自身的校验缺失。

### 第一性原则

`finalize` 是设计阶段到开发阶段的**唯一关卡**。它的职责是：锁定设计基线，将项目状态从"不确定"转为"确定"。一旦通过 `finalize`，`analyze` 应该信任项目状态是完整的——不需要再问"这个东西有没有"。

### 现状审计

| 检查项 | finalize 保证? | Stage 1 校验? | Stage 3 校验? | 判定 |
|--------|---------------|--------------|--------------|------|
| `constraints` 存在 | ✅ line 169 硬错误 | ❌ `is_required=False` | `if not: return []` | **冗余** — finalize 已保证 |
| `language` 存在 | ✅ line 184 硬错误 | ❌ 不在 config schema | `if not: _GateBlocked(1)` | **冗余** — finalize 已保证 |
| `ltm` 有语言配置 | ✅ line 191 硬错误 | ❌ | `if not: return []` | **冗余** — finalize 已保证 |
| PRD 非 draft | ❌ **未检查** | 允许 draft 通过 | `if is_draft: return []` | **缺失** — finalize 应拦截 |

---

## 修复路径

### 变更 1：finalize 拦截 draft PRD

**目标**：finalize 作为设计→开发的关卡，不应允许 draft 状态的 PRD 通过。

**修改文件**：`src/vibe_tracing/cli/finalize.py`

**当前行为**：
- finalize 读取 PRD 文件计算哈希（line 228），但**不解析 PRD 内容**
- 一个 `status: "draft"` 的 PRD 可以成功 finalize
- 导致 Stage 3 在运行时才发现"草稿模式跳过工具执行"——这是一个本应在 finalize 就拦住的状态

**修改步骤**：

1. 在 `run_finalize()` 的步骤 5（提取 language）之后、步骤 5.5（PRD-Architecture 映射校验）之前，插入 PRD 解析和状态校验：

```
位置：finalize.py line ~200（language 提取之后）

新增逻辑：
  1. 解析 PRD 文件：调用 PrdParser().parse_text(prd_content)
  2. 检查解析结果：如果 prd_res.is_valid 为 false → 打印解析错误 → return 1
  3. 检查 PRD 状态：如果 prd_res.status == "draft" → 打印提示信息 → return 1
```

2. 提示信息应说明：
   - draft PRD 不允许 finalize
   - 需要将 PRD 状态改为 active 后重新运行

**影响范围**：
- 已经 finalize 过的项目不受影响（finalize 有幂等检查，line 256 直接返回 0）
- 只影响首次 finalize 或 PRD 内容变更后的 re-finalize

---

### 变更 2：Stage 1 提升 constraints 为必需文件

**目标**：既然 finalize 保证 constraints 存在，Stage 1 的 `is_required=False` 是错误的契约声明。

**修改文件**：`src/vibe_tracing/infra/loader/raw_input.py`

**当前行为**：
- `REQUIRED_FILES = ("prd",)` — 只有 PRD 是必需的
- `architecture_constraints` 在非必需分支加载（line 86-93）
- Stage 1 对 constraints 缺失不做任何阻断

**修改步骤**：

1. 将 `architecture_constraints` 加入必需文件列表。有两种实现方式：

   **方式 A（推荐）**：修改 `RawInputLoader.load()` 中的加载逻辑，将 constraints 从非必需分支移到必需分支。当前代码 line 78-81 加载必需文件，line 86-93 加载非必需文件。将 constraints 的加载移到必需分支。

   **方式 B**：将 `REQUIRED_FILES` 从 `("prd",)` 改为 `("prd", "architecture_constraints")`，并调整 `load()` 方法使其从 `REQUIRED_FILES` 驱动加载逻辑（当前硬编码了 `prd` 的加载）。

2. 同步修改 `_load_context()` 中的相关逻辑：
   - 删除 line 114-129 中对 `constraints_record` 的 None 检查（既然已提升为必需，Stage 1 的 `has_required_errors` 检查会自动覆盖）
   - 删除 line 154 中 `constraints_record and constraints_record.status == STATUS_OK` 的防御性判断（已成为必需文件，状态一定 OK）

**影响范围**：
- 未运行 finalize 的项目在 Stage 1 就会被阻断（而非 Stage 3 静默跳过）
- 这是正确的行为：没有 constraints 就不应该运行 analyze

---

### 变更 3：Stage 3 删除冗余前置条件检查

**目标**：信任 finalize 的契约，删除对已保证不变量的重复检查。

**修改文件**：`src/vibe_tracing/cli/analyze/tools.py`

**当前 `_execute_tools()` 的前置检查（line 28-45）**：

```python
# 检查 1: constraints 缺失 → 跳过
if not constraints_record_content:
    return []

# 检查 2: language 缺失 → 阻断
if not config_language:
    print("Error: Project not finalized...", file=sys.stderr)
    raise _GateBlocked(1)

# 检查 3: draft 模式 → 跳过
if ctx.is_draft:
    print("Skipping tool execution: project is in draft status...", file=sys.stderr)
    return []

# 检查 4: ltm 无配置 → 跳过
if not (config_language and ltm):
    return []
```

**修改步骤**：

1. **删除检查 1**（constraints 缺失）：Stage 1 已通过 `is_required=True` 保证 constraints 存在，`_execute_tools` 不可能收到空 constraints。

2. **删除检查 2**（language 缺失）：finalize 保证 language 存在并写入 config.json，Stage 1 的 schema 校验（变更 2 后）会覆盖。`_execute_tools` 不可能收到空 language。

3. **删除检查 3**（draft 模式）：finalize 已拦截 draft PRD（变更 1），`_execute_tools` 不可能收到 `is_draft=True` 的上下文。

4. **删除检查 4**（ltm 无配置）：finalize 保证 `language` 在 `language_tool_matrix` 中有对应配置（line 191-195）。既然 language 非空且 ltm 一定有该语言的配置，`if not (config_language and ltm)` 永远为 false。

5. **保留路径收集逻辑**（line 80-115）：这是 Stage 3 的核心业务逻辑——从 Claims 中提取文件路径并分类。不是前置条件检查。

6. **保留 staged_files 过滤逻辑**（line 117-124）：这是 Stage 3 的运行时业务判断——只对暂存区文件执行工具。不是前置条件检查。

**修改后的 `_execute_tools()` 开头**：

```python
def _execute_tools(
    ctx: UnifiedContext,
    project_root: Path,
    staged_files: Optional[Set[str]] = None,
) -> List:
    """Execute validation tools and return tool evidence candidates.

    前置契约（由 finalize + Stage 1 保证）：
      - ctx.constraints 非空（finalize 保证 + Stage 1 is_required=True）
      - ctx.config["language"] 非空（finalize 保证 + Stage 1 schema 校验）
      - ctx.is_draft 为 False（finalize 拦截 draft PRD）
      - language_tool_matrix 中有 language 对应的配置（finalize 保证）
    """
    config_data = ctx.config
    claims_list = ctx.claims_list

    config_language = config_data["language"]          # 直接访问，不再 .get()
    config_validation_tools = config_data.get("validation_tools", [])
    ltm = ctx.constraints.get("language_tool_matrix", {})  # 不再检查 constraints 是否为空

    # ... 继续工具依赖预检（line 51-68）和路径收集逻辑
```

**影响范围**：
- `_execute_tools` 从 174 行缩减至约 150 行
- 删除了 4 个分支和 2 个 `_GateBlocked` 抛出点
- 函数语义更清晰：它只负责"执行工具"，不负责"验证前置条件"

---

### 变更 4：Stage 1 删除 draft 模式的隐式允许

**目标**：既然 finalize 拦截了 draft PRD，Stage 1 不需要再为 draft 模式开后门。

**修改文件**：`src/vibe_tracing/cli/analyze/pipeline.py`

**当前行为**（line 114-129）：

```python
# 非草稿模式下才强校验 task_list 和 architecture_constraints
if prd_res.status != "draft":
    if not task_list_record or task_list_record.status != STATUS_OK:
        ...raise _GateBlocked(1)
    if not constraints_record or constraints_record.status != STATUS_OK:
        ...raise _GateBlocked(1)
```

**修改步骤**：

1. 删除 `if prd_res.status != "draft":` 条件分支。经过 finalize 后，PRD 一定不是 draft，这个条件永远为 true。

2. 将 task_list 和 constraints 的校验提升为无条件检查（直接执行，不包裹在 if 中）。

3. 删除 `is_draft` 字段的计算和传递（line 168: `is_draft=(prd_res.status == "draft")`）。既然 draft 不可能通过 finalize，`UnifiedContext.is_draft` 字段永远为 false——它是死状态。

4. 同步清理 `UnifiedContext` 中的 `is_draft` 字段定义（`domain/context.py`）。

**影响范围**：
- `_load_context()` 的条件分支减少，逻辑更线性
- `UnifiedContext` 删除一个永远为 false 的字段
- Stage 3、Stage 7 等所有检查 `is_draft` 的地方都可以删除对应分支

---

## 变更依赖关系

```
变更 1 (finalize 拦截 draft)
  └── 变更 4 (Stage 1 删除 draft 后门)
        └── 变更 3 (Stage 3 删除冗余检查)

变更 2 (Stage 1 提升 constraints)
  └── 变更 3 (Stage 3 删除冗余检查)
```

**执行顺序**：变更 1 → 变更 2 → 变更 4 → 变更 3

变更 1 和变更 2 可以并行执行（无依赖）。变更 4 依赖变更 1。变更 3 依赖变更 1 + 变更 2 + 变更 4。

---

## 验证标准

| # | 验证项 | 预期结果 | 状态 |
|---|--------|----------|------|
| 1 | draft PRD 运行 `vt finalize` | 拒绝，退出码 1，提示"PRD 为 draft 状态，不允许 finalize" | ✅ 已完成 |
| 2 | 无 constraints 运行 `vt analyze` | Stage 1 阻断，退出码 1，提示"必需文件缺失" | ✅ 已完成 |
| 3 | 正常项目运行 `vt analyze` | Stage 3 无前置条件检查，直接进入工具执行 | ✅ 已完成 |
| 4 | `_execute_tools` 代码行数 | 从 174 行缩减至约 150 行 | ✅ 已完成 |
| 5 | `UnifiedContext.is_draft` 字段 | 已删除，无任何引用 | ✅ 已完成 |
| 6 | 现有测试全部通过 | 无回归 | ✅ 已完成 |

---

## 重构 C：工具列表数据源收敛

**日期**：2026-06-29
**状态**：已完成
**范围**：`vt finalize` + `cli/analyze/tools.py` + `docs/spec_pipeline_stage_3.md`

### 问题定义

阶段 3 的工具列表来自两个文件，通过拼接得到：

```
config.json → validation_tools = ["test", "lint", ...]     （类别名列表）
architecture_constraints.json → language_tool_matrix         （类别→工具定义）
```

`vt finalize` 从 constraints 读出 `language` 和 `language_tool_matrix`，但只把 `language` 写进 config，把 `language_tool_matrix` 留在 constraints 里。然后 `vt analyze` 再把两个文件拼起来用。

这是一个**半快照**：finalize 有能力也有职责做完整快照，但它只快照了一半。

### 设计决策

**收敛到 `config.json`。**

理由：

1. `FLOW-VT-009` 定义 config.json 为 analyze 阶段的完整运行时快照。当前的半快照违反了这个设计意图。
2. `language_tool_matrix` 是运行时配置（"用什么工具、怎么跑"），不是架构约束（模块边界、依赖规则）。它的消费者是阶段 3 的工具执行，不是 `ArchitectureComplianceChecker`。
3. `ArchitectureComplianceChecker`（阶段 7）检查的是 module_boundaries、dependency_rules 等，不检查 tool matrix。从 constraints 里去掉 tool matrix 不影响阶段 7。
4. 半快照比不快照更糟——得维护两个文件的同步，但又没有获得单一来源的好处。

**收敛后的职责划分：**

| 文件 | 职责 | analyze 阶段消费者 |
|------|------|-------------------|
| `config.json` | 完整运行时快照（language + language_tool_matrix） | 阶段 3（`_execute_tools`） |
| `architecture_constraints.json` | 架构设计基线（module_boundaries、dependency_rules 等）。tool matrix 仍在此文件中作为设计参考，`vt finalize` 读取它生成 config，但 `vt analyze` 不消费它 | 阶段 7（`ArchitectureComplianceChecker`） |

### 变更步骤

#### 变更 C-1：`vt finalize` 写入完整 tool matrix 子集

**修改文件**：`src/vibe_tracing/cli/finalize.py`

**当前行为**：
- finalize 从 constraints 读取 `language`（line 185）和 `language_tool_matrix`（line 191）
- 计算 `tool_categories`（line 198）：`[k for k, v in ltm[language].items() if isinstance(v, dict)]`
- 只把 `language` 和 `tool_categories`（作为 `validation_tools`）写入 config.json
- `language_tool_matrix` 留在 constraints 中，不写入 config

**写入 config 的两条路径**：
- 路径 A（首次 finalize）：line 382-386，`config_data["validation_tools"] = tool_categories`
- 路径 B（re-finalize，tools 变更）：line 313，`config_data["validation_tools"] = tool_categories`
- 比较逻辑（line 275）：`existing_tools = sorted(config_data.get("validation_tools", []))`
- 提示信息（line 363）：`"Updated validation_tools: {existing_tools} → {current_tools}"`

**修改步骤**：

1. 在两条写入路径中，将 `config_data["validation_tools"] = tool_categories` 替换为 `config_data["language_tool_matrix"] = {language: ltm[language]}`
2. 更新比较逻辑（line 275）：从 `language_tool_matrix` 提取 key 列表代替 `validation_tools`
3. 更新提示信息（line 363）：`"Updated validation_tools"` → `"Updated language_tool_matrix"`

**写入后的 config.json 结构变化**：

```json
{
  "language": "python",
  "language_tool_matrix": {
    "python": {
      "extensions": [".py"],
      "test": { "tool": "pytest", "default_command": "...", "output_format": "pytest_json", ... },
      "coverage": { ... },
      "lint": { ... },
      "type_check": { ... },
      "security": { ... }
    }
  }
}
```

`validation_tools` 字段删除，由 `language_tool_matrix[language].keys()` 动态获取。

#### 变更 C-2：`_execute_tools` 只读 config

**修改文件**：`src/vibe_tracing/cli/analyze/tools.py`

**当前行为**（tools.py:26-28）：

```python
config_language = config_data["language"]
config_validation_tools = config_data.get("validation_tools", [])
ltm = ctx.constraints.get("language_tool_matrix", {})
```

**修改为**：

```python
config_language = config_data["language"]
ltm = config_data["language_tool_matrix"]
config_validation_tools = list(ltm.keys())
```

**变更点**：
- `ltm` 从 `ctx.constraints` 改为 `ctx.config`，直接访问（不 `.get()`，不 fallback）
- `config_validation_tools` 从 config 字段改为 `ltm.keys()` 动态获取
- 删除对 `ctx.constraints` 的依赖
- 不接受向后兼容——旧 config 需要 re-finalize（T-1/T-2/T-3）

#### 变更 C-3：更新 spec 文档

**修改文件**：`docs/spec_pipeline_stage_3.md`

更新 §6（工具白名单机制）和 §7（详细处理流程）中关于数据源的描述，将"从两个文件读取"改为"从 config.json 读取"。

### 变更依赖关系

```
变更 C-1 (finalize 写入完整 tool matrix)
  └── 变更 C-2 (_execute_tools 只读 config)
        └── 变更 C-3 (更新 spec)
```

**执行顺序**：C-1 → C-2 → C-3

### 测试文件变更

| 测试文件 | 影响 | 说明 |
|----------|------|------|
| `test_finalize.py` | **需要改** | 3 个测试断言 `config["validation_tools"]`，需改为断言 `config["language_tool_matrix"]` |
| `test_cli_analyze.py` | **不需要改** | `language_tool_matrix: {}` 在 constraints 中的用例都是 `run_finalize` 测试（输入不变） |
| `test_tool_execution.py` | **不需要改** | 直接测试 `ToolExecutionEngine`，不经过 `_execute_tools` 编排层 |

`test_finalize.py` 需要变更的 3 个测试函数：

1. `test_finalize_happy_path`（L79-92）：断言 `config["language_tool_matrix"]["python"]` 包含预期类别 key
2. `test_finalize_already_finalized_same_language`（L95-114）：同上
3. `test_finalize_updates_tools_when_matrix_changes`（L117-155）：断言 re-finalize 后 `config["language_tool_matrix"]["python"]` 包含新增类别，提示信息从 `"Updated validation_tools"` 改为 `"Updated language_tool_matrix"`

### 验证标准

| # | 验证项 | 预期结果 |
|---|--------|----------|
| 1 | 运行 `vt finalize` 后检查 config.json | 包含 `language_tool_matrix` 字段，值为当前语言的工具矩阵子集 |
| 2 | `vt analyze` 阶段 3 正常执行 | 工具列表来自 config.json，结果与修改前一致 |
| 3 | `tools.py` 不再引用 `ctx.constraints` | `_execute_tools` 内部无 constraints 依赖 |
| 4 | `ArchitectureComplianceChecker` 不受影响 | 阶段 7 正常运行 |
| 5 | `pytest tests/test_finalize.py -v` | 3 个变更测试全量通过 |
| 6 | `pytest tests/test_tool_execution.py tests/test_cli_analyze.py -v` | 无回归 |

---

## 重构 D：删除暂存区过滤和死代码

**日期**：2026-06-29
**状态**：已完成
**范围**：`cli/analyze/tools.py` + `cli/analyze/pipeline.py`

### 问题定义

`_execute_tools()` 中有两个需要删除的代码块：

1. **暂存区文件过滤**：用 `staged_files` 缩小 Claim 文件列表——安全漏洞，Agent 可以通过部分提交绕过测试验证
2. **非代码文件 skipped 证据生成**：对非代码文件构造 `status="skipped"` 的证据候选项——生成的数据无人消费，是死代码

### 设计决策

**只删代码，不加代码。**

删除暂存区过滤的理由：
1. **安全漏洞**：Agent 可以通过部分提交绕过测试验证
2. **阶段 2 已覆盖**：幽灵代码检测保证了 staged 文件都有 Claim

删除非代码文件 skip 逻辑的理由：
1. **死代码**：`skipped_evidence` 字段在 `EvidenceMergeResult` 中定义，但 `apply()`、`persist()`、门禁引擎、报告、Dashboard 均不读取该字段。生成即丢弃。
2. **不值得移动**：之前设计的"下沉到 EvidenceBuilder"方案是把死代码搬到另一个地方——目标位置也是死代码。

不改 EvidenceBuilder 的理由：
- `skipped_evidence` 无人消费，改 `merge()` 签名没有业务价值
- 如果未来需要非代码文件的 skipped 证据，到时再设计完整链路（从门禁引擎到 Dashboard 的消费方）

### 变更步骤

#### 变更 D-1：`_execute_tools` 删除暂存区过滤和非代码文件 skip 逻辑

**修改文件**：`src/vibe_tracing/cli/analyze/tools.py`

**删除项**（从 `_execute_tools()` 函数中）：

1. `staged_files` 参数（函数签名和 docstring）
2. 非代码文件收集逻辑：`non_code_refs` 的构建
3. 暂存区过滤逻辑：`staged_files` 过滤 `test_paths`/`source_paths`
4. 非代码文件 skipped 证据生成：构造 skipped `ToolEvidenceCandidate` 并 append
5. staged_files 过滤后的空路径检查和提示信息：删除 staged_files 过滤后，此检查变为不可达代码（L93-94 已拦截空路径），一并删除。提示信息合并到 L93-94 的空路径检查中。

**保留项**：

1. 工具配置读取
2. 预检
3. 引擎创建
4. 代码文件路径收集：从 Claim 的 `test_refs`/`code_refs` 提取
5. 空路径检查（L93-94）：新增提示信息 `"no code files found in claims"`
6. 工具执行：`engine.execute_all()`
7. 错误输出与统计

**修改后的函数签名**：

```python
def _execute_tools(
    ctx: UnifiedContext,
    project_root: Path,
) -> List:
```

#### 变更 D-2：pipeline.py 删除 staged_files 参数

**修改文件**：`src/vibe_tracing/cli/analyze/pipeline.py`

`_execute_tools` 调用处删除 `staged_files=staged_files` 参数。

`staged_files` 变量在 pipeline.py 中仍保留——阶段 2（`detect_ghost_code`）和阶段 7（`_run_db_analysis`）仍需要它。

#### 变更 D-3：更新 spec 文档

**修改文件**：`docs/spec_pipeline_stage_3.md`

1. §1 输入来源：删除 staged_files 行
2. §3 处理逻辑：删除步骤 5（过滤暂存区文件）和步骤 8（非代码文件跳过处理）

### 变更依赖关系

```
变更 D-1 (_execute_tools 删除代码)
  └── 变更 D-2 (pipeline.py 删除参数)
        └── 变更 D-3 (更新 spec)
```

**执行顺序**：D-1 → D-2 → D-3（同一任务内完成）

### 测试文件变更

| 测试文件 | 影响 | 说明 |
|----------|------|------|
| `test_tool_execution.py` | **不需要改** | 直接测试引擎，不经过 `_execute_tools` |
| `test_cli_analyze.py` | **需要检查** | 如有测试传入 `staged_files` 参数，需删除 |

### 验证标准

| # | 验证项 | 预期结果 |
|---|--------|----------|
| 1 | `_execute_tools` 无 `staged_files` 参数 | 函数签名简化 |
| 2 | `_execute_tools` 无 `non_code_refs` 逻辑 | 不生成死数据 |
| 3 | Claim 引用的所有代码文件都被工具验证 | 不再有"未暂存文件跳过验证"的情况 |
| 4 | 阶段 2 幽灵代码检测不受影响 | `staged_files` 仍传递给 `detect_ghost_code` |
| 5 | 阶段 7 不受影响 | `staged_files` 仍传递给 `_run_db_analysis` |
| 6 | 全量测试通过 | 无回归 |

---

## 重构 E：tools.py 补全日志

**日期**：2026-06-29
**状态**：已完成
**范围**：`cli/analyze/tools.py`

### 问题定义

`_execute_tools()` 有 6 处 `print(stderr)` 但无任何 `OperationalLogger` 调用。预检失败、空路径、执行错误等场景只输出到终端，日志文件中无痕迹，无法事后排查。

### 设计决策

**在 `print(stderr)` 处同时记录日志事件。**

依据：输出通道分层原则（LOG-VT-011）——CLI 层异常处理使用双通道：`logger` 记录技术详情到日志文件，`print` 输出简短提示到终端。

### 变更步骤

#### 变更 E-1：`_execute_tools` 添加 logger

**修改文件**：`src/vibe_tracing/cli/analyze/tools.py`

**修改内容**：

1. 函数开头获取 logger 实例：`vt_logger = OperationalLogger.get()`
2. 在以下 `print(stderr)` 处同时记录日志事件：

| 位置 | print 内容 | 日志事件名 | 级别 |
|------|-----------|-----------|------|
| 预检失败 | `[AI Agent Repair Guide]` | `tool_precheck_failed` | WARNING |
| 无扩展名 | `no file extensions defined` | `no_code_extensions` | WARNING |
| 空路径 | `no code files found in claims` | `no_code_files` | WARNING |
| 执行开始 | `Executing validation tools for N path(s)` | `tool_execution_start` | INFO |
| 跳过文件 | `files skipped` | `tool_files_skipped` | INFO |
| 错误详情 | 各类工具错误 | `tool_execution_error` | WARNING |
| 完成统计 | `Tool execution complete` | `tool_execution_complete` | INFO |

3. 导入 `OperationalLogger`：`from vibe_tracing.infra.logging.logger import OperationalLogger`

### 验证标准

| # | 验证项 | 预期结果 |
|---|--------|----------|
| 1 | `tools.py` 使用 `OperationalLogger.get()` | 不自行 init，遵循内部模块规范 |
| 2 | 预检失败时日志文件有 `tool_precheck_failed` 事件 | 双通道：print 终端 + logger 日志文件 |
| 3 | 空路径时日志文件有 `no_code_files` 事件 | 同上 |
| 4 | 执行完成时日志文件有 `tool_execution_complete` 事件 | 含 executed_count、blocked_count 统计 |
| 5 | 无 `print(stderr)` 缺少对应 logger | 每处 print 都有日志事件 |
| 6 | 全量测试通过 | 无回归 |

---

## 重构 F：消除 tools.py 编排层

**状态**：已完成

### 问题定义

1. **三层编排过度设计**：pipeline.py → cli/analyze/tools.py → infra/tools/executor.py，tools.py 是约 140 行的薄代理层
2. **candidate.py 位置错误**：ToolEvidenceCandidate 定义在 infra/tools/，被 domain/evidence/builder.py 通过 List[Any] + getattr() 鸭子类型消费（隐式依赖 + 类型不安全）
3. **execute_all() 向后兼容**：tools.py 删除后无外部调用方

### 设计决策

1. candidate.py 移至 domain/evidence/，新增 ToolExecutionResult 结构化返回值
2. builder.py 的 getattr() 全部替换为直接属性访问，List[Any] → List[ToolEvidenceCandidate]
3. execute_from_claims() 作为唯一入口，内聚预检 + 路径收集 + 执行 + 统计
4. 删除 execute_all()（无外部调用方）
5. 预检 + 日志全部归 executor，pipeline.py 只做纯调度 + 按返回值 print Agent 修复指南

### 变更步骤

| 步骤 | 任务 | 变更文件 |
|------|------|----------|
| 0 | candidate.py 移动 + ToolExecutionResult | domain/evidence/candidate.py, executor.py, parsers.py, __init__.py |
| 1 | builder.py 类型修复 | domain/evidence/builder.py |
| 2 | execute_from_claims() + 删除 execute_all() | infra/tools/executor.py |
| 3 | 日志事件全归 executor | infra/tools/executor.py |
| 4 | pipeline.py 纯调度 | cli/analyze/pipeline.py |
| 5 | 删除 tools.py | cli/analyze/tools.py |
| 6 | 更新测试 | test_tool_execution.py, test_evidence_builder.py, test_integration_v3.py |
| 7 | 更新文档 | refactoring_design.md, spec_pipeline_stage_3.md 等 |

### 验证标准

| # | 验证项 | 预期结果 |
|---|--------|----------|
| 1 | `domain/evidence/candidate.py` 存在 | 包含 ToolEvidenceCandidate + ToolExecutionResult |
| 2 | `infra/tools/candidate.py` 不存在 | 已删除 |
| 3 | `cli/analyze/tools.py` 不存在 | 已删除 |
| 4 | `executor.py` 有 execute_from_claims，无 execute_all | 唯一入口 |
| 5 | `builder.py` 无 getattr() | 类型安全 |
| 6 | 全量测试通过 | 914 passed |
