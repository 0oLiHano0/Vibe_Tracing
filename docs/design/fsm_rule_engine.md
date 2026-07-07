# 规则引擎：双轴状态模型

> 版本：v4
> 日期：2026-07-03
> 状态：规则定义 + 当前代码差距映射（派生自 `design_historical_debt_mechanism.md` v3）
> 原则：**规则引擎是纯状态变换函数。HISTORICAL 是单一来源状态，不由多层重复计算。**
> 变更（v3→v4）：新增 §1.1 当前实现状态与重构目标、§5.2 目标状态→代码等价、§11 六类问题→信号→状态映射；§2 信号表新增"当前代码近似"列；§1 架构图改为 pipeline 调度宿主。
> 修正（v4.1）：§1.1 activated 信号描述展开完整文件路径推导链（5 步）；§11.4 修正时序约束表述——WARNING issue 不会被 BLOCK issue 过滤出 F() 求值；§1.1 重构路线更新为 8 步（匹配 TASK-VT-180~187）。

---

## 1. 规则引擎在架构中的位置

三层逻辑由 pipeline 统一调度，各模块分工如下：

```
pipeline.py（调度宿主）
  │
  ├─ 1. 调用 engine.detect_all_issues()    → List[DetectedIssue]
  │      └─ engine.py: _check_* / _process_* 方法
  │
  ├─ 2. 调用 SignalComputer.compute()      → List[IssueSignal]   ← 解释层
  │      └─ signal_computer.py + baseline.py
  │
  ├─ 3. 对每个 signal 调用 F(o,a,r,c,v)    → OutputState         ← 规则引擎
  │      └─ types.py: F()
  │
  ├─ 4. state_to_gate_action(state)        → GateAction          ← 门禁层
  │      └─ types.py: state_to_gate_action()
  │
  └─ 5. aggregate → gate_decision ("pass"|"fail"|"blocked")
         └─ types.py: aggregate_gate_decision()
```

**硬约束**：

- 解释层**只输出信号**，不输出 HISTORICAL 或任何状态分类。
- 门禁层**只消费状态**，不重新判定或覆盖 HISTORICAL。
- Dashboard 层**只展示状态**，不重新计算 HISTORICAL。
- **pipeline 是唯一的调度宿主**——各层不互相调用，由 pipeline 串联。

> **HISTORICAL 是规则引擎的单一来源输出。任何其他层不得复制此判定。**

规则引擎是纯函数：`f(signals) → state`。相同输入永远产生相同输出。

### 1.1 当前实现状态与重构目标

> **本文档描述的是目标模型（target），不是当前代码的现实。**

当前 `src/vibe_tracing/domain/gate/engine.py`（`MergeGateEngine`，895 行）是目标模型的前驱实现。两者之间存在三个核心差距，这些差距**就是下一步重构的范围**：

#### 差距 1：输入模型 — 聚合列表 vs per-issue 信号元组

| | 目标 | 当前代码 |
|---|---|---|
| 输入单位 | 每个 issue 的 `(o, a, r, c, v)` 五元信号 | 按检查类型分类的聚合列表 (engine.py:664-680, 14 个参数) |
| `observed` 信号 | fingerprint ∈ Baseline 快照 | **未实现**。无 Baseline 快照机制，无 fingerprint 匹配 |
| `activated` 信号 | `issue.task_id ∈ current_commit_task_set` | `_is_current()` (L96-106): `related_ids & staged_items`。但 `staged_items` 的构建是**多层文件路径血缘推导链**（pipeline.py:227-489）：① `git diff --cached` → `staged_files` ② `find_claimed_and_affected()` 做 `Claim.code_refs ∩ staged_files` → `affected_claim_ids` (claim_coverage.py:72) ③ `_determine_affected_items()` 展开 `affected_claim_ids` → `affected_reqs` + `affected_acs` (staleness.py:11-54) ④ 再从 `affected_claims` 反查 `claim.related_task` → `affected_task_ids` (pipeline.py:472-476) ⑤ 最终 `staged_items = affected_claims ∪ affected_task_ids ∪ affected_acs ∪ affected_reqs` (pipeline.py:470-479)。全链均为文件路径推导，**与 Task 承诺无关**。重构时需删除整条推导链，替换为 `current_commit_task_set` 直接注入 |
| `resolved` 信号 | 自动核销：`all gap_targets ⊆ current_claim_coverage` | `human_decisions` 中的 `mark_complete` 操作（人工标记，L719-720） |
| `accepted` 信号 | 存在有效的人类接受记录 | `human_decisions` 中的 `accept_risk` 操作 → `accepted_risk_target_ids` (L717-718) |
| `severity` 信号 | 六类检查系统的 {BLOCK, WARNING} 输出 | 各 `_check_*` 方法的 `blocked_items` / `any_fail` 二分路，无统一的 severity 枚举 |

