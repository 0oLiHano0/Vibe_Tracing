# 设计基线净化与决策链路重构 — 实施计划

基于 `design_phase_architecture_analysis.md` 和 5 路线下 agent 探查结果，制定可独立调度的原子化实施计划。

---

## 设计原则

1. **每个任务 = 一个 subagent 可独立完成的工作单元** — 任务说明包含完整的输入/输出/范围/验收标准，subagent 无需阅读其他任务文档
2. **不考虑向后兼容** — 现有 `architecture_constraints.json` 中的 `accepted_by`/`accepted_at` 字段将被一次性迁移后移除
3. **数据流先行** — 先定义数据格式（Schema），再实现写入者，最后适配读取者
4. **每任务完成后可 `git commit`** — 任务间通过 git 状态传递依赖

---

## 依赖关系总图

```
T1: human_decisions.schema.json (独立)
  │
T2: accept 命令重写 ──────────── 依赖 T1
  │
T3: 数据迁移脚本 ──────────────── 依赖 T2
  │                            (提取 constraints.json 中现有 accepted_by → human_decisions.json)
  │
T4: compliance checker 适配 ──── 依赖 T2（格式确定即可，无需等 T3）
  │
T5: pipeline 数据流串联 ──────── 依赖 T4
  │
T6: MergeGateEngine accepted_rule ── 独立（只读 human_decisions.json 格式）
  │
T7: check_governance 填充 proposals ── 独立（只改 architecture_change_proposal.py）
  │
T8: cleanup: constraints schema ───── 依赖 T3（迁移完成后再清理）
  │
T9: 集成测试 ──────────────────── 依赖 T2~T8
```

**可并行调度：** T1 → T2 + T6 + T7（T2 依赖 T1，T6/T7 不依赖任何人）

---

## T1: Human Decisions Schema 定义

**目标**：为 `human_decisions.json` 定义 JSON Schema，作为数据格式契约。

**范围**：
- 只创建 1 个 schema 文件
- 不修改任何 Python 代码
- 不修改任何其他文件

**文件**：
- 新建 `src/vibe_tracing/schemas/human_decisions.schema.json`

