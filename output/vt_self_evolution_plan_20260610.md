# VT 自我进化与演进计划

## 一、 概述 (Overview)

本轮进化（v2 决策平台 + v3 证据链重设计 + 根因修复 + 代码质量治理）完成后，Gate PASS、928 测试全通过。但 VT 的价值闭环尚未真正运转：claims 归档后为空，Dashboard 展示空数据，人类无法验收。

下一轮核心目标：**让 VT 的完整流程在有 claims 的情况下也能 PASS，并让 Dashboard 展示有意义的信息供人类验收。**

---

## 二、 诊断与反思 (Diagnostics & Reflections)

- **Reflect ID**: EVO-REF-025
  - **Violation Principle**: 1 (项目不足识别)
  - **Diagnosis**: Claims 归档后 current.json 为空（0 claims）。Gate PASS 是因为没有 claims 就没有风险，不是因为质量真的好。Dashboard 展示空数据，人类无法做出验收判断。
  - **Root Cause**: VT 的价值闭环依赖 claims，但 claims 的创建和生命周期管理完全依赖 Agent 的手动操作。没有自动化的"Agent 工作 → claims 生成 → VT 验证 → Dashboard 展示 → 人类验收"闭环。
  - **Affected Scope**: `src/vibe_tracing/cli.py`（analyze 流程）、`src/vibe_tracing/templates/dashboard.template.html`
  - **Status**: ❌ 未解决

---

## 三、 原子化动作指令 (Atomic Action Tasks)

- [ ] **Task ID**: EVO-TASK-041
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 在 `vt analyze` 流程中，如果 `claims/current.json` 为空，自动生成一个最小化的 claim 模板。从 `git diff --cached` 获取 staged 文件列表，生成一个 claim 包含 `code_refs`（staged 的业务文件）和 `test_refs`（staged 的测试文件）。写入 `claims/current.json`。这样 Agent 不需要手动创建 claims，VT 自动从 git 状态推导。
  - **AC**: `vt analyze --pre-commit` 在 claims 为空时自动从 staged 文件生成 claim；生成的 claim 包含正确的 code_refs 和 test_refs；Gate check_claim_exists 通过

- [ ] **Task ID**: EVO-TASK-042
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 在 `vt analyze` 流程中，如果 claims 非空且 `test_results` 为空（首次运行或 claims 刚生成），自动调用 `_run_claim_tests` 跑 pytest。将结果写入 evidence_index。这样 Dashboard 能展示真实的测试结果，而不是空数据。
  - **AC**: `vt analyze` 首次运行时自动执行 claim 的 test_refs 中的 pytest；evidence_index 包含 test_results；Dashboard 展示测试通过/失败状态

- [ ] **Task ID**: EVO-TASK-043
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/templates/dashboard.template.html`
  - **Instruction**: Dashboard 的"待决策"标签页展示当前 claims 的验证状态：每个 claim 的 test_refs 有哪些、pytest 通过/失败、AC 覆盖情况。让人类看到"Agent 做了什么、测试结果是什么、哪些 AC 被覆盖"的完整故事链，而不是空数据。
  - **AC**: Dashboard 在有 claims 时展示 claim 验证状态卡片；每个卡片包含 claim_id、test_refs 列表、测试结果、AC 覆盖状态

- [ ] **Task ID**: EVO-TASK-044
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 在 `vt analyze` 输出的行动清单中，如果 claims 为空且没有 staged 文件，输出提示："当前无 claims 且无 staged 文件。请先 git add 变更文件，或手动创建 claims/current.json。"让 Agent 知道下一步该做什么。
  - **AC**: `vt analyze` 在无 claims 且无 staged 文件时输出明确的下一步提示

---

## 四、 关联与依赖

```
EVO-041 (自动生成 claim) ← 无依赖
EVO-042 (自动跑 pytest) ← 依赖 EVO-041（需要有 claim 才能跑测试）
EVO-043 (Dashboard 展示) ← 依赖 EVO-042（需要有测试结果才能展示）
EVO-044 (空状态提示) ← 无依赖，可与 EVO-041 并行
```

---

## 五、 建议执行顺序

```
Batch 1: EVO-041 + EVO-044
  ↑ 2 个任务并行，修改不同区域

Batch 2: EVO-042
  ↑ 依赖 EVO-041（需要有 claim）

Batch 3: EVO-043
  ↑ 依赖 EVO-042（需要有测试结果）
```

**预计总耗时**：约 1-2 小时

---

## 附录：历史债务清单（不在本进化计划中）

以下反思项属于历史债务，应另立清理任务，不纳入功能进化：

| 反思项 | 性质 | 清理方向 |
|---|---|---|
| EVO-REF-026 cli.py 2915 行 | 历史债务 | 按命令拆分为 commands/ 目录 |
| EVO-REF-027 _run_claim_tests 性能 | 历史债务 | 添加增量机制 |
| EVO-REF-028 evidence_index 全量重写 | 历史债务 | 增量更新 |
| EVO-REF-029 缺少端到端测试 | 历史债务 | 补充验收测试 |
| EVO-REF-030 cli.py 结构优化 | 历史债务 | 同 EVO-REF-026 |
| EVO-REF-031 语义审计单不适应 | 历史债务 | 删除或简化机制 |
| EVO-REF-032 claim_credibility.py 空模块 | 历史债务 | 删除文件 |
