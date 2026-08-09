# 后端产出清单（Dashboard 前端消费指南）

**生成时间**：2026-07-05
**生成命令**：`PYTHONPATH=src python3 -m vibe_tracing.cli analyze`
**产出根目录**：`output/`

本文档为前端设计提供完整的后端数据契约。Dashboard 通过 `<script type="application/json">` 嵌入 7 份 JSON 数据，客户端渲染；其余文件为原始证据与治理报告。

---

## 1. 文件总览

| # | 文件路径 | 类型 | 大小 | 前端消费方式 |
|---|---|---|---|---|
| 1 | `output/dashboard.html` | HTML（单文件自包含） | ~1.4 MB | 最终呈现物，嵌入 7 份 JSON |
| 2 | `output/traceability_report.json` | JSON | ~1.1 MB | Dashboard 主数据源（trace-report-json） |
| 3 | `output/evidences/test_results.json` | JSON | ~100 KB | Dashboard 测试证据（test-results-json） |
| 4 | `output/evidences/lint_results.json` | JSON | ~5 KB | Dashboard lint 证据（未独立消费，合入 trace-report） |
| 5 | `output/evidences/coverage_reports.json` | JSON | 0 字节（当前为空） | Dashboard 覆盖率证据（coverage-reports-json） |

---

## 2. Dashboard 嵌入的 7 份 JSON

`dashboard.html` 通过 `<script id="xxx-json" type="application/json">` 嵌入以下数据，JS 通过 `document.getElementById('xxx-json').textContent` + `JSON.parse` 读取。

### 2.1 `prd-reqs-json` — PRD 需求列表

**来源**：`docs/prd.md` 解析
**业务含义**：产品需求文档（PRD）中的所有需求及其验收标准，是 Dashboard "需求覆盖" 视图的源头。

```json
[
  {
    "req_id": "REQ-VT-001",
    "title": "全链路需求追踪",
    "priority": "must",
    "acceptance_criteria": [
      {
        "ac_id": "AC-VT-001-01",
        "title": "需求必须能关联任务",
        "is_testing_required": true
      }
    ]
  }
]
```

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `req_id` | string | 需求唯一 ID（`REQ-{项目}-{三位数}`） |
| `title` | string | 需求标题 |
| `priority` | enum | `must` / `should` / `could` |
| `acceptance_criteria` | array | 该需求下的验收标准列表 |
| `acceptance_criteria[].ac_id` | string | AC 唯一 ID（`AC-{需求ID}-{两位序号}`） |
| `acceptance_criteria[].title` | string | AC 标题 |
| `acceptance_criteria[].is_testing_required` | boolean | 是否需要测试证据 |

---

### 2.2 `evidence-idx-json` — 证据索引 / 全链路追踪

**来源**：`infra/db/queries.get_full_chain()` 从 SQLite 查询
**业务含义**：需求 → AC → 任务 → Claim → 测试 → 覆盖率 的完整追踪链路视图（Tab 4 证据索引）。

```json
{
  "run_id": "RUN-7be243d6-...",
  "project_id": "PROJECT-VT",
  "scan_time": "2026-07-05T12:22:16.368443+08:00",
  "full_chain": [
    {
      "req_id": "REQ-VT-001",
      "req_title": "全链路需求追踪",
      "req_priority": "must",
      "req_category": "functional",
      "ac_id": "AC-VT-001-01",
      "ac_title": "需求必须能关联任务",
      "is_testing_required": true,
      "task_id": "TASK-VT-001",
      "task_status": "todo",
      "claim_id": null,
      "test_nodeid": null,
      "test_outcome": null,
      "code_path": null,
      "percent_covered": null
    }
  ]
}
```

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `run_id` | string | 本次分析运行 ID |
| `project_id` | string | 项目 ID |
| `scan_time` | ISO 8601 | 扫描时间戳 |
| `full_chain` | array | 链路记录列表（当前 400 条） |
| `full_chain[].req_id` | string | 需求 ID |
| `full_chain[].req_title` | string | 需求标题 |
| `full_chain[].req_priority` | enum | `must` / `should` / `could` |
| `full_chain[].req_category` | string | 需求分类（`functional` / 自定义） |
| `full_chain[].ac_id` | string\|null | AC ID（无 AC 时为 null） |
| `full_chain[].ac_title` | string\|null | AC 标题 |
| `full_chain[].is_testing_required` | boolean\|null | 是否需要测试 |
| `full_chain[].task_id` | string\|null | 关联任务 ID |
| `full_chain[].task_status` | string\|null | 任务状态（`todo`/`in_progress`/`done`） |
| `full_chain[].claim_id` | string\|null | Claim ID（链路断裂时为 null） |
| `full_chain[].test_nodeid` | string\|null | pytest nodeid |
| `full_chain[].test_outcome` | string\|null | 测试结果（`passed`/`failed`/`skipped`） |
| `full_chain[].code_path` | string\|null | 被覆盖的源码路径 |
| `full_chain[].percent_covered` | number\|null | 覆盖率百分比 |

