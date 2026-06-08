# VT 自我进化与演进计划

## 一、 概述 (Overview)

本轮反思从"我是 VT 的用户"视角出发，识别出 VT 最大的结构性问题：**工具执行产生大量假失败证据，污染风险评估和门禁决策，导致 Agent 被迫使用 `--no-verify` 绕过 hook——而每一次绕过都在削弱人类验收所需的数据链条。** 核心目标：**让 VT 的完整流程快到不需要绕过，让证据链干净到人类可以无摩擦地验收。**

---

## 二、 诊断与反思 (Diagnostics & Reflections)

- **Reflect ID**: EVO-REF-018
  - **Violation Principle**: 1 (项目不足识别)
  - **Diagnosis**: `_execute_tools` 对 claims 中的所有路径运行所有工具，不区分文件类型。pytest 对源文件运行必然 exit 5（no tests collected），被记录为"工具执行失败"证据，触发 must-severity risk，导致 BLOCKED。这不是真实的质量风险，而是工具配置错误。
  - **Root Cause**: 工具执行引擎没有"工具-文件类型"匹配机制。所有工具对所有路径一视同仁。
  - **Affected Scope**: `src/vibe_tracing/cli.py` (`_execute_tools`), `src/vibe_tracing/tool_evidence_adapter.py`

- **Reflect ID**: EVO-REF-019
  - **Violation Principle**: 4 (计算与逻辑冗余)
  - **Diagnosis**: 工具执行对未变更的文件重复运行。如果 claims 中有 50 个文件但本次只变更了 2 个，工具仍然对全部 50 个文件执行。这是纯浪费。
  - **Root Cause**: 工具执行没有"增量"概念，每次运行都是全量。
  - **Affected Scope**: `src/vibe_tracing/cli.py` (`_execute_tools`)

- **Reflect ID**: EVO-REF-020
  - **Violation Principle**: 5 (凭证真实性)
  - **Diagnosis**: evidence_index.json 中包含大量"假失败"证据（pytest exit 5, mypy exit 2 on non-code files）。这些噪音证据污染风险评估，误导门禁决策，增加人类验收的认知负担。
  - **Root Cause**: 工具执行引擎不解析工具的 exit code 和输出，无法区分"真实失败"和"工具无法处理该文件"。
  - **Affected Scope**: `src/vibe_tracing/tool_evidence_adapter.py`, `src/vibe_tracing/evidence_index_builder.py`

- **Reflect ID**: EVO-REF-021
  - **Violation Principle**: 7 (豁免与绕过机制)
  - **Diagnosis**: `--no-verify` 和 `--gates-only` 是对证据链的直接削弱。Agent 使用它们绕过 hook，导致 evidence_index 缺失数据，人类无法完整验收。VT 不应该有任何绕过机制——正确方向是让完整流程快到不需要绕过。
  - **Root Cause**: VT 的完整流程（工具执行 + 分析 + 产物生成）太慢，Agent 被迫寻找捷径。
  - **Affected Scope**: `src/vibe_tracing/cli.py` (CLI 参数), 整体架构

- **Reflect ID**: EVO-REF-022
  - **Violation Principle**: 1 (项目不足识别)
  - **Diagnosis**: Semantic Audit 仅对 quality_evolution task 触发。功能性 task 的代码变更没有语义校验——Agent 可以随意修改功能性代码，只要 claim 存在就通过。这削弱了证据链的语义质量。
  - **Root Cause**: 审计范围设计过于保守，只覆盖了"质量演进"这一类变更。
  - **Affected Scope**: `src/vibe_tracing/semantic_auditor.py`

- **Reflect ID**: EVO-REF-023
  - **Violation Principle**: 2 (架构精简度评估)
  - **Diagnosis**: run_metadata.json 记录的运行时间、版本号等元数据可以内嵌到 traceability_report.json 中，不需要独立文件。减少产物数量降低 Agent 的认知负担和人类的验收成本。
  - **Root Cause**: 产物设计时未考虑精简，每个功能各自生成独立文件。
  - **Affected Scope**: `src/vibe_tracing/cli.py` (`_evaluate_and_output`)

---

## 三、 原子化动作指令 (Atomic Action Tasks)

