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
    *   `architecture_constraints` 的基线状态现在通过 Git 历史自动追溯，不再依赖物理基线文件。
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

---

## 5. 统一编号规范与使用规程 (Unified ID Specifications and Usage Protocols)

为了确保各阶段产物（需求、设计、任务、代码、测试、声明）之间能够被 VT 引擎全自动追溯与校验，项目全生命周期所有实体均必须使用严格的编号（ID）进行管理。

### 5.1 ID 编号格式定义

| 编号前缀 | 正则表达式模式 | 典型示例 | 定义位置 | 编号含义与作用 |
| :--- | :--- | :--- | :--- | :--- |
| **`PROJECT`** | `^PROJECT-VT$` | `PROJECT-VT` | `task_list.json` | 项目唯一标识符，用于区分受管理的项目。 |
| **`PHASE`** | `^PHASE-VT-\d+$` | `PHASE-VT-002` | `task_list.json` | 开发阶段/里程碑编号，用于对开发任务分类。 |
| **`REQ`** | `^REQ-VT-\d+$` | `REQ-VT-001` | `prd.md` | 产品需求编号，定义业务层面的独立功能域。 |
| **`AC`** | `^AC-VT-\d+-\d+$` | `AC-VT-001-01` | `prd.md` | 验收标准编号，隶属于对应需求。第一段为 REQ 序号。 |
| **`MOD`** | `^MOD-VT-\d+$` | `MOD-VT-002` | `architecture_constraints.json` | 模块架构编号，对应物理模块或逻辑层级。 |
| **`TASK`** | `^TASK-VT-\d+$` | `TASK-VT-005` | `task_list.json` | 原子开发任务编号，最小开发单元。 |
| **`DOD`** | `^DOD-VT-\d+-\d+$` | `DOD-VT-005-01` | `task_list.json` | 完成定义编号，隶属于对应任务。第一段为 TASK 序号。 |
| **`CLAIM`** | `^CLAIM-VT-\d+$` | `CLAIM-VT-005` | `agent_claims.json` | 代理完成声明自证编号，推荐与关联任务 ID 一致。 |
| **`EVIDENCE`** | `^EVIDENCE-VT-\d+$` | `EVIDENCE-VT-001` | `evidence_index.json` | 编译证据编号，由引擎在分析时动态生成。 |
| **`RISK`** | `^RISK-VT-\d+$` | `traceability_report.json` | 风险判定编号，由引擎检测异常时生成。 |
| **`GATE`** | `^GATE-VT-\d+$` | `GATE-VT-001` | `architecture_constraints.json` | 质量门禁红线编号，不可违反的硬性合并拦截规则。 |
| **`FORBID`** | `^FORBID-VT-\d+$` | `FORBID-VT-001` | `architecture_constraints.json` | 禁用规约编号，禁止调用的库、代码或外部资源。 |
| **`PRINCIPLE`** | `^PRINCIPLE-VT-\d+$` | `PRINCIPLE-VT-001` | `architecture_constraints.json` | 架构设计原则，非机器可验证的软性手动评审共识。 |

### 5.2 编号变更决策树与使用规程

当项目发生演进、重构或修补时，Agent 必须根据下表判定何时新增或修改何种编号，严禁乱用 ID 类型：

| 变更场景 | 治理行为 / 编号操作 | 使用决策 rationale 与规范要求 |
| :--- | :--- | :--- |
| **细化或演进现有功能需求**<br>*(e.g., 增强 Raw Loader 支持同名 NodeID 判定逻辑)* | 新增验收标准 **`AC-VT-xxx-yy`**<br>(例如新增 `AC-VT-002-04`) | **为什么不用新 REQ**：这仍然属于原有功能域 `REQ-VT-002`（证据校验）的增强与演进，不需要创建独立的新业务需求。<br>**约束**：必须定义在其父级 `REQ-VT-xxx` 段落下方，ID 第一段必须与父级需求一致。 |
| **规划落实具体 AC 的开发任务** | 新建开发任务 **`TASK-VT-xxx`** 及其下属完成定义 **`DOD-VT-xxx-yy`** | **为什么**：每一个 AC 的实现必须有对应的 TASK 和 DoD 承载。DoD 细化测试和交付物要求。<br>**约束**：Task 内的 `related_acceptance_criteria` 必须包含该 AC 编号，从而建立需求到开发任务的映射。 |
| **引入独立全新的产品大特性/子系统**<br>*(e.g., 新增基于 AI 的代码自动 Review 模块)* | 新建产品需求 **`REQ-VT-zzz`** 及其下属的一组 **`AC`** 编号 | **为什么**：新特性超出了现有的任何功能需求域，是完全独立的新需求类别。 |
| **规范代码目录划分、层级调用限制或禁用库**<br>*(e.g., 禁止 CLI 模块直接调用底层 Analyzer 工具)* | 在架构约束中新增 **`GATE-VT-*`**、**`FORBID-VT-*`** 或修改 **`MOD-VT-*`** 关系 | **为什么**：涉及工程底线、依赖依赖图谱与安全禁区，属于全局性的架构红线设计。 |
