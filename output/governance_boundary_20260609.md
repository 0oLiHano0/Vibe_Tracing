# VT 治理边界定义

**日期**: 2026-06-09
**状态**: ✅ 已实施
**关联**: EVO-REF-004 (治理覆盖盲区)

---

## 一、问题重新定义

此前将"63 个文件未被 Task/AC 覆盖"视为治理缺陷。经分析，这是**正确的设计**，不是缺陷。

VT 治理的对象是"业务需求是否被正确实现"。辅助文件不在治理边界内。

---

## 二、治理边界定义

### 应被 VT 治理的文件

| 类型 | 示例 | 治理方式 |
|---|---|---|
| 业务逻辑代码 | `src/vibe_tracing/*.py` | Claim + Task + AC |
| 测试代码 | `tests/test_*.py` | Claim test_refs + covers docstring |
| 需求文档 | `docs/prd.md` | PRD 哈希保护 + 漂移检测 |
| 架构约束 | `docs/architecture_constraints.json` | 哈希保护 + 映射校验 |
| 任务列表 | `docs/task_list.json` | Schema 校验 + 关联校验 |

### 不应被 VT 治理的文件

| 类型 | 示例 | 正确的保障方式 |
|---|---|---|
| Schema 定义 | `schemas/*.json` | 单元测试 + CI |
| 输出模板 | `templates/*.html`, `templates/*.json` | 单元测试 + CI |
| 测试固件 | `tests/fixtures/**` | 测试自身 |
| 运行时配置 | `.vibetracing/config.json` | Schema 校验 |
| 生成产物 | `output/*.html`, `output/*.json` | 重新生成 |
| 决策日志 | `.vibetracing/human_decisions.json` | 运行时写入 |
| 语义审计 | `.vibetracing/semantic_audit.json` | 运行时写入 |
| 项目配置 | `pyproject.toml`, `.gitignore` | 标准工具链 |
| 文档 | `docs/architecture_change_log.md` | 人工审查 |
| 调研报告 | `output/*.md` | 人工审查 |

---

## 三、解决方案

### 3.1 在 VT 配置中声明治理边界

在 `docs/architecture_constraints.json` 中新增 `governance_boundary` 配置：

```json
{
  "governance_boundary": {
    "included_patterns": [
      "src/vibe_tracing/**/*.py",
      "tests/test_*.py",
      "docs/prd.md",
      "docs/architecture_constraints.json",
      "docs/task_list.json"
    ],
    "excluded_patterns": [
      "schemas/**",
      "templates/**",
      "tests/fixtures/**",
      "output/**",
      ".vibetracing/**",
      "*.md",
      "*.toml",
      "*.json",
      "*.html"
    ],
    "excluded_note": "辅助文件由标准软件工程实践保障（单元测试、CI、schema 校验），不纳入 VT claim/task/AC 治理体系。"
  }
}
```

### 3.2 Gate 2 使用治理边界过滤

修改 `ghost_code_reconciler.py`（或 Gate 2 的检查逻辑），在检测幽灵代码时，先用 `governance_boundary` 过滤 staged 文件。排除在边界外的文件不触发幽灵代码警告。

### 3.3 Dashboard 治理覆盖统计

在 Dashboard 的 Overview 标签页，区分"治理范围内文件"和"治理范围外文件"的统计：

```
治理覆盖：15/18 文件（83%）
范围外：45 个辅助文件（不纳入治理）
```

### 3.4 vt analyze 输出

在 Agent 行动清单的 SUMMARY 中，不再报告"63 个文件未覆盖"，而是：

```
治理范围：18 个文件（业务代码 + 测试 + 契约文件）
范围外：45 个辅助文件（不纳入治理）
覆盖率：15/18 (83%)
```

---

## 四、原子化任务

- [x] **Task ID**: GOV-TASK-001
  - **Action**: MODIFY
  - **Target File**: `docs/architecture_constraints.json`
  - **Instruction**: 新增 `governance_boundary` 配置节，声明 `included_patterns` 和 `excluded_patterns`。`included_patterns` 包含业务代码、测试、契约文件。`excluded_patterns` 包含 schemas、templates、fixtures、output、.vibetracing、非代码文件。
  - **AC**: `vt finalize` 通过，`governance_boundary` 字段存在于 constraints 中
  - **前置依赖**: 无

- [x] **Task ID**: GOV-TASK-002
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/ghost_code_reconciler.py`
  - **Instruction**: 在幽灵代码检测逻辑中，读取 `governance_boundary.excluded_patterns`，对 staged 文件进行过滤。匹配 excluded_patterns 的文件不触发幽灵代码警告。
  - **AC**: staging `.md` 或 `.json` 文件不触发"未经报备的幽灵代码"警告
  - **前置依赖**: GOV-TASK-001

- [x] **Task ID**: GOV-TASK-003
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 在 `vt analyze` 输出中，区分治理范围内和范围外文件。Agent 行动清单的 SUMMARY 显示"治理范围：X 个文件，范围外：Y 个辅助文件"。移除"63 个文件未覆盖"的治理覆盖警告。
  - **AC**: `vt analyze` 输出不再报告辅助文件的覆盖缺口
  - **前置依赖**: GOV-TASK-001

- [x] **Task ID**: GOV-TASK-004
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/templates/dashboard.template.html`
  - **Instruction**: 在 Overview 标签页的治理覆盖统计中，区分"治理范围内"和"范围外"文件。显示"治理覆盖：X/Y (Z%)"和"范围外：N 个辅助文件"。
  - **AC**: Dashboard Overview 显示治理边界统计
  - **前置依赖**: GOV-TASK-001

- [x] **Task ID**: GOV-TASK-005
  - **Action**: MODIFY
  - **Target File**: `docs/prd.md`
  - **Instruction**: 在 PRD 中新增治理边界的定义，明确 VT 的治理范围和排除范围。作为 AC-VT-009-04（配置驱动）的补充说明。
  - **AC**: PRD 中包含治理边界的明确定义
  - **前置依赖**: 无

---

## 五、与 Claim 自动失效机制的关系

治理边界定义和 Claim 自动失效是两个独立的问题：

- **治理边界**：定义"VT 管什么"——排除辅助文件，减少噪音
- **Claim 自动失效**：定义"Claim 何时失效"——引用文件变化时标记 needs_reverification

两者互补：治理边界减少了需要管理的文件数量，Claim 自动失效确保剩余文件的 claim 保持有效。

---

## 六、预期效果

实施后：
- `git add .md .json` 不再触发幽灵代码警告
- `vt analyze` 不再报告辅助文件的覆盖缺口
- Dashboard 清晰区分治理范围内/外的文件
- Agent 行动清单只关注业务代码的问题
- 人类在 Dashboard 上看到的统计更准确（83% 覆盖率 vs 之前的"63 个文件未覆盖"）
