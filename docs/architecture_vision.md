# Vibe Tracing 架构愿景

> **文档定位**：本文档是架构愿景层，定义"为什么重构"和"核心设计原则"。
>
> - 具体设计（接口契约、文件变更）→ [`analyze_redesign.md`](analyze_redesign.md)
> - 执行计划（Phase 任务清单、偏离点跟踪）→ [`analyze_execution_plan.md`](analyze_execution_plan.md)
> - 格式校验实现（第一层校验的代码实现）→ `src/vibe_tracing/infra/validation/`

---

## 一、 现状与问题分析

### 1. 现状数据流
* **开发声明 (Claims)**：存放在 `.vibetracing/claims/current.json`。
* **证据收集 (Evidences)**：运行 `vt analyze` 时，由测试/分析工具生成，汇总至 `output/evidence_index.json`。
* **门禁判定 (Merge Gate)**：[merge_gate_engine.py](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/merge_gate_engine.py) 使用 Python 嵌套循环手工拼装内存中的字典并比对规则。

### 2. 核心 Bug 与设计痛点
* **数据结构不匹配导致门禁绕过**：
  * **问题 1**：门禁代码检查 `details.get("test_category") == "test"`，但实际写入的字段为 `"tool_category": "test"`，导致无法匹配到测试结果。
  * **问题 2**：门禁代码检查 `ev.get("status") == "passed"`，但根据 Schema，测试证据的 `status` 只能是 `"covered"`（真正的测试结果 `"passed"` 存放在 `details.outcome` 中）。这导致就算有测试数据，也被判定为未通过。
* **单一 JSON 文件膨胀**：所有类型的工具证据（pytest 用例、覆盖率、lint、安全扫描）全部堆在一个 JSON 文件中，行数破万，极难进行 Git 评审与日常查阅。
* **人肉拼装逻辑复杂**：在 Python 内存中对 Task ➡️ Claim ➡️ Code ➡️ Test 之间的多对多关系进行映射，需要维护多层嵌套字典，极易产生逻辑缝隙。

---

## 二、 识别并清除过度设计 (De-engineering & Optimization)

在将单一的 Evidence Index 拆分为多个本地域 JSON，并引入 SQLite 进行关系化查询后，我们可以**顺藤摸瓜清除以下多项严重的过度设计（Over-engineering）与冗余**：

### 1. 彻底废除"通用证据外壳" (Generic Wrapper Redundancy)
在拆分后的 JSON 证据文件中，**完全抛弃通用外壳与 `details` 嵌套**，直接采用扁平化、领域特定的字段。这不仅让文件可读性极高，也免去了 Python 和 JS 中嵌套取值的繁琐与潜在空指针风险。

### 2. 彻底废除证据文件中的"顺序 ID 编号" (Sequential ID Churn)
对于测试结果，`nodeid` (如 `tests/test_x.py::test_y`) 是天然且绝对唯一的标识符；对于覆盖率，源码文件路径 `source_path` 是天然唯一的标识符。
在数据库和 JSON 存储中**完全移除 `evidence_id` 字段**，从源头上解决添加测试文件导致的 Git 冲突与 Diff 污染。

### 3. 利用 SQL 的 `UPSERT` 彻底干掉复杂的继承逻辑 (Timestamp & mtime Redundancy)
引入内存数据库后，**完全不进行任何文件修改时间戳（mtime）比对**。
* 启动时把上一次落盘的 JSON 缓存全量读入 SQLite 表中（标记 `carried_over = 1`）。
* 只对本次修改的代码和测试运行工具，产生局部最新结果。
* 用 `INSERT OR REPLACE INTO` (UPSERT) 直接把新结果拍入数据库，相同主键的记录自动覆盖更新（`carried_over` 重置为 `0`），未重跑的记录在数据库中被原封不动保留。
* **陈旧缓存清理**：UPSERT 只能覆盖已存在的 key。如果用户删除或重命名了测试用例（如 `test_old` → `test_new`），旧记录不会被新结果覆盖，将永久残留形成"幽灵测试"。因此在 UPSERT 之前，必须按目标文件清理旧缓存：`DELETE FROM test_results WHERE (nodeid LIKE 'F::%' OR nodeid = 'F') AND carried_over = 1`。同理对 `coverage_reports` 按 `source_path` 清理。
* **物理存在性检查**：`load_initial_cache()` 加载历史 JSON 时，应检查文件在磁盘上是否物理存在，已删除的文件不予载入。
* 最终全量导出数据库写回 JSON 即可。

