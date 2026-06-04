# VT 项目边界收敛设计方案

> 版本：v0.1 草案
> 日期：2026-06-03
> 状态：待确认

---

## 一、背景与问题

### 1.1 当前状态

VT 项目同时运行两套功能：

- **产出物审计（核心）**：检查 PRD、任务列表、Agent 声明、测试报告等文件是否齐全、格式正确、相互对得上。
- **工作过程管控（Claude Code Bootstrap）**：定义 Agent 内部角色分工、权限配置、行为约束。

### 1.2 存在的问题

**边界模糊**：VT 到底是"证据审计员"还是"Agent 管理员"？每次向外解释 VT 的定位时，都需要加一句"它还能管 Agent 配置"。

**虚假安全感**：Bootstrap 检查了 Agent 的权限配置（如 researcher 不能有写权限），但权限配置正确不等于证据可信。一个配置完全合规的 Agent，同样可以写出无意义的测试来声称"验收标准已覆盖"。

**证据链存在漏洞**：当前 VT 不自己执行测试工具（pytest、coverage 等），而是读取 Agent 放在 `.vibetracing/tool_reports/` 目录下的报告文件。Agent 可以生成伪造的报告文件蒙骗 VT。

**膨胀风险**：如果未来接入 Hermes、DeepSeek 等其他 Agent，每个都需要一套对应的 Bootstrap 配置，VT 会膨胀为一个"Agent 管理平台"。

---

## 二、核心原则

### 2.1 VT 是证据审计员，不是 Agent 管理员

VT 不关心 Agent 内部怎么分工、用什么工具、遵循什么流程。VT 只检查一件事：**产出物是否可信。**

### 2.2 VT 只信自己执行的结果

Agent 声称"测试通过了"不可信。Agent 提交一份报告文件也不可信。只有 VT 自己执行测试工具、自己捕获输出，才算可信证据。

### 2.3 config.json 是开发阶段的唯一配置来源

项目的语言、启用的工具、路径映射等信息，在开发阶段全部从 config.json 读取。config.json 由 `vt finalize` 从架构约束一次性写入，之后不再修改。

### 2.4 架构约束定义能力边界，config.json 声明实际使用

架构约束中的 `language_tool_matrix` 定义"Python 项目可以用哪些工具"。config.json 声明"这个项目实际启用了哪些工具"。`vt finalize` 时从架构约束读取，写入 config.json；`vt analyze` 时只读 config.json。

### 2.5 项目生命周期分为两个阶段

- **前期阶段**（init → Agent 生成架构约束和任务列表）：config.json 只有基础元数据。
- **开发阶段**（finalize → Agent 开发 → analyze 循环）：config.json 已定型，VT 只读不写。

---

## 三、方案设计

### 3.1 移除 Claude Code Bootstrap 模块

| 移除项 | 说明 |
|--------|------|
| `claude_code_bootstrap_adapter.py` | Bootstrap 适配器 |
| `claude_bootstrap_validator.py` | Bootstrap 校验器 |
| `claude_bootstrap_evidence_adapter.py` | Bootstrap 证据适配器 |
| `claude_bootstrap_manifest.schema.json` | Bootstrap 清单 Schema |
| `claude_subagent_definition.schema.json` | Subagent 定义 Schema |
| `claude_skill_definition.schema.json` | Skill 定义 Schema |
| `.vibetracing/claude_bootstrap/` 目录 | Bootstrap 配置文件 |
| 架构约束中 MOD-VT-011 定义 | Bootstrap 模块定义 |

### 3.2 引入语言工具矩阵

在 `architecture_constraints.json` 中新增顶层字段 `language_tool_matrix`，定义每种语言可用的验证工具。

**结构示意：**

```
language_tool_matrix
  └── python（语言名）
        ├── test（工具类别）
        │     ├── tool: "pytest"
        │     ├── default_command: "pytest {test_path} --tb=short -q ..."
        │     ├── output_format: "pytest_json"
        │     └── pass_condition: "exit_code == 0"
        ├── coverage（工具类别）
        │     ├── tool: "coverage"
        │     ├── default_command: "coverage run -m pytest {test_path} ..."
        │     ├── output_format: "coverage_json"
        │     └── pass_condition: "percent_covered >= 80"
        ├── lint（工具类别）
        │     ├── tool: "ruff"
        │     ...
        ├── type_check（工具类别）
        │     ├── tool: "mypy"
        │     ...
        └── security（工具类别）
              ├── tool: "bandit"
              ...
```

**设计要点：**

- 每种语言是一个顶层键，值是该语言的工具列表。
- 每个工具包含：工具名、默认命令模板、输出格式、通过条件。
- 命令模板中的 `{test_path}`、`{source_path}` 等占位符，由 VT 在执行时从 Claim 中提取并替换。
- 未来新增语言（如 JavaScript、Go），只需在这个矩阵中添加一个条目，不需要改代码。

