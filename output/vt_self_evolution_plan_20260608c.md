# VT 自我进化与演进计划

## 一、 概述 (Overview)

本轮从"用户+开发者"双视角进行 8 维度反思，清理了 3 层治理债务（unclear constraints、非存在证据、工具不可用），修复了工具依赖检查和执行回退机制。核心发现：**VT 缺少独立于工具执行的"治理数据健康度检查"机制，导致债务只能在 hook 失败时被动暴露，而非主动检测。** 预存债务必须清零——不能用 `--no-verify` 绕过，否则 Agent 会养成绕过习惯，破坏证据链。

---

## 二、 诊断与反思 (Diagnostics & Reflections)

- **Reflect ID**: EVO-REF-024
  - **Violation Principle**: 1 (项目不足识别)
  - **Diagnosis**: VT 的工具依赖检查只检查裸二进制（`shutil.which`），不检查 Python 模块（`python3 -m`）。工具通过 pip 安装为 Python 模块时，VT 误判为"工具未安装"，跳过工具执行，产生空证据链。修复花了 3 轮迭代（检测→执行→复合命令），说明根因分析不够彻底。
  - **Root Cause**: 工具可用性检查假设工具以独立二进制形式安装，未考虑 Python 模块安装方式。
  - **Affected Scope**: `src/vibe_tracing/cli.py`, `src/vibe_tracing/tool_evidence_adapter.py`

- **Reflect ID**: EVO-REF-025
  - **Violation Principle**: 2 (架构精简度评估)
  - **Diagnosis**: `_tool_available`（cli.py）和命令回退逻辑（tool_evidence_adapter.py）分散在两个模块，都在解决同一个问题（工具不在 PATH 上）。应该有统一的工具路径解析层。
  - **Root Cause**: 修复时采用最快方案（各自模块内修复），未做统一抽象。
  - **Affected Scope**: `src/vibe_tracing/cli.py`, `src/vibe_tracing/tool_evidence_adapter.py`

- **Reflect ID**: EVO-REF-026
  - **Violation Principle**: 3 (彻底根因修复验证)
  - **Diagnosis**: 本轮清理了 3 层债务，但每层都是被 hook 失败暴露的，不是主动发现的。VT 缺少"债务检测"机制——不是等 hook 失败才发现问题，而是定期扫描治理数据健康度。
  - **Root Cause**: VT 的验证依赖工具执行。工具不运行时，claim 的 evidence_refs 不被校验，债务不可见。
  - **Affected Scope**: 整体架构

- **Reflect ID**: EVO-REF-027
  - **Violation Principle**: 4 (计算与逻辑冗余)
  - **Diagnosis**: evidence_refs 引用 test nodeid（如 `tests/test_foo.py::test_bar`），但 evidence_index 中的条目是 source_path 级别（如 `src/foo.py`）。粒度不匹配导致引用永远无法对齐。
  - **Root Cause**: 工具执行生成 source_path 级别证据，但 claims 设计时假设 test nodeid 级别证据。
  - **Affected Scope**: `src/vibe_tracing/traceability/claim_evidence_analyzer.py`, `.vibetracing/agent_claims.json`

- **Reflect ID**: EVO-REF-028
  - **Violation Principle**: 5 (凭证真实性)
  - **Diagnosis**: verification_method 字段区分了"可自动验证"和"需人类审查"的规则。但 VT 缺少让人类明确"接受"手动规则的机制——当前只是标记为 manual 然后忽略，没有人类确认的记录。
  - **Root Cause**: VT 的治理模型缺少"人类确认"这个环节。manual 规则应该有人类确认的记录，而不是被静默忽略。
  - **Affected Scope**: `src/vibe_tracing/architecture_compliance_checker.py`

- **Reflect ID**: EVO-REF-029
  - **Violation Principle**: 6 (代码认知复杂度)
  - **Diagnosis**: 债务清理过程逐层剥离（unclear → 非存在引用 → 工具不可用），每层修复暴露下一层。应该有"vt doctor"式的一次性全量扫描，而不是分轮修复。
  - **Root Cause**: VT 的验证是增量的（每次 commit 检查变更），没有全量扫描模式。
  - **Affected Scope**: 整体架构

