# 模板全面复核与对齐计划 (Template Format Review & Alignment)

根据您的反馈，随着后续功能的演进（例如加入 `vt finalize` 的自动锁定机制，以及 `language_tool_matrix` 的扩展），`src/vibe_tracing/templates/` 目录下的初始模板文件确实已经落后于当前 Schema 与实际使用逻辑。

这会导致 AI Agent 在项目初始化后无法看到完整的字段骨架，进而迷失方向。我已结合最新的 Schema 对这些模板进行了逐回复核，以下是需要更新的核心项及计划。

## User Review Required
> [!IMPORTANT]
> 此计划将全量更新初始化模板，这些修改不会影响您当前正在开发的项目数据，但会决定后续所有新项目或 AI Agent 运行 `vt init` 时的初始上下文格式。请确认下方的修改方向是否符合期望。

## Proposed Changes

### 1. [MODIFY] `src/vibe_tracing/templates/config.template.json`
**当前问题**：缺少由 `vt finalize` 命令回写的状态字段。虽然这些字段在运行时会被填充，但提供空占位符可以极大地帮助 AI 理解配置文件的生命周期。
**修改计划**：增加 `language`, `validation_tools`, `architecture_constraints_hash`, `finalize_git_commit` 等字段的初始占位符。

```json
{
  "project_id": "PROJECT-{{PROJECT_PREFIX}}",
  "project_prefix": "{{PROJECT_PREFIX}}",
  "project_name": "{{PROJECT_NAME}}",
  "language": "",
  "validation_tools": [],
  "architecture_constraints_hash": "",
  "finalize_git_commit": "",
  "finalize_constraints_path": "",
  "paths": { ... }
}
```

### 2. [MODIFY] `src/vibe_tracing/templates/architecture_constraints.template.json`
**当前问题**：缺少 `project.language` 和核心的 `language_tool_matrix` 字典。这会导致 `vt finalize` 失败，同时也让 Agent 失去编写门禁工具命令的参考。
**修改计划**：补充 `language` 字段（默认为 python），并增加 `language_tool_matrix` 以及包含 `test`, `coverage`, `lint` 等示例。

```json
  "project": {
    "project_id": "PROJECT-{{PROJECT_PREFIX}}",
    ...
    "language": "python"
  },
  "language_tool_matrix": {
    "python": {
      "test": {
        "tool": "pytest",
        "default_command": "pytest {test_path} --tb=short -q --json-report --json-report-file={output_path}",
        "output_format": "pytest_json",
        "pass_condition": "exit_code == 0"
      },
      ...
    }
  },
```

### 3. [MODIFY] `src/vibe_tracing/templates/task_list.template.json`
**当前问题**：根据最新的 `task_list.schema.json`，任务列表还包含全局 ID 格式约束 (`id_rules`) 和研发阶段切分 (`phases`)，但模板中只有空荡荡的 `tasks` 数组。
**修改计划**：补充这几个外围结构的空骨架，帮助 Agent 在拆解任务时能先定义出全局的阶段和 ID 规范。

```json
{
  "schema_version": "1.0.0",
  "project": { ... },
  "id_rules": {
    "task_id_format": "TASK-{{PROJECT_PREFIX}}-\\d{3}",
    "dod_id_format": "DOD-{{PROJECT_PREFIX}}-\\d{3}-\\d{2}"
  },
  "phases": [],
  "tasks": []
}
```

### 4. 保持不变的文件
- `agent_claims.template.json`：当前为 `[]`。因为 JSON 不支持注释，放置规范的空数组即可。
- `prd.template.md` 与 `prd_analysis.template.md`：经交叉对比验证，内容结构完整，当前暂无需改动。

## Verification Plan
1. 修改模板文件。
2. 运行 `vibe-tracing init --name "Test Project" --prefix "TEST"` 到一个测试空目录。
3. 检查生成的 `config.json`, `architecture_constraints.json`, `task_list.json` 是否包含了所有上述补充的字段且格式正确。
4. 运行现有的测试集 `pytest tests/` 确保模板结构的更新没有引发预料之外的 Schema 解析错误。

---

## 独立审查结果 (Independent Review)

> 由架构师独立核实，逐项交叉验证 Schema、实际代码和报告声明。

### 逐项核实

#### Claim 1: config.template.json 缺少 finalize 回写字段 — **准确**

