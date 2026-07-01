# 数据库结构审核报告 2026-07-01

## 背景

基于 `docs/spec_stage7_business_logic_v2.md`（六维业务分类规约）对当前内存 SQLite 数据库的 15 张表 schema、表拆分、和查询逻辑进行评审。

## 复审记录（2026-07-01）

本报告经过独立复审，逐项核对了代码实现。以下是复审结论和已确认的业务决策：

**已确认的业务决策：**
1. AC 检查全量化——检查层发现所有问题，Dashboard 负责分层呈现
2. 覆盖率违规只关注本次变更——历史债务在 Dashboard 呈现但不阻碍当前提交（已通过 `carried_over` 字段实现）
3. 一个 Task 对应一个 Claim——schema 层加 `UNIQUE(related_task)` 约束

**复审修正：**
- 第 1 项：使用次数统计有误（遗漏 SELECT/INSERT 用法），工作量上调
- 第 6 项：问题已在此前通过双查询设计修复，非新发现
- 第 8 项：业务模型已确认（一 task 一 claim），可直接实施

---

## 一、逐项调查结论

### 1. 删除 `tasks.priority`

**结论：可删。** `tasks.priority` 仅在 `check_ac_coverage` 的 WHERE 条件中用过一次（`t.priority = 'must' OR ...`），但语义错位——优先级是需求的属性，不是任务的属性。一个任务可能同时为高优和低优需求服务。

**操作**：直接删除字段，AC 过滤改走 `requirements.priority`。

> **复审修正**：原报告称"仅在 WHERE 中用过一次"不准确。`tasks.priority` 还在 `get_full_chain` 的两个 SELECT 子查询中输出，且由 `load_tasks`（loaders.py:26）写入。删除需同步清理 4 处（schema、loader、get_full_chain Query A/B、测试），工作量从"简单"上调为"中"。需先确认 `get_full_chain` 返回的 priority 字段是否被 Dashboard 模板消费。

---

### 2. `arch_modules` 加 `path_pattern`，`arch_constraints` 加 `description`

**结论：必要。** 当前两个表是 ID-only 的空壳，无法实现规约要求的"代码路径 vs 模块"链条错位检查。

**操作**：`arch_modules` 加 `path_pattern TEXT`；`arch_constraints` 加 `description TEXT`。

> **复审补充**：分析正确，但实施时机需推迟。当前代码中没有代码路径 vs 模块比对的逻辑，加了字段但没有 loader/parser 写入、没有查询消费，等于更宽的废表。应等功能需求明确时再加。

---

### 3. `coverage_reports.num_statements` 是否在用？

**结论：部分在用。** 流经链路：

```
coverage JSON → parsers.py 提取 → builder.py merge → coverage_reports.json → Dashboard → HTML
```

但 `reports.py` 中有一段覆盖率汇总代码读 `evidence_meta["coverage_baseline"]`——这个 key **从来没人设过**，因此是死代码。

**操作**：字段保留（dashboard 在用），删除 `reports.py` 中 dead `coverage_baseline` 路径。

---

### 4. Lint 的使用现状与入库必要性

**结论：生成后丢弃，从未入库。** 链路追踪：

```
executor.execute_from_claims() → ruff/bandit 产出 ToolEvidenceCandidate
→ EvidenceBuilder.merge() → source_type="tool" 走 else 分支 → skipped[]
→ 丢弃，不写入 DB / JSON / Dashboard
```

`builder.py` line 65-70 只分发 `"test"` 和 `"coverage"` 两种 source_type。`"tool"` 类型（含 lint）全部跳过。

基础设施（executor + parser + candidate 模型）全部就位，但 merge 这一步没接上。

**操作**：在 `EvidenceBuilder.merge()` 中增加 `tool_category="lint"` 的路由，写入新表 `lint_results`，让 lint 参与"任务不达标"门禁判定。

> **复审补充**：链路分析完全正确。但 lint 入库是新功能扩展而非 bug 修复——当前项目基础链条检查尚未全部完成，lint 门禁的优先级应低于现有缺陷修复。标记为 feature request。

---

### 5. `staged_files` 表的消费方

**结论：表是死的，数据通过 Python set 传递。** `staged_files` 表由 `load_staged_files()` 写入，但 `queries.py` 中没有任何查询读它。实际消费方全部从 Python `set` 走：

| 消费方 | 用途 |
|--------|------|
| `domain/gate/claim_coverage.py` `find_claimed_and_affected()` | 幽灵代码检测 |
| `domain/gate/claim_coverage.py` `detect_ghost_code()` | 幽灵代码判定 |
| `domain/gate/staleness.py` `mark_staleness()` | 陈旧性标记 |
| `cli/analyze/output.py` `_print_empty_claims_hint()` | CLI 提示 |
| `cli/analyze/formatting.py` | urgency 计算 |

**操作**：删除 `staged_files` 表及写入代码。set 传递够用。

> **复审确认**：分析完全正确。`staged_files` 表确认为死表——写入但从未通过 SQL 读取。删除时需注意测试代码中对 `load_staged_files` 的调用也需同步清理。

---

### 6. `get_full_chain` 的 AC 关联路径

**结论：数据正确性问题。** ~~当前 SQL（line 121）：~~

~~```sql~~
~~FROM requirements r~~
~~LEFT JOIN acceptance_criteria ac ON r.req_id = ac.req_id          -- 从 req 直接走~~
~~LEFT JOIN task_requirements trq ON r.req_id = trq.req_id          -- task 也从 req 走~~
~~```~~

~~AC 不经过 `task_acs`，导致 AC 和 task 之间的关联是没有业务依据的笛卡尔积。同一个 requirement 下有 N 个 AC + M 个 task 时，产生 N×M 行，其中大量是虚假的 AC↔Task 配对。~~

