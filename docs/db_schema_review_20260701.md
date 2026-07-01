# 数据库结构审核报告 2026-07-01

## 背景

基于 `docs/spec_stage7_business_logic_v2.md`（六维业务分类规约）对当前内存 SQLite 数据库的 15 张表 schema、表拆分、和查询逻辑进行评审。

---

## 一、逐项调查结论

### 1. 删除 `tasks.priority`

**结论：可删。** `tasks.priority` 仅在 `check_ac_coverage` 的 WHERE 条件中用过一次（`t.priority = 'must' OR ...`），但语义错位——优先级是需求的属性，不是任务的属性。一个任务可能同时为高优和低优需求服务。

**操作**：直接删除字段，AC 过滤改走 `requirements.priority`。

---

### 2. `arch_modules` 加 `path_pattern`，`arch_constraints` 加 `description`

**结论：必要。** 当前两个表是 ID-only 的空壳，无法实现规约要求的"代码路径 vs 模块"链条错位检查。

**操作**：`arch_modules` 加 `path_pattern TEXT`；`arch_constraints` 加 `description TEXT`。

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

---

### 6. `get_full_chain` 的 AC 关联路径

**结论：数据正确性问题。** 当前 SQL（line 121）：

```sql
FROM requirements r
LEFT JOIN acceptance_criteria ac ON r.req_id = ac.req_id          -- 从 req 直接走
LEFT JOIN task_requirements trq ON r.req_id = trq.req_id          -- task 也从 req 走
```

AC 不经过 `task_acs`，导致 AC 和 task 之间的关联是没有业务依据的笛卡尔积。同一个 requirement 下有 N 个 AC + M 个 task 时，产生 N×M 行，其中大量是虚假的 AC↔Task 配对。

**操作**：AC 应通过 `task_acs` 关联到 task，至少确保 AC 的展示范围与 task 的关联一致。

---

### 7. `check_ac_coverage` 与 `check_requirement_coverage` 过滤策略

**当前差异：**

| 查询 | 过滤条件 | 效果 |
|------|---------|------|
| `check_ac_coverage` | `t.priority = 'must' OR (r.priority = 'must' AND is_testing_required)` | 只查 MUST |
| `check_requirement_coverage` | 无 WHERE | 查全部 |

**业务判断**：规约 6 维模型不按优先级区分。非 MUST 的 AC 链路问题被静默忽略——这不是设计选择而是数据遗漏。

**操作**：统一为**全量检查不跳过**。如果 Dashboard 需要优先级分层展示，在展示层做而非检查层做。

---

### 8. `query_related_code` / `query_existing_tests` 的 Claim 限定

**现状**：`ClaimLoader` 无约束（一个 task 可以有多个 claim），`load_claims` 不做重复检查。查询走 `task_acs → claims → refs` 但不限定 claim_id。一个 task 有多个 claim 时，所有 claim 的数据全部返回。

**操作**：取决于业务模型选择：
- 若"一个 task 同时只有一个活跃 claim"：在 loader 或 schema 层加约束
- 若允许多 claim 共存（迭代修复）：按 `timestamp` 取最新 claim，或返回聚合结果

---

## 二、附加发现

### `evidence_meta` 缺 `coverage_baseline`

`build_evidence_meta()` 只返回 `{run_id, project_id, scan_time, full_chain}`，无 `"coverage_baseline"` key。导致 `reports.py:75` 的覆盖率汇总计算和格式化输出的"低于阈值文件列表"全是死代码。

### `check_coverage_violations` 不关联 Claim

返回全部 violated 记录，未限定到当前分析的 Claim 集合。Dashboard 可能展示不属于本次变更的历史覆盖率违规。

---

## 三、优先修复建议

| 优先级 | 编号 | 改动 | 工作量 | 理由 |
|--------|------|------|--------|------|
| **P0** | 6 | `get_full_chain` AC 关联修复 | 中 | **数据正确性问题**，Dashboard 展示虚假配对 |
| **P0** | 5 | 删除 `staged_files` 表及写入 | 简单 | 死表，无风险 |
| **P0** | 1 | 删除 `tasks.priority` + 清理 AC filter | 简单 | 死字段，语义错位 |
| **P1** | 7 | 统一 coverage 过滤为全量检查 | 中 | 消除 MUST-only 检测盲区 |
| **P1** | 2 | `arch_modules.path_pattern` + `arch_constraints.description` | 简单 | 为链条错位检查铺路 |
| **P1** | 4 | lint 接入 DB + 门禁 | 中 | 补齐"任务不达标"维度的 lint 缺口 |
| **P2** | 3 | 删除 `reports.py` dead `coverage_baseline` | 简单 | 死代码清理 |
| **P2** | 8 | Claim 多版本查询限定 | 中 | 取决于业务模型确认 |
| **P2** | — | 参数化查询替代 f-string | 简单 | 长期健壮性 |
