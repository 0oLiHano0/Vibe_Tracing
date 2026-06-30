# 阶段 5 模块详解

## 1. 输入来源

| 来源 | 包/模块 | 文件 |
|------|---------|------|
| **数据库连接** | `infra/db/schema.py` | 阶段 4 输出（内存） |
| **PRD 数据** | `infra/loader/prd_parser.py:PrdParseResult` | `ctx.prd`（阶段 1 加载） |
| **任务列表** | `infra/loader/task_loader.py:TaskListLoadResult` | `ctx.task_result`（阶段 1 加载） |
| **Claims** | `infra/loader/claim_loader.py:Claim` | `ctx.claims_list`（阶段 1 加载） |
| **架构约束** | `infra/loader/raw_input.py:RawInputLoader` | `ctx.constraints`（阶段 1 加载） |
| **暂存区文件列表** | Git subprocess（`git diff --cached --name-only`） | `staged_files`（阶段 2 获取） |

> 所有数据输入都已由阶段 1 完成校验，阶段 5 是一个"纯灌入"环节，不做任何校验。

---

## 2. 输入结构

### 数据库连接（conn）

**输入位置**：内存（由阶段 4 `init_in_memory_db()` 构建）
**包/模块**：`infra/db/schema.py:init_in_memory_db()`

```yaml
type: "sqlite3.Connection"            # SQLite 内存数据库连接
mode: ":memory:"                       # 仅存在于内存中
tables_count: 15                       # 15 张已建好的空表
```

### PrdParseResult（PRD 解析结果）

**输入位置**：内存（由阶段 1 `PrdParser.parse_text()` 构建）
**包/模块**：`infra/loader/prd_parser.py:PrdParseResult`

```yaml
requirements:                          # 需求列表
  - req_id: "REQ-VT-001"              # 需求 ID
    title: "全链路需求追踪"              # 需求标题
    priority: "must"                   # 优先级："must" | "should" | "could" | "unclear"
    category: "functional"             # 类别："functional" | "quality_evolution" | "unclear"
    acceptance_criteria:               # 验收标准列表
      - ac_id: "AC-VT-001-01"         # 验收标准 ID
        title: "需求必须能关联任务"       # 验收标准标题
        is_testing_required: true      # 是否必须有测试：true | false
```

### Task（任务字典）

**输入位置**：内存（由阶段 1 `TaskLoader.deserialize()` 构建，通过 `__dict__` 序列化）
**包/模块**：`infra/loader/task_loader.py:TaskLoader`

```yaml
task_id: "TASK-VT-001"                 # 任务 ID
priority: "must"                       # 优先级："must" | "should" | "could"
status: "in_progress"                  # 状态："todo" | "in_progress" | "done"
related_requirements:                  # 关联的需求 ID 列表（可选）
  - "REQ-VT-001"
related_acceptance_criteria:           # 关联的验收标准 ID 列表（可选）
  - "AC-VT-001-01"
related_modules:                       # 关联的模块 ID 列表（可选）
  - "MOD-VT-001"
related_architecture_constraints:      # 关联的架构约束 ID 列表（可选）
  - "PRINCIPLE-VT-006"
```

### Claim（Claim 字典）

**输入位置**：内存（由阶段 1 `ClaimLoader.deserialize()` 构建，通过 `__dict__` 序列化）
**包/模块**：`infra/loader/claim_loader.py:ClaimLoader`

```yaml
claim_id: "CLAIM-VT-001"              # Claim ID
related_task: "TASK-VT-001"           # 关联的任务 ID
code_refs:                             # 代码文件引用列表（可选）
  - "src/vibe_tracing/cli/main.py"
test_refs:                             # 测试节点引用列表（可选）
  - "tests/test_cli.py::test_func"
```

### architecture_constraints（架构约束字典）

**输入位置**：内存（由阶段 1 `RawInputLoader.load()` 加载）
**包/模块**：`infra/loader/raw_input.py:RawInputLoader`

```yaml
module_boundaries:                     # 模块边界定义
  - module_id: "MOD-VT-001"           # 模块 ID
    name: "core"                      # 模块名称
    owned_files:                       # 归属文件列表
      - "main.py"
    forbidden_to_call:                 # 禁止调用的模块 ID 列表
      - "MOD-VT-002"
architecture_principles:              # 架构原则（可选）
  - principle_id: "PRINCIPLE-VT-006"  # 原则 ID
    title: "..."                      # 原则标题
    severity: "must"                  # 级别："must" | "should" | "could"
dependency_rules:                     # 依赖规则（可选）
  - constraint_id: "DEP-VT-001"       # 约束 ID
    severity: "must"
data_flow_rules:                      # 数据流规则（可选）
storage_rules:                        # 存储规则（可选）
error_handling_rules:                 # 错误处理规则（可选）
logging_rules:                        # 日志规则（可选）
security_rules:                       # 安全规则（可选）
technology_constraints:               # 技术约束（可选）
  - tech_id: "TECH-VT-001"
forbidden_patterns:                   # 禁止模式（可选）
  - pattern_id: "PATTERN-VT-001"
quality_gates:                        # 质量门禁（可选）
  - gate_id: "GATE-VT-001"
```

