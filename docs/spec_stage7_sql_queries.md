# 阶段 7 SQL 查询全集

阶段 7 是 Pipeline 的分析引擎，通过内存 SQLite 数据库执行 15 个查询（12 个 `check_*` + 2 个辅助查询 + 1 个全链路视图），覆盖从需求到测试证据的完整追溯链路。

## 数据库 Schema（15 张表）

```
┌────────────────────────────────────────────────────────────┐
│                        PRD 域                              │
│  requirements ──→ acceptance_criteria                      │
│  (req_id PK)      (ac_id PK, req_id FK)                    │
├────────────────────────────────────────────────────────────┤
│                       任务域                               │
│  tasks ──→ task_requirements (M:N)                         │
│  (task_id PK)  task_acs (M:N)                              │
│                task_modules (M:N)                           │
│                task_constraints (M:N)                       │
├────────────────────────────────────────────────────────────┤
│                      Claim 域                               │
│  claims ──→ claim_code_refs (1:N)                          │
│  (claim_id PK,    claim_test_refs (1:N)                    │
│   related_task FK)                                         │
├────────────────────────────────────────────────────────────┤
│                   测试与覆盖率域                            │
│  test_results        coverage_reports                      │
│  (nodeid PK)         (source_path PK)                      │
├────────────────────────────────────────────────────────────┤
│                     架构域                                  │
│  arch_modules       arch_constraints                        │
│  (module_id PK)     (constraint_id PK)                      │
├────────────────────────────────────────────────────────────┤
│                     Git 域                                   │
│  staged_files (file_path PK)                                │
└────────────────────────────────────────────────────────────┘
```

**表结构详情：**

| 表 | 主键 | 关键字段 | 灌入来源 |
|----|------|----------|----------|
| `requirements` | req_id | title, priority, category | `load_prd()` |
| `acceptance_criteria` | ac_id | req_id, title, is_testing_required | `load_prd()` |
| `tasks` | task_id | priority, status | `load_tasks()` |
| `task_requirements` | (task_id, req_id) | — | `load_tasks()` |
| `task_acs` | (task_id, ac_id) | — | `load_tasks()` |
| `task_modules` | (task_id, module_id) | — | `load_tasks()` |
| `task_constraints` | (task_id, constraint_id) | — | `load_tasks()` |
| `claims` | claim_id | related_task | `load_claims()` |
| `claim_code_refs` | (claim_id, code_path) | — | `load_claims()` |
| `claim_test_refs` | (claim_id, test_nodeid) | — | `load_claims()` |
| `test_results` | nodeid | outcome, exit_code | 阶段 6 EvidenceBuilder |
| `coverage_reports` | source_path | percent_covered, status | 阶段 6 EvidenceBuilder |
| `staged_files` | file_path | — | `load_staged_files()` |
| `arch_modules` | module_id | — | `load_architecture_constraints()` |
| `arch_constraints` | constraint_id | — | `load_architecture_constraints()` |

> **注意**：SQLite 内存数据库未启用外键约束，所有 JOIN 依赖数据一致性由灌入阶段保证。

---

## 查询分类总览

```
15 个查询
├── 核心覆盖查询（3）──→ 生成缺口（merged_gaps）
│   ├── check_requirement_coverage   需求覆盖链路
│   ├── check_ac_coverage            AC 覆盖链路
│   └── check_claim_evidence         Claim 证据链路
│
├── 辅助诊断查询（9）──→ 写入 analysis_details
│   ├── check_dangling_claims        Claim 悬空
│   ├── check_coverage_violations    覆盖率违规
│   ├── check_invalid_task_requirements  无效需求引用
│   ├── check_invalid_task_acs           无效 AC 引用
│   ├── check_invalid_task_modules       无效模块引用
│   ├── check_invalid_task_constraints   无效约束引用
│   ├── check_invalid_ac_parent         AC 父需求不匹配
│   ├── check_isolated_tasks            孤立任务
│   └── check_architectural_orphans     架构孤儿 → 也生成缺口
│
├── 辅助查询（2）──→ Dashboard 使用
│   ├── query_related_code          AC → 源码文件
│   └── query_existing_tests        AC → 测试用例
│
└── 全链路视图（1）──→ 供扩展使用
    └── get_full_chain              需求→测试完整链路
```

