# infra/loader 包模块详解

## 1. 输入来源

| 来源 | 包/模块 | 文件 |
|------|---------|------|
| **项目配置** | `infra/loader/config.py` | `.vibetracing/config.json` |
| **PRD 文档** | `infra/loader/raw_input.py` | `docs/prd.md`（路径由 config 指定） |
| **架构约束** | `infra/loader/raw_input.py` | `docs/architecture_constraints.json`（路径由 config 指定） |
| **任务列表** | `infra/loader/raw_input.py` | `docs/task_list.json`（路径由 config 指定） |
| **Agent Claims** | `infra/loader/raw_input.py` | `.vibetracing/claims/CLAIM-*.json`（硬编码路径） |
| **人类决策** | `infra/loader/raw_input.py` | `.vibetracing/human_decisions.json`（路径由 config 指定） |

**路径解析规则**：
- PRD、架构约束、任务列表、人类决策的路径从 `config.json` 的 `paths` 字段读取
- Agent Claims 路径硬编码为 `.vibetracing/claims/`，不受 config 覆盖
- 路径解析统一由 `config.py:resolve_path()` 处理，各 loader 不硬编码路径

---

## 2. 输入结构

### config.json

**输入位置**：硬盘文件（`.vibetracing/config.json`）
**包/模块**：`infra/loader/config.py:load_config()`

```yaml
schema_version: "1.0.0"             # Schema 版本号
project_id: "PROJECT-VT"            # 项目 ID
project_prefix: "VT"                # 项目前缀（用于 ID 校验，代码中默认 "VT"）
paths:
  prd: "docs/prd.md"                # PRD 文件路径
  architecture_constraints: "docs/architecture_constraints.json"  # 架构约束文件路径
  task_list: "docs/task_list.json"  # 任务列表文件路径
  output_dir: "output"              # 输出目录
logging:
  level: "DEBUG"                    # 日志级别
gate:
  incremental_only: false           # 是否只检查增量问题
  show_historical_debt: true        # 是否显示历史债务详情
```

---

### InputFileRecord（单文件加载记录）

**输入位置**：内存（由 `RawInputLoader.load()` 构建）
**包/模块**：`infra/loader/raw_input.py:InputFileRecord`

```yaml
file_key: "prd"                     # 文件标识符："prd" | "architecture_constraints" | "task_list" | "agent_claims" | "human_decisions"
file_path: "docs/prd.md"            # 文件路径
is_required: true                   # 是否为必需文件（仅 "prd" 为必需）
status: "ok"                        # 加载状态："ok" | "missing" | "parse_error" | "read_error"
error_code: null                    # 失败时的 ErrorCode 枚举值（仅必需文件缺失时填充）
error_message: ""                   # 错误描述信息
content: {}                         # 已解析的内容（dict/list/str，加载失败为 null）
sha256_hash: "abc123..."            # 文件原始字节的 SHA-256 哈希
```

---

### RawInputManifest（加载清单）

**输入位置**：内存（由 `RawInputLoader.load()` 构建）
**包/模块**：`infra/loader/raw_input.py:RawInputManifest`

```yaml
has_required_errors: false          # 是否有必需文件加载失败
error_count: 0                      # 加载失败的文件总数（仅 parse_error/read_error，可选文件 missing 不计入）
inputs_used:                        # 所有文件的加载记录
  - file_key: "prd"                 # 文件标识符
    file_path: "docs/prd.md"        # 文件路径
    is_required: true               # 是否为必需文件
    status: "ok"                    # 加载状态
    error_code: null                # 失败时的错误码
    error_message: ""               # 错误描述
    content: {}                     # 已解析内容
    sha256_hash: "abc123..."        # SHA-256 哈希
```

---

### PrdParseResult（PRD 解析结果）

**输入位置**：内存（由 `PrdParser.parse_text()` 构建）
**包/模块**：`infra/loader/prd_parser.py:PrdParseResult`

