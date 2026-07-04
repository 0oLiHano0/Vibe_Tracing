# VT 任务反思与执行轨迹：业务逻辑规范

**状态**：业务逻辑已锁定（架构设计待启动）
**创建**：2026-07-04
**定位**：业务需求源头文档，**架构设计的输入**
**关联**：
- `docs/design_channel_separation.md`（channel 架构设计，**待基于本文档整体重写**）
- `docs/design_agent_action_unification.md`（issue 级分流契约，**PHASE-VT-015 已落地**；作为本文 §2.1.6 跨通道审计在 issue 粒度的底层依据）
- `docs/tech_debt/ux_action_output_issues.md`（UX 瑕疵，本文落地后瑕疵 1 自然消解）
- `docs/tech_debt/design_requires_human_field.md`（独立条目，不冲突）

> **本文不写架构实现**。只锁定"VT 应该做什么、为什么这么做、边界在哪"。架构设计师从本文推导技术方案，但不受本文约束具体实现细节。

---

## 1. 背景与目标

### 1.1 业务场景

VT 管理下的 AI Coding Agent 项目，涉及三类干系人：

| 干系人 | 角色 | 核心诉求 |
|---|---|---|
| **业务方**（非技术管理者） | 业务需求来源 + 开发过程管理者 | 了解技术债、治理健康度、Agent 效能，**不需要读代码** |
| **AI Coding Agent** | 被管理的执行者 | 获取明确指令、完成任务、交付可追溯的证据 |
| **VT 自身** | 治理系统 | 自我演进：识别规则/PRD/架构约束的改进点 |

### 1.2 当前缺口

**缺口 1：业务方看不到 Agent 的工作质量**。Agent 完成任务后，业务方只能从"gate 是否 PASS"这一个信号判断。但"PASS"背后可能隐藏技术债、妥协、治理文件过时等问题。

**缺口 2：VT 没有自我演进的数据基础**。每次 analyze 产出的 issue 数据**只在当次消费**，不沉淀。VT 无法回答"哪类规则反复被违反？是否该简化？"这类元问题。

**缺口 3：任务边界不严格**。一个 PASS 的 task 可能在后续 commit 被重新引用，导致任务边界模糊、轨迹数据失真。

### 1.3 业务目标

通过引入**任务验收摘要**、**任务会话追踪**、**Phase 深度反思**、**任务不可复活**四个机制，达成：

1. 业务方在**任务结束时**能通过 stdout 轻量验收摘要快速判断"继续还是介入"
2. 业务方在 **PHASE 结束时**能通过 Dashboard 深度反思识别技术债和治理改进点
3. VT 能基于任务轨迹数据**自我演进**规则、PRD、架构约束
4. 任务成为**不可变的历史单元**，轨迹数据干净可审计

---

## 2. 核心概念

### 2.1 Channel（通道）

VT 的信息输出本质是一个**三阶段决策路由系统**，按"谁在什么阶段用这条信息做判断"划分：

| 决策阶段 | 核心问题 | 物理通道 | 消费时机 |
|---|---|---|---|
| **执行决策** | Agent 现在怎么改代码 | stdout 前段 | 任务执行中 |
| **验收决策** | 人类判断任务是否算完成 | stdout 末尾段 + Dashboard | 任务结束时 |
| **治理决策** | 人类判断系统是否在变好 | Dashboard + 独立文件 | PHASE 结束 / 长期 |

三个阶段共享同一套规则信号源，在不同阶段呈现不同抽象层次的信息。

**关键原则**：stdout 内的"Agent 指令段"和"验收摘要段"**物理共存但语义隔离**——验收摘要必须在所有指令之后，独立 section 呈现，不要求 Agent 响应。

#### 2.1.1 双通道契约

```
stdout (terminal)  = Agent 通道（指令段 + 验收摘要段，按时序共存）
Dashboard (HTML)   = Human 通道（深度阅读 + 长期查阅）
```

任何输出只能归属一个通道。跨通道需求（如 gate decision 人类和 Agent 都看）通过**两处各渲染一份**解决，而非共享 stdout。

#### 2.1.2 受众特征

| 通道 | 受众 | 特征 | 期望 |
|---|---|---|---|
| **stdout** | AI Coding Agent | 结构化、可解析、信噪比高 | Gate decision 一行 + action 列表（含上下文）+ 摘要 |
| **Dashboard** | 人类开发者 / 项目经理 / 审计 | 可视化、全量信息、交互 | 全量 issue 明细、HISTORICAL 列表、反思提示、图表 |

