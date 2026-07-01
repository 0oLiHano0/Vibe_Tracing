# 阶段 8 代码逻辑审核：pipeline.py vs spec_stage7_business_logic_v2.md

审核日期：2026-07-01
审核范围：`_evaluate_and_output` → `_run_analysis_phase` → `_run_gate_evaluation` → `MergeGateEngine.evaluate`

---

## 审核结论

阶段 8 的六维分类判定逻辑正确实现了 spec 的决策框架。审核中发现三个值得关注的问题，其中 1 个需修复、2 个为架构风险。

**重要发现：spec 文档明显过时。** spec 中标记的三个代码差距（module code path 错位、lint 入库、`in_progress` 不需要阻断）在实际代码中已被修复，但 spec 未同步更新。

---

## 六维分类逐项判定

### 1. 链条中断 ✅

| 环节 | 结果 |
|------|------|
| spec 要求 | task→req/ac/module/constraint 引用不存在 ID → **阻拦** |
| 阶段 7 | `check_invalid_task_*` 5 种查询 |
| 阶段 8 | `_check_invalid_task_references` → 对应 4 种引用 → `blocked` |
| 阶段 8 | `_check_dangling_claims` → claim→task 引用不存在 → `blocked` |

**判定：** 完全覆盖，处理正确。

### 2. 链条错位 ✅（spec 已过时）

| 环节 | 结果 |
|------|------|
| spec 要求 | 所有引用存在，但交叉验证矛盾 → **阻拦** |
| 阶段 7 | `check_invalid_ac_parent` + `_check_module_code_path_mismatch` |
| 阶段 8 | `_check_invalid_task_references` → `invalid_ac_parents` + `invalid_module_code_paths` → `blocked` |

spec 中标记 `⚠️ 未检查 code_path vs module 矛盾`，但 `_check_module_code_path_mismatch()` 已在 `db_analysis.py` 中实现，且 engine.py 中 `invalid_module_code_paths` 处理路径完整。代码已覆盖两种错位类型。

**判定：** 完全覆盖，spec 需同步更新。

### 3. 孤立任务 ⚠️

| 环节 | 结果 |
|------|------|
| spec 要求 | 任务无关联需求/AC/模块 → **告警** |
| 阶段 7 | `check_isolated_tasks` → `analysis_details["isolated_tasks"]` |
| 阶段 8 | 传入 `_build_report_document` ✅，但**未传入** `MergeGateEngine.evaluate()` ❌ |

**关键问题：** 孤立任务仅出现在报告中，不在 gate 终端输出中。spec 要求"告警→Dashboard 可见"，报告确实包含，但终端 `vt analyze` 输出看不到孤立任务的标记。

**建议修复：** 将 `isolated_tasks` 传入 `MergeGateEngine.evaluate()` 作为 gap 或 reason 展示。

### 4. 无声明 ✅（spec 已过时）

| 环节 | 结果 |
|------|------|
| spec 要求 | `done` + 无 Claim → **阻拦**；`in_progress` + 无 Claim → **容忍** |
| 阶段 7 | `check_ac_coverage` SQL 中 `WHEN t.status != 'done' AND c.claim_id IS NULL THEN 'covered'`，已过滤 `in_progress` |
| 阶段 8 | `_check_ac_coverage` → `blocked`（仅收到 `done` 任务的 `no_claim_for_task`） |

spec 中标记 `⚠️ 当前不区分 task 状态，应改为仅 done 阻断`。查询层在 `queries.py:39` 已实现 `status != 'done'` 过滤，阶段 8 收到的数据天然仅含 `done` 任务的缺口。代码已修复。

**判定：** 完全覆盖，处理正确。spec 需同步更新。

### 5. 任务失败 ✅

| 环节 | 结果 |
|------|------|
| spec 要求 | 测试失败 → **阻拦** |
| 阶段 7 | `check_claim_evidence` → `test_failed` |
| 阶段 8 | `_check_claim_evidence_gaps` → `verification_status == "test_failed"` → `blocked` |

**判定：** 完全覆盖，处理正确。

### 6. 任务不达标 ✅（spec 已过时）

| 环节 | 结果 |
|------|------|
| spec 要求 | 覆盖率低于阈值 / lint 违规 → **告警** |
| 阶段 7 | `check_coverage_violations` + `check_lint_violations` |
| 阶段 8 | `_compute_gate_decision` → 均作为 warning（→`fail` 非 blocking） |

