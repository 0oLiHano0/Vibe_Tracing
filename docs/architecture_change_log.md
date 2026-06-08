# Vibe Tracing 架构变更日志

本项目的所有架构约束变更均在此记录，供项目经理（PM）进行日常审计与追溯。

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
