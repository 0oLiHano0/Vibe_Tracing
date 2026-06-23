# 重构设计文档

> 阅读对象：AI coding agent。按需跳转，不必顺序阅读。

---

## 1. 现状与目标

### 1.1 核心问题

| # | 问题 | 模块 | 状态 |
|---|------|------|------|
| P1 | pipeline.py 混入 ~250 行业务逻辑（evidence_dicts、文件分类、关联查询） | pipeline.py | ✅ 已修复 |
| P2 | evidence_builder 内部 5 步自治，pipeline 无法控制顺序 | evidence_builder.py | ✅ 已修复 |
| P3 | merge_gate_engine 直接调 db.check_*，绕过 pipeline | merge_gate_engine.py | ✅ 已修复 |
| P4 | ghost_code_reconciler 与 MergeGateEngine 重复调 check_ghost_code | 两者 | ✅ 已修复 |
| P5 | context.py 的 tool_evidence 后绑定，对象"半构造" | context.py | ✅ 已修复 |
| P6 | analysis.py 与 pipeline.py 职责重叠 | 两者 | ✅ 已修复 |
| P7 | Gate 1/1b/1c 属于 finalize 职责却在 analyze 中执行 | gates.py | ✅ 已修复 |
| P8 | analyzers 消费 Python dict 而非直接查 DB | analyzers/ | ✅ 已修复 |

### 1.2 已修复项

| 项 | 说明 |
|----|------|
| db.py 拆分为 infra/db/ 子包 | schema.py, loaders.py, queries.py, exports.py |
| purge_stale_cache 传 nodeid | 已改为传文件路径 |
| export_* 未标内部函数 | 已加 `_` 前缀 |
| _measure_source_coverage 无参数 | 已连接 coverage_baseline_path |
| Severity 枚举死代码 | 已删除 |
| _classify_staged_files | 已删除 |
| _auto_generate_claim_from_staged | 已删除 |

### 1.3 设计原则

| 原则 | 含义 |
|------|------|
| pipeline 是调度层 | 只负责"按顺序调用谁"，不含业务逻辑 |
| db.py 是唯一查询层 | 所有 SQL 查询由 pipeline 调用 db.check_* |
| 子模块不直接调 db | 子模块接收数据参数，返回处理结果 |
| 对象要么构造完成，要么不构造 | 消除 UnifiedContext 的"半构造"状态 |

---

## 2. 五项设计决策

### 决策 1：分析器直接查询数据库

analyzers 从"消费 Python dict"变为"查询 SQLite"。

- **删除**：pipeline.py 中 ~100 行 evidence_dicts 构建
- **删除**：`EVIDENCE-VT-{idx}` 顺序编号（用 source_path/nodeid 替代）
- **替代**：状态映射用 SQL CASE WHEN

### 决策 2：check_* 函数留在 db.py

3 个活跃函数（`check_ac_coverage`、`check_coverage_violations`、`check_ghost_code`）+ 3 个保留函数（`check_dangling_claims`、`check_test_dead_links`、`check_active_task_coverage`）均留在 `infra/db/queries.py`。

### 决策 3：evidence_builder 只做"证据合并"

- `build()` 拆为 `merge()` + `apply()` + `persist()`
- `merge()` 纯数据处理，不需要 conn
- `apply()` 需要 conn，内部处理 purge + upsert 路由
- `persist()` 仅导出 JSON，不依赖 conn

### 决策 4：analysis.py 合并到 pipeline.py

- 删除 analysis.py
- 调度逻辑 → pipeline.py
- staleness 标记 → 新建 `domain/staleness_tracker.py`
- gap 合并逻辑 → pipeline.py（纯数据合并）

### 决策 5：tool_evidence 作为独立返回值

- 从 UnifiedContext 中移除 `tool_evidence` 字段
- `_execute_tools()` 返回 `List[ToolEvidenceCandidate]`
- tool_evidence 作为 pipeline 局部变量传递

---

## 3. 目标流水线（12 阶段）

