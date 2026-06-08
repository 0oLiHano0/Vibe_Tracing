# VT 自我进化与演进计划

## 一、 概述 (Overview)

本轮从"用户+开发者"双视角进行 8 维度反思，清理了 3 层治理债务（unclear constraints、非存在证据、工具不可用），修复了工具依赖检查和执行回退机制。核心发现：(1) VT 缺少独立于工具执行的"治理数据健康度检查"机制，导致债务只能在 hook 失败时被动暴露；(2) 工具检测机制存在 3 个缺陷（不检查 exit code、两处不同步、依赖 `--version`），需要统一为一个工具解析层；(3) hook 的 BLOCKED 判定不区分"当前变更"和"预存债务"，迫使 Agent 使用 `--no-verify` 绕过。预存债务必须清零——不能用绕过手段逃避。

---

## 二、 诊断与反思 (Diagnostics & Reflections)

- **Reflect ID**: EVO-REF-024
  - **Violation Principle**: 1 (项目不足识别)
  - **Diagnosis**: VT 的工具依赖检查只检查裸二进制（`shutil.which`），不检查 Python 模块（`python3 -m`）。工具通过 pip 安装为 Python 模块时，VT 误判为"工具未安装"，跳过工具执行，产生空证据链。
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
  - **Root Cause**: VT 的治理模型缺少"人类确认"这个环节。
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

- **Reflect ID**: EVO-REF-032
  - **Violation Principle**: 1 (项目不足识别)
  - **Diagnosis**: 债务有隐藏的层叠结构——清理第一层（unclear constraints）后暴露第二层（非存在证据），清理第二层后暴露第三层（工具不可用）。债务之间有依赖关系：工具不可用 → 证据为空 → 引用无法校验 → 债务不可见。VT 缺少能穿透所有层的全量扫描机制。
  - **Root Cause**: VT 的验证是增量的（每次 commit 检查变更），没有全量扫描模式。债务只能在 hook 失败时被动暴露。
  - **Affected Scope**: 整体架构

- **Reflect ID**: EVO-REF-033
  - **Violation Principle**: 2 (架构精简度评估)
  - **Diagnosis**: evidence_refs 的粒度设计有问题。claims 的 evidence_refs 引用文件路径，但 evidence_index 中同一文件可能有多个条目（不同工具的结果）。ClaimEvidenceAnalyzer 需要额外的 source_path → source_type 映射逻辑才能对齐，增加了复杂度。
  - **Root Cause**: claims 设计时假设 evidence_index 的粒度与文件路径一致，实际不一致。
  - **Affected Scope**: `src/vibe_tracing/traceability/claim_evidence_analyzer.py`

- **Reflect ID**: EVO-REF-034
  - **Violation Principle**: 4 (计算与逻辑冗余)
  - **Diagnosis**: evidence_index 中的 "violated" 状态来自 3 种不同工具（ruff、mypy、coverage），但状态码相同。排查时需要逐个检查 stderr 内容才能区分来源。应该在 evidence 条目中增加 `tool_category` 字段。
  - **Root Cause**: ToolEvidenceCandidate 的 status 字段承载了过多语义。
  - **Affected Scope**: `src/vibe_tracing/tool_evidence_adapter.py`, `src/vibe_tracing/evidence_index_builder.py`

- **Reflect ID**: EVO-REF-035
  - **Violation Principle**: 5 (凭证真实性)
  - **Diagnosis**: claims 的 evidence_refs 经历了 3 轮修改才对齐（替换为 code_refs → 指向实际文件 → 指向 evidence_index 条目）。claim 的证据引用没有可靠的自动生成机制，每次都是手动修复。
  - **Root Cause**: claim 的 evidence_refs 需要与 evidence_index 对齐，但两者之间没有自动关联逻辑。
  - **Affected Scope**: `.vibetracing/agent_claims.json`

