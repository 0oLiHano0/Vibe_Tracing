# VT 自我进化与演进计划

## 一、 概述 (Overview)

本轮实施了 PRD 质量演进 REQ 类别、反思覆盖校验、Gate 2.5 反向覆盖升级、Semantic Auditor 两阶段协议。执行过程中暴露了工具执行文件过滤缺失、治理机制文件被误判为幽灵代码、Gate 2.5 与 Gate 3 功能重叠等结构性问题。下一轮核心目标：**合并 Gate 2/2.5 为单一代码-声明对账、消除治理机制文件的 claim 冗余、从配置推导文件扩展名、拆分膨胀的门禁函数**。共 15 个原子化任务（EVO-TASK-010 ~ 014），均独立可验证。

---

## 二、 诊断与反思 (Diagnostics & Reflections)

- **Reflect ID**: EVO-REF-010
  - **Violation Principle**: 1 (项目不足识别)
  - **Diagnosis**: semantic_audit.json 被 Gate 2 幽灵代码检测阻断，要求每次修改审计单都必须同步修改 claim。治理机制文件（semantic_audit.json、agent_claims.json、config.json）与业务代码文件被同等对待，无白名单豁免。
  - **Root Cause**: Gate 2 的白名单只包含 agent_claims.json、config.json、task_list.json，未覆盖 semantic_audit.json。更深层原因：VT 治理模型未区分"治理机制文件"和"治理对象文件"。
  - **Affected Scope**: `src/vibe_tracing/ghost_code_reconciler.py`, `.vibetracing/semantic_audit.json`

- **Reflect ID**: EVO-REF-011
  - **Violation Principle**: 2 (架构精简度评估)
  - **Diagnosis**: Gate 2（幽灵代码检测）和 Gate 2.5（正向+反向覆盖校验）检查的是同一关系的两个角度——"代码文件与声明的结构性对账"。拆成两个 Gate 是历史演进的结果，不是设计意图。合并为单一 Gate 2 可消除命名混乱、减少函数数量、统一白名单管理。
  - **Root Cause**: Gate 2 和 Gate 2.5 在不同时间点独立添加，未做全局审视。两者都读取 staged files 和 claims，存在重复 I/O。
  - **Affected Scope**: `src/vibe_tracing/ghost_code_reconciler.py`, `src/vibe_tracing/ac_freshness_checker.py`, `src/vibe_tracing/cli.py`

- **Reflect ID**: EVO-REF-012
  - **Violation Principle**: 2 (架构精简度评估) + 4 (计算与逻辑冗余)
  - **Diagnosis**: `_execute_tools` 中 `_CODE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx"}` 硬编码，但 `architecture_constraints.json` 的 `language_tool_matrix` 已定义语言-工具映射。硬编码集合与配置重复，新增语言支持需同时修改两处。
  - **Root Cause**: 修复工具执行报错时采用最快方案（硬编码），未利用现有配置基础设施。
  - **Affected Scope**: `src/vibe_tracing/cli.py` (`_execute_tools` 函数)

- **Reflect ID**: EVO-REF-013
  - **Violation Principle**: 6 (代码认知复杂度)
  - **Diagnosis**: `_run_integrity_gates` 函数包含 Gate 1/1b/1c/2/2.5/3 六个检查逻辑，函数体超过 100 行。Gate 执行顺序是隐式的，无显式依赖声明。新增 Gate 需理解整个函数控制流。
  - **Root Cause**: 函数随 Gate 增长自然膨胀，未进行阶段性拆分。
  - **Affected Scope**: `src/vibe_tracing/cli.py` (`_run_integrity_gates`)

- **Reflect ID**: EVO-REF-014
  - **Violation Principle**: 5 (凭证真实性)
  - **Diagnosis**: Semantic Audit 的 `verify_tickets` 只检查 audit_reason 是否非空，不检查是否有意义。Agent 可填写"修改了代码"通过门禁。VT 治理模型过度依赖"声明存在性"而非"声明质量"。
  - **Root Cause**: 确定性工具无法判断语义质量，这是 VT 的固有天花板。但可通过结构化约束部分缓解。
  - **Affected Scope**: `src/vibe_tracing/semantic_auditor.py`

- **Reflect ID**: EVO-REF-015
  - **Violation Principle**: 7 (豁免与绕过机制)
  - **Diagnosis**: `--gates-only` CLI 参数仍存在，任何人可用来跳过工具执行和分析。VT 的 CLI 参数（`--pre-commit`、`--gates-only`、`--draft`）都是不同形式的绕过机制，其使用不受治理——无日志、无审计、无告警。
  - **Root Cause**: CLI 参数设计时未考虑治理追踪，参数使用是隐式行为。
  - **Affected Scope**: `src/vibe_tracing/cli.py` (CLI 参数定义)

