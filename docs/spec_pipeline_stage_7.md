# 阶段 7 模块详解

## 1. 输入来源

| 来源 | 包/模块 | 文件 |
|------|---------|------|
| **SQLite 内存数据库连接** | `infra/db/__init__.py` | 内存（由阶段 4 `init_in_memory_db()` 创建，阶段 5 灌入数据） |
| **统一上下文** | `domain/context.py` | 内存（由阶段 1 `_load_context()` 构建） |
| **项目根目录** | `cli/main.py` | 命令行参数传入 |
| **暂存区文件集合** | `pipeline.py`（阶段 2 `git diff --cached`） | 内存（由阶段 2 通过 subprocess 获取） |
| **人类决策记录** | `infra/loader/raw_input.py` | 硬盘文件 `.vibetracing/human_decisions.json`（经过 `ctx.human_decisions` 传入） |
| **受影响的 Claim ID 集合** | `pipeline.py`（阶段 2 `find_claimed_and_affected()`） | 内存（由阶段 2 预计算，传入阶段 7 避免在 staleness 中重复遍历） |

---

## 2. 输入结构

### SQLite 内存数据库（conn）

**输入位置**：内存（由 `infra/db:init_in_memory_db()` 创建，`infra/db:load_prd/load_tasks/load_claims/load_architecture_constraints/load_staged_files` 灌入数据）
**包/模块**：Python 标准库 `sqlite3.Connection`

数据库中的表由阶段 5 灌入，包含以下核心表（供阶段 7 的 `check_*` 查询使用）：

| 表名 | 灌入函数 | 内容 |
|------|----------|------|
| `requirements` | `load_prd` | req_id, title, priority, category |
| `acceptance_criteria` | `load_prd` | ac_id, req_id, title, is_testing_required |
| `tasks` | `load_tasks` | task_id, title, status, priority, phase_id 等 |
| `task_requirements` | `load_tasks` | task_id, req_id（多对多关联） |
| `task_acs` | `load_tasks` | task_id, ac_id（多对多关联） |
| `task_modules` | `load_tasks` | task_id, module_id（多对多关联） |
| `task_constraints` | `load_tasks` | task_id, constraint_id（多对多关联） |
| `claims` | `load_claims` | claim_id, related_task, notes, timestamp |
| `claim_code_refs` | `load_claims` | claim_id, code_path（一对多） |
| `claim_test_refs` | `load_claims` | claim_id, test_nodeid（一对多） |
| `test_results` | 阶段 6 `EvidenceBuilder.apply` | nodeid, outcome |
| `coverage_reports` | 阶段 6 `EvidenceBuilder.apply` | source_path, percent_covered, status |
| `staged_files` | `load_staged_files` | file_path |
| `arch_modules` | `load_architecture_constraints` | module_id, name |
| `arch_constraints` | `load_architecture_constraints` | constraint_id |

---

### UnifiedContext（统一上下文）

**输入位置**：内存（由 `_load_context()` 构建）
**包/模块**：`domain/context.py:UnifiedContext`

阶段 7 实际使用的字段：

```yaml
config: {}                          # config.json 内容，其中 id_rules.all_tasks_must_link_requirements_and_acceptance_criteria 控制孤立任务判定
constraints: {}                     # 架构约束数据（Dict[str, Any]，可选），传入 ArchitectureComplianceChecker
task_result: TaskListLoadResult     # 任务列表解析结果，含 tasks 列表，用于 staleness 标记
claims_list:                        # Claims 列表，用于 staleness 标记的 affected item 计算
  - claim_id: "CLAIM-VT-001"
    related_task: "TASK-VT-001"
    code_refs: [...]
    test_refs: [...]
manifest: RawInputManifest          # 加载清单，用于获取 constraints_hash
human_decisions: {}                 # 人类决策记录，在 run_analyze() 中通过 ctx.human_decisions 取出后传入 _run_db_analysis
```

---

### staged_files（暂存区文件集合）

**输入位置**：内存（由阶段 2 `git diff --cached --name-only` 获取）
**包/模块**：Python 标准库 `subprocess`

```yaml
# Set[str]，例：
staged_files:
  - "src/vibe_tracing/cli/main.py"
  - ".vibetracing/claims/CLAIM-VT-003.json"
  - "tests/test_cli.py"
```

用途：传入 `mark_staleness()` 用于陈旧项标记。幽灵代码检测由阶段 2 `detect_ghost_code` 完成，阶段 7 不再重复查询。

