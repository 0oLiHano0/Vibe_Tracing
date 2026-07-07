# Agent Action 消费路径统一设计

> 设计决策文档。解决门禁判定与 Agent 指令数据源分裂问题。

**状态**：**已落地**（PHASE-VT-015 实施完成，VT-190 已删除 6 个旧 collector，三元组链路 `_collect_issue_actions` 已生效）
**定位**：历史架构决策记录（回溯"为什么这么写"时查阅），不再作为待实现设计
**下游关联**：`docs/business_task_reflection_trajectory.md` §2.1.6 跨通道审计以本文档 §2.2 状态分流为 issue 粒度依据

---

## 1. 背景

PHASE-VT-013 重构（VT-180~188）将门禁系统从"文件路径血缘驱动的聚合 3 态"重构为"Task 承诺驱动的 per-issue 5 态纯函数规则引擎"。重构后，门禁判定链路正确运行，但暴露出 **Agent 指令生成链路与门禁判定链路数据源不一致** 的架构问题。

### 症状

运行 `vt analyze` 后，门禁显示 `BLOCKED` 并输出 100+ 条 `[预存]` 历史债务，这些历史债务同时作为 HIGH 优先级 action 发送给 AI Coding Agent。Agent 不应对自己未参与的历史债务负责。

### 根因

```
门禁判定链路:
  engine.detect_all_issues() → DetectedIssue[15 类] → SignalComputer → F() → gate_decision

Agent 指令链路:
  merged_gaps    → _collect_gap_actions()       ─┐
  active_risks   → _collect_risk_actions()       ├─→ agent hints
  violations     → _collect_violation_actions()  ─┘
  gate_reasons   → _collect_gate_reason_actions() ← 兜底补丁
```

两条链路消费不同的数据源。Gate 基于 `DetectedIssue[]`（15 类检测器全量覆盖），Agent 基于原始 `gaps/risks/violations`（仅覆盖 3 类）。`_collect_gate_reason_actions` 是为弥合这一缺口而存在的兜底函数，它将所有 gate_reasons（含 HISTORICAL）无差别地转为 HIGH 优先级 action。

---

## 2. 目标业务逻辑

### 2.1 单一数据源原则

同一份 `(OutputState, IssueSignal, DetectedIssue)[]` 作为 Gate 判定和 Agent 指令的唯一数据源。Gate blocked 必然有对应的 Agent action，悖论从结构上不可能发生。

```
(OutputState, IssueSignal, DetectedIssue)[]
  ──→ Gate 判定（哪些 issue 阻断门禁）
  └──→ Agent action（哪些 issue 需要 Agent 处理 + 执行上下文）
```

### 2.2 状态分流规则

每个 DetectedIssue 经 F() 产出 5 种状态之一。按状态分流给不同消费者：

| 状态 | 含义 | Agent | Dashboard | 理由 |
|------|------|-------|-----------|------|
| CURRENT_BLOCK | 当前变更引入的阻断 | 显示 | 显示 | Agent 必须修 |
| CURRENT_WARNING | 当前变更引入的告警 | 显示 | 显示 | Agent 建议修 |
| HISTORICAL | 已存在、本次未触碰 | 不显示 | 显示 | 人类管理，非 Agent 职责 |
| ACCEPTED | 人类已接受风险 | 不显示 | 显示 | 人类决策，审计留痕 |
| RESOLVED | 已核销/已解决 | 不显示 | 显示 | 完成记录 |

### 2.3 Agent 可修复性分类

VT 是纯静态规则检查系统（无 LLM 集成），AI Coding Agent 通过读取 VT 输出获取行动指令。根据问题性质分为两类：

**Agent 可修复**（代码层面问题，规则明确、修复路径确定）：Agent 直接执行修复。

**Agent 提示人类**（治理层面问题，需要业务上下文和意图理解）：Agent 不生成修复 action，而是输出一条提示"此问题需要人类决策，请通知人类查看 Dashboard"。

### 2.4 全量 issue 明细表

以下为 15 个检测器产出的所有 issue 类型、状态、消费归属。

