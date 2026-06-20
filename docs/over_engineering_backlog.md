# 过度设计待优化清单

> 本文档记录逐模块审核中发现的过度设计项，待审查 domain 层时一并处理。
> 本文档是自包含的——新 session 只需读取此文档即可了解全部背景和下一步工作。

---

## 工作计划（三步走）

### 第一步：Pipeline 重设计（设计阶段，不写代码）

**目标**：定义 pipeline.py 的正确架构——调度顺序、数据传递契约、模块接口。

**需要确认的关键决策**：
1. analyzers 是否直接查 DB？（决定是否需要 evidence_dicts 中间层）
2. check_* 函数留在 db.py 还是迁到 domain？（决定 pipeline 如何调用关系校验）
3. evidence_builder 的职责边界？（合并逻辑 vs 完整构建流程）
4. analysis.py 是否合并到 pipeline.py？（消除不必要的间接层）
5. unified context 的 tool_evidence 后绑定如何处理？

**产出**：pipeline 重构设计文档（调度顺序、数据契约、模块接口定义）

### 第二步：Pipeline 重构（建立正确基线）

**目标**：按设计文档重构 pipeline.py，清除所有旧代码，建立正确的调度模式。

**关键原则**：
- pipeline.py 只做调度（决定顺序和数据流），不包含业务逻辑
- 所有 DB 操作由 pipeline 调用 db.py，子模块只接收 conn 或数据参数
- 子模块不直接调 db.py（消除自治问题）

**产出**：pipeline.py 重构完成，所有旧代码清除

**验证**：现有测试通过 + 新增契约测试

### 第三步：逐个 Domain 对齐

**目标**：每个 domain 模块按照 pipeline 定义的接口进行对齐。

**每个模块的处理流程**：
1. 审查内部逻辑（用 vt-module-review skill 的 7 维度审核）
2. 对齐 pipeline 定义的接口（输入→输出→DB 交互）
3. 删除子模块自治的 DB 调用
4. 验证测试通过

**执行顺序**（按依赖关系从底层到上层）：
```
domain/context.py → domain/raw_input_loader.py → domain/claim_loader.py →
domain/task_loader.py → domain/prd_parser.py → domain/tool_evidence_adapter.py →
domain/evidence_builder.py → domain/ghost_code_reconciler.py →
domain/merge_gate_engine.py → domain/risk_advisor.py →
domain/architecture_compliance_checker.py → analyzers/（3 个分析器）
```

**产出**：每个模块的审核报告 + 接口对齐

---

## 模块调研汇总

> 以下是对 analyze 阶段所有模块的调研结果，用于 pipeline 重设计时参考。

### 已调研的 14 个模块

| 模块 | 包 | 行数 | 调 DB？ | 状态 | 核心发现 |
|------|---|------|:------:|------|---------|
| pipeline.py | cli/analyze | 510 | ❌ | ⚠️ | 混入 ~250 行业务逻辑；子模块自治 |
| db.py | infra | 571 | — | ✅ | 6 个 check_* 函数（3 个活跃，3 个死代码待定） |
| enums.py | infra | ~50 | ❌ | ✅ | 已清理 Severity 死代码 |
| context.py | domain | 40 | ❌ | ✅ | 纯数据容器，tool_evidence 后绑定 |
| raw_input_loader.py | domain | ~180 | ❌ | ✅ | 纯文件读取，契约清晰 |
| claim_loader.py | domain | ~285 | ❌ | 待审 | 多文件 Claim 加载 |
| task_loader.py | domain | ~374 | ❌ | 待审 | 任务加载与校验 |
| prd_parser.py | domain | ~386 | ❌ | 待审 | PRD 解析 |
| tool_evidence_adapter.py | domain | 1042 | ❌ | ✅ | 工具执行引擎，契约清晰 |
| evidence_builder.py | domain | ~75 | ✅ 调 5 个 | ⚠️ | 内部 5 步自治，返回值被丢弃 |
| merge_gate_engine.py | domain | 867 | ✅ 调 3 个 | ⚠️ | 内部直接调 db.check_* |
| ghost_code_reconciler.py | domain | 284 | ✅ 调 3 个 | ⚠️ | 通过 gates.py 间接调用；与 MergeGateEngine 重复调 check_ghost_code |
| risk_advisor.py | domain | 220 | ❌ | ✅ | 纯内存转换，契约清晰 |
| architecture_compliance_checker.py | domain | 885 | ❌ | ⚠️ | 7 类检查混在一个方法中，体量过大 |

### 未调研的模块（待第三步逐个审核）