---

### human_decisions（人类决策记录）

**输入位置**：硬盘文件 `.vibetracing/human_decisions.json`，经 `ctx.human_decisions` 传入
**包/模块**：`infra/loader/raw_input.py`

```yaml
version: "1.0"                      # 决策记录格式版本
decisions:                          # 决策列表
  - category: "accepted_rule"       # 决策类别
    targetId: "TECH-VT-001"         # 目标规则 ID
    action: "accept"                # 动作："accept"
    decidedBy: "human"              # 决策人
    timestamp: "2026-06-23T12:00:00Z"  # 决策时间戳
```

用途：传入 `ArchitectureComplianceChecker.check()`，用于判断手动校验规则是否已被人类接受。

---

## 3. 处理逻辑

阶段 7 由 `_run_db_analysis()` 函数实现，包含 7 个核心步骤（其中步骤 4 不使用 SQL，为独立的文件系统静态分析）。

---

### 步骤 1：执行数据库查询（12 个 check_*）

调用模块：`infra/db/queries.py` 的 12 个查询函数

对内存 SQLite 数据库执行所有分析查询，检查从需求到测试证据的完整覆盖链路。查询分为三组：

**核心覆盖查询**（结果用于生成缺口）：

| 函数 | 查询内容 | 返回字段 |
|------|----------|----------|
| `check_requirement_coverage(conn)` | 每个需求的 Task → Claim → Test 覆盖状态（不限优先级） | `req_id`, `coverage_status` |
| `check_ac_coverage(conn)` | 每个 MUST 任务/需求的 AC 的 Task → Claim → Test 覆盖状态 | `task_id`, `ac_id`, `coverage_status` |
| `check_claim_evidence(conn)` | 每个 Claim 的 Task 状态 + Test 执行状态 | `claim_id`, `verification_status` |

**辅助查询**（结果放入 `analysis_details` 供阶段 8 门禁和 Dashboard 使用）：

| 函数 | 查询内容 | 返回字段 |
|------|----------|----------|
| `check_dangling_claims(conn)` | Claim 指向不存在的 Task | `claim_id`, `related_task` |
| `check_coverage_violations(conn)` | 覆盖率低于阈值（status=violated）的记录 | `source_path`, `percent_covered` |
| `check_invalid_task_requirements(conn)` | Task 引用了不存在的 Requirement | `task_id`, `req_id` |
| `check_invalid_task_acs(conn)` | Task 引用了不存在的 AC | `task_id`, `ac_id` |
| `check_invalid_task_modules(conn)` | Task 引用了不存在的 Module | `task_id`, `module_id` |
| `check_invalid_task_constraints(conn)` | Task 引用了不存在的 Constraint | `task_id`, `constraint_id` |
| `check_invalid_ac_parent(conn)` | Task 的 AC 其父 Requirement 不在 Task 的关联需求中 | `task_id`, `ac_id`, `parent_req_id` |

**孤立/孤儿查询**（结果独立处理）：

| 函数 | 查询内容 | 返回字段 |
|------|----------|----------|
| `check_isolated_tasks(conn, strict_link)` | 孤立任务（无 REQ 或无 AC 关联） | `task_id`, `reason` |
| `check_architectural_orphans(conn)` | 架构孤儿（状态非 done 且无模块关联） | `task_id`, `reason` |

判定逻辑：
- `coverage_status` / `verification_status` 的可能值由 SQL CASE WHEN 生成，包括 `no_task_for_requirement`、`no_claim_for_task`、`no_tests_declared`、`test_not_run`、`test_failed`、`task_missing`、`task_not_done`、`no_tests`、`test_missing` 等
- 状态值为 `covered` 的记录在 HAVING 子句中被过滤，不返回
- `check_isolated_tasks` 的判定逻辑由 `ctx.config.id_rules.all_tasks_must_link_requirements_and_acceptance_criteria` 控制：
  - 如果为 `true`（strict 模式）：缺少 REQ 或缺少 AC 均视为孤立
  - 如果为 `false`（宽松模式）：同时缺少 REQ 和 AC 才视为孤立

---

### 步骤 2：将查询结果转换为缺口格式

调用模块：`pipeline.py:_db_result_to_gaps()` + `pipeline.py:_gap()`

将步骤 1 中三个核心覆盖查询的结果转换为阶段 8 `MergeGateEngine` 所需的统一缺口格式。