---

## 一、核心覆盖查询

这三个查询是阶段 7 的核心输出——其结果经 `_db_result_to_gaps()` 转换为缺口列表，直接影响阶段 8 门禁判定。

### 1. check_requirement_coverage

**业务问题**：每个需求是否被开发任务承接 → 任务是否有 Agent Claim 声明 → Claim 是否声明了测试 → 测试是否已执行并通过？

**覆盖链路**：`requirements → task_requirements → tasks → claims → claim_test_refs → test_results`

```sql
SELECT r.req_id,
  CASE
    WHEN trq.task_id IS NULL                                  THEN 'no_task_for_requirement'
    WHEN c.claim_id IS NULL                                   THEN 'no_claim_for_task'
    WHEN COUNT(ctr.test_nodeid) = 0                           THEN 'no_tests_declared'
    WHEN SUM(CASE WHEN tr.nodeid IS NULL THEN 1 ELSE 0 END) > 0 THEN 'test_not_run'
    WHEN SUM(CASE WHEN tr.outcome != 'covered' THEN 1 ELSE 0 END) > 0 THEN 'test_failed'
    ELSE 'covered'
  END as coverage_status
FROM requirements r
LEFT JOIN task_requirements trq ON r.req_id = trq.req_id
LEFT JOIN tasks t                ON trq.task_id = t.task_id
LEFT JOIN claims c               ON t.task_id = c.related_task
LEFT JOIN claim_test_refs ctr    ON c.claim_id = ctr.claim_id
LEFT JOIN test_results tr        ON ctr.test_nodeid = tr.nodeid
GROUP BY r.req_id
HAVING coverage_status != 'covered'
```

| 状态值 | 业务含义 | 缺口消息模板 |
|--------|----------|-------------|
| `no_task_for_requirement` | 需求没有关联任何开发任务 | `Requirement {req_id} has no task coverage.` |
| `no_claim_for_task` | 关联的任务未签发 Agent Claim | `Requirement {req_id} tasks have no claims.` |
| `no_tests_declared` | Claim 未声明测试用例 | `Requirement {req_id} claims declare no tests.` |
| `test_not_run` | Claim 声明的测试未执行（test_results 中无记录） | `Requirement {req_id} has tests that were not run.` |
| `test_failed` | 至少一个关联测试未通过 | `Requirement {req_id} has failed tests.` |
| `covered` | 完整覆盖（被 HAVING 过滤，不输出） | — |

**关键设计决策**：
- **不限优先级**：与 `check_ac_coverage` 不同，此查询不按 `priority` 过滤——检查所有需求。业务假设：每个需求都应有覆盖，不应因优先级而遗漏。
- **CASE WHEN 短路求值**：按覆盖链路的顺序逐级检查——先看有没有 Task，再看有没有 Claim，以此类推。停在第一个断点，确保缺口描述指向根本原因而非末端症状。
- **GROUP BY + HAVING**：按 `req_id` 聚合（一个需求可能关联多个 Task），HAVING 过滤掉完全覆盖的记录，只返回有问题的。

---

### 2. check_ac_coverage

**业务问题**：每个验收标准（AC）是否被任务承接 → 任务是否有 Claim → Claim 是否声明了测试 → 测试是否执行通过？**仅检查 MUST 优先级的任务或需求。**

**覆盖链路**：`acceptance_criteria → task_acs → tasks → claims → claim_test_refs → test_results`

