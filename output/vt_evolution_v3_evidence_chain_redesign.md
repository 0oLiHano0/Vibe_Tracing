# VT 进化 v3：证据链重设计

## 一、问题背景

VT 的门禁（Gate）持续 BLOCKED。159 个 HIGH 风险全部是"Claim 声明完成但无 VT 执行的工具验证证据"。根因不是代码质量问题，而是 **Claim 的验证生态从未真正运转过**：

- Agent 创建 Claim（声明"我做完了"）
- Claim 引用 code_refs 和 test_refs
- 但 VT 从未用这些 test_refs 实际跑过 pytest
- Claim 的 status 和 content_hash 变成需要维护的"状态"，而非"指针"
- hash 过期 → 重新验证 → 更多 hash → 更多过期 → 恶性循环

**本轮进化目标**：从第一性原则重新设计证据链，让 Gate 能真正判定，让 Claim 回归其本质价值。

---

## 二、第一性原则分析

### 2.1 证据链需要满足什么条件？

VT 的核心使命是让人类（无开发经验）能判断 Agent 的交付是否可信。可信的证据必须满足：

| 条件 | 含义 |
|---|---|
| **独立性** | 验证者不能是声明者（Agent 不能自证完成） |
| **可重现** | 任何人重跑都能得到相同结果 |
| **可追溯** | 证据必须关联到需求（测试覆盖了哪条 AC） |
| **时效性** | 证据必须是当前的，不是过期的 |

### 2.2 当前设计：Claim + Evidence 两层

```
Agent 写 Claim（声明）
  → Claim 引用 code_refs + test_refs
  → VT 验证 Claim 的 hash 是否匹配
  → VT 验证 Claim 是否有 "工具验证证据"
  → Gate 检查：Claim 的 status + evidence 支撑
```

**问题**：Claim 不仅是"指针"，还变成了"状态"——有 hash、有 status、有 content_hash。代码改了 → hash 过期 → Claim 失效 → 需要重新验证。这导致 Claim 的维护成本极高，且从未真正运转。

### 2.3 Claim 的真正价值是什么？

分析 Claim 在整个系统中的角色：

| 角色 | Claim 的价值 | 是否不可替代 |
|---|---|---|
| **门禁判定** | Gate 检查 Claim 的 status 和 evidence | **否** — Gate 可以直接看工具结果 |
| **Dashboard 展示** | 展示"Agent 做了什么" | **是** — 人类需要看到 Agent 的工作记录 |
| **VT 验证入口** | Claim 的 test_refs 告诉 VT 跑哪些测试 | **是** — VT 需要知道验证范围 |
| **审计轨迹** | 记录 Agent 的历史工作 | **是** — 但可以归档 |

**核心洞察**：Claim 的价值是"指针"（告诉 VT 跑什么测试）和"工作日志"（告诉人类 Agent 做了什么），不是"状态"（hash、status、content_hash）。

### 2.4 证据链的本质

去掉 Claim 的"状态"角色后，证据链变成：

```
需求（AC）
  ↑
  │ 关联
  │
Task（任务）──→ Claim（指针：test_refs）──→ VT 跑 pytest
  │                                              │
  │                                              ↓
  │                                     evidence_index（工具结果）
  │                                              │
  └──────────────────────────────────────────────┘
                         ↓
                   Gate 判定（只看 evidence_index）
```

**Gate 的判定依据**：
1. 每个 MUST AC 是否有通过的测试覆盖？
2. 覆盖率是否达标？
3. 架构约束是否合规？
4. 有没有 MUST 级未处理风险？

**不需要检查 Claim 的 hash、status 或 content_hash。**

---

## 三、新设计

### 3.1 Claim 的重新定位

| 旧定位 | 新定位 |
|---|---|
| 门禁判定的必要输入 | 门禁不看 Claim |
| 有 hash、status、content_hash | 只有 code_refs、test_refs、related_task |
| 代码改了 → Claim 失效 → 需要更新 | 代码改了 → VT 重新跑测试 → Claim 不变 |
| 永久累积在一个文件 | 按提交生命周期管理 |

