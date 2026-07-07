# 规则引擎形式化定义

> 版本：v2
> 日期：2026-07-03
> 状态：形式化建模（派生自 `design_rule_engine.md` v3）
> 原则：**规则引擎是优先级短路求值函数，不是笛卡尔积查表。**

---

## 1. 概述

本文档将 `design_rule_engine.md` 中的规则引擎定义转化为形式化状态机模型。目的：

1. 消除自然语言描述中的歧义
2. 显式表达规则的优先级短路语义
3. 提供可直接验证的完备性/互斥性证明
4. 为代码实现提供精确规格

本文档与 `design_rule_engine.md` 是同一系统的两种表述。如有冲突，以 `design_rule_engine.md` 中的 Invariant 定义为准。

---

## 2. 输入信号空间

每个 issue 在一个评估周期内的输入为一个五元组：

```
S = (o, a, r, c, v)
```

| 符号 | 含义 | 取值 | 来源 |
|------|------|------|------|
| o | observed | {0, 1} | fingerprint ∈ Baseline |
| a | activated | {0, 1} | issue.task_id ∈ current_commit_task_set |
| r | resolved | {0, 1} | all gap_targets ⊆ current_claim_coverage |
| c | accepted | {0, 1} | 存在有效的人类接受记录 |
| v | severity | {B, W} | 六类检查系统的输出（BLOCK / WARNING） |

输入空间大小：2 × 2 × 2 × 2 × 2 = **32 种输入组合**。

规则引擎不质疑信号来源。信号错误 → 修复信号来源，不在规则引擎内处理。

---

## 3. 域函数（Domain Guard）

域函数是条件门控，不是状态输出，不是组合维度：

```
D(o, a) =
  INACTIVE    if o=1 ∧ a=0
  ACTIVE      otherwise
```

**硬约束**：域是 guard，不是 axis。域控制后续信号的求值路径，但域本身不进入状态组合的维度空间。详见 `design_rule_engine.md` Section 4.1。

---

## 4. 轴函数（Axis Functions）

### 4.1 生命周期轴

```
L(r) =
  RESOLVED      if r=1
  UNRESOLVED    if r=0
```

### 4.2 治理轴

```
G(c) =
  ACCEPTED    if c=1
  NORMAL      if c=0
```

### 4.3 门禁轴

```
A(v) =
  BLOCK       if v=B
  WARNING     if v=W
```

**域受限**：A(v) 仅在 ACTIVE 域中被消费（R_severity 的 guard 包含 D(o,a)=ACTIVE）。在 INACTIVE 域中，severity 不参与 F 的求值，仅作为展示属性透传（见 Section 10.2）。

三个轴独立计算，互不影响。

---

## 5. 状态空间

输出状态集合：

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

---

## 6. 状态函数（核心）

### 6.1 规则函数定义

每个规则 R_i 是一个 guard + output 对。guard 命中时返回 output，否则返回 ⊥（未命中，传递给下一条规则）：

```
R_resolve(r) =
  RESOLVED    if L(r) = RESOLVED
  ⊥           otherwise

R_accept(r, c) =
  ACCEPTED    if L(r) = UNRESOLVED ∧ G(c) = ACCEPTED
  ⊥           otherwise

R_domain(o, a, r, c) =
  HISTORICAL  if D(o,a) = INACTIVE ∧ L(r) = UNRESOLVED ∧ G(c) = NORMAL
  ⊥           otherwise

R_severity(o, a, r, c, v) =
  CURRENT_BLOCK    if D(o,a) = ACTIVE ∧ L(r) = UNRESOLVED ∧ G(c) = NORMAL ∧ A(v) = BLOCK
  CURRENT_WARNING  if D(o,a) = ACTIVE ∧ L(r) = UNRESOLVED ∧ G(c) = NORMAL ∧ A(v) = WARNING
  ⊥                otherwise
```

### 6.2 状态函数（分段定义）

F 是规则函数的优先级短路组合：