**前端渲染规则**：
- 字段为 null 时显示灰色 `—` 占位符
- `task_id` 非空但 `claim_id` 为 null 时显示 `⚠️ 未声明` 徽章
- 50 行分页，带"上一页/下一页"按钮

---

### 2.3 `test-results-json` — 测试结果证据

**来源**：`output/evidences/test_results.json`
**业务含义**：所有 pytest 测试用例的执行结果，是 Claim 验证的核心证据。

```json
[
  {
    "nodeid": "tests/test_merge_gate_engine.py::TestClaimExistence::test_ghost_files_produce_issues",
    "outcome": "covered",
    "exit_code": 0,
    "command": "... pytest tests/... --json-report ...",
    "carried_over": false
  }
]
```

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `nodeid` | string | pytest 节点 ID（文件::类::方法） |
| `outcome` | enum | `covered`（通过）/ `failed` / `skipped` |
| `exit_code` | int | pytest 退出码（0=成功） |
| `command` | string | 实际执行的 pytest 命令 |
| `carried_over` | boolean | 是否为历史继承结果（非本次运行） |

---

### 2.4 `coverage-reports-json` — 代码覆盖率证据

**来源**：`output/evidences/coverage_reports.json`
**业务含义**：代码覆盖率报告，用于验证 Claim 中声明的代码路径被实际覆盖。

**当前状态**：空数组 `[]`（项目未启用覆盖率采集）。

**预期 schema**（与 test_results 同构）：

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `source_path` | string | 源码路径 |
| `outcome` | enum | `covered` / `uncovered` |
| `percent_covered` | number | 覆盖率百分比 |
| `command` | string | 采集命令 |
| `carried_over` | boolean | 是否历史继承 |

---

### 2.5 `trace-report-json` — 可追溯性报告（核心）

**来源**：`output/traceability_report.json`
**业务含义**：VT 分析的核心产出，包含 gate 决策、issue 状态、缺口、风险、架构合规等所有治理信息。

```json
{
  "run_id": "RUN-...",
  "project_id": "PROJECT-VT",
  "scan_time": "...",
  "gate_decision": "blocked",
  "per_issue_states": [...],
  "historical_issues": [...],
  "requirement_coverage": [...],
  "gaps": [...],
  "risks": [...],
  "architecture_compliance_status": [...],
  "architecture_violations": [...],
  "unclear_constraints": [...],
  "accepted_rules": [...],
  "acceptance_archive": [...],
  "rule_stats_table": [...],
  "governance_metrics": {...},
  "agent_capability_metrics": {...},
  "metadata": {...}
}
```

#### 2.5.1 顶层字段

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `run_id` | string | 本次分析运行 ID |
| `project_id` | string | 项目 ID |
| `scan_time` | ISO 8601 | 扫描时间戳 |
| `gate_decision` | enum | `pass` / `blocked` — 门禁决策 |

#### 2.5.2 `per_issue_states` — 当前 issue 状态列表

**业务含义**：本次分析检测到的所有 issue（含 CURRENT 与 RESOLVED），是 Dashboard "诊断详情" 视图的核心数据。

```json
{
  "issue_id": "task_failed:CLAIM-VT-096",
  "issue_type": "task_failed",
  "state": "RESOLVED",
  "severity": "WARNING",
  "task_id": "",
  "reason": "Claim CLAIM-VT-096 证据验证失败: test_missing",
  "observed": true,
  "activated": false,
  "resolved": true,
  "accepted": false
}
```

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `issue_id` | string | issue 唯一 ID（`{type}:{target}`） |
| `issue_type` | enum | `no_claim` / `chain_broken` / `task_failed` / `isolated_task` / `substandard` / ... |
| `state` | enum | `CURRENT_BLOCK` / `CURRENT_WARNING` / `HISTORICAL` / `RESOLVED` / `ACCEPTED` |
| `severity` | enum | `BLOCK` / `WARNING` |
| `task_id` | string | 关联任务 ID（可为空） |
| `reason` | string | 人类可读的原因描述 |
| `observed` | boolean | 本次是否被观察到 |
| `activated` | boolean | 是否被激活（进入 CURRENT） |
| `resolved` | boolean | 是否已解决 |
| `accepted` | boolean | 是否被人类接受 |

