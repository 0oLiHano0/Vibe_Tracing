# Claude Code 自举配置 (Claude Code Bootstrap Configurations)

本目录包含 Vibe Tracing 在 Claude Code 运行时环境中执行时的自举与治理配置文件。

## 目录结构
- `bootstrap_manifest.json`：自举主清单，声明了目标运行时、被批准的子 Agent、允许的工具技能（Skills）、禁止的行为以及期望的治理输出。
- `subagents/`：子 Agent 角色定义、允许的技能以及行为约束。
  - `researcher.json`：定义了 `SUBAGENT-VT-001`（代码库调研员）。
  - `developer.json`：定义了 `SUBAGENT-VT-002`（代码开发者）。
- `skills/`：各具体工具/动作的调用边界和参数约束。
  - `view_file.json`：读取工作区文件内容（对应技能 `SKILL-VT-001`）。
  - `edit_file.json`：修改或创建工作区文件内容（对应技能 `SKILL-VT-002`）。

## Schema 治理与校验
本目录下的所有配置文件均由 Vibe Tracing Core 核心引擎，对照 `schemas/` 目录中定义的 Draft-07 JSON Schema 进行强类型格式校验：
- `bootstrap_manifest.json` -> `claude_bootstrap_manifest.schema.json`
- `subagents/*.json` -> `claude_subagent_definition.schema.json`
- `skills/*.json` -> `claude_skill_definition.schema.json`
