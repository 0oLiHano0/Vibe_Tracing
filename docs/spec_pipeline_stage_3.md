# 阶段 3 模块详解：执行验证工具

## 1. 输入来源

| 来源 | 包/模块 | 文件 |
|------|---------|------|
| **配置文件**（含工具矩阵） | `domain/context.py` | 内存（由阶段 1 加载并存入 `UnifiedContext.config`） |
| **Claims** | `domain/context.py` | 内存（由阶段 1 加载并存入 `UnifiedContext.claims_list`） |

---

## 2. 输入结构

### config.json 中的工具配置

**输入位置**：内存（由阶段 1 从 `.vibetracing/config.json` 加载，存入 `UnifiedContext.config`）
**包/模块**：`domain/context.py:UnifiedContext.config`

```yaml
language: "python"                  # 项目编程语言（由 vt finalize 锁定）
language_tool_matrix:               # 工具矩阵（由 vt finalize 从架构约束生成）
  python:                           # 当前语言的工具配置
    extensions:                     # 该语言的文件扩展名列表
      - ".py"
    test:                           # 测试工具配置
      tool: "pytest"                # 工具二进制名
      default_command: "pytest {test_path} --tb=short -q --json-report --json-report-file={output_path}"
                                    # 命令模板（含占位符：{test_path}、{source_path}、{output_path}）
      output_format: "pytest_json"  # 输出格式标识（决定使用哪个解析器）
      pass_condition: "exit_code == 0"
                                    # 通过条件（文档性质，代码不直接使用）
    coverage:                       # 覆盖率工具配置
      tool: "coverage"
      default_command: "coverage run -m pytest {test_path} ; coverage json -o {output_path}"
      output_format: "coverage_json"
      pass_condition: "percent_covered >= 80"
    lint:                           # 代码风格检查工具配置
      tool: "ruff"
      default_command: "ruff check {source_path} --output-format=json"
      output_format: "ruff_json"
      pass_condition: "violations == 0"
    type_check:                     # 类型检查工具配置
      tool: "mypy"
      default_command: "mypy {source_path}"
      output_format: "mypy_json"
      pass_condition: "exit_code == 0"
    security:                       # 安全扫描工具配置
      tool: "bandit"
      default_command: "bandit -r {source_path} -f json -o {output_path}"
      output_format: "bandit_json"
      pass_condition: "results == 0"
```

---

### Claim（Claim 数据）

**输入位置**：内存（由阶段 1 从 `.vibetracing/claims/CLAIM-*.json` 加载，存入 `UnifiedContext.claims_list`）
**包/模块**：`domain/context.py:UnifiedContext.claims_list`

```yaml
claim_id: "CLAIM-VT-001"           # Claim ID
related_task: "TASK-VT-001"        # 关联的任务 ID
code_refs:                          # 代码文件引用列表（阶段 3 用此收集源码路径）
  - "src/vibe_tracing/cli/main.py"
test_refs:                          # 测试文件引用列表（阶段 3 用此收集测试路径）
  - "tests/test_cli.py"
notes: "实现了 CLI 入口"             # 备注
timestamp: "2026-06-23T12:00:00Z"   # 时间戳
```

---

## 3. 处理逻辑

阶段 3 的全部逻辑在 `infra/tools/executor.py:ToolExecutionEngine.execute_from_claims()` 中完成，分为以下步骤：

### 步骤 1：读取工具配置

从 config.json 中读取编程语言和工具矩阵，确定本次要执行的工具类别列表。

判定逻辑：工具类别从工具矩阵的 key 中动态获取（排除非字典类型的 key，如 `extensions`）。

---

### 步骤 2：工具依赖预检

调用模块：`infra/tools/resolver.py:ToolResolver.is_available()`

遍历所有要执行的工具类别，检查每个工具的二进制文件是否可用。检查方式为：先在系统 PATH 中查找，找不到则尝试以 Python 模块方式调用。

判定逻辑：如果有任何工具不可用，打印修复建议（"AI Agent Repair Guide"）到终端，返回空列表，整个阶段 3 跳过。流水线继续进入阶段 4，不会阻断。

---

### 步骤 3：创建执行引擎

调用模块：`infra/tools/executor.py:ToolExecutionEngine`

将工具矩阵、编程语言、工具类别列表传入执行引擎。引擎在初始化时构建内部白名单映射（类别→工具配置），后续所有工具执行都通过白名单校验。

---

### 步骤 4：收集执行路径

从所有 Claim 文件中提取文件路径，按用途分为两组：

- **测试路径**：来自 Claim 的 `test_refs` 字段
- **源码路径**：来自 Claim 的 `code_refs` 字段