- **Reflect ID**: EVO-REF-030
  - **Violation Principle**: 7 (豁免与绕过机制)
  - **Diagnosis**: 本轮多次使用 `--no-verify` 绕过 hook，每次都是因为 BLOCKED 来自预存债务。hook 应该区分"当前变更引入的问题"和"预存债务"——预存债务应该输出 WARNING 而非阻断，否则 Agent 会学会总是绕过。
  - **Root Cause**: hook 的 BLOCKED 判定不区分问题来源（当前变更 vs 预存）。
  - **Affected Scope**: `src/vibe_tracing/ghost_code_reconciler.py`, `src/vibe_tracing/merge_gate_engine.py`

- **Reflect ID**: EVO-REF-031
  - **Violation Principle**: 8 (残留与死代码清理)
  - **Diagnosis**: CLAIM-VT-005 的 12 条 evidence_refs 全部指向不存在的 test nodeid，从项目早期就存在但未被检测到。claim 引用完整性校验依赖工具执行，工具不运行时债务不可见。
  - **Root Cause**: claim 验证依赖 evidence_index（需要工具执行），缺少独立于工具执行的文件系统级引用校验。
  - **Affected Scope**: `.vibetracing/agent_claims.json`

---

## 三、 原子化动作指令 (Atomic Action Tasks)

### 工具路径统一解析

- [ ] **Task ID**: EVO-TASK-021
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/tool_evidence_adapter.py`, `src/vibe_tracing/cli.py`
  - **Instruction**: 将工具可用性检查和命令回退逻辑统一到 `ToolExecutionEngine` 中。新增 `resolve_command(tool_name, template) -> str` 方法：检查 `shutil.which(tool_name)`，不可用时尝试 `python3 -m tool_name`，返回可执行的命令模板。cli.py 的 `_tool_available` 和 `_execute_tools` 中的回退逻辑全部移除，改用 engine 的统一方法。
  - **AC**: `python3 -m pytest tests/test_tool_execution.py tests/test_cli_analyze.py -v` 全部通过。cli.py 中无 `_tool_available` 函数。
  - **Subagent**: self

### 债务全量扫描

- [ ] **Task ID**: EVO-TASK-022
  - **Action**: NEW
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 新增 `vt doctor` 子命令，一次性扫描所有治理数据健康度：
    1. claims 的 evidence_refs 是否指向存在的文件/测试
    2. claims 的 code_refs/test_refs 是否指向存在的文件
    3. tasks 的 related_requirements 是否在 PRD 中存在
    4. tasks 的 related_acceptance_criteria 是否在 PRD 中存在
    5. 架构约束的 verification_method 为 machine 的规则是否都有对应的检查实现
    输出健康度报告（JSON 格式），列出所有发现的问题。
  - **AC**: `vt doctor` 输出包含所有 5 项检查结果。发现的问题可逐个修复。
  - **Subagent**: self

### 预存债务清零

- [ ] **Task ID**: EVO-TASK-023
  - **Action**: MODIFY
  - **Target File**: `.vibetracing/agent_claims.json`, `docs/task_list.json`
  - **Instruction**: 运行 `vt doctor`（或手动扫描），修复所有预存债务：
    1. 更新 evidence_refs 指向实际存在的证据
    2. 更新 code_refs/test_refs 指向实际存在的文件
    3. 确保所有 claims 的 evidence_refs 非空且非自引用
    4. 确保所有 tasks 的 related_requirements 在 PRD 中存在
    目标：`vt analyze --pre-commit` 的 BLOCKED 全部来自当前变更的代码质量问题，而非预存债务。
  - **AC**: `vt analyze --pre-commit` 输出中无"non-existent evidence"、"non-existent code path"、"non-existent test path"。
  - **Subagent**: self

### hook 债务感知

- [ ] **Task ID**: EVO-TASK-024
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/merge_gate_engine.py`, `src/vibe_tracing/cli.py`
  - **Instruction**: 在门禁决策中区分"当前变更引入的问题"和"预存债务"。具体做法：对每个 BLOCKED reason，检查其关联的 claim/task 是否在本次 commit 中被修改（staged vs HEAD）。未修改的 claim/task 产生的 BLOCKED 标记为 `source: "pre_existing"`。输出时区分显示：当前变更的问题标记为 `[当前]`，预存债务标记为 `[预存]`。
  - **AC**: `vt analyze --pre-commit` 输出中，BLOCKED reasons 区分 `[当前]` 和 `[预存]` 来源。
  - **Subagent**: self