```
run_analyze(project_root, ...)
│
├── Logger 初始化（异常守卫）
│
├── 阶段 1：加载输入
│   调用：_load_context(project_root)
│   输出：ctx: UnifiedContext（不含 tool_evidence）
│
├── 阶段 2：Claim 覆盖检查（前置条件）
│   调用：_check_claim_coverage(ctx, project_root, is_pre_commit, staged_files)
│   输出：exit_code 或 None
│   说明：Gate 1/1b/1c 已移除（属于 finalize）。Gate 2 提前为前置条件。
│
├── 阶段 3：创建数据库
│   调用：init_in_memory_db() → conn
│
├── 阶段 4：执行工具
│   调用：tool_evidence = _execute_tools(ctx)
│   输出：List[ToolEvidenceCandidate]（局部变量）
│
├── 阶段 5：灌入基础数据
│   调用：load_prd(conn, ctx.prd)
│         load_tasks(conn, ctx.task_result)
│         load_claims(conn, ctx.claims_list)
│
├── 阶段 6：构建证据（domain 自治）
│   调用：builder = EvidenceBuilder(project_root)
│         merge_result = builder.merge(tool_evidence)
│         builder.apply(conn, merge_result)
│         evidence_meta = builder.persist(output_dir)
│
├── 阶段 7：运行分析（db.py 唯一查询层）
│   调用：req_coverage  = db.check_requirement_coverage(conn)
│         ac_coverage   = db.check_ac_coverage(conn)
│         claim_analysis = db.check_claim_evidence(conn)
│         compliance_res = ArchitectureComplianceChecker().check(conn, constraints, human_decisions)
│
├── 阶段 8：提取 gaps + 生成 risks + staleness 标记
│   调用：req_gaps/claim_gaps/ac_gaps = extract_gaps(...)
│         merged_gaps = merge_gaps(...)
│         risks = RiskAdvisor(project_root).generate_risks(...)
│         merged_gaps, risks = mark_staleness(merged_gaps, risks, staged_files, claims_list, task_list_data)
│
├── 阶段 9：门禁判定
│   调用：gate_res = MergeGateEngine(project_root).evaluate(
│             gaps, risks, ghost_files, ac_gaps, dangling_claims,
│             claim_evidence_gaps, cov_violations, tool_outputs, staged_items)
│         _print_gate_summary(gate_res, staged_items)
│
├── 阶段 10：Agent 行动建议（仅 Gate blocked）
│   调用：_print_agent_actions(ctx, gate_res)
│
├── 阶段 11：人类决策层（仅 Gate passed）
│   调用：report_doc = _build_report_document(...)
│         _render_dashboard(...)
│         _print_reflection_prompts(...)
│
└── 阶段 12：返回退出码
    0=通过, 1=执行错误, 2=门禁 blocked
```

### 3.1 Gate 归属

| Gate | 原归属 | 新归属 | 理由 |
|------|--------|--------|------|
| Gate 1（constraints 哈希） | analyze 阶段 2 | **删除** | 属于 finalize |
| Gate 1b（PRD 漂移） | analyze 阶段 2 | **删除** | 属于 finalize |
| Gate 1c（PRD↔Arch 映射） | analyze 阶段 2 | **删除** | 属于 finalize |
| Gate 2（幽灵代码） | analyze 阶段 2 | analyze 阶段 2（**前置条件**） | 阻断越早越好 |

### 3.2 Gate 判定规则

#### Gate 2：前置条件（Stage 2）

| # | 规则 | db 函数 | 阻断条件 |
|---|------|---------|---------|
| 1 | Claim 覆盖 staged 文件 | `check_ghost_code(config)` | 有业务文件未被覆盖 → blocked |
| 2 | Claim 格式 | `validate_inputs()` | 格式错误 → Stage 1 阻断 |

#### Gate 3：分析判定（Stage 9）