**Claim 的新定义**：Agent 的工作指针 + 工作日志。告诉 VT "去验证这些测试"，告诉人类"Agent 做了这些事"。

### 3.2 Claim 生命周期

```
.vibetracing/
  claims/
    current.json          ← 当前待提交的 Claim（Agent 写入）
    archive/
      commit-abc123.json  ← 归档的历史 Claim
      commit-def456.json
```

**生命周期**：

```
Agent 工作中：
  → 写 Claim 到 claims/current.json
  → 每个 Claim 包含：claim_id, related_task, code_refs, test_refs, notes

git commit 时：
  → Gate 检查 current.json 是否覆盖了 staged 业务文件
  → VT 用 current.json 的 test_refs 跑 pytest
  → 测试结果写入 evidence_index.json
  → commit 成功后：
    → current.json 归档到 archive/commit-{hash}.json
    → current.json 清空

历史查询：
  → Dashboard 从 archive/ 读取历史 Claim
  → evidence_index.json 是永久的事实记录
```

### 3.3 Claim Schema 简化

旧 schema（需要维护的状态）：
```json
{
  "claim_id": "CLAIM-VT-067",
  "related_task": "TASK-VT-065",
  "claimed_status": "covered",
  "evidence_refs": [...],
  "code_refs": [...],
  "test_refs": [...],
  "timestamp": "...",
  "content_hash": "...",      // 删除
  "notes": "..."
}
```

新 schema（纯指针）：
```json
{
  "claim_id": "CLAIM-VT-067",
  "related_task": "TASK-VT-065",
  "code_refs": [
    "src/vibe_tracing/decision_server.py",
    "src/vibe_tracing/merge_gate_engine.py"
  ],
  "test_refs": [
    "tests/test_decision_server.py",
    "tests/test_merge_gate_engine.py"
  ],
  "notes": "决策平台 v1：Decision Server + Gate Engine 人类决策集成"
}
```

**删除的字段**：
- `claimed_status` — Gate 不看 Claim 状态
- `evidence_refs` — evidence 由 VT 工具执行生成，不依赖 Claim 声明
- `content_hash` — 不做 hash 比较
- `timestamp` — Claim 的时效性由归档机制管理，不需要时间戳

### 3.4 门禁逻辑简化

**Gate 检查项**（按优先级）：

| 检查项 | 判定依据 | 阻断级别 |
|---|---|---|
| 1. Claim 存在性 | staged 业务文件 ⊆ current.json 的 code_refs ∪ test_refs | blocked |
| 2. 测试通过性 | evidence_index 中 pytest 结果 | blocked |
| 3. AC 覆盖性 | 每个 MUST AC 有关联 Task，Task 有关联 Claim，Claim 的 test_refs 中有通过的测试 | blocked |
| 4. 覆盖率 | evidence_index 中业务代码（src/）coverage 数据 >= 80%，测试代码（tests/）不纳入计算 | blocked |
| 5. 架构合规 | architecture_compliance_checker 结果 | blocked |
| 6. MUST 级风险 | risk_advisor 结果 | blocked |
| 7. 人类决策 | human_decisions.json 中的 accept_risk / mark_complete | 解除对应阻断 |

**Gate 不检查**：
- ~~Claim 的 hash~~
- ~~Claim 的 status~~
- ~~Claim 的 content_hash~~
- ~~Claim 是否有 "VT 执行的工具验证证据"~~
- ~~Claim 的 timestamp 是否过期~~

### 3.5 AC 覆盖的推导链

Gate 如何判断"每个 MUST AC 是否有通过的测试覆盖"？

**关键约束**：task_list.json 在设计阶段创建，此时还没有代码，因此 Task 不可能包含 code_refs 或 test_refs。Task 只能声明 `related_acceptance_criteria`（关联哪些 AC）。代码和测试的映射由 Claim 在编码阶段补充。

**推导链**：

