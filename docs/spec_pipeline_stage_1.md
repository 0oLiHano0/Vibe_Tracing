# 阶段 1 模块详解

## 1. 输入来源

| 来源 | 包/模块 | 文件 |
|------|---------|------|
| **配置文件** | `infra/loader/config.py` | `.vibetracing/config.json` |
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
project_prefix: "VT"             # 项目前缀（用于 ID 校验，配置中可选，代码中默认 "VT"）
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
is_draft: false                     # 是否草稿模式
```

---

### RawInputManifest（加载清单）

**输入位置**：内存（由 `RawInputLoader.load()` 构建）
**包/模块**：`infra/loader/raw_input.py:RawInputManifest`

```yaml
has_required_errors: false          # 是否有必需文件加载失败
error_count: 0                      # 加载失败的文件总数
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

## 3. 处理逻辑（重构后的五大阶段）

在 `cli/analyze/pipeline.py:_load_context()` 中，整个阶段一的处理过程收敛为以下 5 个逻辑阶段：

### 阶段 1：物理读取所有输入文件 (Physical Load)

调用模块：`infra/loader/config.py` + `infra/loader/raw_input.py:RawInputLoader`

1. 调用 `load_config(project_root)` 显式加载 `.vibetracing/config.json` 配置文件。
2. 实例化 `RawInputLoader(project_root, config_data=config)`，将配置传入 loader（构造函数无 I/O）。
3. 调用 `RawInputLoader.load()` 一次性物理读取所有治理文件（PRD、Architecture Constraints、Task List、Agent Claims、Human Decisions），并在内存中生成包含原始文件内容（Dict 或纯文本）和哈希校验值的 `RawInputManifest`。在此步骤后，所有物理磁盘读取操作全部结束。

> 路径解析由 `config.py:resolve_path()` 统一处理，loader 和 pipeline 均不硬编码路径。

---

### 阶段 2：静态格式与 Schema 校验 (Static Validation)

调用模块：`infra/validation/checks.py:validate_inputs()`

对内存中已物理加载的所有原始数据统一执行静态格式合规性检查：
1. **必需文件与读取错误检查**：检查 manifest 的加载状态（如果必需文件丢失或有 JSON 解析错误，阻断并 `raise _GateBlocked(1)`）。
2. **读取项目前缀**：获取并设置项目 ID 全局正则匹配前缀（默认 `"VT"`）。
3. **统一格式校验**：调用 `validate_inputs()` 批量对内存数据进行 JSON Schema 验证、ID 正则格式校验、文件内重复 ID 校验以及路径安全（越权/绝对路径）检查。如果校验失败，输出错误并阻断。

---

### 阶段 3：领域模型解析 (Domain Parsing)

调用模块：`infra/loader/` 下的具体解析类

将内存中通过校验的原始数据，转换为强类型的 Python 领域模型对象。在此步骤中，**不进行任何文件之间的跨引用（如 Task 引用 PRD）关系校验**：
1. **解析 PRD**：通过 `PrdParser.parse_text()` 将 Markdown 文本解析为 `PrdParseResult` 实体对象。
2. **解析 Tasks**：通过 `TaskLoader().load_and_validate()` 将 Task List 原始字典反序列化为 `Task` 实体列表，不传入 PRD 和架构参数，只进行任务自身属性自洽校验（如孤立任务检测）。
3. **解析 Claims**：通过 `ClaimLoader().load()` 将 Claims 原始字典反序列化为 `Claim` 实体列表。
4. **提取人类决策**：利用 `records_dict` 快速取得人类决策已反序列化的 Dict 对象。

---

### 阶段 4：业务规则前置判定 (Pre-checks)

调用模块：`cli/analyze/pipeline.py:_load_context()` 内联逻辑

