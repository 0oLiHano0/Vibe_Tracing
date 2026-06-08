# VT 自我进化与演进计划

## 一、 概述 (Overview)

本轮进化将 VT 从"报告工具"升级为"决策平台"，核心产出包括：Agent 可执行行动清单、Dashboard 待决策标签页（业务语言+折叠证据链+交互按钮）、Decision API、决策日志机制。同时修复了 6 个预存 AC 覆盖率缺口，更新了架构约束白名单。

**整体质量评估**：方向正确，执行中暴露了 VT 自身的治理盲区——门禁摩擦导致大量时间花在"通过门禁"而非"交付价值"。决策平台功能已就绪但缺乏端到端测试，Agent 行动清单有 bug（已修复）。

**下一轮核心目标**：清理预存债务（11 个 AC 覆盖率缺口）、补充决策平台端到端测试、优化门禁摩擦。

---

## 二、 诊断与反思 (Diagnostics & Reflections)

- **Reflect ID**: EVO-REF-001
  - **Violation Principle**: 1 (项目不足识别)
  - **Diagnosis**: Agent 视图长期缺失。vt analyze 只输出统计摘要（Gaps: 12, Risks: 5），不输出"下一步做什么"。Agent 需要自己读 PRD/代码/测试来推断行动。
  - **Root Cause**: VT 的设计初衷是"一致性校验"，但演变成了"增加摩擦"。没有从 Agent 的使用场景出发设计输出格式。
  - **Affected Scope**: src/vibe_tracing/cli.py (run_analyze 输出逻辑)
  - **Status**: ✅ 已解决 — 新增 `_format_agent_actions` 函数，输出可执行行动清单

- **Reflect ID**: EVO-REF-002
  - **Violation Principle**: 1 (项目不足识别)
  - **Diagnosis**: 人类决策窗口被噪音消除堵死。accepted_by 让规则从输出消失，exit code 5/2 让"无测试"信息被丢弃，stale 机制让预存债务被门禁忽略。
  - **Root Cause**: 噪音消除措施偏向"减少 Agent 摩擦"，以"降低人类可见性"为代价。没有区分 Agent 视图和人类视图。
  - **Affected Scope**: src/vibe_tracing/architecture_compliance_checker.py, src/vibe_tracing/tool_evidence_adapter.py
  - **Status**: ✅ 已解决 — accepted_rules 可见化、skipped 证据生成、Dashboard 待决策标签页

- **Reflect ID**: EVO-REF-003
  - **Violation Principle**: 1 (项目不足识别)
  - **Diagnosis**: PRD 落后于代码实现。PRD 中 AC-VT-009-17 写的是 hook 使用 --gates-only 模式，但该标志已被废弃。
  - **Root Cause**: 代码变更时未同步更新 PRD。VT 的 PRD↔代码一致性校验在开发阶段被跳过。
  - **Affected Scope**: docs/prd.md
  - **Status**: ✅ 已解决 — PRD 已更新，移除 --gates-only 引用

- **Reflect ID**: EVO-REF-004
  - **Violation Principle**: 1 (项目不足识别)
  - **Diagnosis**: 治理覆盖盲区——63 个文件未被任何 Task/AC 覆盖。VT 自身的治理链路存在大面积盲区。
  - **Root Cause**: VT 的 Task/AC 体系只覆盖了核心功能模块，辅助文件（schemas、templates、fixtures、config）未纳入治理。
  - **Affected Scope**: 全项目 63 个文件
  - **Status**: ❌ 未解决 — 需要在后续迭代中逐步补充覆盖

- **Reflect ID**: EVO-REF-005
  - **Violation Principle**: 3 (彻底根因修复验证)
  - **Diagnosis**: Agent 行动清单 bug——门禁 BLOCKED 但行动清单显示"NO ACTION REQUIRED"。
  - **Root Cause**: `_format_agent_actions` 只检查 active_gaps（非 stale），不检查 gate_reasons、架构违规、AC 覆盖率缺口等其他阻断源。
  - **Affected Scope**: src/vibe_tracing/cli.py (_format_agent_actions)
  - **Status**: ✅ 已解决 — 新增 gate_reasons/merged_gaps/compliance_status 参数，fallback 机制