提取规则：去掉路径中的 `#anchor` 后缀，检查文件后缀是否属于当前语言的扩展名列表，检查文件是否存在于磁盘，去重。

---

### 步骤 5：执行工具并收集证据

调用模块：`infra/tools/executor.py:ToolExecutionEngine.execute_from_claims()`

对每个文件路径，根据路径类型（测试/源码）选择要执行的工具类别：

- **测试路径**：只执行"test"类别（pytest）
- **源码路径**：执行除"test"外的所有类别（lint、type_check、security）

覆盖率（coverage）不按文件逐个执行，而是作为批量工具单独处理（步骤 7）。

对每个工具的执行过程（`execute_tool()`）：
1. 命令生成——从模板替换占位符（shlex.quote 引用路径），生成实际命令
2. 命令回退——如果工具不在 PATH 中，回退到 python3 -m 方式（ToolResolver.resolve_command）
3. 执行子进程——运行命令，捕获输出
4. 解析输出——根据 output_format 调用对应解析器（_parse_output 分发），标记 tool_category

---

### 步骤 6：覆盖率基线处理

调用模块：`infra/tools/executor.py:ToolExecutionEngine._measure_source_coverage()`

从 `coverage.json` 基线文件读取每个源文件的覆盖率数据（百分比和语句数），生成"coverage"类别的证据候选项。不执行 coverage 命令本身——覆盖率数据来自之前运行的缓存。

---

### 步骤 7：输出统计信息

打印执行结果到终端：总证据候选项数、阻断数、跳过数，以及各类错误详情（超时、工具未找到等）。

---

## 4. 输出结构

**输出类型**：`List[ToolEvidenceCandidate]`
**输出位置**：内存（通过 pipeline 局部变量传递给阶段 6，不落盘）

### ToolEvidenceCandidate（工具证据候选项）

**包/模块**：`domain/evidence/candidate.py:ToolEvidenceCandidate`

```yaml
source_type: "test"                 # 证据来源类型："test"（pytest）| "tool"（其他工具）
source_path: "tests/test_cli.py::test_help"
                                    # 文件路径或测试用例标识（nodeid）
covers:                             # 关联的验收标准/需求 ID 列表
  - "AC-VT-001-01"                  # 从测试函数的 docstring 中自动提取
status: "covered"                   # 覆盖状态：
                                    #   "covered"    — 测试通过
                                    #   "violated"   — 测试失败或发现违规
                                    #   "compliant"  — lint/类型检查/安全扫描通过
                                    #   "skipped"    — 工具不适用（如非代码文件）
                                    #   "blocked"    — 工具执行失败
                                    #   "unclear"    — 无法判定
tool_category: "test"               # 工具类别：
                                    #   "test"       — pytest（测试）
                                    #   "coverage"   — coverage（覆盖率）
                                    #   "lint"       — ruff（代码风格）
                                    #   "type_check" — mypy（类型检查）
                                    #   "security"   — bandit（安全扫描）
command: "pytest tests/test_cli.py --tb=short -q ..."
                                    # 实际执行的命令
exit_code: 0                        # 进程退出码
stderr: ""                          # 标准错误输出
error_code: null                    # 错误码（仅失败时有值）：
                                    #   "tool_execution_failed"     — 工具执行失败
                                    #   "tool_no_tests_collected"   — pytest 未收集到测试
                                    #   "tool_usage_error"          — 工具用法错误
details:                            # 附加详情
  outcome: "passed"                 # 测试结果详情
  violations_count: 0               # 违规数量（lint/安全扫描）
  percent_covered: 85.0             # 覆盖率百分比（coverage）
  num_statements: 120               # 语句数（coverage）
```

**用途**：传递给阶段 6 的 `EvidenceBuilder.merge()`，与历史证据合并后写入内存数据库和 JSON 文件，供阶段 7 分析和阶段 8 门禁判定使用。

---

## 5. 异常捕获与日志

### 异常情况

| 异常类型 | 退出码 | 触发条件 |
|----------|--------|----------|
| 工具二进制缺失 | 0（不阻断） | 预检阶段发现工具不在 PATH 中，返回空列表，阶段 3 整体跳过 |
| 子进程超时 | 0（不阻断） | 工具执行超过 120 秒，返回 blocked 状态的证据候选项 |
| 二进制不存在 | 0（不阻断） | 执行时工具被删除或不可达，返回 blocked 状态的证据候选项 |
| 权限拒绝 | 0（不阻断） | 无执行权限，返回 blocked 状态的证据候选项 |
| 路径越权 | 0（不阻断） | 路径解析后超出项目根目录，返回 blocked 状态的证据候选项 |
| 命令注入 | 0（不阻断） | 路径包含 shell 特殊字符，返回 blocked 状态的证据候选项 |
| 类别不在白名单 | 0（不阻断） | 工具类别未在工具矩阵中定义，返回 blocked 状态的证据候选项 |
| 输出格式不支持 | 0（不阻断） | 工具输出格式标识未匹配任何解析器，返回 blocked 状态的证据候选项 |