处理逻辑：
1. 遍历 `req_coverage` 列表，对每行调用 `_gap(req_id, "requirement", coverage_status)`
2. 遍历 `ac_coverage` 列表，对每行调用 `_gap(ac_id, "ac", coverage_status, task_id=...)`
3. 遍历 `claim_evidence` 列表，对每行调用 `_gap(claim_id, "claim", verification_status)`

`_gap()` 函数采用查表法：`_GAP_MESSAGES` 是一个 `(item_type, status) → 消息模板` 的映射表。共 15 个模板，覆盖 requirement（5 种状态）、ac（5 种状态）、claim（5 种状态）。未知状态（如 `covered`）未在表中注册，返回 `None`，调用方静默跳过。

每个缺口字典包含三个字段：`item_id`（被检查项的 ID）、`item_type`（类型：`requirement` / `ac` / `claim`）、`reason`（人类可读的缺口描述）。

---

### 步骤 3：添加架构孤儿缺口

调用模块：`pipeline.py:_run_db_analysis()` 内联

将 `check_architectural_orphans(conn)` 的返回结果直接转换为缺口格式并合并到 `merged_gaps` 中：

```yaml
item_id: "TASK-VT-005"              # 孤儿任务的 task_id
item_type: "task"                   # 固定为 "task"
reason: "Architectural orphan: Task TASK-VT-005 is not linked to any module."
```

注意：`check_isolated_tasks` 的结果放入 `analysis_details` 供阶段 8 使用，但不在此步骤转换为缺口。

---

### 步骤 4：架构合规检查

调用模块：`domain/compliance/checker.py:ArchitectureComplianceChecker`

> **注意**：此步骤**不使用 SQL**，与步骤 1 的 DB 查询完全独立。`ArchitectureComplianceChecker` 是纯文件系统静态分析工具——扫描磁盘上的 `.py` 文件，用 Python `ast` 模块解析 import 语句，对照 `architecture_constraints.json` 中的 `module_boundaries` 规则逐条判定跨模块引用是否合规。

判定逻辑：
- 仅当 `ctx.constraints` 不为 `None` 时执行（即架构约束文件加载成功）
- 所有检查均为文件系统 I/O + AST 解析，**不涉及 SQLite**

检查内容：
1. **模块边界**：扫描所有 Python 文件的 import 语句，根据 `architecture_constraints.json` 中定义的 `module_boundaries`（`forbidden_to_call` / `allowed_to_call` / `owned_files`），检查是否存在禁止的跨模块引用
2. **手动规则验收**：遍历 constraints 文件中所有类别的 `verification_method == "manual"` 的 must 级规则——已通过 `human_decisions` 接受 → 记入 `accepted_rules`；未接受 → 记入 `unclear_constraints`
3. **非 manual 规则跳过**：`verification_method != "manual"` 的规则静默跳过——当前无内置 machine 规则检查器，不标记 unclear、不阻断

返回值是一个字典，包含 4 个字段（见 §4 输出结构）。

---

### 步骤 5：生成风险建议

调用模块：`domain/risk/advisor.py:RiskAdvisor`

`RiskAdvisor.generate_risks()` 基于当前的全部缺口和合规检查结果，生成人类可读的风险条目。处理逻辑：

1. **丰富已有 Claim 风险**：对 `claims_analysis`（阶段 7 中传空列表 `[]`）和 `claim_risks`（阶段 7 中传空列表 `[]`）中的每条风险，按 `risk_category` 匹配对应的 `business_impact` 和 `suggested_action`
2. **缺口 → 风险转换**：遍历 `merged_gaps`，按 `item_type` 分类：
   - `requirement` 缺口 → 风险描述"需求缺少关联的开发任务"，严重度 `must`
   - `ac` 缺口 → 风险描述"验收标准缺失通过的测试证据"，严重度 `must`
   - `task` 缺口 → 风险描述"任务缺少 Agent Claim 声明"，严重度 `should`
3. **合规结果 → 风险转换**：
   - `architecture_violations` → 风险描述"架构约束违反"，严重度 `must`
   - `unclear_constraints` → 风险描述"架构约束状态不明确"，严重度 `should`，置信度 `low_confidence`

注意：在阶段 7 的调用中，`claims_analysis` 和 `claim_risks` 均传空列表——阶段 7 只生成基于缺口和合规的风险，不包含 Claim 维度的专项风险分析。

---

### 步骤 6：陈旧项标记（Staleness）

调用模块：`domain/gate/staleness.py:mark_staleness`