**`activated` 信号的实现偏差是最高优先级问题**：`design_historical_debt_mechanism.md` Section 7 明确将 `staged_files ∩ Claim.code_refs` 标注为"不应该采用的方案"——文件是共享资源而非责任边界，且该方案会惩罚正确的工程行为。当前代码恰好在做文档反对的事。

#### 差距 2：输出模型 — 3 态字符串 vs 5 态枚举

| | 目标 | 当前代码 |
|---|---|---|
| 输出类型 | `(state, display_attrs)` per issue，state ∈ {RESOLVED, ACCEPTED, HISTORICAL, CURRENT_BLOCK, CURRENT_WARNING} | `{"gate_decision": "pass"|"fail"|"blocked", "reasons": [...], ...}` (L649-657) |
| HISTORICAL | 明确的 per-issue 状态，保留原始 severity | `_historical_debt_count` 计数器 (L67)，仅显示为 `"📊 N historical debts exist"` (L647)。历史债务失去个体身份和 severity |
| RESOLVED | 覆盖即核销，自动触发 | 仅通过人类 `mark_complete` 操作触发 |
| ACCEPTED | 人类显式接受，含 reason/expires_at | 仅通过人类 `accept_risk` 操作触发，无过期机制 |

当前代码的 3 态与目标 5 态之间存在粗略语义对应：`blocked` ≈ CURRENT_BLOCK，`fail` ≈ CURRENT_WARNING（当前）+ HISTORICAL（非当前时标记 `[预存]`），但这是聚合决策而非 per-issue 状态分类。

#### 差距 3：Baseline 机制 — 未实现

目标模型中 `observed` 信号依赖 Baseline（VT 首次接管项目时的一次性认知快照）。当前代码中该机制完全未实现。所有 issue 等价于 `observed=false`——`incremental_only` 模式通过 `_is_current()` 返回 false 来隐式区分新旧，而非通过 Baseline fingerprint 匹配。

#### 重构路线

以上三个差距是结构性的。重构不应修补当前实现，而应按以下顺序重建：

1. **定义数据类型**（TASK-VT-180）：`IssueSignal`、`Severity`、`OutputState`、`GateAction`、纯函数 `F()`、`state_to_gate_action()`、`aggregate_gate_decision()`。
2. **实现 Baseline 快照**（TASK-VT-181）：`observed` 信号来源。由 pipeline 在 VT 首次运行时调用 `generate_snapshot()`，engine 仅消费 `is_observed()` 查询。
3. **重构 engine.py**（TASK-VT-182）：`_check_*` / `_process_*` 方法改为返回 `List[DetectedIssue]`，统一 severity 输出。engine 精简为纯 issue 检测器。
4. **实现信号计算器**（TASK-VT-183）：`SignalComputer.compute()` — `List[DetectedIssue]` → `List[IssueSignal]`。
5. **Pipeline 层 — activated 修正**（TASK-VT-184）：`staged_items` 从文件血缘改为 commit message + `VT_TASKS` 的 Task 承诺。
6. **Pipeline 层 — 集成调度**（TASK-VT-185）：pipeline 串联全部层级——调 engine 检测 issue → SignalComputer 计算信号 → F 函数判定状态 → state_to_gate_action 映射门禁行为 → aggregate 输出 gate_decision。engine.py 的旧 `evaluate()` 和 `_compute_gate_decision()` 删除。
7. **Dashboard 适配**（TASK-VT-186）：per-issue 状态展示。
8. **测试与文档**（TASK-VT-187）。

> **Section 11 提供了六类问题检测→信号→状态的完整映射**，可作为解释层实现的输入规格。

---

## 2. 输入信号