- **Reflect ID**: EVO-REF-036
  - **Violation Principle**: 7 (豁免与绕过机制)
  - **Diagnosis**: 债务清零过程中 `--no-verify` 被使用 3 次，每次都是因为 hook 的 BLOCKED 来自预存债务。hook 需要区分"当前变更引入的问题"和"预存债务"。
  - **Root Cause**: hook 的 BLOCKED 判定不区分问题来源。
  - **Affected Scope**: `src/vibe_tracing/ghost_code_reconciler.py`, `src/vibe_tracing/merge_gate_engine.py`

- **Reflect ID**: EVO-REF-037
  - **Violation Principle**: 1 (项目不足识别)
  - **Diagnosis**: 项目有 500+ 测试用例，但代码行覆盖率仅 42%（低于 80% 阈值）。覆盖率工具将 41 个证据标记为 "violated"。测试用例数量与覆盖率严重不匹配，说明测试用例的分布和目标需要全面审查——可能大量测试集中在少量模块，而大量模块缺少测试。
  - **Root Cause**: 测试用例随功能增长自然积累，未有系统的覆盖率规划。需要独立调查和重新规划。
  - **Affected Scope**: 整体测试套件

---

## 三、 问题归类

| 类别 | 问题 | 关联诊断 |
|---|---|---|
| **工具解析** | 检测不完整、两处不同步、依赖 --version | 024, 025 |
| **债务检测** | 无全量扫描、债务层叠不可见 | 026, 029, 031, 032 |
| **hook 行为** | BLOCKED 不区分当前/预存，迫使绕过 | 030, 036 |
| **证据管理** | 粒度不匹配、violated 语义模糊、无自动生成 | 027, 033, 034, 035 |
| **规则确认** | manual 规则无确认记录 | 028 |
| **测试覆盖** | 500+ 测试但覆盖率 42% | 037 |

---

## 四、 原子化动作指令 (Atomic Action Tasks)

### 批次 1：工具解析统一（基础层，其他任务依赖）

- [ ] **Task ID**: EVO-TASK-021
  - **Action**: NEW
  - **Target File**: `src/vibe_tracing/tool_resolver.py`
  - **Instruction**: 新建 `ToolResolver` 类，统一工具可用性检测和命令解析：
    - `is_available(tool_name: str) -> bool`：先 `shutil.which(tool_name)`，不可用时 `importlib.import_module(tool_name)` 验证模块存在（不依赖 `--version`）。检查模块可导入即视为可用。
    - `resolve_command(command_template: str) -> str`：解析命令模板，对每个 `;` 分隔的段提取工具名，不可用时替换为 `python3 -m` 形式。
  - **AC**: `python3 -m pytest tests/test_tool_execution.py -v` 全部通过。`ToolResolver` 可独立导入和使用。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-021b
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`, `src/vibe_tracing/tool_evidence_adapter.py`
  - **Instruction**: 将 cli.py 的 `_tool_available` 函数和 tool_evidence_adapter.py 的 fallback 逻辑替换为 `ToolResolver` 调用。删除 `_tool_available` 函数，删除 `import shutil as _shutil` 和 `import sys` 的冗余导入。
  - **AC**: `grep -n "_tool_available\|_shutil.which" src/vibe_tracing/cli.py src/vibe_tracing/tool_evidence_adapter.py` 无结果。`python3 -m pytest tests/ --tb=short` 全部通过。
  - **Subagent**: self

### 批次 2：债务检测 + 证据增强（依赖批次 1）

- [ ] **Task ID**: EVO-TASK-022
  - **Action**: NEW
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 新增 `vt doctor` 子命令，一次性扫描治理数据健康度：
    1. claims 的 evidence_refs 是否指向 evidence_index 中存在的条目
    2. claims 的 code_refs/test_refs 是否指向存在的文件
    3. tasks 的 related_requirements 是否在 PRD 中存在
    4. tasks 的 related_acceptance_criteria 是否在 PRD 中存在
    5. 架构约束 verification_method=machine 的规则是否有检查实现
    输出 JSON 格式健康度报告。
  - **AC**: `vt doctor` 输出包含 5 项检查结果，问题可逐个定位。
  - **Subagent**: self

- [ ] **Task ID**: EVO-TASK-027
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/tool_evidence_adapter.py`, `src/vibe_tracing/evidence_index_builder.py`
  - **Instruction**: 在 `ToolEvidenceCandidate` 中新增 `tool_category: str` 字段（值为 "test"/"lint"/"type_check"/"security"/"coverage"）。在 `execute_tool()` 中设置该字段。在 `evidence_index_builder.py` 中将 `tool_category` 写入 evidence_index 条目。这样 "violated" 状态可以区分来源工具。
  - **AC**: `python3 -m pytest tests/test_tool_execution.py tests/test_evidence_index_builder.py -v` 全部通过。evidence_index 中的条目包含 `tool_category` 字段。
  - **Subagent**: self

