# Vibe Tracing 项目自管理规范

## 项目概述

Vibe Tracing (VT) 是一个 AI Coding Agent 的一致性校验框架。VT 自身也由 AI Agent 开发，因此**项目自身也受 VT 治理体系约束**——这是 VT 的核心设计验证：如果 VT 无法治理自身的开发过程，它也无法治理其他项目。

## 核心用户

VT项目的核心用户是AI Coding Agent，也就是你自己。它并不是为了限制你而存在，而是为了给你提供一个工具，帮你检查偏差，并提供指引。

DashBoard是让用户能够快速通过从PRD开始的完整生命周期链条，进行业务判断，以便能快速确认任务的完成情况。

你需要站在你就是用户的角度，通过VT提示的8项反思来思考VT项目。

dashboard的全链条呈现是必须的，因为你的任务最终需要人类（业务人员，没有开发经验，只能凭业务逻辑是否合理来验收），如果没有人类验收，你会一直陷在任务里，所以为了便于人类验收，需要直观的dashboard。

不要尝试设计过度的跳过检查，正确的方向是如何让vt的完整流程足够快而无需跳过，因为跳过会带来人类决策成本上升，一旦人类不作出“任务完成”的决策，你讲永远陷在任务里。

## 当前工作重心

围绕 `docs/refactoring_design.md` 开展。该文档定义了 pipeline 重构的接口契约、实施步骤、变更清单和删除清单。执行前务必阅读。

## 重构阶段原则

1. **不接受技术债务**：不保留向后兼容代码、不保留废弃接口、不保留"先这样以后再改"的妥协。可全量重写，只为最优架构。
2. **设计即目标**：`docs/refactoring_design.md` 和 `docs/architecture_vision.md` 是唯一的设计基线。代码必须向设计对齐，而非设计向代码妥协。
3. **测试代码同等治理**：测试债务与业务债务同级。废弃测试直接删除，不保留 `skip`/`xfail` 标记；测试覆盖缺口按 refactoring_design.md §10 补齐。
4. **删除优先于适配**：当模块被 redesign 标记为"删除"时，直接删除并替换为新实现，不做适配层或兼容包装。
5. **接口变更不留尾巴**：修改模块接口时，所有调用方同步更新，不留 deprecated wrapper。

## 自管理机制

### Pre-commit Hook

`vt init` 安装 `.git/hooks/pre-commit`，在每次 `git commit` 时自动执行：

```sh
#!/bin/sh
set -e
# Vibe Tracing Git Guard
"<python_path>" -m vibe_tracing analyze --pre-commit
```

Hook 执行 Gate 2（幽灵代码检测：staged 业务文件是否被 Claim 覆盖）。门禁失败则阻断提交。

### Agent Claims

所有代码变更必须在 `.vibetracing/claims/` 目录下创建独立的 Claim 文件（`CLAIM-{prefix}-{num}.json`，一任务一文件）。Claim 关联 Task，Task 关联 PRD 的 REQ/AC。未声明 Claim 的业务代码称为"幽灵代码"，会被 Gate 2 阻断。

### 契约文件

- `docs/prd.md` — 需求文档，定义 REQ/AC
- `docs/architecture_constraints.json` — 架构约束，受 SHA256 哈希保护（设计基线，不可被 accept 命令修改）
- `docs/task_list.json` — 开发任务，关联 REQ/AC
- `.vibetracing/config.json` — 项目配置，存储双哈希基线
- `.vibetracing/human_decisions.json` — 人类决策记录（accept/risk/gap 决策），由 `vt accept` 和 Dashboard 写入

> [!CAUTION]
> VT项目自身的prd.md、architecture_constraints.json等与init阶段的src/vibe_tracing/templates，还有src/vibe_tracing/schemas，存在关联性关系，需要考虑是否关联更新。

### 门禁链路

```
vt finalize（设计阶段）
  → PRD↔Architecture 映射校验 + 双哈希锁定

vt analyze（开发阶段）
  → Stage 2（前置条件）：Gate 2 幽灵代码检测（staged 代码 vs staged claims）
  → Stage 7：db.check_* 分析查询
  → Stage 9：Gate 3 门禁判定（AC 覆盖、测试通过、架构合规等）
```

详见 `docs/refactoring_design.md` §3。

## 开发工作流

### 正常流程（必须遵守）

