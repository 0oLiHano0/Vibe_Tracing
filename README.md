# Vibe Tracing (VT)

AI Coding Agent 的一致性校验框架。将技术产物（代码、测试、Claims）转化为治理指标（覆盖状态、风险、门禁判定），供非技术业务人员通过 Dashboard 验收。

---

## 核心理念

1. **结果导向，不约束过程**：不限制 Agent 的实现方式，在交付端通过 JSON Schema 契约 + Merge Gate 进行刚性校验。
2. **本地反馈闭环**：Agent 通过 `vt analyze` 的终端输出迭代修复，无需人工提示。
3. **证据驱动信任**：Agent 的自然语言声明被视为未验证，缺失证据的项目降级为 "unclear" 或 "missing"。

---

## 项目结构

```text
.
├── pyproject.toml                      # 包配置、依赖与 CLI 入口
├── docs/
│   ├── prd.md                          # 需求文档（REQ/AC）
│   ├── architecture_constraints.json   # 架构约束
│   ├── task_list.json                  # 开发任务
│   ├── architecture_change_log.md      # 架构变更日志
│   ├── business_logic/                 # 业务逻辑（锁定源头）
│   ├── design/                         # 代码架构设计（编码/重构依据）
│   └── tech_debt/                      # 技术债务条目
├── src/vibe_tracing/
│   ├── cli/                            # CLI 命令与编排层
│   │   ├── main.py                     # 命令入口
│   │   ├── init.py / doctor.py         # 项目初始化与健康检查
│   │   ├── accept.py / finalize.py     # 人工验收与交付收尾
│   │   └── analyze/                    # analyze 流水线、输出与报告
│   ├── domain/                         # 领域层
│   │   ├── context.py                  # UnifiedContext
│   │   ├── capability/                 # Agent 能力指标
│   │   ├── compliance/                 # PRD 与架构合规校验
│   │   ├── evidence/                   # 证据构建与合并结果
│   │   ├── gate/                       # 门禁、基线与信号计算
│   │   ├── governance/                 # 治理指标与变更提案
│   │   ├── risk/                       # 风险建议
│   │   └── task/                       # 任务会话、验收与业务影响
│   └── infra/                          # 基础设施层
│       ├── db/                         # 内存 SQLite
│       ├── loader/                     # PRD、Task、Claim 与配置加载
│       ├── validation/                 # 输入与 Schema 校验
│       ├── compliance/                 # 架构约束加载
│       ├── report/                     # Dashboard、追溯报告与反思提示
│       ├── config/                     # 枚举、边界与动态提示
│       ├── logging/                    # JSONL 运行日志
│       └── tools/                      # 外部工具执行、解析与路径解析
│   └── templates/                      # 初始化时使用的治理文件与 Dashboard 模板
├── tests/                              # 单元测试与端到端测试
├── output/                             # analyze 生成的报告与证据（运行产物）
└── .vibetracing/                       # 被分析项目的治理数据（运行时创建）
```

---

## Quick Start

```bash
# 安装
pip install -e ".[dev]"

# 分析
vt analyze --project-root /path/to/project

# 测试
pytest
```

### 输出文件

| 文件 | 说明 |
|------|------|
| `output/evidences/test_results.json` | 测试结果 |
| `output/evidences/coverage_reports.json` | 覆盖率 |
| `output/traceability_report.json` | 追溯报告 |
| `output/dashboard.html` | Dashboard（人类验收用） |

### 退出码

| 码 | 含义 |
|----|------|
| 0 | 通过 |
| 1 | 输入错误 / Schema 违规 |
| 2 | 门禁 blocked |

---

## 设计文档

| 文档 | 内容 |
|------|------|
| [vision_redesign.md](docs/design/vision_redesign.md) | 重构设计：接口契约、实施步骤、变更清单、删除清单 |
| [vision_Analyze_Arch_Redesign.md](docs/design/vision_Analyze_Arch_Redesign.md) | vt analyze 架构设计：设计原则、接口契约、包结构、数据流 |
| [prd.md](docs/prd.md) | 需求文档：REQ/AC 定义 |