> 阶段 3 的所有异常均为"不阻断"——工具执行失败不会阻止流水线继续运行。失败的工具会生成 blocked 状态的证据候选项，由阶段 8 的门禁引擎统一判定是否阻断合并。

### 工具退出码分类

| 工具 | 退出码 | 含义 | 处理方式 |
|------|--------|------|----------|
| pytest | 0 | 全部通过 | 解析报告，生成 covered 状态证据 |
| pytest | 1 | 有测试失败 | 解析报告，生成 violated 状态证据 |
| pytest | 2 | 用法错误 | 生成 skipped 状态证据（非真实失败） |
| pytest | 5 | 无测试收集 | 生成 skipped 状态证据（非真实失败） |
| ruff | 0 | 无违规 | 生成 compliant 状态证据 |
| ruff | 1 | 有违规 | 生成 violated 状态证据 |
| mypy | 0 | 无类型错误 | 生成 compliant 状态证据 |
| mypy | 1 | 有类型错误 | 生成 violated 状态证据 |
| mypy | 2 | 用法错误 | 生成 skipped 状态证据 |
| bandit | 0 | 无安全问题 | 生成 compliant 状态证据 |
| bandit | 1 | 有安全问题 | 生成 violated 状态证据 |

### 日志事件

`infra/tools/executor.py` 的 `execute_from_claims()` 记录（全部 7 个事件归 executor，pipeline.py 无日志事件）：

| 事件名 | 级别 | 触发时机 | 附加字段 |
|--------|------|----------|----------|
| `tool_precheck_failed` | WARNING | 工具依赖预检失败（工具缺失） | `missing_tools` |
| `no_code_extensions` | WARNING | 语言配置无代码扩展名 | — |
| `no_code_files` | WARNING | Claim 中无代码文件 | — |
| `tool_execution_start` | INFO | 工具执行开始 | `total_paths`, `test_paths`, `source_paths` |
| `tool_files_skipped` | INFO | 工具引擎跳过部分文件 | `skipped_count` |
| `tool_execution_error` | WARNING | 单个工具执行失败 | `source_path`, `error_type`, `exit_code` |
| `tool_execution_complete` | INFO | 工具执行完成 | `executed_count`, `blocked_count`, `skipped_count` |

`infra/tools/executor.py` 记录：

| 事件名 | 级别 | 触发时机 | 附加字段 |
|--------|------|----------|----------|
| `subprocess_exec` | INFO | 子进程完成 | `command`, `duration_ms`, `exit_code`, `stdout_size`, `stderr_size` |
| `subprocess_output` | DEBUG | 子进程完成 | `command`, `stdout_preview`, `stderr_preview` |

`cli/analyze/pipeline.py` 记录：

| 事件名 | 级别 | 触发时机 | 附加字段 |
|--------|------|----------|----------|
| `phase_end` | INFO | 阶段 3 完成 | `phase="execute_tools"`, `duration_ms`, `tools_executed` |

### 错误传播

阶段 3 不抛出异常。所有工具执行失败都被捕获并转化为 blocked 状态的证据候选项。预检失败返回空列表。

错误信息使用双通道输出：
- `OperationalLogger` 记录技术详情到日志文件（供开发者排查）
- `print(stderr)` 输出简短提示到终端（供 Agent 或人类阅读后决定下一步行动）

---

## 6. 下游依赖

| 下游模块 | 目标包 | 说明 |
|----------|--------|------|
| **阶段 4-5** | `infra/db/init.py` | 阶段 3 的输出不直接传递给阶段 4-5，而是先经过阶段 6 |
| **阶段 6：EvidenceBuilder** | `domain/evidence/builder.py` | 接收 `List[ToolEvidenceCandidate]`，与历史证据合并后写入内存数据库和 JSON 文件 |
| **阶段 7：分析查询** | `infra/db/queries.py` | 从数据库查询工具证据，用于覆盖率违规检测（`check_coverage_violations`） |
| **阶段 8：门禁判定** | `domain/gate/engine.py` | 基于工具证据状态（covered/violated/blocked）判定是否阻断合并 |
