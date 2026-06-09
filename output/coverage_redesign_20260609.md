# 测试覆盖率重新设计方案

**日期**: 2026-06-09
**状态**: 待实施
**关联**: vt_pending_issues_20260608.md (问题一)

---

## 一、当前系统的根本缺陷

### 1.1 测量方向错误

当前命令：`coverage run -m pytest {test_path}`

这测量的是**"运行这个测试文件，覆盖了全库多少代码"**。每个测试文件独立运行 coverage，得到一个全局百分比。

**正确的问题应该是**：**"这个源文件有多少行被测试执行到了？"**

当前逻辑：
```
test_cli.py → coverage 70% (全库) → violated
test_prd_parser.py → coverage 45% (全库) → violated
```

正确逻辑：
```
src/cli.py → 85% 行被测试覆盖 → compliant
src/config.py → 12% 行被测试覆盖 → violated
```

### 1.2 测量范围错误

只对 staged 的测试文件运行 coverage。如果 `test_cli.py` 未 staged，不运行 coverage，该测试文件的覆盖数据丢失。

但覆盖率应该反映**整个测试套件对源文件的覆盖**，不是单个测试文件的贡献。

### 1.3 阈值应用错误

80% 阈值应用于每个测试文件的全局覆盖率。一个测试文件覆盖全库 80% 是不现实的。

正确做法：80% 阈值应用于每个**源文件**的被覆盖率。

### 1.4 证据不持久化

FIX-TASK-006 只持久化 `source_type="test"` 的证据（测试执行结果），不持久化 `source_type="tool"` + `tool_category="coverage"` 的证据（覆盖率）。

结果：未 staged 的文件覆盖率数据丢失。

---

## 二、最优方案设计

### 2.1 核心思路

**一次全量测量，增量更新，按源文件聚合。**

```
vt analyze
  → 全量 coverage（如果首次运行或源文件有变化）
  → 按源文件聚合覆盖率
  → 持久化结果
  → 下次运行：只重新测量变化的源文件
```

### 2.2 测量方式

**不再按测试文件运行 coverage，而是按源文件测量。**

```bash
# 全量测量（首次或源文件变化时）
coverage run -m pytest tests/
coverage json -o .vibetracing/coverage_baseline.json

# 结果：每个源文件的行覆盖率
{
    "src/vibe_tracing/cli.py": {"percent_covered": 85.2, "num_statements": 1200, "missing": 178},
    "src/vibe_tracing/config.py": {"percent_covered": 12.5, "num_statements": 80, "missing": 70},
    ...
}
```

### 2.3 持久化机制

**新增 `.vibetracing/coverage_baseline.json`**：

```json
{
    "timestamp": "2026-06-09T18:00:00Z",
    "total_files": 31,
    "total_statements": 15000,
    "total_covered": 6300,
    "aggregate_percent": 42.0,
    "files": {
        "src/vibe_tracing/cli.py": {
            "percent_covered": 85.2,
            "num_statements": 1200,
            "missing_lines": [45, 67, 89, ...],
            "last_measured": "2026-06-09T18:00:00Z"
        },
        "src/vibe_tracing/config.py": {
            "percent_covered": 12.5,
            "num_statements": 80,
            "missing_lines": [5, 8, 12, ...],
            "last_measured": "2026-06-09T18:00:00Z"
        }
    }
}
```

### 2.4 增量更新策略

```
if 首次运行 or baseline 不存在:
    全量测量
else:
    变化文件 = staged 的源文件 + 其测试文件
    if 有变化文件:
        增量测量（只重新运行相关测试）
        合并到 baseline
    else:
        使用 baseline 数据
```

**增量测量命令**：
```bash
# 只运行与变化文件相关的测试
coverage run -m pytest tests/test_cli.py tests/test_config.py
coverage json -o .vibetracing/coverage_delta.json
# 合并 delta 到 baseline
```

### 2.5 阈值逻辑

**80% 就是 80%，不妥协。**