| 信号 | 类型 | 目标来源 | 当前代码近似 (engine.py) | 含义 |
|------|------|---------|------------------------|------|
| `observed` | bool | fingerprint ∈ Baseline 快照 | **未实现**。所有 issue 等效 `observed=false`。`incremental_only` 模式通过 `_is_current()` 隐式区分新旧 | 此 issue 是否已被系统认知 |
| `activated` | bool | `issue.task_id ∈ current_commit_task_set`（Task 承诺） | `_is_current()` (L96-106): `related_ids & staged_items`。但 `staged_items` 由文件路径血缘构建（pipeline.py:227-479，`Claim.code_refs ∩ staged_files`），非 Task 承诺。**此偏差与 `design_historical_debt_mechanism.md` §7 标注的错误方案一致** | 归属 Task 是否在当前提交中 |
| `resolved` | bool | all gap_targets ⊆ current_claim_coverage（自动核销） | `human_decisions` 中 `mark_complete` 操作 → `resolved_gap_target_ids` (L719-720)，仅人工标记，无自动核销 | 所有缺口是否已被当前 Claim 覆盖 |
| `accepted` | bool | 存在有效的人类接受记录（含 expires_at） | `human_decisions` 中 `accept_risk` 操作 → `accepted_risk_target_ids` (L717-718)，无过期机制 | 人类是否已显式接受此 issue |
| `severity` | enum {BLOCK, WARNING} | 六类检查系统的输出 | 各 `_check_*` 方法 `blocked_items` / `any_fail` 二分路，无统一 severity 枚举。各方法内联判断 severity 等价物 | 此 issue 的严重级别 |

规则引擎不质疑信号。信号错误 → 修复信号来源。

---

## 3. 域不变量（Domain Invariance Contracts）

以下三个不变量是规则引擎的**硬约束**。任何规则扩展不得违反。

### Invariant 1 — HISTORICAL 域不变量

```
observed = true ∧ activated = false → 此 issue 在同一评估周期内
始终属于 INACTIVE 域（severity 不参与判定）。
```

此不变量保证：只要 issue 在 Baseline 中且 Task 未被激活，它就不会因 severity 被重新拉入门禁。

### Invariant 2 — ACTIVE 域不变量

```
¬(observed = true ∧ activated = false) → 此 issue 属于 ACTIVE 域。
在 ACTIVE 域中，severity 信号参与状态判定。
```

此不变量保证：新问题或已激活 Task 的历史问题，一律进入可评估 severity 的域。

### Invariant 3 — RESOLVED 优先不变量

```
resolved = true → 输出状态 = RESOLVED。
此条覆盖域轴、治理轴、severity 的所有组合。
```

此不变量保证：已修复的 issue 不存在于门禁系统中。不需要人类接受，不产生告警。

### 3.1 Invariant 优先级（硬约束）

三个 Invariant 之间存在严格的求值优先级。此优先级派生自状态组合表（Section 5）的行顺序，提取为 Invariant 层面的显式约束，防止未来规则扩展破坏求值顺序。

```
优先级从高到低：

  Invariant 3 (RESOLVED)
    → 最高。resolved=true 时立即终止，不进入后续判定。

  Invariant 1 / 2 (域判定)
    → 第二。确定 INACTIVE 或 ACTIVE 域。
    → INACTIVE 域中 severity 不参与状态判定。

  治理轴 (accepted)
    → 第三。在域判定之后求值。

  severity
    → 最低。仅在 ACTIVE 域 + 治理轴 = NORMAL 时生效。
```

**等价求值流程**（优先级短路，每步命中即终止）：

```
Step 1: resolved = true ?           → RESOLVED（终止）
Step 2: accepted = true ?           → ACCEPTED（终止）
Step 3: observed ∧ ¬activated ?     → HISTORICAL（终止）
Step 4: severity = BLOCK ?          → CURRENT_BLOCK（终止）
Step 5: （剩余）                    → CURRENT_WARNING（终止）
```

Step 3 的 guard `observed ∧ ¬activated` 即 INACTIVE 域判定。到达 Step 4 时，必在 ACTIVE 域中，severity 必为 BLOCK 或 WARNING——不存在其他分支。

**约束**：任何新增轴或规则不得改变此优先级顺序。新增内容只能追加在现有优先级之后，或插入已有层级之间（如在治理轴和 severity 之间插入新轴），不得提升优先级。

---

## 4. 双轴模型

