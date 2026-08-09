# vt analyze 架构设计

> **范围**：本文档描述 `vt analyze` 命令的架构设计，覆盖 pipeline 调度、DB 查询、规则判定、证据合并、输出渲染、任务会话追踪全链路。
> **阅读对象**：AI coding agent。按需跳转，不必顺序阅读。
> **相关文档**：[gate_engine_design.md](gate_engine_design.md)（门禁判定引擎）、[channel_separation.md](channel_separation.md)（通道分离）、[stage7_sql_reference.md](stage7_sql_reference.md)（SQL 查询参考）

---

## 1. 设计原则

| 原则 | 含义 |
|------|------|
| pipeline 是调度层 | 只负责"按顺序调用谁"，不含业务逻辑 |
| db.py 是唯一查询层 | 所有 SQL 查询由 pipeline 调用 db.check_* |
| 子模块不直接调 db | 子模块接收数据参数，返回处理结果 |

---

## 2. 设计决策

### 决策 1：分析器直接查询数据库

analyzers 查询 SQLite，不消费 Python dict。

- 状态映射用 SQL CASE WHEN
- source_path/nodeid 替代顺序编号

### 决策 2：调度逻辑集中在 pipeline.py

- staleness 标记 → `domain/gate/staleness.py`
- gap 合并逻辑 → pipeline.py（纯数据合并）

### 决策 3：tool_evidence 作为独立返回值

- `execute_from_claims()` 返回 `ToolExecutionResult`（含 `candidates: List[ToolEvidenceCandidate]`）
- tool_evidence 作为 pipeline 局部变量传递，不存入 UnifiedContext

---

## 3. 规则判定

规则判定由 **Gate Engine** 完成：解释层将 issue 检测结果计算为五元信号 `(o, a, r, c, v)`，规则引擎 `F()` 按优先级短路求值输出 5 态之一。

参见 [`gate_engine_design.md`](gate_engine_design.md)（完整设计规格与形式化证明）。

---

## 4. 目标包结构

### 4.1 Domain 包（纯业务逻辑，无 I/O）

```
domain/
├── capability/                   # Agent 能力评分（AgentCapabilityMetricsAggregator）
├── compliance/                   # 合规检查（纯规则）
├── evidence/                     # 证据构建与合并（纯内存操作）
├── gate/                         # 门禁判定引擎（纯规则）
├── governance/                   # 治理演进指标（GovernanceMetricsAggregator）
├── risk/                         # 风险评估（纯规则）
├── task/                         # 任务会话追踪（TaskSessionManager）、
│                                 # 验收摘要（AcceptanceSummaryBuilder）、
│                                 # 严重风险判定（BusinessImpactResolver）
└── context.py                    # UnifiedContext（数据模型）
```

### 4.2 Infra 包（基础设施，含 I/O）

```
infra/
├── compliance/                  # 合规数据加载
├── config/                      # 配置读取
├── db/                          # 数据库操作（schema / loaders / queries / exports）
├── loader/                      # 数据加载（文件 I/O）
├── logging/                     # OperationalLogger
├── report/                      # 报告生成（TraceabilityReportBuilder / DashboardRenderer）
├── tools/                       # 工具执行
└── validation/                  # 校验（Schema 校验、输入检查）
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
    ├── actions.py                  # 行动建议收集 + 辅助查询
    ├── channel.py                  # 通道分流调度（Agent stdout vs Dashboard）
    ├── db_analysis.py              # DB 分析查询（check_* 调用封装）
    ├── exceptions.py               # CLI 层共享异常（_GateBlocked）
    ├── formatting.py               # 行动建议格式化
    ├── output.py                   # 终端渲染（委托 ChannelRenderer）
    ├── pipeline.py                 # 主流水线编排（调度层，含 _load_context）
    └── reports.py                  # 报告生成（含 _rel_path_str）
```

设计说明：
- `exceptions.py` 独立存在，避免 `pipeline.py` ↔ `reports.py` 的循环导入
- `_load_context()` 定义在 `pipeline.py`，是阶段 1 的唯一入口
- `_rel_path_str()` 仅 `reports.py` 使用，内联定义
- `channel.py` 的 ChannelRenderer 负责 stdout 与 Dashboard 的分流调度

### 4.4 依赖方向

```
CLI → Domain → Infra
```

域内依赖：
```
evidence/        → 无域内依赖
gate/            → 无域内依赖
task/            → 无域内依赖
capability/      → 无域内依赖
compliance/      → infra/compliance/（通过参数注入）
risk/            → 无域内依赖
governance/      → infra/loader/config（通过参数注入）
context          → infra/loader/, gate/, compliance/, risk/
```

---

## 5. 接口定义

### 5.0 ToolExecutionResult

位置：`domain/evidence/candidate.py`

```python
@dataclass
class ToolExecutionResult:
    """Structured return value from execute_from_claims()."""
    candidates: List[ToolEvidenceCandidate]
    skipped: bool = False          # True = precheck failed or no code files
    skip_reason: str = ""          # "precheck_failed" | "no_code_files" | "no_extensions"
    missing_tools: List[str] = field(default_factory=list)
```

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

### 5.8 TaskSessionManager

位置：`domain/task/session.py`

