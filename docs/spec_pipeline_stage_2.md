# 阶段 2 模块详解

## 1. 输入来源

| 来源 | 包/模块 | 文件 |
|------|---------|------|
| **统一上下文** | `domain/context.py:UnifiedContext` | 内存（由阶段 1 `_load_context()` 构建） |
| **暂存区文件** | `subprocess.run(["git", "diff", "--cached", ...])` | Git 暂存区 |

---

## 2. 输入结构

### UnifiedContext（统一上下文）

**输入位置**：内存（由阶段 1 `_load_context()` 构建）
**包/模块**：`domain/context.py:UnifiedContext`

```yaml
config: {}                          # config.json 内容（Dict[str, Any]）
prd: PrdParseResult                 # PRD 解析结果
constraints: {}                     # 架构约束（Dict[str, Any]，可选）
task_result: TaskListLoadResult     # 任务列表解析结果（Optional）
claims_list:                        # Claims 列表（List[Claim]）
  - claim_id: "CLAIM-VT-001"       # Claim ID
    related_task: "TASK-VT-001"    # 关联的任务 ID
    code_refs: []                   # 代码文件引用列表（可能含 #L42 行号锚点）
    test_refs: []                   # 测试文件引用列表
manifest: RawInputManifest          # 加载清单（可选）
human_decisions: {}                 # 人类决策（可选）
config_prefix: "VT"                 # 项目前缀
is_draft: false                     # 是否草稿模式
governance_whitelist:               # 治理文件白名单路径集合（阶段 1 预计算）
  - ".vibetracing/config.json"
  - "docs/prd.md"
governance_boundary: {}             # 治理边界 include/exclude 模式（阶段 1 预计算）
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

阶段 2 的入口在 `pipeline.py` 中内联，核心业务逻辑在 `domain/gate/claim_coverage.py` 中实现。阶段 2 始终执行（无 `is_pre_commit` 条件分支）。

### 步骤 1：获取暂存区文件

调用模块：`cli/analyze/pipeline.py`（inline subprocess）

执行 `git diff --cached --name-only` 获取当前暂存区中的所有文件路径列表。失败时降级为空集合（`set()`），记录 `vt_logger.warning("staged_files_unavailable", ...)`。

---

### 步骤 2：调用幽灵代码检测

调用模块：`domain/gate/claim_coverage.py:detect_ghost_code()`

阶段 2 始终执行，无条件调用 `detect_ghost_code(ctx, staged_files)`。

---

### 步骤 3：白名单与治理边界过滤

调用模块：`domain/gate/claim_coverage.py:_filter_business_files()`

从暂存区文件中过滤掉以下白名单文件，剩余文件为"业务代码文件"：
- 治理输入文件（`ctx.governance_whitelist`，由阶段 1 通过 `build_governance_whitelist(manifest, project_root)` 预计算）
- Claims 目录下的文件（`.vibetracing/claims/` 前缀）
- Git 目录（`.git/` 前缀）
- 输出目录（`output/` 前缀）

然后通过 `is_in_scope(f, ctx.governance_boundary)` 过滤治理边界外文件。`ctx.governance_boundary` 由阶段 1 通过 `load_boundary(project_root, constraints_data)` 预计算。

---

### 步骤 4：幽灵代码检测

调用模块：`domain/gate/claim_coverage.py:_collect_claimed_files()`

使用 Python set 差集操作：`business_files - all_claimed`

其中 `all_claimed = {ref.split("#")[0] for claim in ctx.claims_list for ref in claim.code_refs}`

关键细节：`code_refs` 可能包含行号锚点（如 `"src/foo.py#L42"`），必须用 `.split("#")[0]` 去除后再做集合运算。

判定逻辑：若存在未被 Claim 覆盖的文件（幽灵代码），门禁阻断，返回退出码 1。

---

## 4. 输出结构

**输出类型**：`GhostCodeResult`
**输出位置**：内存（通过函数返回值传递到 `pipeline.py`）

### GhostCodeResult

**包/模块**：`domain/gate/claim_coverage.py:GhostCodeResult`

```yaml
ghost_files:                        # 幽灵代码文件集合（空 = 通过）
  - "src/unclaimed.py"
is_pass: true                       # 属性：ghost_files 为空时为 True
```

**用途**：`pipeline.py` 根据 `is_pass` 判断是否阻断流水线。`ghost_files` 非空时输出到 stderr 并返回退出码 1。

---

## 5. 异常捕获与日志

### 异常情况

| 异常类型 | 退出码 | 触发条件 |
|----------|--------|----------|
| 门禁阻断（幽灵代码） | 1 | 暂存区存在未被 Claim 覆盖的业务代码文件 |

> [!NOTE]
> 暂存区获取失败时降级为空集合，记录 warning 日志。

### 日志事件

| 事件名 | 级别 | 触发时机 | 附加字段 |
|--------|------|----------|----------|
| `ghost_code_blocked` | WARNING | 幽灵代码检测未通过 | `ghost_files`（排序后的文件列表）, `ghost_count` |
| `phase_end` | INFO | 阶段 2 完成 | `phase="integrity_gates"`, `duration_ms`, `gate_result`（"pass" 或 "blocked"）, `exit_code`, `staged_files_count` |
| `staged_files_unavailable` | WARNING | 暂存区获取失败 | `exc`（异常对象） |

### 错误传播

幽灵代码检测失败时，`pipeline.py` 输出错误信息到 stderr 并返回退出码 1。业务逻辑层（`claim_coverage.py`）不做日志记录，仅返回结果对象。

---

## 6. 下游依赖

| 下游模块 | 目标包 | 说明 |
|----------|--------|------|
| **阶段 3** | `infra/tools/executor.py` | 门禁通过后，`execute_from_claims()` 执行 pytest/ruff/bandit/coverage |
| **阶段 7** | `cli/analyze/pipeline.py` | `staged_files` 传递给 `_run_db_analysis()`，用于债务感知判定 |