### 4. 彻底废除 Claims 的"清除与归档"机制 (Eliminate Claims Archiving)
在老架构下，门禁通过后系统会运行 `_archive_claims` 将当前 `current.json` 里的声明移动到 `archive/commit-{hash}.json` 并清空该文件。这导致后续分析失去了历史声明上下文，使得全量分析无法正确校验历史任务。
* **解决方案**：完全删除 `_archive_claims` 代码及对应的 `archive/` 物理目录，Claims 账本转为累积式。

---

## 三、 重构核心设计

### 1. "一任务一声明文件" (One File Per Claim)
为了避免多个开发人员在同一个 Claims 文件中追加记录产生 Git 冲突，并提供极其稳定的活跃声明识别，本重构采用"一任务一声明文件"的设计：
* **文件存储**：所有的开发声明不再放在单个 JSON 数组中，而是以独立文件存放在 `.vibetracing/claims/` 目录下，文件命名格式为 `CLAIM-{config_prefix}-{task_num}.json`（例如 `CLAIM-VT-050.json`）。
* **活跃声明（Active Claims）识别**：
  * VT 不再运行复杂的 `git show HEAD:claims.json` 子进程进行文件历史版本对比。
  * **规则**：VT 整合三个来源获取活跃文件列表：
    1. `git diff --cached --name-only`（已暂存）
    2. `git diff --name-only`（已修改未暂存）
    3. `git status --porcelain`（未跟踪的新文件）
  * 三者合并后匹配 `.vibetracing/claims/CLAIM-*.json` 的文件，即为本次运行的"活跃声明"。仅在 `--pre-commit` 模式下仅使用 `git diff --cached`（因为 hook 只关心暂存区）。这确保本地开发预览（未 `git add`）与 pre-commit 钩子行为一致。

---

### 2. 双层校验设计原则 (Double-Layer Validation Principle)
为了同时兼顾"快速错误定位"与"多错误一次性收集报告"的开发体验，系统对所有数据实体均采取**双层校验**机制：

* **第一层：格式静态校验 (Syntax/Validation)**
  * **执行时机**：在 `RawInputLoader.load()` 之后、数据灌入 SQLite 之前，由 `infra/validation/checks.py` 的 `validate_inputs()` 统一执行。
  * **唯一实现位置**：`infra/validation/` 包。db.py 的 `load_*` 函数不再执行格式校验，只负责数据泵（INSERT）。
  * **设计决策**：所有第一层格式校验收拢到 validation 模块单一入口，db.py 失去自保护能力但通过文档约定确保调用方先执行校验。
  * **校验内容**：检查 ID 命名是否符合正则、字段是否存在、枚举值（如 `status`、`priority`）是否合法、路径是否越界等静态规则。
  * **处理方式**：只要第一层校验失败，**直接拒绝灌入 SQLite**，当场阻断并打印单点错误。
* **第二层：关系存在性校验 (Relational/Referential Validation)**
  * **执行时机**：数据成功灌入 SQLite 数据库之后。
  * **校验内容**：检查跨表实体关系是否合法（如 Claim 指向的 Task 是否存在、Task 关联的 AC 是否在 PRD 中定义等）。
  * **处理方式**：为了不因为单个异常导致整个导入事务被数据库硬性中断（从而漏报其他错误），**在 DDL 中不设置硬性的物理 `FOREIGN KEY` 约束，而是通过 SQL 的 `LEFT JOIN` 进行软校验**。这样能够把全量错误收集为列表，一次性输出给 Agent，极大提升修复效率。