规则引擎将五个信号映射到两个独立轴，加上域判定（Invariant 1/2），组合为输出状态。

### 4.1 域判定（Scope）

域判定不由轴承载——它是输入信号的直接条件判断，受 Invariant 1 和 Invariant 2 约束：

| 条件 | 域 | severity 是否生效 |
|------|-----|-----------------|
| `observed=true ∧ activated=false` | **INACTIVE** | 否 |
| 其他所有情况 | **ACTIVE** | 是 |

"INACTIVE" 是域标记，不是输出状态。输出状态 HISTORICAL = INACTIVE 域 + 特定轴组合（见第 5 节）。

**域 ≠ 轴（硬约束）**：

域是 guard（条件门控），不是 axis（组合维度）。轴（Lifecycle、Governance）是独立正交的信号投影，参与状态组合。域控制组合表的求值路径——决定后续哪些信号生效——但域本身不进入组合表的维度空间。

此区分对 severity 的影响：

| 域 | severity 角色 | 含义 |
|-----|-------------|------|
| ACTIVE | **决策信号** | 参与状态判定（BLOCK → CURRENT_BLOCK，WARNING → CURRENT_WARNING） |
| INACTIVE | **issue 固有属性** | 不参与状态判定，仅透传至 Dashboard 用于展示（🔴/🟡） |

severity 始终是 issue 的固有属性。规则引擎在 ACTIVE 域中消费它做决策，在 INACTIVE 域中忽略它做决策、仅透传它做展示。

### 4.2 生命周期轴（Lifecycle Axis）

| 条件 | 轴值 |
|------|------|
| `resolved=true` | RESOLVED |
| `resolved=false` | UNRESOLVED |

输入信号：`resolved`。

### 4.3 治理轴（Governance Axis）

| 条件 | 轴值 |
|------|------|
| `accepted=true` | ACCEPTED |
| `accepted=false` | NORMAL |

输入信号：`accepted`。

### 4.4 轴独立性

```
observed ──→ 域判定（Invariant 1/2）──→ INACTIVE / ACTIVE
activated ─┘

resolved ──→ 生命周期轴 ──→ RESOLVED / UNRESOLVED

accepted ──→ 治理轴 ──→ ACCEPTED / NORMAL
```

三路独立计算。添加新轴（如 Urgency）时不影响已有轴逻辑，只扩展组合表。

---

## 5. 状态组合表

域 × 生命周期轴 × 治理轴 × severity → 输出状态。

```
域        生命周期轴   治理轴     severity  │  输出状态
──────────────────────────────────────────┼──────────────
  *        RESOLVED     *          *      │  RESOLVED        (Invariant 3)
INACTIVE   UNRESOLVED  NORMAL       *      │  HISTORICAL
INACTIVE   UNRESOLVED  ACCEPTED     *      │  ACCEPTED
ACTIVE     UNRESOLVED  ACCEPTED     *      │  ACCEPTED
ACTIVE     UNRESOLVED  NORMAL     BLOCK    │  CURRENT_BLOCK
ACTIVE     UNRESOLVED  NORMAL     WARNING  │  CURRENT_WARNING
```

`*` = 任意值。

### 5.1 行解释

**行 1**：生命周期 = RESOLVED → RESOLVED。Invariant 3。gap 不存在，不需要治理决策。

**行 2**：INACTIVE 域 + 未解决 + 未接受 → **HISTORICAL**。VT 接管前存在、当前 Task 未激活、未修复、人类未接受。门禁展示但不阻拦。原始 severity 保留为展示属性（🔴/🟡）。

**行 3**：INACTIVE 域 + 未解决 + 已接受 → **ACCEPTED**。人类已确认接受此历史债务。

**行 4**：ACTIVE 域 + 未解决 + 已接受 → **ACCEPTED**。人类已接受此当前问题。约束：CURRENT_BLOCK 不可被接受——此约束由信号层（人类操作端）执行。若操作端 bug 导致 blocking issue 携带 accepted=true，此行产出 ACCEPTED，应修复操作端。

**行 5**：ACTIVE 域 + 未解决 + 未接受 + BLOCK → **CURRENT_BLOCK**。阻拦。

**行 6**：ACTIVE 域 + 未解决 + 未接受 + WARNING → **CURRENT_WARNING**。告警。