### 工具执行：文件类型匹配

- [ ] **Task ID**: EVO-TASK-015a
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/tool_evidence_adapter.py`
  - **Instruction**: 在 `ToolExecutionEngine` 中新增 `TOOL_FILE_TYPE_MAP` 类属性，定义每个工具类别能处理的文件类型：`{"test": {".py"}, "lint": {".py"}, "type_check": {".py"}, "security": {".py"}, "coverage": {".py"}}`。在 `execute_all()` 中，对每个 path 只运行文件扩展名匹配的工具类别。
  - **AC**: `python3 -m pytest tests/test_tool_execution.py -v` 全部通过。对 `.md` 文件不运行任何工具。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-015b
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 在 `_execute_tools` 中区分 `test_paths` 和 `source_paths`：从 `test_refs` 收集的路径标记为 test 类型，从 `code_refs` 收集的路径标记为 source 类型。传递给 `engine.execute_all()` 时附带类型信息，使 pytest 只运行 test_paths，ruff/mypy 只运行 source_paths。
  - **AC**: `python3 -m pytest tests/test_tool_execution.py tests/test_cli_analyze.py -v` 全部通过。pytest 不再对 source 文件运行。
  - **Subagent**: self

### 工具执行：增量执行

- [ ] **Task ID**: EVO-TASK-016
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 在 `_execute_tools` 中，将 `execution_paths` 过滤为仅包含本次 staged 变更的文件。使用 `git diff --cached --name-only` 获取 staged 文件列表，与 execution_paths 取交集。未变更的文件不执行工具。
  - **AC**: `python3 -m pytest tests/test_cli_analyze.py -v` 全部通过。只有 staged 变更的文件被工具执行。
  - **Subagent**: self

### 工具执行：exit code 解析

- [ ] **Task ID**: EVO-TASK-017
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/tool_evidence_adapter.py`
  - **Instruction**: 在各工具的解析方法中（`_parse_pytest_output`, `_parse_mypy_output` 等），区分"真实失败"和"工具无法处理"。具体规则：
    - pytest exit 5（no tests collected）→ 不记录为证据，跳过
    - mypy exit 2（usage error）→ 不记录为证据，跳过
    - ruff exit 1（violations found）→ 记录为证据
    - pytest exit 1（test failure）→ 记录为证据
  - **AC**: `python3 -m pytest tests/test_tool_execution.py -v` 全部通过。evidence_index 中无 exit 5/exit 2 usage error 条目。
  - **Subagent**: self

### Semantic Audit 扩大范围

- [ ] **Task ID**: EVO-TASK-018
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/semantic_auditor.py`
  - **Instruction**: 修改 `generate_tickets()` 的触发条件：不再仅限 `quality_evolution` task，而是所有 task 的代码变更都触发审计。但审计标准分级：quality_evolution 的 audit_reason 需要 ≥50 字符且包含变更动机；functional 的 audit_reason 需要 ≥20 字符且包含文件名。在 ticket 中新增 `audit_level` 字段（`"standard"` 或 `"detailed"`）。
  - **AC**: `python3 -m pytest tests/test_semantic_auditor.py -v` 全部通过。functional task 的代码变更也生成审计单。
  - **Subagent**: self

### 产物精简

- [ ] **Task ID**: EVO-TASK-019
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 将 `run_metadata.json` 的内容合并到 `traceability_report.json` 中，作为 `metadata` section。删除独立的 `run_metadata.json` 生成逻辑。
  - **AC**: `vt analyze` 不再生成 `run_metadata.json`。`traceability_report.json` 包含 `metadata` section。
  - **Subagent**: self

### 分析阶段增量优化

- [ ] **Task ID**: EVO-TASK-020
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 在 `_run_analyzers` 中，传递 staged 文件列表给各 analyzer。各 analyzer 只对变更文件相关的 claim/task/requirement 进行分析，未变更的部分复用已有结果（从上一次 traceability_report.json 读取）。
  - **AC**: `python3 -m pytest tests/test_cli_analyze.py tests/test_e2e_finalize_analyze.py -v` 全部通过。分析时间与变更文件数量正相关，而非全量文件。
  - **Subagent**: self
