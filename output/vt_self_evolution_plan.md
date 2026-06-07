# VT 自我进化与演进计划

## 一、 概述 (Overview)

本轮重构消除了 2x I/O、修复了 MergeGateEngine 逻辑缺陷、建立了 PRD 哈希保护与持续映射校验。整体架构精简度提升，但暴露了向后兼容 fallback 路径构成的"活死代码群"。下一轮核心目标：**清理 fallback 路径，将所有组件接口统一为"必须传入 UnifiedContext"，消除隐式数据加载**。

---

## 二、 诊断与反思 (Diagnostics & Reflections)

- **Reflect ID**: EVO-REF-001
  - **Violation Principle**: 8 (残留与死代码清理)
  - **Diagnosis**: `evidence_index_builder.py` 的 `build()` 方法保留了 `ctx=None` fallback 路径，当 ctx 为 None 时内部重新实例化 RawInputLoader/PrdParser/TaskLoader/ClaimLoader 并重新加载所有文件。当前所有调用方（cli.py）已传入 ctx，fallback 路径从未被执行。
  - **Root Cause**: 重构时采用"渐进式迁移"策略，保留旧路径作为向后兼容。但无外部消费者依赖旧接口，fallback 已成为死代码。
  - **Affected Scope**: `src/vibe_tracing/evidence_index_builder.py` (line 59-145 的 else 分支)

- **Reflect ID**: EVO-REF-002
  - **Violation Principle**: 8 (残留与死代码清理)
  - **Diagnosis**: `architecture_compliance_checker.py` 的 `check()` 方法保留了 `constraints_data=None` fallback 路径，当 constraints_data 为 None 时调用 `self._load_constraints()` 重新读取文件。cli.py 已始终传入 constraints_data。
  - **Root Cause**: 同 EVO-REF-001，渐进式迁移的遗留。
  - **Affected Scope**: `src/vibe_tracing/architecture_compliance_checker.py` (line 153-157 的 else 分支)

- **Reflect ID**: EVO-REF-003
  - **Violation Principle**: 8 (残留与死代码清理) + 4 (计算与逻辑冗余)
  - **Diagnosis**: `task_loader.py` 和 `claim_loader.py` 的 `load_and_validate()` 保留了 `skip_schema=False` 默认路径。cli.py 已始终传入 `skip_schema=True`，默认路径的 Schema 校验代码从未执行。
  - **Root Cause**: 同 EVO-REF-001。
  - **Affected Scope**: `src/vibe_tracing/task_loader.py` (skip_schema 分支), `src/vibe_tracing/claim_loader.py` (skip_schema 分支)

- **Reflect ID**: EVO-REF-004
  - **Violation Principle**: 6 (代码认知复杂度)
  - **Diagnosis**: `cli.py` 的 `run_analyze()` 函数约 600 行，包含 Gate 1/1b/1c/2/2.5、Schema 校验、PRD 解析、Task/Claim 校验、工具执行、证据索引构建、四路分析器、风险评估、门禁决策、产物输出。认知复杂度过高，阻碍 Agent 理解单一流程。
  - **Root Cause**: 函数随功能增长自然膨胀，未进行阶段性拆分。
  - **Affected Scope**: `src/vibe_tracing/cli.py` (run_analyze, line 421-1041)

- **Reflect ID**: EVO-REF-005
  - **Violation Principle**: 1 (项目不足识别)
  - **Diagnosis**: 工具依赖检查（pytest/ruff/mypy/bandit/coverage）的结果未纳入证据索引。当工具未安装时 analyze 直接失败，但失败原因不出现在 evidence_index.json 或 traceability_report.json 中。
  - **Root Cause**: 工具依赖检查是"环境问题"而非"治理问题"，设计时未将其纳入治理数据流。
  - **Affected Scope**: `src/vibe_tracing/cli.py` (工具执行预检阶段)

- **Reflect ID**: EVO-REF-006
  - **Violation Principle**: 2 (架构精简度评估)
  - **Diagnosis**: `reflection_prompts.py` 的 8 个维度硬编码在 Python 代码中。如果需要自定义维度、国际化或按项目配置，需要改代码。
  - **Root Cause**: 初版实现选择最简方案（硬编码），未预留配置化接口。
  - **Affected Scope**: `src/vibe_tracing/reflection_prompts.py`

---