#### 2.1.3 信息归属判定原则

对每条待输出信息，按以下优先级判定归属：

1. **Agent 是否可执行？** 是 → stdout
2. **是否为 gate 决策结果？** 是 → 两者都渲染（Dashboard 展示，stdout 单行摘要）
3. **是否仅供人类自省 / 历史参考 / 治理视角？** 是 → Dashboard
4. **是否跨受众（如覆盖率统计）？** 是 → Dashboard 主渲染 + stdout 单行摘要

#### 2.1.4 stdout 结构规范

stdout 分为两段：**Agent 指令段**（任务执行中）+ **验收摘要段**（任务结束时）。

**Agent 指令段**（任务执行中）：

```
GATE DECISION: {decision}
{空行}
ACTION 1 [HIGH] ...
...
ACTION N [HIGH/MEDIUM] ...
{空行}
======================================================================
SUMMARY
======================================================================
HIGH: X | MEDIUM: Y | LOW: Z
当前阻拦: X 项 | 当前告警: Y 项 | 等待人类: Z 项
Coverage: {pct}% ({status}, target: 80%)
```

**验收摘要段**（仅 `gate=PASS 且 current_commit_task_set 非空` 时打印）：结构见规则 1。Agent 不响应该段，仅作为任务交付的最后动作输出。

**总量目标**：约 50-70 行（vs 现状 120+ 行，信噪比从 42% → 90%+）。

#### 2.1.5 Dashboard 内容补充清单

在现有 Dashboard 基础上，明确承载以下"人类专属"内容：

- Gate summary 全量 [阻拦]/[告警]/[预存]/[已接受]/[已解决] 列表（含 severity marker）
- **Phase 深度反思**（规则 2）：完整 8 维度 + 数据洞察 + 改进建议，独立 "Phase Reflection" 标签页
- **任务验收摘要完整版**（每个 CLOSED task 的详细汇报存档）
- **任务轨迹数据**：task_sessions.json 的可视化视图（迭代次数、issue 分布）
- **Agent 能力评分面板**（规则 5）：First-time-right 率、平均迭代次数、同类重复率、能力健康度
- **治理演进面板**（规则 6）：全量规则触发统计表、衍生 task 比例、任务平均迭代次数
- HISTORICAL issue 明细（按 age 排序）
- 空 claims 详细说明（当前 stdout 仅 3 行警告，详情放 Dashboard）

#### 2.1.6 现有代码的跨通道审计结论

对 `_render_output` 调用的 5 个渲染函数的归属判定（业务层规范，实现细节由架构设计落地）：

| 渲染函数 | 当前通道 | 应属通道 | 判定依据 |
|---|---|---|---|
| `_render_dashboard` | Dashboard HTML | Dashboard | 已正确 |
| `_print_gate_summary` 的 [阻拦]/[告警] 计数 | stdout | stdout 单行摘要 + Dashboard 全量 | gate decision 双受众 |
| `_print_gate_summary` 的 70+ 行 [预存] 列表 | stdout | **Dashboard only** | HISTORICAL 仅人类治理用 |
| `_print_empty_claims_hint` | stdout | stdout | Agent 可执行（生成 claim） |
| `_print_agent_actions` | stdout | stdout | Agent 核心消费 |
| `_print_reflection_prompts` 的 8 维度反思 | stdout | **Dashboard only**（Phase 级触发） | 纯人类深度阅读，Agent 无法执行 |
| 覆盖率摘要 | stdout | 两者（Dashboard 主渲染 + stdout 一行） | 双受众 |

**跨通道冗余已识别**：`_print_gate_summary` 在 stdout 打印 [阻拦]/[告警]/[预存] 列表，而 Dashboard 的 `per_issue_states` 面板已渲染完整列表（含 HISTORICAL）。属于典型跨通道重复，按"删除 stdout 那份"原则处理。

### 2.2 Task（任务）

**定义**：Task 是 VT 治理下的**最小工作承诺单元**，对应一次明确的"工作承诺 → 兑现"闭环。

**生命周期状态**：

| 状态 | 含义 | 可转换到 |
|---|---|---|
| `OPEN` | 已创建，未 PASS | IN_PROGRESS、CLOSED |
| `IN_PROGRESS` | commit 中首次引用该 task，正在执行 | CLOSED |
| `CLOSED` | PASS 达成，不可逆 | **终态，不可转换** |

