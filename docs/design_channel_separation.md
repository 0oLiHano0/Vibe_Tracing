# Channel 分离与任务反思架构设计

**状态**：已批准（PHASE-VT-016 待实施）
**创建**：2026-07-04
**定位**：基于 `docs/business_task_reflection_trajectory.md` 的架构设计（一期 + 二期合并设计、分期实施）
**业务规范源头**：`docs/business_task_reflection_trajectory.md`（已锁定，不可变）

**关联**：
- `docs/business_task_reflection_trajectory.md`（业务规范，架构设计的唯一输入）
- `docs/design_agent_action_unification.md`（PHASE-VT-015 已落地，issue 级分流底层依据）

---

## 1. 背景

### 1.1 触发场景

PHASE-VT-015 验证时，一次 `vt analyze` 的终端输出约 120 行：

- **42%**（~50 行）是给 Agent 的：gate decision + 7 个 action
- **58%**（~70 行）是给人类的：70+ 个 `[预存]` 列表、8 维度反思提示、空 claims 警告

Agent 读取的 stdout 上下文中**近六成是它不应消费的噪声**。

### 1.2 上游设计的缺口

`design_agent_action_unification.md`（已落地）在 issue 级完成了分流（CURRENT → Agent，HISTORICAL → Dashboard），但未在 **信息级** 定义通道归属。具体表现：

| 缺口 | 症状 |
|---|---|
| 未禁止人类内容进 stdout | 70+ 行 HISTORICAL 列表占据 Agent context window |
| 未定义反思内容的通道 | 8 维度反思提示用 `print()` 直出，可能被 Agent 误当执行指令 |
| 未定义任务完成信息的形态 | 业务方仅能从 "gate=PASS" 单信号判断 |
| 未沉淀任务轨迹数据 | VT 无法自我演进规则/PRD/架构约束 |

### 1.3 本文目标

基于 `business_task_reflection_trajectory.md` 的锁定规范，定义：

1. **Channel 契约**：stdout 与 Dashboard 的信息归属规则与物理实现
2. **任务生命周期基础设施**：会话追踪、不可变性检查、验收摘要生成
3. **Phase 反思机制**：CLI + Dashboard 入口 + 文件持久化
4. **治理演进数据基础**：规则触发表、Agent 能力评分、衍生关系近似统计
5. **分期实施契约**：一期 MVP 与二期扩展的接口边界

### 1.4 设计评审反馈响应（决策日志）

> 本节记录架构设计评审中识别的 6 项反馈及本设计的响应，作为设计决策的可追溯日志。

| # | 类型 | 反馈 | 决策 | 落地位置 |
|---|---|---|---|---|
| 1 | 🔴 业务盲区 | 验收摘要未说明 commit 含多 task 时行为 | **按 task 独立输出多份摘要**（每个 task 是独立工作承诺单元） | §2.3.2 + §3.2.1 |
| 2 | 🔴 过度强硬 | `business_impact` 不允许覆写 → 长期"误报疲劳" | **允许项目级覆写**：新增 `.vibetracing/business_impacts.json`，双层查找 | §3.3.4 |
| 3 | 🔴 语义重叠 | Task immutability 阻断 exit 2 与 gate BLOCKED 相同 | **新增 exit code 3** 专用于 closed task 引用 | §2.3.1 + §3.1（TaskSessionManager.find_closed_references）+ §3.2.1 |
| 4 | 🟡 指标噪音 | 衍生 task 比例基于标题匹配，易被绕过 | 在 Dashboard 面板 + 设计文档注明"近似指标"定位 | §2.3.4 |
| 5 | 🟡 数据缺口 | 8 维度反思中 5.5 个无法从 Phase 1 数据推导 | `PhaseReflectionEngine` 二期采用混合数据源（task_sessions + 代码扫描 + mock 元数据 + human_decisions） | §3.2 补注 |
| 6 | 🟡 文档误导 | `design_channel_separation.md` 当前为空壳但被引用 | ~~加 `> ⚠️ STUB` 醒目引用块~~ **已 superseded**：文档头已更新为"已批准（PHASE-VT-016 待实施）"状态，STUB 提示不再需要 | — |

**对业务规范的反向修订建议**（需回 `business_task_reflection_trajectory.md` 执行）：
- 规则 1：补充多 task 处理规则
- 规则 4：exit code 从 2 改为 3
- 决策 13：从"不提供覆写"改为"允许项目级覆写（`.vibetracing/business_impacts.json`）"
- 决策 8：补充严重风险判定的双层查找语义
- §9 待架构问题清单：合并本设计中的待答问题，避免双份维护