| # | 检测方法 | issue_type | severity | 问题描述 | Agent 分类 | 修复方式 / 提示内容 |
|---|---------|------------|----------|---------|-----------|-------------------|
| 1 | ghost code | no_claim | BLOCK | 有代码变更但无对应 Claim | Agent 可修复 | 确认变更并生成 Claim（git add 后 VT 自动生成） |
| 2 | dangling claims | chain_broken | BLOCK | Claim 引用了不存在的 ID | Agent 可修复 | 修正引用指向正确的 ID，或删除无效 Claim |
| 3 | claim evidence (test_failed) | task_failed | BLOCK | Claim 关联的测试用例失败 | Agent 可修复 | 修复代码或测试使测试通过 |
| 4 | claim evidence (其他) | task_failed | WARNING | Claim 证据质量不达标 | Agent 可修复 | 补充测试或改进代码 |
| 5 | AC coverage | no_claim | BLOCK | AC 无 Claim 覆盖 | Agent 可修复 | 为 AC 编写实现代码，触发 Claim 自动生成 |
| 6 | invalid refs (不存在) | chain_broken | BLOCK | 引用了不存在的 REQ/AC/MOD/约束 ID | Agent 可修复 | 修正引用或删除无效引用 |
| 7 | invalid refs (错位) | chain_misaligned | BLOCK | 引用存在但层级/模块归属不匹配 | Agent 可修复 | 修正 AC 的父需求归属或模块声明 |
| 8 | must gaps | task_failed | BLOCK | 架构合规 MUST 级 AC 缺口 | Agent 可修复 | 按 gap 描述补全实现和测试 |
| 9 | must risks | chain_broken | BLOCK | 架构合规 MUST 级风险（含自证风险） | Agent 可修复 | 消除风险或补充 suggested_action/business_impact |
| 10 | arch violations | chain_broken | BLOCK | 违反 MUST 级架构规则 | Agent 可修复 | 修改代码使其符合架构约束 |
| 11 | proposal governance | chain_broken | BLOCK | 架构变更未经提案审批 | **人类决策** | Agent 通知人类：需要提交架构变更提案 |
| 12 | should gaps | substandard | WARNING | 架构合规 SHOULD 级缺口 | Agent 可修复 | 建议改进（非强制），按 gap 描述处理 |
| 13 | should risks | substandard | WARNING | 架构合规 SHOULD 级风险 | Agent 可修复 | 建议改进（非强制），评估是否处理 |
| 14 | unclear constraints | substandard | WARNING | 架构约束规则描述不明确 | **人类决策** | Agent 通知人类：约束文档需要澄清 |
| 15 | coverage violations | substandard | WARNING | 代码覆盖率低于 80% 阈值 | Agent 可修复 | 补充测试用例提升覆盖率 |
| 16 | lint violations | substandard | WARNING | 代码风格/lint 违规 | Agent 可修复 | 修复 lint 问题 |
| 17 | isolated tasks | isolated_task | WARNING | 任务无关联需求/AC | **人类决策** | Agent 通知人类：任务需要重新规划关联关系 |

**Agent 可修复：14 类** | **人类决策：3 类**（#11 proposal governance、#14 unclear constraints、#17 isolated tasks）

### 2.5 人类决策类 issue 的 Agent 行为

对于标记为"人类决策"的 3 类 issue，Agent 在 CURRENT 状态下：
- 不生成修复 action
- 输出一条提示：说明问题性质 + 指引人类查看 Dashboard
- 不影响其他 Agent 可修复类 issue 的正常处理

---

## 3. 目标代码逻辑

### 3.1 架构变更

```
当前:
  DetectedIssue[] ──→ Gate 判定
  gaps/risks/violations ──→ _collect_*_actions() ──→ Agent hints (独立链路)
  gate_reasons ──→ _collect_gate_reason_actions() (兜底补丁)

目标:
  (OutputState, IssueSignal, DetectedIssue)[] ──→ Gate 判定
                  └──→ _collect_issue_actions() ──→ Agent hints (统一链路)
                     按 issue_type 分发:
                       Agent 可修复类 → 生成 action（从 PRD/hint/DB 增强上下文）
                       人类决策类     → 生成提示（通知人类查看 Dashboard）
```