| # | 规则 | db 函数 | 阻断条件 |
|---|------|---------|---------|
| 3 | task id 有效 | `check_dangling_claims()` | Task 不存在 → blocked |
| 4 | 测试通过 | `check_claim_evidence()` | 无测试 → warning；失败 → blocked |
| 5 | AC 测试覆盖 | `check_ac_coverage()` | MUST AC 无测试 → blocked |
| 6 | coverage 达标 | `check_coverage_violations()` | 低于阈值 → blocked |
| 7 | 架构合规 | `ArchitectureComplianceChecker` | MUST 违规 → blocked |
| 8 | 工具结果 | `_execute_tools()` | 严重问题 → blocked |

#### 判定结果分级

| 结果 | 含义 | 后续动作 |
|------|------|---------|
| blocked | MUST 违规，阻断提交 | Agent 通过行动建议修复 |
| warning | SHOULD 问题，不阻断 | 记录在报告中 |
| pass | 无问题 | 生成 Dashboard，人类验收 |

---

## 4. 目标包结构

### 4.1 Domain 包（纯业务逻辑，无 I/O）

```
domain/
├── evidence/                            # 证据构建与合并（纯内存操作）
│   ├── builder.py                       # EvidenceBuilder
│   └── merge_result.py                  # EvidenceMergeResult
│
├── gate/                                # 门禁判定引擎（纯规则）
│   ├── engine.py                        # MergeGateEngine（纯规则判定，不持有 conn）
│   └── staleness.py                     # mark_staleness, determine_affected_items 纯函数
│
├── compliance/                          # 合规检查（纯规则）
│   ├── checker.py                       # ArchitectureComplianceChecker
│   └── prd_arch_validator.py            # PRD↔Arch 映射校验
│
├── risk/                                # 风险评估（纯规则）
│   └── advisor.py                       # RiskAdvisor
│
├── governance/                          # 治理规则（纯规则）
│   ├── ghost_code.py                    # GhostCodeReconciler
│   └── change_proposal.py              # ArchitectureChangeProposalEngine
│
└── context.py                           # UnifiedContext（数据模型）
```

### 4.2 Infra 包（基础设施，含 I/O）

```
infra/
├── db/                                  # 数据库操作
│   ├── schema.py                        # init_in_memory_db
│   ├── loaders.py                       # load_tasks, load_claims, load_staged_files, load_initial_cache, load_prd
│   ├── queries.py                       # check_*, get_full_chain
│   └── exports.py                       # upsert_*, purge_stale_cache
│
├── validation/                          # 校验（Schema 校验、输入检查）
│
├── loader/                              # 数据加载（文件 I/O）
│   ├── raw_input.py                     # RawInputLoader
│   ├── prd_parser.py                    # PrdParser, PrdParseResult
│   ├── task_loader.py                   # TaskLoader, TaskListLoadResult
│   └── claim_loader.py                  # ClaimLoader, ClaimListLoadResult
│
├── report/                              # 报告生成（文件写入、HTML 渲染）
│   ├── traceability.py                  # TraceabilityReportBuilder
│   ├── dashboard.py                     # DashboardRenderer
│   └── reflection.py                    # render_reflection_prompts
│
├── logging/                             # OperationalLogger
├── git/                                 # git_show, git_has_uncommitted_changes, get_staged_files
├── config/                              # 配置相关
│   ├── enums.py                         # CoverageStatus, ErrorCode
│   ├── hint_loader.py                   # load_hints, resolve_hint
│   └── boundary.py                      # load_boundary, is_in_scope, partition_by_scope, load_human_decisions
├── governance/                          # 治理数据加载（I/O）
│   └── loader.py                        # read_claims_from_filesystem, read_task_list, read_prd_ac_ids, read_constraints_file, read_constraints_json
├── compliance/                          # 合规数据加载（I/O）
│   └── loader.py                        # get_python_imports, find_python_files, find_dashboard_files, read_dashboard_content, check_file_exists
└── tools/                               # 工具执行
    ├── resolver.py                      # ToolResolver（工具可用性检测）
    ├── candidate.py                     # ToolEvidenceCandidate（数据模型）
    ├── parsers.py                       # 输出解析器（6个纯函数：parse_pytest_output, parse_pytest_json, parse_ruff_output, parse_mypy_output, parse_bandit_output, parse_coverage_json_output）
    └── executor.py                      # ToolExecutionEngine（工具执行引擎，调用 parsers.py）
```