```python
class TaskSessionManager:
    def __init__(self, sessions_path: Path):
        """加载 task_sessions.json，不存在时初始化为空。"""

    def find_closed_references(self, task_ids: Set[str]) -> List[str]:
        """返回 current_commit_task_set 中已 CLOSED 的 task_id 列表。"""

    def update_sessions(
        self, current_commit_task_set, states_and_signals,
        gate_decision, task_name_lookup, phase_id_lookup, model,
    ) -> None:
        """更新 task 会话（创建/迭代计数/关闭），gate=PASS 时写占位。"""

    def writeback_acceptance_summaries(self, summaries: List[dict]) -> None:
        """验收摘要计算完成后回写到 session 文件。"""
```

### 5.9 ChannelRenderer

位置：`cli/analyze/channel.py`

```python
class ChannelRenderer:
    @staticmethod
    def render_stdout(
        print_agent_actions, gate_decision,
        current_commit_task_set, acceptance_summaries,
    ):
        """stdout 通道：Agent 指令段 + 验收摘要段（gate=PASS 时）。"""

    @staticmethod
    def render_dashboard(render_fn):
        """Dashboard 通道：直接委托 reports._render_dashboard。"""
```

---

## 6. DB Schema

全量 15 张表 + 12 个 `check_*` 查询详见 [`stage7_sql_reference.md`](stage7_sql_reference.md)。本文仅列出 pipeline 直接调用的核心查询：

| 函数 | 说明 |
|------|------|
| `check_requirement_coverage(conn)` | PRD → Task 覆盖 |
| `check_claim_evidence(conn)` | Claim → Test 一致性 |
| `get_full_chain(conn)` | 全链条 JOIN（Dashboard/Report 用） |
| `check_ac_coverage(conn)` | AC → Claim 覆盖 |
| `check_dangling_claims(conn)` | Claim → Task 存在性 |

---

## 7. 数据流

`vt analyze` 一次执行经过以下阶段：

```
1. _load_context()
   加载 config / PRD / 架构约束 / task_list / claims / human_decisions → UnifiedContext
      │
2. closed task 预检查
     TaskSessionManager.find_closed_references()
       → 命中则 exit code 3（短路，不进入 gate 检测）
      │
3. DB 初始化 + 数据灌入
     init_in_memory_db() → 15 张表
     灌入：requirements / acceptance_criteria / tasks / claims / ……
     灌入：evidence 缓存（test_results / coverage_reports）
      │
4. DB 分析查询
     check_requirement_coverage()
     check_ac_coverage()
     check_claim_evidence()
     check_dangling_claims()
     ……
      │
5. 幽灵代码检测
     GhostCodeReconciler (stage 2)
      │
6. 证据合并（工具执行）
     EvidenceBuilder.merge() + apply() + persist()
      │
7. 规则判定
     MergeGateEngine.evaluate()
     SignalComputer.compute_signals()
     F() 求值 → 5 态输出
      │
8. 报告构建 + 输出渲染
     _build_report_document() → report_doc
     ChannelRenderer.render_dashboard() → HTML
     ChannelRenderer.render_stdout()    → stdout（Agent 指令段）
     TaskSessionManager.update_sessions()
       → gate=PASS 时：AcceptanceSummaryBuilder.build_list()
       → ChannelRenderer.render_stdout() 输出验收摘要段
```

---

## 8. 异常处理与日志

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
        ├── Exception → logger.exception() + print(stderr)，返回 1
        └── 正常 → 返回 0 或 2（gate=blocked）
```

Exit code 三级制已扩展为四级（参见 [`phase_channel_separation.md`](phase_channel_separation.md) §2.3.1）：
| Exit | 语义 |
|------|------|
| 0 | 成功（gate=PASS） |
| 1 | 内部崩溃 |
| 2 | Gate BLOCKED（可修复 issue） |
| 3 | Closed task 引用 |

---

## 附录：域包接口契约（__init__.py 导出）

> 以下导出清单与代码同步。数据模型类定义在各自模块内，不从 `__init__.py` 导出。

```python
# infra/loader/__init__.py
from .config import load_config, resolve_path, REQUIRED_FILES
from .raw_input import RawInputLoader
from .prd_parser import PrdParser, PrdParseResult
from .task_loader import TaskLoader, TaskListLoadResult
from .claim_loader import ClaimLoader, ClaimListLoadResult

# domain/evidence/__init__.py
from .builder import EvidenceBuilder
from .merge_result import EvidenceMergeResult

# domain/gate/__init__.py
from .engine import MergeGateEngine
from .staleness import mark_staleness, determine_affected_items

# domain/compliance/__init__.py
from .checker import ArchitectureComplianceChecker
from .prd_arch_validator import validate_prd_architecture_mapping

# domain/risk/__init__.py
from .advisor import RiskAdvisor

# infra/report/__init__.py
from .traceability import TraceabilityReportBuilder
from .dashboard import DashboardRenderer
from .reflection import render_reflection_prompts

# domain/governance/__init__.py
from .change_proposal import ArchitectureChangeProposalEngine

# infra/db/__init__.py
from .schema import init_in_memory_db
from .loaders import (load_tasks, load_claims, load_staged_files,
                      load_initial_cache, load_prd, load_architecture_constraints)
from .queries import (check_ac_coverage, check_coverage_violations,
                      check_requirement_coverage, check_claim_evidence,
                      check_dangling_claims,  get_full_chain,
                      check_test_dead_links, check_active_task_coverage,
                      check_invalid_task_requirements, check_invalid_task_acs,
                      check_invalid_task_modules, check_invalid_task_constraints,
                      check_invalid_ac_parent,
                      check_isolated_tasks)
from .exports import (upsert_test_result, upsert_coverage_report,
                      purge_stale_cache, persist_evidences)
```