cli/ 子模块：common.py、gates.py、tools.py、analysis.py、actions.py、helpers.py、formatting.py、output.py、reports.py
domain/ 子模块：prd_arch_validator.py、traceability_report_builder.py、dashboard_renderer.py、reflection_prompts.py、architecture_change_proposal.py
infra/ 子模块：validation/、operational_logger.py、hint_loader.py、tool_resolver.py、governance.py、git_utils.py

---

## 架构决策待讨论（高优先级）

## 架构决策待讨论（高优先级）

| # | 问题 | 涉及模块 | 说明 |
|---|------|---------|------|
| A1 | vt analyze 的定位模糊 | gates.py, pipeline.py, finalize.py | vt analyze 同时承担"设计验证"（Gate 1/1b/1c）和"开发检查"（Gate 2）两个角色。Gate 1/1b/1c 检查的是设计基线完整性，应在 vt finalize 时执行；Gate 2（代码-声明对齐）是输入前置条件，应在加载 Claims 时校验。需要重新定义 finalize 和 analyze 的职责边界。 |
| A2 | Gate 2 是前置条件而非门禁 | gates.py, common.py | Agent 提交代码时必须有 Claim，这是基本契约（前置条件），不是可选的检查点。应将 Claim 存在性校验移到 _load_context() 中，而非在门禁阶段检测。 |
| A3 | 子模块绕过 pipeline 直接自治 | evidence_builder.py, merge_gate_engine.py, ghost_code_reconciler.py, tools.py | pipeline.py 名义上是调度层，但子模块内部的操作顺序（如 EvidenceBuilder 的 load→purge→upsert→persist、GhostCodeReconciler 的 load+check）是硬编码在子模块中的，pipeline.py 无法控制。如果 pipeline.py 是调度层，它应该决定"什么时候做什么"，而不是让子模块自治。 |

---

## pipeline.py（调度层）

| # | 位置 | 业务逻辑 | SQL 可替代？ | 应在 domain 层？ | 说明 |
|---|------|---------|:----------:|:--------------:|------|
| 1 | evidence_dicts 构建（L447-545） | 状态映射 + 数据翻译 | ✅ | ✅ | `status_map = {"todo": MISSING, ...}` 等映射规则可用 SQL CASE WHEN 替代，100 行 Python 代码可缩减为分析器直接查询数据库 |
| 2 | `_classify_staged_files`（L48-71） | 文件分类（src/ vs tests/） | ✅ | ✅ | staged_files 已在数据库 staged_files 表中，`WHERE file_path LIKE 'src/%'` 一行 SQL 可替代 |
| 3 | staged_items 构建（L188-211） | Claim→Task→AC→REQ 关联查询 | ✅ | ✅ | Python 循环匹配可用 SQL JOIN 替代，如 `SELECT DISTINCT t.task_id FROM claims c JOIN tasks t ON c.related_task = t.task_id` |
| 4 | `_auto_generate_claim_from_staged`（L76-150） | Claim 自动生成（分类+编号+写入） | 部分 | ✅ | 75 行业务逻辑，文件分类可用 SQL，顺序编号和写入应在 domain 层 |
| 5 | evidence_id 顺序编号（L533-534） | `EVIDENCE-VT-{idx+1:03d}` | 无意义 | 应删除 | 编号只用于报告展示标签，增删测试会导致编号漂移，应用 source_path/nodeid 替代 |

### 根因分析

pipeline.py 作为调度层，应只负责"按顺序调用谁"。当前 508 行中约 250 行是业务逻辑（evidence_dicts 构建、文件分类、关联查询、Claim 生成），只有约 250 行是真正的调度代码。

**第一性原则**：如果分析器能直接查询数据库，pipeline.py 不需要构建中间数据结构（evidence_dicts）。

**剃刀原则**：SQL JOIN 能完成的关联查询，不需要用 Python 循环手动拼装。

---

## enums.py（基础设施层）

| # | 位置 | 问题 | 优先级 | 说明 |
|---|------|------|--------|------|
| 1 | `Severity` 枚举（已删除） | 未使用的死代码 | ✅ 已修复 | 代码库用字符串直接使用，枚举从未被 import |

---

## db.py（基础设施层）

| # | 位置 | 问题 | 优先级 | 说明 |
|---|------|------|--------|------|
| 1 | `purge_stale_cache` 调用方 | target_files 传入 nodeid 而非文件路径 | ✅ 已修复 | evidence_builder.py 已修复，提取文件路径再传入 |
| 2 | 覆盖率永不重新测量 | `_measure_source_coverage()` 无参数 | ✅ 已修复 | tool_evidence_adapter.py 已连接 coverage_baseline_path |
| 3 | `export_test_results` / `export_coverage_reports` | 未标记为内部函数 | ✅ 已修复 | 已加 `_` 前缀 |
| 4 | check_* 函数归属 | 业务查询接口在 db.py 中 | 待定 | 暂留 db.py，审查 domain 层时评估是否迁移 |

