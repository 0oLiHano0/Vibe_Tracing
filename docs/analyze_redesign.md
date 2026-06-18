# Analyze 阶段重构：文件分布与接口契约

> **文档定位**：本文档是**具体设计层**，定义每个模块的接口契约、文件变更和关键决策。
>
> - 架构愿景（为什么重构、核心原则）→ [`architecture_vision.md`](architecture_vision.md)
> - 执行计划（Phase 任务清单、偏离点跟踪）→ [`analyze_execution_plan.md`](analyze_execution_plan.md)
>
> 范围：仅覆盖 `vt analyze` 流水线。`vt init`、`vt finalize`、`vt accept`、`vt doctor` 不在本次重构范围内。

---

## 一、 现状文件分布与职责

### 1.1 入口与编排层

| 文件 | 行数 | 职责 |
|---|---|---|
| `cli.py` | 218 | CLI 入口，解析参数，分发到命令模块 |
| `commands/common.py` | 299 | `_load_context`（加载所有输入构建 UnifiedContext）、`_get_staged_files`、`_determine_affected_items` |
| `commands/analyze/pipeline.py` | 447 | analyze 流水线编排：context → tools → evidence → analyzers → gate → output |
| `commands/analyze/tools.py` | 321 | `_execute_tools`（工具执行）、`_check_staged_extensions`、`_archive_claims` |
| `commands/analyze/analysis.py` | 314 | `_run_analyzers`（运行所有分析器）、`_run_claim_tests`（pytest 子进程）、`_load_human_decisions` |
| `commands/analyze/gates.py` | 180 | `_run_integrity_gates`（Gate 1/2/2.5） |
| `commands/analyze/reports.py` | 185 | `_build_report_document`（生成 traceability_report） |
| `commands/analyze/output.py` | 167 | `_render_output`（Dashboard + 终端输出） |
| `commands/analyze/formatting.py` | 123 | CLI 输出格式化 |
| `commands/analyze/actions.py` | 244 | Agent action 提取与格式化 |
| `commands/analyze/helpers.py` | 129 | 杂项辅助函数 |

### 1.2 核心领域模块

| 文件 | 行数 | 职责 |
|---|---|---|
| `context.py` | 38 | `UnifiedContext` 数据类，所有解析结果的单一容器 |
| `evidence_index_builder.py` | 320 | 构建 `evidence_index.json`（含 mtime 增量缓存） |
| `merge_gate_engine.py` | 867 | 门禁判定引擎：AC 覆盖、覆盖率违规、stale 标记 |
| `ghost_code_reconciler.py` | 442 | Gate 2 幽灵代码检测（`git show HEAD` 获取旧 claims） |
| `claim_loader.py` | 285 | 加载 `claims/current.json`，Schema 校验，Claim 数据类 |
| `task_loader.py` | 374 | 加载 `task_list.json`，Schema 校验，Task 数据类 |
| `prd_parser.py` | 386 | 解析 `prd.md`（mistune AST） |
| `raw_input_loader.py` | 183 | 一次性加载所有原始输入文件，生成 `RawInputManifest` |
| `tool_evidence_adapter.py` | 1042 | `ToolExecutionEngine`：执行 pytest/ruff/bandit/coverage，输出 `ToolEvidenceCandidate` |
| `architecture_compliance_checker.py` | 885 | 架构约束合规检查（import 边界、依赖规则） |
| `risk_advisor.py` | 220 | 基于 gaps + compliance 生成风险项 |
| `traceability_report_builder.py` | 64 | 构建 traceability_report.json |

### 1.3 Traceability 分析器

| 文件 | 行数 | 职责 |
|---|---|---|
| `traceability/requirement_task_analyzer.py` | 123 | REQ → Task 覆盖分析 |
| `traceability/ac_test_analyzer.py` | 131 | AC → Test 覆盖分析 |
| `traceability/claim_evidence_analyzer.py` | 540 | Claim → Evidence 关联分析 |

### 1.4 基础设施

| 文件 | 行数 | 职责 |
|---|---|---|
| `core/enums.py` | 43 | 枚举：CoverageStatus、ErrorCode |
| `core/ids.py` | 141 | ID 生成与校验（validate_id、set_project_prefix） |
| `governance.py` | 101 | 治理边界加载与判断（is_in_scope） |
| `git_utils.py` | 131 | git 子进程封装（git_show、git_diff） |
| `schema_validator.py` | 278 | JSON Schema 校验器 |
| `operational_logger.py` | 206 | JSONL 运行日志 |
| `hint_loader.py` | 71 | Hints 加载与解析 |
| `tool_resolver.py` | 49 | 检测工具是否可用（which） |

---

## 二、 重构后目标架构

### 2.1 核心变更

| 变更 | 现状 | 目标 |
|---|---|---|
| 证据存储 | 单一 `evidence_index.json`（含所有类型） | 拆分为 `output/evidences/test_results.json` + `coverage_reports.json` |
| Claims 存储 | `.vibetracing/claims/current.json`（单文件数组） | `.vibetracing/claims/CLAIM-*.json`（一任务一文件） |
| Claims 归档 | `_archive_claims` 提交后清空 | 彻底删除归档机制，Claims 累积式 |
| 关联查询 | Python 嵌套循环 + 内存字典拼装 | 内存 SQLite（`sqlite3 :memory:`）+ SQL JOIN |
| 证据 ID | 顺序编号 `EVIDENCE-VT-001` | 天然主键（nodeid / source_path），删除 evidence_id |
| 增量缓存 | mtime 比对 + carried_over 标记 | SQLite UPSERT：历史缓存全量入表，新结果覆盖 |
| 活跃 Claims 识别 | `git show HEAD:claims.json` 对比 | `git diff --cached --name-only` 匹配 `CLAIM-*.json` |
| 幽灵代码检测 | `git show HEAD` 获取旧 claims + Python 循环 | SQL LEFT JOIN 查询 staged_files ↔ claim_code_refs |
| 门禁判定 | Python 嵌套循环检查 test_category/status | SQL 查询一次性获取未通过 AC 列表 |

