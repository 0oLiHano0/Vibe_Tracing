# Phase 8: 架构约束基线校验重构 — Git 单一基线方案

## 一、业务目标与设计哲学

### 1.1 问题本质

当前系统通过比对两个物理文件来检测架构漂移：
- `docs/architecture_constraints.json`（当前状态，agent 可修改）
- `.vibetracing/architecture_constraints.base.json`（基线状态，人工维护）

这种设计引入了**双重事实来源**：两个文件描述同一件事（"架构约束应该是什么"），但维护路径完全不同。base.json 从不被代码写入，纯靠人工同步，违反了 VT 自己的单一事实来源原则。

### 1.2 业务目标重新定义

VT 的架构约束治理不是"阻止变更"，而是"暴露变更"：

1. **暴露偏离**：AI agent 可能静默修改 constraints.json，系统必须检测并暴露
2. **人类审批**：架构约束可以变更，但必须记录在 `architecture_change_log.md` 中
3. **不让 agent 自证**：agent 不需要证明自己没改过，系统通过客观机制检测

因此，GATE-VT-014 的核心语义是：
> "架构约束文件是否被改过？如果改了，人类是否已经审批？"

### 1.3 设计前提

- **非 Git 项目 = 不可管理的项目**。VT 的全链条（commit hash、merge gate、stale file 检测）天然绑定 Git。非 Git 环境不做降级支持，直接报错。
- **base.json 是过度设计**。它引入了物理文件同步成本，而 Git 已经是项目的事实来源。

---

## 二、方案设计

### 2.1 核心思路

用 **config.json 中的 SHA256 哈希** 作为快路径检测，用 **Git commit 历史** 作为基线重建手段，彻底删除 `architecture_constraints.base.json`。

**职责分离**：analyze 只读检测，finalize 验证并写入。这是整个方案的核心架构决策。

| 职责 | vt analyze | vt finalize |
|---|---|---|
| 检测指纹变化 | 是 | 是 |
| 输出 diff 详情（修复指南） | 是 | 否 |
| 验证 change_log 时间线 | 否 | 是 |
| 更新 hash 检查点 | 否 | 是 |
| 判定通过/不通过 | 否（只输出警告） | 是（验证失败则拒绝） |

**设计原则**：
- VT 不判断变更是否合理（不做自证），只判断"变更日志有没有被同步更新"
- 非恶意场景：agent 意外修改约束时，不会同步修改 change_log.md，因此会被拦截
- 合理变更场景：人类修改约束并更新 change_log.md，通过 finalize 锁定新状态
- 无交互：不需要人类输入 agree 或任何额外操作
- analyze 只读不写：符合 FLOW-VT-009（config.json 只在 init 和 finalize 时写入）

### 2.2 生命周期

```
                    vt finalize
                         │
                         ▼
          ┌──────────────────────────────┐
          │ config.json                  │
          │   architecture_constraints_  │  ← SHA256 指纹
          │     hash: "a1b2c3..."        │
          │   finalize_git_commit:       │  ← Git 版本号
          │     "abc123..."              │
          │   finalize_constraints_path: │  ← 文件相对路径
          │     "docs/architecture_...   │
          └──────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
   agent 工作        vt analyze       vt finalize
   (可能意外修改     (只读检测)       (验证并写入)
    constraints)
        │                │                │
        ▼                ▼                ▼
   constraints      指纹比对          指纹比对
   被修改           不匹配→           不匹配→
                    输出 diff         验证 change_log
                    + 修复指南        ┌─────┴─────┐
                    不判定通过/不通过  │           │
                                  验证通过    验证失败
                                     │           │
                                  更新 hash    拒绝更新
                                  写入 config  输出修复指南
```

### 2.3 analyze 的行为（只读）

```
constraints 指纹一致？
├─ 是 → 通过（无变更），不输出任何架构治理信息
└─ 否 → 输出警告 + 修复指南：
         1. 通过 git show 还原旧版本，逐条对比，列出变更的规则
         2. 提示："请在 docs/architecture_change_log.md 中记录变更原因，
                   然后运行 vt finalize 锁定新状态"
         3. 不判定通过/不通过，不更新 hash
         4. GATE-VT-014 仍然输出为 "unclear"（而非 violated）
            因为判定权在 finalize，analyze 只负责暴露
```

**修复指南示例**：
```
检测到架构约束文件 (docs/architecture_constraints.json) 自定稿后发生以下变更：
  - MODIFY: module_boundaries.MOD-VT-001
  - ADD: dependency_rules.DEP-VT-003

请在 docs/architecture_change_log.md 中记录变更原因，
然后运行 vt finalize 锁定新状态。
```