---

## 主要优化方向（审查 domain 层时评估）

1. **分析器直接查询数据库**：消除 evidence_dicts 中间层，分析器从"消费 Python dict"变为"查询 SQLite"
2. **状态映射 SQL 化**：`status_map` 用 SQL CASE WHEN 替代 Python dict
3. **关联查询 SQL 化**：Claim→Task→AC→REQ 的 Python 循环匹配改为 SQL JOIN
4. **evidence_id 重构**：删除顺序编号，用 source_path/nodeid 作为天然标识
5. **pipeline.py 瘦身**：将 ~250 行业务逻辑迁移到 domain 层，保留 ~250 行纯调度代码

---

## Pipeline 模块差距分析（2026-06-19 调研）

### 正确的 Pipeline 设计

```
pipeline.py 的唯一职责：决定数据从哪来、经过哪些处理、到哪去
  - 调用 db.py（唯一的 DB 操作者）
  - 传递 conn 给子模块（子模块不直接调 db.py）
  - 子模块只做一件事：接收数据 → 处理 → 返回结果
```

### 各模块实际契约 vs 正确设计

| 模块 | 实际输入 | 实际输出 | 直接调 DB？ | 正确设计 | 差距 |
|------|---------|---------|:----------:|---------|------|
| raw_input_loader | project_root | RawInputManifest | ❌ | 一致 | 无 |
| tool_evidence_adapter | Claims 的 refs | List[ToolEvidenceCandidate] | ❌ | 一致 | 无 |
| evidence_builder | conn + tool_evidence | dict（被丢弃） | ✅ 调 5 个 db 函数 | conn + tool_evidence → evidence_meta | 内部 5 步自治，返回值被丢弃 |
| analyzers | evidence_list（List[dict]） | gaps + risks | ❌ | conn + prd + claims → gaps + risks | 需要 100 行 evidence_dicts 中间层 |
| merge_gate_engine | gaps + risks + conn | gate_decision | ✅ 调 3 个 check 函数 | conn + gaps + risks → gate_decision | 内部直接调 db.py |

### 核心问题

**问题 1：evidence_builder 内部自治**
- 当前：load_initial_cache → purge_stale_cache → upsert → persist_evidences（5 步硬编码在子模块中）
- 正确：pipeline 调用每个 db 函数，evidence_builder 只做合并逻辑
- 影响：pipeline 无法控制证据构建的顺序

**问题 2：analyzers 需要 evidence_dicts 中间层**
- 当前：pipeline.py 用 ~100 行 Python 构建 evidence_dicts（Task/Claim/Code/Tool 的翻译）
- 正确：analyzers 直接查询 DB，不需要中间层
- 影响：pipeline 承担了不属于调度的业务逻辑

**问题 3：merge_gate_engine 直接调 db.py**
- 当前：engine 内部调用 check_ghost_code / check_ac_coverage / check_coverage_violations
- 正确：pipeline 调用 check_* 函数，将结果传给 engine
- 影响：engine 自行决定查询哪些表，pipeline 无法控制

**问题 4：evidence_builder 返回值被丢弃**
- 当前：`evidence_builder.build(ctx)` 的返回值（dict with paths）未被使用
- 正确：build() 应返回 evidence_meta（供分析器使用），而非文件路径
- 影响：evidence_meta 由 pipeline 手动构建（与 build() 返回值无关）

### 修复方向

1. **pipeline 统一调用 db.py**：所有 DB 操作（load_*、check_*、upsert_*）由 pipeline 调用，子模块只接收 conn 或数据参数
2. **analyzers 直接查 DB**：消除 evidence_dicts 中间层，analyzers 从"消费 Python dict"变为"查询 SQLite"
3. **evidence_builder 重构**：只做"合并逻辑"（接收 tool_evidence + 历史缓存，返回合并后的 evidence_meta），不直接调 db.py
4. **merge_gate_engine 重构**：接收 pipeline 传入的 check_* 查询结果，不自行调 db.py

---

## 第二轮模块调研汇总（2026-06-19）

### 模块状态总览

