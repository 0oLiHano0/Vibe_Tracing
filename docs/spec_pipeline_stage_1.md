# 阶段 1 模块详解

## 1. 输入来源

| 来源 | 包/模块 | 文件 |
|------|---------|------|
| **配置文件** | `infra/loader/raw_input.py` | `.vibetracing/config.json` |
| **PRD** | `infra/loader/prd_parser.py` | `docs/prd.md` |
| **架构约束** | `infra/loader/raw_input.py` | `docs/architecture_constraints.json` |
| **任务列表** | `infra/loader/task_loader.py` | `docs/task_list.json` |
| **Claims** | `infra/loader/claim_loader.py` | `.vibetracing/claims/CLAIM-*.json` |
| **人类决策** | `infra/loader/raw_input.py` | `.vibetracing/human_decisions.json` |

---

## 2. 输入结构

### config.json

**输入位置**：硬盘文件（`.vibetracing/config.json`）
**包/模块**：`infra/loader/raw_input.py:RawInputLoader._load_config()`

```yaml
schema_version: "1.0.0"          # Schema 版本号
project_id: "PROJECT-VT"         # 项目 ID
project_prefix: "VT"             # 项目前缀（用于 ID 校验）
paths:
  prd: "docs/prd.md"                           # PRD 文件路径
  architecture_constraints: "docs/architecture_constraints.json"  # 架构约束文件路径
  task_list: "docs/task_list.json"             # 任务列表文件路径
  output_dir: "output"                         # 输出目录
logging:
  level: "DEBUG"                               # 日志级别
gate:
  incremental_only: false                      # 是否只检查增量问题
  show_historical_debt: true                   # 是否显示历史债务详情
```

---

### PrdParseResult（PRD 解析结果）

**输入位置**：硬盘文件（`docs/prd.md`，通过解析转换）
**包/模块**：`infra/loader/prd_parser.py:PrdParseResult`

```yaml
status: "active"                    # PRD 状态："active" | "draft"
project_name: "Vibe Tracing"        # 项目名称（可选）
project_id: "PROJECT-VT"            # 项目 ID（可选）
is_valid: true                      # 是否解析成功
errors: []                          # 解析错误列表
requirements:                       # 需求列表
  - req_id: "REQ-VT-001"            # 需求 ID
    title: "全链路需求追踪"          # 需求标题
    priority: "must"                # 优先级："must" | "should" | "could" | "unclear"
    category: "functional"          # 类别："functional" | "quality_evolution" | "unclear"
    acceptance_criteria:            # 验收标准列表
      - ac_id: "AC-VT-001-01"       # AC ID
        title: "需求必须能关联任务"  # AC 标题
        is_testing_required: true    # 是否必须有测试
```

---

### TaskListLoadResult（任务列表解析结果）

**输入位置**：硬盘文件（`docs/task_list.json`，通过解析转换）
**包/模块**：`infra/loader/task_loader.py:TaskListLoadResult`

```yaml
is_valid: true                      # 是否解析成功
errors: []                          # 解析错误列表
gaps: []                            # 覆盖缺口列表
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
      - "REQ-VT-002"
    related_acceptance_criteria:    # 关联的 AC ID 列表
      - "AC-VT-001-01"
      - "AC-VT-002-01"
    related_modules:                # 关联的模块 ID 列表
      - "MOD-VT-001"
      - "MOD-VT-002"
    related_architecture_constraints:  # 关联的架构约束 ID 列表
      - "PRINCIPLE-VT-006"
      - "TECH-VT-001"
    definition_of_done:             # 完成定义列表
      - dod_id: "DOD-VT-001-01"     # DoD ID
        description: "项目可通过本地 CLI 命令启动并显示帮助信息"  # DoD 描述
    is_valid: true                  # 任务是否有效
    errors: []                      # 任务校验错误
```

---

### Claim（Claim 数据）

**输入位置**：硬盘文件（`.vibetracing/claims/CLAIM-*.json`，通过解析转换）
**包/模块**：`infra/loader/claim_loader.py:Claim`

```yaml
claim_id: "CLAIM-VT-001"           # Claim ID
related_task: "TASK-VT-001"        # 关联的任务 ID
code_refs:                          # 代码文件引用列表
  - "src/vibe_tracing/cli/main.py"
  - "src/vibe_tracing/domain/context.py"
test_refs:                          # 测试文件引用列表
  - "tests/test_cli.py"
  - "tests/test_context.py"
notes: "实现了 CLI 入口和上下文加载"  # 备注
timestamp: "2026-06-23T12:00:00Z"   # 时间戳
```