**核心规则（任务不可复活）**：
- 一旦 task 进入 CLOSED 状态，任何后续 commit 引用该 task_id 都会被 VT 阻断（exit code 2）
- 如需继续相关工作，必须创建**新 task**
- 哲学：每个 task 是**不可变的历史单元**，对应一个闭合的工作承诺

### 2.3 Task Session（任务会话）

**定义**：Task 从首次被 analyze 到 CLOSED 的全过程，包含所有 analyze 迭代的累积数据。

**会话边界**：
- 起点：commit message 首次引用该 task_id
- 终点：gate=PASS 且 current_commit_task_set 包含该 task_id
- 不可复活：CLOSED 后会话数据封存，永不再打开

### 2.4 Reflection（反思）

分两个层级：

| 层级 | 命名 | 触发时机 | 通道 | 业务目的 |
|---|---|---|---|---|
| **Task 级** | 任务验收摘要（Task Acceptance Summary） | task CLOSED 时 | stdout 末尾（轻量段） | 业务方当场判断"继续还是介入" |
| **Phase 级** | 阶段深度反思（Phase Deep Reflection） | PHASE 结束或用户请求 | Dashboard + 独立文件 | 业务方识别技术债、治理改进点 |

### 2.5 治理演进（Governance Evolution）

VT 作为治理系统的**自我改进机制**。通过任务轨迹数据的累积分析，识别：
- 哪些 VT 规则需要简化或删除
- 哪些 PRD / 架构约束需要澄清
- 任务拆分粒度是否合理

---

## 3. 业务规则（已锁定）

### 规则 1：Task 验收摘要（stdout 轻量段）

**触发条件**：
```
gate = PASS 且 current_commit_task_set 非空
```

**多 task 处理规则**：若 `current_commit_task_set` 含多个 task_id，**按 task 独立输出多份摘要**（每 task 一个独立 section，使用相同分隔符），不合并。

- **理由**：每个 task 是独立工作承诺单元，混合会掩盖差异（如 task A 全清 vs task B 留 WARNING），业务方无法当场判断"哪个任务可接受、哪个需介入"
- **stdout 信噪比**：2-3 个 task × 5-8 行 = 15-24 行，未超总量目标（50-70 行）
- **建议行**：每个 task 独立判定（可能 task A `✅ 接受`、task B `⚠️ 驳回`）
- **输出顺序**：按 task_id 字典序排列，确保可预期

**内容结构**（5-8 行，中文业务语言）：

```
═══ 任务验收摘要 ═══
任务：TASK-VT-190
建议：✅ 接受（2 项遗留 WARNING 无业务影响）
交付：[1-2 句话业务描述]
已解决：BLOCK 5 项 / WARNING 7 项（共 12 项）
遗留：WARNING 1 项（已接受，无业务影响）
严重风险：无 / [1-2 项业务影响大的 WARNING]
迭代次数：4
═══ 验收结束 ═══
```

**"建议"行的判定规则**：
- 严重风险 = 无 → `建议：✅ 接受`（附简要理由）
- 严重风险 ≥ 1 → `建议：⚠️ 驳回`（附简要理由）
- 建议为系统判断，人类始终有最终决定权

**严重风险的判定标准**：
- 仅上报"业务影响大"的 WARNING（如模块耦合、架构妥协、技术债累积）
- 纯代码风格类、命名规范类 WARNING **不上报**（避免冗长）
- `business_impact` 字段由系统预设默认值（VT 开发者维护，随版本发布），不提供人类覆写
- 不确定有无业务影响的，默认标为有影响（宁可多报）

**语言约定**：
- 业务术语：中文（"登录模块" 而非 "auth module"）
- 文件路径：保持原样
- Task / REQ / AC ID：保持原样
- 技术术语：首次出现中英对照，之后纯中文

**位置**：stdout 末尾，独立 section，与 Agent 指令段物理隔离（分隔符）。

**Agent 行为**：Agent 不响应该段，仅作为任务交付的最后动作输出。

### 规则 2：Phase 深度反思（Dashboard + 文件）

**触发条件**（双触发）：
- 显式 CLI 命令：`vt reflect --phase VT-015`
- Dashboard 入口：用户在 Dashboard 点击"生成本 PHASE 反思"