```yaml
status: "active"                    # PRD 状态："active" | "draft"
project_name: "Vibe Tracing"        # 项目名称（可选，从 front matter 提取）
project_id: "PROJECT-VT"            # 项目 ID（可选，格式 PROJECT-{prefix}）
is_valid: true                      # 是否解析成功
errors: []                          # 解析错误列表（字符串数组）
requirements:                       # 需求列表
  - req_id: "REQ-VT-001"            # 需求 ID（格式 REQ-{prefix}-\d+ 或 Q-\d+）
    title: "全链路需求追踪"          # 需求标题
    priority: "must"                # 优先级："must" | "should" | "could" | "unclear"
    category: "functional"          # 类别："functional" | "quality_evolution" | "unclear"
    acceptance_criteria:            # 验收标准列表
      - ac_id: "AC-VT-001-01"       # AC ID（格式 AC-{prefix}-\d+-\d+）
        title: "需求必须能关联任务"  # AC 标题
        is_testing_required: true    # 是否必须有测试
```

---

### TaskListLoadResult（任务列表解析结果）

**输入位置**：内存（由 `TaskLoader.deserialize()` 构建）
**包/模块**：`infra/loader/task_loader.py:TaskListLoadResult`

```yaml
is_valid: true                      # 是否解析成功
errors: []                          # 解析错误列表
tasks:                              # 任务列表
  - task_id: "TASK-VT-001"          # 任务 ID
    title: "建立依赖与完整目录骨架"  # 任务标题
    phase_id: "PHASE-VT-001"        # 所属阶段 ID
    priority: "must"                # 优先级："must" | "should" | "could"
    status: "todo"                  # 状态："todo" | "in_progress" | "done"
    owner_role: "AI Coding Agent"   # 负责角色
    objective: "建立 MVP 项目的可运行基础"  # 任务目标
    related_requirements:           # 关联的需求 ID 列表
      - "REQ-VT-001"
    related_acceptance_criteria:    # 关联的 AC ID 列表
      - "AC-VT-001-01"
    related_modules:                # 关联的模块 ID 列表
      - "MOD-VT-001"
    related_architecture_constraints:  # 关联的架构约束 ID 列表
      - "PRINCIPLE-VT-006"
    definition_of_done:             # 完成定义列表
      - dod_id: "DOD-VT-001-01"     # DoD ID
        description: "项目可通过本地 CLI 命令启动并显示帮助信息"
    is_valid: true                  # 任务是否有效
    errors: []                      # 任务校验错误
```

---

### ClaimListLoadResult（Claim 解析结果）

**输入位置**：内存（由 `ClaimLoader.load()` 构建）
**包/模块**：`infra/loader/claim_loader.py:ClaimListLoadResult`

```yaml
is_valid: true                      # 是否解析成功
errors: []                          # 解析错误列表
claims:                             # Claim 列表
  - claim_id: "CLAIM-VT-001"       # Claim ID
    related_task: "TASK-VT-001"    # 关联的任务 ID
    code_refs:                      # 代码文件引用列表
      - "src/vibe_tracing/cli/main.py"
    test_refs:                      # 测试文件引用列表
      - "tests/test_cli.py"
    notes: "实现了 CLI 入口和上下文加载"  # 备注
    timestamp: "2026-06-23T12:00:00Z"    # 时间戳
```

---

## 3. 处理逻辑

### 步骤 1：加载配置文件

调用模块：`infra/loader/config.py:load_config()`

从 `.vibetracing/config.json` 读取项目配置，返回配置字典。

判定逻辑：config.json 不存在时抛出 `FileNotFoundError`；格式损坏时抛出 `ValueError`。异常由调用方（pipeline）捕获处理。

---

### 步骤 2：物理读取所有输入文件

调用模块：`infra/loader/raw_input.py:RawInputLoader.load()`

实例化 `RawInputLoader(project_root, config_data=config)`（构造函数无 I/O），然后调用 `load()` 一次性读取所有治理文件。

