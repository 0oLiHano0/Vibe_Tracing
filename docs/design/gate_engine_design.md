# Gate Engine 设计规格

> **版本**：v5（已落地）
> **日期**：2026-07-03（设计规格），2026-07-07（合并形式化验证 + 落地状态确认）
> **定位**：门禁判定引擎的完整设计规格——从信号定义到状态输出，含完备性/互斥性证明。
> **原则**：规则引擎是纯状态变换函数。HISTORICAL 是单一来源状态，不由多层重复计算。
> **落地状态**：✅ 全部落地（2026-07-07 确认）。`types.py`（F/DetectedIssue/IssueSignal/OutputState）、`engine.py`（detect_all_issues）、`signal_computer.py`（SignalComputer）、`baseline.py`（BaselineManager）、`pipeline.py`（detect → Signal → F → aggregate 调度链）。

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

## 2. 输入信号空间

每个 issue 在一个评估周期内的输入为一个五元组：

```
S = (o, a, r, c, v)
```

| 信号 | 符号 | 类型 | 来源 | 含义 |
|------|------|------|------|------|
| `observed` | o | bool | fingerprint ∈ Baseline 快照 | 此 issue 是否已被系统认知 |
| `activated` | a | bool | `issue.task_id ∈ current_commit_task_set` | 归属 Task 是否在当前提交中 |
| `resolved` | r | bool | all gap_targets ⊆ current_claim_coverage | 所有缺口是否已被当前 Claim 覆盖 |
| `accepted` | c | bool | 存在有效的人类接受记录 | 人类是否已显式接受此 issue |
| `severity` | v | enum {BLOCK, WARNING} | 六类检查系统的输出 | 此 issue 的严重级别 |

输入空间大小：2 × 2 × 2 × 2 × 2 = **32 种输入组合**。

规则引擎不质疑信号。信号错误 → 修复信号来源。

## 3. 域不变量

以下三个不变量是规则引擎的**硬约束**。

### Invariant 1 — HISTORICAL 域不变量

```
observed = true ∧ activated = false → 此 issue 在同一评估周期内
始终属于 INACTIVE 域（severity 不参与判定）。
```

### Invariant 2 — ACTIVE 域不变量

```
¬(observed = true ∧ activated = false) → 此 issue 属于 ACTIVE 域。
在 ACTIVE 域中，severity 信号参与状态判定。
```

### Invariant 3 — RESOLVED 优先不变量

```
resolved = true → 输出状态 = RESOLVED。
此条覆盖域轴、治理轴、severity 的所有组合。
```

### Invariant 优先级（等价求值流程）

求值优先级从高到低，每步命中即终止：

```
Step 1: r=1 ?             → RESOLVED（终止）
Step 2: c=1 ?             → ACCEPTED（终止）
Step 3: o=1 ∧ a=0 ?       → HISTORICAL（终止）
Step 4: v=B ?             → CURRENT_BLOCK（终止）
Step 5: (剩余)            → CURRENT_WARNING
```

### Invariant 证明

**Invariant 1**：`o=1 ∧ a=0` 时，若 `r=1` → R1 命中（RESOLVED，这是 Invariant 3 的覆盖）。若 `r=0 ∧ c=1` → R2 命中（ACCEPTED）。若 `r=0 ∧ c=0` → R3 命中（HISTORICAL），`v` 不参与 R3 判定。在 R1 和 R2 未命中的条件下，`o=1 ∧ a=0` 始终映射到 HISTORICAL。✅

**Invariant 2**：`¬(o=1 ∧ a=0)` = `(o=0 ∨ a=1)`。在 R1、R2、R3 均未命中的条件下（`r=0, c=0, ¬(o=1∧a=0)`），进入 R4/R5，`v` 参与判定。✅

**Invariant 3**：R1 是优先级链中的第一个规则。`r=1` 时 R1 命中，直接返回 RESOLVED，不进入 R2-R5。✅

## 4. 双轴模型

### 4.1 域函数（Domain Guard）

域是条件门控，不是状态输出，不是组合维度：

```
D(o, a) =
  INACTIVE    if o=1 ∧ a=0
  ACTIVE      otherwise
```

