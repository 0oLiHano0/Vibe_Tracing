# 阶段 6 模块详解

## 1. 输入来源

| 来源 | 包/模块 | 文件 |
|------|---------|------|
| **工具执行结果** | `infra/tools/executor.py` | 内存（阶段 3 返回的 `tool_evidence`） |
| **数据库连接** | `infra/db/schema.py` | 内存（阶段 4 创建的内存 SQLite 连接） |
| **项目根目录** | `cli/main.py` | 命令行参数传入 |
| **输出目录** | `cli/main.py` / `config.json` | 由 `resolve_path()` 解析 |
| **历史证据缓存** | `infra/db/loaders.py` | 硬盘文件 `output/evidences/test_results.json` + `output/evidences/coverage_reports.json` |

---

## 2. 输入结构

### ToolEvidenceCandidate（工具证据候选，来自阶段 3）

**输入位置**：内存（由 `ToolExecutionEngine.execute_from_claims()` 返回，经 `result.candidates` 传递）
**包/模块**：`domain/evidence/candidate.py:ToolEvidenceCandidate`

```yaml
# 工具执行引擎产出的标准化证据候选列表
source_type: "test"                     # 证据来源类型："test"（pytest 产出）| "tool"（其他工具产出）
source_path: "tests/test_cli.py::test_init"  # 证据源路径：测试 nodeid（test 类）或报告文件路径（tool 类）
covers:                                 # 此证据关联的 AC/REQ ID 列表
  - "AC-VT-001-01"
  - "AC-VT-002-01"
status: "covered"                       # 执行状态，CoverageStatus 枚举值。各 parser 已将工具原生结果映射为："covered" | "violated" | "skipped" | "blocked" | "compliant" | "unclear" 等（完整枚举见 infra/config/enums.py:CoverageStatus）
tool_category: "test"                   # 工具类别："test" | "lint" | "type_check" | "security" | "coverage"
command: "pytest tests/ --json"         # 执行的完整命令
exit_code: 0                            # 子进程退出码
stderr: ""                              # 标准错误输出
error_code: null                        # 错误码（ErrorCode 枚举，如 "tool_execution_failed"），无错误时为 null
details:                                # 工具特定详情
  percent_covered: 85.5                 # 覆盖率百分比（coverage 类）
  num_statements: 120                   # 语句总数（coverage 类）
  error_type: ""                        # 错误类型："timeout" | "tool_not_found" | "unknown"
  timeout_seconds: 0                    # 超时秒数
```

### sqlite3.Connection（内存数据库连接）

**输入位置**：内存（由 `init_in_memory_db()` 创建，阶段 4-5 已灌入 tasks/claims/requirements/ACs/staged_files）
**包/模块**：`sqlite3.Connection`

数据库在阶段 6 开始时已包含以下表的数据：
- `tasks`：任务列表
- `task_requirements`、`task_acs`：任务关联关系
- `claims`、`claim_code_refs`、`claim_test_refs`：Claim 及其引用
- `requirements`、`acceptance_criteria`：PRD 需求及 AC
- `staged_files`：暂存区文件列表
- `arch_modules`、`arch_constraints`、`task_modules`、`task_constraints`：架构约束数据
- `test_results`、`coverage_reports`：历史缓存数据（`load_initial_cache()` 在阶段 6 内部加载）

### 历史证据缓存文件

**输入位置**：硬盘文件（`output/evidences/test_results.json` + `output/evidences/coverage_reports.json`）
**包/模块**：`infra/db/loaders.py:load_initial_cache()`

