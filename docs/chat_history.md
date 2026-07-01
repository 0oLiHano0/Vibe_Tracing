## 用户
我正在做一个人类和ai coding agent结伴编程场景下的项目，以下是我梳理的业务逻辑，请你从架构师和具备丰富ai coding经验的资深开发者角度帮我分析是否合理：
## 核心命题

Vibe Tracing 治理系统回答人类的一个问题：**"这段代码/这个提交，我该不该让它进仓库？"**
Vibe Tracing 治理系统通过在stdout的输出，快速指引agent快速修复：**“这里肯定有问题，你应该主动修复”**

从开发管理角度，答案取决于一个六维评估——六个分类互斥、完备、可行动。

---

## 一、六维业务分类

### 分类总表

| # | 分类 | 业务逻辑 | 决策 | 业务价值 | 时序 |
|---|------|---------|------|---------|------|
| 1 | **链条中断** | req—ac—arch_constraints—task 的链条中，某条引用指向了不存在的目标 | **阻拦** | 设计文档不完整，不能 coding | 1 |
| 2 | **链条错位** | 链条中引用都存在，但逻辑关系矛盾（如 Task 关联的 AC 属于另一个需求） | **阻拦** | 设计有问题，不能 coding | 2 |
| 3 | **孤立任务** | 仅有任务，没有关联任何需求/模块 | **告警** | 临时性任务是合法的，但必须在 Dashboard 中可见 | 1（与 1/2 并行） |
| 4 | **无声明** | req→task 链条完整，task 标记为完成，但没有提交 Claim | **阻拦** | 任务完成但没有提交可核验的请求 | 3 |
| 5 | **任务失败** | req→task 链条完整，有声明，但 VT 独立运行测试未通过 | **阻拦** | 任务结果验证失败 | 4 |
| 6 | **任务不达标** | req→task 链条完整，有声明，测试通过，但覆盖率低、lint 报错等 | **告警** | 任务完成了，但质量不达标 | 5 |

### 时序依赖

六个分类存在逻辑上的时序依赖，构成评估流水线：

```
链条中断 ────→ 链条错位 ────┐
                             ├──→ 无声明 ──→ 任务失败 ──→ 任务不达标
孤立任务（始终可并行评估） ──┘
```

- **链条中断**是最高优先级——如果引用都不存在，后续所有分类无法评估
- **链条错位**需要引用的目标都存在（错位的前提是两个引用都存在）
- **孤立任务**与链条中断/错位并行——临时性任务即使关联完整也可能是孤立的
- **无声明**需要 req→task 关联完整——否则无从判断"没有声明"
- **任务失败**需要声明存在——没有 Claim 无法验证
- **任务不达标**需要测试通过——测试失败时不检查质量（前者是更强的问题）

---

## 二、逐类详细定义

### 1. 链条中断

**业务逻辑**：三份设计文档（prd.json、architecture_constraints.json、task_list.json）之间，一份文件引用了另一份文件中不存在的 ID。

**具体场景**：