- **Reflect ID**: EVO-REF-006
  - **Violation Principle**: 3 (彻底根因修复验证)
  - **Diagnosis**: claims 时间戳批量更新是打补丁式修复。修改 cli.py 后批量更新 19 个旧 claims 时间戳，而非验证 claim 有效性。
  - **Root Cause**: VT 的 claim 时间戳机制与文件修改脱节。文件被修改后，引用它的 claim 应该自动标记为"需要重新验证"，而非依赖手动更新时间戳。
  - **Affected Scope**: .vibetracing/agent_claims.json
  - **Status**: ❌ 未解决 — 需要设计 claim 自动失效机制

- **Reflect ID**: EVO-REF-007
  - **Violation Principle**: 4 (计算与逻辑冗余)
  - **Diagnosis**: D2 单次加载优化修改了 5 个文件，收益不确定（文件 I/O 非瓶颈），成本很高（白名单更新+变更日志）。
  - **Root Cause**: AC-VT-009-12 的"单次加载"要求可能过度工程。在 VT 的使用场景中，文件读取次数不是性能瓶颈。
  - **Affected Scope**: src/vibe_tracing/raw_input_loader.py, src/vibe_tracing/cli.py, src/vibe_tracing/architecture_change_proposal.py, src/vibe_tracing/architecture_compliance_checker.py, src/vibe_tracing/dashboard_renderer.py
  - **Status**: ❌ 未解决 — 需要评估是否回滚 D2 的代码修改

- **Reflect ID**: EVO-REF-008
  - **Violation Principle**: 4 (计算与逻辑冗余)
  - **Diagnosis**: 行动清单的内联上下文可能冗余。Agent 可以自己读取 PRD/代码/测试文件，VT 做内联增加了 vt analyze 的运行时间。
  - **Root Cause**: 未区分"能力弱的 Agent"（需要内联）和"能力强的 Agent"（可以自己读取）。
  - **Affected Scope**: src/vibe_tracing/cli.py (_format_agent_actions, _get_ac_description, _get_related_code)
  - **Status**: ❌ 未解决 — 需要评估内联上下文的实际价值

- **Reflect ID**: EVO-REF-009
  - **Violation Principle**: 5 (凭证真实性)
  - **Diagnosis**: 决策平台功能缺乏端到端测试。Dashboard JavaScript 逻辑（extractPendingDecisions、submitDecision）和 Decision API 完全没有测试。
  - **Root Cause**: 测试策略偏向核心逻辑（checker、validator），忽略了用户体验（dashboard、action list）。
  - **Affected Scope**: src/vibe_tracing/templates/dashboard.template.html, decision_server.py
  - **Status**: ❌ 未解决 — 需要补充决策平台测试

- **Reflect ID**: EVO-REF-010
  - **Violation Principle**: 5 (凭证真实性)
  - **Diagnosis**: 11 个 AC 覆盖率缺口（AC-VT-009-03/04/08/09/10/11/13/14/15/16/17）阻断门禁。
  - **Root Cause**: VT 的 AC 体系定义了大量验收标准，但测试覆盖跟不上。部分 AC 的实现分散在多个文件中，难以用单一测试覆盖。
  - **Affected Scope**: tests/test_*.py
  - **Status**: ❌ 未解决 — 需要逐个 AC 补充测试

- **Reflect ID**: EVO-REF-011
  - **Violation Principle**: 6 (代码认知复杂度)
  - **Diagnosis**: `_format_agent_actions` 接收 9 个参数，内部有 5 个 action 来源分支。认知复杂度高。
  - **Root Cause**: 函数承担了太多职责——gap 检测、risk 检测、violation 检测、gate_reason fallback、渲染。应该拆分。
  - **Affected Scope**: src/vibe_tracing/cli.py (_format_agent_actions)
  - **Status**: ❌ 未解决 — 需要拆分为独立函数