| 域 | severity 角色 | 含义 |
|-----|-------------|------|
| ACTIVE | **决策信号** | 参与状态判定（BLOCK → CURRENT_BLOCK，WARNING → CURRENT_WARNING） |
| INACTIVE | **展示属性** | 不参与状态判定，仅透传至 Dashboard 用于展示 |

### 4.2 生命周期轴

```
L(r) =
  RESOLVED      if r=1
  UNRESOLVED    if r=0
```

### 4.3 治理轴

```
G(c) =
  ACCEPTED    if c=1
  NORMAL      if c=0
```

### 4.4 轴独立性

三路独立计算。添加新轴时不改变已有逻辑。

## 5. 状态函数

### 5.1 定义

F 是规则函数的优先级短路组合：

```
F(o, a, r, c, v) =
  RESOLVED          if r=1
  ACCEPTED          if r=0 ∧ c=1
  HISTORICAL        if r=0 ∧ c=0 ∧ o=1 ∧ a=0
  CURRENT_BLOCK     if r=0 ∧ c=0 ∧ (o=0 ∨ a=1) ∧ v=B
  CURRENT_WARNING   if r=0 ∧ c=0 ∧ (o=0 ∨ a=1) ∧ v=W
```

**关键性质**：这是优先级短路求值，不是笛卡尔积组合。每个分支命中即终止。

### 5.2 规则展开

| 规则 | 条件 | 输出 | 终止？ |
|------|------|------|--------|
| R1 | r=1 | RESOLVED | 是 |
| R2 | r=0 ∧ c=1 | ACCEPTED | 是 |
| R3 | r=0 ∧ c=0 ∧ o=1 ∧ a=0 | HISTORICAL | 是 |
| R4 | r=0 ∧ c=0 ∧ (o=0 ∨ a=1) ∧ v=B | CURRENT_BLOCK | 是 |
| R5 | r=0 ∧ c=0 ∧ (o=0 ∨ a=1) ∧ v=W | CURRENT_WARNING | 是 |

### 5.3 完备性证明

```
R1 覆盖：r=1                          → 16 种组合（o,a,c,v 任意）
R2 覆盖：r=0, c=1                     →  8 种组合（o,a,v 任意）
R3 覆盖：r=0, c=0, o=1, a=0           →  2 种组合（v ∈ {B,W}）
R4 覆盖：r=0, c=0, (o=0∨a=1), v=B     →  3 种组合（(o,a) ∈ {(0,0),(0,1),(1,1)}）
R5 覆盖：r=0, c=0, (o=0∨a=1), v=W     →  3 种组合
                                          ─────────
                                    合计：32 种 ✅
```

**完备且互斥。每个输入组合命中且仅命中一条规则。**

### 5.4 互斥性证明

```
R1 ∩ R2 = ∅  (r=1 vs r=0)
R1 ∩ R3 = ∅  (r=1 vs r=0)
R1 ∩ R4 = ∅  (r=1 vs r=0)
R1 ∩ R5 = ∅  (r=1 vs r=0)
R2 ∩ R3 = ∅  (c=1 vs c=0)
R2 ∩ R4 = ∅  (c=1 vs c=0)
R2 ∩ R5 = ∅  (c=1 vs c=0)
R3 ∩ R4 = ∅  (o=1∧a=0 vs o=0∨a=1)
R3 ∩ R5 = ∅  (o=1∧a=0 vs o=0∨a=1)
R4 ∩ R5 = ∅  (v=B vs v=W)
```

### 5.5 完整枚举表

| o | a | r | c | v | 命中规则 | 输出状态 |
|---|---|---|---|---|---|---------|---------|
| * | * | 1 | * | * | R1 | RESOLVED |
| * | * | 0 | 1 | * | R2 | ACCEPTED |
| 1 | 0 | 0 | 0 | * | R3 | HISTORICAL |
| 0 | 0 | 0 | 0 | B | R4 | CURRENT_BLOCK |
| 0 | 0 | 0 | 0 | W | R5 | CURRENT_WARNING |
| 0 | 1 | 0 | 0 | B | R4 | CURRENT_BLOCK |
| 0 | 1 | 0 | 0 | W | R5 | CURRENT_WARNING |
| 1 | 1 | 0 | 0 | B | R4 | CURRENT_BLOCK |
| 1 | 1 | 0 | 0 | W | R5 | CURRENT_WARNING |