| 覆盖率 | 状态 | 门禁行为 |
|---|---|---|
| ≥ 80% | compliant | 通过 |
| < 80% | violated | 阻断门禁 |
| 无数据 | unknown | 阻断门禁（视为未测试） |

**为什么不低于 80%**：降低门槛不会让问题消失，只会让问题隐藏。人类没有开发经验，如果 VT 不阻断，人类无法判断代码质量，问题会一直积累直到项目崩溃。80% 门槛迫使 Agent 补充测试，而不是绕过。

**当前 42% 意味着**：门禁会持续 BLOCKED。这是正确的——它如实反映了代码质量不达标。解决方式是补充测试，不是降低门槛。

### 2.6 与治理边界的关系

只对 `governance_boundary.included_patterns` 中的 .py 文件测量覆盖率。辅助文件不测量。

```
治理范围内源文件：31 个 (src/vibe_tracing/**/*.py)
治理范围内测试文件：38 个 (tests/test_*.py)
范围外文件：不测量覆盖率
```

### 2.7 与 Claim 体系的关系

覆盖率证据与 Claim 体系解耦：

| 维度 | Claim 体系 | 覆盖率体系 |
|---|---|---|
| 测量对象 | AC 是否有测试 | 源文件有多少行被测试 |
| 数据来源 | test_refs + covers docstring | coverage 工具 |
| 持久化 | claim_fingerprints.json | coverage_baseline.json |
| 阈值 | 有/无测试 | 行覆盖率百分比 |
| 门禁影响 | 通过 risk 影响 | 直接通过 evidence status 影响 |

两者独立运作，互不干扰。

---

## 三、代码变更清单

### 3.1 新增文件

| 文件 | 用途 |
|---|---|
| `.vibetracing/coverage_baseline.json` | 覆盖率基线数据 |

### 3.2 修改文件

| 文件 | 改动 |
|---|---|
| `src/vibe_tracing/tool_evidence_adapter.py` | 新增按源文件测量 coverage 的逻辑；修改阈值为分层策略 |
| `src/vibe_tracing/evidence_index_builder.py` | 持久化 coverage 证据（与 test 证据同等对待） |
| `src/vibe_tracing/cli.py` | 集成覆盖率基线加载/更新逻辑；在报告中输出覆盖率统计 |
| `src/vibe_tracing/merge_gate_engine.py` | 新增覆盖率门禁检查（aggregate_percent < 50% → blocked） |
| `src/vibe_tracing/templates/dashboard.template.html` | 新增覆盖率仪表盘（按文件着色的热力图） |
| `docs/architecture_constraints.json` | 更新 coverage 工具命令模板 |

### 3.3 Dashboard 覆盖率仪表盘

```
┌─────────────────────────────────────────────────────────┐
│ 覆盖率概览                                               │
│ 整体：42% (6300/15000 行)  目标：80%                      │
│                                                         │
│ 文件覆盖率热力图：                                        │
│ ████████████████████░░░░ cli.py           85% ✓          │
│ ██████████████░░░░░░░░░░ risk_advisor.py  62% ⚠          │
│ ████████░░░░░░░░░░░░░░░░ config.py        38% ✗          │
│ ████░░░░░░░░░░░░░░░░░░░░ tool_resolver.py 18% ✗          │
│ ...                                                     │
│                                                         │
│ 未覆盖的关键行（可展开）：                                 │
│ ▶ cli.py:445-462 (handle_invalid_args 未测试)            │
│ ▶ config.py:12-45 (load_config 未测试)                   │
└─────────────────────────────────────────────────────────┘
```

---

## 四、原子化任务

- [ ] **Task ID**: COV-TASK-001
  - **Action**: MODIFY
  - **Target File**: `docs/architecture_constraints.json`
  - **Instruction**: 更新 coverage 工具命令模板。将 `coverage run -m pytest {test_path}` 改为支持全量测量的命令。新增 `coverage_baseline` 配置项声明基线文件路径和阈值策略。
  - **AC**: 覆盖率命令模板支持全量和增量两种模式

