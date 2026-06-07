# 设计阶段代码审计报告

审计日期：2026-06-07
审核日期：2026-06-07
审计范围：`vt init`、`vt finalize`、pre-commit Gate 2/2.5、模板文件

> [!NOTE]
> 本报告已经过独立审核（见 [design_phase_audit_report_review.md](design_phase_audit_report_review.md)）。D6 误报已修正，L4 已升级为 P1。

---

## 一、死代码（5 处）

| # | 位置 | 说明 | 建议 |
|---|---|---|---|
| D1 | `cli.py:104` | `render_template` 中 `-VT\\\\` 替换是死代码，line 103 的 `-VT\\` 已覆盖该场景（`str.replace` 非贪婪，会正确保留第二个反斜杠） | 删除 line 104 |
| D2 | `cli.py:199` | `_validate_constraints_change` 内 `import json` 重复，模块级（line 11）已导入 | 删除 line 199 |
| D3 | `cli.py:532` | `task_list_path` 变量赋值后从未被 Gate 2/2.5 使用（两门禁各自通过 `git show` 读取） | 删除或改为传参 |
| D4 | `cli.py:572` | Gate 2.5 的 `success` 变量赋值后从未读取（`check()` 始终返回 True） | 改为 `_ , warning_msg =` |
| D5 | `cli.py:113` | `.vibetracing/` 目录重复 mkdir（line 60 已创建） | 删除 line 113 |

---

## 二、逻辑问题

### HIGH（4 处）

| # | 位置 | 问题 | 影响 |
|---|---|---|---|
| L1 | `cli.py` Branch B/D (lines 376-411, 431-467) | **config 先写盘、git 后提交**。若 git commit 或 amend 失败，config.json 已写入新 hash/commit，但 git 历史不一致。失败后返回 0（成功） | `vt analyze` 的反篡改校验可能通过不一致的状态 |
| L4 | `cli.py` Branch C (line 417) | **架构变更审计绕过**：tools 和 content 同时变更时，Branch C 优先命中，只更新 tools 不校验 change_log。开发者可通过同时修改工具配置，将未备案的架构破坏合规地定稿 | MUST 级架构约束可不经 change_log 审计就锁定 |
| L2 | `cli.py:142` | pre-commit hook 硬编码 `python3`，不兼容 venv 和无 `python3` 的系统 | hook 在 venv 环境中静默失败 |
| L3 | `ghost_code_reconciler.py` | Gate 2（阻断型门禁）无任何测试覆盖 | 回归风险高 |

### MEDIUM（5 处）

| # | 位置 | 问题 | 影响 |
|---|---|---|---|
| L5 | `cli.py:40-153` | init 中途失败无回滚，已创建的目录和文件残留，项目处于半初始化状态 | 重跑 init 可恢复，但依赖旧行为 |
| L6 | `ac_freshness_checker.py:77` / `ghost_code_reconciler.py` | `subprocess.run` 未捕获 `FileNotFoundError`（git 不存在时直接 traceback） | 非 git 项目触发未处理异常 |
| L7 | `ghost_code_reconciler.py:54-57` | `agent_claims.json` 格式错误时静默按空处理，所有业务代码被误判为 ghost code | 用户看到大量误报，无提示 claims 文件损坏 |
| L8 | `cli.py:570-571` | Gate 2/2.5 硬编码 `docs/task_list.json` 路径，未使用 `raw_loader.get_path()` 解析的路径 | 自定义路径配置不生效 |
| L12 | `cli.py:82-96` | **config.json 写入时序不当**：config 在其他模板之前写入，中途失败后重跑 init 会静默使用旧 config 值，忽略用户新传入的 --name/--prefix | 半初始化状态下重试时参数被吞 |

### LOW（3 处）