> **第一层格式校验的代码实现**：`infra/validation/` 包封装了所有格式校验逻辑，作为数据进入分析管道前的守门人。
>
> | 模块 | 职责 |
> |---|---|
> | `validation/checks.py` | 校验入口 `validate_inputs()`，执行 Schema 校验、ID 格式、重复 ID、路径安全、human_decisions 结构校验 |
> | `validation/ids.py` | 13 种 ID 正则模式（REQ/TASK/AC/DOD 等）+ 项目前缀校验 |
> | `validation/schema_validator.py` | JSON Schema 校验引擎，基于 jsonschema 库 |
> | `validation/schemas/` | 6 个 JSON Schema 契约文件 |
>
> 校验在 `RawInputLoader.load()` 之后、数据灌入 SQLite 之前执行，采用"不短路"策略（所有规则依次执行，不因前面失败而跳过后面）。
>
> **与 db.py 的关系**：db.py 中原有的 `validate_task`、`validate_claim`、`validate_test_result`、`validate_coverage_report` 函数将被移除，其逻辑下沉到 validation 模块。db.py 的 `load_*` 函数仅负责数据泵（INSERT），不再执行格式校验。
>
> ⚠️ **当前状态**：上述为目标架构。当前 db.py 仍包含 validate_* 函数且被 load_* 调用，计划在 Phase 1（task/claim）和 Phase 3（test_result/coverage）中迁移到 validation 模块。详见 [`analyze_execution_plan.md`](analyze_execution_plan.md) 的 GAP-VAL-001。

---

### 3. 双层校验在各个实体中的应用规范

> **第一层校验的统一入口**：`validate_inputs(manifest, project_prefix, schemas_dir)` 一次性执行以下 5 类格式校验，不做短路（即使前面发现问题仍继续校验后续规则）：
>
> | 校验规则 | 实现函数 | 覆盖的实体 |
> |---|---|---|
> | JSON Schema 合规 | `_check_schemas()` → `SchemaValidator.validate_dict()` | task_list, agent_claims, architecture_constraints, human_decisions |
> | ID 格式 + 项目前缀 | `_check_id_formats()` → `ids.validate_id()` | task_id, phase_id, claim_id, related_task, ac_id, req_id |
> | 同文件重复 ID | `_check_duplicate_ids()` | task_id, claim_id |
> | 路径安全 | `_check_path_safety()` | claim 的 code_refs, test_refs |
> | human_decisions 结构 | `_check_human_decisions()` → `SchemaValidator.validate_dict()` | human_decisions |
>
> **尚未覆盖的第一层校验**（需在后续 Phase 中补全）：
>
> | 实体 | 缺失的校验规则 | 计划补全位置 |
> |---|---|---|
> | Test Results | nodeid 非空+格式、outcome 枚举、exit_code 非负整数 | Phase 3 创建 `test_results.schema.json` 后注册到 validation |
> | Coverage Reports | source_path 合法相对路径、percent_covered 0-100、status 枚举 | Phase 3 创建 `coverage_reports.schema.json` 后注册到 validation |
> | Claims (单文件) | claim_id 正则、related_task 正则、code_refs/test_refs 路径安全 | Phase 2 创建 `claim_file.schema.json` 后注册到 validation |
> | Ghost Code | 暂存文件路径格式验证 | Phase 5（Gate 2 重构时） |

#### A. 声明实体 (Claims)
* **第一层 (格式)**：
  * 检查 `claim_id` 符合 `CLAIM-[A-Z]+-\d{3,4}$` 正则；
  * 检查 `related_task` 符合 `TASK-[A-Z]+-\d{3,4}$` 正则；
  * 检查并校验 `code_refs` 和 `test_refs` 中的每个文件路径是否为合法的项目内**相对路径**（不得包含 `../` 进行路径穿越，且不能为绝对路径）。
* **第二层 (关系)**：通过 `LEFT JOIN` 软校验（不使用硬 FOREIGN KEY）。如果关联的 Task 在 `tasks` 表中不存在，`check_dangling_claims()` 查询会将其收集到错误列表中，与其他错误一次性输出给 Agent，避免硬 FK 在第一个错误时中断事务导致无法批量报告。

