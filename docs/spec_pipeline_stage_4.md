# 阶段 4 模块详解

## 1. 输入来源

| 来源 | 包/模块 | 文件 |
|------|---------|------|
| **无外部输入** | `infra/db/schema.py` | 无（纯函数调用，无文件读取） |

> `init_in_memory_db()` 无参数，不接收任何文件或上下文数据。它创建一个空的内存数据库，随后由阶段 5 灌入数据。

---

## 2. 输入结构

**无输入**。`init_in_memory_db()` 是一个零参数的工厂函数，其唯一的"输入"是 `infra/db/schema.py` 中硬编码的 DDL（数据定义语言）。

本阶段的实质输出是数据库 Schema，因此用本节展示 Schema 的 15 张表结构。

### 数据库 Schema（15 张建表语句）

**创建位置**：内存（由 `infra/db/schema.py:init_in_memory_db()` 执行 DDL）
**包/模块**：`infra/db/__init__.py`（通过 `__init__.py` 导出）

```yaml
# ──────────────────── 任务域（4 张表）────────────────────
tasks:                               # 任务主表
  task_id: "TASK-VT-001"             # 任务 ID（主键）
  priority: "must"                   # 优先级："must" | "should" | "could"
  status: "in_progress"              # 状态："todo" | "in_progress" | "done"

task_requirements:                   # 任务-需求关联表（多对多）
  task_id: "TASK-VT-001"            # 任务 ID
  req_id: "REQ-VT-001"              # 需求 ID

task_acs:                            # 任务-验收标准关联表（多对多）
  task_id: "TASK-VT-001"            # 任务 ID
  ac_id: "AC-VT-001-01"             # 验收标准 ID

# ──────────────────── Claim 域（3 张表）────────────────────
claims:                              # Claim 主表（开发声明）
  claim_id: "CLAIM-VT-001"          # Claim ID（主键）
  related_task: "TASK-VT-001"       # 关联的任务 ID

claim_code_refs:                     # Claim-代码文件关联表（一对多）
  claim_id: "CLAIM-VT-001"          # Claim ID
  code_path: "src/module.py"        # 代码文件路径

claim_test_refs:                     # Claim-测试节点关联表（一对多）
  claim_id: "CLAIM-VT-001"          # Claim ID
  test_nodeid: "tests/test_module.py::test_func"  # 测试节点 ID

# ──────────────────── 测试与覆盖率域（2 张表）────────────────────
test_results:                        # 测试执行结果表
  nodeid: "tests/test_module.py::test_func"  # 测试节点 ID（主键）
  outcome: "passed"                  # 测试结果："passed" | "failed" | "skipped"
  exit_code: 0                       # 退出码（整数）
  command: "pytest -k test_func"     # 执行命令（可选）
  carried_over: 0                    # 是否历史缓存数据：0=本次执行 | 1=历史缓存

coverage_reports:                    # 覆盖率报告表
  source_path: "src/module.py"       # 代码文件路径（主键）
  percent_covered: 85.5              # 覆盖率百分比（实数）
  num_statements: 200                # 总语句数（可选）
  status: "violated"                 # 覆盖状态："violated" | "covered" | "not_covered"
  carried_over: 0                    # 是否历史缓存数据：0=本次执行 | 1=历史缓存

# ──────────────────── Git 暂存区（1 张表）────────────────────
staged_files:                        # Git 暂存区文件表
  file_path: "src/module.py"        # 暂存区文件路径（主键）

# ──────────────────── PRD 域（2 张表）────────────────────
requirements:                        # 需求表（从 PRD 解析而来）
  req_id: "REQ-VT-001"              # 需求 ID（主键）
  title: "全链路需求追踪"              # 需求标题
  priority: "must"                   # 优先级："must" | "should" | "could" | "unclear"
  category: "functional"             # 类别："functional" | "quality_evolution" | "unclear"

acceptance_criteria:                 # 验收标准表（从 PRD 解析而来）
  ac_id: "AC-VT-001-01"             # 验收标准 ID（主键）
  req_id: "REQ-VT-001"              # 所属需求 ID
  title: "需求必须能关联任务"           # 验收标准标题
  is_testing_required: 1             # 是否必须有测试：0=否 | 1=是

# ──────────────────── 架构域（4 张表，含 IF NOT EXISTS）────────────────────
arch_modules:                        # 架构模块表
  module_id: "MOD-VT-001"           # 模块 ID（主键）

arch_constraints:                    # 架构约束表
  constraint_id: "PRINCIPLE-VT-006" # 约束 ID（主键，涵盖所有约束类型）

task_modules:                        # 任务-模块关联表（多对多）
  task_id: "TASK-VT-001"            # 任务 ID
  module_id: "MOD-VT-001"           # 模块 ID

task_constraints:                    # 任务-约束关联表（多对多）
  task_id: "TASK-VT-001"            # 任务 ID
  constraint_id: "PRINCIPLE-VT-006" # 约束 ID
```

---

