# VT 边界收敛 — 前期文档更新执行计划

> 版本：v0.1
> 日期：2026-06-03
> 依据：`output/VT_boundary_convergence_design.md`
> 阶段：前期文档更新（PRD → 架构约束 → 任务列表）

---

## 一、执行顺序

```
PRD 更新（需求层）
    ↓
架构约束更新（设计层）
    ↓
任务列表更新（任务层）
```

三步完成后前期文档就绪，进入开发阶段。

---

## 二、第一步：更新 PRD

### 2.1 REQ-VT-009 重构

**当前标题：** "Claude Code 自举与 Agent / Skill 治理配置"
**新标题：** "项目生命周期管理与工具执行验证"

**当前描述：** 围绕 Claude Code Bootstrap 的自举配置、subagent 治理、skill 审查。
**新描述：** 围绕项目从前期设计到开发验证的完整生命周期管理，包括项目配置定型（finalize）、VT 自主执行验证工具、Claim 可信度判定。

### 2.2 现有 AC 变更

| AC | 当前标题 | 变更类型 | 变更说明 |
|---|---|---|---|
| AC-VT-009-01 | MVP 必须明确 Claude Code 首选执行环境 | 移除 | 不再管控 Agent 运行环境 |
| AC-VT-009-02 | 自举过程必须产生可追踪治理产物 | 移除 | 不再有自举过程 |
| AC-VT-009-03 | subagent 职责和 skill 使用必须可审查 | 移除 | 不再管控 Agent 配置 |
| AC-VT-009-04 | 架构约束变更必须显式治理 | 保留微调 | 改为"架构约束必须声明项目语言和可用验证工具" |
| AC-VT-009-05 | 目录结构配置化与引擎解耦 | 保留不变 | 与收敛无关 |
| AC-VT-009-06 | 自身治理变更生命周期契约 | 保留不变 | 与收敛无关 |
| AC-VT-009-07 | 零提示词 AI 引导与脚手架机制 | 保留不变 | 已在前期更新中修正 |

### 2.3 新增 AC

| AC ID | 标题 | 验收条件 |
|-------|------|----------|
| AC-VT-009-08 | 项目配置定型必须从架构约束获取语言和工具 | 运行 `vt finalize` 时，VT 从 architecture_constraints.json 的 project.language 和 language_tool_matrix 读取语言及工具配置，写入 config.json。架构约束中无 language 时必须报错退出。 |
| AC-VT-009-09 | VT 必须能自行执行 Claim 关联的验证工具 | 运行 `vt analyze` 时，VT 根据 config.json 中的 validation_tools 和 language_tool_matrix 中的命令模板，自行执行 pytest/coverage/ruff/mypy/bandit 等工具并捕获输出。VT 不读取 Agent 放置的报告文件。 |
| AC-VT-009-10 | 工具执行失败时必须精确反馈 | 工具未安装、测试路径不存在、执行超时等场景下，VT 必须通过 stderr 输出具体错误信息，包含修复建议。 |
| AC-VT-009-11 | 无工具验证证据的 Claim 必须降级 | Claim 声明完成但无 VT 执行的工具证据支撑时，必须标记为 low_confidence，门禁不得将其判定为通过。 |

### 2.4 同步更新

- PRD 中 SCENE-VT-008（Claude Code bootstrap 治理场景）：移除或改写为"项目配置定型场景"
- PRD 附录中 bootstrap 相关工作流描述：移除
- PRD 状态标签：从 frozen 改为 draft（因为需求变更）

---

## 三、第二步：更新架构约束

### 3.1 移除项（与 MOD-VT-011 Bootstrap 全部相关）

#### 模块边界

| 位置 | 内容 | 操作 |
|------|------|------|
| MOD-VT-011 定义（357-392行） | 整个 claude_code_bootstrap_adapter 模块 | 移除整个模块 |
| MOD-VT-001 allowed_to_call | 包含 MOD-VT-011 | 从列表中移除 MOD-VT-011 |
| MOD-VT-009 allowed_to_call | 包含 MOD-VT-011 | 从列表中移除 MOD-VT-011 |

#### 依赖规则

