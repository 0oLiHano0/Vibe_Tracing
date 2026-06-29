# 阶段 3 模块详解

## 1. 输入来源

| 来源 | 包/模块 | 文件 |
|------|---------|------|
| **统一上下文** | `cli/analyze/pipeline.py:_load_context()` | 内存（阶段 1 构建） |
| **暂存区文件集合** | `cli/analyze/pipeline.py:run_analyze()` | 内存（阶段 2 通过 `git diff --cached` 获取） |
| **架构约束** | `infra/loader/raw_input.py` | `docs/architecture_constraints.json` |
| **Claims 列表** | `infra/loader/claim_loader.py` | `.vibetracing/claims/CLAIM-*.json` |
| **配置文件** | `infra/loader/config.py` | `.vibetracing/config.json` |

---

## 2. 输入结构

### UnifiedContext（统一上下文）

**输入位置**：内存（由阶段 1 `_load_context()` 构建）
**包/模块**：`domain/context.py:UnifiedContext`

阶段 3 仅使用以下字段：

```yaml
config:                             # 配置文件内容（Dict[str, Any]）
  language: "python"                # 项目语言（必需，缺失则阻断）
  validation_tools:                 # 要执行的验证工具类别列表
    - "test"                        # 可选值："test" | "coverage" | "lint" | "type_check" | "security"
constraints: {}                     # 架构约束（Dict[str, Any]，Stage 1 必需文件，由 finalize 保证存在）
claims_list:                        # Claims 列表
  - claim_id: "CLAIM-VT-001"       # Claim ID
    related_task: "TASK-VT-001"     # 关联的任务 ID
    code_refs:                      # 代码文件引用列表
      - "src/vibe_tracing/cli/main.py"
    test_refs:                      # 测试文件引用列表
      - "tests/test_cli.py"
task_result: null                   # 任务列表解析结果（可选，阶段 3 不使用）
```

### staged_files（暂存区文件集合）

**输入位置**：内存（阶段 2 通过 `git diff --cached --name-only` 获取）
**包/模块**：`cli/analyze/pipeline.py:run_analyze()` 内联逻辑

```yaml
staged_files:                       # Set[str]，暂存区中的文件路径
  - "src/vibe_tracing/cli/main.py"
  - "tests/test_cli.py"
```

### language_tool_matrix（工具矩阵）

**输入位置**：硬盘文件（`docs/architecture_constraints.json`，通过 `constraints` 字段传入）
**包/模块**：`infra/tools/executor.py:ToolExecutionEngine`

```yaml
language_tool_matrix:               # 工具矩阵（Dict[str, Dict[str, Any]]）
  python:                           # 语言名作为 key
    extensions:                     # 该语言的文件扩展名列表
      - ".py"
    test:                           # 工具类别名作为 key
      tool: "pytest"                # 工具二进制名称
      default_command: "pytest {test_path} --tb=short -q --json-report --json-report-file={output_path}"
      output_format: "pytest_json"  # 输出格式标识，决定解析器选择
      pass_condition: "exit_code == 0"  # 人工可读的通过条件
    coverage:
      tool: "coverage"
      default_command: "coverage run -m pytest {test_path} ; coverage json -o {output_path}"
      output_format: "coverage_json"
      pass_condition: "percent_covered >= 80"
    lint:
      tool: "ruff"
      default_command: "ruff check {source_path} --output-format=json"
      output_format: "ruff_json"
      pass_condition: "violations == 0"
    type_check:
      tool: "mypy"
      default_command: "mypy {source_path}"
      output_format: "mypy_json"
      pass_condition: "exit_code == 0"
    security:
      tool: "bandit"
      default_command: "bandit -r {source_path} -f json -o {output_path}"
      output_format: "bandit_json"
      pass_condition: "results == 0"
```

---

## 3. 前置契约

Stage 3 **不执行**前置条件检查。以下契约由 `finalize` + Stage 1 保证，Stage 3 直接信任上游：

| 契约项 | 保证方 | 说明 |
|--------|--------|------|
| `constraints` 非空 | finalize + Stage 1 `is_required=True` | finalize 保证文件存在，Stage 1 作为必需文件加载 |
| `config["language"]` 非空 | finalize + Stage 1 schema 校验 | finalize 写入 language，Stage 1 校验 config schema |
| PRD 非 draft 状态 | finalize 拦截 | draft PRD 不允许通过 finalize |
| `language_tool_matrix` 有对应语言配置 | finalize | finalize 校验语言在工具矩阵中有配置 |

Stage 3 直接使用 `ctx.constraints`、`ctx.config["language"]` 等字段，不做空值防御。

---

## 4. 处理逻辑

### 步骤 1：工具依赖预检

调用模块：`infra/tools/resolver.py:ToolResolver.is_available()`

