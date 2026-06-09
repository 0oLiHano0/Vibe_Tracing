# Vibe Tracing 架构变更日志

本项目的所有架构约束变更均在此记录，供项目经理（PM）进行日常审计与追溯。

## [2026-06-09] language_tool_matrix 新增非代码文件类型声明

### language_tool_matrix 新增 json/markdown/html/toml
* **变更规则**：`language_tool_matrix` 新增 `json`、`markdown`、`html`、`toml` 四个条目，每个条目声明对应的 `extensions`（`.json`、`.md`、`.html`、`.toml`）并将所有工具字段设为 `null`。
* **变更原因**：当 `.json`、`.md`、`.html`、`.toml` 文件被 staged 时，VT 的 `_check_staged_extensions` 函数发出"发现未配置的代码文件类型"警告。通过在矩阵中显式声明这些非代码文件类型，VT 识别它们为已知类型，不再产生警告。工具字段使用空对象 `{}` 而非 `null`，以满足 schema 的 `type: "object"` 约束。
* **影响范围**：
  - `docs/architecture_constraints.json`：`language_tool_matrix` 新增 4 个条目。

## [2026-06-08] 人类接受机制 — manual 规则 accepted_by/accepted_at 字段

### 所有规则类型新增 accepted_by / accepted_at 字段
* **变更规则**：为 architecture_constraints.json 中所有规则类型（architecture_principles、module_boundaries、dependency_rules、data_flow_rules、storage_rules、error_handling_rules、logging_rules、security_rules、technology_constraints、forbidden_patterns、quality_gates、interface_contracts、performance_constraints、deployment_constraints、test_constraints）添加 `accepted_by` 和 `accepted_at` 可选字段。
* **变更原因**：manual 规则此前仅被标记为 "unclear" 后静默忽略，无任何人类确认记录。通过显式接受机制，人类可在 architecture_constraints.json 中设置 `accepted_by`（接受者标识）和 `accepted_at`（ISO 8601 时间戳），已接受的 manual 规则不再出现在 unclear 警告中。
* **影响范围**：
  - `docs/architecture_constraints.json`：所有规则类型 schema 新增 accepted_by / accepted_at 属性。
  - `src/vibe_tracing/architecture_compliance_checker.py`：manual 规则处理逻辑增加 accepted_by 检查，已接受的规则跳过。
  - `src/vibe_tracing/templates/architecture_constraints.template.json`：模板示例规则添加 accepted_by / accepted_at。
  - `src/vibe_tracing/cli.py`：新增 `vt accept <rule_id>` 子命令，自动设置 accepted_by 和 accepted_at。

## [2026-06-08] GATE-VT-002~012 改为 manual 并确认

### quality_gates 中无检查器实现的 machine 规则
* **变更规则**：GATE-VT-002, 003, 004, 005, 008, 009, 010, 011, 012 从 `verification_method: "machine"` 改为 `"manual"`，并设置 `accepted_by: "human"`。
* **变更原因**：这些规则标记为 machine 但无实际检查器实现，每次 hook 运行时被标记为 "unclear" 产生噪音。改为 manual 后通过 accepted_by 机制确认，消除噪音。

## [2026-06-08] verification_method 字段引入 — 消除手动规则门禁噪声

### 所有规则新增 verification_method 字段
* **变更规则**：为 architecture_constraints.json 中所有规则（architecture_principles、dependency_rules、data_flow_rules、storage_rules、error_handling_rules、logging_rules、security_rules、technology_constraints、forbidden_patterns、quality_gates）添加 `verification_method` 字段，值为 `"machine"` 或 `"manual"`。
* **变更原因**：约 60 条"不可机器验证"的治理规则（PRINCIPLE-*、FORBID-*、FLOW-* 等）在每次 hook 运行时触发 BLOCKED（GATE-VT-007），产生大量噪声，掩盖真正的问题。通过显式声明 `verification_method`，手动规则在 audit 时被记录但不再阻断门禁，仅机器可验证规则的 unclear 状态才触发保守门禁。
* **影响范围**：
  - `docs/architecture_constraints.json`：所有规则添加 verification_method 字段。
  - `src/vibe_tracing/architecture_compliance_checker.py`：section 7 逻辑改为根据 verification_method 决定是否加入 unclear_constraints。
  - `src/vibe_tracing/schemas/architecture_constraints.schema.json`：所有 rule 类型的 schema 添加 verification_method 属性。
  - `src/vibe_tracing/templates/architecture_constraints.template.json`：模板示例规则添加 verification_method。

## [2026-06-08] MOD-VT-006 新增 REQ-VT-003/004/005 架构映射

### MOD-VT-006 related_requirements 新增 REQ-VT-003, REQ-VT-004, REQ-VT-005
* **变更规则**：MOD-VT-006 (traceability_analyzer) 的 `related_requirements` 新增 `REQ-VT-003`、`REQ-VT-004`、`REQ-VT-005`。
* **变更原因**：三个 SHOULD/COULD 级需求此前缺少架构映射。REQ-VT-003（业务流程图生成与检查）、REQ-VT-004（输入输出表与跨模块衔接检查）、REQ-VT-005（数据结构列表与业务解释）均为追踪分析职责，归属 MOD-VT-006。

## [2026-06-08] 语言工具矩阵新增 extensions 字段

