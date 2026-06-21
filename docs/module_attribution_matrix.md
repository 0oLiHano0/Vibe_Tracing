# 模块归属矩阵

> 本文档定义 VT 各模块的流水线归属、职责边界和重构优先级。
> 目标：消除"谁调用谁"的歧义，为逐模块重构提供执行依据。

---

## 一、概述

### 流水线条数

VT 有 **2 条流水线**，不是 3 条：

| 流水线 | 入口命令 | 职责 |
|---|---|---|
| **finalize** | `vt finalize` | 锁定设计基线（PRD + Architecture Constraints 双哈希） |
| **analyze** | `vt analyze` | 校验代码/测试/claims 与设计基线的一致性 |

**为什么 dashboard 不是独立流水线**：Dashboard 是 analyze 流水线的输出层（`dashboard_renderer.py`），不是一个独立的执行路径。它消费 analyze 流水线产出的数据，渲染终端报告。把 dashboard 单独算流水线会导致模块归属混乱——analyze 的 domain 层会错误地被标记为"dashboard 专属"。

### 设计决策

1. **CLI 层只做调度**：`pipeline.py` 决定"什么时候调用谁"，不包含业务逻辑。
2. **Domain 层不直接读文件**：所有文件 I/O 由 CLI 层完成，domain 函数接收已解析的数据结构。
3. **Domain 层不直接调 db.py**：`pipeline.py` 负责创建连接并传入，domain 函数接收 `conn` 参数。
4. **Infra 层是叶子节点**：不依赖 domain 或 cli，只依赖标准库。

---

## 二、模块归属矩阵

### Finalize 流水线

| 模块 | 路径 | 职责 | 行数 |
|---|---|---|---|
| **pipeline 调度** | `cli/finalize.py` | 哈希计算、PRD↔Arch 映射校验、config 写入、git 操作 | 384 |
| **原始输入加载** | `domain/raw_input_loader.py` | 读取 PRD + constraints + config + claims + task 文件 | 233 |
| **PRD 解析** | `domain/prd_parser.py` | 解析 prd.md，提取 REQ/AC 结构 | 386 |
| **PRD↔Arch 映射校验** | `domain/prd_arch_validator.py` | 校验 PRD 中的 REQ 是否在 constraints 中有对应模块 | 177 |

**调用链**：`main.py` → `finalize.py` → `raw_input_loader.py` + `prd_parser.py` + `prd_arch_validator.py`

---

### Analyze 流水线

#### CLI 调度层

| 模块 | 路径 | 职责 | 行数 |
|---|---|---|---|
| **pipeline** | `cli/analyze/pipeline.py` | 9 阶段编排：加载→门禁→DB→工具→灌入→证据→分析器→判定→退出码 | 510 |
| **gates** | `cli/analyze/gates.py` | Gate 2 前置条件：幽灵代码检测、staged 文件扩展名检查 | 182 |
| **tools** | `cli/analyze/tools.py` | 工具执行：linter/formatter/test/coverage 调度 | 258 |
| **reports** | `cli/analyze/reports.py` | 报告生成：coverage 摘要、AC 映射、req 映射 | 203 |
| **output** | `cli/analyze/output.py` | 终端输出：渲染最终报告到 stdout | 166 |
| **formatting** | `cli/analyze/formatting.py` | 动作格式化：收集 gap/risk/violation 动作项 | 129 |
| **actions** | `cli/analyze/actions.py` | 动作收集：从分析结果中提取可执行的改进动作 | 244 |
| **helpers** | `cli/analyze/helpers.py` | 辅助函数：共用工具函数 | 129 |
| **common** | `cli/common.py` | 共享工具：上下文加载、staged 文件获取、受影响项计算 | 236 |

**调用链**：`main.py` → `pipeline.py` → `gates.py` + `tools.py` + `reports.py` + `output.py` + `formatting.py` + `actions.py` + `helpers.py` + `common.py`

#### 待删除模块

| 模块 | 路径 | 状态 | 说明 |
|---|---|---|---|
| **analysis** | `cli/analyze/analysis.py` | **待删除** | 153 行，已被 `pipeline.py` 合并，残留代码应清除 |

---

### 领域层（被 analyze 和 dashboard 共同消费）

