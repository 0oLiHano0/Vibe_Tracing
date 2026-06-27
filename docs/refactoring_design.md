# 重构设计文档

> 阅读对象：AI coding agent。按需跳转，不必顺序阅读。

---

## 1. 设计原则

| 原则 | 含义 |
|------|------|
| pipeline 是调度层 | 只负责"按顺序调用谁"，不含业务逻辑 |
| db.py 是唯一查询层 | 所有 SQL 查询由 pipeline 调用 db.check_* |
| 子模块不直接调 db | 子模块接收数据参数，返回处理结果 |
| 对象要么构造完成，要么不构造 | 消除 UnifiedContext 的"半构造"状态 |

---

## 2. 设计决策

### 决策 1：分析器直接查询数据库

analyzers 查询 SQLite，不消费 Python dict。

- 状态映射用 SQL CASE WHEN
- source_path/nodeid 替代顺序编号

### 决策 2：check_* 函数留在 db.py

3 个活跃函数（`check_ac_coverage`、`check_coverage_violations`、`check_ghost_code`）+ 3 个保留函数（`check_dangling_claims`、`check_test_dead_links`、`check_active_task_coverage`）均留在 `infra/db/queries.py`。

### 决策 3：evidence_builder 只做"证据合并"

- `merge()` 纯数据处理，不需要 conn
- `apply()` 需要 conn，内部处理 purge + upsert 路由
- `persist()` 仅导出 JSON，不依赖 conn

### 决策 4：调度逻辑集中在 pipeline.py

- staleness 标记 → `domain/gate/staleness.py`
- gap 合并逻辑 → pipeline.py（纯数据合并）

### 决策 5：tool_evidence 作为独立返回值

- `_execute_tools()` 返回 `List[ToolEvidenceCandidate]`
- tool_evidence 作为 pipeline 局部变量传递，不存入 UnifiedContext

---

## 3. 目标流水线

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
│
├── 阶段 3：执行工具
│   调用：tool_evidence = _execute_tools(ctx)
│   输出：List[ToolEvidenceCandidate]（局部变量）
│
├── 阶段 4：创建数据库
│   调用：init_in_memory_db() → conn
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
│   调用：merged_gaps, final_risks, compliance_res, analysis_details = _run_db_analysis(
│             conn, ctx, project_root, staged_files, human_decisions)
│
├── 阶段 8：门禁判定 + 输出
│   调用：gate_engine = MergeGateEngine(
│             project_root,
│             incremental_only=incremental_only,
│             show_historical_debt=show_historical_debt,
│         )
│         gate_res = gate_engine.evaluate(
│             gaps, risks,
│             compliance_res=compliance_res,
│             staged_items=staged_items,
│             directly_staged_items=directly_staged_items,
│             human_decisions=human_decisions,
│             ghost_files=ghost_files,
│             ac_gaps=ac_gaps,
│             dangling_claims=dangling_claims,
│             claim_evidence_gaps=claim_evidence_gaps,
│             cov_violations=cov_violations)
│         report_doc = _build_report_document(...)
│         _render_output(...)
│
└── 阶段 9：返回退出码
    0=通过, 1=执行错误, 2=门禁 blocked
```

### 3.1 Gate 判定规则

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
│   ├── config.py                        # load_config, resolve_path, REQUIRED_FILES
│   ├── raw_input.py                     # RawInputLoader, InputFileRecord, RawInputManifest
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

### 4.3 CLI 包（命令层）

```
cli/
├── main.py                         # CLI 入口与调度
├── init.py                         # vt init
├── finalize.py                     # vt finalize
├── accept.py                       # vt accept
├── doctor.py                       # vt doctor
└── analyze/
    ├── exceptions.py               # CLI 层共享异常（_GateBlocked）
    ├── pipeline.py                 # 主流水线编排（调度层，含 _load_context）
    ├── gates.py                    # 门禁检查（Gate 2 前置条件）
    ├── tools.py                    # 工具执行
    ├── reports.py                  # 报告生成（含 _rel_path_str）
    ├── actions.py                  # 行动建议收集 + 辅助查询（DB 查询委托 queries.py）
    ├── formatting.py               # 行动建议格式化
    └── output.py                   # 终端渲染