根据领域实体对象进行状态检查：
* 检查 PRD 解析结果的 `status` 是否为 `"draft"`（草稿模式）。
* **非草稿模式下**：强校验 `task_list` 和 `architecture_constraints` 文件在阶段 1 是否加载成功，若不存在则打印错误并阻断流水线。

---

### 阶段 5：构建并返回 UnifiedContext (Context Build)

调用模块：`domain/context.py:UnifiedContext`

将上述所有解析好的领域模型实体，打包为 `UnifiedContext` 对象。

```yaml
config: {}                          # config.json 内容
prd: PrdParseResult                 # PRD 解析结果
constraints: {}                     # 架构约束（可选）
task_result: TaskListLoadResult     # 任务列表解析结果（可选）
claims_list: []                     # Claims 列表
manifest: RawInputManifest          # 原始加载清单
human_decisions: {}                 # 人类决策数据（可选）
config_prefix: "VT"                 # 项目前缀
is_draft: false                     # 是否草稿模式 (prd_res.status == "draft")
```

---

## 4. 输出结构

**输出类型**：`UnifiedContext`
**输出位置**：内存（通过 pipeline 局部变量传递，不落盘）

---

## 5. 异常捕获与日志

### 异常情况

| 异常类型 | 退出码 | 触发条件 | 对应步骤 |
|----------|--------|----------|----------|
| `_GateBlocked` | 1 | config.json 缺失或 `paths` 字段缺失 | 阶段 1 |
| `_GateBlocked` | 1 | 必需文件缺失（`manifest.has_required_errors` 为 true） | 阶段 2 |
| `_GateBlocked` | 1 | 文件格式错误（status 为 `parse_error` 或 `read_error`） | 阶段 2 |
| `_GateBlocked` | 1 | Schema/ID/路径校验失败（`validate_inputs()` 返回 `is_valid=false`） | 阶段 2 |
| `_GateBlocked` | 1 | PRD 记录缺失或加载失败 | 阶段 3 |
| `_GateBlocked` | 1 | PRD 解析错误（`prd_res.is_valid` 为 false） | 阶段 3 |
| `_GateBlocked` | 1 | 任务自洽校验失败（`task_res.is_valid` 为 false） | 阶段 3 |
| `_GateBlocked` | 1 | Claims 自洽校验失败（`claim_res_loader.is_valid` 为 false） | 阶段 3 |
| `_GateBlocked` | 1 | 任务列表或架构约束缺失（非 draft 模式） | 阶段 4 |

> [!NOTE]
> 关联关系检验（如 Task 引用不存在的 AC）下沉至阶段七/八后，引用校验失败将表现为门禁阻断，由门禁引擎统一判定，返回 **退出码 2**。

### 日志事件

阶段 1 运行完成后（`_load_context` 执行成功后），由 `pipeline.py:run_analyze()` 记录：

| 事件名 | 级别 | 触发时机 | 附加字段 |
|--------|------|----------|----------|
| `run_start` | INFO | logger 初始化完成（阶段 1 末尾） | `is_pre_commit`, `gates_only` |
| `phase_end` | INFO | 阶段 1 完成 | `phase="load_context"`, `duration_ms`, `config_prefix`, `claims_count` |

### 错误传播

所有校验失败均抛出 `_GateBlocked(1)` 退出码 1，传播到 `run_analyze()` 捕获。

---

## 6. 下游依赖

| 下游模块 | 目标包 | 说明 |
|----------|--------|------|
| **阶段 2** | `cli/analyze/gates.py` | 检查 staged 文件是否被 Claim 覆盖（幽灵代码检测） |
| **阶段 5** | `infra/db/loaders.py` | 将 PRD、Tasks、Claims 写入内存 SQLite 数据库 |
| **阶段 6** | `domain/evidence/builder.py` | 合并历史证据 + 本次工具结果，生成完整证据链 |
| **阶段 7** | `infra/db/queries.py` | 用 SQL 查询数据库，找出所有"缺口"（包括新增的无效引用 SQL 校验） |