### 2.4 finalize 的行为（验证并写入）

```
constraints 指纹一致？
├─ 是 → 已是最新，无需更新，直接返回
└─ 否 → 还原旧版本，逐条对比
         │
         diff 为空？（格式变化但规则没变）
         ├─ 是 → 跳过 change_log 验证，直接更新 hash，写入 config.json
         └─ 否 → 检查未提交变更：constraints.json 是否有未暂存/未提交的改动
                  - 有 → 拒绝 finalize（exit 1），提示：
                    "constraints.json 存在未提交变更，请先 git add + git commit 后再运行 vt finalize"
                  - 无 → 进入 change_log 验证：
                     1. 找到 constraints.json 最后一次变更的 commit（commit X）
                     2. 检查 change_log.md 是否满足以下任一条件：
                     a. 和 constraints 在同一个 commit 中被修改
                     b. 在 commit X 之后被修改过
                  4. 满足任一 → 更新 hash 和 commit，写入 config.json
                  5. 都不满足 → 拒绝更新，输出修复指南
```

**finalize 拒绝时的输出示例**：
```
Error: 检测到架构约束被修改，但 docs/architecture_change_log.md 未同步更新。
请在 change_log.md 中记录变更原因后重新运行 vt finalize。
变更的规则：MOD-VT-001 (modify), DEP-VT-003 (add)
```

### 2.5 变更清单

#### [DELETE] `.vibetracing/architecture_constraints.base.json`
彻底移除物理基线文件。

#### [MODIFY] `src/vibe_tracing/cli.py` — `run_finalize()`
在现有逻辑末尾（写入 `language` 和 `validation_tools` 之后），新增：

1. 计算 `docs/architecture_constraints.json` 的 SHA256 哈希
2. 与 config.json 中已存储的 hash 比对
3. 一致 → 已是最新，打印提示，返回
4. 不一致 → 执行 change_log 时间线验证（见下方验证逻辑）
5. 验证通过 → 将以下三个字段写入 config.json：
   - `architecture_constraints_hash`：当前 SHA256 哈希
   - `finalize_git_commit`：当前 Git HEAD commit（`git rev-parse HEAD`，失败则写入 null）
   - `finalize_constraints_path`：constraints 文件的相对路径（如 `"docs/architecture_constraints.json"`），供后续 `git show <commit>:<path>` 使用
6. 验证不通过 → 报错（exit 1），拒绝更新，输出修复指南

幂等逻辑调整：
- 如果已 finalize 且语言/工具匹配 + hash 匹配 → 打印 "Already finalized"，返回
- 如果已 finalize 且语言/工具匹配 + hash 不匹配 → 进入 change_log 验证流程
- 如果 constraints 内容变了导致语言/工具也变了 → 现有冲突检测逻辑不变

#### [MODIFY] `src/vibe_tracing/architecture_change_proposal.py` — `check_governance()`
重写为只读检测逻辑。不再判定通过/不通过，只输出 diff 详情和修复指南。

```python
def check_governance(self, start_counter=1):
    """只读检测架构约束漂移，不判定通过/不通过。"""
    warnings = []
    risks = []
    gaps = []

    # 1. 读取 config.json 中的 hash
    stored_hash = self.raw_loader.config_data.get("architecture_constraints_hash")
    if not stored_hash:
        # 未 finalize，跳过漂移检查
        return {"is_valid": True, "errors": [], "warnings": [], "risks": [], "gaps": []}

    # 2. 计算当前 constraints 的 hash
    current_hash = sha256(self.constraints_path.read_bytes())
    if current_hash == stored_hash:
        # 快路径：无漂移
        return {"is_valid": True, "errors": [], "warnings": [], "risks": [], "gaps": []}

    # 3. 慢路径：hash 不匹配，通过 git 重建基线，输出 diff 详情
    finalize_commit = self.raw_loader.config_data.get("finalize_git_commit")
    finalize_constraints_path = self.raw_loader.config_data.get("finalize_constraints_path")
    if not finalize_commit or not finalize_constraints_path:
        warning = "架构约束文件已变更，但无定稿记录（finalize 信息缺失），请运行 vt finalize。"
        warnings.append(warning)
        risks.append({...severity: "should"...})
        return {"is_valid": True, "errors": [], "warnings": warnings, "risks": risks, "gaps": gaps}

    # git show 获取定稿时刻的基线内容（使用 finalize 时记录的路径）
    base_content = git_show(finalize_commit, finalize_constraints_path)
    base_data = json.loads(base_content)
    curr_data = json.loads(self.constraints_path.read_text())

    # 4. 逐条规则对比，找出差异
    diffs = self._find_differences(base_data, curr_data)
    if not diffs:
        # 格式变化但规则没变，提示运行 finalize 更新 hash
        warning = "架构约束文件格式已变更（无规则变化），请运行 vt finalize 更新检查点。"
        warnings.append(warning)
        return {"is_valid": True, "errors": [], "warnings": warnings, "risks": risks, "gaps": gaps}

    # 5. 输出 diff 详情 + 修复指南
    changed_rules = [f"  - {d['action'].upper()}: {d.get('rule_id') or d['path']}" for d in diffs]
    rule_list = "\n".join(changed_rules)

    warning = (
        f"检测到架构约束文件自定稿后发生以下变更：\n{rule_list}\n\n"
        "请在 docs/architecture_change_log.md 中记录变更原因，\n"
        "然后运行 vt finalize 锁定新状态。"
    )
    warnings.append(warning)
    risks.append({...severity: "should"...})
    gaps.append({...item_type: "architecture_constraints_changed"...})

    # 始终返回 is_valid=True，判定权在 finalize
    return {"is_valid": True, "errors": [], "warnings": warnings, "risks": risks, "gaps": gaps}
```