## 三、 原子化动作指令 (Atomic Action Tasks)

- [ ] **Task ID**: EVO-TASK-001
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/evidence_index_builder.py`
  - **Instruction**: 将 `build()` 方法签名从 `build(self, output_path=None, ctx=None, **kwargs)` 改为 `build(self, output_path, ctx)`，移除 `ctx=None` 的可选性。删除 `__init__` 中的 `self.raw_loader`、`self.prd_parser`、`self.task_loader`、`self.claim_loader`、`self.tool_adapter` 实例化。删除 `build()` 中 ctx 为 None 时的整个 else 分支（line 87-145）。删除 `importlib` 动态导入。
  - **AC**: `python3 -m pytest tests/test_evidence_index_builder.py tests/test_cli_analyze.py tests/test_e2e_finalize_analyze.py -v` 全部通过。`grep -n "ctx=None" src/vibe_tracing/evidence_index_builder.py` 无结果。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-002
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/architecture_compliance_checker.py`
  - **Instruction**: 将 `check()` 方法签名从 `check(self, evidences, constraints_data=None)` 改为 `check(self, evidences, constraints_data)`，移除 `constraints_data=None` 的可选性。删除 `constraints_data` 为 None 时调用 `self._load_constraints()` 的 fallback 分支。删除 `__init__` 中的 `self.constraints_path` 存储（如果不再需要）。
  - **AC**: `python3 -m pytest tests/test_architecture_compliance_checker.py tests/test_cli_analyze.py -v` 全部通过。`grep -n "constraints_data=None" src/vibe_tracing/architecture_compliance_checker.py` 无结果。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-003
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/task_loader.py`, `src/vibe_tracing/claim_loader.py`
  - **Instruction**: 将 `load_and_validate()` 的 `skip_schema` 参数默认值从 `False` 改为 `True`。或者更彻底地：移除 `skip_schema` 参数，始终跳过 Schema 校验（由 cli.py 统一校验）。删除 `skip_schema=False` 分支中的 Schema 校验代码。
  - **AC**: `python3 -m pytest tests/test_task_loader.py tests/test_claim_loader.py tests/test_cli_analyze.py -v` 全部通过。`grep -n "skip_schema" src/vibe_tracing/task_loader.py src/vibe_tracing/claim_loader.py` 无结果（如果选择移除参数）。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-004
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 将 `run_analyze()` 拆分为多个子函数：
    - `_load_and_validate_inputs(project_root, raw_loader, validator) -> UnifiedContext`
    - `_run_integrity_gates(ctx, is_pre_commit, project_root) -> int|None`（返回 exit code 或 None 表示通过）
    - `_execute_tools(ctx, project_root) -> List[ToolEvidenceCandidate]`
    - `_run_analyzers(ctx, evidence_list) -> Tuple[gaps, risks, compliance]`
    - `_evaluate_and_output(ctx, gaps, risks, compliance, output_dir) -> int`
    - `run_analyze()` 变为编排函数，调用上述子函数。
  - **AC**: `run_analyze()` 函数体不超过 50 行。`python3 -m pytest tests/test_cli_analyze.py tests/test_e2e_finalize_analyze.py -v` 全部通过。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-005
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`, `src/vibe_tracing/evidence_index_builder.py`
  - **Instruction**: 在工具依赖检查失败时，生成一条 `ToolEvidenceCandidate`（status=BLOCKED, error_code=tool_not_found）并注入 `ctx.tool_evidence`，而非直接 return 1。这样工具安装状态会出现在 evidence_index.json 中，可被分析器和报告追踪。
  - **AC**: 当工具未安装时，`vt analyze` 不直接退出，而是在 evidence_index.json 中记录 BLOCKED 证据，最终 gate_decision 为 blocked（因为工具证据缺失导致 AC 无覆盖）。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-006
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/reflection_prompts.py`
  - **Instruction**: 将 8 个维度的提示词从硬编码改为从配置文件读取。创建 `src/vibe_tracing/templates/reflection_prompts.template.json`，包含维度 ID、标题、提示词模板、条件表达式。`render_reflection_prompts()` 从配置文件加载维度列表并渲染。
  - **AC**: `python3 -m pytest tests/test_reflection_prompts.py -v` 全部通过（测试需适配新接口）。自定义维度可通过修改 JSON 配置实现，无需改 Python 代码。
  - **Subagent**: self