```yaml
# test_results.json（历史测试结果缓存）
- nodeid: "tests/test_gate.py::test_evaluate_pass"     # pytest nodeid
  outcome: "covered"                                    # 覆盖状态（CoverageStatus 枚举值，取自 ev.status）："covered" | "violated" | "skipped" | "blocked" | "unclear" 等。pytest 原生 outcome（"passed"/"failed"/"error"）已由 parser 映射为 CoverageStatus
  exit_code: 0                                          # 子进程退出码
  command: "pytest tests/test_gate.py -v"               # 执行命令
  carried_over: false                                   # 是否从上一轮继承（写入时固定为 false，加载时标记为 true）

# coverage_reports.json（历史覆盖率报告缓存）
- source_path: "src/vibe_tracing/domain/gate/engine.py" # 源码文件路径
  percent_covered: 85.5                                 # 覆盖率百分比
  num_statements: 120                                   # 语句总数
  status: "covered"                                     # 覆盖状态（CoverageStatus 枚举值，由 builder 从 ev.status 透传）。完整枚举值见 infra/config/enums.py:CoverageStatus，包括 covered / partial / missing / unclear / low_confidence / blocked / compliant / violated / skipped / needs_reverification 等 10 个值
  carried_over: false                                   # 是否从上一轮继承
```

---

## 3. 处理逻辑

阶段 6 由 pipeline 内联编排，分为 5 个步骤：

### 步骤 1：实例化证据构建器

调用模块：`domain/evidence/builder.py:EvidenceBuilder.__init__()`

创建 `EvidenceBuilder` 实例，仅持有 `project_root`，不持有数据库连接。此设计遵循"构造完成才可用"原则——`EvidenceBuilder` 在构造后即处于可用状态。

---

### 步骤 2：合并新旧证据（merge）

调用模块：`domain/evidence/builder.py:EvidenceBuilder.merge()`

将阶段 3 产出的 `tool_evidence` 列表（本次工具执行的新证据）按 `source_type` 分类处理，生成结构化的 `EvidenceMergeResult`：

1. **遍历** `tool_evidence` 列表中的每个候选证据。

2. **测试类证据**（`source_type == "test"`）：
   - 从 nodeid 中提取裸文件路径（取 `::` 之前的部分）
   - 将文件路径加入 `files_to_purge` 列表（用于后续清除该文件的陈旧缓存）
   - 生成测试结果条目（含 nodeid、outcome、exit_code、command），`carried_over` 标记为 `false`（表示本次执行产生）

3. **覆盖率类证据**（`source_type == "coverage"`，或 `source_type == "tool"` 且 `tool_category == "coverage"`）：
   - 从 `details` 中提取 `percent_covered` 和 `num_statements`
   - 生成覆盖率报告条目（含 source_path、percent_covered、num_statements、status），`carried_over` 标记为 `false`

4. **其他类型证据**：
   - 归入 `skipped_evidence`，标注原因（如 "Unknown source_type"）

5. **去重**：对 `files_to_purge` 做集合去重。

6. **统计**：汇总 test_count、coverage_count、skipped_count、purge_count。

此步骤是**纯数据处理**，不访问数据库或文件系统。

---

### 步骤 3：应用到数据库（apply）

调用模块：`domain/evidence/builder.py:EvidenceBuilder.apply()` → 内调 `infra/db/` 模块

将合并结果写入内存 SQLite 数据库，分为 3 个子步骤：

**3a. 加载历史缓存**

调用模块：`infra/db/loaders.py:load_initial_cache()`

从 `project_root/output/evidences/` 目录读取上一轮的持久化文件（路径由 builder.py:98 硬编码为 `self.project_root / "output" / "evidences"`，不依赖 config.json 或 resolve_path() 的输出目录配置）：
- 读取 `test_results.json` → 逐条 INSERT OR REPLACE 到 `test_results` 表，`carried_over` 标记为 `1`（表示继承自缓存）
- 读取 `coverage_reports.json` → 逐条 INSERT OR REPLACE 到 `coverage_reports` 表，`carried_over` 标记为 `1`。跳过源文件已不存在的记录（防止幽灵覆盖率残留）

判定逻辑：缓存文件不存在时静默跳过（首次运行场景）；文件损坏（JSON 解析失败或不可读）时抛出 `ValueError`。