~~**操作**：AC 应通过 `task_acs` 关联到 task，至少确保 AC 的展示范围与 task 的关联一致。~~

> **复审结论：此问题已在此前通过双查询设计修复，非新发现。** 当前 `queries.py:111-116` 文档明确说明了双查询设计意图——Query A 通过 `task_acs` 关联 AC 与 task，Query B 处理无 AC 的 requirement（用 `WHERE NOT EXISTS` 过滤）。两个查询分离避免了笛卡尔积。此条目可标记为"已关闭"。

---

### 7. `check_ac_coverage` 与 `check_requirement_coverage` 过滤策略

**当前差异：**

| 查询 | 过滤条件 | 效果 |
|------|---------|------|
| `check_ac_coverage` | `t.priority = 'must' OR (r.priority = 'must' AND is_testing_required)` | 只查 MUST |
| `check_requirement_coverage` | 无 WHERE | 查全部 |

**业务判断**：规约 6 维模型不按优先级区分。非 MUST 的 AC 链路问题被静默忽略——这不是设计选择而是数据遗漏。

**操作**：统一为**全量检查不跳过**。如果 Dashboard 需要优先级分层展示，在展示层做而非检查层做。

> **复审确认**：业务决策已明确——AC 检查应全量化，检查层负责发现所有问题，Dashboard 负责分层呈现。实施时去掉 `check_ac_coverage` 的 `WHERE t.priority = 'must' OR ...` 过滤条件，同步更新依赖"只查 MUST"行为的测试用例。

---

### 8. `query_related_code` / `query_existing_tests` 的 Claim 限定

**现状**：`ClaimLoader` 无约束（一个 task 可以有多个 claim），`load_claims` 不做重复检查。查询走 `task_acs → claims → refs` 但不限定 claim_id。一个 task 有多个 claim 时，所有 claim 的数据全部返回。

~~**操作**：取决于业务模型选择：~~
~~- 若"一个 task 同时只有一个活跃 claim"：在 loader 或 schema 层加约束~~
~~- 若允许多 claim 共存（迭代修复）：按 `timestamp` 取最新 claim，或返回聚合结果~~

> **复审结论：业务模型已确认——一个 Task 对应一个 Claim。** Claim 的本质是"对某个 task 完成状态的声明"，同一时刻只能有一个有效声明。实施方案：schema 层 `claims` 表加 `UNIQUE(related_task)` 约束，loader 使用现有的 `INSERT OR REPLACE` 即可。不再需要 timestamp 排序或聚合逻辑。

---

## 二、附加发现

### `evidence_meta` 缺 `coverage_baseline`

`build_evidence_meta()` 只返回 `{run_id, project_id, scan_time, full_chain}`，无 `"coverage_baseline"` key。导致 `reports.py:75` 的覆盖率汇总计算和格式化输出的"低于阈值文件列表"全是死代码。

> **复审确认**：属实。`reports.py:75` 和 `formatting.py:90` 两处读取 `coverage_baseline` 始终得到 `{}`，相关计算和格式化代码为死代码。

### `check_coverage_violations` 不关联 Claim

返回全部 violated 记录，未限定到当前分析的 Claim 集合。Dashboard 可能展示不属于本次变更的历史覆盖率违规。

> **复审补充**：此问题已通过增量模式下的 `carried_over` 字段部分解决——`check_coverage_violations` 已返回 `carried_over` 标记，`_compute_gate_decision` 在增量模式下过滤历史违规。全量模式下返回所有违规记录属于预期行为。

---

## 三、优先修复建议（复审修订版）

| 优先级 | 编号 | 改动 | 工作量 | 理由 | 状态 |
|--------|------|------|--------|------|------|
| **P0** | 5 | 删除 `staged_files` 死表 + `load_staged_files` 函数 | 简单 | 死表，零风险 | 已完成 |
| **P0** | 8 | Claim 唯一约束 `UNIQUE(related_task)` | 简单 | 业务决策已确认（一 task 一 claim） | 已完成 |
| **P0** | 7 | `check_ac_coverage` 去掉 priority 过滤，全量检查 | 中 | 业务决策已确认（全量检查） | 已完成 |
| **P1** | 1 | 删除 `tasks.priority` 字段 | 中 | 第 7 项完成后 priority 无消费方，需确认 Dashboard 依赖 | 已完成 |
| **P1** | 3 | 清理 `coverage_baseline` 死代码 | 简单 | `reports.py:75` + `formatting.py:90` 两处 | 已完成 |
| **P2** | 2 | `arch_modules.path_pattern` + `arch_constraints.description` | 简单 | 代码路径 vs 模块的错位检查已通过 Python 层实现，无需 schema 字段 | 搁置（规则已实现） |
| **P2** | 4 | lint 入库 + 门禁接入 | 中 | 新功能扩展，非 bug 修复 | 已完成 |
| **P2** | — | 参数化查询替代 f-string | 简单 | 长期健壮性 | 已完成 |
| ~~P0~~ | ~~6~~ | ~~`get_full_chain` AC 关联修复~~ | — | **已关闭**：双查询设计已修复此问题 | 已完成 |

### 与原版差异说明

- **第 6 项**：原标 P0，复审确认已修复，移除
- **第 1 项**：原标 P0/简单，复审发现使用点遗漏，降为 P1/中，依赖第 7 项先完成，已于 2026-07-01 实施（Dashboard 不消费 `task_priority`）
- **第 7 项**：原标 P1，业务决策确认后升为 P0，已于 2026-07-01 实施
- **第 8 项**：原标 P2/待确认，业务模型确认后升为 P0
- **第 2、4 项**：原标 P1，复审认为时机未到（无消费方/新功能），降为 P2
