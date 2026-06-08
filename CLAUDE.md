# Vibe Tracing 项目自管理规范

## 项目概述

Vibe Tracing (VT) 是一个 AI Coding Agent 的一致性校验框架。VT 自身也由 AI Agent 开发，因此**项目自身也受 VT 治理体系约束**——这是 VT 的核心设计验证：如果 VT 无法治理自身的开发过程，它也无法治理其他项目。

## 核心用户

VT项目的核心用户是AI Coding Agent，也就是你自己。它并不是为了限制你而存在，而是为了给你提供一个工具，帮你检查偏差，并提供指引。

DashBoard是让用户能够快速通过从PRD开始的完整生命周期链条，进行业务判断，以便能快速确认任务的完成情况。

你需要站在你就是用户的角度，通过VT提示的8项反思来思考VT项目。

dashboard的全链条呈现是必须的，因为你的任务最终需要人类（业务人员，没有开发经验，只能凭业务逻辑是否合理来验收），如果没有人类验收，你会一直陷在任务里，所以为了便于人类验收，需要直观的dashboard。

不要尝试设计过度的跳过检查，正确的方向是如何让vt的完整流程足够快而无需跳过，因为跳过会带来人类决策成本上升，一旦人类不作出“任务完成”的决策，你讲永远陷在任务里。

## 自管理机制

### Pre-commit Hook

`vt init` 安装 `.git/hooks/pre-commit`，在每次 `git commit` 时自动执行：

```sh
#!/bin/sh
set -e
# Vibe Tracing Git Guard
"<python_path>" -m vibe_tracing analyze --pre-commit --gates-only
```

Hook 执行 Gate 1（防篡改）、Gate 2（幽灵代码检测）、Gate 2.5（AC 新鲜度）。任一门禁失败则阻断提交。

### Agent Claims

所有代码变更必须在 `.vibetracing/agent_claims.json` 中声明对应的 Claim。Claim 关联 Task，Task 关联 PRD 的 REQ/AC。未声明 Claim 的业务代码称为"幽灵代码"，会被 Gate 2 阻断。

### 契约文件

- `docs/prd.md` — 需求文档，定义 REQ/AC
- `docs/architecture_constraints.json` — 架构约束，受 SHA256 哈希保护
- `docs/task_list.json` — 开发任务，关联 REQ/AC
- `.vibetracing/config.json` — 项目配置，存储双哈希基线

> [!CAUTION]
> VT项目自身的prd.md、architecture_constraints.json等与init阶段的src/vibe_tracing/templates，还有src/vibe_tracing/schemas，存在关联性关系，需要考虑是否关联更新。

### 门禁链路

```
git commit
  → pre-commit hook
    → Gate 1: constraints 哈希 + PRD 漂移 + PRD↔Arch 映射
    → Gate 2: 幽灵代码检测（staged 代码 vs staged claims）
    → Gate 2.5: AC 新鲜度（WARNING）
```

## 开发工作流

### 正常流程（必须遵守）

1. **更新 PRD**：在 `docs/prd.md` 中添加/修改 REQ 或 AC
2. **更新架构约束**（如需）：在 `docs/architecture_constraints.json` 中添加模块或规则
3. **执行 `vt finalize`**：锁定设计基线（PRD↔Arch 映射校验 + 双哈希）
4. **创建 Task**：在 `docs/task_list.json` 中添加 task，关联 REQ 和 AC
5. **编写代码和测试**
6. **创建 Claim**：在 `.vibetracing/agent_claims.json` 中声明 claim，关联 task，引用 code_refs 和 test_refs
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
- 补充 agent_claims.json
- 运行 `vt analyze` 确认门禁通过

**场景 2：批量重构，逐文件创建 Claim 不现实**

如果改动涉及大量文件（如全局重命名），可以先提交再补 Claim：

```sh
# 1. 跳过 hook 提交代码
git commit --no-verify -m "refactor: 批量重命名 [待补 claim]"

# 2. 补充 claims
# 编辑 .vibetracing/agent_claims.json

# 3. 单独提交 claims
git add .vibetracing/agent_claims.json
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

## 不可跳过的行为

以下行为**任何时候都不可跳过**：

- `vt finalize` 的 PRD↔Architecture 映射校验（死链检测 + MUST 覆盖）
- Gate 1 的 constraints 哈希校验（防篡改）
- Claim 的自引用检测（evidence_refs 不能仅指向自身）
- Schema 校验（task_list / constraints / claims 的 JSON Schema）

## 开发阶段与设计阶段的职责边界

| 阶段 | 命令 | 职责 |
|---|---|---|
| 设计阶段 | `vt init` → `vt finalize` | 锁定 PRD + constraints 基线 |
| 开发阶段 | `vt analyze` | 校验 task/claim/code 与基线的一致性 |
| 提交时 | `--pre-commit --gates-only` | 快速校验完整性门禁 |

设计阶段的产物（PRD、constraints）受哈希保护，不可在开发阶段静默修改。开发阶段的产物（task、claim、code）通过声明式校验与设计基线保持一致。
