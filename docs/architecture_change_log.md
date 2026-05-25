# Vibe Tracing 架构变更日志

本项目的所有架构约束变更均在此记录，供项目经理（PM）进行日常审计与追溯。

## [2026-05-24] 架构约束变更说明
* **变更规则**：允许 core 模块导入 claude_code_bootstrap_adapter。
* **变更原因**：为了实现自举校验，Vibe Tracing CLI 需要调用自举适配器检查子代理的技能分配安全。