> 缓存记录中缺失的字段使用以下默认值：`outcome` 默认 `"violated"`、`exit_code` 默认 `-1`、`percent_covered` 默认 `0.0`、`status` 默认 `"violated"`（`loaders.py:147-148, 171-173`）。这是防御性设计，防止部分损坏或手动编辑的缓存文件导致不可预知的行为。

**3b. 清除陈旧缓存**

调用模块：`infra/db/exports.py:purge_stale_cache()`

对 `merge_result.files_to_purge` 中的每个文件路径：
- 从 `test_results` 表删除 `carried_over = 1` 且 nodeid 匹配该路径的记录（nodeid 以 `{file_path}::` 开头或精确相等）
- 从 `coverage_reports` 表删除 `carried_over = 1` 且 source_path 匹配该路径的记录

判定逻辑：`files_to_purge` 为空时跳过此步骤。

**3c. 写入新证据**

调用模块：`infra/db/exports.py:upsert_test_result()` + `upsert_coverage_report()`

对 `merge_result` 中的每条测试结果和覆盖率报告，逐条 INSERT OR REPLACE（`carried_over = 0`）。

> 每条记录写入后都立即执行 `conn.commit()`（`exports.py:23, 41`），即 upsert_test_result() 和 upsert_coverage_report() 各自包含一次 commit。这意味着大量证据写入时会产生多次事务提交，可能影响性能。此设计优先保证每条写入的原子性——即使中途崩溃，已提交的数据也不会丢失。

判定逻辑：新数据与缓存发生主键冲突时，新数据覆盖旧数据（INSERT OR REPLACE 语义）。

---

### 步骤 4：持久化到硬盘（persist）

调用模块：`domain/evidence/builder.py:EvidenceBuilder.persist()`

将 `merge_result` 的测试结果和覆盖率报告从内存写入硬盘文件，**不依赖数据库连接**：
- 创建 `output_dir/evidences/` 目录（不存在则自动创建），其中 `output_dir` 由 pipeline 传入（通过 `resolve_path()` 从 config 解析），**与 apply() 内部硬编码的 `self.project_root / "output" / "evidences"` 路径构造方式不同**
- 写入 `test_results.json`（JSON 格式化输出，UTF-8 编码）
- 写入 `coverage_reports.json`（同上）

返回写入的文件路径字典（`evidences_dir`、`test_results_file`、`coverage_reports_file`）。

判定逻辑：写入采用覆盖模式，每次运行生成最新的缓存快照。

---

### 步骤 5：构建证据元数据

调用模块：`infra/db/queries.py:get_full_chain()`

从内存 SQLite 数据库获取全链路追踪视图（requirements → ACs → tasks → claims → test_results + coverage_reports 的多表 LEFT JOIN），构造 `evidence_meta` 字典：

```yaml
run_id: "RUN-{uuid}"                    # 本次运行的唯一标识
project_id: "PROJECT-{config_prefix}"   # 项目标识
scan_time: ""                           # 扫描时间（当前为空字符串，由报告层填充）
full_chain: [...]                       # 全链路追踪数据（由 get_full_chain() 返回）
```

此步骤替代了之前的 `evidence_dicts` 中间层，直接从数据库获取全链路数据供阶段 8 报告使用。

判定逻辑：整个阶段 6 被 `try/except` 包裹——任何异常打印错误信息并返回退出码 `1`。

---

## 4. 输出结构

### EvidenceMergeResult（合并结果，内存）

**输出类型**：`EvidenceMergeResult`
**输出位置**：内存（通过 pipeline 局部变量传递）
**包/模块**：`domain/evidence/merge_result.py:EvidenceMergeResult`

