# Claude Code 自举与治理 (Claude Code Self-Bootstrapping & Governance)

本文档描述了 Vibe Tracing 在开发生命周期中，如何将 Claude Code 作为其首选 Agent 运行环境，同时保持运行时隔离与架构合规性。

## 1. 运行时隔离原则 (Runtime Isolation Principles)

Vibe Tracing 核心模块（Core）必须保持与 AI 代理执行器严格独立：

- **无强依赖**：核心代码库（`vibe_tracing`）是纯 Python 代码，绝对不能导入或引用任何特定于 Claude Code 的包或 API。
- **CLI 命令行接口**：AI 代理与 Vibe Tracing 治理系统的所有交互，都必须通过对 `vibe-tracing` 命令行工具的 Shell 调用来完成。
- **可移植性**：此设计确保了通过实现对应的自举适配层，可以在未来将 Claude Code 无缝替换为任何其他 Agent 运行环境（如 Aider, AutoGPT）。

---

## 2. 子 Agent 与工具技能分离 (Subagents and Skills Separation)

为了防止 AI 代理自我证明（"self-attesting"）或做出越权行为，自举配置对子 Agent 的角色和能力进行了隔离：

- **子 Agent (Subagents)**：拥有特定 Prompt、允许的行为规范和狭窄职责范围的代理配置（例如：`researcher` 调研员，`developer` 开发者）。
- **工具技能 (Skills)**：子 Agent 被授权使用的特定 Shell 命令或 API 工具（例如：`view_file` 读文件，`edit_file` 改文件）。

所有的子 Agent 和 Skill 定义都以 JSON 文件的形式保存在 `claude_bootstrap/` 目录下，便于机器读取、静态校验并纳入版本控制。

---

## 3. 自举清单 (The Bootstrap Manifest)

`claude_bootstrap/bootstrap_manifest.json` 作为代理执行环境的统一入口，声明了以下内容：
1. 目标运行环境版本 (`claude-code`)。
2. 被批准的子 Agent 列表及其定义文件。
3. 被批准的工具技能列表及其定义文件。
4. 禁止的行为（如：在工作区外执行命令，或与未经授权的端点进行通信）。
5. 期望产出的结构化治理证据。

---

## 4. 架构变更提案（提案胜于静默修改）(Proposals over Silent Edits)

为了避免对质量门禁和设计原则进行未经授权的篡改：

- **禁止静默修改**：严禁子 Agent 直接修改 `architecture_constraints.json`（架构约束文件）。
- **变更提案**：如果 Agent 建议增加、修改或删除某项架构约束，必须在 `docs/architecture_change_log.md` 路径下记录相应的自然语言变更说明。
- **人类审批**：由人类项目经理根据自然语言的变更说明进行允许或拒绝的决策。
- **静默修改检测**：合规校验器如果检测到 `architecture_constraints.json` 发生了漂移/变更，但在 `docs/architecture_change_log.md` 中没有对应的已登记变更说明，将立即引发 MUST 级风险并拦截门禁。
