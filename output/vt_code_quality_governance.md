# VT 代码质量治理指南

本文档记录当前代码库中的质量残留和治理方向，作为下一轮进化的指导文件。

---

## 一、已确认的残留

### 1.1 TOOL_FILE_TYPE_MAP 死代码

**位置**：`src/vibe_tracing/tool_evidence_adapter.py` line 90-94

```python
TOOL_FILE_TYPE_MAP: Dict[str, set] = {
    "test": {".py"},
    "lint": {".py"},
    "type_check": {".py"},
    "security": {".py"},
}
```

**状态**：`execute_all` 已重写，不再使用此 MAP。但类属性保留，测试 `test_tool_execution.py:808` 仍验证其结构。

**处理**：删除属性 + 删除对应测试断言。

### 1.2 claim_credibility.py 空模块

**位置**：`src/vibe_tracing/traceability/claim_credibility.py`（26 行）

**状态**：`assess_claim_credibility` 函数体已清空为 `return []`。模块保留仅为向后兼容（其他模块可能 import）。

**处理**：确认无其他模块 import 后，可删除整个文件。或保留为 stub 直到下一轮重构。

### 1.3 legacy agent_claims.json fallback

**位置**：`src/vibe_tracing/raw_input_loader.py` line 87-91

```python
# the legacy agent_claims.json does, fall back to the old path.
legacy = self.project_root / ".vibetracing" / "agent_claims.json"
if legacy.exists():
    return legacy
```

**状态**：Claim 已迁移到 `claims/current.json`，但 loader 仍 fallback 到旧路径。

**处理**：确认所有 claim 引用已更新后，删除 fallback。

### 1.4 coverage_baseline.json fallback

**位置**：`src/vibe_tracing/tool_evidence_adapter.py` line 866

```python
self.project_root / ".vibetracing" / "coverage_baseline.json"
```

**状态**：`_measure_source_coverage` 的 `baseline_path` 参数默认值仍指向已删除的文件。只有显式传入 `baseline_path` 时才生效。

**处理**：更新默认值或删除 `baseline_path` 参数（改为只从 evidence_index 读取）。

---

## 二、架构复杂度热点

### 2.1 cli.py 超大函数

| 函数 | 行数 | 位置 |
|---|---|---|
| `_evaluate_and_output` | 350 行 | line 1917 |
| `run_doctor` | 220 行 | line 2453 |
| `run_finalize` | 193 行 | line 238 |
| `_execute_tools` | 176 行 | line 826 |
| `_load_context` | 154 行 | line 439 |
| `run_init` | 125 行 | line 43 |
| `main` | 113 行 | line 2675 |
| `_run_analyzers` | 106 行 | line 1066 |
| `_render_actions` | 103 行 | line 1523 |

**问题**：`_evaluate_and_output` 是 350 行的编排函数，承担了分析、门禁、报告、行动清单、归档的全部逻辑。认知复杂度高，难以维护。

**方向**：按职责拆分为子函数（分析编排、门禁调用、报告生成、行动清单渲染、归档）。

### 2.2 merge_gate_engine.py evaluate() 405 行

**问题**：`evaluate()` 是 405 行的单体函数，包含 7 个 section（Claim 存在性、AC 覆盖、Must AC gaps、Must risks、Should gaps、Should risks、gate_decision 计算）。

**方向**：每个 section 提取为独立方法，`evaluate()` 变为编排层。

### 2.3 tool_evidence_adapter.py execute_tool() 181 行

**问题**：`execute_tool()` 是 181 行的工具执行函数，包含 pytest、coverage、ruff、mypy、bandit 的所有解析逻辑。

**方向**：按工具类型拆分为独立的解析器。

---

## 三、数据流残留

### 3.1 claim_evidence_analyzer Section 4 删除后的文档

**位置**：`src/vibe_tracing/traceability/claim_evidence_analyzer.py` line 30

```python
#   (Section 4 removed: file existence checks are now handled by Gate's check_claim_exists and VT's _run_claim_tests)
```

**状态**：注释保留，说明 Section 4 被移除及原因。这是好的文档实践，保留。

### 3.2 risk_advisor claims_list 参数

**位置**：`src/vibe_tracing/risk_advisor.py` `generate_risks` 方法

**状态**：`claims_list` 参数保留但不再使用（credibility 检查已删除）。函数签名中仍有此参数。

**处理**：从函数签名中删除 `claims_list` 参数，更新所有调用方。

---

## 四、测试质量

### 4.1 预存测试失败

`test_cli_analyze_fail_conditional` 预存失败（临时目录没有 git）。需要修复测试环境 setup。

### 4.2 测试覆盖盲区

以下功能缺少专门的集成测试：
- `_run_claim_tests`（VT 自动跑 pytest）
- `_archive_claims`（Claim 归档机制）
- Gate `check_claim_exists` + `check_ac_coverage` 的端到端流程

---

## 五、治理优先级

