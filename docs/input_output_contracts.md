# Vibe Tracing: 输入与输出契约 (Input and Output Contracts)

本文档明确规定了构成 Vibe Tracing 治理契约的目录布局、数据 Schema、状态语义以及合并门禁决策。

## 1. 目录结构契约 (Directory Structure Contract)

Vibe Tracing 运作于清晰划分的配置与治理路径之上，允许项目通过 `.vibetracing/config.json` 显式指定文件的物理存放路径。以下为标准规范布局：

*   **`/docs/`**：包含项目规格与开发规范文档（供人类与 AI Agent 共同阅读）。
    *   `prd.md`：包含业务需求（`REQ-VT-*`）和验收标准（`AC-VT-*-*`）的 Markdown 格式产品需求文档。
    *   `architecture_constraints.json`：约束代码库结构和模块依赖的核心规则与校验配置。
    *   `task_list.json`：开发任务与交付（DoD）条目的结构化清单。
    *   `architecture_change_log.md`：记录架构约束演进的历史与合理性说明的自然语言日志。
*   **`/.vibetracing/`**：VT 引擎的专属沙箱运行目录（通常被加入到 `.gitignore` 中以防止频繁干扰提交）。
    *   `config.json`：核心配置文件，显式定义项目文件到 VT 引擎的映射路径。
    *   `agent_claims.json`：AI 代理填报的开发事实自证声明审计账本。
    *   `architecture_constraints.base.json`：由人类审批通过的架构约束基线文件（用于比对架构漂移）。
    *   `claude_bootstrap/`：Claude Code 自举环境的权限、子代理与技能配置。
    *   `tool_reports/`：存放开发工具（如 `pytest_report.json`、`coverage.json`、`ruff_report.json` 等）在分析前输出的原始报告文件。
    *   `output/`：在 `vibe-tracing analyze` 分析流中自动生成的审计产物目录，包含：
        *   `evidence_index.json`：汇总并规范化后的所有证据项索引。
        *   `traceability_report.json`：最终生成的评估报告，包含需求覆盖分析、缺口（Gaps）、风险（Risks）和门禁裁决决定（Gate Decisions）。
        *   `dashboard.html`：支持离线直接打开、内嵌数据的单体可视化 Dashboard 面板。
        *   `run_metadata.json`：分析运行元数据，包含本次运行的统计数据和输入输出路径。

---

## 2. 覆盖与合规状态语义 (Coverage and Compliance Status Semantics)

Vibe Tracing 使用一组标准化的状态来评估各追踪节点的覆盖和合规性：

| 状态值 | 含义 | 对应的治理动作 |
| --- | --- | --- |
| **`covered`** | 所有要求的要素（如任务或测试）已完全实现，且测试通过。 | 允许通过 / 合规 |
| **`partial`** | 要素存在但有限制，或者关联的测试套件未完全通过。 | 产生治理警告或 SHOULD 风险 |
| **`missing`** | 目标项目未提供任何证据或下属任务。 | 产生 GAP 缺口；若为 MUST 项则直接拦截 |
| **`unclear`** | 缺失必要的元数据、未声明优先级或验证结果不明确。 | 保守评估，等同于校验失败 |
| **`low_confidence`**| 证据存在，但其真实性或与目标的关联可信度较低/可疑。 | 产生治理警告风险 |
| **`blocked`** | 校验过程被构建或第三方工具运行报错完全阻断。 | 直接封锁门禁决定 |
| **`compliant`** | 静态架构约束或 Agent 自证声明经核实符合规则。 | 允许通过 |
| **`violated`** | 明确违反了硬性架构约束。| 直接封锁门禁决定 |

---

## 3. 合并门禁裁决与命令行退出码 (Merge Gate Decisions and Exit Codes)

在运行 `vibe-tracing analyze` 时，引擎评估所收集的所有证据并对分支是否能够被安全合并进行裁决。输出结果映射如下：

- **`pass`** (退出码 `0`)：所有 MUST 级需求与验收标准都已覆盖，静态架构红线检查 compliant，且不存在任何 MUST 级高危风险。分支被允许合并。
- **`fail`** (退出码 `0`)：有条件允许。虽无 MUST 级红线被违反，但存在次要警告、SHOULD/COULD 级 Gap 缺口，或是存在机器不可验证的软性规则（例如 `GATE-VT-007`）。系统建议人工介入 Review，但流水线不会被硬性拦截。
- **`blocked`** (退出码 `2`)：检测到严重的合规性缺陷（例如必需的治理文件缺失、MUST 级测试运行失败、存在架构违规，或自证 Claim 证据为空等）。合并分支被硬性拦截。
- **`error`** (退出码 `1`)：工具执行报错、Schema 校验未通过，或文件加载失败。检查流自身未能正确运行。

---

## 4. 人机决策权分离原则 (Human Decision Separation)

Vibe Tracing 严格执行**系统门禁决策**与**人类最终决策**的分离：
- 生成的 `traceability_report.json` 和 `dashboard.html` 只客观记录事实、建议和风险评估。
- 它们**不包含**人类签名，也不代表自动通过合并分支。
- 必须要有人类项目经理或架构师在对有条件的 `fail` 决定和警告进行人工 Review 确认后，才能手动在代码库发布流水线中执行正式部署。
