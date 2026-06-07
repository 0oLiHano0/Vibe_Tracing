# VT 治理盲区修复计划

## 一、 概述 (Overview)

VT 的治理模型为"需求驱动的功能开发"设计，缺少对"质量驱动的架构演进"的治理路径。本轮修复两项结构性缺陷：(1) PRD 无质量演进 REQ 类别，导致重构任务被迫挂载到语义不匹配的 AC 上；(2) 反思诊断的 Affected Scope 未校验 REQ 覆盖，导致治理盲区不可见。两项修复均为纯规则实现，不引入 LLM。

**设计原则：零向后兼容。** VT 处于开发期，无历史兼容债务。一切以当前最佳实现为目标，不保留陈旧逻辑或接口。

---

## 二、 诊断与反思 (Diagnostics & Reflections)

- **Reflect ID**: GOV-FIX-001
  - **Violation Principle**: 1 (项目不足识别) + 5 (凭证真实性)
  - **Diagnosis**: PRD 中 REQ 无类别字段，所有 REQ 均为隐式"功能性"。EVO 任务（死代码清理、函数拆分、模板化）被迫挂载到 AC-VT-009-12（"单次加载输入文件"）等语义不匹配的 AC 上，治理链接名存实亡。
  - **Root Cause**: PRD 模板设计时未考虑非功能性需求类别。PrdParser 仅提取 req_id/title/priority/AC，无 category 字段。
  - **Affected Scope**: `src/vibe_tracing/templates/prd.template.md`, `src/vibe_tracing/prd_parser.py`, `docs/prd.md`

- **Reflect ID**: GOV-FIX-002
  - **Violation Principle**: 1 (项目不足识别) + 7 (豁免与绕过机制)
  - **Diagnosis**: 反思诊断输出的 Affected Scope（文件路径）未与 task_list.json 的 code_refs 做覆盖校验。当反思发现某文件存在缺陷但该文件未被任何 Task/AC 覆盖时，VT 无告警，治理盲区不可见。
  - **Root Cause**: `render_reflection_prompts()` 仅接收 gate_decision/gaps/risks/compliance_result，不接收 task_list 数据，无法做覆盖校验。
  - **Affected Scope**: `src/vibe_tracing/reflection_prompts.py`, `src/vibe_tracing/cli.py`, `src/vibe_tracing/templates/reflection_prompts.template.json`

---

## 三、 原子化动作指令 (Atomic Action Tasks)

- [ ] **Task ID**: GOV-TASK-001
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/templates/prd.template.md`
  - **Instruction**: 在每个 REQ 示例块中，`#### 优先级` 之前新增 `#### 类别` 段落，允许值为 `functional` 或 `quality_evolution`。在模板说明中注明：`类别` 为必填字段，用于区分功能性需求与质量演进需求。不设默认值，缺失时 PrdParser 报错。
  - **AC**: 模板文件包含 `#### 类别` 段落。`grep -c "#### 类别" src/vibe_tracing/templates/prd.template.md` 返回 >= 1。
  - **Subagent**: self

- [ ] **Task ID**: GOV-TASK-002
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/prd_parser.py`
  - **Instruction**: 在 `Requirement` dataclass 中新增 `category: str` 字段（无默认值）。在 `_parse_requirements()` 中，使用与 `优先级` 相同的提取逻辑解析 `#### 类别` 段落——查找 level-4 heading 包含"类别"，读取下一个 paragraph token，允许值为 `functional` 或 `quality_evolution`。**缺失时报错**（与缺失优先级相同的错误处理路径）。新增 post-parse check：如果 REQ ID 匹配 `Q-\d+` 模式但 category 不是 `quality_evolution`，发出 WARNING。
  - **AC**: `python3 -m pytest tests/test_prd_parser.py -v` 全部通过。解析包含 `#### 类别: quality_evolution` 的 REQ 时，`req.category == "quality_evolution"`。解析无 `#### 类别` 的 REQ 时，解析器报错。现有测试必须更新以适配必填 category。
  - **Subagent**: self