| 规则 ID | 标题 | 操作 |
|---------|------|------|
| DEP-VT-006 | Claude Code 是首选 Runtime，不是 Core 强依赖 | 移除 related_modules 中的 MOD-VT-011；整体规则可考虑保留（核心原则仍有价值）或移除 |

#### 数据流规则

| 规则 ID | 标题 | 操作 |
|---------|------|------|
| FLOW-VT-007 | Claude Code 自举输出必须进入治理文件 | 移除整条规则 |
| FLOW-VT-008 | Subagent 不得直接覆盖架构约束 | 移除整条规则 |

#### 存储规则

| 规则 ID | 标题 | 操作 |
|---------|------|------|
| STORE-VT-005 | Claude Code 自举配置必须文件化 | 移除整条规则 |

#### 错误处理规则

| 规则 ID | 标题 | 操作 |
|---------|------|------|
| ERR-VT-006 | Claude Code 自举配置缺失必须降级 | 移除整条规则 |

#### 日志规则

| 规则 ID | 标题 | 操作 |
|---------|------|------|
| LOG-VT-004 | Claude Code 自举运行必须记录关键元数据 | 移除整条规则 |

#### 安全规则

| 规则 ID | 标题 | 操作 |
|---------|------|------|
| SEC-VT-005 | Subagent 不得越权修改治理边界 | 移除整条规则 |

#### 技术约束

| 约束 ID | 标题 | 操作 |
|---------|------|------|
| TECH-VT-006 | MVP 提供 Claude Code 自举配置 | 移除整条规则 |

#### 禁止模式

| 模式 ID | 标题 | 操作 |
|---------|------|------|
| FORBID-VT-008 | Claude Code 自举不可追踪 | 移除整条规则 |
| FORBID-VT-009 | Subagent 静默修改架构约束 | 移除整条规则 |

#### 质量门禁

| 门禁 ID | 标题 | 操作 |
|---------|------|------|
| GATE-VT-013 | Claude Code 自举配置必须可审查 | 移除整条规则 |
| GATE-VT-014 | 架构约束变更建议必须显式记录 | 移除整条规则 |

#### 原则

| 原则 ID | 标题 | 操作 |
|---------|------|------|
| PRINCIPLE-VT-016 | MVP 默认以 Claude Code 作为首选 Agent Runtime | 移除整条原则 |
| PRINCIPLE-VT-017 | 自举产物必须可追踪 | 移除整条原则 |

### 3.2 新增项

#### 模块定义

**MOD-VT-012：tool_execution_engine**

```json
{
  "module_id": "MOD-VT-012",
  "name": "tool_execution_engine",
  "responsibility": "根据 config.json 中的 validation_tools 和架构约束中的 language_tool_matrix，执行验证工具（pytest、coverage、ruff、mypy、bandit）并捕获输出。只能执行白名单中的工具，命令参数从模板替换生成，不接受任意命令。",
  "allowed_to_call": ["MOD-VT-005"],
  "forbidden_to_call": ["MOD-VT-007"],
  "owned_data": ["tool_execution_result"],
  "must_not_own_data": ["gate_decision", "evidence_truth"],
  "related_requirements": ["REQ-VT-009", "REQ-VT-002"]
}
```

**MOD-VT-013：project_finalizer**

```json
{
  "module_id": "MOD-VT-013",
  "name": "project_finalizer",
  "responsibility": "从架构约束中读取 project.language 和 language_tool_matrix，写入 config.json。一次性命令，执行前校验架构约束完整性，执行后 config.json 不再被修改。",
  "allowed_to_call": [],
  "forbidden_to_call": ["MOD-VT-007"],
  "owned_data": [],
  "must_not_own_data": ["gate_decision", "evidence_truth"],
  "related_requirements": ["REQ-VT-009"]
}
```

#### 新增原则

**PRINCIPLE-VT-018：工具执行主权**

> VT 只采信自己执行的工具结果作为高可信度证据。Agent 自报的完成状态、自行放置的报告文件，不得作为门禁判定的充分依据。

#### 新增技术约束

**TECH-VT-007：语言工具矩阵**

> 架构约束必须包含 language_tool_matrix 顶层字段，定义每种编程语言可用的验证工具、默认命令模板、输出格式和通过条件。VT 只能执行矩阵中定义的工具。

#### 新增依赖规则

**DEP-VT-008：工具执行白名单**