**关键设计点**：
- `is_valid` 始终为 True，analyze 不做通过/不通过判定
- GATE-VT-014 在 `architecture_compliance_checker.py` 中的处理：当 `check_governance` 返回 warning 时，GATE-VT-014 标记为 "unclear"（而非 "violated"），触发 GATE-VT-007 的保守门禁行为（fail 但不 blocked）
- 这确保了"暴露但不阻断"——agent 收到警告和修复指南，可以自行修正

#### [MODIFY] `src/vibe_tracing/cli.py` — `run_finalize()` 中的 change_log 验证逻辑

```python
def _validate_constraints_change(project_root, constraints_path, finalize_commit, finalize_constraints_path):
    """验证 constraints 变更是否需要 change_log 审批。
    返回 (passed, message)。

    两个路径参数的区别：
    - constraints_path：当前文件的实际路径，用于读取当前内容和查 git log
    - finalize_constraints_path：finalize 时记录的路径，用于 git show 还原历史版本
      （文件可能已被 rename，当前路径在历史 commit 中不存在）
    """
    # 1. 还原旧版本，逐条对比
    #    git show 用 finalize 时的路径定位历史版本
    base_content = git_show(finalize_commit, finalize_constraints_path)
    base_data = json.loads(base_content)
    #    当前内容用当前路径读取
    curr_data = json.loads(constraints_path.read_text())
    diffs = find_differences(base_data, curr_data)

    # 2. diff 为空 → 格式变化，无需 change_log 审批
    if not diffs:
        return True, "格式变化（无规则变更），直接更新检查点"

    # 3. diff 不为空 → 检查未提交变更
    if git_has_uncommitted_changes(constraints_path):
        return False, (
            "constraints.json 存在未提交变更，"
            "请先 git add + git commit 后再运行 vt finalize。"
        )

    # 4. 验证 change_log 时间线
    change_log_path = project_root / "docs" / "architecture_change_log.md"
    last_change_commit = git_last_commit_touching(constraints_path)
    if not last_change_commit:
        return False, "无法确定 constraints.json 的变更历史"

    # 5. 同一 commit → 通过
    log_last_commit = git_last_commit_touching(change_log_path)
    if log_last_commit == last_change_commit:
        return True, "change_log.md 与 constraints.json 在同一 commit 中被修改"

    # 6. change_log 在 constraints 变更之后被修改 → 通过
    if git_file_modified_after(change_log_path, last_change_commit):
        return True, "change_log.md 在 constraints 变更之后被更新"

    # 7. 都不满足 → 拒绝
    changed_rules = [f"  - {d['action'].upper()}: {d.get('rule_id') or d['path']}" for d in diffs]
    rule_list = "\n".join(changed_rules)
    return False, (
        f"检测到架构约束被修改，但 change_log.md 未同步更新。\n"
        f"变更的规则：\n{rule_list}\n"
        "请在 docs/architecture_change_log.md 中记录变更原因后重新运行 vt finalize。"
    )
```

#### [MODIFY] `src/vibe_tracing/architecture_compliance_checker.py` — GATE-VT-014 处理
调整 GATE-VT-014 对 `check_governance` 结果的处理：
- 有 warning、无 error → GATE-VT-014 标记为 "unclear"（而非 "compliant"）
- 这触发 GATE-VT-007 的保守门禁行为：gate decision = "fail"（警告级别，不阻断）

#### Git 操作封装

需在 `src/vibe_tracing/` 中新建或在现有模块中添加 Git 工具函数：