遍历 `validation_tools` 列表中每个类别对应的 `tool` 字段值，检查工具二进制是否在 PATH 中可用。如果工具不可用，尝试通过 `python3 -m <tool>` 检测。

判定逻辑：有缺失工具 → 打印修复指南（`[AI Agent Repair Guide]`）→ 返回空列表 `[]`，不阻断流水线。

---

### 步骤 2：收集目标路径

调用模块：`cli/analyze/tools.py:_execute_tools()` 内联逻辑

从 Claims 列表中提取所有代码文件和测试文件的引用路径：

1. 遍历所有 Claim 的 `test_refs`，收集测试路径（加入 `test_paths`）
2. 遍历所有 Claim 的 `code_refs`，收集源码路径（加入 `source_paths`）
3. 仅保留扩展名匹配 `language_tool_matrix` 中定义的文件扩展名的路径
4. 仅保留文件实际存在于磁盘上的路径
5. 收集非代码文件引用（扩展名不在语言配置中），用于生成跳过证据

路径分类：
- `test_paths`：测试文件路径列表，仅执行 `test` 类别工具
- `source_paths`：源码文件路径列表，执行 `test` 以外的所有类别工具（`lint`、`type_check`、`security`）

---

### 步骤 3：过滤暂存区文件

调用模块：`cli/analyze/tools.py:_execute_tools()` 内联逻辑

如果 `staged_files` 不为 None，则将 `test_paths` 和 `source_paths` 过滤为仅保留暂存区中的文件。

判定逻辑：过滤后无任何路径 → 打印 "no staged files match claim references" → 返回空列表 `[]`。

---

### 步骤 4：执行验证工具

调用模块：`infra/tools/executor.py:ToolExecutionEngine.execute_all()`

将路径按类型（`test` / `source`）传入执行引擎。执行引擎对每个路径执行以下逻辑：

1. 遍历 `validation_tools` 列表中的每个工具类别
2. 跳过 `coverage` 类别（覆盖率是批量工具，由 `_measure_source_coverage()` 单独处理）
3. 根据路径类型路由：`test` 路径仅执行 `test` 类别，`source` 路径执行其余类别
4. 对每个 (路径, 类别) 组合调用 `execute_tool()`

`execute_tool()` 内部逻辑：
- 白名单检查：工具类别必须在 `_tool_configs` 中
- 路径安全校验：路径必须在项目根目录内（防止路径越权）
- 命令模板替换：将 `{test_path}`、`{source_path}`、`{output_path}` 替换为实际路径，路径值经过 shell 注入防护（正则校验 + `shlex.quote()`）
- 子进程执行：以 `shell=True` 执行命令，默认超时 120 秒
- 输出解析：根据 `output_format` 选择对应的解析器（`pytest_json`、`ruff_json`、`mypy_json`、`bandit_json`、`coverage_json`）

---

### 步骤 5：解析工具输出

调用模块：`infra/tools/parsers.py` 中的各解析函数

根据 `output_format` 选择解析器，将工具的 stdout/stderr 转换为标准化的 `ToolEvidenceCandidate` 列表：

| 解析器 | 适用工具 | 解析逻辑 |
|--------|----------|----------|
| `parse_pytest_output` | pytest | 解析 JSON 报告，每个测试用例生成一个候选证据，从 docstring 提取 covers 标注 |
| `parse_ruff_output` | ruff | 解析 JSON 输出，无违规 = `compliant`，有违规 = `violated` |
| `parse_mypy_output` | mypy | 解析 JSON 报告或 stdout 中的错误行数，无错误 = `compliant` |
| `parse_bandit_output` | bandit | 解析 JSON 输出，无安全问题 = `compliant` |
| `parse_coverage_json_output` | coverage | 解析 `coverage.json`，每个源文件生成一个候选证据 |

退出码分类规则：
- 退出码 0：成功 → `compliant` 或 `covered`
- 退出码 1：发现问题（如测试失败、违规）→ `violated`
- pytest 退出码 2/5、mypy 退出码 2：工具无法处理该文件 → `skipped`，不产生证据
- 其他退出码：工具执行异常 → `blocked`，记录 `error_code`

---

### 步骤 6：生成跳过证据

调用模块：`cli/analyze/tools.py:_execute_tools()` 内联逻辑

为非代码文件引用（如 `.json`、`.md` 等）生成 `skipped` 状态的候选证据，记录跳过原因为 "non-code file, tools not applicable"。

---

## 5. 输出结构

**输出类型**：`List[ToolEvidenceCandidate]`
**输出位置**：内存（通过 pipeline 局部变量 `tool_evidence` 传递，不落盘）

### ToolEvidenceCandidate（工具证据候选）

**包/模块**：`infra/tools/candidate.py:ToolEvidenceCandidate`