### 2.2 重构后文件分布

> 以下路径基于第八章目录重组后的结构。`cli/`、`domain/`、`analyzers/`、`infra/` 四个子包的划分见第八章。

```
src/vibe_tracing/
├── cli/                               # 入口与编排层（见第八章）
│   ├── main.py                        # CLI 入口
│   ├── common.py                      # [修改] _load_context 增加 claims 多文件加载
│   ├── analyze/
│   │   ├── pipeline.py                # [重构] 集成 db 初始化、evidence 拆分输出
│   │   ├── tools.py                   # [修改] 删除 _archive_claims
│   │   ├── analysis.py               # [重构] 删除 _run_claim_tests
│   │   ├── reports.py                 # [修改] 适配新 evidence 格式
│   │   ├── output.py                  # [修改] 适配新 evidence 格式
│   │   └── ...
│   └── ...
├── domain/                            # 核心领域模块（见第八章）
│   ├── claim_loader.py                # [重构] 支持 CLAIM-*.json 多文件加载
│   ├── evidence_index_builder.py      # [重构] SQLite UPSERT + 拆分 JSON 输出
│   ├── merge_gate_engine.py           # [重构] SQL 驱动门禁判定
│   ├── ghost_code_reconciler.py       # [重构] 删除 git show，SQL 驱动
│   ├── context.py                     # [保留] tool_evidence 字段保留
│   ├── task_loader.py                 # [保留]
│   ├── prd_parser.py                  # [保留]
│   ├── raw_input_loader.py            # [修改] claims 加载改为 git staged 多文件
│   ├── tool_evidence_adapter.py       # [保留]
│   ├── architecture_compliance_checker.py  # [保留]
│   ├── risk_advisor.py                # [保留]
│   ├── traceability_report_builder.py # [修改] 适配新 evidence 格式
│   └── ...
├── analyzers/                         # Traceability 分析器（见第八章）
│   ├── ac_test_analyzer.py            # [保留] 接口不变
│   ├── claim_evidence_analyzer.py     # [保留] 接口不变
│   └── requirement_task_analyzer.py   # [保留] 接口不变
├── infra/                             # 基础设施（见第八章）
│   ├── db.py                          # [新建] 内存 SQLite 管理
│   ├── enums.py                       # ← core/enums.py
│   ├── governance.py                  # ← governance.py
│   ├── git_utils.py                   # ← git_utils.py
│   ├── operational_logger.py          # ← operational_logger.py
│   ├── hint_loader.py                 # ← hint_loader.py
│   ├── tool_resolver.py              # ← tool_resolver.py
│   └── validation/                    # [新建] 统一格式校验
│       ├── __init__.py
│       ├── checks.py                  # 校验入口（validate_inputs）
│       ├── ids.py                     # ← core/ids.py（ID 格式校验）
│       ├── schema_validator.py        # ← schema_validator.py（JSON Schema 校验）
│       └── schemas/                   # ← src/vibe_tracing/schemas/
│           ├── agent_claims.schema.json
│           ├── architecture_constraints.schema.json
│           ├── evidence_index.schema.json
│           ├── human_decisions.schema.json
│           ├── task_list.schema.json
│           └── traceability_report.schema.json
├── schemas/                           # [已删除] 迁入 infra/validation/schemas/
├── templates/
│   └── dashboard.template.html        # [修改] 适配扁平化 evidence 字段
└── ...

output/
├── evidences/                         # [新建目录]
│   ├── test_results.json              # [新建] 扁平化测试结果
│   └── coverage_reports.json          # [新建] 扁平化覆盖率
├── dashboard.html                     # [修改] 适配新字段
├── traceability_report.json           # [修改] 适配新 evidence 引用
└── evidence_index.json                # [删除]

.vibetracing/claims/
├── CLAIM-VT-001.json                  # [新建] 一任务一文件
├── CLAIM-VT-002.json
├── ...
├── current.json                       # [删除]
└── archive/                           # [删除]
```

---

## 三、 接口契约

> ⚠️ **目标状态声明**：以下接口契约描述的是**重构完成后的目标状态**，部分接口在当前代码中尚未实现（如 db.py 的 validate_* 函数迁移、EvidenceBuilder 类重命名等）。执行进度见 [`analyze_execution_plan.md`](analyze_execution_plan.md)。

### 3.1 `infra/db.py` — 内存数据库管理模块