#### 2.5.3 `historical_issues` — 历史债务 issue 列表

**业务含义**：基线中已存在但本次未触发的历史债务，Dashboard 用于展示"预存债务"。

```json
{
  "issue_id": "no_claim:AC-VT-003-01",
  "issue_type": "no_claim",
  "severity": "BLOCK",
  "task_id": "",
  "reason": "AC AC-VT-003-01 (task None) 未测试覆盖。..."
}
```

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `issue_id` | string | issue 唯一 ID |
| `issue_type` | enum | issue 类型 |
| `severity` | enum | `BLOCK` / `WARNING` |
| `task_id` | string | 关联任务 ID |
| `reason` | string | 原因描述 |

#### 2.5.4 `gaps` — 缺口列表

**业务含义**：需求/AC 未被任务覆盖的缺口。

```json
{
  "item_id": "REQ-VT-003",
  "item_type": "requirement",
  "reason": "Requirement REQ-VT-003 has no task coverage."
}
```

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `item_id` | string | 缺口对象 ID（REQ/AC/Task） |
| `item_type` | enum | `requirement` / `acceptance_criterion` / `task` |
| `reason` | string | 缺口原因 |

#### 2.5.5 `risks` — 风险列表

**业务含义**：由缺口衍生的业务风险，含修复建议。

```json
{
  "risk_id": "RISK-VT-001",
  "description": "需求 REQ-VT-003 缺少关联的开发任务。",
  "severity": "must",
  "business_impact": "需求 REQ-VT-003 缺少关联的开发任务。修复：...",
  "suggested_action": "在 `task_list.json` 中为需求 `REQ-VT-003` 规划并关联开发任务。",
  "evidence_ids": ["EVIDENCE-VT-999"],
  "original_gap_reason": "Requirement REQ-VT-003 has no task coverage."
}
```

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `risk_id` | string | 风险 ID（`RISK-VT-{序号}`） |
| `description` | string | 风险描述 |
| `severity` | enum | `must` / `should` / `could` |
| `business_impact` | string | 业务影响 + 修复指引 |
| `suggested_action` | string | Agent 可执行的修复动作 |
| `evidence_ids` | array | 关联证据 ID 列表 |
| `original_gap_reason` | string | 原始缺口原因 |

#### 2.5.6 `architecture_compliance_status` — 架构合规状态

**业务含义**：每条架构约束的合规状态。

```json
{
  "rule_id": "MOD-VT-001",
  "status": "compliant",
  "severity": "must",
  "title": "Module Boundary: agent_runtime_adapter",
  "description": "为成熟 Agent Runtime 或 CLI 环境提供集成入口。..."
}
```

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `rule_id` | string | 约束 ID（`MOD-VT-xxx` / `PRINCIPLE-VT-xxx` / `GATE-VT-xxx`） |
| `status` | enum | `compliant` / `violated` / `unknown` |
| `severity` | enum | `must` / `should` / `could` |
| `title` | string | 约束标题 |
| `description` | string | 约束描述 |

#### 2.5.7 `architecture_violations` — 架构违反列表

**业务含义**：`status=violated` 的约束子集（当前为空数组）。

**schema**：与 `architecture_compliance_status` 同构。

#### 2.5.8 `unclear_constraints` — 不清晰约束

**业务含义**：需要人类手动确认的约束（manual verification）。

```json
{
  "rule_id": "PRINCIPLE-VT-002",
  "reason": "Manual verification rule PRINCIPLE-VT-002 requires human acceptance."
}
```

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `rule_id` | string | 约束 ID |
| `reason` | string | 需要人工确认的原因 |

#### 2.5.9 `accepted_rules` — 已接受规则

**业务含义**：人类已接受但需手动验证的规则。