**内容结构**（完整 8 维度，业务语言）：
1. 项目不足识别（本 PHASE 暴露的设计或功能缺陷）
2. 架构精简度（是否过度工程）
3. 根因修复深度（是否打补丁）
4. 计算与逻辑冗余（重复 I/O、二次反序列化）
5. 凭证真实性（测试是否过度 Mock）
6. 代码认知复杂度（是否阻碍后续 Agent 推理）
7. 豁免与绕过机制（是否用了临时白名单）
8. 残留与死代码（废弃类、函数、失效测试）

**存储**：`.vibetracing/phase_reflections/PHASE-VT-XXX.md`（独立文件，可版本控制）

**呈现**：Dashboard 新增 "Phase Reflection" 标签页，渲染为人类友好视图。

**语言**：中文业务语言（同规则 1）。

### 规则 3：任务会话追踪

**采集时机**：每次 `vt analyze` 完成后，在 `_run_gate_evaluation` 之后追加追踪更新。

**会话数据模型**：

```json
{
  "task_id": "TASK-VT-190",
  "phase_id": "PHASE-VT-015",
  "status": "CLOSED",
  "first_seen": "2026-07-04T08:00:00Z",
  "closed_at": "2026-07-04T10:30:00Z",
  "iterations": 4,
  "issue_counts": {
    "no_claim": {"BLOCK": 2, "WARNING": 0},
    "chain_broken:GATE-VT-006": {"BLOCK": 3, "WARNING": 1},
    "substandard:coverage": {"BLOCK": 0, "WARNING": 5}
  },
  "resolved_count": 11,
  "accepted_count": 1,
  "model": "claude-opus-4-8"
}
```

**`phase_id` 来源**：从 `task_list.json` 中对应 task 记录的 `phase_id` 字段读取（required 字段），首次创建 session 时写入。

**`issue_counts` key 格式**：复合粒度。非架构类 issue 用 `issue_type`（如 `"no_claim"`），架构合规类用 `issue_type:rule_id`（如 `"chain_broken:GATE-VT-006"`），需子分类的用 `issue_type:subtype`（如 `"substandard:coverage"`）。

**`model` 字段采集**：读取 `.vibetracing/config.json` 中的 `model` 字段（字符串），由人类（业务方）手动维护。换模型时人类改 config 即可，VT 仅做读取。config 中缺失 `model` 字段时，会话记录写入 `"model": "unknown"`，不阻断流程。

**存储位置**：`.vibetracing/task_sessions.json`

**生命周期**：
- 首次看到 task_id：创建新会话记录，`status=IN_PROGRESS`
- 每次 analyze 看到 task_id：`iterations += 1`，累加 issue_counts
- gate=PASS 且 task_id 在 current_commit_task_set 中：`status=CLOSED`，记录 `closed_at`

**CLOSED 后**：数据封存，永不更新。

### 规则 4：Task Immutability 检查（Gate 阻断）

**触发条件**：
- 当前 commit message 引用的 task_id，在 `task_sessions.json` 中已 CLOSED

**行为**：
- vt analyze exit code = **3**（Closed task 引用阻断，**与常规 gate BLOCKED 的 exit 2 隔离**，便于 CI 日志区分"可修复 issue"与"任务边界违反"）
- stderr 输出："TASK-VT-XXX 已于 {closed_at} CLOSED。如需继续相关工作，请创建新 task。用 `vt analyze --task-status TASK-VT-XXX` 查询任务状态。"

**Exit code 语义四级制**（架构设计落地约束）：

| Exit | 语义 | 可恢复性 |
|---|---|---|
| `0` | 成功（gate=PASS） | — |
| `1` | 内部崩溃（未捕获异常、输入损坏） | 修复 VT / 输入 |
| `2` | Gate BLOCKED（检测到可修复 issue） | Agent 修复后再次 commit |
| `3` | Closed task 引用（任务边界违反） | Agent 创建新 task |

**Agent 自救路径**：
1. 通过 `vt analyze --task-status TASK-VT-XXX` 查询 task 状态
2. task_list.json 中已 CLOSED 的 task 标记 `"closed": true` 字段，Agent 创建新 task 前先查
3. 创建新 task 承载后续工作

**业务价值**：任务边界严格化，轨迹数据不失真。

### 规则 5：Agent 能力评分

**数据源**：`.vibetracing/task_sessions.json` 的聚合分析。

**核心指标**：