| # | 位置 | 问题 | 影响 |
|---|---|---|---|
| L9 | `cli.py:574` | Gate 2.5 warning 输出到 stdout，Gate 2 error 输出到 stderr，不一致 | pre-commit 框架捕获行为不同 |
| L10 | `cli.py:138-139` | 无 `.git` 目录时 hook 静默跳过，无任何提示 | 用户不知 hook 未安装 |
| L11 | `cli.py:213-222` | `_validate_constraints_change` 只检查 change_log 文件是否存在，不校验内容 | 空文件可通过校验 |

### 不纳入问题项

| 位置 | 原始判定 | 结论 | 原因 |
|---|---|---|---|
| `architecture_constraints.template.json:8` | LOW：language 硬编码 python | **不纳入** | MVP 阶段预期行为，用户/agent 在设计阶段自行覆盖 |

---

## 三、L12 详细分析：config.json 写入时序问题

### 当前执行顺序

```
1. 创建 .vibetracing/ 目录          (line 54-63)
2. 检查 config.json 是否存在         (line 82)
   ├─ 存在 → 读取已有值，忽略用户传入的 --name/--prefix
   └─ 不存在 → 使用用户传入的 --name/--prefix
3. 写入 config.json                  (line 112-117)  ← 其他模板还没写
4. 写入其他 5 个模板文件              (line 119-135)
5. 安装 pre-commit hook             (line 138-147)
```

### 问题场景

**场景 A：首次 init 中途失败**
1. 用户执行 `vt init --name "Foo" --prefix "FO"`
2. config.json 写入成功（step 3）
3. `architecture_constraints.json` 写入失败（step 4，如磁盘满）
4. 项目处于半初始化状态：有 config，无 constraints

**场景 B：重试 init 时参数不同**
1. 用户修复磁盘问题后执行 `vt init --name "Bar" --prefix "BR"`
2. line 82 检测到 config.json 已存在
3. 静默读取旧值 `name=Foo, prefix=FO`，**忽略用户新传入的 `Bar/BR`**
4. 所有模板按旧值生成，用户无感知

### 建议方案

将 config.json 的写入移到所有模板写入之后（step 3 → step 4 之后）。这样：

1. **首次 init 中途失败**：config.json 不存在，重跑 init 时进入 else 分支（line 93），正确使用用户参数
2. **首次 init 成功**：config.json 最后写入，所有模板已就位，状态一致
3. **幂等重跑**：config.json 已存在，读取已有值，模板跳过——行为不变

```python
# 调整后的顺序：
# 1. 写入所有模板文件（config.json 除外）
# 2. 写入 config.json（最后）
# 3. 安装 pre-commit hook
```

这个方案不需要改逻辑分支，只调整写入顺序，副作用最小。

---

## 四、模板问题（1 处）

| # | 位置 | 严重度 | 问题 |
|---|---|---|---|
| T1 | `field_hints.json` | MEDIUM | 缺少 3 个 field key 的修复引导：`task_list.related_modules`、`task_list.related_architecture_constraints`、`agent_claims.evidence_refs` |

### 无问题项

- 所有 JSON 模板语法合法
- PRD 模板 heading 结构与 `PrdParser` 期望一致
- `task_list.template.json` 包含 `all_tasks_must_link_requirements_and_acceptance_criteria: true`
- 占位符（`{{PROJECT_NAME}}` / `{{PROJECT_PREFIX}}` / `{{TODAY}}`）在所有模板中一致
- `architecture_constraints.template.json` 中 `language: "python"` 硬编码——MVP 阶段预期行为，不纳入问题
- `run_init` / `run_finalize` / `_validate_prd_architecture_mapping` 无死锁
- 4 分支结构（A/B/C/D）覆盖完整，无状态遗漏

---

## 五、修复优先级建议

