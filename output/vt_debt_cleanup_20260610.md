# VT 历史债务清理计划

## 目标

清理 7 项历史债务，消除对新设计评估的干扰。清理完成后，VT 的代码库应该只包含新设计的逻辑，没有旧机制残留和结构债务。

---

## 债务清单

| ID | 债务 | 来源 | 清理方式 |
|---|---|---|---|
| DEBT-032 | claim_credibility.py 空模块（26 行） | v3 根因修复残留 | 删除文件 |
| DEBT-031 | 语义审计单不适应新设计 | 旧机制与新设计不匹配 | 删除或跳过 |
| DEBT-027 | _run_claim_tests 无增量 | 实现时未考虑性能 | 添加增量机制 |
| DEBT-028 | evidence_index 全量重写 | 实现时未考虑增量 | 增量更新 |
| DEBT-026 | cli.py 2915 行 | 开发过程累积 | 按命令拆分 |
| DEBT-030 | cli.py 结构优化 | 同上 | 同上 |
| DEBT-029 | 缺少端到端测试 | 测试覆盖不完整 | 补充验收测试 |

---

## 原子化任务

### Batch 1：快速清理（3 个并行任务）

---

#### DEBT-TASK-001：删除 claim_credibility.py

- **目标文件**：`src/vibe_tracing/traceability/claim_credibility.py`（删除）
- **变更内容**：
  - 删除文件
  - 检查并删除所有 import 引用（`from vibe_tracing.traceability.claim_credibility import assess_claim_credibility`）
  - 删除 `tests/test_claim_credibility.py`（所有测试都测试已清空的函数）
- **验证**：`grep -rn 'claim_credibility' src/ tests/ --include='*.py'` 返回 0；`pytest tests/ -x -q` 全部通过

---

#### DEBT-TASK-002：删除语义审计单机制

- **目标文件**：`src/vibe_tracing/semantic_auditor.py`（删除或清空）、`.git/hooks/pre-commit`（修改）
- **变更内容**：
  - 在 pre-commit hook 中删除语义审计单的 pending 状态检查逻辑
  - 保留 claim 存在性检查（Gate check_claim_exists）作为唯一的 ghost code 检测
  - 删除 `.vibetracing/semantic_audit.json` 文件
  - 删除 `src/vibe_tracing/semantic_auditor.py` 或清空为空模块
  - 删除 cli.py 中对 semantic_auditor 的调用
  - 删除相关测试
- **验证**：`git commit` 不再触发语义审计单检查；`pytest tests/ -x -q` 全部通过

---

#### DEBT-TASK-003：删除 legacy agent_claims.json 路径引用

- **目标文件**：所有引用 `agent_claims.json` 的文件
- **变更内容**：
  - 搜索 `agent_claims.json` 的所有引用
  - 删除 fallback 逻辑和 legacy 路径
  - 确认所有引用都指向 `claims/current.json`
- **验证**：`grep -rn 'agent_claims\.json' src/ --include='*.py'` 返回 0

---

### Batch 2：性能优化（2 个并行任务）

---

#### DEBT-TASK-004：_run_claim_tests 增量机制

- **目标文件**：`src/vibe_tracing/cli.py`
- **变更内容**：
  - 在 evidence_index 中记录每个 test_ref 的 `last_run_time` 和 `result_hash`
  - `_run_claim_tests` 执行前，检查 test_ref 的文件 mtime
  - 如果 mtime 早于 `last_run_time`，复用上次结果，不重新跑 pytest
  - 只对 mtime 晚于 `last_run_time` 的 test_ref 跑 pytest
  - 更新 evidence_index 中的记录
- **验证**：连续两次 `vt analyze`，第二次不重新跑未变化的测试（通过执行时间差异验证）

---

#### DEBT-TASK-005：evidence_index 增量更新

- **目标文件**：`src/vibe_tracing/evidence_index_builder.py`
- **变更内容**：
  - `build()` 方法先读取已有的 `output/evidence_index.json`
  - 对比每个源文件的 mtime 与 evidence_index 中的 `scan_time`
  - 只对 mtime 晚于 scan_time 的文件重新生成证据条目
  - 未变化的条目复用已有数据
  - 更新 `scan_time` 为当前时间
- **验证**：连续两次 `vt analyze`，第二次的 evidence_index.json 中未变化的条目保持不变

---

### Batch 3：cli.py 结构重构（1 个任务）

---

#### DEBT-TASK-006：cli.py 按命令拆分

- **目标文件**：`src/vibe_tracing/cli.py`（拆分）、`src/vibe_tracing/commands/`（新增）
- **变更内容**：
  - 创建 `src/vibe_tracing/commands/` 目录
  - 创建 `__init__.py`、`init.py`、`finalize.py`、`analyze.py`、`doctor.py`、`accept.py`
  - 将 `run_init` → `commands/init.py`
  - 将 `run_finalize` → `commands/finalize.py`
  - 将 `run_analyze` + `_evaluate_and_output` + 所有子函数 → `commands/analyze.py`
  - 将 `run_doctor` → `commands/doctor.py`
  - 将 `run_accept` → `commands/accept.py`
  - 将 `_load_context` → `commands/common.py`
  - 将 `_execute_tools` → `commands/analyze.py`
  - cli.py 变为薄编排层：只保留 `main()` + 参数解析 + 命令分发
- **验证**：`vt init/finalize/analyze/doctor/accept` 功能不变；`pytest tests/ -x -q` 全部通过；cli.py < 300 行

---

### Batch 4：验收测试（1 个任务）

---

#### DEBT-TASK-007：端到端验收测试

- **目标文件**：`tests/test_acceptance.py`（新增）
- **前置依赖**：DEBT-TASK-006（commands/ 结构稳定）
- **变更内容**：
  - 使用 VT 项目自身的 PRD、task_list 作为输入
  - 运行完整 `vt analyze` 流程
  - 验证：evidence_index 非空、traceability_report 非空、Dashboard 包含有意义的数据
  - 不 mock subprocess，使用真实 pytest 执行
  - 测试运行时间 < 60 秒
- **验证**：`pytest tests/test_acceptance.py -v` 全部通过

---

## 执行顺序

```
Batch 1（并行）:
  DEBT-001 (删除 claim_credibility.py) ─┐
  DEBT-002 (删除语义审计单) ────────────┤
  DEBT-003 (删除 legacy 路径) ──────────┤
                                         ├→ 完成后进入 Batch 2
Batch 2（并行）:
  DEBT-004 (_run_claim_tests 增量) ─────┐
  DEBT-005 (evidence_index 增量) ───────┤
                                         ├→ 完成后进入 Batch 3
Batch 3:
  DEBT-006 (cli.py 按命令拆分) ─────────→ 完成后进入 Batch 4

Batch 4:
  DEBT-007 (端到端验收测试) ───────────→ 完成
```

**预计总耗时**：Batch 1（20 分钟）+ Batch 2（30 分钟）+ Batch 3（2-3 小时）+ Batch 4（30 分钟）= 约 3.5-4.5 小时

---

## 验收标准

清理完成后，VT 应满足：
1. `grep -rn 'claim_credibility\|semantic_audit\|agent_claims\.json' src/ --include='*.py'` 返回 0
2. `vt analyze` 在有 claims 时能自动跑测试并生成有意义的 Dashboard
3. cli.py < 300 行，按命令拆分到 commands/ 目录
4. `pytest tests/ -x -q` 全部通过
5. 端到端验收测试通过
