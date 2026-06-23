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
├── docs/
│   ├── prd.md                          # 需求文档（REQ/AC）
│   ├── architecture_constraints.json   # 架构约束
│   ├── task_list.json                  # 开发任务
│   ├── refactoring_design.md           # 重构设计（接口+步骤+删除清单）
│   ├── architecture_vision.md          # 架构愿景（设计原则+校验规范）
│   └── architecture_change_log.md      # 架构变更日志
├── src/vibe_tracing/
│   ├── cli/                            # 入口与编排层
│   │   ├── main.py                     # CLI 入口
│   │   ├── common.py                   # 共享工具（_load_context 等）
│   │   └── analyze/                    # vt analyze 子命令
│   │       ├── pipeline.py             # 流水线调度（12 阶段）
│   │       ├── gates.py                # Gate 2 前置条件
│   │       ├── tools.py                # 工具执行
│   │       ├── reports.py              # 报告生成
│   │       └── output.py               # 终端输出
│   ├── domain/                         # 领域层
│   │   ├── context.py                  # UnifiedContext
│   │   ├── evidence_builder.py         # 证据构建（merge+apply+persist）
│   │   ├── merge_gate_engine.py        # 门禁判定引擎
│   │   ├── risk_advisor.py             # 风险建议
│   │   ├── architecture_compliance_checker.py
│   │   ├── ghost_code_reconciler.py    # 幽灵代码检测
│   │   ├── tool_evidence_adapter.py    # 工具执行引擎
│   │   ├── raw_input_loader.py         # 原始输入加载
│   │   ├── prd_parser.py              # PRD 解析
│   │   ├── task_loader.py             # Task 加载
│   │   ├── claim_loader.py            # Claim 加载
│   │   ├── dashboard_renderer.py       # Dashboard 渲染
│   │   ├── traceability_report_builder.py
│   │   ├── reflection_prompts.py       # 反思提示
│   │   └── architecture_change_proposal.py
│   ├── analyzers/                      # 追踪分析器
│   │   ├── requirement_task_analyzer.py
│   │   ├── ac_test_analyzer.py
│   │   └── claim_evidence_analyzer.py
│   └── infra/                          # 基础设施层
│       ├── db/                         # 内存 SQLite
│       │   ├── schema.py               # 表结构 + init_in_memory_db
│       │   ├── loaders.py              # load_tasks, load_claims, load_prd 等
│       │   ├── queries.py              # check_* 查询函数 + get_full_chain
│       │   └── exports.py              # upsert_*, purge_stale_cache
│       ├── validation/                 # 格式校验
│       │   ├── checks.py              # validate_inputs 入口
│       │   ├── ids.py                 # ID 正则 + 生成
│       │   ├── schema_validator.py    # JSON Schema 校验器
│       │   └── schemas/               # JSON Schema 契约文件
│       ├── config/                     # 枚举与 hints
│       ├── logging/                    # JSONL 运行日志
│       ├── git/                        # Git 工具
│       └── tools/                      # 工具路径解析
├── tests/
└── .vibetracing/                       # VT 治理数据
    ├── config.json
    ├── claims/CLAIM-*.json             # 一任务一声明文件
    ├── human_decisions.json
    └── logs/
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
| [refactoring_design.md](docs/refactoring_design.md) | 重构设计：接口契约、实施步骤、变更清单、删除清单 |
| [architecture_vision.md](docs/architecture_vision.md) | 架构愿景：设计原则、双层校验规范、门禁规则 |
| [prd.md](docs/prd.md) | 需求文档：REQ/AC 定义 |