| 指标 | 计算方式 | 健康阈值 | 警告阈值 |
|---|---|---|---|
| First-time-right 率 | CLOSED 任务中 iterations=1 的比例 | ≥ 60% | < 40% |
| 平均迭代次数 | CLOSED 任务的 iterations 均值 | ≤ 3 | > 5 |
| 同类问题重复率 | 同一 issue_type 在不同 task 中反复出现的比例 | < 20% | > 40% |
| BLOCK 类型集中度 | 某类 issue 占 BLOCK 总数的最大比例 | < 50% | > 70% |

**警告阈值触发时**：
- Dashboard 显示警告徽章（如 "Agent Capability: ⚠️ Needs Review"）
- **不阻断主流程**，**不在 stdout 提示**（避免干扰 Agent）
- 业务方在 Dashboard 主动查阅时看到

**业务价值**：业务方据此判断是否需要换更强的模型，避免低效 token 浪费。

### 规则 6：治理演进指标

**数据源**：`.vibetracing/task_sessions.json` + issue 历史累积。

**核心指标**：

**（1）全量规则触发统计表**

将所有规则按 `issue_type:rule_id`（或 `issue_type:subtype`）粒度统一呈现，让人类一眼看清每条规则的治理状态：

| 列 | 说明 |
|---|---|
| 规则标识 | `issue_type:rule_id` 或 `issue_type:subtype`（可点击跳转规则定义） |
| 规则描述 | 一句话 |
| BLOCK 次数 | 本 PHASE 累计 |
| WARNING 次数 | 本 PHASE 累计 |
| 最近触发 | 日期 / "从未触发" |

默认按 BLOCK 次数降序排列，"从未触发"的规则自然沉底。人类基于全量数据自主判断哪些规则需要调整或删除，VT 不自动执行规则变更。**趋势列（跨 PHASE 对比）不在 MVP 范围**，待二期"治理复盘报告"（跨 PHASE 元分析）落地时再引入。

**（2）衍生 task 比例**

| 指标 | 计算方式 | 业务解读 |
|---|---|---|
| 衍生 task 比例（轻量代理） | 标题包含"修复/优化/调整 TASK-VT-XXX"字样的新 task 占比 | 任务拆分粒度或 PRD 清晰度问题 |

**衍生 task 比例的实现**：
- **MVP 不做显式 `derived_from` 字段**（避免 Agent 创建 task 时扫全表找相关 task，token 浪费）
- 改用**标题关键词匹配**近似识别（如"修复 TASK-VT-XXX"、"优化 TASK-VT-XXX"）
- 作为"参考数据"显示在 Dashboard，不算正式指标
- Token 成本：接近零（仅字符串匹配）

**（3）任务平均迭代次数**

| 指标 | 计算方式 | 业务解读 |
|---|---|---|
| 任务平均迭代次数（按 PHASE） | 按 PHASE 分组计算 iterations 均值 | 任务粒度是否合理 |

**呈现**：Dashboard 新增 "Governance Evolution" 面板，全量规则表为主体，衍生 task 比例和任务平均迭代次数为辅助指标。

---

## 4. 业务流程

### 4.1 任务正常完成流程

```
[Agent 创建 task TASK-VT-XXX，task_list.json 中 status=OPEN]
    ↓
[Agent 完成部分工作，git commit 引用 TASK-VT-XXX]
    ↓
[vt analyze 触发]
    ├── 检测到 TASK-VT-XXX 首次出现 → 创建 task session，status=IN_PROGRESS，iterations=1
    ├── gate=BLOCKED → 输出 action 列表 → 任务继续
    ↓
[Agent 修复 issue，再次 commit + vt analyze]
    ├── iterations=2，累加 issue_counts
    ├── gate=BLOCKED → 任务继续
    ↓
[重复 N 次]
    ↓
[vt analyze，gate=PASS，current_commit_task_set 含 TASK-VT-XXX]
    ├── 更新 task session：status=CLOSED，closed_at=now
    ├── 输出 Agent 指令段（stdout 前段）
    ├── 输出 Task 验收摘要（stdout 末尾段）  ← 规则 1
    └── 任务结束
```

### 4.2 任务尝试复活流程（阻断）

```
[TASK-VT-XXX 已 CLOSED]
    ↓
[Agent 错误地在 commit message 中再次引用 TASK-VT-XXX]
    ↓
[vt analyze 触发]
    ├── 检测到 TASK-VT-XXX 已 CLOSED → 阻断
    ├── exit code = 3（Closed task 引用，与常规 gate BLOCKED 的 exit 2 隔离）
    ├── stderr: "TASK-VT-XXX 已 CLOSED，请创建新 task"
    └── 不输出 action 列表
    ↓
[Agent 调用 `vt analyze --task-status TASK-VT-XXX` 查询状态]
    ↓
[Agent 创建 TASK-VT-YYY 承载后续工作]
    ↓
[正常流程]
```