| 字段 | 模板中 | 实际 config.json 中 | Schema 要求 |
|---|---|---|---|
| `language` | 缺失 | `run_finalize()` 写入 | 无 Schema |
| `validation_tools` | 缺失 | `run_finalize()` 写入 | 无 Schema |
| `architecture_constraints_hash` | 缺失 | `run_finalize()` 写入 | 无 Schema |
| `finalize_git_commit` | 缺失 | `run_finalize()` 写入 | 无 Schema |

`config.json` 无对应 Schema 文件，这些字段由 `run_finalize()` 动态注入。加入空占位符可帮助 AI 理解配置生命周期，**不影响功能**。

#### Claim 2: architecture_constraints.template.json 缺少 language_tool_matrix — **准确，但方案需修正**

**问题确认**：模板缺少 `project.language`，`vt finalize` 会因此报错（`cli.py:233` 显式检查 `if not language: return 1`）。

**方案修正**：报告建议将完整 `language_tool_matrix`（含 pytest、coverage 等命令模板）写入模板。此方案存在两个问题：

1. **违反 PRINCIPLE-VT-008**（核心语言无关）：模板不应将 Python 工具硬编码为默认值。`language_tool_matrix` 应由 Agent 根据项目实际语言按需生成。
2. **渲染冲突风险**：`run_init()` 的 `render_template()` 执行 `content.replace("-VT-", f"-{config_prefix}-")`，若模板中包含 `PROJECT-VT` 引用会被错误替换。

**建议**：仅在模板的 `project` 对象中补充 `"language": "python"`（MVP 默认值），`language_tool_matrix` 保留在实际文件中由 Agent 按需生成。

#### Claim 3: task_list.template.json 缺少 id_rules 和 phases — **准确，id_rules 格式设计合理**

**Schema 核实**：
- `id_rules` 和 `phases` 均为可选字段（非 `required`），但 `tasks` 数组中的 `task_id` 有 pattern 约束：`^TASK-[a-zA-Z0-9_-]+-\\d+$`，`phase_id` 有 pattern：`^PHASE-[a-zA-Z0-9_-]+-\\d+$`
- `id_rules.task_id_format` 和 `dod_id_format` 的 Schema 定义为 `type: string`，无 pattern 约束，是**自由文本描述字段**

**id_rules 格式辨析**：

报告建议：`"task_id_format": "TASK-{{PROJECT_PREFIX}}-\\d{3}"`
VT 项目实例：`"task_id_format": "TASK-VT-序号"`

两者差异在于**描述风格**，非逻辑错误：
- VT 项目用中文自然语言 `"序号"` 描述格式
- 报告建议用正则语法 `"\\d{3}"` 描述格式

由于 `id_rules.task_id_format` 是自由文本、无 Schema 校验，两种风格均合法。但报告方案使用 `{{PROJECT_PREFIX}}` 占位符的设计是正确的——确保新项目的 ID 规则自动适配各自 prefix（如 `TASK-CAPL-001`、`TASK-TEST-001`），而非硬编码 `VT`。

**结论**：报告的占位符设计方向正确。格式风格（正则 vs 自然语言）属于实现细节，不影响模板功能。

#### Claim 4: agent_claims / prd 模板无需改动 — **准确**

- `agent_claims.template.json` 为 `[]`，符合 Schema（`type: array`）
- PRD 模板结构完整，无需调整

### 总体评估

| 维度 | 评价 |
|---|---|
| 问题诊断 | **准确**，模板确实落后于实际使用逻辑 |
| 修复方向 | **基本正确**，但 `language_tool_matrix` 入模板需降级为仅补充 `project.language` |
| id_rules 格式 | **合理**，`{{PROJECT_PREFIX}}` 占位符设计正确，格式风格为实现细节 |
| 风险 | **低**，模板变更只影响 `vt init` 新项目，不影响现有数据 |

### 修正后的实施建议

| 文件 | 报告方案 | 审查修正 |
|---|---|---|
| `config.template.json` | 补充 finalize 占位字段 | **同意**，直接执行 |
| `architecture_constraints.template.json` | 补充完整 `language_tool_matrix` | **降级**：仅补充 `project.language: "python"`，`language_tool_matrix` 不入模板 |
| `task_list.template.json` | 补充 `id_rules` + `phases` | **同意**，id_rules 使用 `{{PROJECT_PREFIX}}` 占位符 |
| `agent_claims.template.json` | 保持不变 | **同意** |
| `prd.template.md` / `prd_analysis.template.md` | 保持不变 | **同意** |