```python
# ---- 初始化 ----

def init_in_memory_db() -> sqlite3.Connection:
    """创建内存 SQLite 数据库，执行 DDL 建表（8 张表），返回连接。"""

# ---- 格式校验（第一层）— 已移至 validation 模块 ----

> **架构决策**：所有第一层格式校验收拢到 `infra/validation/` 模块统一执行。db.py 不再包含格式校验函数，`load_*` 函数仅负责数据泵（INSERT）。
>
> 格式校验的接口定义见 `infra/validation/checks.py` 的 `validate_inputs(manifest, project_prefix, schemas_dir) -> PreImportResult`。

~~validate_task(task: dict) -> List[str]~~ → 迁移至 `validation/checks.py` 的 `_check_id_formats()` + JSON Schema 校验
~~validate_claim(claim: dict) -> List[str]~~ → 迁移至 `validation/checks.py` 的 `_check_id_formats()` + `_check_path_safety()` + JSON Schema 校验
~~validate_test_result(entry: dict) -> List[str]~~ → 待 Phase 3 创建 `test_results.schema.json` 后迁移
~~validate_coverage_report(entry: dict) -> List[str]~~ → 待 Phase 3 创建 `coverage_reports.schema.json` 后迁移

# ---- 数据泵（写入） ----

def load_tasks(conn, tasks: List[Task]) -> List[str]:
    """批量插入 tasks + task_acs。数据已通过 validation 模块校验，此处仅执行 INSERT。返回插入的记录列表。"""

def load_claims(conn, claims: List[Claim]) -> List[str]:
    """批量插入 claims + claim_code_refs + claim_test_refs。数据已通过 validation 模块校验，此处仅执行 INSERT。返回插入的记录列表。"""

def load_staged_files(conn, files: Set[str]) -> list:
    """插入 staged_files 表。返回插入的文件路径列表。"""

def load_initial_cache(conn, cache_dir: Path) -> None:
    """从 output/evidences/*.json 装载历史缓存，carried_over=1。"""

def upsert_test_result(conn, nodeid, outcome, exit_code, command, carried_over: bool) -> None:
    """INSERT OR REPLACE 写入 test_results。"""

def upsert_coverage_report(conn, source_path, percent_covered, num_statements, status, carried_over: bool) -> None:
    """INSERT OR REPLACE 写入 coverage_reports。"""

# ---- 关系校验（第二层） ----

def check_ac_coverage(conn) -> List[dict]:
    """SQL 查询未覆盖的 MUST AC。返回 [{ac_id, task_id, coverage_status}]。"""

def check_coverage_violations(conn) -> List[dict]:
    """SQL 查询 status='violated' 的覆盖率记录。"""

def check_ghost_code(conn) -> List[str]:
    """SQL 查询 staged 中未关联合法任务的文件列表。"""

def check_dangling_claims(conn) -> List[dict]:
    """SQL 查询指向不存在 Task 的 Claim。"""

def check_test_dead_links(conn) -> List[dict]:
    """SQL 查询 Claim 引用的测试不存在或未通过。
    SELECT ctr.claim_id, ctr.test_nodeid
    FROM claim_test_refs ctr
    LEFT JOIN test_results tr ON ctr.test_nodeid = tr.nodeid
    WHERE tr.nodeid IS NULL OR tr.outcome != 'passed';
    """

def check_active_task_coverage(conn) -> List[dict]:
    """SQL 查询活跃任务中文件的覆盖率违规/缺失。
    SELECT ccr.code_path, cr.percent_covered, cr.status
    FROM claim_code_refs ccr
    JOIN claims c ON ccr.claim_id = c.claim_id
    JOIN tasks t ON c.related_task = t.task_id
    LEFT JOIN coverage_reports cr ON ccr.code_path = cr.source_path
    WHERE t.status = 'in_progress' AND (cr.source_path IS NULL OR cr.status = 'violated');
    """

# ---- 数据泵（读取/导出） ----

def export_test_results(conn) -> List[dict]:
    """SELECT * FROM test_results，返回扁平 dict 列表。"""

def export_coverage_reports(conn) -> List[dict]:
    """SELECT * FROM coverage_reports，返回扁平 dict 列表。"""

def persist_evidences(conn, output_dir: Path) -> None:
    """将 test_results + coverage_reports 导出为 JSON 文件。"""
```

**DDL 表结构**（8 张表）：

| 表名 | 主键 | 外键 | 数据源 |
|---|---|---|---|
| `tasks` | `task_id` | — | `task_list.json` |
| `task_acs` | `(task_id, ac_id)` | —（软校验） | `task.related_acceptance_criteria` |
| `claims` | `claim_id` | —（软校验 via LEFT JOIN） | `CLAIM-*.json` 文件 |
| `claim_code_refs` | `(claim_id, code_path)` | —（软校验） | `claim.code_refs` |
| `claim_test_refs` | `(claim_id, test_nodeid)` | —（软校验） | `claim.test_refs` |
| `test_results` | `nodeid` | — | pytest 输出 + 历史缓存 |
| `coverage_reports` | `source_path` | — | coverage 输出 + 历史缓存 |
| `staged_files` | `file_path` | — | `git diff --cached` |

### 3.2 `domain/claim_loader.py` — 多文件 Claim 加载

```python
@dataclass
class Claim:
    claim_id: str
    related_task: str
    code_refs: List[str]
    test_refs: List[str]
    notes: str = ""
    content_hash: str = ""
    timestamp: str = ""
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)

@dataclass
class ClaimGap:
    """校验过程中发现的 Claim 问题。"""
    item_id: str
    item_type: str
    reason: str

@dataclass
class ClaimListLoadResult:
    """Claim 加载结果。"""
    claims: List[Claim]
    is_valid: bool
    errors: List[str]
    gaps: List[ClaimGap]

class ClaimLoader:
    def load(self) -> ClaimListLoadResult:
        """加载 .vibetracing/claims/CLAIM-*.json 所有文件。
        原方法名 load_and_validate()，重命名为 load()。"""

    def load_active(self, staged_files: Set[str]) -> List[Claim]:
        """仅返回 staged_files 中匹配的 CLAIM-*.json 对应的 Claim。"""

    def validate_data(self, data: dict, task_result, source_label: str) -> ClaimListLoadResult:
        """纯内存校验，不涉及文件 I/O。"""
```