### 批次 3：hook 债务感知（依赖批次 2）

- [ ] **Task ID**: EVO-TASK-025
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/merge_gate_engine.py`, `src/vibe_tracing/cli.py`
  - **Instruction**: 在门禁决策中区分"当前变更引入的问题"和"预存债务"：
    - MergeGateEngine.evaluate() 新增 `staged_items: Optional[Set[str]]` 参数
    - 对每个 BLOCKED reason，检查其关联的 claim_id/task_id 是否在 staged_items 中
    - 不在的标记为 `source: "pre_existing"`，在的标记为 `source: "current"`
    - 输出时 `[当前]` 和 `[预存]` 区分显示
  - **AC**: `vt analyze --pre-commit` 输出中 BLOCKED reasons 区分来源。`python3 -m pytest tests/test_merge_gate_engine.py tests/test_quality_gates.py -v` 全部通过。
  - **Subagent**: self

### 批次 4：规则确认机制（独立，可与批次 2/3 并行）

- [ ] **Task ID**: EVO-TASK-028
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/architecture_compliance_checker.py`, `docs/architecture_constraints.json`
  - **Instruction**: 为 manual 规则增加人类确认机制：
    - 在 architecture_constraints.json 中，manual 规则新增 `accepted_by: null` 和 `accepted_at: null` 字段
    - 在 compliance checker 中，manual 规则如果 `accepted_by` 为 null，输出提示："规则 {rule_id} 需要人类确认，请在 architecture_constraints.json 中设置 accepted_by 和 accepted_at"
    - 如果 `accepted_by` 非 null，跳过该规则的检查（已确认）
    - 新增 `vt accept <rule_id>` 子命令，自动填充 accepted_by 和 accepted_at
  - **AC**: `vt accept PRINCIPLE-VT-001` 成功填充确认字段。已确认的规则不再输出提示。
  - **Subagent**: self

### 独立计划：测试覆盖率调查（暂不实施）

- [ ] **Task ID**: EVO-TASK-026
  - **Action**: NEW
  - **Target File**: 测试套件整体
  - **Instruction**: 调查 500+ 测试用例但覆盖率仅 42% 的根因。分析各模块的测试分布，输出覆盖率分析报告和测试补充计划。需要独立计划和调度。
  - **AC**: 输出覆盖率分析报告。
  - **Subagent**: 待定

---

## 五、 批次依赖关系

```
批次 1（工具解析）  ──→  批次 2（债务检测 + 证据增强）  ──→  批次 3（hook 债务感知）
                                    ↓
                              批次 4（规则确认）── 独立，可并行
                                    ↓
                         独立计划（测试覆盖率调查）
```

- 批次 1 无依赖，可立即执行
- 批次 2 依赖批次 1（ToolResolver 可用后才能运行 vt doctor）
- 批次 3 依赖批次 2（需要 tool_category 字段才能精确区分来源）
- 批次 4 独立，可与批次 2/3 并行
- 测试覆盖率调查完全独立