1. **更新 PRD**：在 `docs/prd.md` 中添加/修改 REQ 或 AC
2. **更新架构约束**（如需）：在 `docs/architecture_constraints.json` 中添加模块或规则
3. **执行 `vt finalize`**：锁定设计基线（PRD↔Arch 映射校验 + 双哈希）
4. **创建 Task**：在 `docs/task_list.json` 中添加 task，关联 REQ 和 AC
5. **编写代码和测试**
6. **创建 Claim**：在 `.vibetracing/claims/` 下创建 `CLAIM-{prefix}-{num}.json`，关联 task，引用 code_refs 和 test_refs
7. **`git add` + `git commit`**：hook 自动执行门禁校验

### 如何跳过自管理（仅限紧急情况）

> [!CAUTION]
> 跳过自管理是**例外而非常态**。每次跳过都应在后续补全 Claim 和门禁校验。

**场景 1：Hook 阻断了合法提交**

如果 Gate 2 错误地阻断了合法代码（如白名单遗漏），可以临时跳过 hook：

```sh
git commit --no-verify -m "描述原因"
```

**后续必须**：
- 分析 hook 误报原因
- 修复 hook 逻辑或更新白名单
- 补充 Claim 文件（.vibetracing/claims/CLAIM-*.json）
- 运行 `vt analyze` 确认门禁通过

**场景 2：批量重构，逐文件创建 Claim 不现实**

如果改动涉及大量文件（如全局重命名），可以先提交再补 Claim：

```sh
# 1. 跳过 hook 提交代码
git commit --no-verify -m "refactor: 批量重命名 [待补 claim]"

# 2. 补充 claims
# 在 .vibetracing/claims/ 下创建 CLAIM-*.json 文件

# 3. 单独提交 claims
git add .vibetracing/claims/CLAIM-*.json
git commit -m "chore: 补充重构 claims"

# 4. 运行完整 analyze 验证
vt analyze
```

**场景 3：修改设计文件（PRD/Constraints）**

设计文件的修改应通过 `vt finalize`，而非直接 commit。如果 finalize 的映射校验阻断了你：

1. 先修复 PRD↔Architecture 映射关系
2. 重新执行 `vt finalize`
3. 正常提交

**场景 4：测试/CI 环境不需要 hook**

CI 环境中 hook 通常不生效（git clone 不复制 hooks）。CI 应独立运行：

```sh
vt analyze  # 完整分析（不含 --gates-only）
```

### `vt accept` 命令说明

`vt accept RULE_ID` 将决策写入 `.vibetracing/human_decisions.json`，**不修改** `architecture_constraints.json`。compliance checker 在 analyze 时从 `human_decisions.json` 读取已接受的规则。

- 只接受 `verification_method == "manual"` 的规则
- 重复 accept 同一规则会提示"已被接受"
- machine 规则被拒绝（需程序验证，无需人工确认）

## 不可跳过的行为

以下行为**任何时候都不可跳过**：

- `vt finalize` 的 PRD↔Architecture 映射校验（死链检测 + MUST 覆盖）+ 双哈希锁定
- Gate 2 的幽灵代码检测（staged 业务文件必须被 Claim 覆盖）
- Claim 的自引用检测（evidence_refs 不能仅指向自身）
- Schema 校验（task_list / constraints / claims 的 JSON Schema）

## 开发阶段与设计阶段的职责边界

| 阶段 | 命令 | 职责 |
|---|---|---|
| 设计阶段 | `vt init` → `vt finalize` | 锁定 PRD + constraints 基线 |
| 开发阶段 | `vt analyze` | 校验 task/claim/code 与基线的一致性 |
| 提交时 | `--pre-commit --gates-only` | 快速校验完整性门禁 |

设计阶段的产物（PRD、constraints）受哈希保护，不可在开发阶段静默修改。开发阶段的产物（task、claim、code）通过声明式校验与设计基线保持一致。

## 运行时日志排错指南

VT 每次运行会生成 JSON Lines 格式的运行日志，位于 `.vibetracing/logs/vt-{timestamp}.jsonl`。日志级别通过 `config.json` 的 `logging.level` 控制，开发阶段默认 `DEBUG`。

### 何时查看日志

- Gate 决策不符合预期时（应该 pass 但 blocked，或反过来）
- 某个 AC/requirement 的覆盖状态不符合预期时
- 架构合规检查结果异常时
- 性能问题排查（哪个阶段耗时异常）