**关于 o=0, a=0（新 issue + 未激活）**：此组合落入 ACTIVE 域（行 5-6），severity 生效，可能被阻拦。这是有意的设计决策——阻拦的判定标准是"存在客观可验证的错误"，不是"这个错误是否由当前开发者引入"。新 issue 不在 Baseline 中，说明代码库存在已知质量问题，不论谁遇到都应阻拦。开发者的处理路径：修复（→ RESOLVED）、关联 Task 到当前提交（→ 正常 CURRENT 流程）、或人类接受（→ ACCEPTED）。详见 `design_rule_engine_formal_fsm.md` Section 9.2。

### 5.2 目标状态 → 当前代码等价

> 本节服务于重构：明确每个目标状态在当前 `engine.py` 中对应的实现片段，以便逐状态迁移。

| 目标状态 | 当前代码等价 | 代码位置 | 差距 |
|---------|------------|---------|------|
| RESOLVED | `resolved_gap_target_ids` 中的 item 从 `blocked_items` 移除，标记 `[已人工完成]` | L411, L719-720 (`mark_complete` 操作) | 目标：自动核销（覆盖即 RESOLVED）。当前：仅人工操作触发 |
| ACCEPTED | `accepted_risk_target_ids` / `accepted_rule_target_ids` 中的 item，标记 `[已接受风险]` | L464-466, L717-718 (`accept_risk` 操作) | 目标：含 `reason`/`accepted_by`/`expires_at` 完整记录。当前：无过期，无结构化接受记录 |
| HISTORICAL | `_historical_debt_count += 1`，原因项标记 `[预存]` | L67, L109-119 (`_tag_reason`), L168/L210/L252/L300 等 15 处 | 目标：per-issue 状态含原始 severity 透传。当前：聚合计数器，issue 个体身份和 severity 全部丢失 |
| CURRENT_BLOCK | `blocked_items.append(msg)` → `gate_decision = "blocked"` | L165, L208, L249, L297, L325 等 | 目标：per-issue 状态。当前：聚合到全局 `gate_decision`，无法区分哪些 issue 各自导致了阻拦 |
| CURRENT_WARNING | `current_fail_detected = True` → `gate_decision = "fail"` | L570-587 (`_compute_gate_decision`) | 目标：per-issue 状态。当前：聚合到全局 `gate_decision`，"告警"和"非当前历史债务"混在同一 `fail` 态中 |

---

## 6. 输出状态定义

规则引擎输出为一个二元组：

```
Output = (state, display_attrs)

state         = F(o, a, r, c, v) 的输出状态（下表五行之一）
display_attrs = { severity: v }   透传 issue 固有属性，不参与状态判定
```

| 状态 | 门禁行为 | Dashboard |
|------|---------|-----------|
| RESOLVED | 无动作 | 从活跃列表移除 |
| ACCEPTED | 无动作 | 展示，标记"已接受"，附原因和有效期 |
| HISTORICAL | 无动作 | 展示，保留原始 severity 颜色（🔴/🟡），不阻拦不告警 |
| CURRENT_BLOCK | **阻拦** | 🔴 展示 |
| CURRENT_WARNING | **告警** | 🟡 展示 |

HISTORICAL 的原始 severity 传递到 Dashboard 但不影响门禁——这是 issue 固有属性，不由规则引擎修改。

---

## 7. 执行契约

### 7.1 确定性

纯函数。五信号入，一状态出。不依赖时序、外部状态、随机数。

### 7.2 同一周期内的终止性

同一提交周期内，五个输入信号不变 → 轴值不变 → 输出状态不变。RESOLVED 和 ACCEPTED 是终止状态，不可回退。

### 7.3 跨周期的重新评估

`activated` 信号在后续提交中从 false 变为 true → 域从 INACTIVE 变为 ACTIVE → 重新评估，可能产出不同状态。这不是同周期回退——是新提交的新评估。

### 7.4 域不变量的优先级

三个 Invariant 是硬约束。完整的求值优先级定义见 Section 3.1。任何新增轴或规则必须与三个 Invariant 兼容，且不得改变已有优先级顺序。冲突时，Invariant 优先。

---

## 8. 规则引擎不做什么

