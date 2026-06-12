# VT 日志系统实现方案

## 定位

日志系统是 VT 自身的**运行时可观测性基础设施**，面向 VT 开发者，用于排错和性能优化。

与现有体系的关系：
- **Hints** = 面向消费者（Agent/人类）的实时指导输出
- **JSON 报告** = 面向审查的交付物（evidence_index.json, traceability_report.json）
- **日志** = VT 自身运行的内部状态记录，记录 hints 和报告背后没有呈现的运行细节

## 当前状态

| 维度 | 现状 |
|---|---|
| Python logging 模块 | 零使用 |
| 运行时性能数据 | 零采集（无 timing） |
| 异常处理 | ~80 个 except 块，大量静默吞没 |
| 缓存命中率 | claim test cache 有计数但只输出 stderr |
| 子进程执行 | 无执行时间、PID 记录 |
| 决策中间路径 | gate engine 计算了但丢弃了大量中间状态 |
| 工具输出详情 | ruff/mypy/bandit 只保留计数，丢弃详情 |
| Hint 回退频率 | 无法统计 hint 缺失时回退到硬编码字符串的次数 |
| 文件 I/O 失败 | 下游消费方静默吞没，无聚合统计 |
| 数据量统计 | 部分 len() 调用分散在代码中，无统一汇总 |

## 实现任务

### Task 1: 日志基础设施

创建 `src/vibe_tracing/operational_logger.py`，基于 Python 标准 `logging` 模块。

**设计要点：**
- 零外部依赖（不用 structlog/loguru）
- JSON Lines 格式输出，每条日志一行 JSON
- 输出路径：`.vibetracing/logs/vt-{YYYYMMDD-HHMMSS}.jsonl`
- 提供 `OperationalLogger` 类，接受 `run_id` 上下文
- 自动注入 `run_id`、`elapsed_ms`（自运行开始的毫秒数）到每条日志
- 不改变任何现有 print() 输出或报告生成逻辑

**日志级别配置：**

通过 `config.json` 的 `logging.level` 字段控制，默认 `"DEBUG"`：

```json
{
  "logging": {
    "level": "DEBUG"
  }
}
```

支持的级别：`DEBUG`、`INFO`、`WARNING`、`ERROR`，映射到 Python 标准 logging 级别。

| 级别 | 记录内容 | 典型场景 |
|---|---|---|
| DEBUG | 全部事件，包括中间数据值、变量快照、分支路径 | 开发排错、重构分析 |
| INFO | 阶段耗时、子进程执行、缓存统计、数据量汇总、gate_decision | 日常运行监控 |
| WARNING | hint 回退、异常但可恢复、降级处理 | 发现潜在问题 |
| ERROR | 不可恢复异常、文件 I/O 失败、schema 校验失败 | 故障定位 |

开发阶段默认 DEBUG 级别，可捕获：
- 每个 gate 判定的中间变量值（哪些文件被检查、哪些 AC 被遍历）
- 每次 hint 解析的 key、请求级别、是否回退
- 每个 analyzer 的输入/输出数据量
- 每次文件 I/O 的路径、大小、耗时
- 每个 except 块捕获的异常类型和 traceback

**日志事件类型：**

```
# INFO 级别事件
run_start          - 运行开始，记录 inputs_used
run_end            - 运行结束，记录 gate_decision、总耗时
phase_start/end    - pipeline 各阶段耗时
subprocess_exec    - 子进程执行详情（命令、耗时、exit_code）
cache_stat         - 缓存命中/未命中统计
data_volume        - 关键数据结构的元素数量
exception          - 被捕获的异常（类型、消息、位置）
file_io            - 文件读写操作（路径、结果、耗时）

# DEBUG 级别事件（开发排错用）
gate_eval_detail   - gate engine 每个检查点的中间变量值
hint_resolve       - 每次 hint 解析的 key、请求级别、解析结果、是否回退
analyzer_io        - 每个 analyzer 的输入/输出数据快照
compliance_detail  - 每条架构约束的检查过程和判定依据
coverage_detail    - 每个 AC/requirement 的覆盖判定明细
decision_path      - merge gate engine 的分支路径选择
variable_snapshot  - 关键变量的 DEBUG 快照（通过 logger.debug 调用）
```