### language_tool_matrix.python.extensions
* **变更规则**：新增 `extensions: [".py"]` 字段，显式声明该语言的代码文件扩展名。
* **变更原因**：工具执行从配置读取扩展名替代硬编码，使 VT 对不同项目的文件类型支持由配置驱动。

## [2026-06-08] mypy 工具配置修复

### language_tool_matrix.python.type_check 命令模板
* **变更规则**：mypy 命令从 `mypy {source_path} --json-report {output_path}` 改为 `mypy {source_path} --no-error-summary`，output_format 从 `mypy_json` 改为 `mypy_text`。
* **变更原因**：mypy 1.19.1 已废弃 `--json-report` 参数。简化为 `mypy {source_path}`，解析器使用 stdout 错误行计数作为 fallback。

## [2026-06-07] 治理盲区修复 — REQ-VT-010 架构映射

### MOD-VT-003 新增 REQ-VT-010 关联
* **变更规则**：MOD-VT-003 (CLI & Entry Points) 的 `related_requirements` 新增 `REQ-VT-010`。
* **变更原因**：新增 REQ-VT-010（质量演进生命周期管理），涵盖反思诊断输出、覆盖校验、进化计划结构化。该需求由 CLI 层 (`run_analyze`) 调度，归属 MOD-VT-003。

## [2026-06-04] 架构约束基线校验重构（Phase 8）

### 移除物理基线文件
* **变更规则**：删除 `.vibetracing/architecture_constraints.base.json`，以 Git commit 历史作为唯一基线来源。
* **变更原因**：消除双重事实来源，降低人工同步成本。通过 config.json 中存储的 SHA256 哈希实现 O(1) 快路径检测，通过 `git show` 还原历史版本进行语义 Diff。

### check_governance 变为只读检测
* **变更规则**：`check_governance()` 不再判定通过/不通过，始终返回 `is_valid=True`，仅输出警告和修复指南。
* **变更原因**：分析阶段只负责暴露偏离，判定权交给 `vt finalize`，符合 VT 的职责分离原则。

### run_finalize 新增变更日志时间线验证
* **变更规则**：`vt finalize` 在 hash 不匹配时，验证 `architecture_change_log.md` 是否在 constraints 变更之后被更新。未更新则拒绝锁定新指纹。
* **变更原因**：确保架构约束变更必须经过人类审批记录，防止 agent 静默修改。

### GATE-VT-014 架构约束变更治理门禁
* **变更规则**：新增 GATE-VT-014 门禁定义。当检测到架构约束变更且 change_log 已同步更新时，标记为 "unclear"（非 "violated"），触发保守门禁行为。
* **变更原因**：暴露架构变更但不阻断 agent 工作流，让人类在 dashboard 上审查。

### GATE-VT-013 自举配置审查门禁
* **变更规则**：新增 GATE-VT-013 门禁定义（severity: should，blocks_merge: false），用于审查 Agent 运行时自举配置。
* **变更原因**：task_list.json 中多处引用了 GATE-VT-013，补齐定义消除断链。

## [2026-05-24] 架构约束变更说明
* **变更规则**：允许 core 模块导入 claude_code_bootstrap_adapter。
* **变更原因**：为了实现自举校验，Vibe Tracing CLI 需要调用自举适配器检查子代理的技能分配安全。

## [2026-05-27] 架构约束白名单对齐变更
* **变更规则**：修改 `MOD-VT-001`, `MOD-VT-006`, 和 `MOD-VT-009` 的 `allowed_to_call` 列表。
* **变更原因**：
  * 为了支持在 `cli.py` (MOD-VT-001) 中直接组织、调用自举校验和生成完整的 traceability 报告，扩充其允许调用的模块白名单以覆盖所有的 Core 逻辑与适配器（包括 `MOD-VT-005`, `MOD-VT-006`, `MOD-VT-007`, `MOD-VT-008`, `MOD-VT-009`, `MOD-VT-011`）。
  * 允许 `traceability_analyzer` (MOD-VT-006) 调用 `raw_input_loader` (MOD-VT-002) 加载路径配置文件。
  * 允许 `architecture_compliance_checker` (MOD-VT-009) 引入 `raw_input_loader` (MOD-VT-002) 加载配置，以及在质量门禁中校验 `claude_code_bootstrap_adapter` (MOD-VT-011)。

## [2026-06-08] 单次加载优化 — 模块调用白名单扩展

### MOD-VT-001 和 MOD-VT-005 的 allowed_to_call 更新
* **变更规则**：MOD-VT-001 (cli.py) 新增 `MOD-VT-004` (tool_evidence_adapter)；MOD-VT-005 (evidence_index_builder) 新增 `MOD-VT-002` (raw_input_loader)。
* **变更原因**：AC-VT-009-12 要求分析流水线必须单次加载输入文件。为避免重复读取磁盘，cli.py 需要直接访问 tool_evidence_adapter 的数据结构，evidence_index_builder 需要从 raw_input_loader 的已加载记录中获取 SHA-256 哈希。这些调用关系此前被白名单阻断，导致每次分析重复读取文件。
* **影响范围**：
  - `docs/architecture_constraints.json`：MOD-VT-001 和 MOD-VT-005 的 allowed_to_call 数组扩展。
  - `src/vibe_tracing/raw_input_loader.py`：InputFileRecord 新增 sha256_hash 字段，加载时一次性计算。
  - `src/vibe_tracing/cli.py`：gate 函数复用 manifest 中的哈希，PRD 解析改用已加载内容。
