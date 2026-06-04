# Vibe Tracing 架构变更日志

本项目的所有架构约束变更均在此记录，供项目经理（PM）进行日常审计与追溯。

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
