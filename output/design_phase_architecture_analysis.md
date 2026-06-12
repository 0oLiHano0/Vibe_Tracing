# 设计阶段架构分析：finalize 前逻辑审查（v2 更新版）

基于第一性原则和剃刀原则，对 `vt finalize` 前的逻辑链路进行审查，识别代码问题并给出架构决策。
**v2 更新**：基于 5 路线下 agent 探查结果修正遗漏、补充新发现。

---

## 一、问题清单一（修正版）

### 问题 1：`vt accept` 破坏已锁定的基线 ← CRITICAL

`accept.py` 直接修改 `docs/architecture_constraints.json`（写入 `accepted_by` 和 `accepted_at` 字段），导致 SHA-256 指纹变化。

**实际代码验证**（`accept.py:69-73`）：
```python
rule["accepted_by"] = accepted_by
rule["accepted_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
# 随后 json.dump 写回原文件
```

每次 accept 都导致 constraints 文件内容变化 → SHA-256 变化 → `config.json` 中的 `architecture_constraints_hash` 失效 → Gate 1 拦截 → 用户困惑。

**违反约束**：
- **STORE-VT-004**：系统不得覆写原始 PRD、架构约束、任务清单、Agent Claim 或工具输出
- **AC-VT-009-14**：PRD 哈希保护与漂移检测（同样的保护机制适用于 constraints_hash）

### 问题 2：`vt accept` 不校验 `verification_method` ← MINOR

schema 中规则有 `verification_method: "machine" | "manual"` 字段，但 `accept.py` 不检查该值。

**实际代码验证**（`accept.py:49-77`）：任何 rule_id 都接受，包括 machine 类型规则。
**Compliance checker 已有约定**（`architecture_compliance_checker.py:731`）：
```python
verification = rule.get("verification_method", "machine")
if verification == "manual":
    # ...处理 manual 规则
```
accept.py 与 compliance checker 不一致。

### 问题 3：change log 检查形同虚设 ← MODERATE

`_validate_constraints_change()` 仅调用 `git_has_uncommitted_changes()` 检查文件是否被修改过，不校验内容。

**实际代码验证**（`finalize.py:64-72`）：只检查 `architecture_change_log.md` 是否有任何未提交修改。内容质量、格式、与 diff 的对应关系均不校验。

### 问题 4：PRD 漂移与约束漂移处理不对称 ← CORRECT（无需改动）

| 漂移类型 | finalize 时 | analyze 时 |
|---------|------------|-----------|
| constraints 被改 | 要求 change log 更新，否则拦截 | **BLOCK** |
| PRD 被改 | 无 change log 要求 | **WARNING only** |

**通过代码验证确认**：PRD 内容变更不影响结构映射（`_collect_related_reqs()` 只检查 REQ ID 存在性，不关心 AC 描述文字变化）。映射校验在 finalize（`finalize.py:120-128`）和 analyze（`prd_arch_validator.py`）中均无条件执行，覆盖所有结构性破坏。Gate 1b 的 WARNING 足够。

---

## 二、问题清单二（Agent 探查新增发现）

### 问题 5：`accepted_rule` 决策链路断裂 ← MODERATE

`accepted_rule` 的端到端链路在 MergeGateEngine 处断裂：

```
compliance checker (生成 accepted_rules)
  → Dashboard (渲染为决策卡片)
  → 人类操作（"仍然有效"/"不再适用"）
  → decision_server.py POST → human_decisions.json ✓
  → MergeGateEngine.evaluate()
    → 只识别 action=="accept_risk" 或 action=="mark_complete"
    → action=="reconfirm" 或 action=="reject" 被静默忽略 ✗
```

**实际代码验证**（`merge_gate_engine.py:594-600`）：
```python
for d in decisions_list:
    action = d.get("action", "")
    target_id = d.get("targetId", "")
    if action == "accept_risk" and target_id:
        accepted_risk_target_ids.add(target_id)
    elif action == "mark_complete" and target_id:
        resolved_gap_target_ids.add(target_id)
```

**影响**：
- 人类在 Dashboard 上对 `accepted_rule` 做的"仍然有效"/"不再适用"决策被记录但不产生任何效果
- 门禁判定无法感知人类已重新确认或否定某项架构规则
- 违反 **AC-VT-008-03**：门禁结论必须包含决策依据（但 current decisions 被忽略）

### 问题 6：`human_decisions` 数据流不完整 ← MODERATE

`ArchitectureComplianceChecker.check()` 没有 `human_decisions` 参数。当前 compliance checker 从 `architecture_constraints.json` 中直接读取 `accepted_by` 字段（`architecture_compliance_checker.py:734-744`），而不是从 `human_decisions.json`。