`*` = 任意值。共 9 行覆盖 32 种组合。

### 5.6 行解释

**R1**（RESOLVED）：生命周期 = RESOLVED → 立即终止。gap 不存在，不需要治理决策。

**R2**（ACCEPTED）：未解决 + 已接受 → 人类已确认接受。可作用于任一域。

**R3**（HISTORICAL）：INACTIVE 域 + 未解决 + 未接受。VT 接管前存在、当前 Task 未激活。门禁展示但不阻拦。原始 severity 保留为展示属性。

**R4**（CURRENT_BLOCK）：ACTIVE 域 + 未解决 + 未接受 + BLOCK → 阻拦。

**R5**（CURRENT_WARNING）：ACTIVE 域 + 未解决 + 未接受 + WARNING → 告警。

### 5.7 o=0, a=0（新 issue + 未激活）设计决策

```
o=0（不在基线中）, a=0（未激活）, r=0, c=0：
  → D = ACTIVE → R4/R5 → CURRENT_BLOCK/WARNING
  新 issue 未被当前提交处理 → 阻拦。
```

这是**有意的设计决策**：阻拦的判定标准是"存在客观可验证的错误"，不是"这个错误是否由当前开发者引入"。开发者的处理路径：

| 路径 | 操作 | 结果 |
|------|------|------|
| 修复 | 直接修复 issue | → r=1 → RESOLVED |
| 关联 Task | 将 issue 关联的 Task 加入当前提交 | → a=1 → 正常 CURRENT 流程 |
| 人类决策 | 人类判断是否接受 | → c=1 → ACCEPTED |

## 6. 输出状态定义

### 输出模型

规则引擎输出为一个二元组：

```
Output = (state, display_attrs)

state         = F(o, a, r, c, v)
display_attrs = { severity: v }   透传 issue 固有属性
```

### 状态空间

```
Q = { RESOLVED, ACCEPTED, HISTORICAL, CURRENT_BLOCK, CURRENT_WARNING }
```

| 状态 | 门禁行为 | Dashboard |
|------|---------|-----------|
| RESOLVED | 无动作 | 从活跃列表移除 |
| ACCEPTED | 无动作 | 展示，标记"已接受"，附原因和有效期 |
| HISTORICAL | 无动作 | 展示，保留原始 severity 颜色（🔴/🟡），不阻拦不告警 |
| CURRENT_BLOCK | **阻拦** | 🔴 展示 |
| CURRENT_WARNING | **告警** | 🟡 展示 |

### severity 的双重角色

| 域 | severity 角色 | 说明 |
|-----|-------------|------|
| ACTIVE | **决策信号** | 参与 F 的求值（R4/R5），决定 CURRENT_BLOCK vs CURRENT_WARNING |
| INACTIVE | **展示属性** | 不参与 F 的求值（R3 不消费 v），仅通过 display_attrs 透传至 Dashboard |

## 7. 执行契约

### 确定性

纯函数。五信号入，一状态出。不依赖时序、外部状态、随机数。

### 同周期终止性

同一提交周期内，五个输入信号不变 → 轴值不变 → 输出状态不变。RESOLVED 和 ACCEPTED 是终止状态，不可回退。

### 跨周期重新评估

`activated` 信号在后续提交中可能从 false 变为 true。这不是同周期回退——是新提交的新评估。

```
周期 N：  Task A 不在提交中，a=0
  (o=1, a=0, r=0, c=0, v=B) → HISTORICAL

周期 N+1：Task A 被激活，a=1
  (o=1, a=1, r=0, c=0, v=B) → CURRENT_BLOCK
```

## 8. 规则引擎不做什么

| 不属于规则引擎 | 属于谁 |
|-------------|--------|
| 判断 issue 是否真的被修复 | 解释层（resolved 信号） |
| 判断人类接受是否合理 | 人类操作层（accepted 信号 + 约束逻辑） |
| 判断 issue 严重度 | 六类检查系统（severity 信号） |
| 判断 baseline 是否正确 | Baseline 快照管理（observed 信号） |
| 输出 HISTORICAL 之外的"类似分类" | 任何其他层不得复制 HISTORICAL 判定 |
| 处理部分核销 | 解释层内部（resolved=true 仅当全部覆盖） |

## 9. 六类问题 → 信号 → 状态映射