```sql
SELECT ta.task_id, ac.ac_id,
  CASE
    WHEN ta.task_id IS NULL                                  THEN 'no_task_for_ac'
    WHEN c.claim_id IS NULL                                   THEN 'no_claim_for_task'
    WHEN COUNT(ctr.test_nodeid) = 0                           THEN 'no_tests_declared'
    WHEN SUM(CASE WHEN tr.nodeid IS NULL THEN 1 ELSE 0 END) > 0 THEN 'test_not_run'
    WHEN SUM(CASE WHEN tr.outcome != 'covered' THEN 1 ELSE 0 END) > 0 THEN 'test_failed'
    ELSE 'covered'
  END as coverage_status
FROM acceptance_criteria ac
LEFT JOIN requirements r     ON ac.req_id = r.req_id
LEFT JOIN task_acs ta        ON ac.ac_id = ta.ac_id
LEFT JOIN tasks t            ON ta.task_id = t.task_id
LEFT JOIN claims c           ON t.task_id = c.related_task
LEFT JOIN claim_test_refs ctr ON c.claim_id = ctr.claim_id
LEFT JOIN test_results tr    ON ctr.test_nodeid = tr.nodeid
WHERE t.priority = 'must'
   OR (r.priority = 'must' AND ac.is_testing_required = 1)
GROUP BY ta.task_id, ac.ac_id
HAVING coverage_status != 'covered'
```

| 状态值 | 业务含义 | 缺口消息模板 |
|--------|----------|-------------|
| `no_task_for_ac` | AC 没有关联任务 | `AC {ac_id} has no task coverage.` |
| `no_claim_for_task` | 关联的任务无 Claim | `AC {ac_id} (task {task_id}) has no claims.` |
| `no_tests_declared` | Claim 未声明测试 | `AC {ac_id} (task {task_id}) declares no tests.` |
| `test_not_run` | 测试未执行 | `AC {ac_id} (task {task_id}) has tests that were not run.` |
| `test_failed` | 测试未通过 | `AC {ac_id} (task {task_id}) has failed tests.` |

**与 check_requirement_coverage 的关键差异**：

| 维度 | check_requirement_coverage | check_ac_coverage |
|------|---------------------------|-------------------|
| 起点表 | `requirements` | `acceptance_criteria` |
| 优先级过滤 | 无（全量） | MUST（task.priority 或 req.priority） |
| GROUP BY | `req_id` | `task_id, ac_id`（粒度更细） |
| 缺口 item_type | `requirement` | `ac` |
| 缺口含 task_id | 否 | 是 |

**优先级过滤逻辑**：`WHERE t.priority = 'must' OR (r.priority = 'must' AND ac.is_testing_required = 1)`
- 任务本身是 must → 检查
- 任务的父需求是 must **且** AC 标记为需要测试 → 检查
- 双重条件确保非测试类 AC（如文档、设计评审）不会因优先级被误报

---

### 3. check_claim_evidence

**业务问题**：每个 Agent Claim 是否关联了有效任务 → 任务是否完成 → Claim 是否声明了测试 → 测试是否都有结果 → 测试是否全部通过？

**覆盖链路**：`claims → tasks + claims → claim_test_refs → test_results`

```sql
SELECT c.claim_id,
  CASE
    WHEN t.task_id IS NULL                                      THEN 'task_missing'
    WHEN t.status != 'done'                                     THEN 'task_not_done'
    WHEN COUNT(ctr.test_nodeid) = 0                             THEN 'no_tests'
    WHEN SUM(CASE WHEN tr.nodeid IS NULL THEN 1 ELSE 0 END) > 0 THEN 'test_missing'
    WHEN SUM(CASE WHEN tr.outcome = 'covered' THEN 1 ELSE 0 END) < COUNT(ctr.test_nodeid)
                                                                THEN 'test_failed'
    ELSE 'covered'
  END as verification_status
FROM claims c
LEFT JOIN tasks t            ON c.related_task = t.task_id
LEFT JOIN claim_test_refs ctr ON c.claim_id = ctr.claim_id
LEFT JOIN test_results tr    ON ctr.test_nodeid = tr.nodeid
GROUP BY c.claim_id
HAVING verification_status != 'covered'
```

| 状态值 | 业务含义 | 缺口消息模板 |
|--------|----------|-------------|
| `task_missing` | Claim 关联的 Task 不存在（数据一致性错误） | `Claim {claim_id} references missing task.` |
| `task_not_done` | Task 状态不是 done | `Claim {claim_id} task is not done.` |
| `no_tests` | Claim 未声明任何测试用例 | `Claim {claim_id} declares no tests.` |
| `test_missing` | 声明的测试在 test_results 中无记录（未执行） | `Claim {claim_id} has missing tests.` |
| `test_failed` | 至少一个测试未通过 | `Claim {claim_id} has failed tests.` |