标记不在本次暂存变更影响范围内的缺口和风险为 `stale=True`。处理逻辑：

1. 如果 `staged_files` 为空（无暂存文件），所有项保持原样，不标记 stale
2. 否则，根据 `staged_files` 和 `claims_list` 计算受影响的 Claim 集合（通过匹配 Claim 的 `code_refs` / `test_refs` 路径）
3. 通过受影响的 Claim → 关联的 Task → Task 的 `related_requirements` / `related_acceptance_criteria`，推导受影响的 Requirement 和 AC 集合
4. 对 `merged_gaps` 中的每个缺口——按 `item_type` 分派：`claim` 类型检查 `claim_id` 是否在受影响 Claim 集合中、`requirement` 类型检查 `item_id` 是否在受影响 Requirement 集合中、`ac` 类型检查 `item_id` 是否在受影响 AC 集合中——不在则标记 `stale: true`
5. 对 `final_risks` 中的每个风险——仅检查带 `claim_id` 字段的风险（即 Claim 层面的风险）：若 `claim_id` 不在受影响集合中则标记 `stale: true`。从 gaps 和 compliance 派生的风险无 `claim_id` 字段，始终活跃，不参与 staleness 判定

标记为 stale 的项在阶段 8 仍会出现在完整报告中，但不参与门禁判定（由 `_run_analysis_phase` 过滤）。

---

### 步骤 7：构建分析详情字典

调用模块：`pipeline.py:_run_db_analysis()` 内联

将步骤 1 中所有辅助查询的结果打包为 `analysis_details` 字典，供阶段 8 的 `MergeGateEngine.evaluate()` 使用。

---

## 4. 输出结构

**输出类型**：`tuple` — `(merged_gaps, final_risks, compliance_res, analysis_details)`
**输出位置**：内存（通过 pipeline 局部变量传递给阶段 8 `_evaluate_and_output()`）

---

### merged_gaps（缺口列表）

**包/模块**：由 `_db_result_to_gaps()` + 内联合并生成

```yaml
# list[dict]，每项表示一个覆盖缺口
- item_id: "REQ-VT-001"             # 被检查项的 ID（req_id / ac_id / claim_id / task_id）
  item_type: "requirement"          # 类型："requirement" | "ac" | "claim" | "task"
  reason: "Requirement REQ-VT-001 has no task coverage."  # 人类可读的缺口描述
  stale: true                       # 是否陈旧（由 mark_staleness 添加，可选）
- item_id: "AC-VT-001-01"
  item_type: "ac"
  reason: "AC AC-VT-001-01 (task TASK-VT-001) has no claims."
- item_id: "CLAIM-VT-003"
  item_type: "claim"
  reason: "Claim CLAIM-VT-003 has failed tests."
  stale: false
- item_id: "TASK-VT-005"
  item_type: "task"
  reason: "Architectural orphan: Task TASK-VT-005 is not linked to any module."
```

**用途**：传入阶段 8 `_run_analysis_phase()` 过滤 stale 项后，传入 `MergeGateEngine.evaluate()` 进行门禁判定。

---

### final_risks（风险列表）

**包/模块**：`domain/risk/advisor.py:RiskAdvisor.generate_risks()`

```yaml
# list[dict]，每项表示一个业务风险
- risk_id: "RISK-VT-001"            # 风险编号
  description: "需求 REQ-VT-002 缺少关联的开发任务。"  # 风险描述
  severity: "must"                  # 严重度："must" | "should"
  business_impact: "需求没有对应的开发任务覆盖，可能导致功能遗漏或开发偏离方向。"  # 业务影响
  suggested_action: "在 task_list.json 中为需求 REQ-VT-002 规划并关联开发任务。"  # 建议操作
  evidence_ids:                     # 关联的证据 ID
    - "EVIDENCE-SENTINEL"
  original_gap_reason: "Requirement REQ-VT-002 has no task coverage."  # 原始缺口原因
  stale: true                       # 是否陈旧（由 mark_staleness 添加，可选）
- risk_id: "RISK-VT-002"
  description: "架构约束违反 (规则 MOD-B): Forbidden import..."
  severity: "must"
  business_impact: "破坏了既定的架构约束与模块隔离边界..."
  suggested_action: "根据规则 MOD-B 的定义，重构相关文件..."
  evidence_ids:
    - "EVIDENCE-SENTINEL"
```

**用途**：传入阶段 8 `_run_analysis_phase()` 过滤 stale 项后，传入 `MergeGateEngine.evaluate()` 进行门禁判定。

