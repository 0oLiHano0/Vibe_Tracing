# 历史债务判定机制：业务逻辑定义

> 版本：v3
> 日期：2026-07-03
> 状态：业务逻辑定义（架构收敛版）
> 原则：**本文档只定义业务逻辑，不涉及代码实现。**

---

## 1. 一句话定义

**历史债务 = 系统首次观测（Baseline）时已存在，且当前 Task 未承诺解决的存量问题。**

判定依据不是"文件路径是否被触及"，而是：

> **这个 issue 是否属于当前 Task 的责任范围。**

---

## 2. 两层架构：解释层与决策层

历史债务机制的核心架构约束：

```
┌─────────────────────────────────────┐
│           解 释 层                   │
│  只回答：这个 issue 是什么？         │
│                                     │
│  Issue Type → 语义（什么问题）       │
│  Task ID    → 归属（谁的）           │
│  Gap Target → 匹配键（核销用）       │
│  Baseline   → 是否已被系统认知       │
│  Evidence   → 验证载体（凭什么判断） │
└─────────────────────────────────────┘
                  ↓ 输出：issue 的属性集
┌─────────────────────────────────────┐
│           决 策 层                   │
│  只回答：门禁应该怎么处理？           │
│                                     │
│  输入：解释层的属性集                 │
│  输出：门禁行为（阻拦/告警/展示）     │
│  输出：issue 状态（5 种之一）        │
└─────────────────────────────────────┘
```

**解释层不决定门禁行为。决策层不解释问题来源。** 两者不混。

---

## 3. 解释层：三个约束投影

每个 issue 被三个约束函数投影，得到三个独立属性：

### 3.1 认知约束：是否已被系统观测

| 条件 | 属性值 |
|------|--------|
| Issue 指纹存在于 Baseline 中 | **已观测**（observed） |
| Issue 指纹不存在于 Baseline 中 | **新观测**（new） |

Baseline 是 VT 首次接管项目时生成的一次性认知快照。它记录当时系统能发现的所有 issue 指纹。Baseline 不滚动更新。

**关键语义**：这不是"时间前/后"，而是"系统是否已经见过这个 issue"。同一个问题修复后重新出现 → 指纹重新生成，与 baseline 中的旧指纹不匹配 → new。

### 3.2 归属约束：属于哪个 Task

每个 issue 关联一个 Task ID。这是**静态归属**——issue 属于哪个 Task，在 issue 产生时就确定了，不随后续提交变化。

```
归属判定：issue.task_id → Task
```

### 3.3 修复约束：关联哪个 Gap Target

每个 issue 关联一个或多个 Gap Target。Gap Target 是**匹配键**，唯一职责是在核销时做匹配。

```
Gap Target = 匹配键，不承载语义
Issue Type = 语义容器
Evidence  = 验证载体
```

| 层 | 职责 | 示例 |
|---|------|------|
| Issue Type | 这是什么问题 | 链断裂、测试失败、lint 违反、覆盖率不足 |
| Gap Target | 核销时用什么匹配 | `AC-003`, `rule:E501`, `test_foo.py::test_bar` |
| Evidence | 凭什么判断 | 测试结果 JSON、lint 报告、覆盖率数据 |

不同 Issue Type 的 Gap Target 格式可以不同，不需要统一。核销匹配只关心"当前 Claim 是否覆盖了这个 target"，与 target 的语义无关。

---

## 4. 决策层：激活判定 + 状态分类

### 4.1 激活判定

解释层给出了 issue 的静态属性。决策层追加一个**动态判定**：

```
激活判定：issue.task_id ∈ current_commit_task_set ?
```

| 激活结果 | 含义 |
|---------|------|
| 已激活 | 当前提交包含了产生这个 issue 的 Task |
| 未激活 | 当前提交没有包含产生这个 issue 的 Task |

**激活判定 ≠ 归属判定。** 归属是静态的（issue 永远属于那个 Task），激活是动态的（这个 Task 是否在本次提交中）。

### 4.2 状态分类（5 个状态）

结合解释层属性 + 激活判定 + issue 严重度，得到最终状态：