### 4.3 依赖方向

```
CLI → Domain → Infra
```

域内依赖：
```
evidence/        → 无域内依赖
gate/            → 无域内依赖
compliance/      → infra/compliance/（通过参数注入）
risk/            → 无域内依赖
governance/      → infra/governance/, infra/git/（通过参数注入）
context          → infra/loader/, gate/, compliance/, risk/
```

架构修复说明：
- domain 层不再直接进行文件 I/O，所有 I/O 操作通过 infra 层函数完成
- infra 层不再依赖 domain 层（已消除反向依赖）
- dashboard.py 的提案引擎调用已移至 cli 层

---

## 5. 接口变更

### 5.1 EvidenceBuilder

```python
class EvidenceBuilder:
    def __init__(self, project_root: Path):  # 不持有 conn

    def merge(self, tool_evidence: List[ToolEvidenceCandidate]) -> EvidenceMergeResult:
        """合并新旧证据。"""

    def apply(self, conn: sqlite3.Connection, merge_result: EvidenceMergeResult) -> None:
        """purge + upsert 路由。"""

    def persist(self, output_dir: Path, merge_result: EvidenceMergeResult) -> Dict[str, str]:
        """导出 JSON。从内存写入，不依赖 conn。"""
```

### 5.2 MergeGateEngine

```python
class MergeGateEngine:
    def __init__(self, project_root: Path):  # 不持有 conn

    def evaluate(
        self,
        gaps: List[dict],
        risks: List[dict],
        ghost_files: List[str],
        ac_gaps: List[dict],
        dangling_claims: List[dict],
        claim_evidence_gaps: List[dict],
        cov_violations: List[dict],
        tool_outputs: List[ToolEvidenceCandidate],
        staged_items: Optional[Set[str]],
    ) -> Tuple[str, List[str], List[dict]]:
        """纯规则判定，不访问数据库。"""
```

### 5.3 ArchitectureComplianceChecker

```python
class ArchitectureComplianceChecker:
    def check(
        self,
        conn: sqlite3.Connection,
        constraints_data: Dict[str, Any],
        human_decisions: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """直接从 DB 查询，不再接收 evidences list。"""
```

### 5.4 UnifiedContext

```python
@dataclass
class UnifiedContext:
    config: Dict[str, Any]
    prd: PrdParseResult
    constraints: Optional[Dict[str, Any]] = None
    task_result: Optional[TaskListLoadResult] = None
    claims_list: List[Claim] = field(default_factory=list)
    manifest: Optional[RawInputManifest] = None
    human_decisions: Optional[dict] = None
    config_prefix: str = "VT"
    # tool_evidence 字段已删除
```

### 5.5 mark_staleness

位置：`domain/gate/staleness.py`（而非设计文档原定的 `domain/staleness_tracker.py`）

```python
def mark_staleness(
    merged_gaps: list,
    risks: list,
    staged_files: Optional[Set[str]],
    claims_list: list,
    task_list_data: Optional[dict] = None,
) -> Tuple[list, list]:
    """纯函数，返回新列表，不修改原列表。"""
```

### 5.6 EvidenceMergeResult

```python
@dataclass
class EvidenceMergeResult:
    test_results_to_upsert: List[Dict[str, Any]]
    coverage_reports_to_upsert: List[Dict[str, Any]]
    files_to_purge: List[str]
    skipped_evidence: List[Dict[str, Any]]
    stats: Dict[str, int]  # test_count, coverage_count, skipped_count, purge_count
```

---

## 6. DB Schema 扩展

### 6.1 新增表