---

### compliance_res（架构合规检查结果）

**包/模块**：`domain/compliance/checker.py:ArchitectureComplianceChecker.check()`

```yaml
# Optional[dict]，仅当 ctx.constraints 不为 None 时返回。包含 4 个字段。
architecture_compliance_status:     # 各规则状态列表
  - rule_id: "MOD-A"                # 模块 ID（来自 architecture_constraints.json 的 module_boundaries）
    status: "compliant"             # 状态："compliant" | "violated" | "unclear"
    severity: "must"                # 严重度："must" | "should"
    title: "Module Boundary: module_alpha"  # 模块名称
    description: "Alpha module — may call B, forbidden to call C"  # 模块职责描述
  - rule_id: "MOD-B"
    status: "violated"              # 跨模块引用违反了 allowed_to_call 白名单
    severity: "must"
    title: "Module Boundary: module_beta"
    description: "Beta module — empty allowed_to_call means nothing is whitelisted"
  - rule_id: "RULE-MANUAL-001"      # 手动校验规则（verification_method == "manual"）
    status: "unclear"               # 未被人类接受时标记为 unclear
    severity: "must"
    title: "某手动校验规则"
    description: "该规则需要人类审核。"
    verification_method: "manual"
architecture_violations:            # 确认的违规列表（仅模块边界违反）
  - rule_id: "MOD-B"
    evidence_id: "EVIDENCE-SENTINEL"
    message: "模块 MOD-B (module_beta) 导入了不在白名单中的模块..."
unclear_constraints:                # 无法确认的约束列表（未接受的手动规则）
  - rule_id: "RULE-MANUAL-001"
    reason: "Manual verification rule RULE-MANUAL-001 requires human acceptance."
accepted_rules:                     # 已接受的手动规则
  - rule_id: "RULE-MANUAL-002"
    title: "某已接受的手动规则"
    severity: "must"
    verification_method: "manual"
    accepted_by: "human"
    accepted_at: "2026-06-23T12:00:00Z"
    stale_acceptance: false         # 接受是否超过 30 天
```

**用途**：传入阶段 8 `_evaluate_and_output()`，再传入 `_run_gate_evaluation()` 供 `MergeGateEngine.evaluate()` 使用。

---

### analysis_details（分析详情字典）

**包/模块**：`pipeline.py:_run_db_analysis()` 内联构建

```yaml
# dict，打包所有辅助查询结果，供阶段 8 门禁判定使用
ghost_files:                        # 固定为空列表（幽灵代码由阶段 2 前置阻断，阶段 7 不再重复查询）
  # 始终为 []
ac_gaps:                            # AC 覆盖原始查询结果（list[dict]），供 Dashboard 展示
  - task_id: "TASK-VT-001"
    ac_id: "AC-VT-001-01"
    coverage_status: "no_tests_declared"
dangling_claims:                    # 悬空 Claim 列表（list[dict]）
  - claim_id: "CLAIM-VT-005"
    related_task: "TASK-NONEXISTENT"
claim_evidence_gaps:                # Claim 证据原始查询结果（list[dict]）
  - claim_id: "CLAIM-VT-003"
    verification_status: "test_failed"
cov_violations:                     # 覆盖率违规列表（list[dict]）
  - source_path: "src/vibe_tracing/cli/main.py"
    percent_covered: 45.2
isolated_tasks:                     # 孤立任务列表（list[dict]）
  - task_id: "TASK-VT-007"
    reason: "isolated"              # 严格模式下："missing_req" | "missing_ac"
arch_orphans:                       # 架构孤儿列表（list[dict]）
  - task_id: "TASK-VT-008"
    reason: "architectural_orphan"
invalid_task_references:            # 无效任务引用（dict of list[dict]）
  invalid_requirements:             # Task 引用不存在的 Requirement
    - task_id: "TASK-VT-001"
      req_id: "REQ-NONEXISTENT"
  invalid_acs:                      # Task 引用不存在的 AC
    - task_id: "TASK-VT-002"
      ac_id: "AC-NONEXISTENT"
  invalid_modules:                  # Task 引用不存在的 Module
    - task_id: "TASK-VT-003"
      module_id: "MOD-NONEXISTENT"
  invalid_constraints:              # Task 引用不存在的 Constraint
    - task_id: "TASK-VT-004"
      constraint_id: "PRINCIPLE-NONEXISTENT"
  invalid_ac_parents:               # Task 的 AC 父 Requirement 不在 Task 关联需求中
    - task_id: "TASK-VT-001"
      ac_id: "AC-VT-002-01"
      parent_req_id: "REQ-VT-002"
```