- [ ] **Task ID**: GOV-TASK-003
  - **Action**: MODIFY
  - **Target File**: `docs/prd.md`
  - **Instruction**: 为所有现有 REQ（REQ-VT-001 到 REQ-VT-009）补充 `#### 类别: functional`。新增 `### REQ-VT-010：质量演进生命周期管理`，类别为 `quality_evolution`，优先级为 `should`。包含以下 AC：
    - `AC-VT-010-01`：8 维度反思诊断输出 — 条件：vt analyze 执行完成；期望输出：控制台输出包含 8 个维度的反思提示，每个维度包含标题、提示词、条件性提示。
    - `AC-VT-010-02`：反思诊断覆盖校验 — 条件：反思诊断输出包含 Affected Scope；期望输出：Affected Scope 中的文件路径与 task_list.json 的 code_refs 做覆盖校验，未覆盖的文件输出 WARNING。
    - `AC-VT-010-03`：进化计划结构化输出 — 条件：vt analyze 完成且存在质量缺陷；期望输出：可生成结构化的自我进化计划（Reflect ID + Violation Principle + Atomic Action Tasks）。
  - **AC**: `vt analyze` 通过所有门禁。PRD 中存在 REQ-VT-010 且包含 3 个 AC。所有 REQ 均有 `#### 类别` 段落。`grep -c "#### 类别" docs/prd.md` 返回 >= 10。
  - **Subagent**: self

- [ ] **Task ID**: GOV-TASK-004
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/reflection_prompts.py`
  - **Instruction**: 新增函数 `check_uncovered_scopes(affected_files: List[str], task_list: Dict[str, Any]) -> List[str]`：从 task_list 的 tasks 中提取所有 code_refs 文件路径，与 affected_files 做差集，返回未覆盖的文件路径列表。修改 `render_reflection_prompts()` 签名，新增 `task_list: Dict[str, Any]` 参数（**必传，非 Optional**）。在函数末尾（返回字符串之前），调用 `check_uncovered_scopes()`，如果有未覆盖文件，追加 WARNING 段落：
    ```
    ⚠ 治理覆盖警告 (Coverage Warning)
    以下反思诊断涉及的文件未被任何 Task/AC 覆盖：
      - path/to/file1.py
      - path/to/file2.py
    请在 docs/task_list.json 中补充对应 Task，并关联 REQ/AC。
    ```
  - **AC**: `python3 -m pytest tests/test_reflection_prompts.py -v` 全部通过。所有现有测试必须更新，传入 `task_list` 参数（可为空 dict `{"tasks": []}`）。新增测试：传入含 code_refs 的 task_list 时，未覆盖文件出现在输出中。
  - **Subagent**: self

- [ ] **Task ID**: GOV-TASK-005
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 在 `_evaluate_and_output()` 中调用 `render_reflection_prompts()` 时，传入 `task_list=ctx.task_result.raw_data`（或等效的 task_list dict）。确保 `task_list` 数据在 UnifiedContext 中可用且格式正确。
  - **AC**: `python3 -m pytest tests/test_cli_analyze.py tests/test_e2e_finalize_analyze.py -v` 全部通过。`vt analyze` 输出中包含反思提示。当存在未覆盖的 Affected Scope 文件时，输出包含 WARNING 段落。
  - **Subagent**: self

- [ ] **Task ID**: GOV-TASK-006
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/templates/reflection_prompts.template.json`
  - **Instruction**: 在第 8 个维度（dead_code）的 `conditional_hints` 数组中，新增一个 hint：`{"condition": "has_uncovered_evolution_scope", "text": "\n     ⚠ 发现 {uncovered_count} 个反思诊断涉及的文件未被 Task/AC 覆盖，治理链路存在盲区。"}`。在 `_evaluate_condition()` 中新增条件 `has_uncovered_evolution_scope`，返回 `uncovered_scope_count > 0`（需新增该参数）。在 `render_reflection_prompts()` 的调用链中传递 `uncovered_scope_count`。
  - **AC**: `python3 -m pytest tests/test_reflection_prompts.py -v` 全部通过。当存在未覆盖文件时，dead_code 维度输出包含条件性提示。
  - **Subagent**: self