spec 中标记 `❌ lint 结果未入库`，但 `check_lint_violations()` + `lint_results` 表已实现，engine 中 `_compute_gate_decision` 已完整处理。

仍然存在的差距：覆盖率违规未与具体 Claim 关联（文件级而非 claim 级）。

**判定：** 覆盖完整，spec 需同步更新。

---

## 发现的问题

### 问题 1（需修复）：孤立任务未纳入门禁输出

**位置：** `pipeline.py:_run_gate_evaluation` → 调用 `MergeGateEngine.evaluate()` 时 `isolated_tasks` 未传入

**当前路径：**
```
check_isolated_tasks → analysis_details["isolated_tasks"]
  ├── _build_report_document ✅（报告可见）
  └── MergeGateEngine.evaluate ❌（终端不可见）
```

**影响：** spec 要求孤立任务为"告警"级别，应在终端输出中可见。当前仅在报告中可见，`vt analyze` 终端未展示。

**推荐修复：** 在 `MergeGateEngine.evaluate()` 参数中增加 `isolated_tasks`，在 `_compute_gate_decision` 或 `_process_should_gaps` 中追加到 reasons 列表。

### 问题 2（架构风险）：`_process_must_gaps` 仅处理 AC 类型

**位置：** `engine.py:_process_must_gaps` line 414

```python
if item_type == "ac":
    # 仅 AC 类型走 blocking 逻辑
```

`merged_gaps` 中 `item_type` 为 `requirement`、`claim`、`task` 的项全部落入 `_process_should_gaps` → 非阻塞路径。虽然 blocking 判定已由 Rule 3/4/5/9 分别覆盖，但这是**隐式依赖**——新增 gap 类型时易遗漏对应的 blocking 处理。

**建议：** 在 `_process_must_gaps` 中增加断言或兜底逻辑，确保所有已知 item_type 都有预期处理路径，或加注释说明哪些类型依赖外部 Rule。

### 问题 3（架构风险）：AC 覆盖缺口增量判断维度不匹配

**位置：** `engine.py:_check_ac_coverage` line 296

```python
if not self.incremental_only or self._is_current({ac_id}, staged_items):
```

对于 `no_claim_for_task` 类型的 AC 缺口，增量判断维度应为 `task_id` 而非 `ac_id`。当前用 `ac_id` 判断是否当期，可能导致 pre-existing 缺口误判为当期阻塞（AC ID 不在 staged_items 中，但任务相关文件改了）。

**影响：** 小。增量模式下 `staged_items` 集合已包含受影响的 claim/task/AC/req ID。但 AC 缺口的"受影响"维度来自任务，而非 AC 本身。

---

## 阶段 8 调用链总览

```
_evaluate_and_output (pipeline.py)
├── _run_analysis_phase          → 过滤 stale、构建 staged_items
│   ├── active_gaps              = merged_gaps minus stale
│   ├── active_risks             = final_risks minus stale
│   ├── staged_items             = 受影响的 claim/task/ac/req ID
│   └── directly_staged_items    = 直接 staged 的 claim ID
├── _run_gate_evaluation         → 调用 MergeGateEngine
│   ├── Rule 2: Ghost code       → blocked
│   ├── Rule 3: Dangling claim   → blocked
│   ├── Rule 4: Evidence gap     → test_failed → blocked
│   ├── Rule 5: AC coverage      → blocked
│   ├── Rule 9: Invalid refs     → blocked
│   ├── Must gaps/risks          → blocked (仅 AC 类型)
│   ├── Should gaps/risks        → fail (非 blocking)
│   ├── Coverage/lint            → fail (非 blocking)
│   └── Compliance               → blocked/fail
├── _build_report_document       → 追溯报告
├── _render_output               → Dashboard + 终端
└── exit_code                    → 0=pass / 2=blocked
```

---

## 与 spec 的差异总结

| spec 声称的差距 | 代码实际状态 | 建议 |
|----------------|-------------|------|
| `code_path vs module` 未检查 | ✅ 已实现 `_check_module_code_path_mismatch` | 更新 spec |
| `in_progress` 不区分 | ✅ 查询层已过滤 `status != 'done'` | 更新 spec |
| lint 未入库 | ✅ `check_lint_violations` + `lint_results` 表已实现 | 更新 spec |
| 覆盖率未与 Claim 关联 | ⚠️ 仍为文件级，未 claim 级 | 保持标记 |