### staged_files（暂存区文件集合）

**输入位置**：内存（由阶段 2 通过 `git diff --cached --name-only` 获取）
**包/模块**：pipeline.py 内联

```yaml
type: "Set[str]"                       # Git 暂存区文件路径集合
values:
  - "src/module.py"                   # 业务文件
  - ".vibetracing/claims/CLAIM-001.json"  # Claim 文件
  - "docs/prd.md"                     # PRD 文件（治理文件）
```

---

## 3. 处理逻辑

阶段 5 共执行 **5 个数据加载步骤**，每步将内存数据写入阶段 4 创建的空数据库。顺序严格固定。

### 步骤 1：灌入 PRD（必须先执行）

调用模块：`infra/db/loaders.py:load_prd()`

1. 从 `ctx.prd.requirements` 中提取每个需求（requirement），通过 `INSERT OR REPLACE` 写入 `requirements` 表。
2. 从每个需求的 `acceptance_criteria` 中提取验收标准，写入 `acceptance_criteria` 表。
3. 调用 `conn.commit()` 提交变更。

> **为什么必须先执行？** `requirements` 和 `acceptance_criteria` 表是后续 `check_requirement_coverage` 和 `check_ac_coverage` 查询的前提。`load_tasks` 写入的 `task_requirements` 和 `task_acs` 表引用了这些记录。

---

### 步骤 2：灌入任务列表

调用模块：`infra/db/loaders.py:load_tasks()`

1. 遍历 `ctx.task_result.tasks`（Task 字典列表）。
2. 对每个任务，写入 5 张表：
   - `tasks` 表：任务 ID、优先级、状态
   - `task_requirements` 表：任务与需求的关联关系（多对多）
   - `task_acs` 表：任务与验收标准的关联关系（多对多）
   - `task_modules` 表：任务与架构模块的关联关系（多对多）
   - `task_constraints` 表：任务与架构约束的关联关系（多对多）
3. 调用 `conn.commit()` 提交变更。

> `_coerce_strlist()` 函数自动处理空值或 None 值，确保关联字段始终为列表。

---

### 步骤 3：灌入 Claims

调用模块：`infra/db/loaders.py:load_claims()`

1. 遍历 `ctx.claims_list`（Claim 字典列表）。
2. 对每个 Claim，写入 3 张表：
   - `claims` 表：Claim ID、关联任务 ID
   - `claim_code_refs` 表：Claim 与代码文件的关联关系（一对多）
   - `claim_test_refs` 表：Claim 与测试节点的关联关系（一对多）
3. 空字符串引用（`""`）被跳过，不写入。
4. 调用 `conn.commit()` 提交变更。

---

### 步骤 4：灌入架构约束

调用模块：`infra/db/loaders.py:load_architecture_constraints()`

1. 从 `ctx.constraints`（架构约束字典）中提取：
   - `module_boundaries` 列表 → 写入 `arch_modules` 表（记录模块 ID）
   - 各规则分类中的 `principle_id` / `constraint_id` / `rule_id` / `gate_id` / `pattern_id` / `tech_id` / `dep_id` → 写入 `arch_constraints` 表（记录约束 ID）
2. 规则分类包括：`architecture_principles`、`dependency_rules`、`data_flow_rules`、`storage_rules`、`error_handling_rules`、`logging_rules`、`security_rules`、`technology_constraints`、`forbidden_patterns`、`quality_gates`
3. 调用 `conn.commit()` 提交变更。

---

### 步骤 5：灌入暂存区文件列表

调用模块：`infra/db/loaders.py:load_staged_files()`

1. 遍历 `staged_files` 集合（从 `git diff --cached --name-only` 获取的暂存文件路径）。
2. 将每个文件路径写入 `staged_files` 表。
3. 调用 `conn.commit()` 提交变更。

> 暂存区文件表是阶段 7 `check_ghost_code()` 查询的数据来源：通过 `staged_files LEFT JOIN claim_code_refs` 找出未被任何 Claim 覆盖的文件。

---

## 4. 输出结构

**输出类型**：无返回值（所有 `load_*` 函数返回 `None`）
**输出位置**：内存 SQLite 数据库（流水线的 `conn` 对象，在阶段 6/7/8 继续使用）

数据库各表的灌入结果如下（参见阶段 4 文档的 15 张 Schema）：