| 优先级 | 项目 | 影响 | 工作量 |
|---|---|---|---|
| P0 | 删除 TOOL_FILE_TYPE_MAP 死代码 | 消除混淆 | 5 分钟 |
| P0 | 删除 legacy agent_claims.json fallback | 消除路径歧义 | 10 分钟 |
| P1 | 删除 claims_list 参数残留 | 接口清洁 | 15 分钟 |
| P1 | 修复 test_cli_analyze_fail_conditional | 测试健康 | 20 分钟 |
| P2 | cli.py 超大函数拆分 | 可维护性 | 2-3 小时 |
| P2 | merge_gate_engine evaluate() 拆分 | 可维护性 | 1-2 小时 |
| P3 | 补充集成测试（_run_claim_tests、归档、Gate 端到端） | 质量保障 | 2-3 小时 |

---

## 六、质量治理原则

1. **不保留死代码**：如果代码不被任何路径调用，删除它。不为"可能有用"保留。
2. **不保留向后兼容 fallback**：VT 处于开发期，零历史兼容债务。旧路径删除后，fallback 也应删除。
3. **函数不超过 100 行**：超过 100 行的函数应拆分为子函数。
4. **每个模块职责单一**：如果一个模块做了多件事，拆分它。
5. **测试必须覆盖新功能**：新增功能必须有对应的测试，不能只靠现有测试通过。

---

## 七、原子化任务计划

### 文件冲突矩阵

| 文件 | Batch 1 | Batch 2 | Batch 3 |
|---|---|---|---|
| tool_evidence_adapter.py | QUAL-001 | | |
| test_tool_execution.py | QUAL-001 | | |
| raw_input_loader.py | QUAL-002 | | |
| risk_advisor.py | | QUAL-003 | |
| cli.py | | QUAL-003, QUAL-004 | QUAL-006 |
| test_cli_analyze.py | | QUAL-004 | |
| merge_gate_engine.py | | | QUAL-007 |
| test files (new) | | | QUAL-008 |

### Batch 1：死代码清理（2 个并行任务）

---

#### QUAL-001：删除 TOOL_FILE_TYPE_MAP 死代码

- **目标**：删除不再被 execute_all 使用的 TOOL_FILE_TYPE_MAP
- **目标文件**：`src/vibe_tracing/tool_evidence_adapter.py` + `tests/test_tool_execution.py`
- **前置依赖**：无
- **变更内容**：
  - 删除 `tool_evidence_adapter.py` 中 `TOOL_FILE_TYPE_MAP` 类属性定义（line 90-94）
  - 更新注释：删除对 TOOL_FILE_TYPE_MAP 的引用
  - 删除 `test_tool_execution.py` 中验证 TOOL_FILE_TYPE_MAP 结构的测试（约 line 801-808）
- **验证命令**：`pytest tests/test_tool_execution.py -v`
- **范围限制**：不修改 execute_all 逻辑

---

#### QUAL-002：删除 legacy agent_claims.json fallback

- **目标**：删除 raw_input_loader 中对旧路径的 fallback
- **目标文件**：`src/vibe_tracing/raw_input_loader.py`
- **前置依赖**：无
- **变更内容**：
  - 删除 line 87-91 的 legacy fallback 代码
  - 确认 config.json 中 `paths.agent_claims` 已指向新路径
  - 如果 config.json 仍指向旧路径，更新为 `.vibetracing/claims/current.json`
- **验证命令**：`pytest tests/test_raw_input_loader.py -v`
- **范围限制**：不修改其他 loader

---

### Batch 2：接口清理 + 测试修复（2 个并行任务）

---

#### QUAL-003：删除 risk_advisor claims_list 参数

- **目标**：从 risk_advisor.generate_risks 中删除不再使用的 claims_list 参数
- **目标文件**：`src/vibe_tracing/risk_advisor.py` + `src/vibe_tracing/cli.py`
- **前置依赖**：无
- **变更内容**：
  - `risk_advisor.py`：从 `generate_risks` 签名中删除 `claims_list` 参数
  - `risk_advisor.py`：删除函数体中对 `claims_list` 的引用（如有残留）
  - `cli.py`：更新 `_run_analyzers` 中对 `generate_risks` 的调用，删除 `claims_list=...` 参数
  - 更新 docstring
- **验证命令**：`pytest tests/test_risk_advisor.py tests/test_cli_analyze.py -v`
- **范围限制**：不修改 claim_credibility.py

---

#### QUAL-004：修复 test_cli_analyze_fail_conditional

- **目标**：修复预存的测试环境问题
- **目标文件**：`tests/test_cli_analyze.py`
- **前置依赖**：无
- **变更内容**：
  - 找到 `test_cli_analyze_fail_conditional` 测试
  - 分析失败原因（临时目录没有 git 仓库）
  - 修复：在测试 setup 中初始化 git 仓库，或 mock git 调用