### 3.3 扩展 config.json

在现有 config.json 中新增两个字段，由 `vt finalize` 写入：

| 字段 | 类型 | 说明 | 写入时机 |
|------|------|------|----------|
| `language` | 字符串 | 项目使用的编程语言，如 "python" | vt finalize 时从架构约束读取写入 |
| `validation_tools` | 字符串列表 | 该语言下启用的工具类别，如 `["test", "lint"]` | vt finalize 时从架构约束读取写入 |

**config.json 完整结构：**

init 后（前期阶段）：

```
config.json
  ├── project_name: "My Project"
  ├── project_prefix: "MP"
  ├── project_id: "PROJECT-MP"
  └── paths:
        ├── prd: "docs/prd.md"
        ├── task_list: "docs/task_list.json"
        └── ...
```

finalize 后（开发阶段）：

```
config.json
  ├── project_name: "My Project"
  ├── project_prefix: "MP"
  ├── project_id: "PROJECT-MP"
  ├── language: "python"                          ← finalize 写入
  ├── validation_tools: ["test", "lint"]           ← finalize 写入
  └── paths:
        ├── prd: "docs/prd.md"
        ├── task_list: "docs/task_list.json"
        └── ...
```

**`validation_tools` 的含义：**

- `["test"]`：只跑 pytest，验证测试是否通过。
- `["test", "coverage"]`：跑 pytest + coverage，同时验证测试通过和覆盖率。
- `["test", "lint", "security"]`：跑 pytest + ruff + bandit。
- 默认值由语言决定（如 python 默认 `["test", "lint"]`），用户可在 finalize 后手动编辑 config.json 调整。

### 3.4 init 流程（无变化）

init 流程不需要改动。保持现有行为：

```
vibe-tracing init --name "My Project" --prefix "MP"
  → 生成 config.json（基础元数据，不含 language）、模板文件、目录结构
```

init 只负责创建项目骨架，不涉及语言和工具配置。

### 3.5 finalize 流程（新增）

新增 `vibe-tracing finalize` 命令，在架构约束就绪后、开发开始前执行。

**触发时机：** Agent 完成 PRD 分析、架构约束生成、任务列表拆分后，由用户（或 Agent）执行一次。

**执行逻辑：**

```
vibe-tracing finalize
  1. 读取 config.json（已存在，init 时创建）
  2. 读取 docs/architecture_constraints.json
     → 提取 project.language
     → 提取 language_tool_matrix 中该语言的工具列表
  3. 校验：
     → 架构约束中必须有 project.language，否则 stderr 报错退出
     → language_tool_matrix 中必须有该语言的条目，否则 stderr 报错退出
  4. 向 config.json 写入 language 和 validation_tools
  5. 输出确认信息："Project finalized: language=python, tools=[test, lint]"
```

**finalize 是一次性命令：**

- 只在开发前执行一次。
- 如果 config.json 中已有 language 字段，finalize 检查是否与架构约束一致：
  - 一致 → 跳过，输出"Already finalized"
  - 不一致 → stderr 报错，要求用户手动处理（防止意外覆盖）
- finalize 不会在开发阶段被重复执行。

**stderr 反馈：**

| 场景 | stderr 输出 |
|------|------------|
| 架构约束文件不存在 | `Error: architecture_constraints.json not found. Agent must generate it before finalization.` |
| 架构约束中无 language | `Error: project.language not set in architecture_constraints.json.` |
| language_tool_matrix 中无对应语言 | `Error: language "xxx" not found in language_tool_matrix.` |
| 已 finalize 但 language 不一致 | `Error: config.json language "python" conflicts with architecture_constraints language "go". Manual intervention required.` |

### 3.6 analyze 流程变化

**现有流程：**

```
1. 读取 PRD、任务列表、架构约束、Agent Claims
2. 解析验证
3. 生成证据索引
4. 生成追踪报告
5. 门禁判定
```

**更新后流程：**

```
1. 读取 config.json → 获取 language、validation_tools
   → 如果 config.json 中无 language 字段，stderr 报错："Project not finalized. Run 'vibe-tracing finalize' first."
2. 读取架构约束 → 获取 language_tool_matrix 中该语言的工具命令模板
3. 读取 PRD、任务列表、Agent Claims（现有逻辑）
4. 解析验证（现有逻辑）
5. 【新增】执行验证阶段：
   a. 遍历每个 Claim
   b. 找到 Claim 关联的测试路径（从 Claim 的 evidence_refs 或关联任务中获取）
   c. 根据 validation_tools 列表，逐个工具执行：
      - 从 language_tool_matrix 取命令模板
      - 替换占位符（{test_path}、{source_path} 等）
      - 执行命令，捕获 stdout/stderr
      - 解析输出，生成证据条目
   d. 如果命令执行失败（工具不存在、路径错误等），通过 stderr 输出错误信息
6. 【新增】非代码类 Claim 验证：
   a. 检查 Claim 关联的产出物文件是否存在
   b. 检查是否有下游代码 Claim 的证据链
7. 汇总所有证据，生成证据索引（现有逻辑）
8. 生成追踪报告（现有逻辑）
9. 门禁判定（现有逻辑，新增：无工具证据的 Claim → low_confidence）
```