```
F(o, a, r, c, v) =
  RESOLVED          if r=1
  ACCEPTED          if r=0 ∧ c=1
  HISTORICAL        if r=0 ∧ c=0 ∧ o=1 ∧ a=0
  CURRENT_BLOCK     if r=0 ∧ c=0 ∧ (o=0 ∨ a=1) ∧ v=B
  CURRENT_WARNING   if r=0 ∧ c=0 ∧ (o=0 ∨ a=1) ∧ v=W
```

等价使用轴函数的表述：

```
F(o, a, r, c, v) =
  RESOLVED          if L(r) = RESOLVED
  ACCEPTED          if L(r) = UNRESOLVED ∧ G(c) = ACCEPTED
  HISTORICAL        if D(o,a) = INACTIVE ∧ L(r) = UNRESOLVED ∧ G(c) = NORMAL
  CURRENT_BLOCK     if D(o,a) = ACTIVE ∧ L(r) = UNRESOLVED ∧ G(c) = NORMAL ∧ A(v) = BLOCK
  CURRENT_WARNING   if D(o,a) = ACTIVE ∧ L(r) = UNRESOLVED ∧ G(c) = NORMAL ∧ A(v) = WARNING
```

**关键性质**：这是优先级短路求值，不是笛卡尔积组合。每个分支命中即终止，不进入后续分支。

### 6.3 等价求值流程

```
Step 1: r=1 ?           → RESOLVED（终止）
Step 2: c=1 ?           → ACCEPTED（终止）
Step 3: o=1 ∧ a=0 ?     → HISTORICAL（终止）
Step 4: v=B ?           → CURRENT_BLOCK（终止）
Step 5: (剩余)          → CURRENT_WARNING
```

### 6.4 组合函数表述

```
F(s) = first_defined(R_resolve(s), R_accept(s), R_domain(s), R_severity(s))
```

其中 `first_defined` 返回第一个非 ⊥ 的结果。这是**优先级短路**，不是代数复合。

---

## 7. Transition Matrix

### 7.1 规则展开

| 规则 | 条件 | 输出 | 终止？ |
|------|------|------|--------|
| R1 | r=1 | RESOLVED | 是 |
| R2 | r=0 ∧ c=1 | ACCEPTED | 是 |
| R3 | r=0 ∧ c=0 ∧ o=1 ∧ a=0 | HISTORICAL | 是 |
| R4 | r=0 ∧ c=0 ∧ (o=0 ∨ a=1) ∧ v=B | CURRENT_BLOCK | 是 |
| R5 | r=0 ∧ c=0 ∧ (o=0 ∨ a=1) ∧ v=W | CURRENT_WARNING | 是 |

### 7.2 完备性证明

```
R1 覆盖：r=1                          → 16 种组合（o,a,c,v 任意）
R2 覆盖：r=0, c=1                     →  8 种组合（o,a,v 任意）
R3 覆盖：r=0, c=0, o=1, a=0           →  2 种组合（v ∈ {B,W}）
R4 覆盖：r=0, c=0, (o=0∨a=1), v=B     →  3 种组合（(o,a) ∈ {(0,0),(0,1),(1,1)}）
R5 覆盖：r=0, c=0, (o=0∨a=1), v=W     →  3 种组合（(o,a) ∈ {(0,0),(0,1),(1,1)}）
                                          ─────────
                                    合计：32 种 ✅
```

### 7.3 互斥性证明

```
R1 ∩ R2 = ∅  (r=1 vs r=0)
R1 ∩ R3 = ∅  (r=1 vs r=0)
R1 ∩ R4 = ∅  (r=1 vs r=0)
R1 ∩ R5 = ∅  (r=1 vs r=0)
R2 ∩ R3 = ∅  (c=1 vs c=0)
R2 ∩ R4 = ∅  (c=1 vs c=0)
R2 ∩ R5 = ∅  (c=1 vs c=0)
R3 ∩ R4 = ∅  (o=1∧a=0 vs o=0∨a=1，互斥)
R3 ∩ R5 = ∅  (o=1∧a=0 vs o=0∨a=1，互斥)
R4 ∩ R5 = ∅  (v=B vs v=W，互斥)
```