| 优先级 | 编号 | 修复内容 |
|---|---|---|
| P1 | L1 | config 写入时机调整（移到 git commit 之后，或使用临时变量延迟写入） |
| P1 | L4 | 重构 Branch 判定逻辑，确保 hash 变化时必须校验 change_log（不被 tools 变化掩盖） |
| P1 | L12 | config.json 写入顺序移到所有模板之后（消除半初始化重试时参数被吞的问题） |
| P2 | L2 | pre-commit hook 使用 `sys.executable` 替代硬编码 `python3` |
| P2 | L3 | Gate 2 补充测试覆盖 |
| P3 | D1-D5 | 清理死代码 |
| P3 | T1 | 补充 field_hints.json 缺失条目 |
| P3 | L6-L8 | 补充错误处理和路径解析 |

---

## 六、原子化修复计划

### Phase 1：P1 致命/安全缺陷（阻断发布）

#### FIX-001：finalize config 延迟写盘（L1）

**问题**：Branch B/D 在 git commit 之前将 config 写入磁盘，git 失败后返回 0，config 与 git 状态不一致。
**涉及文件**：`src/vibe_tracing/cli.py`
**改动方案**：
1. 在 Branch B（line 376-380）和 Branch D（line 431-437），将 `config_data` 的更新保留在内存中，不立即写盘
2. 将 `json.dump` 移到 `git commit --amend` 成功之后（即 line 409/465 之后）
3. git add 列表中移除 `.vibetracing/config.json`（因为此时文件内容还是旧的）
4. 将 `except` 块从 `print Warning + return 0` 改为 `return 1`，确保 git 失败时函数返回错误码
5. 在 amend 成功后执行最终的 config 写盘 + `git add` + 再次 amend（或合并为一次写盘+amend）

**测试**：新增 `test_finalize_git_failure_returns_error`，mock `subprocess.run` 使 commit 失败，验证返回值为 1 且 config.json 内容未被修改。

#### FIX-002：Branch C 增加 hash 变化校验（L4）

**问题**：tools 和 content 同时变化时，Branch C（`existing_tools != current_tools`）优先命中，跳过 `_validate_constraints_change`。
**涉及文件**：`src/vibe_tracing/cli.py`（line 364-423）
**改动方案**：重构分支判定逻辑为两层判断：
```
if stored_hash != computed_hash:
    # 无论 tools 是否变化，都必须校验 change_log
    _validate_constraints_change(...)
    # 校验通过后更新 hash
if existing_tools != current_tools:
    # 更新 tools
```
具体实现：
1. 将 line 364-423 的三个 `if` 改为：先判断 hash 变化（触发校验+更新），再判断 tools 变化（更新 tools）
2. hash 变化时必须执行 `_validate_constraints_change`，失败则 return 1
3. tools 变化时静默更新（保持现有行为）
4. 两者可同时发生——先校验 hash，再更新 tools，最后统一写盘+commit

**测试**：新增 `test_finalize_tools_and_content_both_changed_requires_changelog`，同时修改 tools 和 constraints 内容但不写 change_log，验证返回 1。

#### FIX-003：init config.json 写入时序调整（L12）

**问题**：config.json 在其他模板之前写入，中途失败后重跑 init 会静默使用旧 config 值。
**涉及文件**：`src/vibe_tracing/cli.py`（`run_init`，line 38-153）
**改动方案**：
1. 将 line 112-117（config.json 写入）移到 line 135 之后（所有模板写完之后）
2. 将 line 82-96（config 存在性检查+值确定）保留在原位——这只是读取/确定值，不写盘
3. 写入顺序变为：模板文件 → config.json → pre-commit hook

**测试**：新增 `test_init_partial_failure_retry_uses_new_params`，模拟首次 init 在写 constraints 时失败，用不同参数重跑 init，验证生成的模板使用新参数。

### Phase 2：P2 规范与测试

#### FIX-004：pre-commit hook 使用 sys.executable（L2）

**问题**：hook 硬编码 `python3`，不兼容 venv 和无 `python3` 的系统。
**涉及文件**：`src/vibe_tracing/cli.py`（line 142）
**改动方案**：
1. 将 hook 模板中的 `python3` 替换为 `{sys.executable}` 占位符
2. 在写入 hook 时用 `sys.executable` 填充实际 Python 路径
3. 确保路径包含空格时被正确引号包裹

