# 阶段 2 模块详解

## 1. 输入来源

| 来源 | 包/模块 | 文件 |
|------|---------|------|
| **统一上下文** | `domain/context.py:UnifiedContext` | 内存（由阶段 1 `_load_context()` 构建） |
| **暂存区文件** | `subprocess.run(["git", "diff", "--cached", ...])` | Git 暂存区 |
| **项目根目录** | `cli/main.py` | 命令行参数传入 |
| **pre-commit 标志** | `cli/main.py` | 命令行参数 `--pre-commit` |

---

## 2. 输入结构

### UnifiedContext（统一上下文）

**输入位置**：内存（由阶段 1 `_load_context()` 构建）
**包/模块**：`domain/context.py:UnifiedContext`

```yaml
config: {}                          # config.json 内容（Dict[str, Any]）
prd: PrdParseResult                 # PRD 解析结果
constraints: {}                     # 架构约束（Dict[str, Any]，可选）
task_result: TaskListLoadResult     # 任务列表解析结果（Optional，None 时跳过任务/AC 检查）
claims_list:                        # Claims 列表（List[Claim]）
  - claim_id: "CLAIM-VT-001"       # Claim ID
    related_task: "TASK-VT-001"    # 关联的任务 ID
    code_refs: []                   # 代码文件引用列表（可能含 #L42 行号锚点）
    test_refs: []                   # 测试文件引用列表
manifest: RawInputManifest          # 加载清单（可选）
human_decisions: {}                 # 人类决策（可选）
config_prefix: "VT"                 # 项目前缀
is_draft: false                     # 是否草稿模式
```

### 暂存区文件集合

**输入位置**：内存（由 `subprocess.run(["git", "diff", "--cached", "--name-only"])` 获取）
**包/模块**：`cli/analyze/pipeline.py`（inline）

```yaml
staged_files:                       # 暂存区文件路径集合
  - "src/vibe_tracing/cli/main.py"
  - "tests/test_cli.py"
  - ".vibetracing/claims/CLAIM-VT-001.json"
```

---

## 3. 处理逻辑

阶段 2 的入口在 `pipeline.py` 中内联，核心业务逻辑在 `domain/gate/claim_coverage.py` 中实现。

### 步骤 1：获取暂存区文件

调用模块：`cli/analyze/pipeline.py`（inline subprocess）

执行 `git diff --cached --name-only` 获取当前暂存区中的所有文件路径列表。失败时降级为空集合（`set()`），记录 `vt_logger.warning("staged_files_unavailable", ...)`。

---

### 步骤 2：调用业务逻辑

调用模块：`domain/gate/claim_coverage.py:check_claim_coverage()`

仅在 `is_pre_commit=True` 时调用。非 pre-commit 模式跳过，`exit_code` 保持 `None`。

---

### 步骤 3：白名单与治理边界过滤

调用模块：`domain/gate/claim_coverage.py:_filter_business_files()`

从暂存区文件中过滤掉以下白名单文件，剩余文件为"业务代码文件"：
- 治理输入文件（从 `ctx.config` 动态构建：`config.json`、`prd.md`、`task_list.json`、`architecture_constraints.json`、`human_decisions.json`）
- Claims 目录下的文件（`.vibetracing/claims/` 前缀）
- Git 目录（`.git/` 前缀）
- 输出目录（`output/` 前缀）

然后通过 `load_boundary(ctx.constraints)` + `is_in_scope()` 过滤治理边界外文件。`ctx.constraints` 为 `None` 时返回默认空边界（不做边界过滤）。

---

### 步骤 4：幽灵代码检测

调用模块：`domain/gate/claim_coverage.py:_detect_ghost_files()`

使用 Python set 差集操作：`business_files - {ref.split("#")[0] for claim in ctx.claims_list for ref in claim.code_refs}`

关键细节：`code_refs` 可能包含行号锚点（如 `"src/foo.py#L42"`），必须用 `.split("#")[0]` 去除后再做集合运算。