#### B. 任务实体 (Tasks)
* **第一层 (格式)**：
  * 检查 `task_id` 符合 `TASK-[A-Z]+-\d{3,4}$` 正则；
  * 检查 `priority` 属于 `must | should | could` 枚举值；
  * 检查 `status` 属于 `todo | in_progress | done | blocked` 枚举值；
  * 检查 `related_acceptance_criteria` (AC) 中的每个 `ac_id` 是否符合 `AC-[A-Z]+-\d{3,4}-\d{2}$` 正则。
* **第二层 (关系)**：运行 SQL 查询，找出任务关联的 AC 是否不存在于 PRD（`docs/prd.md`）已定义的 AC 列表中（即死链判定）。

#### C. 代码与任务关联判定 (Ghost Code Gate)
* **第一层 (格式)**：Git 暂存文件路径格式验证（必须为项目根目录下的合法路径）。
* **第二层 (关系)**：检查暂存的业务代码文件中，有哪些没有通过活跃声明关联到合法任务（幽灵代码检测）。基于 `staged_files` 表与 `claim_code_refs` 表的 JOIN 查询，一次性返回所有幽灵代码文件，无需 Python 循环：
  ```sql
  SELECT sf.file_path
  FROM staged_files sf
  LEFT JOIN claim_code_refs ccr ON sf.file_path = ccr.code_path
  LEFT JOIN claims c ON ccr.claim_id = c.claim_id
  LEFT JOIN tasks t ON c.related_task = t.task_id
  WHERE ccr.code_path IS NULL;
  ```

#### D. 测试结果实体 (Test Results)
* **第一层 (格式)**：
  * 检查 `nodeid` 不能为空且格式合法（包含 `::` 的 Python 测试函数路径，或合法的测试文件路径）；
  * 校验 `outcome` 必须为 `passed | failed | skipped` 中的一个；
  * 校验 `exit_code` 必须为非负整数。
* **第二层 (关系)**：运行 SQL 查询，检测开发声明（Claims）中引用的测试用例，是否在客观测试结果（`test_results`）中不存在或没有通过（测试死链/未覆盖测试判定）：
  ```sql
  SELECT ctr.claim_id, ctr.test_nodeid
  FROM claim_test_refs ctr
  LEFT JOIN test_results tr ON ctr.test_nodeid = tr.nodeid
  WHERE tr.nodeid IS NULL OR tr.outcome != 'passed';
  ```

#### E. 覆盖率报告实体 (Coverage Reports)
* **第一层 (格式)**：
  * 检查 `source_path` 不能为空，且必须是合法的项目内相对路径（不允许包含 `../` 越界或为绝对路径）；
  * 校验 `percent_covered` 必须为 `0.0` 至 `100.0` 之间的浮点数；
  * 校验 `status` 必须为 `compliant | violated` 中的一个。
* **第二层 (关系)**：运行 SQL 查询，检测在活跃任务中包含的修改文件，是否在覆盖率结果（`coverage_reports`）中标记为 `violated`，或缺失覆盖率记录（覆盖率违规/未覆盖判定）：
  ```sql
  SELECT ccr.code_path, cr.percent_covered, cr.status
  FROM claim_code_refs ccr
  JOIN claims c ON ccr.claim_id = c.claim_id
  JOIN tasks t ON c.related_task = t.task_id
  LEFT JOIN coverage_reports cr ON ccr.code_path = cr.source_path
  WHERE t.status = 'in_progress' AND (cr.source_path IS NULL OR cr.status = 'violated');
  ```

---

### 4. 门禁规则总览 (Gate Rules Overview)

> 以下规则由 `merge_gate_engine.py` 和 `architecture_compliance_checker.py` 在 `vt analyze` 时自动执行。