读取规则：
- 必需文件由 `REQUIRED_FILES` 常量驱动（当前仅 `"prd"`）
- 可选文件由硬编码列表驱动：`"architecture_constraints"`、`"task_list"`、`"agent_claims"`、`"human_decisions"`
- JSON 文件解析为 dict/list，Markdown 文件读取为纯文本字符串
- Agent Claims 支持目录模式：批量加载目录下所有 `CLAIM-*.json` 文件并合并为一个列表
- 每个文件计算 SHA-256 哈希值，记录在 `InputFileRecord.sha256_hash`

错误处理：不抛出异常。所有错误记录在 `InputFileRecord.status` 中：
- 必需文件缺失：`status="missing"`，`error_code=ErrorCode.MISSING_INPUT`，计入 `error_count`
- 可选文件缺失：`status="missing"`，`error_code=None`，不计入 `error_count`
- 解析/读取错误：`status="parse_error"` 或 `status="read_error"`，`error_code=ErrorCode.INVALID_INPUT`，计入 `error_count`

---

### 步骤 3：解析 PRD 文档

调用模块：`infra/loader/prd_parser.py:PrdParser.parse_text()`

将已加载的 PRD Markdown 文本解析为结构化的 `PrdParseResult`。pipeline 模式下使用 `parse_text()` 避免重复读盘，独立使用时可用 `parse_file()`。

解析规则：
- 提取 YAML front matter 中的元数据（`project_abbreviation`、`status` 等）
- 使用 `infra.validation.get_project_prefix()` 获取前缀，构造动态正则匹配 REQ/AC ID
- REQ ID 模式：`REQ-{prefix}-\d+` 或 `Q-\d+`（质量演进类需求）
- AC ID 模式：`AC-{prefix}-\d+-\d+`
- REQ 必须出现在 h3 标题中，AC 必须出现在 h5 标题中
- AC 的父 REQ 必须与当前解析上下文匹配

校验规则（后置检查）：
- 重复的 REQ ID 或 AC ID → `is_valid=false`
- AC 引用的父 REQ 在文档中不存在 → `is_valid=false`
- AC 缺失"是否必须有测试"字段 → `is_valid=false`
- REQ 缺失优先级或类别 → `priority/category` 设为 `"unclear"`，`is_valid=false`
- `Q-\d+` 模式的 REQ 若 category 不是 `quality_evolution` → 记录 WARNING

---

### 步骤 4：校验任务列表

调用模块：`infra/loader/task_loader.py:TaskLoader.deserialize()`

将已加载的任务列表 JSON 字典反序列化为 `Task` 实体列表。纯反序列化，不含判定逻辑。孤立任务检测已移至 SQL 查询层（`check_isolated_tasks()`），作为 dashboard 警告呈现。

---

### 步骤 5：校验 Agent Claims

调用模块：`infra/loader/claim_loader.py:ClaimLoader.load()`

将已加载的 Claims JSON 反序列化为 `Claim` 实体列表。

加载规则：
- pipeline 模式：直接使用传入的 content 数据
- 独立模式且路径为目录：批量加载 `CLAIM-*.json` 文件
- 独立模式且路径非目录：返回 `is_valid=false`

Claim 模块不进行跨文件校验（如 Claim↔Task 引用校验由 SQL 查询层负责）。

---

## 4. 输出结构

**输出类型**：由各 loader 模块分别返回，由调用方（pipeline）组装为 `UnifiedContext`
**输出位置**：内存（通过函数返回值传递，不落盘）

### config.py 输出

**包/模块**：`infra/loader/config.py`

| 输出 | 类型 | 说明 |
|------|------|------|
| `load_config()` 返回值 | `Dict[str, Any]` | config.json 的完整内容字典 |
| `resolve_path()` 返回值 | `Path` | 解析后的绝对文件路径 |

### RawInputLoader 输出