| 不属于规则引擎 | 属于谁 |
|-------------|--------|
| 判断 issue 是否真的被修复 | 解释层（resolved 信号） |
| 判断人类接受是否合理 | 人类操作层（accepted 信号 + 约束逻辑） |
| 判断 issue 严重度 | 六类检查系统（severity 信号） |
| 判断 baseline 是否正确 | Baseline 快照管理（observed 信号） |
| 输出 HISTORICAL 之外的"类似分类" | 任何其他层不得复制 HISTORICAL 判定 |
| 处理部分核销 | 解释层内部（resolved=true 仅当全部覆盖） |
| 处理僵尸 gap target | 解释层（无效 target 静默移除） |
| 区分 VT 接管后存量 | 不存在此区分——observed 只按 Baseline 判定 |

---

## 9. 与相关文档的关系

| 文档 | 内容 | 受众 |
|------|------|------|
| `design_historical_debt_mechanism.md` | WHY/WHAT — 业务逻辑定义 | 系统设计者 |
| `design_rule_engine.md`（本文档） | HOW — 轴 + 组合 + 不变量 + 代码差距映射 | 实现者 |
| `design_rule_engine_formal_fsm.md` | 形式化 FSM 定义 — 完备性/互斥性证明 | 实现者（验证参考） |
| `spec_stage7_business_logic_v2.md` | 六类问题检测定义 | 实现者 |

本文档派生自 `design_historical_debt_mechanism.md` v3。如有冲突，以业务逻辑文档为准。

**阅读路径**：
- 理解业务逻辑 → `design_historical_debt_mechanism.md`
- 理解规则引擎目标模型 → 本文档 §1–§8
- 验证规则引擎数学性质 → `design_rule_engine_formal_fsm.md`
- 理解当前代码与目标的差距 → 本文档 §1.1、§5.2
- 实现解释层（信号计算）→ 本文档 §11 + `spec_stage7_business_logic_v2.md`

---

## 10. 扩展协议

规则引擎必须为未来扩展预留空间，同时保证已有不变量不被破坏。本节定义扩展的硬约束和操作规则。

### 10.1 扩展的两种类型

| 类型 | 含义 | 示例 |
|------|------|------|
| 新增轴 | 引入一个新的独立信号维度，参与状态组合 | Urgency 轴（紧急度）、Recurrence 轴（复发次数） |
| 新增规则 | 在已有轴上增加分支或细化判定 | severity 增加 CRITICAL 级别 |

两种类型的约束不同。

### 10.2 新增轴的约束

新增轴必须满足三个条件：

**条件 1：信号独立性**

新轴必须基于一个不在当前五个信号中的新输入信号。如果新轴的输入可以由已有信号推导，它不是轴，是已有轴的派生函数。

```
✅ 合法：Urgency 轴 ← 新信号 urgency（来自外部工单系统）
❌ 非法：severity_weight 轴 ← f(severity, observed)（可由已有信号推导）
```

**条件 2：不违反已有 Invariant**

新轴不得改变 Invariant 1/2/3 的语义。具体检验方法：对 Invariant 覆盖的所有输入组合，新轴加入后输出状态不变。

```
检验 Invariant 3：
  resolved=true 时，无论新轴取何值 → 输出必须仍为 RESOLVED

检验 Invariant 1：
  observed=true ∧ activated=false 时，无论新轴取何值 →
  输出必须仍为 HISTORICAL 或 ACCEPTED（不得变为 CURRENT_*）
```

**条件 3：遵守优先级顺序**

新轴必须插入 Section 3.1 定义的优先级序列中的某个位置，不得提升已有层级的优先级。

```
当前优先级：
  Invariant 3 > 域判定 > 治理轴 > severity

合法插入位置（示例）：
  Invariant 3 > 域判定 > 治理轴 > [新轴] > severity
  Invariant 3 > 域判定 > [新轴] > 治理轴 > severity

非法：
  [新轴] > Invariant 3 > 域判定 > ...（提升了新轴优先级，破坏 Invariant 3）
```

### 10.3 新增规则的约束

新增规则（在已有轴上增加分支）必须满足：

**完备性**：新规则必须覆盖所有遗漏的输入组合，不留"未定义"状态。组合表的每一行必须有且仅有一个输出。

**互斥性**：新规则不得与已有行产生重叠。同一输入组合不得命中两行。

**操作**：新增规则 = 在组合表中新增行或拆分已有行。