**与两个覆盖查询的差异**：
- 起点是 `claims` 表而非 `requirements`/`acceptance_criteria`
- 检查 Task 是否 **done**（覆盖查询不关心 Task 状态）
- `test_failed` 判定逻辑不同：用 `< COUNT()` 而非 `SUM(...) > 0`——语义等价，实现形式不同

---

## 二、辅助诊断查询

### 4. check_dangling_claims

**业务问题**：哪些 Claim 指向了不存在的 Task？（数据一致性问题——Task 被删除但 Claim 未更新）

```sql
SELECT c.claim_id, c.related_task
FROM claims c
LEFT JOIN tasks t ON c.related_task = t.task_id
WHERE t.task_id IS NULL
```

| 输出字段 | 含义 |
|----------|------|
| `claim_id` | 悬空的 Claim ID |
| `related_task` | 指向的不存在的 Task ID |

**下游用途**：写入 `analysis_details.dangling_claims`，在 Dashboard 中展示为数据一致性警告。

---

### 5. check_coverage_violations

**业务问题**：哪些源码文件的覆盖率被标记为违规（status = 'violated'）？

```sql
SELECT source_path, percent_covered
FROM coverage_reports
WHERE status = 'violated'
```

| 输出字段 | 含义 |
|----------|------|
| `source_path` | 源码文件路径 |
| `percent_covered` | 覆盖率百分比 |

> **判定链**：覆盖率阈值比较在 EvidenceBuilder 中完成——低于阈值的记录 status 被设为 `'violated'`。此查询只做筛选，不做阈值判断。

**下游用途**：写入 `analysis_details.cov_violations`，供 Dashboard 展示覆盖率违规清单。

---

### 6. check_invalid_task_requirements

**业务问题**：`task_requirements` 关联表中是否存在引用了不存在 Requirement 的记录？（数据完整性校验）

```sql
SELECT tr.task_id, tr.req_id
FROM task_requirements tr
LEFT JOIN requirements r ON tr.req_id = r.req_id
WHERE r.req_id IS NULL
```

---

### 7. check_invalid_task_acs

**业务问题**：`task_acs` 关联表中是否存在引用了不存在 AC 的记录？

```sql
SELECT ta.task_id, ta.ac_id
FROM task_acs ta
LEFT JOIN acceptance_criteria ac ON ta.ac_id = ac.ac_id
WHERE ac.ac_id IS NULL
```

---

### 8. check_invalid_task_modules

**业务问题**：`task_modules` 关联表中是否存在引用了不存在 Module 的记录？

```sql
SELECT tm.task_id, tm.module_id
FROM task_modules tm
LEFT JOIN arch_modules am ON tm.module_id = am.module_id
WHERE am.module_id IS NULL
```

---

### 9. check_invalid_task_constraints

**业务问题**：`task_constraints` 关联表中是否存在引用了不存在 Constraint 的记录？

```sql
SELECT tc.task_id, tc.constraint_id
FROM task_constraints tc
LEFT JOIN arch_constraints ac ON tc.constraint_id = ac.constraint_id
WHERE ac.constraint_id IS NULL
```

---

### 10. check_invalid_ac_parent

**业务问题**：Task 关联的 AC，其父 Requirement 是否也在该 Task 的关联需求中？（跨域一致性校验）

```sql
SELECT ta.task_id, ta.ac_id, ac.req_id
FROM task_acs ta
JOIN acceptance_criteria ac ON ta.ac_id = ac.ac_id
LEFT JOIN task_requirements tr ON ta.task_id = tr.task_id AND ac.req_id = tr.req_id
WHERE tr.req_id IS NULL
```

| 输出字段 | 含义 |
|----------|------|
| `task_id` | 存在不一致的 Task |
| `ac_id` | 问题 AC |
| `parent_req_id` | AC 的实际父需求（不在 Task 的关联需求中） |

**场景示例**：Task 关联了 AC-001（父需求为 REQ-A），但 Task 只关联了 REQ-B。这意味着 AC-001 的通过不能证明 REQ-B 的覆盖——关联关系存在逻辑矛盾。