注意：analyze 不写入 config.json，只读取。config.json 的写入只发生在 init 和 finalize。

### 3.7 证据来源标记

每个证据条目记录其来源可信度：

| 证据来源 | source_type | 可信度 | 说明 |
|----------|-------------|--------|------|
| VT 执行 pytest 的结果 | "test" | 高 | VT 自己执行、自己捕获 |
| VT 执行 coverage/ruff/mypy/bandit 的结果 | "tool" | 高 | VT 自己执行、自己捕获 |
| Agent 在 Claim 中声明的 code_ref | "code" | 中 | 文件存在可验证，但内容未验证 |
| Agent 自行报告的状态 | "claim" | 低 | 未经工具验证 |
| 任务状态 | "task" | 参考 | 来自 task_list.json，非独立验证 |

### 3.8 Claim 可信度判定

| 场景 | 可信度 | 门禁行为 |
|------|--------|----------|
| Claim 有 VT 执行的测试证据，且测试通过 | 高 | 可以进入通过判定 |
| Claim 有 VT 执行的测试证据，但测试失败 | 不通过 | 直接阻塞 |
| Claim 只有 code_ref 证据，无工具执行结果 | 中 | 需要人工确认 |
| Claim 无任何外部证据 | 低 | 标记为 low_confidence，阻塞 |
| Claim 关联了非代码任务，产出物文件存在且格式正确 | 中 | 可以进入通过判定 |
| Claim 关联了非代码任务，且有下游代码 Claim 的工具证据链 | 高 | 可以进入通过判定 |

### 3.9 非代码类 Claim 的处理（A + B 方案）

**A：产出物文件检查**

VT 检查 Claim 关联的产出物文件（如 PRD 分析报告、架构约束草稿）是否存在且格式正确。

**B：下游证据链检查**

如果一个非代码 Claim（如"完成了 PRD 分析"）产生了下游代码 Claim（如"实现了 PRD 中定义的功能"），且下游 Claim 有工具执行的证据，那么上游 Claim 可以获得间接验证。

**示例：**

```
Claim-1："完成了 PRD 分析"（非代码）
  → 产出物文件 docs/prd.md 存在且可解析 ✅
  → 下游 Claim-2 有 pytest 证据 ✅
  → Claim-1 可信度：高

Claim-3："完成了架构约束草稿"（非代码）
  → 产出物文件 docs/architecture_constraints.json 存在且 Schema 校验通过 ✅
  → 无下游代码 Claim
  → Claim-3 可信度：中（需人工确认）
```

### 3.10 安全机制

VT 执行 Agent 提交的命令存在安全风险。通过以下机制保证安全：

| 机制 | 说明 |
|------|------|
| **白名单工具** | 只能执行 language_tool_matrix 中定义的工具，不能执行任意命令 |
| **命令模板** | VT 只替换占位符，不接受 Agent 提供的完整命令字符串 |
| **路径校验** | 占位符的值（如测试路径）必须在项目目录内，不允许 `../` 等路径穿越 |
| **禁止管道** | 命令模板中不允许 `&&`、`\|`、`;`、`$()` 等 shell 特殊字符 |
| **超时控制** | 每个工具执行有默认超时（如 120 秒），超时则终止并记录为 blocked |

### 3.11 stderr 反馈机制

VT 在执行验证阶段遇到问题时，通过 stderr 输出精确的错误信息，引导 Agent 修正：

| 场景 | stderr 输出示例 |
|------|-----------------|
| 工具未安装 | `Error: pytest not found. Install with: pip install pytest` |
| 测试路径不存在 | `Error: tests/test_feature_a.py not found. Check the path in Claim TASK-VT-001.` |
| 测试执行超时 | `Error: pytest exceeded 120s timeout for tests/test_slow.py.` |
| 测试全部失败 | `Warning: 3/3 tests failed for AC-VT-001-01. See output/evidence_index.json for details.` |
| 配置缺失 | `Error: config.json missing 'language' field. Run 'vibe-tracing init' to regenerate.` |

---

## 四、受影响的文件清单

### 4.1 新增

| 文件 | 说明 |
|------|------|
| `output/VT_boundary_convergence_design.md` | 本设计文档 |