```
示例：severity 增加 CRITICAL 级别

原行 5：ACTIVE + UNRESOLVED + NORMAL + BLOCK → CURRENT_BLOCK
拆分为：
  行 5a：ACTIVE + UNRESOLVED + NORMAL + CRITICAL → CURRENT_BLOCK（escalated）
  行 5b：ACTIVE + UNRESOLVED + NORMAL + BLOCK → CURRENT_BLOCK
  行 5c：ACTIVE + UNRESOLVED + NORMAL + WARNING → CURRENT_WARNING

约束：
  - INACTIVE 域中的行不拆分（severity 不参与判定）
  - RESOLVED 行不拆分（Invariant 3）
```

### 10.4 扩展检查清单

每次扩展前，逐项确认：

```
□ 新轴/规则是否基于新信号？（不是已有信号的派生）
□ Invariant 3 是否仍成立？（resolved=true → RESOLVED，不受新轴影响）
□ Invariant 1 是否仍成立？（INACTIVE 域不会被 severity 拉入 CURRENT_*）
□ Invariant 2 是否仍成立？（ACTIVE 域中 severity 仍生效）
□ 优先级顺序是否保持不变？（新内容插入，不提升已有层级）
□ 组合表是否仍完备且互斥？（每行唯一输出，无遗漏）
□ 新增内容是否在 Section 3.1 优先级中有明确位置？
```

### 10.5 不应扩展的方向

| 方向 | 为什么不应做 |
|------|-----------|
| 在 INACTIVE 域中引入 severity 判定 | 违反 Invariant 1。HISTORICAL 不因 severity 变为 CURRENT_* |
| 让 RESOLVED 可回退 | 违反 Invariant 3 和 Section 7.2 终止性。同周期内 RESOLVED 不可逆 |
| 增加"域"作为组合维度 | 域是 guard，不是 axis。增加域维度会破坏 Section 4.1 的 guard 语义 |
| 在规则引擎内处理部分核销 | 属于解释层职责（Section 8）。规则引擎只接收 resolved=true/false |

---

## 11. 六类问题 → 信号 → 状态映射

> 本节将 `spec_stage7_business_logic_v2.md` 的六类问题映射到本引擎的信号输入和状态输出。
> 这是解释层（信号计算）的实现规格——解释层的职责是将每类问题的检测结果转化为 `(o, a, r, c, v)` 信号元组，规则引擎消费信号产出状态。

### 11.1 映射总表

| # | 分类 | spec 决策 | severity | 当前 engine.py 方法 | 当前 severity 判定 | 目标状态（activated=true） | 目标状态（activated=false） |
|---|------|---------|----------|-------------------|-------------------|--------------------------|---------------------------|
| 1 | **链条中断** | 阻拦 | BLOCK | `_check_invalid_task_references` (L303-394): invalid_requirements/acs/modules/constraints + `_check_dangling_claims` (L171-211) | 内联：`blocked_items.append` | CURRENT_BLOCK | observed ? HISTORICAL : CURRENT_BLOCK |
| 2 | **链条错位** | 阻拦 | BLOCK | `_check_invalid_task_references` (L367-393): invalid_ac_parents + invalid_module_code_paths | 内联：`blocked_items.append` | CURRENT_BLOCK | observed ? HISTORICAL : CURRENT_BLOCK |
| 3 | **孤立任务** | 告警 | WARNING | `_compute_gate_decision` (L628-633): `isolated_tasks` 参数 → reasons 追加 `[告警]` | 硬编码：始终 warning-level，不触发 blocked/fail | CURRENT_WARNING | observed ? HISTORICAL : CURRENT_WARNING |
| 4 | **无声明** | 阻拦 | BLOCK | `_check_claim_existence` (L121-169): ghost code + `_check_ac_coverage` (L256-301): no_claim_for_task | 内联：`blocked_items.append` | CURRENT_BLOCK | observed ? HISTORICAL : CURRENT_BLOCK |
| 5 | **任务失败** | 阻拦 | BLOCK | `_check_claim_evidence_gaps` (L213-254): verification_status == "test_failed" | 内联：仅 test_failed 时 `blocked_items.append` (L246-252) | CURRENT_BLOCK | observed ? HISTORICAL : CURRENT_BLOCK |
| 6 | **任务不达标** | 告警 | WARNING | `_compute_gate_decision` (L590-625): cov_violations + lint_violations | 内联：cov/lint 违规 → `gate_decision = "fail"` (L603, L622) | CURRENT_WARNING | observed ? HISTORICAL : CURRENT_WARNING |