## 3. 处理逻辑

`init_in_memory_db()` 的处理过程极其简单，仅 1 步：

### 步骤 1：创建内存 SQLite 数据库并建表

调用模块：`infra/db/schema.py:init_in_memory_db()`

1. 通过 `sqlite3.connect(":memory:")` 在内存中创建一个空的 SQLite 数据库连接。
2. 设置两个 PRAGMA 优化参数：`journal_mode=OFF`（禁用日志，提高写入性能）和 `synchronous=OFF`（关闭同步写入，进一步提升写入速度）。这两个设置适用于临时内存数据库，因为重启后数据不需要持久化。
3. 通过 `conn.executescript()` 一次执行完整的 DDL 脚本，创建全部 15 张表。
4. 返回数据库连接对象给调用方。

> **为什么是内存数据库？** 所有分析数据（PRD、Tasks、Claims、测试结果、覆盖率）在每次 `vt analyze` 时重新构建，不需要长期持久化。使用内存 SQLite 避免了磁盘 I/O 的额外开销，且流水线结束后连接自动关闭。

---

## 4. 输出结构

**输出类型**：`sqlite3.Connection`
**输出位置**：内存（通过 pipeline 局部变量 `conn` 传递，流水线结束后 `conn.close()` 关闭）

### sqlite3.Connection（内存 SQLite 数据库连接）

**包/模块**：`infra/db/schema.py:init_in_memory_db()`

```yaml
# 数据库连接对象（无结构化字段，本节点明其状态与特征）
type: "sqlite3.Connection"
mode: ":memory:"                     # 仅存在于内存中，不写磁盘
tables_count: 15                     # 共 15 张表
optimizations:                       # PRAGMA 优化设置
  journal_mode: "OFF"               # 禁用 WAL 日志，无持久化需求
  synchronous: "OFF"                 # 关闭同步写入，提高速度
```

**用途**：返回的数据库连接是后续所有分析的基础设施。阶段 5 将 PRD、Tasks、Claims、架构约束灌入数据库；阶段 6 写入证据数据；阶段 7 通过 SQL 查询执行各种校验分析；阶段 8 从数据库提取全链路追踪数据用于报告生成。

---

## 5. 异常捕获与日志

### 异常情况

| 异常类型 | 退出码 | 触发条件 |
|----------|--------|----------|
| `sqlite3.OperationalError` | 1 | SQLite 建表失败（极罕见，如 Python 运行时内置 SQLite 异常） |

> 本阶段本身无 try/except 块，异常会传播到 `run_analyze()` 的外层 try/except（见下方错误传播）。

### 日志事件

本阶段不记录日志。日志由阶段 1 的 `phase_end` 和阶段 6 的 `phase_end` 覆盖，`init_in_memory_db()` 本身的耗时极短（毫秒级），不单独监控。

### 错误传播

本阶段在 `run_analyze()` 的顶级 `try` 块内执行（第 192 行）。如果 `init_in_memory_db()` 抛出异常，由以下两个路径处理：

1. **`sqlite3.OperationalError`**：传播到第 407 行的 `except Exception as exc` 通用捕获点，打印 "Unexpected error running analyze command: {exc}"，返回退出码 1。
2. **`_GateBlocked`**：由第 405 行的 `except _GateBlocked as exc` 捕获，返回 `exc.exit_code`。

---

## 6. 下游依赖

| 下游模块 | 目标包 | 说明 |
|----------|--------|------|
| **阶段 5：灌入基础数据** | `infra/db/loaders.py` | 将 PRD 的需求/AC 写入 `requirements` / `acceptance_criteria` 表；将 Tasks 写入 `tasks` / `task_requirements` / `task_acs` / `task_modules` / `task_constraints` 表；将 Claims 写入 `claims` / `claim_code_refs` / `claim_test_refs` 表；将架构约束写入 `arch_modules` / `arch_constraints` 表 |
| **阶段 6：构建证据** | `domain/evidence/builder.py` | 将工具执行结果（证据数据）通过 `EvidenceBuilder.apply()` 写入 `test_results` / `coverage_reports` 表 |
| **阶段 7：运行分析** | `infra/db/queries.py` | 执行 11 种 SQL 查询（`check_requirement_coverage`、`check_ac_coverage`、`check_claim_evidence`、`check_ghost_code`、`check_dangling_claims`、`check_coverage_violations`、`check_invalid_task_*`、`check_isolated_tasks`、`check_architectural_orphans`），从 15 张表中读取数据，生成缺口（gaps）和风险 |
| **阶段 8：门禁判定 + 输出** | `infra/db/queries.py:get_full_chain()` | 从数据库提取需求→AC→任务→Claim→测试→覆盖率的全链路追踪数据，用于报告生成和 Dashboard 渲染 |
| **infra/db/exports.py** | `infra/db/exports.py:persist_evidences()` | 将数据库中的测试结果和覆盖率数据导出为 JSON 文件写入硬盘（用于缓存供下次分析使用） |