```
AC（PRD 中定义）
  ↑
  │ related_acceptance_criteria
  │
Task（task_list.json，设计阶段创建，关联 AC）
  ↑
  │ related_task
  │
Claim（current.json，编码阶段创建，关联 Task，声明 test_refs）
  ↑
  │ test_refs
  │
测试文件（VT 跑 pytest 得到通过/失败）
```

**推导步骤**：
1. 从 task_list.json 获取每个 MUST AC 关联的 Task（通过 `related_acceptance_criteria`）
2. 从 current.json 获取每个 Task 关联的 Claim（通过 `related_task`）
3. 从 Claim 获取 test_refs
4. 从 evidence_index 获取 test_refs 的 pytest 结果
5. 如果 pytest 通过 → AC 被覆盖
6. 如果 pytest 失败或无 Claim 关联该 Task → AC 未被覆盖

**为什么不把 code_refs/test_refs 写回 task_list.json？**
- Task 在设计阶段创建，代码不存在，无法引用
- 写回并重新锁定基线增加复杂度，且破坏"设计阶段冻结、开发阶段验证"的职责边界
- Claim 已经承担了"代码和测试的映射"角色，不需要 Task 重复

**覆盖率计算排除测试代码**：
- 覆盖率只计算 `src/vibe_tracing/**/*.py`（业务代码）
- `tests/**/*.py`（测试代码）不纳入覆盖率计算
- 测试代码的质量由测试本身的结果（通过/失败）验证，不由覆盖率验证

**Agent 可靠性分析**：

这个推导链依赖 Agent 的两个声明：
- Claim → related_task（Agent 声明"这个 Claim 关联这个 Task"）
- Task → AC（在 task_list.json 中，人类或 Agent 声明"这个 Task 覆盖这些 AC"）

**VT 能验证的**：
- test_refs 文件存在 ✓
- pytest 通过/失败 ✓
- 业务代码覆盖率 ✓（排除测试代码）
- AC 是否被任何 Task 关联 ✓

**VT 不能验证的**：
- Claim 关联的 Task 是否正确（Agent 可能关联错误的 Task）
- 测试是否真的覆盖了 AC 描述的场景（VT 不理解测试语义）

**缓解**：Dashboard 展示完整的推导链，人类审查"AC → Task → Claim → 测试 → 结果"是否合理。

### 3.6 Dashboard 全生命周期链条

Dashboard 仍然展示完整链条，每层数据来源更清晰：

```
需求（PRD）           ← prd.md
  ↓
架构约束              ← architecture_constraints.json
  ↓
任务                  ← task_list.json（关联 AC）
  ↓
Agent Claim           ← claims/current.json + archive/（工作日志）
  ↓
代码变更              ← evidence_index（git diff 元数据）
  ↓
测试结果              ← evidence_index（VT 跑 pytest 的结果）
  ↓
AC 覆盖状态           ← Gate 推导（Task → Claim → test → 结果）
  ↓
门禁结论              ← Gate 规则引擎
```

**人类看到的**：
- 每个 AC 的覆盖状态（有测试通过 / 无测试 / 测试失败）
- Agent 做了什么（Claim 工作日志）
- 测试结果详情（pytest 输出摘要）
- 门禁结论和原因

**人类不需要看到的**：
- Claim 的 hash、status、content_hash（内部实现细节）
- evidence_refs 列表（已被 evidence_index 替代）

---

## 四、Agent 行为可靠性分析

### 4.1 Agent 行为链条

| 环节 | Agent 行为 | VT 能否验证 | 风险等级 |
|---|---|---|---|
| 写 PRD | 定义需求和 AC | 不能（业务语义） | 低（人类审查） |
| 拆 Task | 关联 Task ↔ AC（设计阶段，无代码引用） | 部分能（检测无 Task 的 AC） | 中 |
| 写代码 | 实现功能 | 能（测试通过/失败） | 中 |
| 写测试 | 编写测试文件（不纳入覆盖率计算） | 部分能（测试结果，但不理解语义） | 高 |
| 写 Claim | 声明 code_refs、test_refs、related_task | 能（文件存在性 + Task 存在性） | 低 |