- [ ] **Task ID**: COV-TASK-002
  - **Action**: NEW
  - **Target File**: `.vibetracing/coverage_baseline.json`
  - **Instruction**: 创建覆盖率基线文件。首次运行 `coverage run -m pytest tests/` + `coverage json`，解析结果，按源文件聚合，写入基线文件。
  - **AC**: 基线文件包含每个源文件的 percent_covered、num_statements、missing_lines

- [ ] **Task ID**: COV-TASK-003
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/tool_evidence_adapter.py`
  - **Instruction**:
    1. 新增 `_measure_source_coverage()` 方法，运行全量 coverage 并按源文件聚合
    2. 阈值逻辑：≥80% compliant，<80% violated，无数据 unknown
    3. 增量更新：只重新测量变化的源文件
  - **AC**: 覆盖率按源文件测量，80% 门槛不妥协

- [ ] **Task ID**: COV-TASK-004
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/evidence_index_builder.py`
  - **Instruction**: 持久化 coverage 证据。对 `source_type="tool"` + `tool_category="coverage"` 的证据也执行 carry over（与 test 证据同等对待）。标记 `carried_over: true`。
  - **AC**: 未重新测量的源文件保留上次的覆盖率数据

- [ ] **Task ID**: COV-TASK-005
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**:
    1. 在 `_execute_tools()` 中集成覆盖率基线加载/更新
    2. 在 `_evaluate_and_output()` 中输出覆盖率统计（整体百分比、按文件分布）
    3. 在报告中新增 `coverage_summary` 字段
  - **AC**: `vt analyze` 输出覆盖率统计，报告包含 coverage_summary

- [ ] **Task ID**: COV-TASK-006
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/merge_gate_engine.py`
  - **Instruction**: 新增覆盖率门禁检查。当任何源文件覆盖率 < 80% 时，生成 must 级 gap 并阻断门禁。无覆盖率数据的文件也视为未通过。
  - **AC**: 覆盖率 < 80% 时门禁 BLOCKED，不妥协

- [ ] **Task ID**: COV-TASK-007
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/templates/dashboard.template.html`
  - **Instruction**:
    1. 新增覆盖率仪表盘组件（按文件着色的热力图）
    2. 绿色 ≥80%（通过），红色 <80%（未通过）
    3. 整体覆盖率百分比和目标对比
    4. 可展开的未覆盖关键行列表
  - **AC**: Dashboard 显示覆盖率热力图和统计

- [ ] **Task ID**: COV-TASK-008
  - **Action**: MODIFY
  - **Target File**: `tests/`
  - **Instruction**: 为覆盖率新逻辑编写测试：
    1. 全量覆盖率测量 → 按源文件聚合
    2. 增量更新 → 只重新测量变化文件
    3. 分层阈值 → compliant/warning/violated
    4. 持久化 → carry over 覆盖率证据
  - **AC**: 新测试全部通过

---

## 五、预期效果

实施后：

| 指标 | 之前 | 之后 |
|---|---|---|
| 覆盖率测量方式 | 按测试文件，全库百分比 | 按源文件，单文件百分比 |
| 覆盖率数据持久化 | 不持久化 | coverage_baseline.json |
| 阈值策略 | 80% 但只测 staged 文件 | 80% 且测量治理范围内所有源文件 |
| 门禁行为 | 覆盖率低 → BLOCKED | 覆盖率 <80% → BLOCKED（不妥协） |
| Dashboard | 无覆盖率可视化 | 热力图 + 统计 |
| 增量更新 | 每次全量 | 只重新测量变化文件 |

**核心改善**：从"覆盖率 42% → 门禁 BLOCKED → 但不知道哪些文件需要补充测试"变为"覆盖率 42% → 门禁 BLOCKED → Agent 和人类都能看到哪些文件需要补充测试 → Agent 有针对性地补充测试 → 覆盖率提升 → 门禁通过"。

门禁始终 80% 门槛。当前 42% 意味着门禁会持续 BLOCKED，这是正确的。解决方式是补充测试，不是降低门槛。