| 模块 | 路径 | 职责 | 行数 | 消费方 |
|---|---|---|---|---|
| **context** | `domain/context.py` | 统一上下文数据结构，所有解析结果的单一来源 | 39 | analyze, dashboard |
| **evidence_builder** | `domain/evidence_builder.py` | 证据构建：从 DB 查询关联数据，组装证据链 | 78 | analyze |
| **merge_gate_engine** | `domain/merge_gate_engine.py` | 门禁判定：gap/risk/compliance 三道门禁的决策逻辑 | 629 | analyze |
| **ghost_code_reconciler** | `domain/ghost_code_reconciler.py` | 幽灵代码检测：staged 代码 vs staged claims 的比对 | 283 | analyze |
| **architecture_compliance_checker** | `domain/architecture_compliance_checker.py` | 架构合规检查：import 边界、模块依赖规则 | 886 | analyze |
| **risk_advisor** | `domain/risk_advisor.py` | 风险建议：从 gaps/violations 生成风险项 | 218 | analyze |
| **tool_evidence_adapter** | `domain/tool_evidence_adapter.py` | 工具证据适配：执行测试工具、解析输出、存储结果 | 1119 | analyze |
| **claim_loader** | `domain/claim_loader.py` | Claim 加载：解析 claims/current.json | 166 | analyze |
| **task_loader** | `domain/task_loader.py` | Task 加载：解析 task_list.json | 329 | analyze |
| **prd_parser** | `domain/prd_parser.py` | PRD 解析：解析 prd.md | 386 | analyze, finalize |
| **raw_input_loader** | `domain/raw_input_loader.py` | 原始输入加载：读取所有文件 | 233 | analyze, finalize |
| **prd_arch_validator** | `domain/prd_arch_validator.py` | PRD↔Arch 映射校验 | 177 | finalize |
| **dashboard_renderer** | `domain/dashboard_renderer.py` | Dashboard 渲染：组装终端报告数据 | 115 | dashboard 输出 |
| **reflection_prompts** | `domain/reflection_prompts.py` | 反思提示：生成 8 项反思问题 | 218 | analyze |
| **traceability_report_builder** | `domain/traceability_report_builder.py` | 追溯报告构建：生成 REQ→Task→Claim→Test 追溯表 | 64 | analyze |
| **architecture_change_proposal** | `domain/architecture_change_proposal.py` | 架构变更建议：生成变更提案 | 355 | analyze |

---

### 独立入口

| 模块 | 路径 | 职责 | 行数 |
|---|---|---|---|
| **main** | `cli/main.py` | CLI 调度：argparse 定义、命令路由、日志初始化 | 328 |
| **init** | `cli/init.py` | 项目初始化：创建 .vibetracing/ 目录结构、安装 hook | 195 |
| **accept** | `cli/accept.py` | 人类决策：接受手动规则，写入 human_decisions.json | 220 |
| **doctor** | `cli/doctor.py` | 治理健康扫描：检查数据文件完整性 | 407 |

---

### 共享基础设施

| 模块 | 路径 | 职责 | 行数 | 依赖关系 |
|---|---|---|---|---|
| **db** | `infra/db.py` | 内存 SQLite 数据库：表结构、UPSERT、关系校验 | 614 | 仅标准库 |
| **validation/checks** | `infra/validation/checks.py` | 格式校验：JSON Schema 验证 | 337 | schema_validator |
| **validation/schema_validator** | `infra/validation/schema_validator.py` | Schema 加载与验证 | 302 | 仅标准库 |
| **validation/ids** | `infra/validation/ids.py` | ID 格式校验：REQ/AC/Task/Claim ID 正则 | 141 | 仅标准库 |
| **operational_logger** | `infra/operational_logger.py` | 运维日志：JSON Lines 格式、单例模式 | 230 | 仅标准库 |
| **governance** | `infra/governance.py` | 治理规则：规则定义、判定逻辑 | 101 | 仅标准库 |
| **git_utils** | `infra/git_utils.py` | Git 工具：staged 文件获取、commit 操作 | 80 | subprocess |
| **enums** | `infra/enums.py` | 枚举定义：门禁状态、分析结果类型 | 79 | 仅标准库 |
| **hint_loader** | `infra/hint_loader.py` | 提示加载：从模板文件加载 hint 文本 | 71 | 仅标准库 |
| **tool_resolver** | `infra/tool_resolver.py` | 工具解析：解析工具配置 | 47 | 仅标准库 |

---

## 三、待删除模块

| 模块 | 路径 | 行数 | 原因 |
|---|---|---|---|
| `analysis.py` | `cli/analyze/analysis.py` | 153 | 功能已合并到 `pipeline.py`，残留代码应清除 |

**删除前提**：确认 `analysis.py` 中的 `_run_analyzers()` 和 claims 归档逻辑已完整迁移到 `pipeline.py`。

---

## 四、核心重构目标（按优先级排序）

| 优先级 | 模块 | 问题 | 重构方向 |
|---|---|---|---|
| **P0** | `cli/analyze/pipeline.py` | 510 行，调度逻辑与业务逻辑混合 | 纯调度化：只决定顺序和数据流，不包含业务逻辑 |
| **P0** | `domain/tool_evidence_adapter.py` | 1119 行，最大模块，职责过重 | 拆分：工具执行 vs 证据解析 vs 存储 |
| **P1** | `domain/architecture_compliance_checker.py` | 886 行，规则判定逻辑复杂 | 简化：规则引擎 vs 检查器分离 |
| **P1** | `domain/merge_gate_engine.py` | 629 行，三道门禁耦合 | 解耦：gap/risk/compliance 独立判定 |
| **P2** | `infra/db.py` | 614 行，表结构 + 业务查询混合 | 分离：DDL vs 查询逻辑 |
| **P2** | `cli/doctor.py` | 407 行，诊断逻辑臃肿 | 拆分：诊断项独立化 |
| **P3** | `domain/ghost_code_reconciler.py` | 283 行，幽灵代码检测逻辑 | 与 gates.py 职责边界明确化 |
| **P3** | `domain/architecture_change_proposal.py` | 355 行，变更提案生成 | 与 compliance_checker 解耦 |