### 3.2 删除项

| 删除项 | 文件 | 原因 |
|--------|------|------|
| `_collect_gap_actions()` | actions.py | 被 `_collect_issue_actions()` 替代 |
| `_collect_risk_actions()` | actions.py | 被 `_collect_issue_actions()` 替代 |
| `_collect_violation_actions()` | actions.py | 被 `_collect_issue_actions()` 替代 |
| `_collect_gate_reason_actions()` | actions.py | 兜底函数，不再需要 |
| `_derive_reasons()` | output.py | gate_reasons 概念消除 |
| `gate_reasons` 参数 | formatting.py | 被 (OutputState, IssueSignal, DetectedIssue) 三元组列表替代 |

### 3.3 新增/重构项

**`_collect_issue_actions()`**：消费 `List[Tuple[OutputState, IssueSignal, DetectedIssue]]`（内部过滤仅处理 CURRENT_BLOCK 和 CURRENT_WARNING 状态的 issue），从 `OutputState` 判断 BLOCK/WARNING 以计算 urgency，从 `IssueSignal` 读取 observed 信号，从 `DetectedIssue` 获取 issue_type/reason/item_id 等分发字段。按 issue_type 分发：

1. Agent 可修复类：根据 issue_type 查询 PRD（AC/需求描述）、hint 系统（修复指引）、DB（关联代码/测试），生成带执行上下文的 action dict
2. 人类决策类：生成一条 `type: "human_decision_required"` 的 action，包含问题描述和 Dashboard 指引

上下文增强（PRD 查询、hint 系统、DB 关联）的具体字段映射在实现时按 issue_type 自然写出，不在设计阶段规格化。但需在设计阶段标注增强能力分级，作为实现和测试验收的依据：

| 增强级别 | issue_type | 可查询的数据源 |
|----------|-----------|--------------|
| 深度增强（PRD + DB + hint） | no_claim（AC coverage）、task_failed | PRD 中 AC/需求描述、DB 中关联代码和已有测试、hint 修复指引 |
| 中度增强（hint + reason） | chain_broken、chain_misaligned、no_claim（ghost code） | DetectedIssue.reason 已含断裂/错位详情、hint 修复指引 |
| 轻度增强（reason + hint） | substandard、isolated_task | DetectedIssue.reason 已含完整诊断、hint 修复指引或人类提示 |

### 3.4 数据流变更

当前 `_print_agent_actions()` 从 `gate_res`（dict）中取 `per_issue_states`，但 `per_issue_states` 是序列化后的 dict 列表，不含 `DetectedIssue` 对象。重构后需要把 `states_and_signals`（`List[Tuple[OutputState, IssueSignal, DetectedIssue]]`）直接传入输出链路：

```
pipeline._run_gate_evaluation()
  → 返回 gate_res (dict，不变)
  → 同时返回 states_and_signals (List[Tuple[OutputState, IssueSignal, DetectedIssue]])

pipeline._render_output()
  → 接收 states_and_signals + gate_res
  → 传 states_and_signals 给 _print_agent_actions()
```

`gate_res` 不存 `DetectedIssue`/`IssueSignal` 对象（保持可序列化）。`states_and_signals` 作为独立参数从 pipeline 层传递到 output 层，由 `_print_agent_actions` 传给 `_format_agent_actions`，最终由 `_collect_issue_actions()` 内部过滤 CURRENT 状态并处理。

### 3.5 输出层适配

`_format_agent_actions()` 重构：

- 输入：`gate_decision` + `List[Tuple[OutputState, IssueSignal, DetectedIssue]]`（状态过滤在 `_collect_issue_actions` 内部完成）
- 内部：调用 `_collect_issue_actions()` 生成 action 列表
- 删除 `gate_reasons`、`active_gaps`、`active_risks`、`violations` 参数
- 保留 `coverage_summary`（用于 action 尾部覆盖率展示）

`_print_gate_summary()` 保持不变：仍从 `per_issue_states` 输出全量状态（含 HISTORICAL），供人类终端查看。

### 3.6 不受影响的参数传递

以下参数同时服务于 Agent action（本次重构）和 `_print_reflection_prompts`（不在重构范围）。重构后这些参数仍需保留在 pipeline → output 的传递链中：