---

## 2. 目标业务逻辑

> 本节从业务规范文档提取架构设计所需的契约。**不重述业务理由**，仅列出"架构必须满足什么"。

### 2.1 三阶段决策路由模型

VT 信息输出按决策阶段划分：

| 决策阶段 | 核心问题 | 物理通道 | 触发条件 |
|---|---|---|---|
| **执行决策** | Agent 现在怎么改代码 | stdout 前段（Agent 指令段） | 每次 `vt analyze` |
| **验收决策** | 人类判断任务是否算完成 | stdout 末尾段 + Dashboard 存档 | `gate=PASS 且 current_commit_task_set 非空` |
| **治理决策** | 人类判断系统是否在变好 | Dashboard 面板 + 独立文件 | PHASE 结束 / 按需 / 长期 |

### 2.2 Channel 契约

**双通道原则**：

```
stdout (terminal)  = Agent 通道（指令段 + 验收摘要段，按时序共存）
Dashboard (HTML)   = Human 通道（深度阅读 + 长期查阅 + 跨期分析）
```

**stdout 结构**（Agent 指令段 + 验收摘要段物理共存、语义隔离）：

```
GATE DECISION: {decision}
ACTION 1 [HIGH] ...
ACTION N [HIGH/MEDIUM] ...
----------------------------------------------------------------------
SUMMARY
HIGH: X | MEDIUM: Y | LOW: Z
当前阻拦: X 项 | 当前告警: Y 项 | 等待人类: Z 项
Coverage: {pct}% ({status}, target: 80%)
══════════════════════════════════════════════════════════════════════
═══ 任务验收摘要 ═══
任务：TASK-VT-XXX
建议：✅ 接受（2 项遗留 WARNING 无业务影响）
交付：[1-2 句业务描述]
已解决：BLOCK X 项 / WARNING Y 项（共 Z 项）
遗留：WARNING N 项（已接受，无业务影响）
严重风险：无 / [业务影响大的 WARNING]
迭代次数：K
═══ 验收结束 ═══
```

**总量目标**：约 50-70 行（vs 现状 120+ 行，信噪比从 42% → 90%+）。

### 2.3 四大核心概念（数据模型契约）

#### 2.3.1 Task Session（任务会话）

- **边界**：首次 commit 引用 task_id → gate=PASS 且 task_id 在 current_commit_task_set 中
- **状态机**：OPEN → IN_PROGRESS → CLOSED（CLOSED 为终态）
- **持久化**：`.vibetracing/task_sessions.json`
- **CLOSED 后**：数据封存，任何后续 commit 引用触发阻断（exit code 3）

**Exit code 语义四级制**：

| Exit | 语义 | 典型场景 | 可恢复性 |
|---|---|---|---|
| `0` | 成功 | gate=PASS | — |
| `1` | 内部崩溃 | 未捕获异常、输入损坏 | 修复 VT / 输入 |
| `2` | Gate BLOCKED | 检测到可修复 issue | Agent 修复后再次 commit |
| `3` | Closed task 引用 | commit 引用已 CLOSED 的 task | Agent 创建新 task |

exit 3 与 exit 2 隔离的目的：CI 日志可区分"可修复 issue"与"任务边界违反"，便于治理审计。

#### 2.3.2 Acceptance Summary（验收摘要）

- **触发**：`gate=PASS 且 current_commit_task_set 非空`
- **多 task 处理**：若 `current_commit_task_set` 含多个 task_id，**按 task 独立输出多份摘要**（每 task 一个独立 section），不合并。理由：每个 task 是独立工作承诺单元，混合会掩盖差异（如 task A 全清 vs task B 留 WARNING）。stdout 信噪比仍可控：2-3 个 task × 5-8 行 = 15-24 行
- **内容**：5-8 行中文业务语言
- **建议行判定**：严重风险=无 → `✅ 接受`；严重风险≥1 → `⚠️ 驳回`
- **严重风险判定（双层查找）**：
  1. 查项目级覆写文件 `.vibetracing/business_impacts.json`（rule_id → impact 映射）
  2. 未命中 → 查 `field_hints.json` 中对应 hint 的 `business_impact` 默认值
  3. 仍未命中 → 默认 `"high"`（不确定默认有业务影响）
- **业务方覆写约束**：项目级覆写文件由人类（业务方/Agent）在项目内维护，VT 不强制校验格式正确性之外的语义