> VT 执行验证工具时，命令必须从 language_tool_matrix 的模板生成，只替换路径占位符。不得执行模板之外的任意命令，不得使用管道、链式命令或 shell 特殊字符。

#### 新增数据流规则

**FLOW-VT-009：项目配置定型单向流**

> 架构约束 → finalize → config.json → analyze。config.json 只在 init 和 finalize 时写入，analyze 只读不写。数据流单向，无环路。

### 3.3 同步更新

- `.vibetracing/architecture_constraints.base.json`：同步所有变更
- 架构约束 Schema（`architecture_constraints.schema.json`）：新增 language_tool_matrix 字段定义

---

## 四、第三步：更新任务列表

### 4.1 标记移除的任务（Bootstrap 相关，当前均为 todo）

| Task ID | 标题 | 操作 |
|---------|------|------|
| TASK-VT-023 | 定义 Claude Code 自举配置 Schema 与治理契约 | 标记 cancelled |
| TASK-VT-024 | 创建 Claude Code 自举 subagent 与 skill 配置初版 | 标记 cancelled |
| TASK-VT-025 | 实现 Claude Code Bootstrap Adapter 配置读取与校验 | 标记 cancelled |
| TASK-VT-026 | 实现 Claude Code 自举产物证据规范化 | 标记 cancelled |
| TASK-VT-027 | 实现架构约束变更建议治理记录 | 标记 cancelled |
| TASK-VT-028 | 将 Claude Code 自举状态纳入报告、Dashboard 与质量门禁 | 标记 cancelled |

### 4.2 新增阶段

**PHASE-VT-009：边界收敛与工具执行验证**

### 4.3 新增任务

| Task ID | 标题 | Phase | Priority | 关联 AC | 关联模块 |
|---------|------|-------|----------|---------|----------|
| TASK-VT-036 | 移除 Claude Code Bootstrap 模块及所有架构约束引用 | PHASE-VT-009 | must | — | MOD-VT-011 |
| TASK-VT-037 | 在架构约束中新增 language_tool_matrix 及相关 Schema | PHASE-VT-009 | must | AC-VT-009-04 | MOD-VT-013 |
| TASK-VT-038 | 实现 vt finalize 命令 | PHASE-VT-009 | must | AC-VT-009-08 | MOD-VT-013 |
| TASK-VT-039 | 实现 VT 工具执行引擎（白名单 + 命令模板 + 超时控制） | PHASE-VT-009 | must | AC-VT-009-09 | MOD-VT-012 |
| TASK-VT-040 | 实现 Claim 可信度判定与 low_confidence 标记 | PHASE-VT-009 | must | AC-VT-009-11 | MOD-VT-005, MOD-VT-006 |
| TASK-VT-041 | 实现工具执行 stderr 反馈机制 | PHASE-VT-009 | should | AC-VT-009-10 | MOD-VT-012 |
| TASK-VT-042 | 更新 evidence_index_builder 移除 tool_reports 目录依赖 | PHASE-VT-009 | must | — | MOD-VT-005 |
| TASK-VT-043 | 端到端测试：finalize → analyze → 工具执行 → 证据生成 | PHASE-VT-009 | must | AC-VT-009-08, AC-VT-009-09, AC-VT-009-11 | — |

### 4.4 受影响的现有任务

| Task ID | 标题 | 影响说明 |
|---------|------|----------|
| TASK-VT-009 | 实现工具输出规范化适配器 | 需重写：从"解析已有报告文件"改为"执行命令并解析输出" |
| TASK-VT-018 | 实现 CLI analyze 命令 | 需扩展：新增执行验证阶段、finalize 前置检查 |

---

## 五、变更统计

| 文档 | 移除 | 修改 | 新增 |
|------|------|------|------|
| PRD | 3 个 AC | 1 个 AC + REQ-VT-009 标题描述 | 4 个 AC |
| 架构约束 | 1 个模块 + 14 条规则 + 2 条原则 | 1 条依赖规则 | 2 个模块 + 1 条原则 + 1 条技术约束 + 1 条依赖规则 + 1 条数据流规则 |
| 任务列表 | 6 个任务（标记 cancelled） | 2 个任务 | 1 个阶段 + 8 个任务 |