- **Reflect ID**: EVO-REF-012
  - **Violation Principle**: 7 (豁免与绕过机制)
  - **Diagnosis**: 架构约束白名单扩展可能是"为了绕过门禁而修改约束"。MOD-VT-001 和 MOD-VT-005 的白名单扩展是否反映了真实架构需求？
  - **Root Cause**: VT 的门禁不区分"架构违规"和"架构演进"。Agent 倾向于"修改约束来绕过门禁"。
  - **Affected Scope**: docs/architecture_constraints.json
  - **Status**: ❌ 未解决 — 需要设计架构演进的显式机制

- **Reflect ID**: EVO-REF-013
  - **Violation Principle**: 7 (豁免与绕过机制)
  - **Diagnosis**: --no-verify 的多次讨论说明 VT 门禁对当前开发节奏造成显著摩擦。
  - **Root Cause**: VT 的完整分析模式在 pre-commit 阶段暴露了所有预存债务，导致每次提交都被阻断。开发阶段需要区分"当前变更的问题"和"代码库积累的问题"。
  - **Affected Scope**: .git/hooks/pre-commit
  - **Status**: ❌ 未解决 — 需要设计"当前变更 vs 预存债务"的分离机制

- **Reflect ID**: EVO-REF-014
  - **Violation Principle**: 8 (残留与死代码清理)
  - **Diagnosis**: dashboard 的 submitDecision 本地回退是半成品——标记"已决策（本地）"但没有持久化，刷新页面后丢失。
  - **Root Cause**: 交互功能分两步实现（先展示后交互），但第二步的回退逻辑不完整。
  - **Affected Scope**: src/vibe_tracing/templates/dashboard.template.html
  - **Status**: ❌ 未解决 — 需要完善本地回退的持久化

- **Reflect ID**: EVO-REF-015
  - **Violation Principle**: 8 (残留与死代码清理)
  - **Diagnosis**: Decision API 的 /api/pending 端点是占位符，返回空数据。
  - **Root Cause**: 实现时只完成了 GET/POST /api/decisions，/api/pending 留为 TODO。
  - **Affected Scope**: decision_server.py
  - **Status**: ❌ 未解决 — 需要实现或移除

- **Reflect ID**: EVO-REF-016
  - **Violation Principle**: 6 (代码认知复杂度)
  - **Diagnosis**: VT 输出的信息密度问题需要重新审视。初始设计中 level1（Agent 视图）被定义为"精简摘要"，但这是从"当前 Agent 足够智能且有完整对话上下文"的角度出发的错误假设。
  - **Root Cause**: 一个没有对话上下文的 subagent 需要的是"技术精确的自包含信息"，而非"精简到没有指引的摘要"。精简的信息会迫使 subagent 花大量时间重新读取 PRD、代码、测试来理解上下文——这正是 Agent 行动清单要解决的问题。三个级别的差异应该是**语言风格**（技术语言 vs 业务语言 vs 审计格式），而非**信息量**。
  - **Affected Scope**: src/vibe_tracing/templates/field_hints.json, src/vibe_tracing/cli.py (_format_agent_actions)
  - **Status**: ❌ 未解决 — 需要在 EVO-TASK-018 中实现三级 verbosity 架构，level1 保持信息完整性但使用技术语言

---

## 三、 原子化动作指令 (Atomic Action Tasks)

### 已解决项（存档）

- [x] **Task ID**: EVO-TASK-001
  - **Action**: MODIFY
  - **Target File**: src/vibe_tracing/cli.py
  - **Instruction**: 新增 `_format_agent_actions` 函数，输出可执行行动清单（含 AC 描述、代码片段、测试场景）
  - **AC**: vt analyze stdout 包含 GATE DECISION + ACTION 格式输出
  - **Status**: ✅ 完成

- [x] **Task ID**: EVO-TASK-002
  - **Action**: MODIFY
  - **Target File**: src/vibe_tracing/architecture_compliance_checker.py
  - **Instruction**: accepted_by 不再静默跳过，改为收集到 accepted_rules 列表
  - **AC**: traceability_report.json 包含 accepted_rules 字段
  - **Status**: ✅ 完成

- [x] **Task ID**: EVO-TASK-003
  - **Action**: MODIFY
  - **Target File**: src/vibe_tracing/tool_evidence_adapter.py
  - **Instruction**: pytest exit 5/2 返回 status=skipped 的候选而非空列表
  - **AC**: evidence_index.json 包含 status=skipped 的条目
  - **Status**: ✅ 完成