**集成点：** 在 `pipeline.py:run_analyze()` 入口初始化，作为参数传递或通过 context 注入到需要记录的模块。

### Task 2: Pipeline 阶段计时

**文件：** `src/vibe_tracing/commands/analyze/pipeline.py`

在 `run_analyze()` 的每个阶段前后记录 `phase_start` / `phase_end`：

| 阶段 | 代码位置 | 记录内容 |
|---|---|---|
| context 加载 | L277 `_load_context()` | 输入文件数量、加载耗时 |
| integrity gates | L287 `_run_integrity_gates()` | 各 gate 结果、耗时 |
| tool execution | L303 `_execute_tools()` | 工具数量、执行耗时 |
| evidence build | L307-319 `EvidenceIndexBuilder.build()` | evidence 数量、增量/全量、耗时 |
| claim tests | L325-348 `_run_claim_tests()` | 测试数量、pass/fail/cached、耗时 |
| analyzers | L356-360 `_run_analyzers()` | gap/risk/compliance 数量、耗时 |
| gate evaluation | L362 `_evaluate_and_output()` | gate_decision、耗时 |
| report render | 在 `_evaluate_and_output()` 内部 | 输出文件路径、耗时 |

总耗时 = run_end.timestamp - run_start.timestamp。

### Task 3: 子进程执行计时

**文件：** `src/vibe_tracing/tool_evidence_adapter.py`

在 `ToolExecutionEngine._run_subprocess()` (L210-249) 中：
- 记录 `subprocess_exec` 事件：command（白名单内的）、duration_ms、exit_code、stdout_size、stderr_size
- 不记录完整的 stdout/stderr 内容（可能很大），只记录大小

**文件：** `src/vibe_tracing/commands/analyze/analysis.py`

在 `_run_claim_tests()` (L217-225) 中：
- 记录 pytest 子进程的执行时间和 timeout 边距

### Task 4: 异常结构化记录

**策略：** 不逐个修改 80 个 except 块，而是：
1. 在关键路径的 except 块中添加 `logger.exception()` 调用
2. 优先覆盖以下被静默吞没的位置：

| 文件 | 行号 | 当前行为 | 改为 |
|---|---|---|---|
| `git_utils.py` | L36,61,85,124 | `return None/False` | 记录 exception 事件后返回 |
| `evidence_index_builder.py` | L77 | `except: pass` | 记录 exception 事件 |
| `analysis.py` | L144 | 返回空 dict | 记录 exception 事件 |
| `hint_loader.py` | L37 | 返回空 dict | 记录 exception 事件 |
| `ghost_code_reconciler.py` | L53,73,95 等 | 静默吞没 | 记录 exception 事件 |
| `tool_evidence_adapter.py` | L320,327,428 等 | JSON 解析静默失败 | 记录 exception 事件 |

每个 `except` 块只加一行 `logger.debug("...")` 或 `logger.warning("...")`，不改变异常处理逻辑。

### Task 5: 缓存和数据量统计

**缓存统计：**
- `analysis.py`: claim test cache_hits/cache_misses 已计算，额外记录到日志
- `evidence_index_builder.py`: 记录 evidence 条目 reused vs regenerated 数量
- `hint_loader.py`: 记录 hint category 加载次数（已有缓存，加计数即可）

**数据量统计：**
- 在 `_run_analyzers()` 返回后，记录 merged_gaps/final_risks/compliance_res 的元素数量
- 在 `EvidenceIndexBuilder.build()` 返回后，记录 evidences 列表长度
- 在 `_evaluate_and_output()` 中，记录 human_decisions_applied 的分类统计

### Task 6: Hint 回退监控

**文件：** `src/vibe_tracing/hint_loader.py`

在 `resolve_hint()` 中：当返回空字符串时，记录一条 `hint_fallback` 事件（hint_key, requested_level）。

不改变 resolve_hint 的返回值或行为，只是旁路记录。