### 4.2 修改

| 文件 | 改动内容 |
|------|----------|
| `src/vibe_tracing/templates/config.template.json` | 新增 language、validation_tools 字段 |
| `docs/architecture_constraints.json` | 新增 language_tool_matrix 顶层字段，移除 MOD-VT-011 |
| `.vibetracing/architecture_constraints.base.json` | 同上 |
| `src/vibe_tracing/schemas/evidence_index.schema.json` | 可能需要调整 source_type 枚举（确认现有值是否足够） |
| `src/vibe_tracing/tool_evidence_adapter.py` | 从"读取已有报告"改为"执行命令并解析输出" |
| `src/vibe_tracing/evidence_index_builder.py` | 移除 tool_reports 目录读取，改为调用 adapter 执行 |
| `src/vibe_tracing/raw_input_loader.py` | 移除 tool_reports 文件键，新增 config.json 中 validation_tools 的读取 |
| `src/vibe_tracing/cli.py` | 新增 finalize 命令，analyze 新增执行验证阶段 |
| `src/vibe_tracing/claim_loader.py` | 新增：无工具证据的 Claim 标记为 low_confidence |
| `src/vibe_tracing/risk_advisor.py` | 新增风险类型：Claim 无工具验证证据 |
| `docs/prd.md` | 更新相关需求和验收标准描述 |
| `docs/task_list.json` | 更新相关任务描述 |

### 4.3 移除

| 文件 | 说明 |
|------|------|
| `src/vibe_tracing/claude_code_bootstrap_adapter.py` | Bootstrap 适配器 |
| `src/vibe_tracing/claude_bootstrap_validator.py` | Bootstrap 校验器 |
| `src/vibe_tracing/claude_bootstrap_evidence_adapter.py` | Bootstrap 证据适配器 |
| `src/vibe_tracing/schemas/claude_bootstrap_manifest.schema.json` | Bootstrap 清单 Schema |
| `src/vibe_tracing/schemas/claude_subagent_definition.schema.json` | Subagent 定义 Schema |
| `src/vibe_tracing/schemas/claude_skill_definition.schema.json` | Skill 定义 Schema |
| `.vibetracing/claude_bootstrap/` 目录 | Bootstrap 配置文件及 README |
| `.vibetracing/tool_reports/` 目录 | 不再需要，工具报告由 VT 内部生成 |

---

## 五、已确认的设计决策

### 5.1 语言参数的处理方式

**结论：init 不需要 `--language` 参数，新增 `vt finalize` 命令。**

理由：按照 VT 的工作流，init 时项目大概率只有一个不完整的 PRD。语言由 Agent 在生成架构约束时确定。`vt finalize` 在架构约束就绪后执行，读取语言和工具配置写入 config.json。此后 config.json 不再被修改，作为开发阶段的唯一配置来源。

### 5.2 非代码类 Claim 的处理方式

**结论：采用 A + B 组合方案。**

- A：检查产出物文件是否存在且格式正确。
- B：检查是否有下游代码 Claim 的工具证据链。

这样既不要求人类介入，也不会放过"只写了个空文件就声称完成"的情况。

### 5.3 数据流转设计

**结论：init 不变，新增 finalize，analyze 只读不写。**

完整的数据流：

```
vt init → config.json（基础元数据）、模板文件、目录结构
Agent → architecture_constraints.json（含 language、language_tool_matrix）
Agent → task_list.json
vt finalize → 从架构约束读取 language/validation_tools，写入 config.json
Agent 开发 → 写代码、写测试
vt analyze → 读 config.json + 架构约束 → 执行工具 → 生成报告
Agent 修正 → vt analyze（循环）
```

- config.json 的写入只发生在 init 和 finalize，analyze 只读不写。
- 架构约束由 Agent 生成，finalize 一次性同步到 config.json。
- 每条数据只有一个来源，没有环路。

## 六、已解决的细化问题

以下问题在实现阶段已全部解决：

1. **language 字段 Schema 定义** ✅：`project.language` 已作为可选 string 字段加入 `architecture_constraints.schema.json`。
2. **language_tool_matrix Schema 定义** ✅：已作为顶层属性加入 Schema，使用 `additionalProperties` 两级结构支持多语言多工具。
3. **工具执行超时默认值** ✅：统一设为 120 秒（`DEFAULT_TIMEOUT`）。超时时通过 stderr 显式输出 `"Error: {path} timed out after 120s. Increase timeout or simplify the test."`。
4. **validation_tools 默认值** ✅：finalize 从 `language_tool_matrix[language].keys()` 取全部工具类别作为默认值。python 下为 `["test", "coverage", "lint", "type_check", "security"]`。用户可在 finalize 后手动编辑 config.json 精简。