```json
{
  "rule_id": "PRINCIPLE-VT-001",
  "title": "证据优先",
  "severity": "must",
  "verification_method": "manual",
  "accepted_by": "human",
  "accepted_at": "2026-06-12T13:47:30Z",
  "stale_acceptance": false
}
```

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `rule_id` | string | 约束 ID |
| `title` | string | 约束标题 |
| `severity` | enum | `must` / `should` / `could` |
| `verification_method` | enum | `manual` / `automated` |
| `accepted_by` | string | 接受者（`human`） |
| `accepted_at` | ISO 8601 | 接受时间 |
| `stale_acceptance` | boolean | 接受是否已过期 |

#### 2.5.10 `acceptance_archive` — 验收存档

**业务含义**：所有 CLOSED task 的验收摘要历史（Tab 5 验收存档）。

**当前状态**：空数组 `[]`（无 CLOSED task）。

**预期 schema**（按设计文档 §3.2.4）：

```json
[
  {
    "task_id": "TASK-VT-XXX",
    "phase_id": "PHASE-VT-016",
    "closed_at": "2026-07-04T10:30:00Z",
    "recommendation": "accept",
    "delivery": "...",
    "severe_risks": [],
    "resolved_block": 5,
    "resolved_warning": 7,
    "remaining_warning": 1
  }
]
```

#### 2.5.11 `rule_stats_table` — 全量规则触发表

**业务含义**：每条规则被触发的次数统计（Tab 8 治理演进）。

```json
{
  "rule_id": "no_claim",
  "description": "任务缺少 Agent Claim 声明",
  "block_count": 319,
  "warning_count": 0,
  "last_triggered": "2026-07-05T02:00:46.776617Z"
}
```

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `rule_id` | string | 规则 ID |
| `description` | string | 规则描述 |
| `block_count` | int | BLOCK 触发次数 |
| `warning_count` | int | WARNING 触发次数 |
| `last_triggered` | ISO 8601 | 最近触发时间 |

**排序规则**：按 `block_count` 降序，"从未触发"沉底。

#### 2.5.12 `governance_metrics` — 治理演进指标

**业务含义**：跨 PHASE 治理效果度量（Tab 8 治理演进）。

```json
{
  "derived_task_ratio": 0.25,
  "avg_iterations_by_phase": {
    "PHASE-VT-016": 3.0
  }
}
```

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `derived_task_ratio` | number | 衍生 task 比例（基于标题匹配的近似指标） |
| `avg_iterations_by_phase` | object | 按 PHASE 分组的平均迭代次数 |

#### 2.5.13 `agent_capability_metrics` — Agent 能力评分

**业务含义**：Agent 执行能力度量（Tab 7 Agent 能力）。

```json
{
  "first_time_right_rate": 0.65,
  "avg_iterations": 2.3,
  "same_category_repeat_tasks": 5,
  "block_concentration": {
    "no_claim": 319,
    "chain_broken": 17
  },
  "capability_warnings": [],
  "closed_task_count": 0
}
```

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `first_time_right_rate` | number | 首次通过率（0-1） |
| `avg_iterations` | number | 平均迭代次数 |
| `same_category_repeat_tasks` | int | 同类重复任务数 |
| `block_concentration` | object | BLOCK 集中度（rule_id → count） |
| `capability_warnings` | array | 能力警告列表（仅 Dashboard 徽章展示，不阻断） |
| `closed_task_count` | int | 已 CLOSED 任务数 |

#### 2.5.14 `metadata` — 元数据

**业务含义**：本次分析的输入/输出文件、exit code 等元信息。

```json
{
  "run_id": "RUN-...",
  "project_id": "PROJECT-VT",
  "scan_time": "...",
  "input_files": {
    "prd": "docs/prd.md",
    "architecture_constraints": "docs/architecture_constraints.json",
    "task_list": "docs/task_list.json",
    "agent_claims": ".vibetracing/claims"
  },
  "output_files": {
    "evidences_dir": "output/evidences",
    "traceability_report": "output/traceability_report.json",
    "dashboard": "output/dashboard.html"
  },
  "gate_decision": "blocked",
  "exit_code": 2,
  "summary": "..."
}
```

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `run_id` | string | 运行 ID |
| `project_id` | string | 项目 ID |
| `scan_time` | ISO 8601 | 扫描时间 |
| `input_files` | object | 输入文件路径映射 |
| `output_files` | object | 输出文件路径映射 |
| `gate_decision` | enum | `pass` / `blocked` |
| `exit_code` | int | 退出码（0=成功，2=BLOCKED，3=closed task 引用） |
| `summary` | string | 人类可读摘要（多 issue 用 `; ` 分隔） |