**实现技巧**：LEFT JOIN 的 ON 条件中同时匹配 `task_id` 和 `req_id`，找出"Task 关联了 AC 但未关联该 AC 的父需求"的记录。

---

### 11. check_isolated_tasks

**业务问题**：哪些任务是孤立的——没有关联 Requirement 或 AC？

根据 `ctx.config.id_rules.all_tasks_must_link_requirements_and_acceptance_criteria` 有两种判定模式：

**Strict 模式**（`true`）——缺少 REQ **或** 缺少 AC 即视为孤立：

```sql
SELECT t.task_id,
  CASE
    WHEN COUNT(tr.req_id) = 0 THEN 'missing_req'
    WHEN COUNT(ta.ac_id) = 0 THEN 'missing_ac'
  END as reason
FROM tasks t
LEFT JOIN task_requirements tr ON t.task_id = tr.task_id
LEFT JOIN task_acs ta ON t.task_id = ta.task_id
GROUP BY t.task_id
HAVING COUNT(tr.req_id) = 0 OR COUNT(ta.ac_id) = 0
```

**宽松模式**（`false`，默认）——同时缺少 REQ **且** 缺少 AC 才视为孤立：

```sql
SELECT t.task_id, 'isolated' as reason
FROM tasks t
LEFT JOIN task_requirements tr ON t.task_id = tr.task_id
LEFT JOIN task_acs ta ON t.task_id = ta.task_id
GROUP BY t.task_id
HAVING COUNT(tr.req_id) = 0 AND COUNT(ta.ac_id) = 0
```

| reason 值 | 含义 |
|-----------|------|
| `missing_req` | 有 AC 但无 REQ（仅 strict 模式） |
| `missing_ac` | 有 REQ 但无 AC（仅 strict 模式） |
| `isolated` | 既无 REQ 也无 AC（宽松模式） |

**下游用途**：写入 `analysis_details.isolated_tasks`，供 Dashboard 展示和阶段 8 报告使用。**不**转换为缺口——孤立任务是数据质量警示，不是覆盖链路断点。

---

### 12. check_architectural_orphans

**业务问题**：哪些未完成的任务没有归属到任何架构模块？

```sql
SELECT t.task_id, 'architectural_orphan' as reason
FROM tasks t
LEFT JOIN task_modules tm ON t.task_id = tm.task_id
WHERE t.status != 'done'
GROUP BY t.task_id
HAVING COUNT(tm.module_id) = 0
```

| 输出字段 | 含义 |
|----------|------|
| `task_id` | 孤儿任务 ID |
| `reason` | 固定为 `'architectural_orphan'` |

**与 check_isolated_tasks 的差异**：孤立任务关注 REQ/AC 关联，架构孤儿关注 Module 关联——两者是正交维度。

**特殊处理**：架构孤儿的结果**同时**写入两处：
- 转换为缺口（`item_type: "task"`）并入 `merged_gaps`——参与门禁判定
- 写入 `analysis_details.arch_orphans`——供 Dashboard 展示

---

## 三、辅助查询（非 check_*，供 Dashboard 使用）

### 13. query_related_code

**业务问题**：给定一个 AC ID，通过 Task → Claim → Code 链路找到关联的源码文件。

```sql
SELECT DISTINCT ccr.code_path
FROM task_acs ta
JOIN claims c          ON c.related_task = ta.task_id
JOIN claim_code_refs ccr ON ccr.claim_id = c.claim_id
WHERE ta.ac_id = ?
```

**返回**：文件系统中实际存在的路径，最多 3 个（Python 层过滤）。用于 Dashboard 的"相关代码"展示。

---

### 14. query_existing_tests

**业务问题**：给定一个 AC ID，找到已有的测试用例。

```sql
SELECT DISTINCT ctr.test_nodeid
FROM task_acs ta
JOIN claims c          ON c.related_task = ta.task_id
JOIN claim_test_refs ctr ON ctr.claim_id = c.claim_id
WHERE ta.ac_id = ?
```