#### 2.3.3 Phase Reflection（阶段反思）

- **触发**（双触发）：CLI `vt reflect --phase VT-XXX` / Dashboard 点击"生成反思"
- **内容**：8 维度深度反思（详见业务规范规则 2）
- **存储**：`.vibetracing/phase_reflections/PHASE-VT-XXX.md`
- **呈现**：Dashboard "Phase Reflection" 标签页

#### 2.3.4 Governance Evolution（治理演进）

三类指标：

1. **全量规则触发统计表**：规则标识（`issue_type:rule_id` 或 `issue_type:subtype`）/ 描述 / BLOCK 次数 / WARNING 次数 / 最近触发（按 BLOCK 降序）
2. **衍生 task 比例**：标题关键词匹配（"修复/优化/调整 TASK-VT-XXX"），MVP 不做显式 `derived_from` 字段。**注意：该指标为基于标题匹配的近似值**，命名习惯不同的 Agent 可能绕过匹配，导致该指标为 0 或不稳定。Dashboard 面板需显式标注"近似指标"定位，业务方仅作参考，不作为正式治理判定依据
3. **任务平均迭代次数**（按 PHASE 分组）

### 2.4 跨期数据契约

| 数据 | 一期写入 | 一期消费 | 二期写入 | 二期消费 |
|---|---|---|---|---|
| `task_sessions.json.model` | ✅ | ❌ | ✅ | Agent 能力按模型拆分 |
| `task_sessions.json.iterations` | ✅ | 验收摘要 | ✅ | 平均迭代次数指标 |
| `task_sessions.json.issue_counts` | ✅ | 验收摘要 | ✅ | 全量规则触发表 |
| `task_sessions.json.closed_at` | ✅ | immutability 检查 | ✅ | 跨 PHASE 复盘 |
| 全量规则触发表 | ✅ | Dashboard 面板 | ✅ | + 趋势列（跨 PHASE 对比） |

### 2.5 业务决策（架构约束）

来自业务规范 §8 的 12 项决策，全部作为架构硬约束，不重述。架构设计需满足的关键约束摘要：

- **决策 3**：CLOSED task 不可复活，commit 引用触发 exit code 3
- **决策 5**：Agent 能力警告**不阻断**主流程，**不在 stdout 提示**，仅 Dashboard 徽章
- **决策 7**：所有反思报告**中文业务语言**
- **决策 10**：`model` 字段从 `.vibetracing/config.json` 读取，人类手动维护，缺失写 `"unknown"`
- **决策 11**：全量规则触发表替代 Top10/从未触发两个独立指标
- **决策 12**：验收摘要增加系统建议行

---

## 3. 目标代码逻辑

> **二期数据缺口注记**：规则 2 定义的 8 维度 Phase 反思中，仅约 2.5 个维度（项目不足识别、根因修复深度、部分豁免机制）可从 Phase 1 的 `task_sessions.json` 数据推导；其余 5.5 个维度（架构精简度、计算冗余、凭证真实性、代码认知复杂度、残留与死代码）需要**代码层级分析 + 测试 mock 使用率元数据**。因此 `PhaseReflectionEngine` 二期实施时将采用**混合数据源**：`task_sessions.json` + 代码扫描 + `test_results.json` mock 计数 + `human_decisions.json` 统计。Phase 1 不在 `task_sessions.json` 中预先埋点（YAGNI）。

### 3.1 新增模块（4 个）

| 模块 | 位置 | 职责 | 交付期 |
|---|---|---|---|
| **TaskSessionManager** | `domain/task/session.py` | task_sessions.json 读写、状态机、immutability 检查、迭代计数、issue 累加、closed task 引用检测（`find_closed_references`） | 一期 |
| **AcceptanceSummaryBuilder** | `domain/task/acceptance.py` | 从 TaskSession + IssueSignal 构造验收摘要 + 建议行判定 | 一期 |
| **PhaseReflectionEngine** | `domain/reflection/phase.py` | 聚合 PHASE 内所有 TaskSession、生成 8 维度反思 markdown | 二期 |
| **GovernanceMetricsAggregator** | `domain/governance/metrics.py` | 从 task_sessions.json 计算规则触发表、衍生比例、迭代均值 | 一期（基础） + 二期（趋势列） |

### 3.2 扩展模块（4 个）

#### 3.2.1 `cli/analyze/pipeline.py`

**`_evaluate_and_output` 签名扩展**：新增 4 个参数（在现有 12 个基础上）：