---

### UnifiedContext（统一上下文）

**输入位置**：内存（由 `_load_context()` 构建）
**包/模块**：`domain/context.py:UnifiedContext`

```yaml
config: {}                          # config.json 内容（Dict[str, Any]）
prd: PrdParseResult                 # PRD 解析结果
constraints: {}                     # 架构约束（Dict[str, Any]，可选）
task_result: TaskListLoadResult     # 任务列表解析结果（可选）
claims_list:                        # Claims 列表
  - claim_id: "CLAIM-VT-001"
    related_task: "TASK-VT-001"
    code_refs: [...]
    test_refs: [...]
manifest: RawInputManifest          # 加载清单（可选）
human_decisions: {}                 # 人类决策（可选）
config_prefix: "VT"                 # 项目前缀
```

---

### RawInputManifest（加载清单）

**输入位置**：内存（由 `RawInputLoader.load()` 构建）
**包/模块**：`infra/loader/raw_input.py:RawInputManifest`

```yaml
has_required_errors: false          # 是否有必需文件加载失败
error_count: 0                      # 加载失败的文件总数
tool_report_files: []               # 工具报告文件路径列表
inputs_used:                        # 所有文件的加载记录
  - file_key: "prd"                 # 文件标识符
    file_path: "docs/prd.md"        # 文件路径
    is_required: true               # 是否为必需文件
    status: "ok"                    # 加载状态："ok" | "missing" | "parse_error" | "read_error"
    error_code: null                # 失败时的 ErrorCode 枚举值
    error_message: ""               # 错误描述信息
    content: {}                     # 已解析的内容（dict/list/str）
    sha256_hash: "abc123..."        # 文件原始字节的 SHA-256 哈希
```

---

## 3. 处理逻辑

### 步骤 1：创建 RawInputLoader，加载 config.json

调用模块：`infra/loader/raw_input.py:RawInputLoader`

从项目根目录创建 RawInputLoader 实例，自动加载 `.vibetracing/config.json` 配置文件。配置文件包含项目 ID、文件路径、日志级别、门禁配置等。

---

### 步骤 2：加载所有输入文件，生成 manifest

调用模块：`infra/loader/raw_input.py:RawInputLoader.load()`

RawInputLoader 扫描并加载所有输入文件，生成 manifest（加载清单）。加载过程包含：

1. **加载 PRD**（必需文件）：读取 `docs/prd.md`
2. **加载可选文件**：依次读取 `architecture_constraints`、`task_list`、`agent_claims`、`human_decisions`
3. **扫描工具报告**：扫描 `.vibetracing/tool_reports/` 目录下的 `*.json` 文件，写入 `manifest.tool_report_files`

manifest 结构：
```yaml
has_required_errors: false          # 是否有必需文件加载失败
error_count: 0                      # 加载失败的文件总数
tool_report_files: []               # 工具报告文件路径列表
inputs_used:                        # 所有文件的加载记录
  - file_key: "prd"                 # 文件标识符
    status: "ok"                    # 加载状态："ok" | "missing" | "parse_error" | "read_error"
```

---

### 步骤 3：设置项目前缀

调用模块：`infra/validation/set_project_prefix()`

从 `config_data["project_prefix"]` 读取项目前缀（默认 `"VT"`），调用 `ids.set_project_prefix(config_prefix)` 设置全局前缀。后续所有 ID 校验（Schema 校验、PRD 解析等）使用此前缀构建正则表达式。

---

### 步骤 4：检查 manifest 完整性

调用模块：`cli/analyze/pipeline.py:_load_context()` 内联逻辑

对 manifest 执行两道检查：

1. **必需文件检查**：如果 `manifest.has_required_errors` 为 true，遍历 `inputs_used` 打印缺失的必需文件到 stderr，阻断门禁
2. **文件格式检查**：遍历 `inputs_used`，如果任何文件的 `status` 不是 `"ok"` 或 `"missing"`（即 `"parse_error"` 或 `"read_error"`），阻断门禁

判定逻辑：任一检查失败则 `raise _GateBlocked(1)`。

---

### 步骤 5：执行 Schema 校验

调用模块：`infra/validation/checks.py:validate_inputs()`

