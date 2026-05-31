# Vibe Tracing 架构变更日志

本项目的所有架构约束变更均在此记录，供项目经理（PM）进行日常审计与追溯。

## [2026-05-24] 架构约束变更说明
* **变更规则**：允许 core 模块导入 claude_code_bootstrap_adapter。
* **变更原因**：为了实现自举校验，Vibe Tracing CLI 需要调用自举适配器检查子代理的技能分配安全。

## [2026-05-27] 架构约束白名单对齐变更
* **变更规则**：修改 `MOD-VT-001`, `MOD-VT-006`, 和 `MOD-VT-009` 的 `allowed_to_call` 列表。
* **变更原因**：
  * 为了支持在 `cli.py` (MOD-VT-001) 中直接组织、调用自举校验和生成完整的 traceability 报告，扩充其允许调用的模块白名单以覆盖所有的 Core 逻辑与适配器（包括 `MOD-VT-005`, `MOD-VT-006`, `MOD-VT-007`, `MOD-VT-008`, `MOD-VT-009`, `MOD-VT-011`）。
  * 允许 `traceability_analyzer` (MOD-VT-006) 调用 `raw_input_loader` (MOD-VT-002) 加载路径配置文件。
  * 允许 `architecture_compliance_checker` (MOD-VT-009) 引入 `raw_input_loader` (MOD-VT-002) 加载配置，以及在质量门禁中校验 `claude_code_bootstrap_adapter` (MOD-VT-011)。