- `session_mgr: TaskSessionManager` —— task session 读写与 closed task 检测
- `task_name_lookup: dict[str, str]` —— task_id → task name 映射，用于验收摘要 `delivery` 字段（由 pipeline 从已加载的 task_list 上下文构造）
- `phase_id_lookup: dict[str, str]` —— task_id → phase_id 映射，用于 session 的 `phase_id` 字段（同上）
- `model: str` —— 写入 session 的 model 字段（来自 `config.json`）

**`_evaluate_and_output` 4 步编排**（保持 `_run_gate_evaluation` 只做检测与判定，新增职责在编排层处理）：

1. **closed task 预检查**（在 `_run_gate_evaluation` 调用之前）：调用 `session_mgr.find_closed_references(current_commit_task_set) -> list[str]`，非空则直接返回 exit code 3（短路，不进入 gate 检测）
2. **gate 检测**：调用 `_run_gate_evaluation()`（不变），返回 `gate_res` + `states_and_signals`
3. **session 更新 + 验收摘要**（在 `_run_gate_evaluation` 返回之后）：
   - `session_mgr.update_sessions(current_commit_task_set, states_and_signals, gate_decision, task_name_lookup, phase_id_lookup, model)` 更新 task_sessions.json；CLOSED 的 task 在此步写入 `acceptance_summary.delivery = task_name_lookup[task_id]`
   - 当 `gate=PASS 且 current_commit_task_set 非空` 时，调用 `AcceptanceSummaryBuilder.build_list()` 生成**每 task 一份摘要**（返回 `list[dict]`）
4. **报告构建 + 输出渲染**：`_build_report_document()` + `_render_output()`；验收摘要由 pipeline 将步骤 3 返回的 `list[dict]` **逐个**传给 `_print_acceptance_summary`（不经过 report_doc 中转）

**`AcceptanceSummaryBuilder.build_list` 签名**：

```python
def build_list(
    current_commit_task_set: set[str],
    sessions: dict[str, TaskSession],
    states_and_signals: list[tuple[OutputState, IssueSignal, DetectedIssue]],
) -> list[dict]:
```

- `states_and_signals` 为带状态的信号列表（非裸 `DetectedIssue[]`），用于按 task 统计已解决/遗留 issue 数
- **task 归属策略**：优先使用 `DetectedIssue.related_task_id` 匹配 task；`related_task_id` 为空时（大多数 `_check_*` 方法的现状），归入 `current_commit_task_set` 中的 task（多 task 时按 task 均分或归入首个）
- `AcceptanceSummaryBuilder` 内部初始化 `BusinessImpactResolver`：加载 `.vibetracing/business_impacts.json`（项目覆写）与 `field_hints.json`（系统默认），按 §2.3.2 的双层查找规则判定严重风险
- **`delivery` 字段来源**：由 pipeline 通过 `task_name_lookup[task_id]` 传入 `session_mgr.close_session()`，TaskSessionManager 写入 `acceptance_summary.delivery`。VT 不生成自然语言业务描述，直接复用人类已维护的 task 标题（来自 `task_list.json` 的 `name` 字段）
- **调用方职责**：`build_list` 返回 `list[dict]`，pipeline 遍历 list 逐个传给 `_print_acceptance_summary`（多 task 时输出多份摘要段）

**`_render_output` 重构**：
- 删除 `_print_reflection_prompts` 的 stdout 调用（减少 4 个参数：merged_gaps, final_risks, compliance_res, project_root）
- `_print_gate_summary` 改为 `_print_gate_summary_line`（单行）
- 新增 `_print_acceptance_summary`（仅 gate=PASS 时）
- Dashboard 渲染参数增加 `rule_stats_table`、`agent_capability_metrics`、`governance_metrics`

**`run_analyze` 扩展**：
- 新增 `--task-status <task_id>` 参数（CLI 入口，与 analyze 共用解析逻辑）
- 读取 `config.json` 的 `model` 字段传给 TaskSessionManager

#### 3.2.2 `cli/analyze/output.py`

- `_print_gate_summary` → `_print_gate_summary_line(gate_res)`：仅打印 `GATE DECISION: {decision}` 一行
- 删除 `_print_reflection_prompts` 函数（逻辑迁移到 `PhaseReflectionEngine` + Dashboard 渲染）
- 新增 `_print_acceptance_summary(summary: dict)`：打印验收摘要段
- 新增 `_print_section_separator()`：打印 Agent 指令段与验收摘要段之间的分隔符