对所有输入文件执行格式校验，包含 5 项子检查：

1. **JSON Schema 校验**（`_check_schemas`）：对 `task_list`、`agent_claims`、`architecture_constraints`、`human_decisions` 等执行 JSON Schema 验证
2. **ID 格式校验**（`_check_id_formats`）：校验 `task_id`、`phase_id`、`claim_id` 等是否符合 `{PREFIX}-{TYPE}-{NUM}` 格式
3. **重复 ID 检测**（`_check_duplicate_ids`）：检测 task_list 和 claims 中的重复 ID（排除 `-9999` 模板）
4. **路径安全检查**（`_check_path_safety`）：检查 claims 的 `code_refs`/`test_refs` 是否包含绝对路径或路径穿越（`..`）
5. **人类决策 Schema 校验**（`_check_human_decisions`）：如果 manifest 中存在 `human_decisions` 记录，执行 Schema 验证

schemas 目录回退逻辑：优先使用 `{project_root}/schemas`，如果不存在则回退到内置的 `infra/validation/schemas`。

如果校验失败，输出错误信息并阻断门禁。

---

### 步骤 6：解析 PRD

调用模块：`infra/loader/prd_parser.py:PrdParser.parse_text()`

首先检查 PRD 记录是否存在且 `status == "ok"`，如果不存在则阻断门禁。

将 PRD Markdown 文件解析为结构化数据，提取需求（Requirement）和验收标准（AcceptanceCriteria）。解析结果包含：
- requirements：需求列表（含 req_id、title、priority、category）
- acceptance_criteria：每个需求下的验收标准列表

解析完成后检查 `prd_res.is_valid`，如果为 false 则阻断门禁。

---

### 步骤 7：检查 draft 模式与必需文件

调用模块：`cli/analyze/pipeline.py:_load_context()` 内联逻辑

根据 `prd_res.status` 判断是否为 draft 模式。**非 draft 模式**下，额外要求 `task_list` 和 `architecture_constraints` 必须存在且加载成功，否则阻断门禁。draft 模式下这两个文件为可选。

---

### 步骤 8：加载任务列表

调用模块：`infra/loader/task_loader.py:TaskLoader.load_and_validate()`

前提条件：`task_list` 记录存在且 `status == "ok"`。否则跳过（非 draft 模式下已在步骤 7 阻断）。

加载 `docs/task_list.json`，解析任务数据，并与 PRD 和架构约束进行交叉引用校验：
- 检查任务关联的需求 ID 是否存在
- 检查任务关联的 AC ID 是否存在
- 检查任务关联的模块 ID 和约束 ID 是否存在
- 检查孤立任务（未关联需求或 AC）
- 生成覆盖缺口（gaps）

如果校验失败（`task_res.is_valid` 为 false），阻断门禁。

---

### 步骤 9：加载 Claims

调用模块：`infra/loader/claim_loader.py:ClaimLoader.load()`

前提条件：`claims` 记录存在且 `status == "ok"`，**且** `task_res` 不为 None（即任务列表已成功加载）。如果 `task_res` 为 None，Claims 加载被跳过。

加载 `.vibetracing/claims/` 目录下的所有 CLAIM-*.json 文件，解析 Claim 数据，并与任务列表进行交叉引用校验：
- 检查 Claim 关联的任务 ID 是否存在
- 生成覆盖缺口（gaps）

如果校验失败（`claim_res_loader.is_valid` 为 false），阻断门禁。

---

### 步骤 10：加载人类决策

调用模块：`cli/analyze/pipeline.py:_load_context()` 内联逻辑

从 `manifest.inputs_used` 中查找 `file_key == "human_decisions"` 且 `status == "ok"` 的记录。如果找到，使用其 `content`；否则 `human_decisions_data` 为 None。此步骤不会阻断门禁。

---

### 步骤 11：构建 UnifiedContext

调用模块：`domain/context.py:UnifiedContext`

将所有解析结果汇总到 UnifiedContext 对象中，作为后续阶段的统一数据源：

```yaml
config: {}                          # config.json 内容
prd: PrdParseResult                 # PRD 解析结果
constraints: {}                     # 架构约束
task_result: TaskListLoadResult     # 任务列表解析结果
claims_list: []                     # Claims 列表
manifest: RawInputManifest          # 加载清单
human_decisions: {}                 # 人类决策
config_prefix: "VT"                 # 项目前缀
```

---