```yaml
source_type: "test"                 # 来源类型："test"（pytest 测试用例）| "tool"（其他工具）
source_path: "tests/test_cli.py"    # 来源路径：测试文件 nodeid 或源码文件路径
covers:                             # 该证据覆盖的 AC/REQ ID 列表
  - "AC-VT-001-01"                  # 从测试 docstring 中提取
status: "covered"                   # 覆盖状态（CoverageStatus 枚举值）
                                    # "covered" | "compliant" | "violated" | "skipped" | "blocked"
tool_category: "test"               # 工具类别
                                    # "test" | "coverage" | "lint" | "type_check" | "security"
command: "pytest tests/test_cli.py --tb=short -q --json-report --json-report-file=.vibetracing/tmp/vt_test_abc123.json"
                                    # 实际执行的命令字符串
exit_code: 0                        # 工具退出码（0=成功，非0=有问题）
stderr: ""                          # 工具 stderr 输出
error_code: null                    # 错误码（ErrorCode 枚举值，仅执行失败时非空）
                                    # "tool_execution_failed" | "tool_no_tests_collected" | "tool_usage_error"
details: {}                         # 附加详情（Dict[str, Any]，因工具类型而异）
```

**details 字段的工具类型差异**：

```yaml
# pytest 类型
details:
  nodeid: "tests/test_cli.py::test_help"  # 测试用例 ID
  outcome: "passed"                        # 测试结果："passed" | "failed" | "error"

# ruff 类型
details:
  violations_count: 0                      # 违规数量

# mypy 类型
details:
  errors_count: 0                          # 类型错误数量

# bandit 类型
details:
  results_count: 0                         # 安全问题数量

# coverage 类型
details:
  percent_covered: 85.0                    # 覆盖百分比
  num_statements: 100                      # 语句总数

# 跳过类型
details:
  skip_reason: "non-code file, tools not applicable"  # 跳过原因

# 超时类型
details:
  error_type: "timeout"                    # 错误子类型
  timeout_seconds: 120                     # 超时秒数
```

**用途**：`tool_evidence` 列表在阶段 6 传递给 `EvidenceBuilder.merge()`，与历史缓存合并后写入数据库，成为阶段 7 查询分析的原始数据。

---

## 6. 异常捕获与日志

### 异常情况

| 异常类型 | 退出码 | 触发条件 |
|----------|--------|----------|

> Stage 3 不再抛出 `_GateBlocked` 异常。`language` 缺失等前置条件由 `finalize` + Stage 1 保证，Stage 3 直接信任上游。

> [!NOTE]
> 工具依赖缺失、工具执行超时、工具执行失败等情况均不抛出异常，而是返回 `blocked` 或 `skipped` 状态的候选证据，由下游阶段处理。

### 日志事件

阶段 3 运行完成后，由 `pipeline.py:run_analyze()` 记录：

| 事件名 | 级别 | 触发时机 | 附加字段 |
|--------|------|----------|----------|
| `phase_end` | INFO | 阶段 3 完成 | `phase="execute_tools"`, `duration_ms`, `tools_executed`（候选证据总数） |

工具执行引擎内部记录的日志事件（由 `infra/tools/executor.py` 记录）：

| 事件名 | 级别 | 触发时机 | 附加字段 |
|--------|------|----------|----------|
| `subprocess_exec` | INFO | 每个子进程执行完成 | `command`, `duration_ms`, `exit_code`, `stdout_size`, `stderr_size` |
| `subprocess_output` | DEBUG | 子进程输出详情 | `command`, `stdout_preview`（前500字符）, `stderr_preview`（前500字符） |

### 错误传播

阶段 3 不再抛出 `_GateBlocked` 异常。前置条件校验已由 `finalize` + Stage 1 完成，Stage 3 直接信任上游契约。

工具执行层面的错误（超时、二进制缺失、OS 错误等）不传播异常，而是被 `ToolExecutionEngine._run_subprocess()` 内部捕获，转换为 `error_code` 写入 `ToolEvidenceCandidate`，由阶段 6 的 `EvidenceBuilder` 和阶段 8 的门禁引擎判定是否阻断。

---

## 7. 下游依赖

| 下游模块 | 目标包 | 说明 |
|----------|--------|------|
| **阶段 6：构建证据** | `domain/evidence/builder.py:EvidenceBuilder` | 接收 `tool_evidence` 列表，与历史缓存合并后写入数据库，为阶段 7 的 SQL 查询提供原始数据 |
| **阶段 7：运行分析** | `infra/db/queries.py` | 间接依赖——通过数据库中的证据数据执行覆盖率、合规性等查询 |
| **阶段 8：门禁判定** | `domain/gate/engine.py:MergeGateEngine` | 间接依赖——基于分析结果判定门禁通过或阻断 |