```yaml
test_results_to_upsert:                 # 待写入数据库的测试结果
  - nodeid: "tests/test_gate.py::test_evaluate_pass"  # pytest nodeid
    outcome: "covered"                  # 覆盖状态（CoverageStatus 枚举值，由 parser 从 pytest outcome 映射而来）
    exit_code: 0                        # 退出码
    command: "pytest tests/"            # 执行的命令
    carried_over: false                 # 是否为历史缓存继承（本次执行产出均为 false）
coverage_reports_to_upsert:             # 待写入数据库的覆盖率报告
  - source_path: "src/domain/gate/engine.py"  # 源码文件路径
    percent_covered: 85.5               # 覆盖率百分比
    num_statements: 120                 # 语句总数
    status: "covered"                   # 覆盖状态（CoverageStatus 枚举值，由 builder 从 ev.status 透传）。完整枚举值见 infra/config/enums.py:CoverageStatus，包括 covered / partial / missing / unclear / low_confidence / blocked / compliant / violated / skipped / needs_reverification 等 10 个值
    carried_over: false                 # 是否为历史缓存继承
files_to_purge:                         # 需清除陈旧缓存的源文件路径列表
  - "tests/test_gate.py"
  - "tests/test_engine.py"
skipped_evidence:                       # 被跳过的证据（类型未知等）
  - source_path: "..."
    source_type: "unknown"
    reason: "Unknown source_type: unknown"
stats:                                  # 合并统计
  test_count: 15                        # 测试结果总数
  coverage_count: 8                     # 覆盖率报告总数
  skipped_count: 0                      # 被跳过的证据数
  purge_count: 3                        # 应清除的陈旧缓存文件数
```

**用途**：`EvidenceMergeResult` 是 merge 阶段的唯一输出，供 apply() 写入数据库和 persist() 导出 JSON。外部模块（阶段 7-8）不直接消费此对象，它们通过数据库查询获取证据数据。

---

### evidence_meta（证据元数据，内存）

**输出类型**：`Dict[str, Any]`
**输出位置**：内存（通过 pipeline 局部变量传递到阶段 8）
**包/模块**：pipeline 内联构建（`cli/analyze/pipeline.py`）

```yaml
run_id: "RUN-a1b2c3d4"                  # 本次运行的唯一标识
project_id: "PROJECT-VT"                # 项目标识
scan_time: ""                           # 扫描时间（由报告层填充）
full_chain:                             # 全链路追踪数据（requirements → tests 的一条或多条 JOIN 行）
  - req_id: "REQ-VT-001"                # 需求 ID
    req_title: "全链路需求追踪"          # 需求标题
    req_priority: "must"                # 需求优先级
    req_category: "functional"          # 需求类别
    ac_id: "AC-VT-001-01"               # AC ID（可能为 null）
    ac_title: "需求必须能关联任务"       # AC 标题（可能为 null）
    is_testing_required: true            # 是否必须有测试（可能为 null）
    task_id: "TASK-VT-001"              # 任务 ID（可能为 null）
    task_priority: "must"               # 任务优先级（可能为 null）
    task_status: "done"                  # 任务状态（可能为 null）
    claim_id: "CLAIM-VT-001"            # Claim ID（可能为 null）
    test_nodeid: "tests/test_cli.py::test_init"  # 测试 nodeid（可能为 null）
    test_outcome: "covered"             # 测试结果（CoverageStatus 枚举值，如 "covered"/"violated"，可能为 null）
    code_path: "src/cli/main.py"        # 代码文件路径（可能为 null）
    percent_covered: 85.5               # 覆盖率百分比（可能为 null）
```

**用途**：供阶段 8 `_build_report_document()` 生成追溯报告和 Dashboard 模板渲染。是"证据"概念在整个流水线中的最终产出载体。

---

### 落盘文件

**输出类型**：JSON 文件
**输出位置**：硬盘文件（`output/evidences/test_results.json` + `output/evidences/coverage_reports.json`）
**包/模块**：`domain/evidence/builder.py:EvidenceBuilder.persist()`

内容即为 `merge_result` 中 `test_results_to_upsert` 和 `coverage_reports_to_upsert` 的 JSON 序列化，供下一次 `vt analyze` 作为历史缓存加载。