#### 3.2.3 `cli/analyze/reports.py`

`_build_report_document` 新增顶层 key：

| 新 key | 语义 | Dashboard 消费 | 交付期 |
|---|---|---|---|
| `acceptance_archive` | 所有 CLOSED task 的验收摘要历史（从 task_sessions 聚合，含当前 run 刚 CLOSED 的 task） | 新面板"验收存档" | 一期 |
| `rule_stats_table` | 全量规则触发统计表（按 BLOCK 降序） | 新面板"治理演进" | 一期 |
| `agent_capability_metrics` | First-time-right / 平均迭代 / 同类重复 / BLOCK 集中度 | 新面板"Agent 能力" + 警告徽章 | 一期 |
| `governance_metrics` | 衍生 task 比例、PHASE 平均迭代 | 新面板"治理演进" | 一期 |
| `phase_reflection` | 当前 PHASE 反思 markdown（已存在时） | 新面板"Phase 反思" | 二期 |
| `trend` | 规则触发跨 PHASE 对比（↑/→/↓） | 规则触发表追加"趋势"列 | 二期 |

#### 3.2.4 `templates/dashboard.template.html`

新增 4 个 Tab（保持现有 4 个 Tab 不变）：

| Tab | 标签 | 数据来源 | 交付期 |
|---|---|---|---|
| 5 | **验收存档** / Acceptance | `report.acceptance_archive` | 一期 |
| 6 | **Phase 反思** / Phase Reflection | `report.phase_reflection`（markdown → HTML） | 二期 |
| 7 | **Agent 能力** / Agent Capability | `report.agent_capability_metrics` | 一期 |
| 8 | **治理演进** / Governance Evolution | `report.rule_stats_table` + `report.governance_metrics` | 一期（+二期追加趋势列） |

### 3.3 数据结构与文件

#### 3.3.1 新增文件结构

```
.vibetracing/
├── config.json                      # 新增 model 字段（一期）
├── task_sessions.json               # 新建（一期）
├── business_impacts.json            # 新建（一期），项目级 business_impact 覆写
├── phase_reflections/               # 新建目录（二期）
│   └── PHASE-VT-XXX.md
└── completion_reports/              # 新建目录（二期）
    └── TASK-VT-XXX.md
```

#### 3.3.2 `task_sessions.json` schema

```json
{
  "schema_version": "1.0.0",
  "tasks": {
    "TASK-VT-190": {
      "task_id": "TASK-VT-190",
      "phase_id": "PHASE-VT-015",
      "status": "CLOSED",
      "first_seen": "2026-07-04T08:00:00Z",
      "closed_at": "2026-07-04T10:30:00Z",
      "iterations": 4,
      "issue_counts": {
        "no_claim": {"BLOCK": 2, "WARNING": 0},
        "chain_broken:GATE-VT-006": {"BLOCK": 3, "WARNING": 1},
        "substandard:coverage": {"BLOCK": 0, "WARNING": 2}
      },
      "model": "claude-opus-4-8",
      "acceptance_summary": {
        "recommendation": "accept",
        "delivery": "统一 Agent Action 消费路径，删除 6 个旧 collector",
        "severe_risks": [],
        "resolved_block": 5,
        "resolved_warning": 7,
        "remaining_warning": 1
      }
    }
  }
}
```

**加载规则**：文件不存在时视为 `{"schema_version": "1.0.0", "tasks": {}}`（不报错），首次 `update_sessions` 时创建文件。

**并发写入**：单进程模型（`vt analyze` 为同步 CLI），无需锁机制。
**版本迁移**：`schema_version` 字段保留，迁移逻辑在 `TaskSessionManager` 内按需实现（YAGNI：一期不预先设计迁移器）。

**`phase_id` 写入来源**：由 pipeline 从已加载的 task_list 上下文中构造 `phase_id_lookup: dict[str, str]`（与 `task_name_lookup` 同模式），通过 `session_mgr.update_sessions` 参数传入。`TaskSessionManager` 在首次创建 session 时写入，后续不更新。

**`issue_counts` key 格式**：复合粒度 `issue_type` 或 `issue_type:rule_id`。
- 非架构类 issue（no_claim、task_failed、isolated_task 等）：key = `issue_type`（如 `"no_claim"`）
- 架构合规类 issue（chain_broken、substandard 中与架构约束相关的）：key = `issue_type:rule_id`（如 `"chain_broken:GATE-VT-006"`）
- 非架构类但需子分类的（如 substandard:coverage）：key = `issue_type:subtype`
- 查找时先精确匹配完整 key，未命中回退到 `issue_type` 前缀聚合