同时修复 `tool_evidence_adapter.py` 中的重复 hint 加载逻辑，改为导入 `hint_loader.py`，消除两条独立的缓存路径。

### Task 7: config.json 日志配置集成

**文件：** `.vibetracing/config.json`

在 config.json 中新增 `logging` 节：

```json
{
  "logging": {
    "level": "DEBUG"
  }
}
```

**文件：** `src/vibe_tracing/operational_logger.py`

`OperationalLogger.init()` 从 config.json 读取 `logging.level`，映射到 Python logging 级别：

```python
_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}
```

如果 config.json 中没有 `logging` 节或 `level` 字段，默认 `DEBUG`。

**文件：** `src/vibe_tracing/commands/analyze/pipeline.py`

在 `run_analyze()` 入口读取 config 中的 logging level，初始化 OperationalLogger：

```python
log_level = ctx.config.get("logging", {}).get("level", "DEBUG")
vt_logger = OperationalLogger.init(run_id, project_root, level=log_level)
```

### Task 8: DEBUG 级别插桩

在关键决策路径中添加 DEBUG 级别的详细记录，仅在 level=DEBUG 时输出：

**文件：** `src/vibe_tracing/merge_gate_engine.py`
- 每个 `_check_*` 方法的入口/出口：记录检查的文件列表、AC 列表
- `_compute_gate_decision()` 的中间状态：any_fail_detected、current_fail_detected 计数
- human_decisions 匹配详情：哪些决策被匹配、哪些未匹配

**文件：** `src/vibe_tracing/architecture_compliance_checker.py`
- 每条规则检查的输入数据（被检查的 import 列表、被检查的文件路径）
- 判定依据（匹配到的 forbidden pattern、whitelist 检查结果）

**文件：** `src/vibe_tracing/traceability/` 三个分析器
- 每个 analyzer 的输入 evidence 列表长度
- 每个 gap 创建的具体原因和关联数据

**文件：** `src/vibe_tracing/hint_loader.py`
- 每次 `resolve_hint()` 调用记录：hint_key、requested_level、resolved_value（截断到 200 字符）、is_fallback

**文件：** `src/vibe_tracing/evidence_index_builder.py`
- `_should_regenerate()` 的判定结果和 mtime 比较值
- evidence 条目的 reused vs regenerated 逐条记录

## 不做的事

| 不做 | 原因 |
|---|---|
| 替换 print() 为 logger | print() 是用户面向的 CLI 输出，不是日志 |
| 修改 JSON 报告 schema | 日志是独立产物，不改变报告格式 |
| 记录 hints 的内容 | hints 是消费者输出，不是运行时遥测 |
| 引入第三方日志库 | MVP 不增加外部依赖 |
| 日志轮转 | 单次运行一个 .jsonl 文件，无需轮转 |
| 记录子进程 stdout/stderr 内容 | 可能很大，只记录大小 |
| 全面改造所有 80 个 except 块 | 只在关键路径添加，逐步扩展 |

## 文件变更清单

| 变更类型 | 文件 | 说明 |
|---|---|---|
| 新建 | `src/vibe_tracing/operational_logger.py` | 日志基础设施 |
| 修改 | `src/vibe_tracing/commands/analyze/pipeline.py` | 初始化日志、阶段计时 |
| 修改 | `src/vibe_tracing/tool_evidence_adapter.py` | 子进程计时、合并 hint 加载 |
| 修改 | `src/vibe_tracing/commands/analyze/analysis.py` | 缓存统计、异常记录 |
| 修改 | `src/vibe_tracing/evidence_index_builder.py` | run_id 传入、增量统计 |
| 修改 | `src/vibe_tracing/hint_loader.py` | 回退监控 |
| 修改 | `src/vibe_tracing/git_utils.py` | 异常记录 |
| 修改 | `src/vibe_tracing/ghost_code_reconciler.py` | 异常记录 |
| 修改 | `docs/architecture_constraints.json` | 新增日志约束规则 |
| 新建 | `.vibetracing/logs/` | 日志输出目录（.gitignore） |