```yaml
# 灌入完成后数据库内容快照（示例）
requirements:                          # 由 load_prd 写入
  - req_id: "REQ-VT-001"              # 需求记录
    title: "全链路需求追踪"
    priority: "must"
    category: "functional"

acceptance_criteria:                   # 由 load_prd 写入
  - ac_id: "AC-VT-001-01"             # 验收标准记录
    req_id: "REQ-VT-001"
    title: "需求必须能关联任务"
    is_testing_required: 1

tasks:                                 # 由 load_tasks 写入
  - task_id: "TASK-VT-001"            # 任务记录
    priority: "must"
    status: "in_progress"

task_requirements:                     # 由 load_tasks 写入
  - task_id: "TASK-VT-001"
    req_id: "REQ-VT-001"

task_acs:                              # 由 load_tasks 写入
  - task_id: "TASK-VT-001"
    ac_id: "AC-VT-001-01"

task_modules:                          # 由 load_tasks 写入
  - task_id: "TASK-VT-001"
    module_id: "MOD-VT-001"

task_constraints:                      # 由 load_tasks 写入
  - task_id: "TASK-VT-001"
    constraint_id: "PRINCIPLE-VT-006"

claims:                                # 由 load_claims 写入
  - claim_id: "CLAIM-VT-001"
    related_task: "TASK-VT-001"

claim_code_refs:                       # 由 load_claims 写入
  - claim_id: "CLAIM-VT-001"
    code_path: "src/module.py"

claim_test_refs:                       # 由 load_claims 写入
  - claim_id: "CLAIM-VT-001"
    test_nodeid: "tests/test_module.py::test_func"

arch_modules:                          # 由 load_architecture_constraints 写入
  - module_id: "MOD-VT-001"

arch_constraints:                      # 由 load_architecture_constraints 写入
  - constraint_id: "PRINCIPLE-VT-006"

staged_files:                          # 由 load_staged_files 写入
  - file_path: "src/module.py"

# 以下 2 张表由阶段 6 灌入，阶段 5 未填写：
# test_results:                         # (阶段 6 写入)
# coverage_reports:                     # (阶段 6 写入)
```

---

## 5. 异常捕获与日志

### 异常情况

| 异常类型 | 退出码 | 触发条件 |
|----------|--------|----------|
| `KeyError` | 1 | 任务字典缺少 `task_id` / `priority` / `status` 等必需键（上游验证应已拦截） |
| `sqlite3.IntegrityError` | 1 | NOT NULL 约束违反（如 `requirements.title` 为 None 写入 NOT NULL 列） |

> 本阶段无 try/except 块，异常传播到 `run_analyze()` 的外层捕获。

### 日志事件

本阶段不记录日志。5 个 `load_*` 函数均为纯数据写入操作，无 I/O 意义上的"事件"。整体耗时反映在相邻阶段的 `phase_end` 日志中。

### 错误传播

阶段 5 在 `run_analyze()` 的顶级 `try` 块内执行。任何数据库异常传播到第 407 行的 `except Exception as exc` 通用捕获点，打印 "Unexpected error running analyze command: {exc}"，返回退出码 1。

---

## 6. 下游依赖

| 下游模块 | 目标包 | 说明 |
|----------|--------|------|
| **阶段 6：构建证据** | `domain/evidence/builder.py:EvidenceBuilder.apply()` | 读取 `test_results` / `coverage_reports` 表（阶段 6 负责写入）；通过 `purge_stale_cache()` 读取 `carried_over` 字段。不依赖阶段 5 写入的表 |
| **阶段 7：需求覆盖分析** | `infra/db/queries.py:check_requirement_coverage()` | 读取 `requirements`、`task_requirements`、`tasks`、`claims`、`claim_test_refs`、`test_results` 进行 6 表 JOIN 分析 |
| **阶段 7：AC 覆盖分析** | `infra/db/queries.py:check_ac_coverage()` | 读取 `acceptance_criteria`、`requirements`、`task_acs`、`tasks`、`claims`、`claim_test_refs`、`test_results` 进行 7 表 JOIN 分析 |
| **阶段 7：Claim 证据分析** | `infra/db/queries.py:check_claim_evidence()` | 读取 `claims`、`tasks`、`claim_test_refs`、`test_results` 进行 4 表 JOIN 分析 |
| **阶段 7：幽灵代码检查** | `infra/db/queries.py:check_ghost_code()` | 读取 `staged_files`、`claim_code_refs`、`claims`、`tasks` 进行 4 表 LEFT JOIN 分析 |
| **阶段 7：悬空 Claim 检查** | `infra/db/queries.py:check_dangling_claims()` | 读取 `claims`、`tasks` 进行 LEFT JOIN 分析 |
| **阶段 7：孤立任务检查** | `infra/db/queries.py:check_isolated_tasks()` | 读取 `tasks`、`task_requirements`、`task_acs` 进行 LEFT JOIN 分析 |
| **阶段 7：架构孤儿检查** | `infra/db/queries.py:check_architectural_orphans()` | 读取 `tasks`、`task_modules` 进行 LEFT JOIN 分析 |
| **阶段 7：无效引用检查** | `infra/db/queries.py:check_invalid_task_*()` | 读取 `task_requirements` + `requirements`、`task_acs` + `acceptance_criteria`、`task_modules` + `arch_modules`、`task_constraints` + `arch_constraints`、`task_acs` + `acceptance_criteria` + `task_requirements` 等配对表进行跨文件一致性校验 |
| **阶段 8：全链路追踪** | `infra/db/queries.py:get_full_chain()` | 进行 9 表 JOIN 查询（`requirements` → `acceptance_criteria` → `task_requirements` → `tasks` → `claims` → `claim_test_refs` → `test_results` → `claim_code_refs` → `coverage_reports`），生成完整的追溯链数据 |