```sql
CREATE TABLE requirements (
    req_id   TEXT PRIMARY KEY,
    title    TEXT NOT NULL,
    priority TEXT NOT NULL,
    category TEXT NOT NULL
);

CREATE TABLE acceptance_criteria (
    ac_id               TEXT PRIMARY KEY,
    req_id              TEXT NOT NULL,
    title               TEXT NOT NULL,
    is_testing_required INTEGER NOT NULL
);
```

### 6.2 新增/重构查询函数

| 函数 | 说明 | 状态 |
|------|------|------|
| `check_requirement_coverage(conn)` | PRD → Task 覆盖 | ✅ 已实现 |
| `check_claim_evidence(conn)` | Claim → Test 一致性 | ✅ 已实现 |
| `get_full_chain(conn)` | 全链条 JOIN（Dashboard/Report 用） | ✅ 已实现 |
| `check_ac_coverage(conn)` | 重构：从 acceptance_criteria 出发 | ✅ 已重构 |
| `check_dangling_claims(conn)` | Claim → Task 存在性 | ✅ 已实现 |
| `check_ghost_code(conn, config)` | staged_files LEFT JOIN claim_code_refs | ✅ 已实现 |

### 6.3 状态枚举约束

所有 check_* 的 SQL CASE WHEN 必须引用 `CoverageStatus` 枚举，禁止硬编码字符串。

```python
class CoverageStatus(Enum):
    COVERED = "covered"
    PARTIAL = "partial"
    MISSING = "missing"
    BLOCKED = "blocked"
    UNCLEAR = "unclear"
    VIOLATED = "violated"
    NO_TASK = "no_task"
    NO_CLAIM = "no_claim"
    NO_TESTS = "no_tests"
    TEST_FAILED = "test_failed"

TASK_STATUS_TO_COVERAGE = {
    "todo": CoverageStatus.MISSING.value,
    "in_progress": CoverageStatus.PARTIAL.value,
    "blocked": CoverageStatus.BLOCKED.value,
    "done": CoverageStatus.COVERED.value,
}
```

---

## 7. 删除清单

| 文件/函数 | 删除原因 | 替代方案 |
|-----------|---------|---------|
| `analysis.py` 整个文件 | 职责重叠 | 合并到 pipeline.py |
| `analyzers/requirement_task_analyzer.py` | 查询逻辑移入 db.py | `db.check_requirement_coverage()` |
| `analyzers/ac_test_analyzer.py` | 查询逻辑移入 db.py | `db.check_ac_coverage()` |
| `analyzers/claim_evidence_analyzer.py` | 查询逻辑移入 db.py | `db.check_claim_evidence()` |
| pipeline.py evidence_dicts 构建 | 分析器直接查 DB | 删除 |
| pipeline.py `EVIDENCE-VT-{idx}` 编号 | 编号漂移 | source_path/nodeid 替代 |
| context.py `tool_evidence` 字段 | "半构造"状态 | 局部变量传递 |
| `gates.py._gate1_constraints_hash()` | 属于 finalize | 删除 |
| `gates.py._gate1b_prd_drift()` | 属于 finalize | 删除 |
| `gates.py._gate1c_mapping()` | 属于 finalize | 删除 |
| `gates.py._run_integrity_gates()` | Gate 1/1b/1c 已删除 | 重构为 `_check_claim_coverage()` |

---

## 8. 变更影响矩阵

| 模块 | 变更类型 | 变更内容 |
|------|---------|---------|
| `cli/analyze/pipeline.py` | 重构 | 删除 evidence_dicts，接管 DB 调度，合并 analysis.py |
| `cli/analyze/analysis.py` | 删除 | 逻辑拆分到 pipeline + staleness_tracker |
| `domain/context.py` | 微调 | 删除 tool_evidence 字段 |
| `domain/evidence_builder.py` | 重构 | build → merge + apply + persist |
| `domain/staleness_tracker.py` | 新建 | mark_staleness 纯函数 |
| `domain/evidence_merge_result.py` | 新建 | EvidenceMergeResult dataclass |
| `analyzers/` 3 个文件 | 删除 | 查询逻辑移入 db.check_* |
| `domain/architecture_compliance_checker.py` | 接口变更 | check() 接收 conn |
| `domain/merge_gate_engine.py` | 重构 | 解耦 conn，纯判定引擎 |
| `cli/analyze/gates.py` | 重构 | 删除 Gate 1/1b/1c，Gate 2 前置条件 |
| `cli/analyze/tools.py` | 无变更 | 接口已正确 |
| `cli/analyze/reports.py` | 接口变更 | 从 DB 查询全链条数据 |