### 4.3 Phase 反思流程

```
[PHASE-VT-015 所有 task CLOSED]
    ↓
[用户执行 `vt reflect --phase VT-015` 或在 Dashboard 点击"生成反思"]
    ↓
[VT 聚合 PHASE 内所有 task session 数据]
    ├── 计算 PHASE 级聚合指标
    ├── 生成 8 维度深度反思报告
    ├── 保存到 .vibetracing/phase_reflections/PHASE-VT-015.md
    └── Dashboard 渲染
    ↓
[stdout: "PHASE-VT-015 反思已生成，请查看 output/dashboard.html#reflection"]
    ↓
[业务方打开 Dashboard，仔细阅读，决定哪些需及时处理、哪些可延后]
```

### 4.4 治理演进反馈闭环

```
[多个 PHASE 后，task_sessions.json 累积足够数据]
    ↓
[Dashboard 计算治理演进指标]
    ├── 全量规则触发统计表（含趋势）
    ├── 衍生 task 比例
    └── 任务平均迭代次数（按 PHASE）
    ↓
[业务方定期查阅 Dashboard "Governance Evolution" 面板]
    ↓
[识别改进点，例如：规则 R-007 反复被违反，需要简化]
    ↓
[人类更新架构约束，`vt finalize` 锁定新基线]
    ↓
[未来 issue 减少] ← 产品成功的衡量标准
```

---

## 5. 边界与约束

### 5.1 本机制不处理

- **Agent 间对比**：不横向对比多个 Agent 的能力（单 Agent 场景）
- **任务难度评级**：不自动评估任务本身的复杂度
- **强制反思验收**：不要求业务方显式"已读"或"确认"反思报告
- **跨项目对比**：不考虑多项目场景下的治理指标对比

### 5.2 Channel 分离对现有机制的业务要求

> 本节锁定"现状中哪些 stdout 内容应该迁出或保留"的**业务规范**。具体实现（函数名、参数、模板）由后续架构设计落地。

| 现有机制 | 业务要求 |
|---|---|
| `_print_gate_summary`（gate summary） | **精简**：stdout 仅保留首行 gate decision，全量 [阻拦]/[告警]/[预存] 列表迁移到 Dashboard（详见 §2.1.5、§2.1.6） |
| `_print_reflection_prompts`（8 维度反思 stdout 输出） | **删除** stdout 输出，改为 Phase 级触发 + Dashboard 呈现（详见 §2.1.6） |
| `_print_agent_actions`（Agent action 列表） | **保留**，作为 stdout Agent 指令段的核心 |
| `_print_empty_claims_hint`（空 claims 警告） | **保留**，Agent 可执行的简短提示 |
| task_list.json 现有 schema | **新增** `closed: true` 字段（可选），不影响现有字段 |

**业务要求与架构设计的边界**：上表是业务层的"应然"，不约束架构师选择具体实现路径（如迁移到 Dashboard 是 HTML 模板扩展现有面板、还是新增独立面板，由架构设计决定）。

### 5.3 业务约束

- **Task immutability 严格模式**：CLOSED 后不允许任何状态转换，包括"补充证据"、"修订声明"等。所有后续工作必须新 task 承载。
- **反思语言固定中文**：不因项目语言切换，业务方母语固定。
- **Agent 能力警告不阻断**：仅 Dashboard 显示徽章，不干扰 Agent 主流程，不在 stdout 提示。
- **严重风险判定采用双层查找**：优先查 `.vibetracing/business_impacts.json`（项目级覆写），未命中则查 `field_hints.json`（系统默认），仍未命中默认 `"high"`（宁可多报）。项目级覆写文件由人类（业务方/Agent）在项目内维护。
- **衍生关系不做强制字段**：MVP 用标题关键词匹配近似，避免 Agent 创建 task 时的全表扫描 token 成本。

---

## 6. MVP 范围（PHASE 一期）

### 6.1 包含