**Schema 设计**：

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Human Decisions",
  "description": "记录人类对架构规则、风险、缺口等事项的决策记录",
  "type": "object",
  "required": ["version", "decisions"],
  "properties": {
    "version": {
      "type": "string",
      "description": "Schema 版本号，当前为 \"1.0\"",
      "enum": ["1.0"]
    },
    "decisions": {
      "type": "array",
      "description": "决策条目列表",
      "items": {
        "type": "object",
        "required": ["decision_id", "category", "targetId", "action", "decidedBy", "timestamp"],
        "properties": {
          "decision_id": {
            "type": "integer",
            "description": "决策 ID，从 1 开始递增"
          },
          "category": {
            "type": "string",
            "enum": ["accepted_rule", "accept_risk", "mark_complete", "resolved_gap"],
            "description": "决策分类"
          },
          "targetId": {
            "type": "string",
            "description": "决策对象 ID，如 rule_id/gap_id/risk_id"
          },
          "action": {
            "type": "string",
            "enum": ["accept", "reconfirm", "reject", "accept_risk", "mark_complete", "defer"],
            "description": "决策动作类型"
          },
          "reason": {
            "type": "string",
            "description": "人类决策理由"
          },
          "decidedBy": {
            "type": "string",
            "description": "决策者标识，如 human"
          },
          "timestamp": {
            "type": "string",
            "format": "date-time",
            "description": "决策时间，ISO 8601 格式"
          }
        }
      }
    }
  }
}
```

**预期产出**：
- `src/vibe_tracing/schemas/human_decisions.schema.json`

**DoD**：
1. 合法 JSON Schema 文件，可通过 `jsonschema` 库加载
2. 覆盖 `version`、`decisions`、`decision_id`、`category`、`targetId`、`action`、`reason`、`decidedBy`、`timestamp` 字段
3. `category` 枚举包含 `accepted_rule`、`accept_risk`、`mark_complete`、`resolved_gap`
4. `action` 枚举包含 `accept`、`reconfirm`、`reject`、`accept_risk`、`mark_complete`、`defer`
5. 存在对应的单元测试文件 `tests/test_schema_contracts.py`（扩展已有文件或新建），校验 schema 可加载且能拒绝非法格式

---

## T2: `vt accept` 命令重写

**目标**：将 `run_accept()` 从直接修改 `architecture_constraints.json` 改为写入 `human_decisions.json`，并增加 `verification_method` 过滤。

**范围**：
- 只修改 `accept.py`
- 不涉及 compliance checker、pipeline 或其他模块
- 不删除 constraints.json 中的现有 `accepted_by`/`accepted_at`（由 T3 处理）

**键变更**：

1. **移除**：不再读取、修改、回写 `architecture_constraints.json`
2. **移除**：不再设置 `accepted_by`/`accepted_at` 字段
3. **新增**：读取 `architecture_constraints.json` 查找 rule 的 `verification_method` 字段
4. **新增**：如果 `verification_method == "machine"` 或字段缺失（默认 machine），输出错误信息 `"规则 {rule_id} 需通过程序验证，不支持人工确认"` 并返回 1
5. **新增**：写入 `human_decisions.json`，追加一条 `category: "accepted_rule"`、`action: "accept"` 的 decision 条目
6. **新增**：`decision_id` 自增（从现有 decisions 中取最大 `decision_id` + 1）

**写入 human_decisions.json 的格式样例**：

```python
entry = {
    "decision_id": new_id,
    "category": "accepted_rule",
    "targetId": rule_id,
    "action": "accept",
    "reason": "",
    "decidedBy": accepted_by,
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
```

**读取逻辑**：
```python
decisions_path = project_root / ".vibetracing" / "human_decisions.json"
if decisions_path.exists():
    data = json.loads(decisions_path.read_text())
    decisions = data.get("decisions", [])
else:
    decisions = []
# 追加新 decision
# 写回
output = {"version": "1.0", "decisions": decisions}
decisions_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
```

**查找 rule 的逻辑不变**（遍历 15 个 rule key 数组，按 `rule_id`/`principle_id` 等匹配），仅增加 `verification_method` 检查。

**预期产出**：
- `src/vibe_tracing/commands/accept.py` — 重写

**DoD**：
1. `vt accept RULE_ID` 对 `verification_method == "manual"` 的规则写入 `human_decisions.json`，返回 0
2. `vt accept RULE_ID` 对 `verification_method == "machine"` 的规则拒绝并提示原因，返回 1
3. `vt accept RULE_ID` 对缺失 `verification_method` 的规则拒绝（默认 machine），返回 1
4. 重复 accept 同一规则时检测到已存在（检查 human_decisions.json 中是否已有对应 `targetId` 和 `category="accepted_rule"`），输出 "already accepted" 并返回 0（不重复写入）
5. 不存在的 rule_id 返回 1
6. `architecture_constraints.json` 的内容不被修改（SHA-256 不变）
7. 存在对应的测试文件 `tests/test_accept.py`，覆盖上述场景

---

## T3: 现有 accepted_by 数据迁移脚本

**目标**：一次性迁移工具，将 `architecture_constraints.json` 中所有现有 `accepted_by` 规则的记录提取到 `human_decisions.json`，然后从 constraints.json 中清除 `accepted_by`/`accepted_at` 字段。

**范围**：
- 只创建 1 个一次性迁移脚本
- 不修改现有命令代码
- 运行后 `architecture_constraints.json` 中所有 `accepted_by`/`accepted_at` 字段被删除

**文件**：
- 新建 `src/vibe_tracing/scripts/migrate_accepted_rules.py`

**逻辑**：
1. 读取 `architecture_constraints.json`
2. 遍历所有 15 个规则数组
3. 对于每个有 `accepted_by` 字段的规则：
   a. 读取已有的 `human_decisions.json`
   b. 检查是否已存在 `category="accepted_rule"` + `targetId=rule_id` 的记录（防重复）
   c. 不存在则追加一条 decision 记录，使用现有 `accepted_at` 作为 `timestamp`
4. 从所有规则对象中删除 `accepted_by` 和 `accepted_at` 键
5. 写回 `architecture_constraints.json`（清理后）和 `human_decisions.json`（新记录后）

**CLI 入口**：在 `cli.py` 注册 `vt migrate-accepted-rules` 命令，或作为独立 Python 模块 `python -m vibe_tracing.scripts.migrate_accepted_rules`

**预期产出**：
- `src/vibe_tracing/scripts/migrate_accepted_rules.py`
- `cli.py` 新增 `migrate-accepted-rules` 子命令（如需）

**DoD**：
1. 运行后 `architecture_constraints.json` 中不再有 `accepted_by` 或 `accepted_at` 键
2. 所有被迁移的规则在 `human_decisions.json` 中有对应的 `category="accepted_rule"` 条目
3. `decision_id` 正确递增（不与其他已有 decision 冲突）
4. 重复运行是幂等的（第二次运行不产生重复条目）
5. 存在对应的测试

---

## T4: Compliance Checker 接入 human_decisions

**目标**：让 `ArchitectureComplianceChecker.check()` 从 `human_decisions.json` 读取 `accepted_rule` 数据，替代直接从 `architecture_constraints.json` 读 `accepted_by`/`accepted_at` 字段。

**范围**：
- 只修改 `architecture_compliance_checker.py`
- 不修改 pipeline、analysis.py、merge_gate_engine.py
- `check()` 方法签名增加 `human_decisions` 参数

**变更**：

1. **`check()` 签名变更**：
   ```python
   def check(
       self,
       evidences: List[Dict[str, Any]],
       constraints_data: Dict[str, Any],
       human_decisions: Optional[dict] = None,  # 新增
   ) -> Dict[str, Any]:
   ```

2. **内部逻辑变更**（原 `check_quality_gates()` 中约第 731-744 行）：
   - 当前：读取 `rule.get("accepted_by")` 判断规则是否被接受
   - 改为：从 `human_decisions` 的 `decisions` 数组中查找 `category == "accepted_rule"` 且 `targetId == rule_id`、`action == "accept"` 的条目
   - 构建 `accepted_rules` 列表时，从匹配到的 decision 条目中提取 `decidedBy` → `accepted_by`、`timestamp` → `accepted_at`

3. **保持输出格式不变**：
   ```python
   # 已有 Dashboard 和 agent actions 都依赖此格式
   accepted_rules 列表中的每条记录格式不变：
   {"rule_id": str, "title": str, "accepted_by": str, "accepted_at": str, ...}
   ```

4. **向后兼容**：当 `human_decisions is None` 时，行为不变（仍然从 constraints.json 读 embedded 字段）。当 `human_decisions` 提供时，优先使用 human_decisions.json。

**预期产出**：
- `src/vibe_tracing/architecture_compliance_checker.py` — 修改

**DoD**：
1. `check(evidences, constraints_data, human_decisions={"version": "1.0", "decisions": [{"category": "accepted_rule", "targetId": "RULE-001", "action": "accept", "decidedBy": "human", "timestamp": "2026-06-12T00:00:00Z", "decision_id": 1}]})` 正确将 RULE-001 识别为已接受
2. 不传 `human_decisions` 时行为不变（回退到 constraints.json 的 embedded 字段）
3. 输出的 `accepted_rules` 与重构前格式一致
4. 测试覆盖：human_decisions 中有记录、无记录、human_decisions=None 三种场景

---

## T5: Pipeline 数据流串联

**目标**：将 `human_decisions` 的加载时机提前，传递给 `ArchitectureComplianceChecker.check()`，完成端到端数据流。

**范围**：
- 修改 `analysis.py` 和 `pipeline.py`
- 不修改 `architecture_compliance_checker.py`（已由 T4 修改）
- 不修改 `merge_gate_engine.py`（T6 处理）

**变更**：

1. **`analysis.py`**：
   - 在 `_run_analyzers()` 中新增 `human_decisions` 参数
   - 传递给 `ArchitectureComplianceChecker.check(human_decisions=human_decisions)`

2. **`pipeline.py`**：
   - 在 `run_analyze()` 中，在调用 `_run_analyzers()` **之前**加载 `human_decisions`
   - 传递给 `_run_analyzers(human_decisions=human_decisions)`
   - 注意：原有的 `_run_gate_evaluation()` 中的 `_load_human_decisions()` 调用可以保留（MergeGateEngine 还需要），也可以复用同一份数据

**加载位置**（pipeline.py `run_analyze` 中，约第 283-350 行之间）：
```python
# 在 _run_integrity_gates() 之后、_execute_tools() 之前
human_decisions = _load_human_decisions()
# ... 后续传递给 _run_analyzers
```

**数据传递路径**：
```
run_analyze()
  → _load_human_decisions()           ← 这里提前
  → _run_integrity_gates()
  → _execute_tools()
  → EvidenceIndexBuilder.build()
  → _run_analyzers(human_decisions=...)  ← 多了一个参数
      → ArchitectureComplianceChecker.check(human_decisions=...)
  → _evaluate_and_output()
      → _run_gate_evaluation()          ← 可以复用同一份 human_decisions
```

**预期产出**：
- `src/vibe_tracing/commands/analyze/analysis.py` — 修改
- `src/vibe_tracing/commands/analyze/pipeline.py` — 修改

**DoD**：
1. `human_decisions` 在 pipeline 中只加载一次，传递给所有消费者
2. `ArchitectureComplianceChecker.check()` 收到正确的 `human_decisions` 数据
3. `MergeGateEngine.evaluate()` 仍能正确收到 `human_decisions` 数据（复用或重新加载均可）
4. 所有测试通过

---

## T6: MergeGateEngine 识别 accepted_rule 动作

**目标**：让 `MergeGateEngine` 能识别 `category == "accepted_rule"` 的 decision 条目，使人类在 Dashboard 上做的"仍然有效"/"不再适用"决策不被静默丢弃。

**范围**：
- 只修改 `merge_gate_engine.py` 的 `evaluate()` 方法中约第 594-600 行的 decision 处理逻辑

**变更**：

扩展 decision 处理循环（当前只收集 `accept_risk` 和 `mark_complete`）：

```python
accepted_risk_target_ids: Set[str] = set()
resolved_gap_target_ids: Set[str] = set()
accepted_rule_target_ids: Set[str] = set()  # 新增
rejected_rule_target_ids: Set[str] = set()  # 新增

for d in decisions_list:
    action = d.get("action", "")
    target_id = d.get("targetId", "")
    category = d.get("category", "")
    
    if action == "accept_risk" and target_id:
        accepted_risk_target_ids.add(target_id)
    elif action == "mark_complete" and target_id:
        resolved_gap_target_ids.add(target_id)
    elif category == "accepted_rule" and target_id:
        if action == "reconfirm":
            accepted_rule_target_ids.add(target_id)
        elif action == "reject":
            rejected_rule_target_ids.add(target_id)
```

**应用场景**：
- `accepted_rule_target_ids`：在架构约束校验中，如果某条 manual 规则被人类重新确认（`reconfirm`），compliance checker 可以识别"此规则已获确认，仍然有效"
- `rejected_rule_target_ids`：如果人类拒绝（`reject`），则视为该规则不再适用

**注意**：当前阶段只需正确收集这些 ID 集合并使其可通过 `gate_res` 返回即可。具体的门禁判定策略（如何消费 `accepted_rule_target_ids` / `rejected_rule_target_ids`）可在下一轮迭代中细化。

**预期产出**：
- `src/vibe_tracing/merge_gate_engine.py` — 修改

**DoD**：
1. `category="accepted_rule"` 且 `action="reconfirm"` 的 decision 被收集到 `accepted_rule_target_ids`
2. `category="accepted_rule"` 且 `action="reject"` 的 decision 被收集到 `rejected_rule_target_ids`
3. 原有逻辑（`accept_risk`/`mark_complete`）不受影响
4. `human_decisions_applied` 计数正确（包含所有已识别 action）
5. 测试覆盖：reconfirm、reject、无关 category/action 不被收集

---

## T7: check_governance() 填充 proposals

**目标**：让 `ArchitectureChangeProposalEngine.check_governance()` 填充 `proposals` 数组，使 Dashboard Bootstrap tab 的 proposals 表格不再为空。

**范围**：
- 只修改 `architecture_change_proposal.py` 的 `check_governance()` 方法
- 不涉及 finalize.py、dashboard_renderer.py 或其他文件

**变更**：

`check_governance()` 中已有 `_find_differences(base_data, curr_data)` 调用（第 282 行），其返回值是一个 diff 列表。只需要在返回结果中将 diff 数据格式化为 `proposals` 数组。

在 `_empty_result()` 调用前（约第 300-331 行），添加：

```python
# 格式化 proposals 数组
proposals = []
if diffs:
    for diff in diffs:
        action = diff.get("action", "modify")
        value = diff.get("value", "")
        path = diff.get("path", "")
        rule_id = diff.get("rule_id", None)
        
        proposal = {
            "proposal_id": f"PROP-{len(proposals) + 1}",
            "author": "system (auto-detected)",
            "rationale": f"架构约束变更检测：{action} {path}",
            "proposed_changes": [
                {
                    "action": action,
                    "constraint_path": path,
                }
            ],
            "status": "pending",
            "human_approval": None,  # 等待人类确认
        }
        proposals.append(proposal)
```

并修改返回值为 `{...existing keys..., "proposals": proposals}` 而非 `{"proposals": []}`。

**Dashboard 渲染不变**：`dashboard_renderer.py:87` 已注入 `prop_data_json`，Dashboard 前端 `renderBootstrap()` 已能渲染 proposals 表格。无需修改渲染端。

**预期产出**：
- `src/vibe_tracing/architecture_change_proposal.py` — 修改

**DoD**：
1. `check_governance()` 在 constraints 有变更时返回非空 `proposals` 数组
2. 每条 proposal 包含 `proposal_id`、`author`、`rationale`、`proposed_changes`、`status`、`human_approval`
3. 每条 `proposed_changes` 包含 `action` 和 `constraint_path`
4. constraints 无变更时返回空的 `proposals` 数组（`[]`）
5. Dashboard 渲染后 Bootstrap tab 的 proposals 表格显示每条变更记录
6. 测试覆盖：有变更、无变更两种场景

---

## T8: 清理 constraints schema 中的 accepted_by/accepted_at

**目标**：从 `architecture_constraints.schema.json` 的所有规则 item 定义中移除 `accepted_by` 和 `accepted_at` 字段

**范围**：
- 只修改 schema 文件
- 不修改 Python 代码
- 仅在 T3（数据迁移）完成后执行

**文件**：
- `src/vibe_tracing/schemas/architecture_constraints.schema.json`

**变更**：
1. 在所有 13+ 个规则 item 的 `properties` 中删除 `accepted_by` 和 `accepted_at` 键
2. 如果这两个字段出现在任何 `required` 数组中，也从 `required` 中移除（当前它们不在 required 中，但确认性检查）

**预期产出**：
- `src/vibe_tracing/schemas/architecture_constraints.schema.json` — 清理

**DoD**：
1. Schema 文件仍合法，可通过 `jsonschema` 加载
2. 不再包含 `accepted_by` 或 `accepted_at` 字段定义
3. 现有约束数据文件不加这两个字段也能通过 schema 校验

---

## T9: 集成测试

**目标**：端到端验证全套变更。

**范围**：
- 在已有测试文件中新增测试用例，或新建 `tests/test_arch_refactor_integration.py`
- 覆盖所有变更组件的交互路径

**测试场景**：

| 场景 | 步骤 | 期望 |
|------|------|------|
| accept manual 规则 | `vt accept MANUAL-RULE` → `vt analyze` | Gate 1a 通过，accepted_rules 显示已接受 |
| accept machine 规则 | `vt accept MACHINE-RULE` | 拒绝，返回 1 |
| accept 后 finalize | `vt accept RULE` → `vt finalize` | constraints hash 不变，finalize 成功 |
| accept 重复 | `vt accept RULE` × 2 | 第二次提示 "already accepted" |
| proposals 展示 | constraints 有变更时 run `vt analyze` | Dashboard 的 proposals 表格有内容 |
| human_decisions 格式 | 写入合法/非法数据 | Schema 校验通过/拒绝 |
| 迁移脚本 | 运行迁移 → accept 历史数据可读 | 迁移后 human_decisions.json 有历史记录 |
| MergeGate accepted_rule | 通过 POST 写入 reconfirm → run analyze | decision 被正确收集 |

**预期产出**：
- `tests/test_arch_refactor_integration.py` — 新建

**DoD**：
1. 所有测试场景通过
2. 不影响已有测试（`pytest tests/` 全部通过）

---

## 执行顺序建议

```
Day 1:
  ├── T1: human_decisions.schema.json (~30 min, 1 file)
  ├── T6: MergeGateEngine accepted_rule (~30 min, 1 file, 可并行)
  └── T7: check_governance proposals (~45 min, 1 file, 可并行)

Day 2:
  └── T2: accept 命令重写 (~60 min, 1 file)

Day 3:
  ├── T4: compliance checker 适配 (~45 min, 1 file)
  └── T5: pipeline 数据流串联 (~30 min, 2 files)

Day 4:
  ├── T3: 数据迁移脚本 (~30 min, 1 file)
  └── T8: schema 清理 (~15 min, 1 file)

Day 5:
  └── T9: 集成测试 (~60 min, 1 file)
```

每天工作量为 1-2 个原子任务，每个任务 15-60 分钟。
