# VT 自管理差距分析报告

## 一、背景

Vibe Tracing 是一个 AI Coding 治理工具，用于追踪需求到代码的全链条合规性。作为治理工具，VT 应当"吃自己的狗粮"——使用自身的 `vt finalize`、`vt analyze` 等命令管理自己的开发过程。

本报告对 VT 项目的自管理状态进行了 9 个维度的系统审查，发现 VT 存在严重的自管理缺口。

---

## 二、因果链总览

所有差距不是孤立的，它们形成了一条因果链：

```
Git 未提交（工作树与 commit 脱节）
    │
    ▼
architecture_constraints.json 缺少 project.language
    │
    ▼
vt finalize 无法运行
    │
    ▼
config.json 停留在脚手架状态（无 hash/commit/path）
    │
    ▼
vt analyze 无法运行（"Project not finalized"）
    │
    ▼
无证据产出、无 gate 判定、无 dashboard 更新
    │
    ▼
task_list.json 中的 phantom 引用无法被检测
    │
    ▼
change_log.md 未记录本次重构的架构变更
    │
    ▼
VT 不吃自己的狗粮
```

---

## 三、各维度审查详情

### 3.1 配置状态（CRITICAL）

**文件**：`.vibetracing/config.json`

**当前状态**：config.json 停留在 `vt init` 生成的脚手架状态：
```json
{
  "schema_version": "1.0.0",
  "project_id": "PROJECT-VT",
  "paths": { ... }
}
```

**缺失字段**：
- `language`（应为 `"python"`）
- `validation_tools`（应为 `["test", "coverage", "lint", "type_check", "security"]`）
- `architecture_constraints_hash`（finalize 后写入）
- `finalize_git_commit`（finalize 后写入）
- `finalize_constraints_path`（finalize 后写入）

**影响**：VT 从未对自身执行 `vt finalize`。`vt analyze` 会因 "Project not finalized" 而失败。

---

### 3.2 PRD 状态（MEDIUM）

**文件**：`docs/prd.md`

**当前状态**：PRD 内容完整（1600+ 行），有 YAML front matter，但：
- front matter 中有 `tags: [prd, draft]`，无显式 `status` 字段
- `Version` 首字母大写（`Version: v0.1`），与小写惯例不一致
- 最后更新日期为 2026-05-18，距今近 3 周

**影响**：如果 PrdParser 期望 front matter 中有 `status` 字段，解析可能异常。

---

### 3.3 任务列表状态（CRITICAL）

**文件**：`docs/task_list.json`

**当前状态**：43 个任务（14 done、23 todo、6 cancelled）。

**Phantom 引用**：
- TASK-VT-020 和 TASK-VT-021 引用了 `GATE-VT-013` 和 `GATE-VT-014`，但 architecture_constraints.json 中只有 GATE-VT-001 到 GATE-VT-012
- TASK-VT-018 的 `depends_on` 引用了 `TASK-VT-038`，但该任务不存在于 task_list.json 中
- CLAIM-VT-9999 引用了 `TASK-VT-9999`，同样不存在

**影响**：违反 VT 自身的可追溯性原则——引用链断裂。

---

### 3.4 架构约束状态（CRITICAL）

**文件**：`docs/architecture_constraints.json`

**当前状态**：结构完整（1257 行），包含 14 个约束类别、12 个模块、12 个质量门禁。

**缺失项**：
- `project.language` 未设置（finalize 的前置条件）
- `GATE-VT-014`（架构约束变更治理门禁）未在 quality_gates 中定义，但 task_list 和 PRD 中均有引用
- `architecture_change_log.md` 仅有 2 条记录（2026-05-24 和 2026-05-27），未记录本次 Phase 8 重构的架构变更

**影响**：finalize 无法运行；GATE-VT-014 即使代码已实现也无法被门禁系统识别；变更日志不完整。

---

### 3.5 Agent Claims 状态（MEDIUM）

**文件**：`.vibetracing/agent_claims.json`

**当前状态**：7 条 claim，结构正确。

**问题**：
- CLAIM-VT-9999 引用不存在的 TASK-VT-9999
- 所有 claim 的时间戳为 2026 年 5 月，但引用的代码文件此后被大量修改（traceability report 标记了 13 条 stale claim 风险）
- 绝大多数任务（TASK-VT-001 到 TASK-VT-004、TASK-VT-006 到 TASK-VT-029）没有对应的 claim

**影响**：claim 覆盖率低，stale claim 产生误报。

---

### 3.6 证据产出状态（HIGH）

**文件**：`.vibetracing/output/`

**当前状态**：evidence_index.json、traceability_report.json、dashboard.html、run_metadata.json 均存在。

**问题**：
- gate_decision 为 `"fail"`（68+ 条架构约束标记为 "unclear"）
- 大部分任务的 evidence 状态为 `"missing"`
- `.vibetracing/tool_reports/` 目录已被删除（重构过程中的副作用），但产出文件仍引用旧数据
- 扫描时间为 2026-06-03，已过期

**影响**：产出数据与当前代码状态不一致。

---