| 项 | 业务规则 | 工作量估计 |
|---|---|---|
| **A. Task 会话追踪**（数据采集） | 规则 3 | 1 天 |
| **B. Task immutability 检查** | 规则 4 | 0.5 天 |
| **C. Task 验收摘要**（stdout 轻量段） | 规则 1 | 1 天 |
| **D. Agent 能力评分**（Dashboard 面板） | 规则 5 | 1.5 天 |
| **E. 治理演进指标**（Dashboard 面板） | 规则 6 | 2 天 |
| **F. gate summary 精简**（与 channel 分离协同） | 本文 §2.1.6 跨通道审计结论 | 1 天 |

**总计**：7 工作日

### 6.2 落地顺序（建议）

```
A (数据采集) → B (immutability) → C (task 验收摘要) → F (gate 精简) → D (agent 能力) → E (演进指标)
```

理由：先采集数据（A、B），再做 stdout 呈现（C），收尾 channel 分离（F），最后做 Dashboard 分析面板（D、E）。F 提前于 D、E 可避免 Dashboard 面板开发时面对脏 stdout 的返工。

### 6.3 延后（PHASE 二期）

- Phase 深度反思机制（命令 + Dashboard 入口）
- 任务验收摘要完整版文件（`.vibetracing/completion_reports/TASK-VT-XXX.md`）
- 显式 `derived_from` 字段（视数据积累决定是否引入）
- 治理复盘报告（跨 PHASE 元分析）

### 6.4 不做

- 强制 `derived_from` 字段（token 成本不合理）
- 反思 prompt 固定 8 维度在 stdout 输出（已替换为 task 验收摘要）
- 反思报告的"验收机制"（业务方被动接收即可）
- Agent 能力警告阻断主流程（保持 Dashboard-only）

---

## 7. 业务价值主张

### 7.1 业务方视角

**Before**：
- 只能从"gate PASS/BLOCKED"一个信号判断任务状态
- 看不到技术债、看不到治理健康度、看不到 Agent 效能
- 必须信任 Agent 的口头汇报，缺乏独立数据源

**After**：
- 任务结束时 stdout 扫一眼，快速判断"继续还是介入"
- PHASE 结束时深度阅读反思，识别需要及时处理的技术债
- Dashboard 随时查阅 Agent 能力评分，决定是否换模型
- Dashboard 看到 VT 规则的演进趋势，主动更新治理文件

### 7.2 VT 产品视角

**Before**：
- 合规检查工具，每次 analyze 数据即用即弃
- 无自我演进机制
- 任务边界模糊，轨迹数据不可审计

**After**：
- **自演进治理系统**：通过任务轨迹数据持续优化规则/PRD/架构
- **任务边界严格**：每个 task 是不可变历史单元，轨迹干净
- **业务方赋能**：非技术管理者也能通过 Dashboard 洞察项目治理健康度

### 7.3 产品成功的衡量标准

> **长期趋势：未来 issue 数量持续下降**

这意味着：
- VT 规则经过演进，越来越精准
- PRD / 架构约束经过澄清，越来越清晰
- Agent 经过能力评估和模型调整，越来越高效
- 任务拆分粒度经过优化，越来越合理

这是 VT 从"合规检查工具"升级为"自演进治理系统"的终极业务价值。

---

## 8. 业务决策记录

> 本节记录三轮头脑风暴中**已锁定的业务决策**，作为架构设计的约束。

### 决策 1：反思的消费者是业务方，Agent 是生产者

- 反思报告用业务语言，不用技术内省措辞
- 反思内容面向"业务风险说明 + 决策选项"，而非"代码改进建议"

### 决策 2：反思分两层（task 轻量 + phase 深度）

- Task 验收摘要：stdout 末尾，5-8 行，当场扫一眼
- Phase 深度反思：Dashboard + 文件，8 维度，仔细阅读

### 决策 3：任务不可复活（强 immutability）

- CLOSED task 不可再被 commit 引用，否则阻断
- 衍生关系 MVP 不做强制字段，用标题匹配近似

### 决策 4：任务轨迹数据用于 VT 自身演进

- 不是 Agent 绩效评估（虽附带能力评分）
- 核心用途：识别 VT 规则 / PRD / 架构约束的改进点

### 决策 5：Agent 能力警告不阻断主流程

- 仅 Dashboard 徽章
- 业务方主动查阅时可见

### 决策 6：Channel 原则按消费时机细分

- stdout 内部分为 Agent 指令段 + 验收摘要段，物理共存但语义隔离
- Dashboard 承载深度阅读 + 长期查阅

### 决策 7：语言固定中文