| 模块 | 行数 | 调 DB？ | 状态 | 核心问题 |
|------|------|:------:|------|---------|
| domain/context.py | 40 | ❌ | ✅ 设计良好 | tool_evidence 后绑定（创建时为空，pipeline 中途赋值） |
| cli/common.py | 235 | ❌ | ⚠️ 有一个泄漏 | `_determine_affected_items()` 含业务逻辑（Claim→Task→REQ 关联），应迁到 domain 层 |
| cli/analyze/analysis.py | 154 | ❌ | ⚠️ 职责混合 | 60% 调度 + 40% 业务逻辑（gap 合并、staleness 标记） |
| domain/risk_advisor.py | 220 | ❌ | ✅ 设计良好 | 纯内存转换，契约清晰 |
| domain/architecture_compliance_checker.py | 885 | ❌ | ⚠️ 体量大 | 7 类检查，独立于 gate 系统，通过 analysis.py 间接调用 |
| domain/ghost_code_reconciler.py | 284 | ✅ 调 3 个 | ⚠️ 自治 | 通过 gates.py 间接调用；MergeGateEngine 也直接调 check_ghost_code（重复） |

### 新发现的问题

| # | 问题 | 涉及模块 | 说明 |
|---|------|---------|------|
| A4 | context.py 的 tool_evidence 后绑定 | context.py, pipeline.py | UnifiedContext 创建时 tool_evidence 为空，pipeline 中途赋值。对象处于"半构造"状态。可考虑将 tool_evidence 作为独立返回值或拆分为两阶段构造 |
| A5 | common.py 的 _determine_affected_items 泄漏 | common.py | 此函数编码了 Claim→Task→REQ 的追溯链关系，是业务逻辑而非 CLI 辅助。应迁到 domain 层（如新建 impact_analyzer 模块） |
| A6 | analysis.py 的 staleness 逻辑与 pipeline 重复 | analysis.py, pipeline.py | analysis.py 的 _run_analyzers() 内部标记 stale（lines 99-124），pipeline.py 的 _run_analysis_phase() 也过滤 stale（line 182-183）。同一关注点分散在两个模块中 |
| A7 | ghost_code_reconciler 与 MergeGateEngine 重复调 check_ghost_code | ghost_code_reconciler.py, merge_gate_engine.py | reconciler 在 Gate 2 阶段调 check_ghost_code，MergeGateEngine 在 Gate 3 阶段又调一次。同一个 SQL 查询被执行了两次 |
| A8 | architecture_compliance_checker 体量过大 | architecture_compliance_checker.py | 885 行，7 类检查混在一个方法中。可拆分为独立的 checker 子模块（如 import_checker、file_checker、gate_checker） |
| A9 | analysis.py 与 pipeline.py 职责重叠 | analysis.py, pipeline.py | analysis.py 是 pipeline.py 的"子调度器"（调度 3 个分析器 + ComplianceChecker + RiskAdvisor），但只调度一个 stage，独立成模块的必要性不足。且 staleness 逻辑分散在两个文件中（analysis.py 标记 + pipeline.py 过滤）。建议合并到 pipeline.py，消除不必要的间接层 |

### 模块依赖关系（修正后）

```
pipeline.py（调度层）
  │
  ├── common._load_context()     → RawInputLoader + PrdParser + TaskLoader + ClaimLoader
  ├── db.init_in_memory_db()     → 创建 DB
  ├── db.load_tasks/load_claims  → 灌入数据
  ├── tools._execute_tools()     → ToolExecutionEngine
  ├── EvidenceBuilder.build()    → ⚠️ 直接调 db.py（应由 pipeline 调度）
  ├── analysis._run_analyzers()  → 3 个 Analyzer + ComplianceChecker + RiskAdvisor
  │     └── ⚠️ 内部标记 staleness（应移到 pipeline）
  ├── MergeGateEngine.evaluate() → ⚠️ 直接调 db.check_*（应由 pipeline 调度）
  └── reports + output           → 生成报告和 Dashboard

gates.py（门禁层）
  ├── _gate1_constraints_hash    → 读 ctx.manifest 的 hash
  ├── _gate1b_prd_drift          → 读 ctx.manifest 的 hash
  ├── _gate1c_mapping            → 调 prd_arch_validator
  └── _gate2_code_claim_alignment → 创建 GhostCodeReconciler（⚠️ 与 MergeGateEngine 重复调 check_ghost_code）
```

### pipeline 重设计时需考虑的约束

1. **context.py 的 tool_evidence 后绑定**：如果保持 UnifiedContext 为单一数据载体，tool_evidence 的赋值时机需要明确（在哪个阶段赋值，由谁赋值）
2. **_determine_affected_items 的归属**：此函数被 pipeline 和 analysis.py 共同使用，迁移时需确定新的归属模块
3. **staleness 逻辑的统一**：analysis.py 和 pipeline.py 的 stale 处理需要合并到一处
4. **ghost_code 的双重调用**：Gate 2 和 Gate 3 都调 check_ghost_code，需要决定是共享结果还是分别调用
5. **compliance_checker 的体量**：885 行的单一方法是否需要拆分，取决于 pipeline 重设计后的调用方式