#### 3.3.3 `config.json` schema 变更

```json
{
  "schema_version": "1.1.0",
  "model": "claude-opus-4-8",
  "...": "现有字段保持不变"
}
```

#### 3.3.4 `field_hints.json` 新增 `business_impact` 字段

每个 level1/2/3 同级新增：

```json
"ac_missing_evidence": {
  "level1": "...",
  "level2": "...",
  "level3": "...",
  "business_impact": "high"
}
```

取值：`"high"` / `"low"` / `"none"`。默认 `"high"`（不确定默认有业务影响）。
由 VT 开发者维护，人类不覆写。

#### 3.3.5 `business_impacts.json` schema（新建）

项目级覆写文件，结构与 `field_hints.json` 的 hint 项同构（rule_id → impact 映射）：

```json
{
  "schema_version": "1.0.0",
  "overrides": {
    "no_claim": "low",
    "task_failed:test_failed": "high",
    "substandard:coverage": "low"
  }
}
```

**key 格式规范**：
- 一级 key = `issue_type`（如 `"no_claim"`），匹配该 issue_type 下的所有 issue
- 二级 key = `issue_type:subtype`（如 `"task_failed:test_failed"`），仅匹配特定子类型。subtype 取值与 `issue_counts` 的 key 后缀一致
- 查找顺序：先精确匹配 `issue_type:subtype`，未命中回退到 `issue_type`
- key 中不包含 entity_id（不到 entity 级粒度）

- **加载规则**：不存在时视为空 dict（不报错），格式损坏时 warning 并降级为 field_hints 默认
- **维护者**：人类（业务方 / Agent），VT 不校验语义正确性
- **优先级**：本文件 > field_hints.json 默认 > `"high"` 兜底

### 3.4 CLI 扩展

| 命令 | 参数 | 行为 | 交付期 |
|---|---|---|---|
| `vt analyze` | 无变化 | 正常流程 + task session 更新 + 验收摘要输出 | 一期 |
| `vt analyze --task-status <task_id>` | task_id | 仅查询并打印 task session 状态，不触发分析 | 一期 |
| `vt reflect --phase <phase_id>` | phase_id | 生成 Phase 反思 markdown + 触发 Dashboard 渲染 | 二期 |

### 3.5 输出层数据流

```
_evaluate_and_output()
    ├── 1. session_mgr.find_closed_references() → list[str]
    │       非空 → exit 3（短路）
    ├── 2. _run_gate_evaluation()
    │       ├── engine.detect_all_issues() → DetectedIssue[]
    │       ├── SignalComputer.compute_signals() → (IssueSignal, DetectedIssue)[]
    │       ├── F() × aggregate_gate_decision() → gate_res
    │       └── 返回 (gate_res, states_and_signals)
    ├── 3. TaskSessionManager.update_sessions() → 更新 task_sessions.json
    │       AcceptanceSummaryBuilder.build_list() → list[dict]（仅 gate=PASS）
    └── 4. _build_report_document() + _render_output()
            ├── _print_gate_summary_line()                      # Agent 指令段（单行）
            ├── _print_agent_actions()                           # Agent 指令段（actions）
            ├── for summary in summaries:                        # 验收摘要段（仅 gate=PASS，每 task 一次）
            │       _print_acceptance_summary(summary)
            └── _render_dashboard()                              # Human 通道（report_doc 含全量面板数据）
```

### 3.6 Dashboard 架构选择

**现状**：Dashboard 用 `<script type="application/json">` 嵌入数据，JS 客户端渲染。

**新增面板策略**：

- 一期新增 3 个面板（验收存档 / Agent 能力 / 治理演进）沿用客户端渲染：`<script>` 标签注入 JSON，JS 生成 HTML
- 二期 Phase Reflection 面板：服务端把 markdown 渲染为 HTML 片段注入模板（避免引入客户端 markdown 解析库）

**理由**：与现有 4 个 Tab 保持技术栈一致；Phase Reflection 是独立内容，服务端渲染更合适。

### 3.7 与现有机制的关系

| 现有机制 | 处理 |
|---|---|
| `_print_gate_summary` | 精简为 `_print_gate_summary_line` |
| `_print_reflection_prompts` | 删除 stdout 输出，逻辑迁入 `PhaseReflectionEngine` |
| `_print_agent_actions` | 保留（stdout Agent 指令段核心） |
| `_print_empty_claims_hint` | 保留（Agent 可执行） |
| `report_doc` schema | 新增 6 个 key（见 §3.2.3） |