- 所有反思报告（task / phase）使用中文业务语言
- 文件路径 / ID 保持原样

### 决策 8：严重风险只上报业务影响大的 WARNING

- 纯代码风格类、命名规范类 WARNING 不上报
- 避免汇报冗长，保持 5-8 行轻量
- 严重风险判定采用**双层查找**：优先查 `.vibetracing/business_impacts.json`（项目级覆写），未命中则查 `field_hints.json`（系统默认 `business_impact` 字段），仍未命中默认 `"high"`（不确定默认有业务影响）

### 决策 9：MVP 范围锁定（见 §6）

- A-E 六项 + 与 channel 分离协同的 F 项
- 落地顺序 A → B → C → F → D → E
- 工作量 7 工作日

### 决策 10：task_sessions.json 预留 model 字段

- `model` 字段由 vt analyze 自动从 `.vibetracing/config.json` 的 `model` 字段读取
- 由人类（业务方）手动维护 config：换模型时改 config 即可，VT 仅做读取
- config 缺失 `model` 字段时，会话记录写入 `"model": "unknown"`，不阻断流程
- 一期不展示，为二期按模型拆分能力评分留数据基础
- 采集路径选择 config 而非 commit metadata / env / task 上下文文件的理由：MVP 先跑通，最小实现成本

### 决策 11：全量规则触发统计表替代分拆指标

- 删除"高频违规规则 Top 10"和"从未触发的规则"两个独立指标
- 合并为一张全量规则触发统计表，按 BLOCK 次数降序，"从未触发"自然沉底
- 人类基于全量数据自主判断，VT 不自动执行规则变更

### 决策 12：验收摘要增加系统建议行

- 严重风险 = 无 → `建议：✅ 接受`
- 严重风险 ≥ 1 → `建议：⚠️ 驳回`
- 建议为系统判断，人类始终有最终决定权

### 决策 13：允许项目级 business_impact 覆写

- 新增 `.vibetracing/business_impacts.json` 文件，结构为 `rule_id → impact` 映射
- 覆写优先级：项目覆写文件 > `field_hints.json` 系统默认 > `"high"` 兜底
- 文件不存在时视为空 dict（不报错），格式损坏时 warning 并降级为系统默认
- 由人类（业务方 / Agent）在项目内维护，VT 不校验语义正确性
- 理由：避免长期"误报疲劳"——当某条规则在特定项目中确认无业务影响时，人类可将其降级为 `"low"` 或 `"none"`

---

## 9. 待架构设计解决的问题（非业务）

> 本节列出**架构层**需要回答的问题，业务层已无疑问。架构设计师从这些问题出发，不回头质疑业务规则。

**已解决**：以下问题已在 `docs/design_channel_separation.md`（已批准，PHASE-VT-016 待实施）中给出架构答案，不再在本文维护：

1. ~~`.vibetracing/task_sessions.json` 的并发写入策略与跨版本 schema 迁移机制~~ → 单进程模型，无需锁；`schema_version` 保留，迁移按需实现（YAGNI）
2. ~~Task immutability 检查应放在 `_check_*` 系列的哪个位置~~ → pipeline 预检查，在 `detect_all_issues` 之前，命中则 exit code 3
3. ~~Task 验收摘要的"严重风险"判定~~ → 双层查找（决策 13）+ `business_impacts.json` 项目覆写
4. ~~Agent 能力评分的阈值是否应可配置~~ → 一期固定阈值，Dashboard 面板展示
5. ~~治理演进指标的聚合时机~~ → 每次 `vt analyze` 时从 `task_sessions.json` 聚合
6. ~~Dashboard 新增面板的渲染架构~~ → 沿用客户端渲染（JS），Phase 反思面板二期服务端渲染
7. ~~`vt status <task_id>` CLI 命令的设计~~ → `vt analyze --task-status <task_id>`（参数形式，与 analyze 互斥）
8. ~~`vt reflect --phase VT-XXX` CLI 命令的设计~~ → 独立子命令 `vt reflect --phase <phase_id>`（二期）

**二期开放问题**（待二期实施前回答）：

1. Phase 反思的 8 维度中，需要代码扫描 + mock 元数据的 5.5 个维度，数据采集的具体实现方案
2. 跨 PHASE 趋势列的基线对齐策略（不同 PHASE 的规则集可能不同）
3. 任务完成报告完整版（`.vibetracing/completion_reports/TASK-VT-XXX.md`）的模板结构