| 参数 | Agent action（重构后） | 反思提示（不受影响） |
|------|----------------------|-------------------|
| `merged_gaps` | 不再消费 | `_print_reflection_prompts` 直接使用 |
| `active_risks` | 不再消费 | `_print_reflection_prompts` 通过 `final_risks` 使用 |
| `compliance_res` | 不再消费 | `_print_reflection_prompts` 直接使用 |

重构仅切断这些参数到 Agent action 的消费路径，反思提示链路不动。

### 3.7 field_hints.json 优化

Agent action 的修复指引文本来源于 `src/vibe_tracing/templates/field_hints.json`（通过 `resolve_hint()` 加载）。当前 hints 存在以下问题：

**现状问题**：

1. **冗余**：level1 平均 100+ 字，包含内部实现细节（如 `MergeGateEngine.evaluate()` 返回值、`gate_decision=blocked`）。Agent 不需要知道门禁内部机制，只需要知道"哪里坏了、怎么修"
2. **level3 泄漏**：level3 本应是机器可读的诊断数据，但部分 level1 引用了 level3 风格的内部信息（如 `evidence_id={evidence_id}`）
3. **格式不统一**：部分 hint 以问题描述开头，部分以修复动作开头，Agent 无法快速定位行动指令
4. **action 节与 gate_decision 节重复**：`action.cover_gap` 和 `gate_decision.ac_missing_evidence` 描述同一类问题，但措辞不同

**优化原则**：

- level1 只回答两个问题：**什么问题？怎么修？**
- 不暴露内部实现（不提及函数名、返回值、内部状态变量）
- 统一格式：`[问题简述] [修复指令]`，修复指令用祈使句
- level2/level3 保持现状（人类可读 / 机器诊断），不在本次重构范围

**示例对比**：

当前：
```
"ac_missing_evidence": "验收标准 {item_id} 缺失测试证据：{reason}。此为 MUST 级别缺口，门禁将阻断。修复：为该 AC 补充测试用例，在测试函数 docstring 中声明 `covers: {item_id}`，确保 pytest 通过后重新运行 `vt analyze`。"
```

优化后：
```
"ac_missing_evidence": "AC {item_id} 无测试覆盖。编写测试用例，docstring 声明 `covers: {item_id}`，确保 pytest 通过。"
```

**影响范围**：`field_hints.json` 的 `gate_decision` 和 `action` 两节需逐条优化。`input`、`risk`、`compliance`、`tool`、`cli` 五节暂不改动（它们服务于 schema 校验和工具执行，不直接构成 Agent action 文本）。

---

## 4. 现状差距

| 维度 | 现状 | 目标 | 差距 |
|------|------|------|------|
| Agent action 数据源 | merged_gaps + active_risks + violations（3 类原始数据） | (OutputState, IssueSignal, DetectedIssue) 三元组列表（15 类检测器统一输出） | 数据源不同，覆盖缺口 12 类 |
| Gate 与 Agent 一致性 | Gate blocked 但 Agent 可能无对应 action | Gate blocked ⟺ 存在 Agent action | 不一致 → 一致 |
| 兜底机制 | `_collect_gate_reason_actions` 无差别转 HIGH action | 不需要兜底 | 存在 → 消除 |
| 历史债务展示 | HISTORICAL issue 混入 Agent action | 仅 Dashboard 展示 | 泄漏 → 隔离 |
| issue 覆盖 | Agent 只看 gaps/risks/violations | Agent 看所有 CURRENT issue | 3 类 → 15 类 |
| 治理类 issue 处理 | 与代码修复类一视同仁 | 分类为"人类决策"并输出提示 | 无区分 → 有区分 |
| 上下文增强 | 每个 collector 独立查 PRD/DB/hint | 统一按 issue_type 增强 | 分散 → 集中 |
| Agent 修复指引 | hints 冗长（100+ 字）、含内部实现泄漏、格式不统一 | 简练直接、`[问题] [修复指令]` 格式 | 见 §3.7 |

---

## 5. 修复方案

### 5.1 分步执行计划

**Step 1：新增 `_collect_issue_actions()`**