**实际数据流**：

```
human_decisions.json
  → 只在 pipeline.py:186 _run_gate_evaluation() 时加载
  → 只传递给 MergeGateEngine.evaluate()
  → 不传递给 ArchitectureComplianceChecker
```

这意味着：
- 如果迁移 accept 到 human_decisions.json，compliance checker 无法读取
- compliance checker 生成的 `accepted_rules` 是基于 constraints.json 中的 embedded 字段，不是基于 human_decisions.json 中的决策记录
- 两套数据不互通，存在 split-brain 风险

### 问题 7：`proposals` 数组始终为空 ← MODERATE

Dashboard 的 Bootstrap tab 有完整的 proposals 表格（期望 `proposal_id, author, rationale, proposed_changes, status, human_approval`），但 `check_governance()` 始终返回 `proposals: []`。

**实际代码验证**：
- `architecture_change_proposal.py:208-216` 的 `_empty_result()` 返回 `{"proposals": [], ...}`
- `check_governance()` 在所有路径末尾都调用 `_empty_result()`（第 332 行）
- `_find_differences()` 已产出结构化 diff（`{path, action, value, rule_id}`），但从未转换为 proposals 格式
- Dashboard 模板有完整的前端渲染代码（`dashboard.template.html:3065-3105`），数据通过 `#prop-data-json` 注入

### 问题 8：缺少 `human_decisions.schema.json` ← MINOR

`human_decisions.json` 的格式仅由 `decision_server.py` 隐式定义（`architecture_compliance_checker.py` 读取），无 JSON Schema 校验。

**实际影响**：
- 结构变更时无 schema 作为契约
- 与项目中其他 JSON 文件的 schema 校验机制不一致

---

## 三、PRD 业务场景评估

### 3.1 评估方法

以 PRD 中的 **核心业务场景** 和 **功能需求** 为判断依据，评估每个架构变更是否合理、优先级和风险。PRD 的场景和设计目标为正确基准，实现细节的偏移以代码实际状况为准。

### 3.2 场景映射

| PRD 章节 | 关联架构变更 | 评估结论 |
|---------|------------|---------|
| SCENE-VT-006：查看合并门禁结论 | 变更 1(accept→human_decisions) | **必须** - 基线完整性直接影响门禁可信度 |
| SCENE-VT-008：项目配置定型 | 变更 1(accept→human_decisions) | **必须** - 定型后的 config 不应被 accept 静默破坏 |
| SCENE-VT-007：查看风险与处理建议 | 变更 3(结构化 change log) | **需要** - 变更历史直接影响风险追溯 |
| AC-VT-009-14：PRD 哈希保护 | 变更 1 | **必须** - 哈希保护机制的一致性要求 |
| AC-VT-009-06：自治理变更生命周期 | 变更 1、变更 3 | **必须** - accept 绕过生命周期契约 |
| AC-VT-006-01：Dashboard 展示治理维度 | 变更 3 | **需要** - proposals 是 Dashboard 定义的一级维度 |
| AC-VT-008-03：门禁结论说明依据 | 变更 1、问题 5 修复 | **必须** - 人类决策应进入门禁依据 |
| AC-VT-001-03：无证据结论不得显示为完成 | 变更 2(verification_method) | **应当** - machine 规则需程序证据 |

### 3.3 变更合理性评估

#### 变更 1：`vt accept` 迁移到 `human_decisions.json`

**PRD 一致性**：★★★★★（强一致）

PRD 的核心治理哲学是"结果导向，而非微观管理"：
- architecture_constraints.json 应保持纯粹的设计基线身份
- 操作元数据（谁、何时接受了某规则）不应混入设计文档
- "Markdown for Human, JSON for Machine, HTML for Review" 原则：human decisions 是面向 Dashboard 展示的元数据，应独立存放

**当前代码偏差**：`accept.py` 直接写入 constraints.json → 违反 STORE-VT-004 → 违反 SHA-256 保护 → Gate 1 不可靠。

**合理性**：✅ **必须实施**。如果不修复，merge gate 永远无法信任自己的基线校验。

#### 变更 2：`verification_method` 过滤

**PRD 一致性**：★★★★（一致）

AC-VT-001-03 要求无证据结论不得显示为完成。machine 规则必须由工具执行验证，人类确认在语义上无意义。compliance checker 已遵循此约定，accept.py 应保持一致。

**合理性**：✅ **应当实施**。低风险，少量代码改动，消除与 compliance checker 的不一致。

#### 变更 3：结构化 change log + Dashboard proposals

**PRD 一致性**：★★★★（一致）

AC-VT-006-01 要求 Dashboard 展示核心治理维度，包括架构变更。当前 proposals 表格是死 UI，`_find_differences()` 数据被浪费。