```

设计说明：
- `exceptions.py` 独立存在，避免 `pipeline.py` ↔ `reports.py`/`tools.py` 的循环导入
- `_load_context()` 定义在 `pipeline.py`，是阶段 1 的唯一入口
- `_rel_path_str()` 仅 `reports.py` 使用，内联定义
- `actions.py` 包含 hint 解析和 AC/需求描述查询函数（`_hint_title`、`_get_ac_description` 等）

### 4.4 依赖方向

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

---

## 5. 接口定义

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
    def __init__(
        self,
        project_root: Path,
        incremental_only: bool = False,
        show_historical_debt: bool = True,
    ):  # 不持有 conn

    def evaluate(
        self,
        gaps: List[dict],
        risks: List[dict],
        compliance_res: Optional[Dict[str, Any]] = None,
        staged_items: Optional[Set[str]] = None,
        directly_staged_items: Optional[Set[str]] = None,
        human_decisions: Optional[Any] = None,
        ghost_files: Optional[List[str]] = None,
        ac_gaps: Optional[List[dict]] = None,
        dangling_claims: Optional[List[dict]] = None,
        claim_evidence_gaps: Optional[List[dict]] = None,
        cov_violations: Optional[List[dict]] = None,
    ) -> Dict[str, Any]:
        """纯规则判定，不访问数据库。

        返回字典包含：gate_decision, reasons, blocked_items, human_decisions_applied,
                       incremental_mode, historical_debt_count

        增量模式（incremental_only）：
        - 只检查增量问题，历史债务不阻塞门禁
        - Rule 2/3/4/5 在 incremental_only 模式下遵循 _is_current 判定
        - 历史债务显示为摘要（如"📊 3 historical debts exist"）
        - 配置优先级：命令行参数 > 环境变量 > config.json > 默认值
        """
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
        """直接从 DB 查询，不接收 evidences list。"""
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
```

### 5.5 mark_staleness

位置：`domain/gate/staleness.py`

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

### 5.7 _db_result_to_gaps

位置：`cli/analyze/pipeline.py`

```python
def _db_result_to_gaps(
    req_coverage: list,
    ac_coverage: list,
    claim_evidence: list,
) -> list:
    """DB 查询原始行 → gate/report 层所需的 gap dict 格式。

    adapter 模式：隔离 db.check_* 的 SQL 行格式与 MergeGateEngine 的 dict 格式。
    """
```

---

## 6. DB Schema

### 6.1 表结构

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

### 6.2 查询函数

| 函数 | 说明 |
|------|------|
| `check_requirement_coverage(conn)` | PRD → Task 覆盖 |
| `check_claim_evidence(conn)` | Claim → Test 一致性 |
| `get_full_chain(conn)` | 全链条 JOIN（Dashboard/Report 用） |
| `check_ac_coverage(conn)` | 从 acceptance_criteria 出发检查覆盖 |
| `check_dangling_claims(conn)` | Claim → Task 存在性 |
| `check_ghost_code(conn, config)` | staged_files LEFT JOIN claim_code_refs |
| `query_related_code(conn, ac_id)` | AC → 代码文件路径（task_acs → claims → claim_code_refs） |
| `query_existing_tests(conn, ac_id)` | AC → 测试 nodeid（task_acs → claims → claim_test_refs） |

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

## 7. 测试策略

- **不新建测试 DB helper**：各测试自行构造 `conn` + 插入数据，不做共享 fixture 抽象。
- **废弃测试直接删除**：不保留 `skip`/`xfail` 标记。

---

## 8. 数据流图

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

## 9. 异常处理与日志

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
        │     定义位置：cli/analyze/exceptions.py
        │     raise 来源：pipeline.py, reports.py, tools.py
        ├── Exception → logger.exception() + print(stderr)，返回 1
        └── 正常 → 返回 0 或 2
```

---

## 附录：域包接口契约（__init__.py 导出）

```python
# infra/loader/__init__.py
from .config import load_config, resolve_path, REQUIRED_FILES
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