---

## 五、模块关系全景

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CLI 入口层                                  │
│  main.py ──→ init.py / finalize.py / accept.py / doctor.py         │
│         └──→ analyze/pipeline.py                                    │
└────────────────────────────┬────────────────────────────────────────┘
                             │ 调度
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Analyze 流水线 CLI 调度层                        │
│  pipeline.py ──→ gates.py (Gate 2 前置)                             │
│            ──→ tools.py (工具执行)                                   │
│            ──→ reports.py (报告生成)                                 │
│            ──→ output.py (终端输出)                                  │
│            ──→ formatting.py + actions.py (动作格式化)               │
│            ──→ helpers.py (辅助函数)                                 │
│            ──→ common.py (共享上下文加载)                             │
└────────────────────────────┬────────────────────────────────────────┘
                             │ 调用
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         领域层 (Domain)                              │
│                                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────┐    │
│  │ context.py  │  │ loader 层    │  │ compliance 层            │    │
│  │ (数据结构)  │  │ raw_input    │  │ prd_arch_validator       │    │
│  │             │  │ prd_parser   │  │ architecture_compliance  │    │
│  │             │  │ claim_loader │  │ ghost_code_reconciler    │    │
│  │             │  │ task_loader  │  └─────────────────────────┘    │
│  └─────────────┘  └──────────────┘                                  │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐    │
│  │ evidence 层  │  │ gate 层      │  │ risk 层                  │    │
│  │ evidence_    │  │ merge_gate_  │  │ risk_advisor             │    │
│  │ builder      │  │ engine       │  └─────────────────────────┘    │
│  │ tool_        │  └──────────────┘                                  │
│  │ evidence_    │  ┌──────────────┐  ┌─────────────────────────┐    │
│  │ adapter      │  │ governance   │  │ output 层                │    │
│  └──────────────┘  │ reflection_  │  │ dashboard_renderer       │    │
│                    │ prompts      │  │ traceability_report_     │    │
│                    │ architecture_│  │ builder                  │    │
│                    │ change_prop  │  └─────────────────────────┘    │
│                    └──────────────┘                                  │
└────────────────────────────┬────────────────────────────────────────┘
                             │ 依赖
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      基础设施层 (Infra)                              │
│                                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────┐    │
│  │ db.py       │  │ validation/  │  │ operational_logger.py    │    │
│  │ (内存DB)    │  │ checks.py    │  │ (JSON Lines 日志)        │    │
│  │             │  │ schema_val.  │  └─────────────────────────┘    │
│  │             │  │ ids.py       │  ┌─────────────────────────┐    │
│  └─────────────┘  └──────────────┘  │ git_utils.py            │    │
│  ┌─────────────┐  ┌──────────────┐  │ hint_loader.py          │    │
│  │ enums.py    │  │ governance.py│  │ tool_resolver.py        │    │
│  │ (枚举)      │  │ (治理规则)   │  └─────────────────────────┘    │
│  └─────────────┘  └──────────────┘                                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 六、跨模块共性问题

| # | 问题 | 影响范围 | 严重度 |
|---|---|---|---|
| 1 | **Domain 层直接读文件**：部分 domain 函数内部调用 `Path.read_text()`，违反"CLI 层负责 I/O"原则 | `claim_loader`, `task_loader`, `raw_input_loader` | 中 |
| 2 | **Domain 层直接调 db.py**：部分 domain 函数自行创建 DB 连接，违反"pipeline 统一管理连接"原则 | `ghost_code_reconciler`, `tool_evidence_adapter` | 高 |
| 3 | **模块行数超标**：3 个模块超过 600 行，应拆分为更小的职责单元 | `tool_evidence_adapter` (1119), `architecture_compliance_checker` (886), `merge_gate_engine` (629) | 高 |
| 4 | **残留代码未清理**：`analysis.py` 已合并到 `pipeline.py` 但仍存在 | `cli/analyze/analysis.py` | 低 |
| 5 | **职责边界模糊**：`gates.py` 与 `ghost_code_reconciler.py` 都做幽灵代码检测，职责重叠 | `cli/analyze/gates.py`, `domain/ghost_code_reconciler.py` | 中 |
| 6 | **Dashboard 定位不清**：`dashboard_renderer.py` 在 domain 层，但它本质是输出层（CLI 层职责） | `domain/dashboard_renderer.py` | 低 |
| 7 | **缺少统一的数据传递契约**：pipeline 向 domain 传递数据时，部分用参数，部分用 UnifiedContext，不一致 | `pipeline.py` → 各 domain 模块 | 中 |
| 8 | **Infra 层模块散落**：`db.py`, `enums.py`, `governance.py` 在 infra 根目录，`validation/` 是子目录，结构不统一 | `infra/` 全局 | 低 |