---

## 9. 实施步骤

每一步必须保持测试通过。Step 0 是基础，其他步骤依赖它。

```
Step 0a: db 子模块拆分与表结构扩展          ← ✅ 已完成
  - infra/db/ 子包（schema, loaders, queries, exports）
  - requirements + acceptance_criteria 表
  - load_prd()

Step 0b: 新增与重构 SQL 查询函数            ← ✅ 已完成
  - check_requirement_coverage, check_claim_evidence, get_full_chain
  - check_ac_coverage 重构

Step 1: 新建 staleness_tracker.py + evidence_merge_result.py

Step 2: 修改 evidence_builder.py（build → merge + apply + persist）

Step 3: 删除 analyzer 类 + 重构 pipeline.py
  - 删除 3 个 analyzer
  - pipeline 直接调 db.check_*
  - 合并 analysis.py
  - 删除 evidence_dicts

Step 4: 修改 context.py（删除 tool_evidence 字段）

Step 5: 重构 gates.py（删除 Gate 1/1b/1c，Gate 2 前置条件）

Step 6: 修改 MergeGateEngine（解耦 conn，纯判定引擎）

Step 7: 删除 analysis.py

Step 8: 更新测试文件

Step 9: 运行全量测试验证
```

---

## 10. 测试影响

### 测试策略

- **不新建测试 DB helper**：各测试自行构造 `conn` + 插入数据，不做共享 fixture 抽象。
- **不保留 fixtures 项目**：已删除 `tests/fixtures/` 和 `test_e2e_samples.py`，反面用例通过直接构造 DB 数据覆盖。
- **废弃测试直接删除**：不保留 `skip`/`xfail` 标记。

### 已删除（前置清理）

| 文件 | 测试数 | 原因 |
|------|--------|------|
| test_requirement_task_analyzer.py | 5 | analyzer 被删除 |
| test_ac_test_analyzer.py | 6 | analyzer 被删除 |
| test_claim_evidence_analyzer.py | 16 | analyzer 被删除 |
| test_instrumentation_logging.py | 33 | import 3 个被删 analyzer |
| test_ac_vt_009_coverage.py | 28 | import claim_evidence_analyzer |
| test_exception_logging.py | 16 | import analysis.py |
| test_analyze_refactor_integration.py | ~15 | 测试旧 pipeline 结构 |
| test_quality_gates.py | ~20 | 测试旧 Gate 1/1b/1c + 旧 evaluate() |
| test_e2e_samples.py | 4 | fixtures 已删除 |

### 待修改（重构过程中）

| 文件 | 测试数 | 变更 |
|------|--------|------|
| test_evidence_builder.py | 9 | build → merge + apply + persist |
| test_merge_gate_engine.py | 63 | 新增 Rule 3/4，解耦 conn |
| test_db_schema.py | 11 | 新增 requirements + acceptance_criteria 表 |

### 待新增（重构过程中）

| 文件 | 测试数 |
|------|--------|
| test_pipeline.py | ~10 |
| test_staleness_tracker.py | ~5 |

---

## 11. 数据流图