- **验证命令**：`pytest tests/test_cli_analyze.py::test_cli_analyze_fail_conditional -v`
- **范围限制**：只修改这一个测试

---

### Batch 3：架构重构（3 个任务，QUAL-006 和 007 可并行）

---

#### QUAL-005：coverage_baseline.json fallback 清理

- **目标**：删除 tool_evidence_adapter 中对已删除文件的默认路径
- **目标文件**：`src/vibe_tracing/tool_evidence_adapter.py`
- **前置依赖**：QUAL-001
- **变更内容**：
  - `_measure_source_coverage` 的 `baseline_path` 参数默认值改为 `None`
  - 当 `baseline_path` 为 None 且 `evidence_index` 无 `coverage_baseline` 时，返回空结果
  - 删除 line 866 的硬编码路径
  - 更新 docstring
- **验证命令**：`pytest tests/test_tool_execution.py -v`
- **范围限制**：不修改 cli.py

---

#### QUAL-006：cli.py _evaluate_and_output 拆分

- **目标**：将 350 行的 `_evaluate_and_output` 拆分为 5 个子函数
- **目标文件**：`src/vibe_tracing/cli.py`
- **前置依赖**：QUAL-003（claims_list 参数清理后，函数签名稳定）
- **变更内容**：
  - 提取 `_run_analysis(project_root, ctx)` — 调用 _run_analyzers
  - 提取 `_run_gate_evaluation(engine, gaps, risks, ...)` — 调用 gate engine
  - 提取 `_generate_report(ctx, gate_res, evidence_index, ...)` — 生成报告
  - 提取 `_render_and_output(report_doc, gate_res, ...)` — 渲染输出
  - 提取 `_handle_archive(project_root, exit_code, is_pre_commit)` — 归档逻辑
  - `_evaluate_and_output` 变为编排函数，调用以上子函数
- **验证命令**：`pytest tests/test_cli_analyze.py -v`
- **范围限制**：
  - 不改变外部行为（输入输出不变）
  - 不修改 merge_gate_engine.py
  - 每个子函数不超过 80 行

---

#### QUAL-007：merge_gate_engine evaluate() 拆分

- **目标**：将 405 行的 `evaluate()` 拆分为 7 个 section 方法
- **目标文件**：`src/vibe_tracing/merge_gate_engine.py`
- **前置依赖**：无
- **变更内容**：
  - 提取 `_check_claim_existence(claims, staged_items, boundary)` — Section 0.5
  - 提取 `_check_ac_coverage(claims, tasks, evidence_index)` — Section 0.6
  - 提取 `_process_must_gaps(gaps)` — Section 1.1
  - 提取 `_process_must_risks(risks, staged_items)` — Section 1.2
  - 提取 `_process_should_gaps(gaps)` — Section 2.2
  - 提取 `_process_should_risks(risks, staged_items)` — Section 2.3
  - `evaluate()` 变为编排函数，调用以上方法，最后计算 gate_decision
- **验证命令**：`pytest tests/test_merge_gate_engine.py -v`
- **范围限制**：
  - 不改变外部行为
  - 不修改 cli.py
  - 每个方法不超过 60 行

---

#### QUAL-008：补充集成测试

- **目标**：为新功能补充端到端集成测试
- **目标文件**：`tests/test_integration_v3.py`（新增）
- **前置依赖**：QUAL-006, QUAL-007
- **变更内容**：
  - 测试 `_run_claim_tests`：模拟 claim 的 test_refs，验证 pytest 执行结果写入 evidence_index
  - 测试 `_archive_claims`：验证 commit 后 claims 归档到 archive/ 并清空 current.json
  - 测试 Gate `check_claim_exists` + `check_ac_coverage` 端到端：模拟 staged files + claims + tasks，验证门禁判定
  - 测试 `execute_all` 新逻辑：验证只对目标语言文件执行工具
- **验证命令**：`pytest tests/test_integration_v3.py -v`
- **范围限制**：不修改生产代码

---

### 执行计划总览

```
Batch 1（并行）:
  QUAL-001 (tool_evidence_adapter.py) ─┐
  QUAL-002 (raw_input_loader.py) ──────┤
                                        ├→ 完成后进入 Batch 2
Batch 2（并行）:
  QUAL-003 (risk_advisor.py + cli.py) ─┐
  QUAL-004 (test_cli_analyze.py) ──────┤
                                        ├→ 完成后进入 Batch 3
Batch 3:
  QUAL-005 (tool_evidence_adapter.py) ─→ 依赖 QUAL-001
  QUAL-006 (cli.py 拆分) ──────────────┐
  QUAL-007 (merge_gate_engine.py 拆分) ┤→ 可并行
                                        ├→ 完成后进入 QUAL-008
  QUAL-008 (集成测试) ─────────────────→ 依赖 QUAL-006 + QUAL-007
```

**预计总耗时**：Batch 1（15 分钟）+ Batch 2（30 分钟）+ Batch 3（4-6 小时）= 约 5-7 小时