**变更点**：
- 删除 `current.json` 读取逻辑
- 新增 glob `CLAIM-*.json` 批量加载
- `claimed_status` 字段移除（Claim 不再自证完成）
- `credibility` / `credibility_warnings` 字段移除
- `evidence_refs` 字段移除（Claim 降级为指针，不再自证证据链）
- `load_and_validate()` 重命名为 `load()`
- `ClaimListLoadResult` 和 `ClaimGap` 保留（当前代码中已存在）

### 3.3 `domain/evidence_index_builder.py` → `domain/evidence_builder.py`

```python
class EvidenceBuilder:  # 原名 EvidenceIndexBuilder
    def __init__(self, project_root: Path, conn: sqlite3.Connection): ...

    def build(self, ctx: UnifiedContext, tool_evidence: List[ToolEvidenceCandidate]) -> dict:
        """
        原签名: build(self, output_path: Path, ctx: Any, **kwargs) -> Dict
        新签名: build(self, ctx: UnifiedContext, tool_evidence: List[ToolEvidenceCandidate]) -> dict

        output_path 参数移除——输出路径由 db.persist_evidences(conn, output_dir) 管理。
        tool_evidence 参数新增——从 ctx.tool_evidence 解耦，改为显式传入。

        1. 调用 db.load_initial_cache() 装载历史缓存
        2. 遍历 tool_evidence，对 test/coverage 类型调用 upsert_*
        3. 调用 db.persist_evidences() 写入拆分 JSON
        4. 返回 summary dict（供 reports.py 使用）
        """
```

**变更点**：
- 类重命名 `EvidenceIndexBuilder` → `EvidenceBuilder`，文件重命名 `evidence_index_builder.py` → `evidence_builder.py`
- `build()` 删除 `output_path` 参数，新增显式 `tool_evidence` 参数
- 删除 mtime 比对逻辑（`_should_regenerate` 闭包）
- 删除 evidence_id 顺序编号
- 删除通用外壳 `details` 嵌套
- 输出拆分为 `test_results.json` + `coverage_reports.json`
- 接收 `sqlite3.Connection` 而非自行管理文件
- `SchemaValidator` 校验移至 `db.persist_evidences()` 内部（使用新的拆分 schema）

### 3.4 `domain/merge_gate_engine.py` — SQL 驱动判定

```python
class MergeGateEngine:
    def __init__(self, project_root: Path, conn: sqlite3.Connection): ...

    def evaluate(
        self,
        compliance_res: Optional[dict],
        staged_items: Optional[Set[str]],
        directly_staged_items: Optional[Set[str]],
        human_decisions: Optional[dict] = None,
    ) -> dict:
        """
        evaluate() 签名从 11 参数简化为 4 参数。

        原参数 gaps, risks, prd_status, evidence_index, claims, boundary, tasks
        全部改为内部 SQL 查询：
        - db.check_ac_coverage(conn) → 未覆盖 AC 列表（替代原 check_ac_coverage 静态方法）
        - db.check_coverage_violations(conn) → 覆盖率违规
        - db.check_test_dead_links(conn) → 测试死链
        - db.check_active_task_coverage(conn) → 活跃任务覆盖率
        结合 compliance_res、human_decisions 生成 gate_decision。
        """
```

**变更点**：
- `evaluate()` 签名从 11 参数简化为 4 参数——gaps/risks/claims/tasks/boundary 不再由调用方传入，改为内部 SQL 查询
- **删除** 静态方法 `check_claim_exists()`——替代方案：`db.check_ghost_code(conn)`
- **删除** 静态方法 `check_ac_coverage()`——替代方案：`db.check_ac_coverage(conn)`
- **修正**：原文档引用的 `_check_coverage_violations` 方法在当前代码中不存在，实际逻辑在 `_compute_gate_decision()` 内联实现（line 563-580），重构为独立的 `db.check_coverage_violations(conn)`
- `_is_current()` 和 `_tag_reason()` 辅助方法保留
- 接收 `sqlite3.Connection`，通过 SQL 查询获取判定数据

### 3.5 `domain/ghost_code_reconciler.py` — SQL 驱动幽灵检测

```python
class GhostCodeReconciler:
    def __init__(self, project_root: Path, conn: sqlite3.Connection): ...

    def reconcile(self, staged_files: Set[str]) -> Tuple[bool, str]:
        """
        Gate 2 主入口（保留原方法名，不重命名为 check）。

        1. db.load_staged_files(conn, staged_files)
        2. ghost_files = db.check_ghost_code(conn) — 幽灵代码检测
        3. _check_task_coverage(staged_files, active_code_refs) — 任务关联校验
        4. _check_ac_freshness() — AC 新鲜度检查（Gate 2.5）
        返回 (passed, message)
        """
```

**变更点**：
- 删除 `_get_active_claims_code_refs` 中的 `git show HEAD` 子进程
- 删除 `claims/current.json` 文件读取
- 活跃 Claim 识别改为：staged_files 匹配 `CLAIM-*.json`
- 幽灵代码检测改为 SQL LEFT JOIN
- **保留** `_check_task_coverage` 和 `_check_ac_freshness`（Gate 2.5 逻辑），这些不是简单 SQL 可替代的
- **保留** `_is_whitelisted` 白名单机制

### 3.6 `cli/analyze/pipeline.py` — 编排层