| 函数 | 作用 | 使用场景 | 对应 Git 命令 |
|---|---|---|---|
| `git_show(commit, path)` | 读取指定 commit 中某文件的内容 | analyze/finalize 还原旧版本做 diff | `git show <commit>:<path>` |
| `git_last_commit_touching(path)` | 找到某文件最后一次被修改的 commit | finalize 时间线验证（用当前路径查 git log） | `git log -1 --format=%H -- <path>` |
| `git_file_modified_after(path, commit)` | 判断某文件在指定 commit 之后是否被修改过 | finalize 时间线验证 | `git log <commit>..HEAD --format=%H -- <path>` 有输出则为 True |
| `git_has_uncommitted_changes(path)` | 判断某文件是否有未提交的变更 | finalize 前置检查 | `git diff --name-only -- <path>` 或 `git diff --cached --name-only -- <path>` 有输出则为 True |

**路径使用说明**：
- `git_show` 使用 `finalize_constraints_path`（finalize 时记录的路径），因为文件可能已被 rename，当前路径在历史 commit 中不存在
- `git_last_commit_touching` 使用当前路径（`constraints_path`），因为 git log 追踪的是文件的完整变更历史，rename 前后的记录都能找到
- `git_files_in_same_commit` 不需要单独的函数，通过分别调用 `git_last_commit_touching` 比较两个文件的最后 commit hash 即可

#### 测试策略

| 测试类型 | 策略 |
|---|---|
| 单元测试 | Git 操作封装为可注入接口，单元测试中用 mock 替代真实 git 命令 |
| 集成测试 | 在 `tmp_path` 中运行 `git init + add + commit`，测试完整流程 |
| finalize 验证测试 | 测试 change_log 时间线验证的三种分支（同一 commit、后续更新、未更新） |
| analyze 只读测试 | 验证 analyze 不写入 config.json，只输出警告和修复指南 |

测试文件变更：
- `test_finalize.py`：校验 hash 和 commit 写入；校验 change_log 验证通过/拒绝
- `test_architecture_change_proposal.py`：mock Git 操作，验证只读输出
- `test_quality_gates.py`：移除写 base.json 的逻辑
- `test_raw_input_loader.py`：同上
- `test_e2e_finalize_analyze.py`：在真实 git repo 中测试完整流程

---

## 三、边界场景处理

| 场景 | 处理方式 |
|---|---|
| 未 finalize（config.json 中无 hash） | analyze 跳过漂移检查，is_valid=True |
| 非 Git 项目 | finalize 时 `git rev-parse HEAD` 失败，commit 写入 null；analyze 检测到 hash 不匹配时提示"无定稿记录" |
| shallow clone | `git show` 或 `git log` 可能失败，报错误，提示需要完整 clone |
| force push 后旧 commit 被 gc | 同上 |
| constraints.json 路径被 rename | finalize 时记录相对路径到 config.json，git show 使用记录的路径 |
| 文件格式变了但规则没变 | diff 为空，finalize 跳过 change_log 验证，直接更新 hash |
| constraints 有未提交的变更 | finalize 拒绝更新（exit 1），提示先 git commit 后再运行 |
| constraints 和 change_log 在同一个 commit 中被修改 | 视为通过（原子操作） |
| agent 修改了 config.json 中的 hash | hash 匹配，漂移检查通过（属于更高层威胁，不在 VT 范围内） |

---

## 四、验证计划

### 自动化测试
```bash
pytest tests/test_finalize.py
pytest tests/test_architecture_change_proposal.py
pytest tests/test_quality_gates.py
pytest tests/test_raw_input_loader.py
pytest tests/test_e2e_finalize_analyze.py
```

### 手动验证
1. `vibe-tracing init` → `vibe-tracing finalize` → 确认 config.json 写入 hash 和 commit
2. 修改 `docs/architecture_constraints.json`（格式变化，如缩进），不改规则 → `vibe-tracing finalize` → 确认跳过 change_log 验证，直接更新 hash
3. 修改 `docs/architecture_constraints.json`（改规则），不提交、不更新 change_log → `vibe-tracing finalize` → 确认拒绝（exit 1），提示先 commit
4. 提交 constraints 变更，不更新 change_log → `vibe-tracing analyze` → 确认输出警告 + diff 详情 + 修复指南，GATE-VT-014 为 unclear
5. 不更新 change_log → `vibe-tracing finalize` → 确认拒绝更新，输出修复指南
6. 更新 `docs/architecture_change_log.md` → `vibe-tracing finalize` → 确认 hash 更新成功
7. `vibe-tracing analyze` → 确认通过，无重复报告
8. 在同一 commit 中同时修改 constraints 和 change_log → `vibe-tracing finalize` → 确认直接通过