**合理性**：✅ **应当实施**。基础设施已就绪，只差串联。填补"检测到变化 → 在 Dashboard 展示变化"的空缺。

#### 变更 4：PRD 漂移检测（无需改动）

**PRD 一致性**：★★★★★（强一致，经代码验证）

AC-VT-009-14 明确规定 PRD 哈希不匹配时输出 WARNING（不阻断）。映射校验已覆盖所有结构性破坏。

**合理性**：✅ **确认无需改动**。

#### 额外修复：MergeGateEngine 识别 `accepted_rule` 动作

**PRD 一致性**：★★★★（一致）

AC-VT-008-03 要求门禁结论必须包含决策依据。如果人类在 Dashboard 上确认或拒绝某条架构规则，该决策应纳入门禁判定依据。

**合理性**：✅ **应当实施**。完成 `accepted_rule` 端到端链路的最后一段。

---

## 四、变更依赖关系（修正版）

```
(1) accept → human_decisions.json
    └── verification_method 过滤（inline 实现）
        ├── compliance checker 增加 human_decisions 参数
        │   └── 改为从 human_decisions.json 读取（而非从 constraints.json 读 embedded 字段）
        ├── analysis.py 传递 human_decisions
        └── pipeline.py 串联数据流

(2) MergeGateEngine 识别 accepted_rule 动作 ← 新增
    └── 独立于变更 1，但数据流共享 human_decisions.json

(3) 结构化 change log ← 独立，finalize 内部改造
    ├── finalize 时 _find_differences() → 写入结构化日志
    └── check_governance() → proposals 填充 → Dashboard 渲染

(4) PRD 漂移 ← 无需改动 ✅

(5) human_decisions.schema.json ← 独立，纯质量改善
```

---

## 五、需要修改的文件（修正版）

| 文件 | 变更内容 | 关联变更 |
|------|---------|---------|
| `src/vibe_tracing/commands/accept.py` | **重写** `run_accept()`：写入 `human_decisions.json`，校验 `verification_method` | 变更 1+2 |
| `.vibetracing/human_decisions.json` | 决定数据结构（与 `decision_server.py` 对齐），或新建 schema | 变更 1 |
| `src/vibe_tracing/decision_server.py` | 确认 accepted_rule category 的处理逻辑 | 变更 1 |
| `src/vibe_tracing/architecture_compliance_checker.py` | `check()` 增加 `human_decisions` 参数；从 decisions 中查找 `accepted_rule`（替代从 constraints.json 读 embedded 字段） | 变更 1 |
| `src/vibe_tracing/commands/analyze/analysis.py` | 传递 `human_decisions` 到 compliance checker | 变更 1 |
| `src/vibe_tracing/commands/analyze/pipeline.py` | 串联 `human_decisions` 到 compliance checker 调用链 | 变更 1 |
| `src/vibe_tracing/merge_gate_engine.py` | 增加 `accepted_rule` 的 `reconfirm`/`reject` 动作处理 | 变更 2 |
| `src/vibe_tracing/architecture_change_proposal.py` | `check_governance()` 从结构化日志填充 `proposals` | 变更 3 |
| `src/vibe_tracing/commands/finalize.py` | `_validate_constraints_change()` 改为解析结构化日志；finalize 时写结构化 Change Log JSON | 变更 3 |
| `src/vibe_tracing/schemas/human_decisions.schema.json` | **新增**：human_decisions 的 JSON Schema | 变更 5 |
| `src/vibe_tracing/schemas/architecture_constraints.schema.json` | 从规则 item 中移除 `accepted_by`/`accepted_at` 字段定义（移到 human_decisions schema） | 变更 1 |

---

## 六、实施优先级

| 优先级 | 改动 | 独立程度 | PRD 合理性评级 | 工作量估计 |
|--------|------|---------|---------------|-----------|
| P0 | accept → human_decisions.json + verification_method | 高 | ★★★★★ | 低（~50 行） |
| P0+ | compliance checker 接入 human_decisions | 依赖 P0 | ★★★★★ | 中（~80 行） |
| P0+ | pipeline/analysis 传递 human_decisions | 依赖 P0 | ★★★★★ | 低（~20 行） |
| P1 | MergeGateEngine 识别 accepted_rule | 独立 | ★★★★ | 低（~30 行） |
| P1 | 结构化 change log + proposals 填充 | 独立 | ★★★★ | 中（~150 行） |
| P2 | human_decisions.schema.json | 独立 | ★★★ | 低（~30 行） |
| P2 | 清理 constraints schema 中的 accepted_by/accepted_at | 独立 | ★★★ | 低（~100 行 schema 改动） |