**注意**：Task 在设计阶段创建，不包含 code_refs/test_refs。代码和测试的映射由 Claim 在编码阶段补充。这是职责分离——设计阶段定义"做什么"，编码阶段定义"怎么做"。

### 4.2 最大风险点

**风险**：Agent 写了一个测试 `test_foo.py`，测试通过了，Claim 声称它覆盖了 AC-VT-001-01。但实际上测试只测了 happy path，没有覆盖 AC 描述的异常场景。

**VT 无法检测这个问题**：VT 不理解测试的语义，只能验证测试通过/失败。

**缓解方案**：
1. Dashboard 展示测试函数名和 docstring，人类快速判断测试是否合理
2. 覆盖率作为间接指标：代码覆盖率低 → 测试可能不充分
3. 人类审查 AC → Task → Claim → 测试 的推导链

**这是所有不依赖 AI 语义分析的方案的固有局限**，不是本设计的缺陷。

### 4.3 Claim 存在性门禁的价值

Gate 检查"Agent 是否提交了 Claim"（staged 文件 ⊆ claim 的 code_refs ∪ test_refs），确保：

- Agent 不能跳过声明环节
- Agent 必须明确"我改了什么、我测试了什么"
- 如果 Agent 改了代码但没提交 Claim → 门禁阻断

**这个检查不验证 Claim 的质量，只验证 Claim 的存在。** 质量由工具验证（pytest）判定。

---

## 五、与当前设计的对比

| 维度 | 当前设计 | 新设计 |
|---|---|---|
| Claim 的角色 | 门禁判定的必要输入 | 指针 + 工作日志 |
| Claim 的状态 | hash、status、content_hash | 无状态，纯指针 |
| Claim 文件 | 永久累积的巨型文件 | current.json + archive/ |
| Gate 判定依据 | Claim 的 status + evidence | 工具结果（evidence_index） |
| hash 过期问题 | 存在，需要持续维护 | 不存在，不比较 hash |
| 159 个 low_confidence | 存在，阻断门禁 | 不存在，Gate 不检查 Claim status |
| Agent 行为验证 | Claim 的 content_hash | 文件存在性 + pytest |
| AC 覆盖判定 | Claim 的 test_refs + evidence | Task → Claim → test 推导链 |
| 人类信任 | Claim + Evidence 并列 | Claim（工作日志）+ Evidence（工具结果）并列 |

---

## 六、风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| Claim schema 变更影响现有数据 | 高 | 提供迁移脚本，将旧 claim_fingerprints.json 和 agent_claims.json 转换为新格式 |
| Gate 逻辑重写可能引入回归 | 高 | 保留旧 Gate 逻辑作为 fallback，新逻辑逐步替换 |
| archive/ 目录文件数增长 | 低 | 文件很小（每个 commit 1-5 个 Claim），不是问题 |
| 测试↔AC 映射的准确性 | 中 | Dashboard 展示完整推导链，人类审查 |
| Agent 跳过 Claim 的检测 | 低 | 集合包含检查，简单可靠 |

---

## 七、执行计划

### Phase 0：前置清理（1 个任务）

**TASK-V3-000**：幽灵引用清理
- 删除 `evidence_index_builder.py` 中读取 `coverage_baseline.json` 的 fallback 代码（5 处）
- 删除 `tool_evidence_adapter.py` 中读取 `coverage_baseline.json` 的 fallback 代码和 docstring（6 处）
- 删除 `cli.py` 中 `baseline_path` 变量和 `coverage_baseline` 读取逻辑（3 处）
- 删除 `claim_evidence_analyzer.py` 中读取 `claim_fingerprints.json` 的 fallback 代码和注释（4 处）
- 验证：`grep -rn 'coverage_baseline.json\|claim_fingerprints.json' src/` 结果为 0

### Phase 1：Claim 生命周期重构（3 个任务）