---

## 4. 现状差距

### 4.1 数据与存储差距

| 维度 | 现状 | 目标 | 差距 |
|---|---|---|---|
| Task session 持久化 | 不存在 | `.vibetracing/task_sessions.json` | **新建** |
| Task immutability | 不检查 | closed task 引用 → exit 3 | **新建** |
| 验收摘要 | 不存在 | stdout + Dashboard 存档 | **新建** |
| 严重风险判定 | `business_impact` 不在 hint 中 | field_hints.json 预设 + 建议行 | **新建** |
| Phase 反思持久化 | 不存在 | `.vibetracing/phase_reflections/PHASE-VT-XXX.md` | **新建** |
| 规则触发表 | 不存在 | 从 task_sessions.json 聚合 | **新建** |
| Agent 能力评分 | 不存在 | 4 指标 + Dashboard 徽章 | **新建** |
| 治理演进指标 | 不存在 | 衍生比例 + 平均迭代 | **新建** |
| config.json.model | 不存在 | 读取并写入 session | **schema 变更** |

### 4.2 输出层差距

| 维度 | 现状 | 目标 | 差距 |
|---|---|---|---|
| stdout gate summary | 70+ 行 [阻拦]/[告警]/[预存] 列表 | 单行 `GATE DECISION: X` | **重构** |
| stdout 验收摘要 | 不存在 | 5-8 行中文业务语言 | **新建** |
| stdout 反思提示 | `_print_reflection_prompts` 直出 8 维度 | 迁移到 Dashboard | **迁移** |
| Dashboard Tab | 4 个 | 8 个（+4） | **扩展** |
| Channel 分流 | 隐式（函数混杂） | `_render_output` 内显式精简 | **重构** |

### 4.3 CLI 差距

| 命令 | 现状 | 目标 | 差距 |
|---|---|---|---|
| `vt analyze` | 无 closed task 检查、无 session 更新、无验收摘要 | 全功能 | **扩展** |
| `vt analyze --task-status` | 不存在 | 查询 task 状态 | **新建** |
| `vt reflect --phase` | 不存在 | Phase 反思生成 | **新建** |

### 4.4 测试差距

| 现有测试 | 处理 |
|---|---|
| `test_cli_analyze.py` | 扩展：closed task 阻断、验收摘要生成、stdout 结构 |
| `test_dashboard_renderer.py` | 扩展：新面板渲染断言 |
| `test_pipeline.py` | 扩展：TaskSessionManager 调用契约 |
| `test_rule_engine_types.py` | 保留 |
| `test_collect_issue_actions.py` | 保留 |

新增测试文件：

- `test_task_session_manager.py`（session 读写、状态机、immutability）
- `test_acceptance_summary_builder.py`（摘要生成、建议行判定）
- `test_phase_reflection_engine.py`（二期）
- `test_governance_metrics.py`（规则触发表、衍生比例）

---

## 5. 重构方案

### 5.1 实施分两期

#### 一期 MVP（业务规范 §6，约 7 工作日）

| 步骤 | 任务 | 工时 | 核心产出 |
|---|---|---|---|
| 1 | TaskSessionManager + schema | 1d | session.py / task_sessions.json / 单元测试 |
| 2 | Task immutability 检查 | 0.5d | session.py `find_closed_references` / pipeline 预检查 / **exit 3** 路径（与常规 gate BLOCKED 的 exit 2 隔离） |
| 3 | 验收摘要生成 + stdout | 1d | acceptance.py / output.py 扩展 / field_hints business_impact 标注 |
| 4 | Agent 能力评分面板 | 1.5d | metrics.py / Dashboard Tab 7 |
| 5 | 治理演进面板 + 规则触发表 | 2d | metrics 扩展 / Dashboard Tab 8 + Tab 5（验收存档） |
| 6 | Channel 分离（gate summary 精简 + 反思 stdout 删除） | 1d | output.py 重构 / 测试迁移 |

**一期落地顺序理由**：先数据（1、2）→ 后呈现（3、4、5）→ 最后通道收尾（6）。步骤 6 放在最后避免 Dashboard 面板开发期间面对脏 stdout。

#### 二期（约 5 工作日，待一期数据积累后启动）