> 本节将 `docs/business_logic/spec_stage7_business_logic_v2.md` 的六类问题映射到本引擎的信号输入和状态输出。

### 9.1 映射总表

| # | 分类 | severity | 目标状态（activated=true） | 目标状态（activated=false） |
|---|------|----------|--------------------------|---------------------------|
| 1 | **链条中断** | BLOCK | CURRENT_BLOCK | observed ? HISTORICAL : CURRENT_BLOCK |
| 2 | **链条错位** | BLOCK | CURRENT_BLOCK | observed ? HISTORICAL : CURRENT_BLOCK |
| 3 | **孤立任务** | WARNING | CURRENT_WARNING | observed ? HISTORICAL : CURRENT_WARNING |
| 4 | **无声明** | BLOCK | CURRENT_BLOCK | observed ? HISTORICAL : CURRENT_BLOCK |
| 5 | **任务失败** | BLOCK | CURRENT_BLOCK | observed ? HISTORICAL : CURRENT_BLOCK |
| 6 | **任务不达标** | WARNING | CURRENT_WARNING | observed ? HISTORICAL : CURRENT_WARNING |

### 9.2 信号构造规则

**`severity`**：六类中 BLOCK 分类（1/2/4/5）→ BLOCK；WARNING 分类（3/6）→ WARNING。

**`activated`**：`issue.task_id ∈ current_commit_task_set` → true。由 pipeline 层构造，与文件路径血缘解耦。

**`observed`**：`issue.fingerprint ∈ Baseline 快照` → true。Baseline 在 VT 首次接管项目时生成，不滚动更新。

**`resolved`**：`all gap_targets ⊆ current_claim_coverage` → true。覆盖即核销。

**`accepted`**：存在有效的人类接受记录（未过期）→ true。

### 9.3 时序依赖

六类问题的评估时序由解释层处理，规则引擎不关心：

```
链条中断 ──→ 链条错位 ──┐
                        ├──→ 无声明 ──→ 任务失败 ──→ 任务不达标
孤立任务（始终可并行） ──┘
```

解释层在计算 issue 列表时，若检测到中断则跳过后续分类。规则引擎消费的是已完成信号计算的 issue 列表。

## 10. 扩展协议

### 扩展检查清单

每次扩展前逐项确认：

```
□ 新轴/规则是否基于新信号？（不是已有信号的派生）
□ Invariant 3 是否仍成立？（r=1 → RESOLVED，不受新轴影响）
□ Invariant 1 是否仍成立？（INACTIVE 域不会被 severity 拉入 CURRENT_*）
□ Invariant 2 是否仍成立？（ACTIVE 域中 severity 仍生效）
□ 优先级顺序是否保持不变？（新内容插入，不提升已有层级）
□ 组合表是否仍完备且互斥？（每行唯一输出，无遗漏）
□ 新增内容是否在优先级中有明确位置？
```

### 不应扩展的方向

| 方向 | 为什么不应做 |
|------|-----------|
| 在 INACTIVE 域中引入 severity 判定 | 违反 Invariant 1 |
| 让 RESOLVED 可回退 | 违反 Invariant 3 和终止性 |
| 增加"域"作为组合维度 | 域是 guard，不是 axis |
| 在规则引擎内处理部分核销 | 属于解释层职责 |

---

## 附录：FSM 流程图

```
                ┌────────────┐
                │  输入信号   │
                │ (o,a,r,c,v) │
                └─────┬──────┘
                      │
                      ▼
              ┌───────────────┐
          R1  │  r = 1 ?      │─── YES ──→ RESOLVED（终止）
              └───────┬───────┘
                      │ NO
                      ▼
              ┌───────────────┐
          R2  │  c = 1 ?      │─── YES ──→ ACCEPTED（终止）
              └───────┬───────┘
                      │ NO
                      ▼
              ┌───────────────┐
          R3  │ o=1 ∧ a=0 ?   │─── YES ──→ HISTORICAL（终止）
              └───────┬───────┘           severity 透传为展示属性
                      │ NO
                      ▼
              ┌───────────────┐
          R4  │  v = B ?      │─── YES ──→ CURRENT_BLOCK（终止）
              └───────┬───────┘
                      │ NO
                      ▼
                CURRENT_WARNING（终止）
```