**返回**：测试 nodeid 列表，最多 2 个（Python 层过滤）。用于 Dashboard 展示已有测试覆盖。

---

## 四、全链路视图

### 15. get_full_chain

**业务问题**：从需求到测试/覆盖率的完整追溯视图——用于全量导出和调试。

```sql
SELECT
    r.req_id, r.title, r.priority, r.category,
    ac.ac_id, ac.title, ac.is_testing_required,
    t.task_id, t.priority, t.status,
    c.claim_id,
    ctr.test_nodeid, tr.outcome,
    ccr.code_path, cov.percent_covered
FROM requirements r
LEFT JOIN acceptance_criteria ac ON r.req_id = ac.req_id
LEFT JOIN task_requirements trq  ON r.req_id = trq.req_id
LEFT JOIN tasks t               ON trq.task_id = t.task_id
LEFT JOIN claims c              ON t.task_id = c.related_task
LEFT JOIN claim_test_refs ctr   ON c.claim_id = ctr.claim_id
LEFT JOIN test_results tr       ON ctr.test_nodeid = tr.nodeid
LEFT JOIN claim_code_refs ccr   ON c.claim_id = ccr.claim_id
LEFT JOIN coverage_reports cov  ON ccr.code_path = cov.source_path
```

**输出字段**（16 列）：

| 字段 | 来源表 | 含义 |
|------|--------|------|
| req_id, req_title, req_priority, req_category | requirements | 需求基本信息 |
| ac_id, ac_title, is_testing_required | acceptance_criteria | AC 信息 |
| task_id, task_priority, task_status | tasks | 任务信息 |
| claim_id | claims | Claim 标识 |
| test_nodeid, test_outcome | claim_test_refs + test_results | 测试用例及结果 |
| code_path, percent_covered | claim_code_refs + coverage_reports | 代码路径及覆盖率 |

**特点**：
- 全 LEFT JOIN——不做任何过滤，包含所有记录（含 NULL 链路）
- 一次查询获取从需求到覆盖率的完整路径
- 可能导致大量行（笛卡尔积膨胀），当前主要供调试和全量导出使用

---

## 查询间数据流

```
                 ┌──────────────────────┐
                 │   check_requirement   │──→ req_gaps ──┐
                 │   _coverage           │               │
                 └──────────────────────┘               │
                                                        │
                 ┌──────────────────────┐               │    ┌─────────────────┐
                 │   check_ac_coverage  │──→ ac_gaps ───┼───→│ _db_result_to_  │──→ merged_gaps
                 └──────────────────────┘               │    │ _gaps()         │
                                                        │    └─────────────────┘
                 ┌──────────────────────┐               │
                 │   check_claim        │──→ claim_gaps ─┘
                 │   _evidence          │
                 └──────────────────────┘

                 ┌──────────────────────┐
                 │   check_architectural │──→ 直接拼入 merged_gaps（item_type: task）
                 │   _orphans            │
                 └──────────────────────┘

                 ┌──────────────────────────────────────────────────┐
                 │  9 个辅助 check_* ──→ analysis_details            │
                 │  (dangling, coverage_violations, 4 invalid_*,    │
                 │   invalid_ac_parent, isolated, arch_orphans)     │
                 └──────────────────────────────────────────────────┘
                                     │
                                     ▼
                            ┌─────────────────┐
                            │  MergeGateEngine │ (阶段 8)
                            │  .evaluate()     │
                            └─────────────────┘
```

---

## 数据库索引说明

当前为 SQLite 内存数据库，未显式创建索引。但以下列作为 JOIN 条件频繁使用，若未来切换到持久化数据库需考虑索引：

| 列 | 出现频率 | 建议 |
|----|---------|------|
| `claims.related_task` | 高（4 个查询） | 建索引 |
| `task_requirements.task_id` / `task_requirements.req_id` | 高 | 建复合索引 |
| `task_acs.task_id` / `task_acs.ac_id` | 高 | 建复合索引 |
| `claim_test_refs.claim_id` | 高（3 个查询） | 建索引 |
| `acceptance_criteria.req_id` | 中 | 建索引 |

内存数据库场景下全表扫描开销可忽略，以上仅为持久化迁移参考。