### 3.7 CI/CD 集成（HIGH）

**当前状态**：不存在 `.github/workflows/` 或任何 CI 配置。

**影响**：VT 没有任何自动化方式来执行自身的质量门禁。没有 CI 运行 `vt analyze`、没有自动 pytest、没有 merge gate 执行。

---

### 3.8 Git 状态（CRITICAL）

**当前状态**：main 分支，3 个 commit（均在 2026 年 5 月）。

**问题**：
- 30+ 个已修改文件未提交
- 10+ 个已删除文件未提交
- 15+ 个新文件未跟踪
- 工作树与最后一次 commit 严重脱节

**影响**：项目治理数据不在版本控制之下，无法追溯变更历史。

---

### 3.9 自管理测试覆盖（CRITICAL）

**当前状态**：
- `test_e2e_finalize_analyze.py` 使用 mock fixture 项目测试，不测试 VT 自身
- `test_e2e_samples.py` 使用 fixture 样本项目测试，不测试 VT 自身

**缺失**：没有任何测试验证 VT 能否管理自己的项目。

**影响**："吃自己的狗粮"原则完全未被测试覆盖。

---

### 3.10 Prompts 引导模板缺失（MEDIUM）

**当前状态**：`.vibetracing/prompts/` 目录不存在，`prd_analysis.md` 文件缺失。

**代码引用**：
- `cli.py:124`：`vt init` 时会创建 `.vibetracing/prompts/prd_analysis.md`（从模板渲染）
- `cli.py:804`：当 PRD 处于 draft 状态且无任务时，零提示词引导系统输出提示让 Agent 读取该文件

**影响**：冷启动引导流断裂。新项目处于 draft 状态时，Agent 无法获取 7 步分析法的指引。

**原因**：该文件由 `vt init` 生成。VT 自身的 `.vibetracing/` 目录可能是手动创建或在 init 流程重构前建立的，未包含 prompts 子目录。

---

### 3.11 output_dir 配置未对齐（LOW）

**当前状态**：`.vibetracing/config.json` 中 `output_dir` 为 `".vibetracing/output"`。

**影响**：VT 的实际产出（evidence_index.json、dashboard.html 等）写入 `.vibetracing/output/`，而项目根目录下存在独立的 `output/` 目录用于存放设计文档。两者职责不同，但如果 Phase 3 重构确立了"输出目录统合至根目录 output/"的规范，则当前配置未对齐。

**注意**：此条需确认 Phase 3 的规范是否适用于 VT 自身的产出目录，还是仅适用于用户项目的默认配置。

---

### 3.12 GATE-VT-013 门禁规则定义缺失（CRITICAL）

**当前状态**：`task_list.json` 中 8 处引用了 `GATE-VT-013`，但 `architecture_constraints.json` 的 `quality_gates` 数组中只定义了 GATE-VT-001 到 GATE-VT-012。

**引用位置**：
- TASK-VT-020 的 `related_architecture_constraints` 和 `definition_of_done`
- TASK-VT-021 的 `related_architecture_constraints`
- TASK-VT-022 到 TASK-VT-029 的 `related_architecture_constraints`

**影响**：与 GATE-VT-014 缺失类似，造成双重门禁规则断链。task_list 引用了一个不存在的门禁，违反 VT 自身的可追溯性原则。

---

### 3.13 测试文件不纯净（MEDIUM）

**当前状态**：2 个测试文件包含不应存在的动态注入代码，根因是 fixture 物理文件未跟上项目架构演进。

#### test_e2e_samples.py

`_prepare_project` 函数做了一件本应由 fixture 物理文件完成的事：

```python
# 动态注入 finalized config（fixture 文件中没有）
config_data = {
    "language": "python",
    "validation_tools": ["test", ...],
    ...
}

# 动态修正 evidence_refs（fixture 文件中 claim 指向错误的 EVIDENCE ID）
if claim.get("evidence_refs") == ["EVIDENCE-VT-001"]:
    claim["evidence_refs"] = ["EVIDENCE-VT-003"]
```

**不纯净原因**：`tests/fixtures/examples/` 下的样本项目没有自带 finalized config.json，且 agent_claims.json 中的 evidence_refs 指向了错误的证据 ID。

**修复方式**：更新 fixture 物理文件，让样本项目自带：
1. `.vibetracing/config.json`（含 language、validation_tools、architecture_constraints_hash 等）
2. `.vibetracing/agent_claims.json`（evidence_refs 指向正确的 EVIDENCE ID）

修复后，`_prepare_project` 中的动态注入和正则修正代码可完全删除，只保留 `shutil.copytree`。

#### test_cli_analyze.py

`setup_mock_project` 函数包含三处 hack：

1. **mock tool execution**：`mock_tool_execution` fixture 用 monkeypatch 替换了 `ToolExecutionEngine.execute_all`，通过 `test_opts.json` 传递测试参数
2. **手动注入 finalize 元数据**：在 config.json 中手写 `architecture_constraints_hash`、`finalize_git_commit`、`finalize_constraints_path`
3. **手动注入 language_tool_matrix**：在 constraints.json 中补写 `language_tool_matrix`