- [x] **Task ID**: EVO-TASK-004
  - **Action**: NEW
  - **Target File**: src/vibe_tracing/templates/dashboard.template.html
  - **Instruction**: 新增"待决策"标签页（业务语言+折叠证据链+交互按钮）
  - **AC**: Dashboard 显示待决策卡片，点击按钮调用 Decision API
  - **Status**: ✅ 完成

- [x] **Task ID**: EVO-TASK-005
  - **Action**: NEW
  - **Target File**: decision_server.py
  - **Instruction**: 新增 Flask Decision API（3 个端点）
  - **AC**: curl localhost:5000/api/decisions 返回 JSON
  - **Status**: ✅ 完成

- [x] **Task ID**: EVO-TASK-006
  - **Action**: MODIFY
  - **Target File**: docs/prd.md
  - **Instruction**: AC-VT-009-17 移除 --gates-only 引用
  - **AC**: PRD 不再引用 --gates-only
  - **Status**: ✅ 完成

- [x] **Task ID**: EVO-TASK-007
  - **Action**: MODIFY
  - **Target File**: src/vibe_tracing/cli.py
  - **Instruction**: 修复 _format_agent_actions 的 gate_reasons/fallback bug
  - **AC**: 门禁 BLOCKED 时行动清单显示具体行动项
  - **Status**: ✅ 完成

### 未解决项（本轮已完成）

> [!NOTE]
> 以下任务在 2026-06-08 进化轮次中全部完成。

- [x] **Task ID**: EVO-TASK-008
  - **Action**: MODIFY
  - **Target File**: tests/test_cli_analyze.py, tests/test_e2e_finalize_analyze.py
  - **Instruction**: 补充 11 个 AC 覆盖率缺口的测试（AC-VT-009-03/04/08/09/10/11/13/14/15/16/17）。每个 AC 需要至少一个测试用例验证其期望输出。
  - **AC**: vt analyze 不再报告这 11 个 AC 的覆盖率缺口
  - **Subagent**: self（每个 AC 独立调度一个 subagent）

- [x] **Task ID**: EVO-TASK-009
  - **Action**: MODIFY
  - **Target File**: src/vibe_tracing/cli.py
  - **Instruction**: 拆分 `_format_agent_actions` 函数为 5 个独立函数：`_collect_gap_actions`、`_collect_risk_actions`、`_collect_violation_actions`、`_collect_gate_reason_actions`、`_render_actions`。每个函数接收所需参数，返回 actions 列表。同时将 cli.py 中 `_format_agent_actions` 的硬编码中文消息迁移到 field_hints.json（合并 EVO-TASK-019 的 cli.py 部分），避免两个任务交叉编辑同一文件。
  - **AC**: 拆分后 vt analyze 输出不变，每个函数行数 < 50；cli.py 中不再有硬编码的行动标题/上下文中文字符串
  - **Subagent**: self

- [x] **Task ID**: EVO-TASK-010
  - **Action**: MODIFY
  - **Target File**: src/vibe_tracing/cli.py
  - **Instruction**: 在 EVO-TASK-016（D2 回滚评估）完成后执行。评估 `_format_agent_actions` 的内联上下文（_get_ac_description、_get_related_code、_get_existing_tests）的实际价值。如果 Agent 能力足够强，可以移除这些函数，简化行动清单为"问题描述+关联文件"。如果保留，需要优化性能（缓存 PRD 解析结果）。注意：如果 EVO-TASK-016 决定回滚 D2，_get_related_code 的数据来源会变化，需重新评估。
  - **AC**: vt analyze 运行时间不因行动清单格式化而显著增加（< 2s）
  - **Subagent**: research

- [x] **Task ID**: EVO-TASK-011
  - **Action**: MODIFY
  - **Target File**: .vibetracing/agent_claims.json, src/vibe_tracing/claim_evidence_analyzer.py
  - **Instruction**: 设计 claim 自动失效机制——当 claim 引用的文件被修改时，自动将 claim 标记为"需要重新验证"而非依赖手动更新时间戳。可以在 claim 中新增 `last_verified_hash` 字段，与文件当前哈希比较。
  - **AC**: 修改 cli.py 后，引用它的 claims 自动标记为 invalidated
  - **Subagent**: research