| 状态 | 判定条件 | 门禁行为 |
|------|---------|---------|
| **CURRENT_BLOCK** | new + 激活 + block 严重度 | 阻拦 |
| **CURRENT_WARNING** | new + 激活 + warning 严重度 | 告警 |
| **HISTORICAL** | observed + 未激活 | 展示，不影响门禁 |
| **RESOLVED** | 任意 + 所有 gap target 被当前 Claim 覆盖 | 从债务列表移除 |
| **ACCEPTED** | 人类显式标记接受 | 展示，不影响门禁 |

**5 个状态，没有更多。**

### 4.3 状态判定流程

```
输入：issue（含 type、severity、task_id、gap_targets、fingerprint）

Step 1: 认知查询
  fingerprint ∈ Baseline ?
    → 是 → observed
    → 否 → new

Step 2: 激活判定
  issue.task_id ∈ current_commit_task_set ?
    → 是 → 已激活
    → 否 → 未激活

Step 3: 核销判定
  current_claims 覆盖范围 ∩ issue.gap_targets ?
    → 全部覆盖 → RESOLVED（终止）
    → 部分覆盖 → 内部记录覆盖进度，继续判定
    → 未覆盖 → 继续判定

Step 4: 人类接受判定
  issue 被人类标记为 accepted ?
    → 是 → ACCEPTED（终止）
    → 否 → 继续判定

Step 5: 状态输出
  observed + 未激活 → HISTORICAL
  new + 已激活 + block → CURRENT_BLOCK
  new + 已激活 + warning → CURRENT_WARNING
```

注意：**new + 未激活** 不是异常情况——规则引擎的状态函数 F 对所有 32 种输入组合都有正确映射：

- **o=1（在基线中）+ 未激活**：经典历史债务 → HISTORICAL。语义正确。
- **o=0（不在基线中）+ 未激活**：非基线 issue 未被当前提交处理 → ACTIVE 域 → CURRENT_BLOCK/WARNING。被 F 正确阻拦。语义正确。

两种情况都被 F 正确覆盖，不存在"漏网之鱼"。详见 `design_rule_engine_formal_fsm.md` Section 9。

---

## 5. 两种特殊场景的处理

### 5.1 部分核销：内部追踪，不产生新状态

一笔 HISTORICAL 债务可能有多个 gap target。当前 Claim 覆盖了其中一部分时：

- **对外状态**：保持 HISTORICAL（因为未全部覆盖）
- **内部追踪**：记录已覆盖的 gap target 数量（M/N）
- **全部覆盖时**：状态变为 RESOLVED

```
示例：
  历史债务 TASK-001：gap_targets = [AC-003, AC-004, AC-005]
  TASK-010 的 Claim 覆盖了 AC-003
  → 内部：AC-003 已核销（1/3）
  → 外部：仍是 HISTORICAL
  → TASK-011 的 Claim 覆盖了 AC-004, AC-005
  → 内部：全部核销（3/3）
  → 外部：RESOLVED
```

### 5.2 人类接受：操作，不是自动分类

ACCEPTED 不是系统自动判定的状态，而是人类对 issue 执行的**操作**。

| 操作属性 | 必需/可选 | 说明 |
|---------|---------|------|
| `reason` | 必需 | 接受原因 |
| `accepted_by` | 必需 | 操作人 |
| `accepted_at` | 必需 | 操作时间 |
| `expires_at` | 可选 | 到期后自动回到原状态 |

**ACCEPTED 可以作用于任何非 RESOLVED 状态的 issue**：
- CURRENT_WARNING → ACCEPTED："这个警告我看了，风险可接受"
- HISTORICAL → ACCEPTED："这笔历史债务我确认不修"
- CURRENT_BLOCK → **不能直接 ACCEPTED**。Block 必须先通过其他机制处理（修复、或关联未来 Task 的修复计划），不能通过一键接受绕过。

### 5.3 僵尸 Gap Target：静默清理

如果 HISTORICAL 债务的 gap target 关联的实体已不存在（AC 被删除、模块被移除），该 gap target 从债务中静默移除。

- 这不是一个状态变更——gap target 不再存在，追踪它没有意义
- 移除后如果该债务的 gap targets 变为空 → 整笔债务移除
- 在 Dashboard 上不展示"已过期"标记——静默清理，保持界面干净

### 5.4 跨周期激活：HISTORICAL → CURRENT 的状态迁移