| 规则编号 | 名称 | 判定逻辑 | 代码位置 |
|---|---|---|---|
| GhostCodeReconciler | 幽灵代码检测 | staged 业务代码文件 - 活跃 Claim 的 code_refs = 幽灵文件集合。pass（无幽灵文件）/ blocked（存在幽灵文件） | `src/vibe_tracing/domain/ghost_code_reconciler.py` |
| GATE-VT-001 | 必需输入文件必须存在 | 检查 `docs/prd.md`、`docs/architecture_constraints.json`、`docs/task_list.json` 三个文件路径是否存在。compliant（全部存在）/ violated（任一缺失） | `src/vibe_tracing/domain/architecture_compliance_checker.py` |
| GATE-VT-002 | JSON 必须通过 Schema 校验 | 对每个 JSON 文件（task_list、architecture_constraints、CLAIM-*.json）执行 JSON Schema 校验。pass（全部通过）/ violated（任一失败） | `src/vibe_tracing/infra/validation/schema_validator.py` |
| GATE-VT-003 | Must 需求必须有任务覆盖 | 对每个 Must 级 REQ，检查是否存在 task 的 `related_requirements` 包含该 REQ ID。pass（全部覆盖）/ violated（存在无任务的 Must REQ） | `src/vibe_tracing/analyzers/requirement_task_analyzer.py` |
| GATE-VT-004 | Must AC 必须有测试覆盖 | 对每个 Must 级 AC，检查是否存在 test_ref 指向的测试通过且显式声明关联该 AC。pass（全部覆盖）/ violated（存在无测试的 Must AC） | `src/vibe_tracing/analyzers/ac_test_analyzer.py` |
| GATE-VT-005 | Claim 必须有外部证据 | 对每个 completed Claim，检查 `evidence_refs` 是否指向 `evidences/*.json` 中的外部证据（排除 claim 自身）。pass（全部有证据）/ violated（存在无证据的 Claim） | `src/vibe_tracing/analyzers/claim_evidence_analyzer.py` |
| GATE-VT-006 | Must 架构约束不得被违反 | 检查是否存在 `status=violated` 且 `severity=must` 的约束。compliant（无违反）/ violated（存在 Must 级违反） | `src/vibe_tracing/domain/architecture_compliance_checker.py` |

**门禁规则与验收标准的区别**：

| 维度 | 门禁规则 | 验收标准（AC） |
|------|----------|----------------|
| 判定方式 | 机器自动判定 | 需要人类判断或开发过程中验证 |
| 判定结果 | 二元：pass / fail | 多级：covered / partial / missing / unclear |
| 阻断行为 | 直接阻断提交 | 不直接阻断，作为交付依据 |
| 存储位置 | 代码实现（merge_gate_engine / compliance_checker） | PRD 中的 AC 条目 |
| 举例 | "没有 Claim 不允许提交" | "人类决策必须与系统门禁分离" |

---

## 四、 拆分后的 JSON 字段设计

所有的证据 JSON 文件存放在 `output/evidences/` 目录下。

### A. 测试结果证据：`output/evidences/test_results.json`
* **数据结构**：`Array[Object]` （去除 `details` 嵌套、去除 `evidence_id`、去除 `covers` 冗余）
  ```json
  [
    {
      "nodeid": "tests/test_auth.py::test_login_success",
      "outcome": "passed",                      // 枚举："passed" | "failed" | "skipped"
      "exit_code": 0,
      "command": "pytest tests/test_auth.py...",
      "carried_over": false
    }
  ]
  ```

### B. 覆盖率证据：`output/evidences/coverage_reports.json`
* **数据结构**：`Array[Object]` （去除嵌套与通用外壳）
  ```json
  [
    {
      "source_path": "src/vibe_tracing/db.py",
      "percent_covered": 85.5,
      "num_statements": 42,
      "status": "compliant",                      // 枚举："compliant" | "violated"
      "carried_over": false
    }
  ]
  ```

### C. 开发声明文件（单文件）：`.vibetracing/claims/CLAIM-VT-001.json`
* **数据结构**：`Object` （单个声明对象，由 Agent 提交，不清空）
  ```json
  {
    "claim_id": "CLAIM-VT-001",
    "related_task": "TASK-VT-001",
    "code_refs": ["src/vibe_tracing/db.py"],
    "test_refs": ["tests/test_db.py::test_init"],
    "notes": "Implemented db helper",
    "content_hash": "sha256...",
    "timestamp": "2026-06-13T12:00:00Z"
  }
  ```