```python
def run_analyze(project_root, output_dir, is_pre_commit, gates_only) -> int:
    """
    重构后流程：
    1. _load_context() — 加载输入（含 CLAIM-*.json 多文件）
    2. conn = init_in_memory_db() — 创建内存数据库
    3. db.load_tasks(conn, tasks) — 灌入任务
    4. db.load_claims(conn, claims) — 灌入声明
    5. db.load_staged_files(conn, staged) — 灌入暂存区
    6. db.load_initial_cache(conn, output_dir) — 装载历史缓存
    7. _run_integrity_gates() — Gate 1/2/2.5 (内部调用 reconciler.reconcile())
    8. _execute_tools() — 工具执行 → ctx.tool_evidence
    9. evidence_builder.build(ctx, ctx.tool_evidence) — Upsert 新证据 → 导出拆分 JSON
    10. _run_analyzers() — 分析器（接口不变）
    11. MergeGateEngine(conn).evaluate() — SQL 驱动门禁
    12. _build_report_document() — 生成报告
    13. _render_output() — 渲染 Dashboard
    14. conn.close()
    """
```

**变更点**：
- 删除 `_archive_claims` 调用
- 删除 `_run_claim_tests`（claim tests 由 tool_evidence_adapter 统一处理）
- 新增 `init_in_memory_db` + 数据泵调用
- `MergeGateEngine` 和 `EvidenceBuilder` 接收 `conn`

### 3.7 数据流图

```
                    ┌─────────────────────────────────────────┐
                    │              vt analyze                  │
                    └────────────────┬────────────────────────┘
                                     │
                    ┌────────────────▼────────────────────────┐
                    │  1. _load_context()                     │
                    │     PRD → prd.md                        │
                    │     Tasks → task_list.json              │
                    │     Claims → CLAIM-*.json (glob)        │
                    │     Constraints → arch_constraints.json │
                    │     Config → config.json                │
                    └────────────────┬────────────────────────┘
                                     │
                    ┌────────────────▼────────────────────────┐
                    │  2. init_in_memory_db()                 │
                    │     CREATE TABLE tasks, claims, ...     │
                    │     (8 tables, in-memory)               │
                    └────────────────┬────────────────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
    ┌─────────▼──────────┐ ┌────────▼─────────┐ ┌──────────▼──────────┐
    │ 3. load_tasks()    │ │ 4. load_claims() │ │ 5. load_staged()    │
    │    + task_acs      │ │    + code_refs   │ │    staged_files表   │
    │    格式校验(第一层) │ │    + test_refs   │ │                     │
    │    FK 约束(第二层)  │ │    FK 约束       │ │                     │
    └─────────┬──────────┘ └────────┬─────────┘ └──────────┬──────────┘
              │                      │                      │
              └──────────────────────┼──────────────────────┘
                                     │
                    ┌────────────────▼────────────────────────┐
                    │  6. load_initial_cache()                │
                    │     test_results.json → test_results表  │
                    │     coverage_reports.json → coverage表  │
                    │     carried_over = 1                    │
                    └────────────────┬────────────────────────┘
                                     │
                    ┌────────────────▼────────────────────────┐
                    │  7. _run_integrity_gates()              │
                    │     Gate 1: 哈希校验                     │
                    │     Gate 2: 幽灵代码 (SQL)              │
                    │     Gate 2.5: AC 新鲜度                  │
                    └────────────────┬────────────────────────┘
                                     │
                    ┌────────────────▼────────────────────────┐
                    │  8. _execute_tools()                    │
                    │     pytest/ruff/bandit/coverage         │
                    │     → List[ToolEvidenceCandidate]       │
                    └────────────────┬────────────────────────┘
                                     │
                    ┌────────────────▼────────────────────────┐
                    │  9. EvidenceBuilder.build()             │
                    │     UPSERT test_results (carried=0)     │
                    │     UPSERT coverage_reports (carried=0) │
                    │     persist_evidences() → 拆分 JSON     │
                    └────────────────┬────────────────────────┘
                                     │
                    ┌────────────────▼────────────────────────┐
                    │  10. _run_analyzers()                   │
                    │      REQ→Task, AC→Test, Claim→Evidence │
                    │      接口不变，消费 evidence_list        │
                    └────────────────┬────────────────────────┘
                                     │
                    ┌────────────────▼────────────────────────┐
                    │  11. MergeGateEngine(conn).evaluate()   │
                    │      SQL: check_ac_coverage()           │
                    │      SQL: check_coverage_violations()   │
                    │      + compliance + human_decisions     │
                    │      → gate_decision                    │
                    └────────────────┬────────────────────────┘
                                     │
                    ┌────────────────▼────────────────────────┐
                    │  12-13. Report + Dashboard              │
                    │      traceability_report.json           │
                    │      dashboard.html (适配新字段)         │
                    └─────────────────────────────────────────┘
```

---

## 四、 文件级变更清单

### 4.1 新建文件

| 文件 | 职责 | 依赖 |
|---|---|---|
| `infra/db.py` | 内存 SQLite 管理、DDL、Upsert API、双层校验、SQL 查询 | `sqlite3`（标准库） |
| `infra/validation/schemas/test_results.schema.json` | test_results.json 的 JSON Schema | — |
| `infra/validation/schemas/coverage_reports.schema.json` | coverage_reports.json 的 JSON Schema | — |
| `infra/validation/schemas/claim_file.schema.json` | 单文件 CLAIM-*.json 的 JSON Schema | — |

### 4.2 重构文件