**测试**：`test_scaffolding.py` 中新增断言，验证 hook 文件内容包含当前 Python 解释器路径。

#### FIX-005：Gate 2 GhostCodeReconciler 测试覆盖（L3）

**问题**：阻断型门禁无任何测试。
**涉及文件**：新建 `tests/test_ghost_code_reconciler.py`
**改动方案**：覆盖以下场景：
1. 无 claims 文件 + 有 staged 代码文件 → 阻断
2. 有 claims 且 code_refs 匹配 staged 文件 → 通过
3. claims 中引用不存在的文件 → 警告
4. `agent_claims.json` 格式错误 → 友好报错（FIX-007 关联）
5. 无 staged 代码文件 → 跳过

### Phase 3：P3 缺陷清理

#### FIX-006：清理死代码（D1-D5）

**涉及文件**：`src/vibe_tracing/cli.py`、`src/vibe_tracing/ac_freshness_checker.py`
**改动方案**：
| 编号 | 改动 |
|---|---|
| D1 | 删除 `cli.py:104`（`-VT\\\\` 替换行） |
| D2 | 删除 `cli.py:199`（`import json`） |
| D3 | 删除 `cli.py:532`（`task_list_path` 赋值） |
| D4 | `cli.py:572` 改为 `_, warning_msg = freshness_checker.check()` |
| D5 | 删除 `cli.py:113`（重复 mkdir） |

**测试**：运行全量测试确认无回归。

#### FIX-007：claims 文件损坏时友好报错（L7）

**问题**：`agent_claims.json` 格式错误时静默按空处理，导致所有业务代码被误判为 ghost code。
**涉及文件**：`src/vibe_tracing/ghost_code_reconciler.py`（line 54-57）
**改动方案**：
1. 将 `except` 块从 `staged_claims = []` 改为打印明确错误信息：`"Warning: agent_claims.json 格式错误，将按无 claims 处理: {exc}"`
2. 保持降级行为（`staged_claims = []`），但用户能看到原因

**测试**：在 FIX-005 的测试中覆盖此场景。

#### FIX-008：补充 field_hints.json 缺失条目（T1）

**涉及文件**：`src/vibe_tracing/templates/field_hints.json`
**改动方案**：补充 3 条：
- `task_list.related_modules`：提示在 `task` 中添加 `related_modules` 字段并引用 `architecture_constraints.json` 中的模块 ID
- `task_list.related_architecture_constraints`：提示添加逻辑约束引用
- `agent_claims.evidence_refs`：提示添加证据文件引用

**测试**：`test_task_loader.py` 中验证相关错误消息包含修复引导。

#### FIX-009：补充 FileNotFoundError 捕获（L6）

**问题**：`subprocess.run` 调用 git 时未捕获 `FileNotFoundError`。
**涉及文件**：`src/vibe_tracing/ac_freshness_checker.py`、`src/vibe_tracing/ghost_code_reconciler.py`
**改动方案**：在所有 `subprocess.run(["git", ...])` 调用处，将 `except subprocess.CalledProcessError` 扩展为 `except (subprocess.CalledProcessError, FileNotFoundError)`，打印友好提示："git 未安装或不在 PATH 中，跳过 pre-commit 检查。"

**测试**：mock `subprocess.run` 抛出 `FileNotFoundError`，验证优雅降级。

---

### 任务依赖关系

```
FIX-001 ─┐
FIX-002 ─┼─ Phase 1（互不依赖，可并行）
FIX-003 ─┘
          │
FIX-004 ─┐
FIX-005 ─┼─ Phase 2（互不依赖，可并行）
          │
FIX-006 ─┐
FIX-007 ─┤─ FIX-005 依赖 FIX-007（测试中覆盖 claims 损坏场景）
FIX-008 ─┼─ Phase 3（大部分可并行）
FIX-009 ─┘
```