**完备且互斥。每个输入组合命中且仅命中一条规则。**

### 7.4 完整枚举表

| o | a | r | c | v | 命中规则 | 输出状态 |
|---|---|---|---|---|---------|---------|
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

---

## 8. Invariant 验证

### 8.1 Invariant 1 — HISTORICAL 域不变量

```
声明：o=1 ∧ a=0 → 同一评估周期内始终属于 INACTIVE 域，severity 不参与判定。

验证：o=1 ∧ a=0 时，若 r=1 → R1 命中（RESOLVED），但这是 Invariant 3 的覆盖。
      若 r=0 ∧ c=1 → R2 命中（ACCEPTED），这是治理轴的覆盖。
      若 r=0 ∧ c=0 → R3 命中（HISTORICAL），v 不参与 R3 判定。
      
      在 R1 和 R2 未命中的条件下，o=1 ∧ a=0 始终映射到 HISTORICAL，
      且 v（severity）不参与 R3 的条件判定。✅
```

### 8.2 Invariant 2 — ACTIVE 域不变量

```
声明：¬(o=1 ∧ a=0) → ACTIVE 域，severity 参与状态判定。

验证：¬(o=1 ∧ a=0) = (o=0 ∨ a=1)。
      在 R1、R2、R3 均未命中的条件下（r=0, c=0, ¬(o=1∧a=0)），
      进入 R4/R5，v 参与判定：v=B → CURRENT_BLOCK，v=W → CURRENT_WARNING。✅
```

### 8.3 Invariant 3 — RESOLVED 优先不变量

```
声明：r=1 → 输出 RESOLVED，覆盖域轴、治理轴、severity 的所有组合。

验证：R1 是优先级链中的第一个规则。r=1 时 R1 命中，直接返回 RESOLVED，
      不进入 R2-R5。无论 o,a,c,v 取何值，输出均为 RESOLVED。✅
```

### 8.4 优先级不变量

```
声明：求值优先级为 R1 > R2 > R3 > R4/R5。

验证：分段函数（Section 6.2）的分支顺序即为优先级顺序。
      每个分支命中即终止，后续分支不求值。
      新增规则只能插入已有分支之间或追加在末尾，不得提升优先级。✅
```

---

## 9. 输入空间覆盖性

### 9.1 完备覆盖

F 对所有 32 种输入组合都有定义，且每种组合的映射在业务语义上正确。不存在需要异常检测的"漏洞"组合。

逐域验证：

```
INACTIVE 域（o=1 ∧ a=0）：
  r=1 → RESOLVED（已修复的基线问题，终止）
  r=0, c=1 → ACCEPTED（人类已接受的基线问题，终止）
  r=0, c=0 → HISTORICAL（经典历史债务，展示不阻拦）
  ✅ 所有组合语义正确

ACTIVE 域（其余情况）：
  r=1 → RESOLVED（已修复，终止）
  r=0, c=1 → ACCEPTED（人类已接受，终止）
  r=0, c=0, v=B → CURRENT_BLOCK（阻拦）
  r=0, c=0, v=W → CURRENT_WARNING（告警）
  ✅ 所有组合语义正确
```

### 9.2 "new + 未激活"的设计决策

`design_historical_debt_mechanism.md` 提到"new + 未激活"的情况。在形式化模型中：

```
o=1（在基线中）, a=0（未激活）, r=0, c=0：
  → D = INACTIVE → R3 → HISTORICAL
  经典历史债务。可见但不阻拦。

o=0（不在基线中）, a=0（未激活）, r=0, c=0：
  → D = ACTIVE → R4/R5 → CURRENT_BLOCK/WARNING
  新 issue 未被当前提交处理 → 阻拦。
```

第二种情况可能阻拦一个与此 issue 无关的开发者。这是**有意的设计决策**，不是遗漏：

