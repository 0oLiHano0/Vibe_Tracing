# 架构愿景

> 定义"为什么重构"和"核心设计原则"。
> 具体接口/步骤 → [`refactoring_design.md`](refactoring_design.md)

---

## 1. 原始问题

| # | 问题 | 说明 |
|---|------|------|
| B1 | 字段名不匹配 | 门禁检查 `test_category`，实际写入 `tool_category`；检查 `status=="passed"`，实际在 `details.outcome` |
| B2 | 单一 JSON 膨胀 | 所有工具证据堆在一个文件，行数破万，无法 Git 评审 |
| B3 | 人肉拼装 | Python 内存中多层嵌套字典拼装 Task→Claim→Code→Test 关系，逻辑缝隙多 |

---

## 2. 过度设计清除（4 项）

| # | 问题 | 解决方案 | 状态 |
|---|------|---------|:----:|
| D1 | 通用证据外壳（`details` 嵌套） | 扁平化、领域特定字段 | ✅ |
| D2 | 顺序 ID 编号（`EVIDENCE-VT-{idx}`） | 用 `nodeid` / `source_path` 替代 | ❌ 未完成 |
| D3 | mtime 继承逻辑 | UPSERT 直接覆盖，不做时间戳比对 | ✅ |
| D4 | Claims 归档机制 | 删除 `_archive_claims`，Claims 转为累积式 | ✅ |

### D2 未完成详情

`evidence_id` 仍深度嵌入：

- `pipeline.py:434` — 生成 `EVIDENCE-VT-{idx+1:03d}`
- `ac_test_analyzer.py` — 读取 `ev["evidence_id"]`
- `claim_evidence_analyzer.py` — 按 `evidence_id` 建索引
- `requirement_task_analyzer.py` — 读取 `ev["evidence_id"]`
- `architecture_compliance_checker.py` — `_find_evidence_id()` 方法
- `risk_advisor.py` — 输出 `evidence_ids` 列表
- `infra/validation/ids.py` — 定义 `EVIDENCE-VT-\d+` 正则 + `make_evidence_id()`

**目标**：删除 pipeline.py 中的顺序编号，分析器直接查 DB 后用 `source_path`/`nodeid` 作为天然标识。见 `refactoring_design.md` 决策 1。

---

## 3. 核心设计原则

### 3.1 一任务一声明文件

| 项 | 说明 |
|----|------|
| 存储 | `.vibetracing/claims/CLAIM-{prefix}-{num}.json`，每个 Claim 一个文件 |
| 活跃识别 | `git diff --cached` + `git diff` + `git status --porcelain` 合并后匹配 `CLAIM-*.json` |
| pre-commit | 仅用 `git diff --cached` |
| 不再使用 | `current.json`（已删除）、`git show HEAD:claims.json`（已删除） |

**状态**：✅ 已实现

### 3.2 双层校验

| 层 | 执行时机 | 实现位置 | 策略 |
|----|---------|---------|------|
| 第一层：格式校验 | `RawInputLoader.load()` 之后，灌入 SQLite 之前 | `infra/validation/checks.py` → `validate_inputs()` | 不短路，全量收集 |
| 第二层：关系校验 | 数据灌入 SQLite 之后 | `infra/db/queries.py` → `check_*()` | LEFT JOIN 软校验，无硬 FK |

**设计决策**：
- db 的 `load_*` 函数仅做 INSERT（数据泵），不执行格式校验
- 格式校验统一收拢到 `validation/checks.py` 单一入口
- 关系校验用 LEFT JOIN 而非 FOREIGN KEY，避免第一个错误中断事务

**状态**：✅ 已实现（db validate_* 已全部删除，db.py 已拆为 `infra/db/` 子包）

### 3.3 各实体校验规范

#### Claims