- [x] **Task ID**: EVO-TASK-012
  - **Action**: MODIFY
  - **Target File**: src/vibe_tracing/cli.py, .git/hooks/pre-commit
  - **Instruction**: 设计"当前变更 vs 预存债务"分离机制。pre-commit 阶段只检查当前 staged 文件引入的问题，预存债务在完整分析时展示但不阻断提交。可以新增 `--current-only` 标志或修改门禁逻辑。
  - **AC**: git commit 只因当前变更的问题被阻断，不因预存债务被阻断
  - **Subagent**: research

- [x] **Task ID**: EVO-TASK-013
  - **Action**: MODIFY
  - **Target File**: src/vibe_tracing/templates/dashboard.template.html, decision_server.py
  - **Instruction**: 补充决策平台端到端测试。测试 Dashboard 的 extractPendingDecisions 函数、submitDecision 函数、Decision API 的 3 个端点。可以使用 Playwright 或 Selenium 做 E2E 测试，或用 pytest + Flask test client 测试 API。
  - **AC**: 决策平台的核心流程有自动化测试覆盖
  - **Subagent**: self

- [x] **Task ID**: EVO-TASK-014
  - **Action**: MODIFY
  - **Target File**: src/vibe_tracing/templates/dashboard.template.html
  - **Instruction**: 完善 submitDecision 的本地回退——当 Decision API 不可用时，决策结果应持久化到 localStorage，刷新页面后恢复。
  - **AC**: API 不可用时点击决策按钮，刷新页面后决策状态保持
  - **Subagent**: self

- [x] **Task ID**: EVO-TASK-015
  - **Action**: MODIFY
  - **Target File**: decision_server.py
  - **Instruction**: 实现 `/api/pending` 端点——从 traceability_report.json 提取待决策项并返回。或移除此端点（如果 dashboard 已经自行从嵌入数据中提取）。
  - **AC**: /api/pending 返回有意义的待决策数据，或端点已被移除
  - **Subagent**: self

- [x] **Task ID**: EVO-TASK-016
  - **Action**: MODIFY
  - **Target File**: src/vibe_tracing/cli.py
  - **Instruction**: 评估 D2 单次加载优化的必要性。如果文件 I/O 不是性能瓶颈，考虑回滚 raw_input_loader.py 的 sha256_hash 字段和相关代码修改，恢复简单的文件读取模式。保留测试（test_input_files_loaded_once）但修改为通过其他方式验证。
  - **AC**: vt analyze 性能不受影响，代码复杂度降低
  - **Subagent**: research

- [x] **Task ID**: EVO-TASK-017
  - **Action**: MODIFY
  - **Target File**: docs/architecture_constraints.json
  - **Instruction**: 设计架构演进的显式机制——当模块调用关系需要扩展时，应该有"架构变更提案"流程（修改约束+变更日志+finalize），而非直接修改白名单。检查现有的 GATE-VT-014（架构约束变更治理门禁）是否已覆盖此场景。
  - **AC**: 架构约束变更有明确的审批流程，不依赖 Agent 直接修改
  - **Subagent**: research