**不纯净原因**：test_cli_analyze.py 的 fixture 项目从未执行过真实的 `vt finalize`，所有 finalize 相关的元数据都是手动注入的。

**修复方式**：让 setup_mock_project 调用真实的 `run_finalize()` 来生成 finalize 元数据，而非手动注入。mock tool execution 仍需保留（无法在 tmp_path 中运行真实 pytest）。

**影响**：测试代码与源代码的 finalize 逻辑耦合——如果 finalize 写入的字段变了，测试中的手动注入也会过期。这正是本次重构中发现的 `conftest.py` 桥接层的根因。

---

## 四、总结

| 维度 | 差距 | 严重度 |
|---|---|---|
| 配置状态 | 从未 finalize，config.json 停留在脚手架 | CRITICAL |
| PRD 状态 | 缺少 status 字段 | MEDIUM |
| 任务列表 | 引用不存在的 GATE-VT-013/014、TASK-VT-038 | CRITICAL |
| 架构约束 | 缺少 project.language、GATE-VT-013、GATE-VT-014 定义 | CRITICAL |
| Agent Claims | CLAIM-VT-9999 phantom 引用，覆盖率低 | MEDIUM |
| 证据产出 | gate_decision 为 fail，数据过期 | HIGH |
| CI/CD | 无任何自动化门禁 | HIGH |
| Git 状态 | 50+ 文件未提交 | CRITICAL |
| 测试覆盖 | 零自管理测试 | CRITICAL |
| 测试纯净度 | 2 个测试文件含动态注入代码，fixture 文件未跟上演进 | MEDIUM |
| Prompts 引导 | prd_analysis.md 缺失，冷启动引导流断裂 | MEDIUM |
| output_dir 配置 | 可能未对齐 Phase 3 统一规范 | LOW |

---

## 五、修复顺序

因果链决定了修复必须按顺序进行，前一步是后一步的前提：

| 顺序 | 动作 | 解决的差距 |
|---|---|---|
| 1 | 提交工作树 | Git 状态（CRITICAL） |
| 2 | 修复 architecture_constraints.json（加 project.language、加 GATE-VT-013/014） | 架构约束（CRITICAL） |
| 3 | 修复 task_list.json（移除 phantom 引用或补全 GATE 定义） | 任务列表（CRITICAL） |
| 4 | 更新 change_log.md（记录本次重构） | 变更日志（CRITICAL） |
| 5 | 运行 vt finalize | 配置状态（CRITICAL） |
| 6 | 运行 vt analyze | 证据产出（HIGH） |
| 7 | 补充 prompts/ 目录（重新运行 vt init 或手动创建） | Prompts 引导（MEDIUM） |
| 8 | 修复 PRD front matter（加 status: active） | PRD 状态（MEDIUM） |
| 9 | 清理 CLAIM-VT-9999 | Claims 状态（MEDIUM） |
| 10 | 更新 fixture 样本项目（自带 finalized config + 正确 evidence_refs） | 测试纯净度（MEDIUM） |
| 11 | 精简 test_e2e_samples.py（删除动态注入代码） | 测试纯净度（MEDIUM） |
| 12 | 精简 test_cli_analyze.py（用真实 finalize 替代手动注入） | 测试纯净度（MEDIUM） |
| 13 | 确认 output_dir 配置是否需要对齐 | output_dir（LOW） |
| 14 | 添加自管理 E2E 测试（VT 自身 vt analyze → pass） | 测试覆盖（CRITICAL） |
| 15 | 添加 CI/CD workflow | CI/CD（HIGH） |

步骤 1-6 是连续链，步骤 7-13 可并行，步骤 14 依赖步骤 6（VT 自身必须先通过 analyze），步骤 15 可随时添加，步骤 16 在最后收尾。

---

## 六、收尾清理

在所有修复完成后，执行一次项目级清理，移除废弃文件和目录，让项目处于干净状态。

### 清理范围

| 清理项 | 说明 |
|---|---|
| `conftest.py`（根目录） | 如已通过 fixture 更新消除 build() kwargs 不匹配，此文件可删除 |
| `tests/conftest.py` | 同上——如果 cli.py 与 build() 的参数不匹配已修复，patch 不再需要 |
| `.vibetracing/output/` 中的旧产出 | 自管理修复后重新运行 vt analyze 会生成新产出，旧文件可删除 |
| `.vibetracing/tool_reports/` | 如已不存在则跳过；如存在但内容过期则清理 |
| `tests/fixtures/claude_bootstrap/` | 对应的源模块和测试已删除，fixtures 目录也应清理 |
| `tests/fixtures/examples/` 下过期样本 | 更新后的样本项目应与当前架构一致，过期版本应删除 |

### 不清理项

| 保留项 | 原因 |
|---|---|
| `output/*.md`（设计文档） | 保留供必要时查阅 |
| `output/base_json_report.md` | Phase 8 设计思路的演进记录 |
| `output/architecture_constraints_baseline_refactor.md` | Phase 8 最终设计文档 |
| `output/self_management_gap_analysis.md` | 本报告 |