| 层 | 校验内容 |
|----|---------|
| 格式 | `claim_id` 正则、`related_task` 正则、`code_refs`/`test_refs` 路径安全（无 `../`） |
| 关系 | `check_dangling_claims()` — Claim 指向的 Task 是否存在 |

#### Tasks

| 层 | 校验内容 |
|----|---------|
| 格式 | `task_id` 正则、`priority` 枚举、`status` 枚举、`ac_id` 正则 |
| 关系 | Task 关联的 AC 是否在 PRD 中定义（死链判定） |

#### Ghost Code（Gate 2）

| 层 | 校验内容 |
|----|---------|
| 格式 | 暂存文件路径格式 |
| 关系 | `check_ghost_code()` — staged 业务文件 LEFT JOIN claim_code_refs |

```sql
SELECT sf.file_path
FROM staged_files sf
LEFT JOIN claim_code_refs ccr ON sf.file_path = ccr.code_path
WHERE ccr.code_path IS NULL;
```

#### Test Results

| 层 | 校验内容 |
|----|---------|
| 格式 | `nodeid` 非空+格式、`outcome` 枚举、`exit_code` 非负整数 |
| 关系 | Claim 引用的测试是否在 test_results 中存在且通过 |

```sql
SELECT ctr.claim_id, ctr.test_nodeid
FROM claim_test_refs ctr
LEFT JOIN test_results tr ON ctr.test_nodeid = tr.nodeid
WHERE tr.nodeid IS NULL OR tr.outcome != 'passed';
```

#### Coverage Reports

| 层 | 校验内容 |
|----|---------|
| 格式 | `source_path` 合法相对路径、`percent_covered` 0-100、`status` 枚举 |
| 关系 | 活跃任务的修改文件是否有 coverage 且非 violated |

```sql
SELECT ccr.code_path, cr.percent_covered, cr.status
FROM claim_code_refs ccr
JOIN claims c ON ccr.claim_id = c.claim_id
JOIN tasks t ON c.related_task = t.task_id
LEFT JOIN coverage_reports cr ON ccr.code_path = cr.source_path
WHERE t.status = 'in_progress' AND (cr.source_path IS NULL OR cr.status = 'violated');
```

---

## 4. 门禁规则

| 规则 | 名称 | 判定逻辑 | 代码位置 |
|------|------|---------|---------|
| 幽灵代码检测 | 幽灵代码 | staged 文件 - claim_code_refs = 幽灵文件 | `domain/gate/claim_coverage.py` |
| GATE-VT-001 | 必需输入存在 | prd.md + constraints + task_list 存在 | `domain/architecture_compliance_checker.py` |
| GATE-VT-002 | Schema 校验 | JSON Schema 合规 | `infra/validation/schema_validator.py` |
| GATE-VT-003 | Must REQ 覆盖 | Must 需求有任务覆盖 | `analyzers/requirement_task_analyzer.py` |
| GATE-VT-004 | Must AC 覆盖 | Must AC 有测试覆盖 | `analyzers/ac_test_analyzer.py` |
| GATE-VT-005 | Claim 外部证据 | completed Claim 有外部证据 | `analyzers/claim_evidence_analyzer.py` |
| GATE-VT-006 | Must 架构合规 | 无 must 级 violated | `domain/architecture_compliance_checker.py` |

**重构后变化**：见 `refactoring_design.md` §3.2，Gate 1/1b/1c 删除，Gate 2 提前为前置条件，analyzers 删除（查询移入 db.check_*）。

---

## 5. 证据 JSON 结构

所有文件存放在 `output/evidences/`。

### test_results.json

```json
[{
  "nodeid": "tests/test_auth.py::test_login_success",
  "outcome": "passed",
  "exit_code": 0,
  "command": "pytest tests/test_auth.py..."
}]
```

### coverage_reports.json

```json
[{
  "source_path": "src/vibe_tracing/db.py",
  "percent_covered": 85.5,
  "num_statements": 42,
  "status": "compliant"
}]
```

### 单个 Claim 文件

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