| 源文件 | 引用字段 | 目标文件 | 问题 |
|--------|---------|---------|------|
| task_list.json | `related_requirements` | prd.json | 引用了不存在的 req_id |
| task_list.json | `related_acceptance_criteria` | prd.json | 引用了不存在的 ac_id |
| task_list.json | `modules` | architecture_constraints.json | 引用了不存在的 module_id |
| task_list.json | `constraints` | architecture_constraints.json | 引用了不存在的 constraint_id |
| .claims/*.json | `related_task` | task_list.json | 引用了不存在的 task_id |

**判定**：存在至少一条跨文件引用目标不存在 → 阻拦

**决策逻辑**：阻拦。设计文档之间的引用是编码的前提条件。编码没有立足之地。

**人类操作**：
1. 在 Dashboard 上看到虚线标记的引用
2. 判断是"ID 写错"还是"文件未同步"
3. 指示 Agent 修正文件

**业务价值**：`设计文档不完整，不能 coding`

---

### 2. 链条错位

**业务逻辑**：所有跨文件引用都存在（链条不断），但引用关系存在逻辑矛盾——同样的 ID 分散在不同关联链中交叉验证时发现不匹配。

**具体场景**：

```yaml
# 例：需求归属矛盾
task_list.json:
  TASK-001:
    related_requirements: ["REQ-A"]
    related_acceptance_criteria: ["AC-001"]    # AC-001 的父需求是 REQ-B

# Dashboard 上展示的矛盾：
TASK-001
├── 关联需求: REQ-A
└── 关联 AC: AC-001（AC-001 的父需求是 REQ-B）
    → 矛盾：完成 AC-001 不能证明 REQ-A 的覆盖
```

**当前已知的错位类型**：

| 类型 | 矛盾双方 | 当前代码覆盖 |
|------|---------|-------------|
| AC 父需求不匹配 | task→ac 链路 与 task→req 链路 | ✅ `check_invalid_ac_parent` |
| 代码路径与模块不匹配 | task→module 归属 与 claim→code_path 实际路径 | ❌ 未检查 |

**判定**：所有跨文件引用存在，但交叉验证发现逻辑矛盾 → 阻拦

**决策逻辑**：阻拦。任务分配时做了错误的关联，需要判断"这个 Task 到底应该为哪个需求服务"。

**人类操作**：
1. 在 Dashboard 上看到高亮标记的矛盾
2. 判断正确方向（"Task 应属于 REQ-A 还是 REQ-B？"）
3. 指示 Agent 修正关联

**业务价值**：`设计有问题，不能 coding`

---

### 3. 孤立任务

**业务逻辑**：task_list.json 中存在任务，但该任务未关联任何需求、或未关联任何验收标准、或未关联任何架构模块。

**具体场景**：

```yaml
# 完全孤立
TASK-005:
  related_requirements: []
  related_acceptance_criteria: []
  modules: []

# 部分孤立
TASK-006:
  related_requirements: ["REQ-A"]
  related_acceptance_criteria: []   # 有需求但无验收标准
```

**判定**：任务存在但缺乏至少一种关联 → 告警

**决策逻辑**：告警。探索性任务、技术债务清理、研究性工作是合法的。人类需要能看见"体系之外的工作"，但不应该因为看见就阻断。

**严重度分级**（Dashboard 展示用，不在门禁层面区分）：

| 情况 | Dashboard 标记 | 管理含义 |
|------|--------------|---------|
| 无需求、无 AC、无模块 | ⚠️ 强 | 完全游离在规划外 |
| 有需求/有 AC 但无模块 | ⚠️ 弱 | 需求链完整但架构归属不明 |
| 有模块但无需求 | ⚠️ 弱 | 架构有归属但不清楚服务哪个需求 |

**人类操作**：
1. 在 Dashboard 侧边栏看到标记为孤立的任务
2. 判断"这个任务应该归入哪个需求/模块"或"这是独立探索，保留"
3. 指示 Agent 添加关联或标记为"已审查的已知游离工作"
4. 应该补充prd或架构约束，更新文档。

**业务价值**：`临时性任务是合法的，但必须在 Dashboard 中可见`

---

### 4. 无声明

**业务逻辑**：需求到任务的关联完整（req→task 链路通），任务状态标记为 done，但 Agent 没有提交对应的 Claim 文件。

**场景**：

```yaml
TASK-001: status = "done"
# .vibetracing/claims/ 目录下没有 CLAIM-VT-001.json

Dashboard 展示：
REQ-A ──→ TASK-001 (done) ──→ [无 Claim]
```

**与当前代码的差异**：当前代码在检查"无声明"时不区分 task 的状态——`in_progress` 和 `done` 同样报 `no_claim_for_task`。业务逻辑正确的做法是：**只有 `done` 状态的 task 才需要阻断**。`in_progress` 的 task 没有 claim 是正常的——Agent 还在工作中。

| task 状态 | 有 Claim | 无 Claim |
|-----------|---------|---------|
| done | ✅ 正常 | ❌ **阻断** |
| in_progress | ✅ 正常 | ✅ 容忍（进行中不需要声明） |

**判定**：存在 `status = "done"` 的 task → Claim 不存在 → 阻拦

**决策逻辑**：阻拦。Claim 是 Agent 主动请求验证的行为——"我完成了，请检查"。没有 Claim 意味着 Agent 没有提交可核验的请求。人类不能基于"Agent 可能完成了但忘了声明"来决策。

**人类操作**：
1. 在 Dashboard 上看到"TASK-001 已完成但无 Claim"的红色标记
2. 指示 Agent 为刚完成的任务生成 Claim 文件

**业务价值**：`任务完成但没有提交可核验的请求`

---

### 5. 任务失败

**业务逻辑**：需求→任务关联完整，有 Claim 声明，VT 独立执行了测试，测试结果与声明不匹配——存在测试失败。

**场景**：

```yaml
CLAIM-001:
  related_task: "TASK-001"
  test_refs: ["test_foo.py::test_bar"]
  
test_foo.py::test_bar:
  outcome: "failed"    # ← VT 独立执行的测试失败
```

**失败类型**：

| 测试结果 | 含义 |
|---------|------|
| Agent 声明的测试未执行（test_results 中无记录） | 测试未被 VT 执行，无法验证 |
| Agent 声明的测试执行但 failed | 测试失败，功能可能有问题 |
| Agent 声明的测试执行但 非 covered | 测试运行了但结果不符合预期 |

**判定**：存在 Claim → Claim 声明了测试 → 测试存在且 outcome ≠ covered → 阻拦

**决策逻辑**：阻拦。VT 独立执行的测试失败与 Agent 的完成声明矛盾——要么 Agent 的代码有回归，要么 Agent 声明了不存在的测试，要么环境不一致。无论哪种情况，都不能让有问题的代码进入仓库。

**人类操作**：
1. 在 Dashboard 上看到红色失败标记
2. 查看失败测试的详细输出
3. 判断是"代码有问题"还是"测试环境不稳定"或"测试用例本身有问题"
4. 指示 Agent 修复代码、修复测试、或重新执行

**业务价值**：`任务结果验证失败`

---

### 6. 任务不达标

**业务逻辑**：完整链条存在、有声明、测试通过，但质量指标不满足阈值——覆盖率低于标准、lint 有未通过的检查等。

**场景**：

```yaml
CLAIM-001:
  related_task: "TASK-001"
  code_refs: ["src/foo.py"]
  test_refs: ["test_foo.py::test_bar"]

test_foo.py::test_bar: outcome = "covered"                # 测试通过 ✅
coverage_reports["src/foo.py"]:
  percent_covered: 45.2                                   # 覆盖率低于阈值 ❌
  status: "violated"
```

**不达标类型**：

| 类型 | 当前代码覆盖 | 示例 |
|------|------------|------|
| 覆盖率低于阈值 | ✅ 部分（check_coverage_violations 但未与 Claim 关联） | Claim 声称的文件覆盖率不达标 |
| lint 未通过 | ❌ 未覆盖 | ruff/bandit 报错 |
| 其他质量门禁 | ❌ 未覆盖 | 根据项目自定义规则 |

**判定**：测试通过 → 质量指标 ≤ 阈值 → 告警

**决策逻辑**：告警。这是唯一一个"人类可以故意放行"的分类。测试通过说明功能正确，质量不达标说明代码不干净——人类可以在"正确但不干净"上做风险决策。

**为什么不是阻拦**：阻拦意味着"不符合标准就不能进仓库"。但质量阈值通常是一个"推荐值"——低于它更好修一下，但有时团队需要在代码正确但测试覆盖率差一点时先合进主线。这是主观判断，不是客观错误。

**人类操作**：
1. 在 Dashboard 上看到黄色标记
2. 判断"这个代码质量可以接受"（放行）或"必须先修好"（要求修复）
3. 如果放行，可以记录一条 human_decision 供将来追溯

**业务价值**：`任务完成了，但质量不达标`

---

## 三、决策框架

### 阻拦 vs 告警的区分标准

```
阻拦 = 存在客观可验证的错误，不需要人类判断
告警 = 需要主观判断，人类做最终决定
```

| 分类 | 判断依据 | 客观/主观 |
|------|---------|----------|
| 链条中断 | ID 是否存在 | 客观——存在或不存在 |
| 链条错位 | 关联链是否矛盾 | 客观——矛盾或不矛盾 |
| 孤立任务 | 归属是否完整 | 客观——有关联或无关 |
| 无声明 | Claim 文件是否存在 | 客观——存在或不存在 |
| 任务失败 | 测试是否通过 | 客观——通过或不通过 |
| 任务不达标 | 质量是否低于阈值 | 主观——阈值是人为设定的 |

**结论**：阻拦的 4 个分类不需要人类判断——客观错了就是错了。告警的 2 个分类需要人类判断——给了信息，人类做决定。

### 阻断后的修复路径

```
链条中断 ──→ Agent 修改文件 ID                        (5 秒修复)
链条错位 ──→ 人类指示方向 → Agent 修改关联              (人类 30 秒决策)
无声明   ──→ Agent 生成 Claim 文件并提交               (Agent 自动完成)
任务失败 ──→ Agent 修复代码或测试                       (Agent 修复)
任务不达标 ─→ 人类决策：接受债务或要求修复               (人类 10 秒决策)
孤立任务 ──→ 人类决策：归入需求或保留为临时性工作        (人类 10 秒决策)
```

---

## 四、与开发管理目标的映射

| 管理目标 | 对应分类 | 治理手段 |
|---------|---------|---------|
| 设计文档可追溯 | 链条中断、链条错位 | 文档有错 → 阻拦，强迫修复 |
| 任务可追溯 | 孤立任务 | 无归属任务 → Dashboard 可见，人类归入 |
| Agent 提交验证请求 | 无声明 | done 但不提交 Claim → 阻拦 |
| 功能正确性 | 任务失败 | 测试不通过 → 阻拦 |
| 代码质量标准 | 任务不达标 | 质量不达标 → 告警，人类决策是否接受 |
| 人类不被绕过 | **所有分类** | 全部暴露在 Dashboard 上，人类可见即可决 |

---

## 回复
你这套设计整体已经不是“lint / CI 规则系统”，而是一个**面向 agent 的代码治理状态机（Governance State Machine）+ 证据链系统（Evidence Graph）**。从架构师视角看：方向是对的，而且抽象层级其实比大多数 AI coding workflow 工具要高一档。

但我会从三个层面帮你“压一压 + 拉一拉”——看看哪些地方已经很强，哪些地方在真实 agent 环境里会出问题，哪些可以再升级成更通用的系统。

---

# 一、整体评价（先给结论）

## ✔️ 正确的核心设计

你这套系统的本质是：

> **用“可验证的结构约束 + 证据链完整性”替代传统 code review**

这非常关键，因为 AI coding agent 最大的问题不是“写错代码”，而是：

* 任务上下文断裂
* 目标漂移
* 没有可验证完成标准
* “看起来完成了但其实没闭环”

你六分类其实覆盖了三个关键维度：

| 维度                      | 覆盖情况       |
| ----------------------- | ---------- |
| 结构一致性（schema integrity） | 链条中断 / 错位  |
| 任务生命周期完整性               | 无声明 / 任务失败 |
| 质量控制（quality gate）      | 不达标        |
| 工作可见性                   | 孤立任务       |

👉 这是一个非常标准的 **“Agent DevLoop Control Plane”设计**

---

# 二、架构层面最重要的优点

## 1. 你做对了“分层治理”

你隐式做了三层系统：

### L1：结构层（Design Integrity）

* 链条中断
* 链条错位

👉 解决：“这件事能不能做？”

---

### L2：执行层（Execution Truth）

* 无声明
* 任务失败

👉 解决：“有没有真的做完？”

---

### L3：质量层（Quality Acceptance）

* 任务不达标

👉 解决：“做得够不够好？”

---

### L4：组织层（Visibility）

* 孤立任务

👉 解决：“有没有黑箱工作？”

---

✔️ 这个分层非常专业，本质接近：

> Kubernetes + CI/CD + Issue Tracker 的融合体

---

## 2. 你抓住了 AI agent 的“关键失败模式”

你的六类其实对应 agent 的六种典型错误：

| 分类   | agent 行为本质                      |
| ---- | ------------------------------- |
| 链条中断 | 幻觉引用 / context drift            |
| 链条错位 | 错任务绑定 / goal misalignment       |
| 孤立任务 | shadow work / untracked task    |
| 无声明  | 假完成 / missing commit intent     |
| 任务失败 | implementation failure          |
| 不达标  | low-quality but functional code |

👉 这一点非常重要：你不是在做代码规则，而是在做 **agent 行为控制系统**

---

# 三、关键问题（架构风险点）

下面是我认为你系统里“未来一定会踩的坑”。

---

# ⚠️ 问题1：六分类“互斥完备”在真实世界不成立

你现在定义是：

> 六类互斥且完备

但在 agent 场景里，这个假设会破。

## 典型冲突例子：

### case A

* task 没 claim（无声明）
* 同时 test failed（任务失败）

👉 归类冲突：

* 无声明 = 阻拦
* 任务失败 = 阻拦

但优先级不同

---

### case B

* 链条错位 + 无声明 + 不达标同时存在

👉 现实是：
这些不是“六选一”，而是：

> **多维并发故障（multi-failure state）**

---

## ✔️ 建议修正（关键）

不要把它做成 classification，而要改成：

> **Violation Set（违规集合） + Priority Reduction Engine（优先级裁决器）**

也就是：

```text
State = {violations: [V1, V2, V3...]}

not:
State = one_of(6)
```

---

# ⚠️ 问题2：你把“Claim”设计成了单一真相源，但它其实是“中间状态”

你现在：

* done → 必须 claim → 才能验证

问题是：

## AI agent 实际会有三种 completion：

| 类型               | 含义                |
| ---------------- | ----------------- |
| logical done     | agent 认为完成        |
| code merged done | 已 commit          |
| verified done    | claim + test pass |

你现在只认：

> verified done（claim存在）

但现实 agent workflow 会断：

* agent可能已完成但没提交claim
* agent可能提交claim但代码还在本地
* agent可能 claim 和 code 不一致

---

## ✔️ 建议升级

Claim 不要是“存在/不存在”，而是：

```yaml
claim_state:
  created: true
  validated: false
  linked_code_hash: xxx
  verified_by_vt: false
```

👉 Claim 是“状态机”，不是 boolean

---

# ⚠️ 问题3：你现在缺一个“冲突合并层（Conflict Resolution Layer）”

你现在只有：

* detect
* block / warn

但缺：

> **自动修复路径选择器**

例如：

### 链条错位

你现在：

> 人类决定修哪个

但 AI coding agent 系统里应该是：

👉 系统先给：

```
Option A: rebind task → REQ-A
Option B: rebind AC → REQ-B
Option C: split task into TASK-A1 / TASK-A2
```

---

✔️ 建议升级为：

> **Resolution Proposals Engine（RPE）**

---

# ⚠️ 问题4：stdout 反馈机制目前不够结构化

你提到：

> Vibe Tracing 通过 stdout 指引 agent 修复

这个方向很好，但你需要注意：

## stdout 不应该是“人类可读文本”，而是：

> **machine-actionable patch instruction**

否则 agent 会：

* 误读
* 忽略
* 或生成新的歧义

---

## ✔️ 建议格式：

```json
{
  "severity": "blocker",
  "violation": "CHAIN_BREAK",
  "target": "TASK-001",
  "fix_suggestions": [
    {
      "action": "replace_reference",
      "from": "REQ-X",
      "to": "REQ-A"
    }
  ]
}
```

---

# ⚠️ 问题5：你现在缺一个“时间维度（Temporal Consistency）”

你提到了时序，但没有纳入系统约束。

现实 agent 会出现：

* task 已 done
* claim 后生成
* code rollback
* test re-run

👉 导致状态回退

---

## ✔️ 建议增加：

> event-sourced tracing model

每个状态都是 event：

```
TASK_CREATED
TASK_DONE
CLAIM_CREATED
TEST_FAILED
CLAIM_REVISED
```

最终状态 = replay events

---

# 四、你这个系统真正的定位（重要）

你现在不是在做：

❌ CI system
❌ code review tool
❌ project management tool

你实际上在做：

> 🧠 **AI Coding Agent Runtime Governance Kernel**

更精确一点：

> “Git + Jira + CI + Agent behavior firewall 的统一状态机”

---

# 五、建议的升级架构（精简版）

我帮你收敛成一个更工程化版本：

```
                ┌────────────────────────┐
                │  Agent Actions (code)  │
                └──────────┬─────────────┘
                           ↓
        ┌────────────────────────────────────┐
        │   Vibe Tracing Ingestion Layer     │
        │ (parse PRD / Task / Claim / Code)  │
        └────────────────────────────────────┘
                           ↓
        ┌────────────────────────────────────┐
        │  Evidence Graph Builder            │
        │  (REQ ↔ AC ↔ TASK ↔ CODE ↔ CLAIM)  │
        └────────────────────────────────────┘
                           ↓
        ┌────────────────────────────────────┐
        │ Violation Engine (multi-label)     │
        └────────────────────────────────────┘
                           ↓
        ┌────────────────────────────────────┐
        │ Resolution Engine (optional AI)     │
        └────────────────────────────────────┘
                           ↓
        ┌────────────────────────────────────┐
        │ stdout / dashboard / agent signal   │
        └────────────────────────────────────┘
```

---

# 六、总结（核心判断）

## ✔️ 你这个设计的正确性

* 方向：**非常正确（偏 enterprise-grade AI dev infra）**
* 抽象层：**已经超过普通 CI / review system**
* agent 适配性：**高潜力，但需要状态机化**

---

## ⚠️ 最大需要修正的点

1. ❌ 六分类“互斥完备” → 应改为 violation set
2. ❌ Claim boolean → 应改为 lifecycle object
3. ❌ 只有 block/warn → 缺 resolution engine
4. ❌ stdout 文本 → 应结构化 action protocol
5. ❌ 缺 event sourcing → 状态不可追溯

---

# 如果你下一步想做深一点（我建议）

我可以帮你把这个系统直接升级成三种形态之一：

### A. 论文级模型（ICSE / NeurIPS 工程系统方向）

👉 formal model + correctness proof

### B. 可实现架构（Python + Git hook + agent runtime）

👉 可以直接做 MVP

### C. Agent OS kernel（最强版本）

👉 类似“Cursor / Devin runtime governance layer”

---

如果你愿意，我下一步可以帮你做一件更关键的事：

> 把这六分类系统改写成一个**可执行的状态机 + schema + API spec（可直接开发）**

## 用户
把这六分类系统改写成一个可执行的状态机 + schema + API spec（可直接开发）

## 回复
下面我帮你把这套“六分类治理系统”直接升级成一个**可以落地开发的：状态机 + 数据Schema + API Spec（工程可实现版本）**。

我会刻意把它从“设计文档风格”压缩成**可以直接开工写代码的结构**。

---

# 一、系统核心重构（从“分类系统”变成“状态机系统”）

你原来的六分类本质是：

> ❌ 静态分类（classification）
> ✅ 实际应是：**多违规状态驱动的治理状态机（Multi-Violation State Machine）**

---

## ✔️ 核心抽象

### 系统中唯一的核心对象：

```text
WorkUnit（工作单元）
```

它可以是：

* Requirement（REQ）
* Task（TASK）
* Claim（CLAIM）
* CodeChange（COMMIT / PATCH）
* TestRun（VT RESULT）

---

# 二、统一数据模型（Schema）

## 1. Work Graph Schema（核心图结构）

```json
{
  "work_units": {
    "REQ-001": {
      "type": "requirement",
      "status": "active",
      "links": {
        "tasks": ["TASK-001"]
      }
    },

    "TASK-001": {
      "type": "task",
      "status": "done",
      "links": {
        "requirements": ["REQ-001"],
        "acceptance_criteria": ["AC-001"],
        "modules": ["MOD-001"],
        "claim": "CLAIM-001"
      }
    },

    "CLAIM-001": {
      "type": "claim",
      "status": "submitted",
      "task_id": "TASK-001",
      "code_refs": ["src/foo.py"],
      "test_refs": ["test_foo.py::test_bar"]
    }
  }
}
```

---

## 2. Claim Schema（关键升级点）

```json
{
  "claim_id": "CLAIM-001",
  "task_id": "TASK-001",

  "state": {
    "created_at": "...",
    "verified": false,
    "vt_run_id": "VT-001"
  },

  "code_refs": [
    {
      "path": "src/foo.py",
      "hash": "abc123"
    }
  ],

  "test_refs": [
    {
      "id": "test_foo.py::test_bar",
      "expected": "covered"
    }
  ]
}
```

---

## 3. VT Test Result Schema

```json
{
  "vt_run_id": "VT-001",
  "claim_id": "CLAIM-001",

  "results": [
    {
      "test_id": "test_foo.py::test_bar",
      "status": "failed",
      "error": "AssertionError"
    }
  ],

  "coverage": {
    "src/foo.py": 45.2
  },

  "lint": {
    "ruff": "pass",
    "bandit": "fail"
  }
}
```

---

# 三、状态机设计（核心）

## 1. WorkUnit State Machine

```text
        ┌──────────────┐
        │  CREATED      │
        └──────┬───────┘
               ↓
        ┌──────────────┐
        │  LINKED       │ ← 链条中断 / 错位检查在这里
        └──────┬───────┘
               ↓
        ┌──────────────┐
        │  IN_PROGRESS  │
        └──────┬───────┘
               ↓
        ┌──────────────┐
        │  DONE         │ ← 无声明检查点
        └──────┬───────┘
               ↓
        ┌──────────────┐
        │  CLAIMED      │
        └──────┬───────┘
               ↓
        ┌──────────────┐
        │  VERIFIED     │ ← VT 成功
        └──────────────┘
```

---

# 四、六分类 → 状态机规则（核心映射）

你原来的六类，现在变成：

---

## 1. 链条中断（CHAIN_BREAK）

### 触发规则：

```python
if any(link.target_id not exists):
    violation.add("CHAIN_BREAK")
```

### 状态影响：

```text
BLOCK transition: CREATED → LINKED
```

---

## 2. 链条错位（CHAIN_MISMATCH）

```python
if relation_inconsistent(graph):
    violation.add("CHAIN_MISMATCH")
```

---

## 3. 孤立任务（ORPHAN_TASK）

```python
if task.has_no_links():
    violation.add("ORPHAN_TASK")
```

---

## 4. 无声明（NO_CLAIM）

```python
if task.status == "done" and claim == null:
    violation.add("NO_CLAIM")
```

---

## 5. 任务失败（TASK_FAILED）

```python
if vt_result.any_failed():
    violation.add("TASK_FAILED")
```

---

## 6. 任务不达标（QUALITY_DEGRADED）

```python
if coverage < threshold or lint_fail:
    violation.add("QUALITY_DEGRADED")
```

---

# 五、统一违规模型（关键升级）

你不再用：

> ❌ 六选一分类

而是：

## ✔️ Multi-Violation Model

```json
{
  "task_id": "TASK-001",
  "violations": [
    {
      "type": "NO_CLAIM",
      "severity": "blocker"
    },
    {
      "type": "QUALITY_DEGRADED",
      "severity": "warning"
    }
  ]
}
```

---

# 六、Violation Engine（核心计算器）

```python
class ViolationEngine:

    def evaluate(self, task, graph, vt_result):
        violations = []

        if self.chain_broken(task, graph):
            violations.append("CHAIN_BREAK")

        if self.chain_mismatch(task, graph):
            violations.append("CHAIN_MISMATCH")

        if self.is_orphan(task):
            violations.append("ORPHAN_TASK")

        if task.status == "done" and not task.claim:
            violations.append("NO_CLAIM")

        if vt_result.failed():
            violations.append("TASK_FAILED")

        if self.quality_below_threshold(task, vt_result):
            violations.append("QUALITY_DEGRADED")

        return violations
```

---

# 七、决策层（Block vs Warn）

## Rule Engine

```python
BLOCKING_RULES = {
    "CHAIN_BREAK",
    "CHAIN_MISMATCH",
    "NO_CLAIM",
    "TASK_FAILED"
}

WARNING_RULES = {
    "ORPHAN_TASK",
    "QUALITY_DEGRADED"
}
```

---

## Decision Output

```json
{
  "task_id": "TASK-001",

  "decision": "BLOCK",

  "blocking_violations": [
    "NO_CLAIM"
  ],

  "warning_violations": [
    "QUALITY_DEGRADED"
  ]
}
```

---

# 八、API SPEC（可直接开发）

## 1. ingestion API（写入系统）

### POST /ingest/work-unit

```json
{
  "type": "task",
  "id": "TASK-001",
  "links": {
    "requirements": ["REQ-001"],
    "acceptance_criteria": ["AC-001"]
  },
  "status": "done"
}
```

---

## 2. claim API

### POST /claim

```json
{
  "claim_id": "CLAIM-001",
  "task_id": "TASK-001",
  "code_refs": ["src/foo.py"],
  "test_refs": ["test_foo.py::test_bar"]
}
```

---

## 3. vt run API

### POST /vt/run

```json
{
  "claim_id": "CLAIM-001"
}
```

返回：

```json
{
  "vt_run_id": "VT-001",
  "status": "completed"
}
```

---

## 4. evaluate API（核心）

### GET /evaluate/task/{task_id}

返回：

```json
{
  "task_id": "TASK-001",

  "state": "BLOCKED",

  "violations": [
    {
      "type": "NO_CLAIM",
      "severity": "blocker"
    }
  ],

  "actions": [
    {
      "type": "CREATE_CLAIM",
      "auto": true
    }
  ]
}
```

---

## 5. agent stdout protocol（关键）

👉 替代“纯文本stdout”

```json
{
  "signal": "VIOLATION_DETECTED",
  "task_id": "TASK-001",
  "severity": "blocker",

  "violation": "NO_CLAIM",

  "recommended_action": {
    "type": "CREATE_CLAIM",
    "payload": {
      "task_id": "TASK-001"
    }
  }
}
```

---

# 九、系统运行主循环（Agent Loop）

```text
Agent writes code
   ↓
commit / update task
   ↓
ingest
   ↓
violation engine runs
   ↓
decision engine
   ↓
stdout signal → agent
   ↓
agent fix loop
```

---

# 十、你这套系统的“本质升级”

你原本是：

> ❌ 六分类治理系统

现在变成：

> ✔️ **AI Coding Agent Runtime Governance Kernel**

更精确定义：

```text
A multi-violation, event-driven, graph-based execution governance system for AI coding agents.
```

---

# 十一、我帮你点一下最关键的工程建议（非常重要）

如果你真的要做 MVP：

## 🔥 最优先实现顺序

### Phase 1（必须先做）

* Work Graph Schema
* CHAIN_BREAK
* NO_CLAIM
* evaluate API

---

### Phase 2

* TASK_FAILED (VT integration)
* QUALITY_DEGRADED

---

### Phase 3（增强）

* CHAIN_MISMATCH
* ORPHAN_TASK
* stdout protocol

---

### Phase 4（高级）

* auto-resolution engine
* agent self-healing loop

---

# 如果你下一步想继续推进，我可以帮你做更狠的一步：

👉 把这个系统直接升级成：

### “Agent OS Runtime（类似 Kubernetes for coding agents）”

包括：

* scheduler
* state reconciliation loop
* distributed agent execution
* replayable event log
* deterministic rebuild

这个就已经是偏“系统级基础设施”了。