一笔 HISTORICAL 债务，其归属 Task 在后续提交中被激活（`activated` 从 false 变为 true），状态如何变化？

**判定**：域从 INACTIVE 变为 ACTIVE → severity 生效 → 状态可能变为 CURRENT_BLOCK 或 CURRENT_WARNING。

```
示例：
  提交 N：
    TASK-001 的 issue，observed=true，activated=false
    → INACTIVE 域 → HISTORICAL（展示，不阻拦）

  提交 N+1：
    开发者在 commit 中包含了 TASK-001，activated=true
    → ACTIVE 域 → severity 生效
    → severity=BLOCK → CURRENT_BLOCK（阻拦）
    → severity=WARNING → CURRENT_WARNING（告警）
```

**这不是同周期回退**——是新提交的新评估。每次提交是一次独立的评估周期，信号重新计算，状态重新组合。

**业务正确性**：激活 = 开发者在当前提交中显式承诺了这个 Task。一旦承诺，该 Task 的已知问题就是开发者的责任范围——"你说了要做这件事，那这件事上的已知问题你应该知道并处理"。

**与"历史债务不惩罚当前工作"不矛盾**：

| 场景 | activated | 状态 | 逻辑 |
|------|-----------|------|------|
| 我在做 Task B，但碰了 Task A 的文件 | Task A: false | HISTORICAL | 不惩罚——我没承诺 Task A |
| 我显式承诺做 Task A | Task A: true | CURRENT_* | 我承诺了，已知问题是我的责任 |

分界线是**承诺**，不是**文件路径**。

**开发者的处理路径**（激活后面对多个 HISTORICAL → CURRENT 的 issue）：

| 路径 | 操作 | 结果 |
|------|------|------|
| 修复 | 修复 issue，Claim 覆盖 gap target | → RESOLVED |
| 人类接受 | 人类标记 accepted（仅 WARNING 可接受） | → ACCEPTED |
| 拆分 Task | 把不打算本次处理的 issue 拆到独立 Task，当前 Task 缩小承诺范围 | 被拆出的 issue 回到 activated=false → HISTORICAL |

---

## 6. 覆盖即核销

**这是追加开发模式的核心语义。**

```
TASK-001 的 HISTORICAL 债务：AC-003 缺测试证据
TASK-010 的 Claim 覆盖了 AC-003
  ↓
TASK-001 那笔债务的 AC-003 gap target → 已核销
```

**不是**"TASK-001 被重新激活为当前阻塞"。

**不是**"因为 TASK-010 碰了 TASK-001 的文件所以 TASK-001 的债务变成当前问题"。

覆盖即核销。修复遗留问题应该被奖励（自动核销），不应该被惩罚（重新激活）。

---

## 7. 不应该采用的方案：文件路径血缘

```
错误逻辑：
  staged_files ∩ Claim.code_refs
    → "命中了" → 所有关联 issue 变为当前问题
```

**为什么这个方案在业务上不正确：**

1. **文件是共享资源，不是责任边界。** `utils.py` 被 20 个 Task 引用，修改它的一行不意味着为 20 个 Task 的历史问题负责。
2. **惩罚正确的工程行为。** 创建新 Task 修复旧 Task 的遗留问题 → 因为碰了同组文件 → 旧 Task 的债务被激活为当前阻塞。
3. **混淆相关性和责任。** 文件路径回答"有关吗"，不回答"该你管吗"。

---

## 8. 设计原则

| 原则 | 说明 |
|------|------|
| 解释与决策分离 | 解释层描述问题属性，决策层决定门禁行为，两层不混 |
| Task 是责任单位 | 考核的是承诺（Task），不是空间重叠（文件路径） |
| 历史债务不惩罚当前工作 | 继承的问题可见但不阻拦 |
| 覆盖即核销 | 修复遗留问题被奖励（自动核销），不被惩罚（重新激活） |
| 状态最小化 | 5 个状态，内部追踪不暴露为状态 |
| 操作不是状态 | ACCEPTED 是人类操作的结果，不是自动分类的产物 |
| 静默清理优于标记 | 无效 gap target 直接移除，不产生额外状态 |
| Gap Target 只做匹配 | 语义由 Issue Type 携带，验证由 Evidence 携带 |