**TASK-V3-001**：Claim Schema 简化
- 修改 `schemas/agent_claims.schema.json`：删除 claimed_status、evidence_refs、content_hash、timestamp
- 修改 `src/vibe_tracing/claim_loader.py`：适配新 schema
- 迁移现有 agent_claims.json：删除废弃字段

**TASK-V3-002**：Claim 目录结构改造
- 创建 `.vibetracing/claims/current.json`（空）
- 创建 `.vibetracing/claims/archive/`（空）
- 迁移现有 agent_claims.json 的内容到 current.json
- 修改 cli.py：从 `claims/current.json` 加载 Claim

**TASK-V3-003**：Claim 归档机制
- 在 cli.py 的 commit 流程中：commit 成功后，将 current.json 归档到 archive/commit-{hash}.json
- 清空 current.json
- 修改 pre-commit hook：归档逻辑

### Phase 2：Gate 逻辑重写（3 个任务）

**TASK-V3-004**：Gate Claim 存在性检查
- 在 merge_gate_engine.py 中新增 `check_claim_exists(staged_files, claims)` 函数
- 检查 staged 业务文件 ⊆ claims 的 code_refs ∪ test_refs
- 未覆盖的文件 → blocked

**TASK-V3-005**：Gate AC 覆盖推导
- 在 merge_gate_engine.py 中实现推导链：AC → Task → Claim → test_refs → pytest 结果
- 每个 MUST AC 必须有通过的测试覆盖
- 未覆盖的 AC → blocked

**TASK-V3-006**：Gate 移除 Claim status 检查
- 删除 Gate 中检查 Claim status（covered/low_confidence）的逻辑
- 删除 Gate 中检查 Claim hash/content_hash 的逻辑
- Gate 的判定只基于 evidence_index 中的工具结果

### Phase 3：VT 工具执行集成（2 个任务）

**TASK-V3-007**：VT 自动跑 pytest
- 在 cli.py 的 analyze 流程中：读取 current.json 的 test_refs
- 对每个 test_ref 运行 pytest
- 将结果写入 evidence_index.json

**TASK-V3-008**：evidence_index 新增测试结果
- evidence_index.json 新增 `test_results` 字段
- 存储每个测试文件的通过/失败状态、执行时间、错误信息

### Phase 4：清理与验证（2 个任务）

**TASK-V3-009**：删除 Claim 状态相关代码
- 删除 claim_evidence_analyzer.py 中的 hash 比较逻辑
- 删除 claim_fingerprints.json 相关代码（已在进化 v2 中删除）
- 删除 Gate 中的 Claim status 判定逻辑

**TASK-V3-010**：端到端验证
- 在 VT 项目自身上运行完整的 commit 流程
- 验证：Claim 存在性检查 → pytest 执行 → evidence_index 更新 → Gate 判定
- 验证：归档机制正常工作
- 验证：Dashboard 正确展示 Claim 工作日志 + 工具结果

---

## 八、总结

本轮进化的核心转变：

**Claim 从"需要维护状态的验证对象"变为"无状态的指针和工作日志"。**

- Gate 不再检查 Claim 的 hash、status、content_hash
- Gate 只检查：Claim 存在性 + 工具结果（pytest 通过/覆盖率/架构合规）
- Claim 按提交生命周期管理：current.json（当前）+ archive/（历史）
- evidence_index.json 是永久的事实记录
- Dashboard 同时展示 Claim（Agent 做了什么）和 Evidence（工具验证了什么），人类看到完整故事链

**预期效果**：
- 159 个 low_confidence 风险消失（Gate 不再检查 Claim status）
- hash 过期问题消失（不比较 hash）
- 门禁判定更快更简单（只看工具结果）
- Agent 行为更清晰（Claim 是声明，工具结果是事实）
- 覆盖率只计算业务代码，测试代码不纳入（测试质量由测试结果验证）

**总任务数**：11 个（Phase 0: 1 + Phase 1: 3 + Phase 2: 3 + Phase 3: 2 + Phase 4: 2）