- [x] **Task ID**: EVO-TASK-018a
  - **Action**: MODIFY
  - **Target File**: src/vibe_tracing/templates/field_hints.json, src/vibe_tracing/task_loader.py, src/vibe_tracing/claim_loader.py
  - **Instruction**: 重构 field_hints.json 架构 + 现有 12 条迁移 + 消费者适配。具体：
    1. 将现有 12 条扁平字符串 hint 升级为结构化对象，每条包含 level1/level2/level3 三个级别
    2. 扩展 key 命名空间，从按文档类型分组改为按消息源分组（gate_decision.*、risk.*、action.*、compliance.*、cli.*、tool.*、input.*）
    3. 现有 12 条 hint 保留为 level3 值，补写 level1 和 level2
    4. task_loader.py 和 claim_loader.py 的 `get_err_msg` 函数新增 `_resolve_hint` 适配器，支持结构化对象，向后兼容扁平字符串

    **关键设计决策**：level1（Agent 视图）不是"精简摘要"，而是"技术精确的自包含信息"。原因：一个没有对话上下文的 subagent 需要足够的信息来理解问题并采取行动，精简到没有指引的信息会迫使 subagent 花大量时间重新理解上下文。三个级别的差异是**语言风格**而非**信息量**：
    - level1（Agent）：技术语言 + 文件路径 + 行号 + 修复指令。自包含，无需额外上下文。
    - level2（人类）：业务语言 + 因果链 + 决策选项。不包含技术细节，但包含完整的业务含义。
    - level3（审计）：原始数据 + 时间戳 + 全链路。最完整，用于审计追溯。

    **hint 值格式**：
    ```json
    {
      "level1": "Claim {claim_id} 自引用违规：evidence_refs 仅指向自身，未提供外部证据。修复：在 test_refs 中添加测试文件路径，或在 evidence_refs 中添加 commit hash。",
      "level2": "Agent 声称任务完成但没有提供独立的验证证据。需要补充测试或外部确认。",
      "level3": "Claim {claim_id} (task: {related_task}) 的 evidence_refs 中包含 claim 自身路径，违反 Agent 不能自证原则。evidence_refs={evidence_refs}。建议：添加 tests/ 下的测试文件到 test_refs，或添加 commit hash 到 evidence_refs。"
    }
    ```
  - **AC**: field_hints.json 包含 12 条已有 hint 的三级版本；task_loader/claim_loader 现有测试全部通过；`get_err_msg(key, msg)` 行为不变
  - **Subagent**: self

- [x] **Task ID**: EVO-TASK-018b
  - **Action**: MODIFY
  - **Target File**: src/vibe_tracing/templates/field_hints.json
  - **Instruction**: 在 EVO-TASK-018a 完成后执行。新增 48+ 条 hint 覆盖以下模块的硬编码消息：
    - merge_gate_engine.py：12 条门禁决策消息（gate_decision.*）
    - risk_advisor.py：13 类别风险描述（risk.*），每类别含 business_impact + suggested_action
    - architecture_compliance_checker.py：10 条合规状态消息（compliance.*）
    - tool_evidence_adapter.py：5 条工具执行错误消息（tool.*）
    - cli.py 门禁函数：8 条诊断消息（cli.*）

    每条 hint 包含 level1/level2/level3 三个级别。level1 必须自包含（含文件路径、修复指令），不能精简到没有指引。
  - **AC**: field_hints.json 总计 60+ 条 hint，覆盖所有消息产生模块
  - **Subagent**: self

- [x] **Task ID**: EVO-TASK-019
  - **Action**: MODIFY
  - **Target File**: src/vibe_tracing/merge_gate_engine.py, src/vibe_tracing/risk_advisor.py, src/vibe_tracing/architecture_compliance_checker.py, src/vibe_tracing/tool_evidence_adapter.py
  - **Instruction**: 将 4 个模块中的硬编码消息迁移到 field_hints.json（cli.py 的迁移已合并到 EVO-TASK-009）。具体清单：
    - merge_gate_engine.py：12 条门禁决策消息
    - risk_advisor.py：13 类别风险描述（每类别含 business_impact + suggested_action）
    - architecture_compliance_checker.py：10 条合规状态消息
    - tool_evidence_adapter.py：5 条工具执行错误消息

    每个模块新增 `_load_hints(category)` 函数，通过 `_resolve_hint(hint_value, level)` 适配器获取对应级别的文本。消息产生函数接受 `level` 参数，默认值为 `"level1"`。4 个文件互不依赖，可并行调度。
  - **AC**: 4 个模块中不再有硬编码的中文消息字符串；所有消息通过 field_hints.json 查找
  - **Subagent**: self（4 个文件并行调度，每个文件一个 subagent）