```
                ┌─────────────────────────────────────┐
                │         UnifiedContext                │
                │  config, prd, constraints,            │
                │  task_result, claims_list, manifest   │
                │  （不含 tool_evidence）                 │
                └────────────┬────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
   load_prd()          load_tasks()        load_claims()
         │                   │                   │
         └───────────────────┼───────────────────┘
                             ▼
                ┌─────────────────────────────┐
                │   in-memory SQLite (conn)    │
                │                              │
                │  设计层：requirements,         │
                │         acceptance_criteria   │
                │  开发层：tasks, task_acs,      │
                │         claims, refs          │
                │  证据层：test_results,         │
                │         coverage_reports      │
                └──────────┬──────────────────┘
                           ▼
                ┌─────────────────────────────┐
                │  db.check_*（唯一查询层）      │
                │  ├── check_requirement_coverage()  │
                │  ├── check_ac_coverage()           │
                │  ├── check_claim_evidence()        │
                │  ├── check_dangling_claims()       │
                │  ├── check_ghost_code()            │
                │  ├── check_coverage_violations()   │
                │  └── get_full_chain()              │
                └──────────┬──────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
   EvidenceBuilder    RiskAdvisor     MergeGateEngine
   (合并+持久化)      (生成 risks)     (门禁判定)
         │                 │                 │
         └─────────────────┼─────────────────┘
                           ▼
                ┌─────────────────────────────┐
                │  gate_res → 输出分支          │
                └──────────┬──────────────────┘
                           │
                ┌──────────┴──────────────────┐
                │  _print_gate_summary()（始终）│
                └──────────┬──────────────────┘
                           │
                    gate passed?
                   ┌───────┴───────┐
                  yes              no
                   │                │
                   ▼                ▼
          ┌─────────────┐  ┌─────────────┐
          │ 人类决策层    │  │ Agent 修复   │
          │ ├── reflection│  │ └── actions  │
          │ ├── report    │  └─────────────┘
          │ └── dashboard │
          └─────────────┘
```

---

## 12. 异常处理与日志

| 规范项 | 实现方式 |
|--------|---------|
| Logger 获取 | `get_or_init()` + try/except 守卫，失败降级 |
| 异常传播 | 业务异常传播到 main.py，pipeline 不自行捕获 |
| 资源清理 | try/finally 确保 `conn.close()` |
| 日志事件 | `run_start` → 多个 `phase_end` → `run_end` |
| run_id | `ANALYZE-{uuid.uuid4()}` |

```
main.py（全局捕获）
  └── pipeline.py（资源清理）
        ├── _GateBlocked → 已知业务错误，返回 exit_code
        ├── Exception → logger.exception() + print(stderr)，返回 1
        └── 正常 → 返回 0 或 2
```

---

## 附录：域包接口契约（__init__.py 导出）

```python
# domain/loader/__init__.py
from .raw_input import RawInputLoader, InputFileRecord, RawInputManifest
from .prd_parser import PrdParser, PrdParseResult, Requirement, AcceptanceCriteria
from .task_loader import TaskLoader, TaskListLoadResult, Task, DodItem, TaskGap
from .claim_loader import ClaimLoader, ClaimListLoadResult, Claim, ClaimGap

# domain/evidence/__init__.py
from .builder import EvidenceBuilder
from .tool_adapter import ToolExecutionEngine, ToolEvidenceCandidate

# domain/gate/__init__.py
from .engine import MergeGateEngine

# domain/compliance/__init__.py
from .checker import ArchitectureComplianceChecker
from .prd_arch_validator import validate_prd_architecture_mapping, MappingResult

# domain/risk/__init__.py
from .advisor import RiskAdvisor

# domain/report/__init__.py
from .traceability import TraceabilityReportBuilder
from .dashboard import DashboardRenderer
from .reflection import render_reflection_prompts

# domain/governance/__init__.py
from .ghost_code import GhostCodeReconciler
from .change_proposal import ArchitectureChangeProposalEngine

# infra/db/__init__.py
from .schema import init_in_memory_db
from .loaders import load_tasks, load_claims, load_staged_files, load_initial_cache, load_prd
from .queries import check_ac_coverage, check_coverage_violations, check_requirement_coverage,
                      check_claim_evidence, check_dangling_claims, check_ghost_code, get_full_chain
from .exports import upsert_test_result, upsert_coverage_report, purge_stale_cache
```
