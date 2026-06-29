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