**包/模块**：`infra/loader/raw_input.py`

返回 `RawInputManifest`（结构见 §2）。

**用途**：pipeline 从中提取各文件的 `content` 和 `status`，决定后续处理流程。`sha256_hash` 用于变更检测。

### PrdParser 输出

**包/模块**：`infra/loader/prd_parser.py`

返回 `PrdParseResult`（结构见 §2）。

**用途**：`requirements` 列表灌入数据库供覆盖检查使用；`status` 控制 draft 模式；`is_valid` 决定是否阻断流水线。

### TaskLoader 输出

**包/模块**：`infra/loader/task_loader.py`

返回 `TaskListLoadResult`（结构见 §2）。

**用途**：`tasks` 列表灌入数据库供覆盖检查和门禁判定使用。

### ClaimLoader 输出

**包/模块**：`infra/loader/claim_loader.py`

返回 `ClaimListLoadResult`（结构见 §2）。

**用途**：`claims` 列表灌入数据库供证据链构建和覆盖检查使用。

---

## 5. 异常捕获与日志

### 异常情况

loader 包内的异常处理分两种模式：

**抛出异常的模块**（config.py）：

| 异常类型 | 触发条件 | 捕获方 |
|----------|----------|--------|
| `FileNotFoundError` | config.json 不存在 | `pipeline.py:_load_context()` |
| `ValueError` | config.json 格式损坏或读取失败 | `pipeline.py:_load_context()` |
| `ValueError` | config 缺少 `paths` 字段或指定 key | 调用方 |

**返回错误状态的模块**（raw_input / prd_parser / task_loader / claim_loader）：

| 错误状态 | 触发条件 | 判定方式 |
|----------|----------|----------|
| `InputFileRecord.status="missing"` | 必需文件不存在 | `manifest.has_required_errors=true` |
| `InputFileRecord.status="parse_error"` | JSON 解析失败 | `record.status not in ("ok", "missing")` |
| `InputFileRecord.status="read_error"` | 文件读取失败 | `record.status not in ("ok", "missing")` |
| `PrdParseResult.is_valid=false` | PRD 校验失败（ID 格式、父子关系、重复等） | `prd_res.is_valid` |

> loader 包本身不抛出 `_GateBlocked`。所有 `_GateBlocked(1)` 由调用方（`pipeline.py`）根据上述错误状态决定是否抛出。

### 日志事件

loader 包内部不记录日志事件。日志由调用方（`pipeline.py:run_analyze()`）在 loader 返回后统一记录。

### 错误传播

- `config.py` 的异常传播到 `pipeline.py:_load_context()` 的 try/except，被捕获后抛出 `_GateBlocked(1)`
- 其他 loader 模块通过返回值中的错误状态传播，由 pipeline 检查后决定是否抛出 `_GateBlocked(1)`

---

## 6. 下游依赖

| 下游模块 | 目标包 | 说明 |
|----------|--------|------|
| **pipeline 阶段 1** | `cli/analyze/pipeline.py` | 调用全部 loader 组装 `UnifiedContext`，是 loader 的主要消费方 |
| **pipeline 阶段 5** | `infra/db/loaders.py` | 将 `PrdParseResult`、`TaskListLoadResult`、`ClaimListLoadResult` 灌入内存 SQLite |
| **finalize 命令** | `cli/finalize.py` | 调用 `load_config()`、`resolve_path()` 读取配置和路径 |
| **doctor 命令** | `cli/doctor.py` | 调用 `PrdParser.parse_file()` 独立解析 PRD |
| **PRD-Arch 校验** | `domain/compliance/prd_arch_validator.py` | 调用 `PrdParser.parse_file()` 独立解析 PRD |
| **变更提案引擎** | `domain/governance/change_proposal.py` | 调用 `load_config()` 读取配置 |
| **幽灵代码协调器** | `domain/governance/ghost_code.py` | 调用 `load_config()` 读取配置 |