在 `actions.py` 中新增统一收集函数，消费 `List[Tuple[OutputState, IssueSignal, DetectedIssue]]`（内部过滤仅 CURRENT 状态）。按 issue_type 分发到对应的上下文增强逻辑。人类决策类 issue 生成 `type: "human_decision_required"` 提示。

**Step 2：重构 `_format_agent_actions()`**

将入参从 `gate_reasons + merged_gaps + active_risks + violations` 改为 `List[Tuple[OutputState, IssueSignal, DetectedIssue]]`（状态过滤在 `_collect_issue_actions` 内部完成）。内部调用 `_collect_issue_actions()` 替代三个旧 collector + 兜底函数。

**Step 3：适配 output.py 调用链**

`_print_agent_actions()` 新增 `states_and_signals: List[Tuple[OutputState, IssueSignal, DetectedIssue]]` 参数（从 pipeline 层传入，参见 §3.4）。直接传给 `_format_agent_actions()`（状态过滤在 `_collect_issue_actions` 内部完成）。删除 `_derive_reasons()` 调用和 `gate_reasons` 参数传递。

**Step 4：优化 field_hints.json**

按 §3.7 优化原则，逐条重写 `gate_decision` 和 `action` 两节的 level1 文本。删除内部实现泄漏，统一为 `[问题简述] [修复指令]` 格式。

**Step 5：删除旧代码**

前提条件：`_collect_issue_actions` 已保证所有 CURRENT_BLOCK 状态的 issue 均产出 HIGH action（即全覆盖保证）。这是安全删除 `_collect_gate_reason_actions` 兜底函数的前提，由 Step 6 测试点 "Gate blocked ⟺ 存在至少一个 Agent action" 验证。

删除项：`_collect_gap_actions`、`_collect_risk_actions`、`_collect_violation_actions`、`_collect_gate_reason_actions`、`_derive_reasons`。删除 `gate_reasons` 参数在全链路中的传递。`_derive_reasons` 的删除安全性已确认：`gate_reasons` 在 output.py 中唯一消费者为 `_format_agent_actions`（L81 生成、L92 传入），`_print_reflection_prompts` 不消费。

**Step 6：测试更新**

重写 `actions.py` 相关测试，验证：
- 每个 Agent 可修复类 issue_type 生成对应 action
- 人类决策类 issue 生成提示而非 action
- HISTORICAL/ACCEPTED/RESOLVED issue 不出现在 action 中
- Gate blocked ⟺ 存在至少一个 Agent action

### 5.2 不受影响的模块

| 模块 | 原因 |
|------|------|
| engine.py（检测层） | 不变，仍输出 DetectedIssue[] |
| signal_computer.py（信号层） | 不变，仍计算五元信号 |
| types.py（规则层） | 不变，F() 和 aggregate_gate_decision 保持 |
| reports.py（Dashboard 数据） | 不变，per_issue_states/historical_issues 仍为全量 |
| output.py `_print_gate_summary` | 不变，仍展示全量状态 |

### 5.3 风险与注意事项

1. **上下文增强完整性**：旧 collector 从 PRD/hint/DB 拼装的上下文（AC 描述、需求文本、测试场景），需要在 `_collect_issue_actions` 中按 issue_type 重新实现。需逐类验证上下文不丢失。
2. **urgency 计算**：旧的 `_compute_gap_urgency` 和 `_compute_risk_urgency` 区分 3 级（staged 85 / in_evidence 60 / default 30），回答"与本次变更的相关度"。新的 urgency 从三元组的读取 OutputState 和 IssueSignal.observed 计算，保留 3 级精度：

   | 条件 | urgency | 语义 |
   |------|---------|------|
   | CURRENT_BLOCK + observed=true | 90 | 已知债务，本次承诺修复 |
   | CURRENT_BLOCK + observed=false | 70 | 本次新引入的阻断问题 |
   | CURRENT_WARNING | 50 | 告警，建议修复 |
3. **反思提示参数保留**：`merged_gaps`、`active_risks`、`compliance_res` 仍服务于 `_print_reflection_prompts`，不可从 pipeline → output 传递链中删除（详见 §3.6）。