判定逻辑：若存在未被 Claim 覆盖的文件（幽灵代码），门禁阻断，返回退出码 1。

---

### 步骤 5：任务覆盖检查

调用模块：`domain/gate/claim_coverage.py:_check_task_coverage()`

从 `ctx.claims_list` 构建"代码文件 → 关联任务 ID"映射，检查每个任务 ID 是否存在于 `ctx.task_result.tasks` 中。

判定逻辑：若 `ctx.task_result` 为 `None`，跳过检查。若代码文件关联的任务 ID 在 task list 中不存在，门禁阻断，返回退出码 1。

---

### 步骤 6：AC 新鲜度检查

调用模块：`domain/gate/claim_coverage.py:_check_ac_freshness()`

从 `ctx.task_result.tasks` 提取每个任务引用的 AC ID，检查是否在 `ctx.prd.requirements` 中定义。使用 dataclass 遍历（`{ac.ac_id for req in ctx.prd.requirements for ac in req.acceptance_criteria}`），无需 regex。

判定逻辑：若 `ctx.task_result` 为 `None`，跳过检查。若任务引用的 AC 在 PRD 中不存在，产生**警告**（不阻断门禁）。

---

## 4. 输出结构

**输出类型**：`ClaimCoverageResult`
**输出位置**：内存（通过函数返回值传递到 `pipeline.py`）

### ClaimCoverageResult

**包/模块**：`domain/gate/claim_coverage.py:ClaimCoverageResult`

```yaml
ghost_files:                        # 幽灵代码文件集合（空 = 通过）
  - "src/unclaimed.py"
task_coverage_blocked:              # 任务覆盖阻断项（空 = 通过）
  - "反向覆盖检查阻断：以下代码文件的覆盖任务不存在于 task_list.json 中：..."
ac_freshness_warnings:              # AC 新鲜度警告（空 = 无警告）
  - "AC 新鲜度提醒：以下任务引用的 AC 未在 PRD 中找到：..."
is_pass: true                       # 属性：ghost_files 为空且 task_coverage_blocked 为空时为 True
```

**用途**：`pipeline.py` 根据 `is_pass` 判断是否阻断流水线。`ghost_files` 和 `task_coverage_blocked` 非空时输出到 stderr 并返回退出码 1。`ac_freshness_warnings` 仅输出警告，不阻断。

---

## 5. 异常捕获与日志

### 异常情况

| 异常类型 | 退出码 | 触发条件 |
|----------|--------|----------|
| 门禁阻断（幽灵代码） | 1 | 暂存区存在未被 Claim 覆盖的业务代码文件 |
| 门禁阻断（任务缺失） | 1 | 代码文件关联的任务 ID 在 task_list 中不存在 |

> [!NOTE]
> AC 新鲜度检查失败仅产生警告，不阻断门禁。暂存区获取失败时降级为空集合，记录 warning 日志。

### 日志事件

| 事件名 | 级别 | 触发时机 | 附加字段 |
|--------|------|----------|----------|
| `phase_end` | INFO | 阶段 2 完成 | `phase="integrity_gates"`, `duration_ms`, `gate_result`（"pass" 或 "blocked"）, `exit_code`, `staged_files_count` |
| `staged_files_unavailable` | WARNING | 暂存区获取失败 | `exc`（异常对象） |

### 错误传播

幽灵代码检测或任务覆盖检查失败时，`pipeline.py` 输出错误信息到 stderr 并返回退出码 1。业务逻辑层（`claim_coverage.py`）不做日志记录，仅返回结果对象。

---

## 6. 下游依赖

| 下游模块 | 目标包 | 说明 |
|----------|--------|------|
| **阶段 3** | `cli/analyze/tools.py` | 门禁通过后，接收 `staged_files` 参数，执行 pytest/ruff/bandit/coverage |
| **阶段 7** | `cli/analyze/pipeline.py` | `staged_files` 传递给 `_run_db_analysis()`，用于债务感知判定 |