| 文件 | 变更 | 影响范围 |
|---|---|---|
| `domain/claim_loader.py` | 支持 `CLAIM-*.json` 多文件 glob 加载；删除 `claimed_status`、`credibility`、`evidence_refs` 字段 | Claim 数据类、ClaimLoader.load() |
| `domain/evidence_index_builder.py` | 重写为 `EvidenceBuilder`：基于 SQLite UPSERT + 拆分 JSON 输出；删除 mtime 缓存 | build() 签名和输出格式 |
| `domain/merge_gate_engine.py` | `check_ac_coverage` / `_check_coverage_violations` 改为 SQL 查询；构造函数接收 `conn` | evaluate() 内部实现 |
| `domain/ghost_code_reconciler.py` | 删除 `git show HEAD`；活跃 Claim 识别改为 staged 文件匹配；幽灵检测改为 SQL；保留 `reconcile()` 方法名和 Gate 2.5 逻辑 | reconcile() 内部实现 |
| `infra/db.py` | 删除 `validate_task`/`validate_claim`/`validate_test_result`/`validate_coverage_report` 函数；`load_*` 函数仅保留数据泵逻辑 | 数据泵不再执行格式校验 |
| `cli/analyze/pipeline.py` | 新增 db 初始化 + 数据泵调用；删除 `_archive_claims` 调用和 `_run_claim_tests` | run_analyze() 流程 |
| `cli/analyze/tools.py` | 删除 `_archive_claims` 函数 | 被 pipeline.py 不再调用 |
| `cli/analyze/analysis.py` | 删除 `_run_claim_tests`（claim tests 统一由 tool_evidence_adapter 处理） | pipeline.py 不再调用 |
| `cli/analyze/reports.py` | 适配 evidence 拆分格式：从 `evidence_index` dict 改为读取 `test_results` + `coverage_reports`；`run_id`/`project_id`/`scan_time` 从 ctx 提取 | report 数据源 |
| `cli/analyze/output.py` | 适配 evidence 拆分格式：Dashboard 内嵌数据从单一 `evidence_index` 改为三份 JSON | 渲染数据源 |
| `cli/common.py` | `_load_context` 中 claims 加载改为 glob 模式 | 所有调用方 |
| `domain/context.py` | 保留 `tool_evidence` 字段（内存传递载体）；删除 claims 归档相关 | pipeline 数据流 |
| `domain/traceability_report_builder.py` | 适配新的 evidence 引用格式 | 报告生成 |

### 4.3 删除文件/目录

| 文件/目录 | 原因 |
|---|---|
| `output/evidence_index.json` | 被拆分为 `output/evidences/` 下的多个文件 |
| `infra/validation/schemas/evidence_index.schema.json` | 被 `test_results.schema.json` + `coverage_reports.schema.json` 替代 |
| `.vibetracing/claims/current.json` | 被 `CLAIM-*.json` 多文件替代 |
| `.vibetracing/claims/archive/` | 归档机制废除 |

### 4.4 不变文件（重组后路径）

| 文件 | 理由 |
|---|---|
| `cli/main.py` | 入口不变，参数不变；需清理 `_archive_claims` / `_run_claim_tests` 的 re-export |
| `cli/analyze/gates.py` | Gate 1/2/2.5 逻辑不变（内部调用 `reconcile()`） |
| `cli/analyze/formatting.py` | 输出格式化不变 |
| `cli/analyze/actions.py` | Agent action 提取不变 |
| `cli/analyze/helpers.py` | 杂项辅助不变 |
| `domain/task_loader.py` | 任务加载逻辑不变 |
| `domain/prd_parser.py` | PRD 解析不变 |
| `domain/raw_input_loader.py` | [修改] claims 加载从单文件 `current.json` 改为 git staged 多文件 `CLAIM-*.json` |
| `domain/tool_evidence_adapter.py` | 工具执行引擎不变（输出 `ToolEvidenceCandidate`） |
| `domain/architecture_compliance_checker.py` | 架构合规检查不变 |
| `domain/risk_advisor.py` | 风险生成不变 |
| `analyzers/*.py` | 三个分析器接口不变 |
| `infra/enums.py` | 枚举不变 |
| `infra/validation/ids.py` | ID 生成不变 |
| `infra/governance.py` | 治理边界不变 |
| `infra/git_utils.py` | git 工具不变 |
| `infra/validation/schema_validator.py` | Schema 校验器不变 |
| `infra/validation/checks.py` | [新建] 统一格式校验入口 |
| `infra/validation/__init__.py` | [新建] 包入口 |
| `infra/operational_logger.py` | 日志不变 |
| `infra/hint_loader.py` | Hints 不变 |
| `infra/tool_resolver.py` | 工具检测不变 |
| `cli/init_cmd.py` | 需适配：不再生成 `current.json`，改为创建 `CLAIM-*.json` 模板目录 |
| `cli/finalize.py` | 不在范围 |
| `cli/accept.py` | 不在范围 |
| `cli/doctor.py` | 需适配：改用 `ClaimLoader.load()` + 读取 `test_results.json`/`coverage_reports.json` |
| `domain/architecture_compliance_checker.py` | 需适配：`_get_module_for_import` 兼容嵌套包路径（`vibe_tracing.domain.X`） |

---

## 五、 关键设计决策

### 5.1 `_run_claim_tests` 的去留

**现状**：`cli/analyze/analysis.py` 中的 `_run_claim_tests` 对每个 claim 的 test_refs 逐文件运行 pytest，使用 mtime 增量缓存。

**问题**：
- 与 `tool_evidence_adapter.py` 的 `ToolExecutionEngine` 职责重叠
- 自建 mtime 缓存，与 evidence_index_builder 的增量缓存机制重复
- 输出格式（`{status, num_tests, errors}`）与 `ToolEvidenceCandidate` 不一致

**决策**：删除 `_run_claim_tests`，claim 的 test_refs 统一由 `ToolExecutionEngine.execute_all()` 处理。`domain/tool_evidence_adapter.py` 已具备按文件执行 pytest 的能力，且输出标准化的 `ToolEvidenceCandidate`。