---

## 5. 异常捕获与日志

### 异常情况

| 异常类型 | 退出码 | 触发条件 |
|----------|--------|----------|
| `ValueError` | 1 | 历史缓存文件损坏或不可读（`load_initial_cache()` 中 JSON 解析失败或 OS 错误） |
| `Exception`（通用） | 1 | 阶段 6 内任何未预期错误（由 `try/except` 包裹整段代码） |

> 阶段 6 用 `try/except Exception as exc` 包裹全部步骤，捕获任何异常后打印 `Error building evidence: {exc}` 到 stderr 并返回退出码 `1`。用户看到此信息后应检查 `output/evidences/` 下的 JSON 文件是否损坏。
>
> 异常处理内部还包含一层嵌套的 `try/except Exception: pass`（`pipeline.py:361-366`），用于保护 `vt_logger.exception("evidence_build_failed", ...)` 自身的异常不影响退出码。此机制确保即使日志系统自身出错（如日志文件写入失败），阶段 6 仍能返回退出码 `1` 而不是崩溃或返回 `0`。

### 日志事件

| 事件名 | 级别 | 触发时机 | 附加字段 |
|--------|------|----------|----------|
| `evidence_build_failed` | EXCEPTION | 阶段 6 内部异常（仅发生在 pipeline.py:361-364 的异常分支） | `exc`（异常对象，由 `vt_logger.exception()` 自动附加栈追踪） |
| `phase_end` | INFO | 阶段 6 全部步骤正常完成 | `phase="build_evidence"`, `duration_ms`, `full_chain_count` |

> 阶段 6 不单独记录 merge/apply/persist 子步骤的日志事件——所有子步骤完成后方记录一条 `phase_end`，与 pipeline 整体日志风格保持一致。异常场景下 `evidence_build_failed` 先触发，然后函数立即返回 1，不产生 `phase_end`。

### 错误传播

阶段 6 的异常**不向上传播**到 `main.py` 的全局 try/except。pipeline 在阶段 6 外层用 `try/except Exception` 自行捕获，打印错误信息后直接返回退出码 `1`。此设计的考量是：证据构建失败不应让整个流水线崩溃，而是给出明确的错误提示和退出码。

`EvidenceBuilder.apply()` 内部调用的 `load_initial_cache()` 抛出 `ValueError` 时，会穿透 `apply()` 被阶段 6 的 `try/except` 捕获。

阶段 6 的异常处理还包含一层嵌套防御：在 `except` 分支中调用 `vt_logger.exception("evidence_build_failed", ...)` 时，如果日志系统本身抛出异常（如日志文件权限错误），最内层的 `try/except Exception: pass` 会吞掉该异常，确保"logger 自身异常不应影响退出码"（`pipeline.py:361-366`，含显式注释说明）。

---

## 6. 下游依赖

| 下游模块 | 目标包 | 说明 |
|----------|--------|------|
| **阶段 7** | `cli/analyze/pipeline.py:_run_db_analysis()` | 通过 conn 中的 `test_results` 和 `coverage_reports` 表执行 db.check_* 查询（如 `check_claim_evidence`、`check_coverage_violations` 等），证据数据由阶段 6 的 apply() 写入 |
| **阶段 8 — 报告生成** | `cli/analyze/reports.py:_build_report_document()` | 消费 `evidence_meta` 中的 `full_chain` 全链路数据，生成追溯报告和 Dashboard |
| **阶段 8 — 终端摘要** | `cli/analyze/output.py:_render_output()` | 通过 `evidence_meta` 展示证据摘要信息 |
| **下一次运行** | `infra/db/loaders.py:load_initial_cache()` | 下次 `vt analyze` 的阶段 6 将读取 `output/evidences/` 目录下由本次 `persist()` 生成的 JSON 文件作为历史缓存，继承上次运行的测试和覆盖率结果 |