---

### 2.6 `prop-data-json` — 提案引擎结果

**来源**：`cli/analyze/pipeline.py` 构造
**业务含义**：Proposal Engine 的验证结果与改进提案（当前为空，预留扩展）。

```json
{
  "is_valid": true,
  "errors": [],
  "warnings": [],
  "risks": [],
  "gaps": [],
  "proposals": []
}
```

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `is_valid` | boolean | 提案是否有效 |
| `errors` | array | 错误列表 |
| `warnings` | array | 警告列表 |
| `risks` | array | 风险列表 |
| `gaps` | array | 缺口列表 |
| `proposals` | array | 改进提案列表 |

---

### 2.7 `hints-json` — 字段提示（level2 描述）

**来源**：`src/vibe_tracing/templates/field_hints.json`
**业务含义**：每个字段的 level2 人类可读提示，Dashboard 用于 tooltip 或错误解释。

```json
{
  "input.task_id": "任务编号格式不正确。需要使用 \"TASK-项目前缀-三位数字\" 的格式，请检查并修正。",
  "input.title": "任务缺少标题。每个任务需要一个简短的描述来说明任务内容。",
  "input.phase_id": "...",
  "gate_decision.draft_approved": "..."
}
```

**键格式**：`{namespace}.{field_name}`（如 `input.task_id` / `gate_decision.draft_approved`）
**值格式**：人类可读的中文提示字符串

---

## 3. 原始证据文件

### 3.1 `output/evidences/test_results.json`

**业务含义**：pytest 测试执行结果（同 §2.3）。
**当前数据量**：368 条记录。

### 3.2 `output/evidences/lint_results.json`

**业务含义**：ruff lint 检查结果，用于验证代码风格合规。

```json
{
  "source_path": "src/vibe_tracing/domain/gate/engine.py",
  "outcome": "compliant",
  "violations_count": 0,
  "command": "... ruff check ...",
  "carried_over": false
}
```

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `source_path` | string | 被检查的源码路径 |
| `outcome` | enum | `compliant` / `violated` |
| `violations_count` | int | 违规数量 |
| `command` | string | 执行的 ruff 命令 |
| `carried_over` | boolean | 是否历史继承 |

**当前数据量**：19 条记录。

### 3.3 `output/evidences/coverage_reports.json`

**业务含义**：代码覆盖率报告（同 §2.4）。
**当前数据量**：0 条（项目未启用覆盖率采集）。

---

## 4. 前端 Tab 与数据映射

| Dashboard Tab | 数据源 | 关键字段 |
|---|---|---|
| Tab 1: Overview | `trace-report-json` | `gate_decision` / `per_issue_states` / `risks` |
| Tab 2: Traceability | `prd-reqs-json` + `trace-report-json.requirement_coverage` | `req_id` / `status` |
| Tab 3: Debts | `trace-report-json` | `historical_issues` / `gaps` |
| Tab 4: Evidences | `evidence-idx-json.full_chain` | 14 字段链路记录 |
| Tab 5: Acceptance | `trace-report-json.acceptance_archive` | CLOSED task 验收摘要 |
| Tab 7: Agent Capability | `trace-report-json.agent_capability_metrics` | 4 指标 + 警告徽章 |
| Tab 8: Governance | `trace-report-json.rule_stats_table` + `governance_metrics` | 规则触发表 + 衍生比例 |

---

## 5. Exit Code 语义

| Exit | 语义 | 典型场景 |
|---|---|---|
| `0` | 成功 | gate=PASS |
| `1` | 内部崩溃 | 未捕获异常 |
| `2` | Gate BLOCKED | 检测到可修复 issue |
| `3` | Closed task 引用 | commit 引用已 CLOSED 的 task |

---

## 6. 设计参考

- **Channel 分离架构**：`docs/design_channel_separation.md` §2.2（Channel 契约）
- **全链路追踪查询**：`src/vibe_tracing/infra/db/queries.py::get_full_chain()`
- **Dashboard 渲染器**：`src/vibe_tracing/infra/report/dashboard.py::DashboardRenderer`
- **字段提示源**：`src/vibe_tracing/templates/field_hints.json`