### 5.2 `UnifiedContext.tool_evidence` 的去留

**现状**：`ctx.tool_evidence` 存储 `List[ToolEvidenceCandidate]`，在 pipeline 中传递。

**决策**：保留。`tool_evidence` 仍是工具执行结果的内存传递载体，只是不再持久化到 evidence_index.json，而是通过 db UPSERT 写入 SQLite 后导出为拆分 JSON。

### 5.3 Traceability 分析器的接口

**现状**：`RequirementTaskAnalyzer.analyze()`、`AcTestAnalyzer.analyze()`、`ClaimEvidenceAnalyzer.analyze()` 接收 `evidence_list: list`（evidence_index 的 evidences 数组）。

**决策**：分析器接口不变。它们消费的是 evidence 的内存表示，不关心底层存储格式。evidence_list 仍从 db 中 SELECT 组装（或直接使用 tool_evidence_candidates 转换后的列表）。

### 5.4 Dashboard 数据源

**现状**：Dashboard 模板内嵌 `evidence_index.json` 和 `traceability_report.json`。

**决策**：Dashboard 改为内嵌 `test_results.json` + `coverage_reports.json` + `traceability_report.json`。模板中引用 evidence 的方式从 `e.details.outcome` 改为 `e.outcome`（扁平化）。

### 5.5 FK 约束策略：统一软校验

**决策**：所有表均使用软校验（LEFT JOIN），不设置硬性物理 FOREIGN KEY 约束。

**理由**：硬 FK 会在第一个错误记录时中断事务，导致用户无法一次性看到所有错误。例如同时提交 3 个 Claim 其中 2 个关联了不存在的 Task，硬 FK 只会报第一个错误。软校验通过 `check_dangling_claims(conn)` 一次性返回所有悬空声明，提供最佳的 Agent 批量报错体验。

**DDL 调整**：`claims` 表的 `related_task` 列不声明 `FOREIGN KEY`，仅作为普通 TEXT 列。关系校验完全由 `db.check_dangling_claims(conn)` 的 LEFT JOIN 查询负责。

**注意**：`init_in_memory_db()` 不需要执行 `PRAGMA foreign_keys = ON`（因为不使用硬 FK）。

### 5.6 `_check_coverage_violations` 的真实位置

**现状**：重构方案引用了一个名为 `_check_coverage_violations` 的方法，但当前代码中该方法不存在。覆盖率违规检查逻辑内联在 `_compute_gate_decision()` 方法中（line 563-580）。

**决策**：重构时从 `_compute_gate_decision()` 中提取该逻辑，实现为 `db.check_coverage_violations(conn)` 和 `db.check_active_task_coverage(conn)` 两个独立 SQL 查询函数。

### 5.7 `infra/db.py` 零依赖约束

`infra/db.py` 只能依赖 Python 标准库（`sqlite3`、`json`、`re`、`pathlib`），不得导入任何 `vibe_tracing.*` 模块。这保证 `infra/` 包是叶子依赖，不会引入循环导入。数据类（`Task`、`Claim`）以普通 dict 形式传入 db 函数，不要求 db 模块感知数据类定义。

### 5.8 陈旧缓存失效机制

**问题**：UPSERT 只能覆盖已存在的 key。如果用户删除或重命名了测试用例（如 `test_old` → `test_new`），旧记录 `test_old` 不会被新结果覆盖，将永久残留在 `test_results.json` 中形成"幽灵测试"。

**决策**：在 UPSERT 新证据之前，按目标文件清理旧缓存：
```python
def purge_stale_cache(conn, target_files: List[str]) -> None:
    """清除目标文件对应的 carried_over 缓存，防止幽灵测试。"""
    for f in target_files:
        conn.execute("DELETE FROM test_results WHERE (nodeid LIKE ? OR nodeid = ?) AND carried_over = 1",
                     (f"{f}::%", f))
        conn.execute("DELETE FROM coverage_reports WHERE source_path = ? AND carried_over = 1", (f,))
```

**调用时机**：在 `EvidenceBuilder.build()` 中，遍历 `tool_evidence` 执行 UPSERT 之前，先调用 `purge_stale_cache(conn, target_files)` 清理本次运行涉及的文件的旧缓存。

**补充**：`load_initial_cache()` 加载历史 JSON 时，应检查文件在磁盘上是否物理存在，已删除的文件不予载入。

### 5.9 活跃声明（Active Claims）识别范围

**问题**：仅通过 `git diff --cached` 识别暂存区中的 `CLAIM-*.json`，在本地开发预览（未 `git add`）时无法识别刚修改的 Claim。

**决策**：活跃声明识别整合三个来源：
1. `git diff --cached --name-only`（已暂存）
2. `git diff --name-only`（已修改未暂存）
3. `git status --porcelain`（未跟踪的新文件）

三者合并后匹配 `CLAIM-*.json` 模式。仅在 `--pre-commit` 模式下仅使用 `git diff --cached`（因为 hook 只关心暂存区）。

**实现位置**：`cli/common.py` 的 `_get_staged_files()` 函数扩展为 `_get_active_files(is_pre_commit: bool)`。

---

## 六、 Dashboard 模板迁移计划

Dashboard 模板（`templates/dashboard.template.html`，144KB）深度耦合当前 evidence 格式。以下列出所有受影响的 JavaScript 函数和数据绑定。

### 6.1 模板变量变更