**用途**：传入阶段 8 `_evaluate_and_output()`，被拆解后分别传入 `_run_gate_evaluation()`（供 `MergeGateEngine.evaluate()` 使用）和 `_render_output()`（供 Dashboard 渲染使用）。

---

## 5. 异常捕获与日志

### 异常情况

阶段 7 自身不直接抛出异常。所有数据库查询异常（SQL 语法错误、表不存在等）由 Python `sqlite3` 模块抛出，沿调用栈传播到 `run_analyze()` 的全局 `except Exception` 捕获，返回退出码 1。

| 异常类型 | 退出码 | 触发条件 |
|----------|--------|----------|
| `sqlite3.OperationalError` | 1（全局捕获） | 数据库表不存在（阶段 5 灌入数据失败或跳过） |
| `sqlite3.IntegrityError` | 1（全局捕获） | 数据约束违反（理论上不应发生，SQLite 内存数据库无外键约束） |
| `Exception`（合规检查子模块） | 1（全局捕获） | `ArchitectureComplianceChecker` 内部异常（如文件读取失败） |
| `Exception`（风险生成子模块） | 1（全局捕获） | `RiskAdvisor` 内部异常 |

> 注意：`ArchitectureComplianceChecker.check()` 内部的 AST 解析异常（`SyntaxError`）由 `get_python_imports()` 静默捕获（记录 DEBUG 日志），不会向上传播。

### 日志事件

阶段 7 自身不记录日志。日志记录在阶段 7 完成后的 `run_analyze()` 中：

| 事件名 | 级别 | 触发时机 | 附加字段 |
|--------|------|----------|----------|
| `phase_end` | INFO | 阶段 7 完成（`_run_db_analysis` 返回后） | `phase="run_analyzers"`, `duration_ms`（阶段 7 耗时）, `gaps_count`（merged_gaps 总数）, `risks_count`（final_risks 总数）, `has_compliance`（是否执行了合规检查） |

子模块的日志（由 `ArchitectureComplianceChecker` 内部记录，均为 DEBUG 级别）：

| 事件名 | 级别 | 触发时机 | 模块 |
|--------|------|----------|------|
| `compliance_module_boundary` | DEBUG | 每个模块边界检查完成时 | ArchitectureComplianceChecker |
| `compliance_import_violation` | DEBUG | 检测到禁止的跨模块 import 或不在白名单中的 import 时 | ArchitectureComplianceChecker |
| `compliance_import_allowed` | DEBUG | 检测到允许的跨模块 import 时 | ArchitectureComplianceChecker |

### 错误传播

```
_run_db_analysis() 内部异常
  → 未被本函数捕获（无 try/except）
  → 传播到 run_analyze() 的 except Exception 全局捕获
  → 打印 "Unexpected error running analyze command: {exc}"
  → 记录 run_analyze_failed 日志
  → 返回退出码 1
```

阶段 7 自身不包含 try/except 块——所有异常均依赖调用方 `run_analyze()` 的全局异常处理。

---

## 6. 下游依赖

| 下游模块 | 目标包 | 说明 |
|----------|--------|------|
| **阶段 8 分析阶段** | `pipeline.py:_run_analysis_phase()` | 接收 `merged_gaps` 和 `final_risks`，过滤 stale 项后得到 `active_gaps` 和 `active_risks`；同时计算 `staged_items` 和 `directly_staged_items` 供门禁的债务感知判定使用 |
| **阶段 8 门禁判定** | `pipeline.py:_run_gate_evaluation()` | 接收 `active_gaps`、`active_risks`、`compliance_res`，以及拆解后的 `analysis_details` 各字段（`ghost_files`、`ac_gaps`、`dangling_claims`、`claim_evidence_gaps`、`cov_violations`、`invalid_task_references`），由 `MergeGateEngine.evaluate()` 综合判定门禁通过或阻断 |
| **阶段 8 报告生成** | `pipeline.py:_build_report_document()` | 接收 `merged_gaps`（含 stale）、`final_risks`（含 stale）、`compliance_res`、`analysis_details.isolated_tasks`，生成完整的追溯报告文档 |
| **阶段 8 Dashboard 渲染** | `pipeline.py:_render_output()` | 接收 `analysis_details` 各字段，渲染到 Dashboard HTML 页面供人类验收 |