| 步骤 | 任务 | 工时 | 核心产出 |
|---|---|---|---|
| 7 | Phase 反思引擎 + CLI | 2d | phase.py / `vt reflect --phase` / 反思 markdown |
| 8 | Phase 反思 Dashboard 面板 | 1d | Dashboard Tab 6 / markdown→HTML |
| 9 | 治理复盘报告（跨 PHASE 元分析） | 1d | 规则触发表追加趋势列 / 跨 PHASE 聚合 |
| 10 | 任务完成报告完整版文件 | 0.5d | `.vibetracing/completion_reports/TASK-VT-XXX.md` |
| 11 | Agent 能力按 model 拆分 | 0.5d | Dashboard Agent 能力面板分组视图 |

### 5.2 测试策略

**原则**：每个新增模块必须对应测试文件。步骤 1-5 不改 stdout，相关测试无需迁移。步骤 6 修改 stdout 时同步更新受影响的测试（预计影响范围小，仅 gate summary 和 reflection prompts 的 stdout 断言）。

**关键断言点**：

1. CLOSED task 引用 → `exit code = 3`（pipeline 层），与 gate BLOCKED 的 exit 2 严格区分
2. 验收摘要在 gate=PASS 且 current_commit_task_set 非空时一定输出；否则不输出；**多 task 时按 task 输出多份**
3. `.vibetracing/business_impacts.json` 覆写优先级正确（项目覆写 > field_hints 默认 > high 兜底）
4. stdout 中**不再包含** `_print_reflection_prompts` 的 8 维度文本（Channel 分离落地验证）
5. a. Dashboard 渲染后，4 个新 Tab 的容器元素**始终存在**（无论数据是否为空）；b. 当有数据时，容器内数据字段**非空**
6. 规则触发表按 BLOCK 降序、"从未触发"沉底
7. Agent 能力警告**不出现**在 stdout（仅 Dashboard 徽章）
8. `task_sessions.json` CLOSED task 数据在后续 analyze 中**不被修改**（immutability 验证）

### 5.3 风险与缓解

| 风险 | 缓解 |
|---|---|
| **field_hints business_impact 标注工作量大** | 分两步：一期仅标注高频 issue_type（no_claim / chain_broken / task_failed 等 BLOCK 类），其余默认 high |
| **Dashboard Tab 扩展破坏现有布局** | 新增 Tab 不修改现有 4 个 Tab 的 DOM 结构；CSS 变量复用现有样式 |
| **task_sessions.json 跨版本 schema 变化** | 保留 `schema_version` 字段；YAGNI 不预先设计迁移器，按需实现 |
| **`vt analyze --task-status` 与主流程冲突** | 互斥参数：`--task-status` 与常规 analyze 不同时生效 |
| **Phase 反思 markdown 渲染依赖 LLM** | 二期实施时再评估；MVP 用模板填充 8 维度固定结构，不引入 LLM |
| **Channel 分离后测试影响** | 步骤 6 单独收尾；步骤 1-5 不改 stdout，测试无需迁移；步骤 6 的 stdout 变更预计影响范围小（仅 gate summary 和 reflection prompts 相关断言） |
| **config.model 与实际模型一致性靠人类保证** | 已接受的**数据质量风险**：VT 无法校验 config.json 中的 model 字符串是否与实际执行模型一致；一期在决策 10 中显式标注该风险，不做自动检测（最小成本解） |
| **衍生 task 比例指标被业务方过度解读** | Dashboard 面板 + 架构文档均显式标注"基于标题匹配的近似指标，仅作参考" |

### 5.4 不受影响的模块

| 模块 | 原因 |
|---|---|
| `domain/gate/engine.py` 的 15 个 `_check_*` 方法 | 保留（closed task 引用检测已迁至 `TaskSessionManager.find_closed_references`，engine 不感知） |
| `domain/gate/signal_computer.py` | 保留（信号计算不变） |
| `domain/gate/types.py` | 保留（F()、OutputState、Severity 不变） |
| `cli/analyze/actions.py` | 保留（PHASE-VT-015 已落地的 `_collect_issue_actions` 不变） |
| `cli/analyze/formatting.py` | 保留（action 格式化不变） |

### 5.5 排期建议

- **一期绑定 PHASE**：建议作为 PHASE-VT-016 实施
- **二期启动条件**：一期落地 + 至少 2 个 PHASE 的 task_sessions 数据积累（用于跨 PHASE 趋势验证）
- **TASK 命名建议**：
  - 一期：`TASK-VT-XXX: Channel 分离 + 任务反思基础设施（一期 MVP）`
  - 二期：`TASK-VT-YYY: Phase 反思机制 + 治理复盘（二期）`