**理由**：阻拦的判定标准是"存在客观可验证的错误"，不是"这个错误是否由当前开发者引入"。新 issue 是客观错误——它不在基线中，说明代码库存在已知质量问题。不论谁遇到，都应阻拦。

**开发者的处理路径**：

| 路径 | 操作 | 结果 |
|------|------|------|
| 修复 | 直接修复 issue | → r=1 → RESOLVED |
| 关联 Task | 将 issue 关联的 Task 加入当前提交 | → a=1 → 正常 CURRENT 流程 |
| 人类决策 | 人类判断是否接受或延后处理 | → c=1 → ACCEPTED |

### 9.3 跨周期信号变化

`activated` 信号在后续提交中可能从 0 变为 1。这不是同周期内的状态回退——是新提交的新评估周期。每次评估周期独立运行 F。

```
周期 N：  Task A 不在提交中，a=0
  (o=1, a=0, r=0, c=0, v=B) → HISTORICAL

周期 N+1：Task A 被激活，a=1
  (o=1, a=1, r=0, c=0, v=B) → CURRENT_BLOCK
```

这是两次独立的 F 调用，不是状态机内的 transition。业务含义：开发者显式承诺了 Task A，其已知问题成为开发者的责任。

---

## 10. 输出注解

### 10.1 完整输出

状态函数的输出不仅是状态，还包括透传的展示属性：

```
Output = (state, display_attrs)

state         = F(o, a, r, c, v)
display_attrs = { severity: v }
```

### 10.2 severity 的双重角色

| 域 | severity 角色 | 说明 |
|-----|-------------|------|
| ACTIVE | **决策信号** | 参与 F 的求值（R4/R5），决定 CURRENT_BLOCK vs CURRENT_WARNING |
| INACTIVE | **展示属性** | 不参与 F 的求值（R3 不消费 v），仅通过 display_attrs 透传至 Dashboard |

severity 始终是 issue 的固有属性。规则引擎在 ACTIVE 域中消费它做决策，在 INACTIVE 域中忽略它做决策、仅透传它做展示。

### 10.3 Dashboard 消费规则

| state | display_attrs.severity 是否消费 | Dashboard 行为 |
|-------|-------------------------------|---------------|
| RESOLVED | 不消费 | 从活跃列表移除 |
| ACCEPTED | 不消费 | 展示"已接受"标记 |
| HISTORICAL | **消费** | 🔴（severity=B）或 🟡（severity=W） |
| CURRENT_BLOCK | 隐含消费 | 🔴（与 severity=B 一致） |
| CURRENT_WARNING | 隐含消费 | 🟡（与 severity=W 一致） |

---

## 11. FSM 流程图

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

---

## 12. 与 `design_rule_engine.md` 的映射

| 形式化本文档 | `design_rule_engine.md` |
|------------|----------------------|
| Section 2 输入信号空间 | Section 2 输入信号 |
| Section 3 域函数 | Section 4.1 域判定 |
| Section 4 轴函数 | Section 4.2-4.3 生命周期轴 + 治理轴 |
| Section 6 状态函数 | Section 5 状态组合表 |
| Section 7 Transition Matrix | Section 5 状态组合表（等价，不同表述） |
| Section 8 Invariant 验证 | Section 3 域不变量 |
| Section 9 输入空间覆盖性 | Section 4.3 注释（new + 未激活） |
| Section 10 输出注解 | Section 4.1 severity 角色表 + Section 6 输出状态定义 |

本文档是 `design_rule_engine.md` 的形式化重述，不引入新的业务逻辑。

---

## 13. 扩展协议摘要

扩展规则引擎时，必须保证：

1. **完备性**：扩展后的规则链覆盖所有输入组合，无遗漏
2. **互斥性**：扩展后的规则链中，每个输入组合仍只命中一条规则
3. **Invariant 兼容**：不违反 Invariant 1/2/3（见 Section 8）
4. **优先级不提升**：新规则插入已有优先级之间或追加在末尾，不提升已有层级

详细扩展协议见 `design_rule_engine.md` Section 10。