## 4. 输出结构

**输出类型**：`Tuple[UnifiedContext, RawInputLoader]`
**输出位置**：内存（通过 pipeline 局部变量传递，不落盘）

### UnifiedContext（统一上下文）

**包/模块**：`domain/context.py:UnifiedContext`

```yaml
config: {}                          # config.json 内容（Dict[str, Any]）
prd: PrdParseResult                 # PRD 解析结果
constraints: {}                     # 架构约束（Dict[str, Any]，可选）
task_result: TaskListLoadResult     # 任务列表解析结果（可选）
claims_list:                        # Claims 列表
  - claim_id: "CLAIM-VT-001"        # Claim ID
    related_task: "TASK-VT-001"     # 关联的任务 ID
    code_refs: [...]                # 代码文件引用列表
    test_refs: [...]                # 测试文件引用列表
    notes: "实现了 CLI 入口"         # 备注
    timestamp: "2026-06-23T12:00:00Z"  # 时间戳
manifest: RawInputManifest          # 加载清单（可选）
human_decisions: {}                 # 人类决策（可选）
config_prefix: "VT"                 # 项目前缀
```

### RawInputLoader（原始加载器）

**包/模块**：`infra/loader/raw_input.py:RawInputLoader`

```yaml
project_root: "/path/to/project"    # 项目根目录
config_data: {}                     # config.json 内容
```

用途：后续阶段可能用到 RawInputLoader 的方法（如 `get_path()`）

## 5. 异常捕获与日志

### 异常情况

| 异常类型 | 退出码 | 触发条件 | 对应步骤 |
|----------|--------|----------|----------|
| `_GateBlocked` | 1 | 必需文件缺失（`manifest.has_required_errors` 为 true） | 步骤 4 |
| `_GateBlocked` | 1 | 文件格式错误（status 为 `parse_error` 或 `read_error`） | 步骤 4 |
| `_GateBlocked` | 1 | Schema/ID/路径校验失败（`validate_inputs()` 返回 `is_valid=false`） | 步骤 5 |
| `_GateBlocked` | 1 | PRD 记录缺失或加载失败 | 步骤 6 |
| `_GateBlocked` | 1 | PRD 解析错误（`prd_res.is_valid` 为 false） | 步骤 6 |
| `_GateBlocked` | 1 | 任务列表或架构约束缺失（非 draft 模式） | 步骤 7 |
| `_GateBlocked` | 1 | 任务列表校验失败（`task_res.is_valid` 为 false） | 步骤 8 |
| `_GateBlocked` | 1 | Claims 校验失败（`claim_res_loader.is_valid` 为 false） | 步骤 9 |

### 日志事件

阶段 1 本身不直接记录日志（logger 在阶段 1 期间初始化）。日志由 `pipeline.py:run_analyze()` 在阶段 1 完成后记录：

| 事件名 | 级别 | 触发时机 | 附加字段 |
|--------|------|----------|----------|
| `run_start` | INFO | logger 初始化完成（阶段 1 末尾） | `is_pre_commit`, `gates_only` |
| `phase_end` | INFO | 阶段 1 完成 | `phase="load_context"`, `duration_ms`, `config_prefix`, `has_prd`, `claims_count` |

### 错误传播

`_load_context()` 不自行捕获业务异常。所有校验失败通过两条路径处理：

1. **`print(stderr)`** — 向终端输出简短错误描述（供用户了解发生了什么）
2. **`raise _GateBlocked(1)`** — 传播到 `run_analyze()` 的 `try/except`，由 `pipeline.py` 捕获并返回退出码 1

阶段 1 不记录日志文件（logger 尚未初始化），错误信息仅通过 stderr 和退出码传递。

---

## 6. 下游依赖

| 下游模块 | 目标包 | 说明 |
|----------|--------|------|
| **阶段 2** | `cli/analyze/gates.py` | 检查 staged 文件是否被 Claim 覆盖（幽灵代码检测） |
| **阶段 5** | `infra/db/loaders.py` | 将 PRD（步骤 6）、Tasks（步骤 8）、Claims（步骤 9）写入内存 SQLite 数据库 |
| **阶段 6** | `domain/evidence/builder.py` | 合并历史证据 + 本次工具结果，生成完整证据链 |
| **阶段 7** | `infra/db/queries.py` | 用 SQL 查询数据库，找出所有"缺口"（需求没任务、任务没测试等） |