### 11.2 信号构造规则

解释层为每个 issue 计算五元信号时，遵循以下规则：

**`severity` 信号**：

```
六类中 BLOCK 分类（1/2/4/5） → severity = BLOCK
六类中 WARNING 分类（3/6）    → severity = WARNING
```

**`activated` 信号**：

```
issue.task_id ∈ current_commit_task_set → activated = true
否则                                      → activated = false
```

`current_commit_task_set` 是开发者显式声明的本次提交涉及的 Task ID 集合。**不是**从文件路径推导的集合。此信号在 pipeline 层构造，与 `find_claimed_and_affected()` 的文件路径血缘解耦。

**`observed` 信号**：

```
issue.fingerprint ∈ Baseline 快照 → observed = true
否则                               → observed = false
```

Baseline 快照在 VT 首次接管项目时生成，记录所有可检测 issue 的 fingerprint。不滚动更新。

**`resolved` 信号**：

```
all gap_targets ⊆ current_claim_coverage → resolved = true
否则                                       → resolved = false
```

覆盖即核销。任意 Task 的 Claim 覆盖了 gap target 即计入，不限于 issue 归属的 Task。

**`accepted` 信号**：

```
存在有效的人类接受记录（未过期） → accepted = true
否则                             → accepted = false
```

### 11.3 当前代码中的 severity 内联问题

当前 engine.py 中 severity 的判定**分散在各 `_check_*` 方法内部**，没有统一的 severity 枚举出口。具体表现：

| 方法 | BLOCK 判定 | WARNING 判定 |
|------|-----------|-------------|
| `_check_claim_existence` | `blocked_items.append(msg)` (L165) | — |
| `_check_dangling_claims` | `blocked_items.append(msg)` (L208) | — |
| `_check_claim_evidence_gaps` | `verification_status == "test_failed"` 时 `blocked_items.append` (L249) | 非 "test_failed" 时静默 |
| `_check_ac_coverage` | `blocked_items.append(msg)` (L297) | — |
| `_check_invalid_task_references` | `blocked_items.append(msg)` (L325 等) | — |
| `_process_must_gaps` | `blocked_items.append(msg)` (L424) | 非 current 时 `final_status = "passed"` (L428) |
| `_process_should_gaps` | — | `any_fail = True` (L523) |
| `_compute_gate_decision` (cov/lint) | — | `gate_decision = "fail"` (L603, L622) |
| `_compute_gate_decision` (isolated_tasks) | — | reasons 追加 `[告警]`，不改变 gate_decision (L628-633) |

**重构时**：解释层应统一输出 `severity ∈ {BLOCK, WARNING}`，不再由各方法分别操纵 `blocked_items` 和 `gate_decision`。

### 11.4 spec 时序依赖在信号模型中的体现

`spec_stage7_business_logic_v2.md` 定义了六类问题的评估时序：

```
链条中断 ──→ 链条错位 ──┐
                        ├──→ 无声明 ──→ 任务失败 ──→ 任务不达标
孤立任务（始终可并行） ──┘
```

在信号模型中，时序依赖体现为信号计算的依赖关系，**不由规则引擎处理**：

| 时序约束 | 在信号模型中的体现 |
|---------|-----------------|
| 链条中断是最高优先级 | 解释层在计算 issue 列表时，若检测到中断则跳过后续分类（无法评估） |
| 无声明需要 req→task 链路完整 | `resolved` 信号仅在链路完整的 issue 上计算 |
| 任务失败需要 Claim 存在 | `resolved` 信号依赖 Claim 证据 |
| 任务不达标需要测试通过 | `resolved` 信号的计算依赖测试结果（测试未通过 → 无法确定是否达标）。若任务失败的 BLOCK issue 与任务不达标的 WARNING issue 属于同一 Task，解释层可跳过 WARNING issue 的信号计算（因为链的上游已阻断）。但**已成功计算信号的 WARNING issue 不会因存在 BLOCK issue 而被过滤**——所有已计算信号的 issue 均进入 F() 求值 |

规则引擎的 `F(o,a,r,c,v)` 不关心时序——它消费的是已完成信号计算的 issue 列表。时序是解释层的内部实现细节。