- **Reflect ID**: EVO-REF-016
  - **Violation Principle**: 4 (计算与逻辑冗余)
  - **Diagnosis**: claims 的 code_refs 与 task 的 related_requirements 存在信息冗余。"cli.py 属于哪个 REQ"需要跨越 claim → task → requirement 三层推导。VT 项目中 claim 与 task 几乎都是一对一关系，分离设计增加了查找复杂度。
  - **Root Cause**: claim-task 分离设计支持"一个 task 被多个 claim 分阶段实现"的场景，但 VT 项目中该场景从未发生。
  - **Affected Scope**: `src/vibe_tracing/semantic_auditor.py`, `src/vibe_tracing/ghost_code_reconciler.py`

- **Reflect ID**: EVO-REF-017
  - **Violation Principle**: 8 (残留与死代码清理)
  - **Diagnosis**: `_CODE_EXTENSIONS` 硬编码集合是与 `language_tool_matrix` 配置重复的常量。`--gates-only` 从 hook 必要模式降级为手动调试工具，但代码中无注释说明降级历史。
  - **Root Cause**: 快速修复引入的冗余常量未及时清理。
  - **Affected Scope**: `src/vibe_tracing/cli.py`

---

## 三、 原子化动作指令 (Atomic Action Tasks)

- [ ] **Task ID**: EVO-TASK-010
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/ghost_code_reconciler.py`
  - **Instruction**: 在 `whitelist_paths` 集合中新增 `.vibetracing/semantic_audit.json`。治理机制文件不应被幽灵代码检测阻断。
  - **AC**: staging semantic_audit.json 时，Gate 2 不再报幽灵代码。`grep "semantic_audit" src/vibe_tracing/ghost_code_reconciler.py` 有结果。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-011a
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/ghost_code_reconciler.py`
  - **Instruction**: 在 `reconcile()` 方法中，幽灵代码检测之后追加反向覆盖检查：对每个 staged 代码文件，通过 claims 的 code_refs → related_task 映射，检查覆盖 task 是否存在。无覆盖 task → 返回 BLOCKED（success=False）。有覆盖 task 但 task 未在本次 commit 修改（比较 staged vs HEAD task_list.json）→ 追加 WARNING。
  - **AC**: `python3 -m pytest tests/test_ghost_code_reconciler.py -v` 全部通过。staged 代码文件无覆盖 claim 时返回 success=False。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-011b
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/ghost_code_reconciler.py`
  - **Instruction**: 在 `reconcile()` 方法中追加正向 AC 新鲜度检查（从 AcFreshnessChecker._forward_check 迁移）：比较 staged vs HEAD task_list.json，对新增 task 检查其 related_acceptance_criteria 是否在本次 commit 的 staged PRD 中。不新鲜 → 追加 WARNING。
  - **AC**: `python3 -m pytest tests/test_ghost_code_reconciler.py -v` 全部通过。新增 task 引用未更新的 AC 时输出 WARNING。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-011c
  - **Action**: DELETE
  - **Target File**: `src/vibe_tracing/ac_freshness_checker.py`, `src/vibe_tracing/cli.py`
  - **Instruction**: 删除 `AcFreshnessChecker` 类及其文件。在 cli.py `_run_integrity_gates` 中移除 Gate 2.5 调用代码块。
  - **AC**: `src/vibe_tracing/ac_freshness_checker.py` 不存在。`grep -rn "AcFreshnessChecker" src/` 无结果。`python3 -m pytest tests/test_cli_analyze.py tests/test_quality_gates.py -v` 全部通过。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-011d
  - **Action**: MODIFY
  - **Target File**: `tests/test_ghost_code_reconciler.py`, `tests/test_ac_freshness.py`
  - **Instruction**: 将 `test_ac_freshness.py` 中的测试用例迁移到 `test_ghost_code_reconciler.py`（或新建 `test_code_claim_alignment.py`）。删除 `test_ac_freshness.py`。
  - **AC**: `test_ac_freshness.py` 不存在。所有原测试用例在新位置通过。`python3 -m pytest tests/test_ghost_code_reconciler.py -v` 全部通过。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-012a
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/templates/architecture_constraints.template.json`
  - **Instruction**: 在 `language_tool_matrix` 的每个语言条目中新增 `extensions` 字段。python: `[".py"]`，javascript: `[".js", ".jsx"]`，typescript: `[".ts", ".tsx"]`。模板中已有 python 条目，补充 extensions。
  - **AC**: 模板 JSON 中每个 language 条目包含 `extensions` 数组。`python3 -c "import json; json.load(open('src/vibe_tracing/templates/architecture_constraints.template.json'))"` 无报错。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-012b
  - **Action**: MODIFY
  - **Target File**: `docs/architecture_constraints.json`
  - **Instruction**: 在 VT 项目自身的 `language_tool_matrix.python` 条目中新增 `"extensions": [".py"]`。
  - **AC**: `python3 -c "import json; d=json.load(open('docs/architecture_constraints.json')); assert '.py' in d['language_tool_matrix']['python']['extensions']"` 无报错。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-012c
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 将 `_execute_tools` 中的 `_CODE_EXTENSIONS` 硬编码替换为从配置读取。新增函数 `_get_code_extensions(ltm: Dict) -> Set[str]`，遍历 `ltm` 各语言条目的 `extensions` 字段合并为集合。配置中无 `extensions` 字段时 fallback 到 `set()`（该语言不执行工具）。`_execute_tools` 中使用此函数替代硬编码。
  - **AC**: `python3 -m pytest tests/test_tool_execution.py tests/test_cli_analyze.py -v` 全部通过。`_execute_tools` 中无硬编码 `_CODE_EXTENSIONS`。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-012d
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 在 `_run_analyzers` 或 `_evaluate_and_output` 中新增覆盖度检查：扫描 staged 代码文件的扩展名，与 `_get_code_extensions(ltm)` 做比对。如果 staged 文件的扩展名不在配置的 extensions 集合中，输出 WARNING：`"发现未配置的代码文件类型 .xxx，请更新 architecture_constraints.json 的 language_tool_matrix 并通过 vt finalize 锁定"`。
  - **AC**: `python3 -m pytest tests/test_cli_analyze.py -v` 全部通过。当 staged 文件有未配置扩展名时，输出包含 WARNING。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-013a
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 将 `_run_integrity_gates` 中 Gate 1（constraints hash 校验）提取为独立函数 `_gate1_constraints_hash(ctx, project_root) -> Optional[int]`。返回 None 表示通过，返回 int 表示 exit code。
  - **AC**: `_gate1_constraints_hash` 函数独立存在。`python3 -m pytest tests/test_cli_analyze.py -v` 全部通过。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-013b
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 将 Gate 1b（PRD 漂移检测）和 Gate 1c（PRD↔Arch 映射校验）提取为独立函数 `_gate1b_prd_drift(ctx) -> None`（WARNING only）和 `_gate1c_mapping(ctx, config_prefix) -> Optional[int]`。
  - **AC**: 两个函数独立存在。`python3 -m pytest tests/test_cli_analyze.py -v` 全部通过。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-013c
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 将 Gate 2（合并后的代码-声明对账）提取为独立函数 `_gate2_code_claim_alignment(ctx, project_root, is_pre_commit) -> Optional[int]`。此任务依赖 EVO-TASK-011 完成。
  - **AC**: 函数独立存在。`python3 -m pytest tests/test_cli_analyze.py tests/test_quality_gates.py -v` 全部通过。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-013d
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 将 Gate 3（Semantic Audit）提取为独立函数 `_gate3_semantic_audit(ctx, project_root, is_pre_commit) -> Optional[int]`。
  - **AC**: 函数独立存在。`python3 -m pytest tests/test_cli_analyze.py -v` 全部通过。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-013e
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 将 `_run_integrity_gates` 简化为编排函数，按序调用 `_gate1_constraints_hash` → `_gate1b_prd_drift` → `_gate1c_mapping` → `_gate2_code_claim_alignment` → `_gate3_semantic_audit`。任一返回非 None 则立即返回。
  - **AC**: `_run_integrity_gates` 函数体不超过 30 行。`python3 -m pytest tests/test_cli_analyze.py tests/test_quality_gates.py tests/test_e2e_finalize_analyze.py -v` 全部通过。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-014
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/semantic_auditor.py`
  - **Instruction**: 在 `verify_tickets` 中增加 audit_reason 结构化校验：reason 长度不得少于 20 字符，且必须包含被审计文件的文件名（`file_path` 的 basename）。不满足条件视为 BLOCKED。
  - **AC**: `python3 -m pytest tests/test_semantic_auditor.py -v` 全部通过。填写"修改了代码"无法通过验证。
  - **Subagent**: self