- [x] **Task ID**: EVO-TASK-020
  - **Action**: MODIFY
  - **Target File**: src/vibe_tracing/task_loader.py, src/vibe_tracing/claim_loader.py
  - **Instruction**: 适配现有消费者使用三级 verbosity。当前的 `get_err_msg` 函数只支持扁平字符串，需要升级为支持结构化对象。新增 `_resolve_hint(hint_value, level)` 适配器函数：
    ```python
    def _resolve_hint(hint_value, level="level3"):
        if isinstance(hint_value, str):
            return hint_value  # 向后兼容：旧格式视为 level3
        return hint_value.get(level, hint_value.get("level3", ""))
    ```
    `get_err_msg` 新增可选 `level` 参数，默认 `"level3"`（保持现有行为不变）。
  - **AC**: 现有测试全部通过；`get_err_msg(key, msg)` 行为不变；`get_err_msg(key, msg, level="level1")` 返回精简文本
  - **Subagent**: self

- [x] **Task ID**: EVO-TASK-021
  - **Action**: MODIFY
  - **Target File**: src/vibe_tracing/cli.py
  - **Instruction**: Agent 行动清单使用 level1 hints。`_format_agent_actions` 中所有硬编码的行动标题和上下文文本改为从 field_hints.json 查找 level1 值。行动清单的输出格式保持不变，但文本内容由 hints 驱动。
  - **AC**: vt analyze 的行动清单输出文本与 field_hints.json 中的 level1 值一致
  - **Subagent**: self

- [x] **Task ID**: EVO-TASK-022
  - **Action**: MODIFY
  - **Target File**: src/vibe_tracing/templates/dashboard.template.html, src/vibe_tracing/dashboard_renderer.py
  - **Instruction**: Dashboard 决策卡片使用 level2 hints。`extractPendingDecisions` JavaScript 函数中的硬编码业务语言文本改为从嵌入的 hints 数据中查找 level2 值。dashboard_renderer.py 在生成 HTML 时将 field_hints.json 的 level2 值嵌入到页面数据中。
  - **AC**: Dashboard 决策卡片显示的文本与 field_hints.json 中的 level2 值一致
  - **Subagent**: self

---

## 四、 关联与依赖

```
EVO-TASK-008  (AC 覆盖率) ← 阻断门禁，优先级最高
EVO-TASK-009  (函数拆分 + cli.py 消息迁移) ← 合并了 EVO-TASK-019 的 cli.py 部分
EVO-TASK-010  (内联评估) ← 依赖 EVO-TASK-016
EVO-TASK-011  (claim 失效) ← 独立
EVO-TASK-012  (变更分离) ← 解决"门禁摩擦"核心问题
EVO-TASK-013  (E2E 测试) ← 独立
EVO-TASK-014  (本地持久化) ← 独立
EVO-TASK-015  (pending 端点) ← 独立
EVO-TASK-016  (D2 回滚评估) ← 先于 EVO-TASK-010
EVO-TASK-017  (架构演进机制) ← 与 EVO-TASK-016 关联
EVO-TASK-018a (hints 架构 + 现有迁移 + 消费者适配) ← 基础设施
EVO-TASK-018b (新增 48+ 条 hint) ← 依赖 EVO-TASK-018a
EVO-TASK-019  (4 模块消息迁移) ← 依赖 EVO-TASK-018b，4 文件并行
EVO-TASK-020  (task/claim 消费者适配) ← 已合并到 EVO-TASK-018a
EVO-TASK-021  (Agent 行动清单用 level1) ← 依赖 EVO-TASK-018b/019
EVO-TASK-022  (Dashboard 用 level2) ← 依赖 EVO-TASK-018b/019
```

**建议执行顺序**：
1. EVO-TASK-008（AC 覆盖率，解除门禁阻断）
2. EVO-TASK-012（变更分离，解决门禁摩擦）
3. EVO-TASK-016（D2 回滚评估，先于 010）
4. EVO-TASK-018a（hints 架构 + 现有 12 条迁移 + 消费者适配）
5. EVO-TASK-018b（新增 48+ 条 hint 编写）
6. EVO-TASK-009 + 019（函数拆分 + 4 模块消息迁移，可并行，不同文件）
7. EVO-TASK-021 + 022（Agent/Dashboard 接入 hints，可并行）
8. EVO-TASK-010（内联评估，在 016 之后）
9. EVO-TASK-011/013/014/015/017（完善和清理）