| 现状 | 目标 |
|---|---|
| `evidence_idx_json`（单一 JSON blob） | `test_results_json` + `coverage_reports_json`（两份 JSON） |
| `evidenceIndex.evidences[]`（扁平数组） | `testResults[]` + `coverageReports[]`（两个数组） |
| `e.evidence_id`（顺序编号） | `e.nodeid`（测试）/ `e.source_path`（覆盖率）作为天然主键 |
| `e.details.outcome` / `e.details.tool_category` | `e.outcome` / 直接字段（扁平化） |

### 6.2 受影响的 JavaScript 函数

| 函数/变量 | 影响 | 迁移动作 |
|---|---|---|
| `jumpToEvidence(evidence_id)` | `evidence_id` 被删除 | 改为 `jumpToTest(nodeid)` + `jumpToCoverage(source_path)` |
| `reqCoverageMap` 构建逻辑 | 从 `evidences[]` 遍历构建 | 改为从 `testResults[]` + `coverageReports[]` 分别构建 |
| `itemEvidenceMap` 构建逻辑 | 同上 | 同上 |
| `renderCoverageHeatmap()` | 读取 `evidenceIndex.evidences` | 改为读取 `coverageReports[]` |
| Claim-Evidence 关联渲染（~line 2826-2860） | 通过 `evidence_id` 匹配 | 改为通过 `nodeid` / `source_path` 匹配 |
| Evidence Tab 渲染（~line 1526-1561） | 遍历单一 `evidences` 数组 | 改为分别渲染 Test Results 和 Coverage 两个子 Tab |
| 搜索功能（~line 2190） | 搜索 `e.details` 嵌套字段 | 改为搜索扁平字段 |

### 6.3 迁移策略

1. **模板注入**：`output.py` 的 `_render_dashboard()` 需要将 `test_results_json` 和 `coverage_reports_json` 分别注入模板
2. **向后兼容**：迁移期间可保留 `evidenceIndex` 变量作为 wrapper（`{testResults: [], coverageReports: []}`），逐步替换引用
3. **测试方法**：迁移完成后运行 `vt analyze`，在浏览器中打开 `output/dashboard.html` 验证所有 Tab 渲染正常

---

## 七、 测试迁移计划

### 7.1 受影响的测试文件（18 个）

| 模块 | 受影响的测试文件 | 主要变更 |
|---|---|---|
| `merge_gate_engine` | `test_merge_gate_engine.py`, `test_quality_gates.py`, `test_integration_v3.py`, `test_e2e_samples.py`, `test_e2e_finalize_analyze.py`, `test_analyze_refactor_integration.py`, `test_self_governance.py` | 构造函数改为 `(project_root, conn)`；`evaluate()` 签名简化；删除 `check_claim_exists` / `check_ac_coverage` 静态方法测试 |
| `claim_loader` | `test_claim_loader.py`, `test_dynamic_hints.py`, `test_evidence_index_builder.py`, `test_ac_vt_009_coverage.py`, `test_claim_evidence_analyzer.py` | `Claim` 字段变更（删除 `claimed_status`、`credibility`、`evidence_refs`）；`load_and_validate()` → `load()` |
| `evidence_index_builder` | `test_evidence_index_builder.py`, `test_schema_contracts.py`, `test_unified_context.py` | 类重命名 `EvidenceIndexBuilder` → `EvidenceBuilder`；构造函数接收 `conn`；输出格式变更 |
| `ghost_code_reconciler` | `test_ghost_code_reconciler.py`, `test_integration_v3.py` | 构造函数改为 `(project_root, conn)`；`reconcile()` 内部逻辑变更 |
| `pipeline` | `test_cli_analyze.py` | 流水线流程变更 |

### 7.2 被删除函数的测试清理

| 被删除函数 | 受影响的测试文件 | 测试方法 |
|---|---|---|
| `_archive_claims` | `test_integration_v3.py` | `TestArchiveClaims`（4 个方法）— 删除整个测试类 |
| `_run_claim_tests` | `test_integration_v3.py` | `TestRunClaimTests`（4 个方法）— 删除整个测试类 |
| `_run_claim_tests` | `test_timing_instrumentation.py` | `TestRunClaimTestsTiming`（4 个方法）— 删除整个测试类 |
| `_run_claim_tests` | `test_instrumentation_logging.py` | `TestClaimTestCacheStats` — 删除整个测试类 |
| `_run_claim_tests` | `claim_evidence_analyzer.py` | 注释引用 — 更新注释 |

### 7.3 迁移策略

1. **Phase 1**：实现 `infra/db.py`，编写 `tests/test_db_schema.py` 和 `tests/test_db_import.py`（新测试）
2. **Phase 2**：重构 `domain/claim_loader.py`，更新 `test_claim_loader.py`
3. **Phase 3**：重构 `domain/evidence_index_builder.py` → `domain/evidence_builder.py`，重写 `test_evidence_index_builder.py`
4. **Phase 4**：重构 `domain/merge_gate_engine.py`，更新 `test_merge_gate_engine.py`
5. **Phase 5**：重构 `domain/ghost_code_reconciler.py`，更新 `test_ghost_code_reconciler.py`
6. **Phase 6**：重构 `cli/analyze/pipeline.py`，更新 `test_cli_analyze.py`；清理被删除函数的测试
7. **Phase 7**：迁移 Dashboard 模板，端到端验证

每个 Phase 完成后运行 `pytest` 确认绿灯再进入下一 Phase。

> 注意：以下文件路径为重组前路径。实际执行时应先完成第八章目录重组，再按本章 Phase 执行重构。

---

## 八、 目录重组与实施计划

> 本章内容已迁移至独立文档：
> - **目录重组映射表 + Phase 详细任务清单** → [`analyze_execution_plan.md`](analyze_execution_plan.md)
> - **架构愿景** → [`architecture_vision.md`](architecture_vision.md)
