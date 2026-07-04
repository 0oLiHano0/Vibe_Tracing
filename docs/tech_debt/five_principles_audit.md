# 五原则审查记录

**审查日期**: 2026-07-04
**审查依据**: P1 不考虑向后兼容 / P2 不接受打补丁式重构 / P3 不得过度设计 / P4 不得重复代码逻辑 / P5 测试文件视同业务代码
**审查范围**: `src/vibe_tracing/` + `tests/`

---

## P1 — 旧架构残留（13 项）

### 高优先级（死代码）

| # | 位置 | 问题 | 状态 |
|---|---|---|---|
| 1 | `tests/test_prd_draft_guidance.py` | 整个文件是空壳，0 个测试函数，仅为已删除功能留墓碑 | 待修复 |
| 2 | `infra/config/enums.py:96-102` | `TASK_STATUS_TO_COVERAGE` 常量，`src/` 中无任何引用，但有专属测试文件 | 待修复 |
| 3 | `domain/task/session.py:86-90` | `TaskSession.to_dict()` 方法，`src/` 和 `tests/` 中从未调用 | 待修复 |

### 中优先级（向后兼容参数/路径）

| # | 位置 | 问题 | 状态 |
|---|---|---|---|
| 4 | `domain/compliance/prd_arch_validator.py:48` | `project_prefix` 参数显式标注 unused，有测试验证其无效果 | 待修复 |
| 5 | `domain/governance/metrics.py:96` | `sessions` 参数显式标注"未使用，保留签名便于二期"（为假想未来预留，违反 P3） | 待修复 |
| 6 | `cli/analyze/pipeline.py:609` | `session_mgr is None` 降级路径，文档写"保留旧行为"，但 pipeline 总是传入非 None | 待修复 |
| 7 | `cli/analyze/db_analysis.py:249,258` | `evidence_list=[]`、`claims_analysis=[]`、`claim_risks=[]` 三个永远为空的参数 | 待修复 |
| 8 | `infra/config/hint_loader.py:47` | `resolve_hint()` 的 `isinstance(str)` 分支，文档写 "Backward compatible" | 待修复 |

### 低优先级（无用 import / re-export）

| # | 位置 | 问题 | 状态 |
|---|---|---|---|
| 9 | `cli/__init__.py:16,27` | `subprocess` re-export + `_GateBlocked` re-export，无消费者 | 待修复 |
| 10 | `cli/analyze/channel.py:16` / `domain/capability/metrics.py:20` / `domain/governance/metrics.py:16` / `domain/task/acceptance.py:22` / `domain/task/business_impact.py:17` / `domain/task/session.py:20` | `from __future__ import annotations` 但实际用的是 `Optional[]`/`Dict[]`，import 无效果 | 待修复 |
| 11 | `cli/analyze/actions.py:7` | 未使用的 `Optional` import | 待修复 |
| 12 | `cli/analyze/output.py:13` | 未使用的 `STATUS_OK` import | 待修复 |
| 13 | `domain/gate/signal_computer.py:13` | 未使用的 `Severity` import | 待修复 |

---

## P2 — 打补丁式重构（3 项）

| # | 位置 | 问题 | 状态 |
|---|---|---|---|
| 14 | `cli/analyze/actions.py:86-101` | `_get_related_code` / `_get_existing_tests` 纯透传 wrapper，可直接调 query 函数 | 待修复 |
| 15 | `domain/gate/staleness.py:11-54` | `determine_affected_items` 定义但生产代码不调用，`mark_staleness` 内联了相同逻辑 | 待修复 |
| 16 | `cli/analyze/pipeline.py:525-532` | `_run_analysis_phase` 仅 3 行列表过滤，只被调用一次，不值得独立函数 | 待修复 |

---

## P3 — 过度设计

无独立发现（#5 已归入 P1 中优先级）。

---

## P4 — 重复逻辑（6 项）

| # | 位置 | 问题 | 状态 |
|---|---|---|---|
| 17 | `domain/task/acceptance.py:37` vs `domain/task/session.py:280` | `_ARCH_ISSUE_TYPES` 集合字面量 `{"chain_broken", "chain_misaligned", "substandard"}` 定义了两处 | 待修复 |
| 18 | `domain/task/acceptance.py:67-68` vs `domain/task/session.py:182-183` | `sorted_tasks` + `default_task` + "分配 issue 到 task 或 fallback 到 default" 模式完全重复 | 待修复 |
| 19 | `cli/analyze/db_analysis.py:236-241` vs `cli/analyze/reports.py:234-239` | `constraints_hash` 从 manifest 提取的循环逐字符相同 | 待修复 |
| 20 | `cli/analyze/reports.py:183` vs `cli/analyze/pipeline.py:727` | `exit_code = 2 if gate_decision == "blocked" else 0` 重复计算 | 待修复 |
| 21 | `domain/gate/engine.py:29` / `cli/analyze/pipeline.py:483` / `cli/init.py:73` / `infra/loader/config.py:35` / `cli/finalize.py:156` | `config.json` 路径构造 + 读取各自独立实现，绕过了 `loader/config.py` 的 `load_config` | 待修复 |
| 22 | `tests/test_phase1_mvp_e2e.py:39-57` vs `tests/test_pipeline_t194.py:42-50` | `_ctx_stub` helper 几乎相同，应提取到 `conftest.py` | 待修复 |

---

## P5 — 测试质量（3 项）

| # | 位置 | 问题 | 状态 |
|---|---|---|---|
| 23 | `tests/test_prd_draft_guidance.py` | 空文件（同 #1） | 待修复 |
| 24 | `tests/test_self_governance.py:34,39` | 同一 JSON 文件连续读取解析两次，第二次冗余 | 待修复 |
| 25 | `tests/test_cli_stub.py` | 仅测 argparse 版本/帮助输出，无业务价值 | 待评估 |

---

## 统计

| 原则 | 高 | 中 | 低 | 合计 |
|---|---|---|---|---|
| P1 旧架构残留 | 3 | 5 | 5 | 13 |
| P2 打补丁式重构 | — | 3 | — | 3 |
| P3 过度设计 | — | — | — | 0（#5 已归 P1） |
| P4 重复逻辑 | — | 6 | — | 6 |
| P5 测试质量 | 1 | 1 | 1 | 3 |
| **合计** | **4** | **15** | **6** | **25** |

## 建议修复顺序

1. P1 高优先级（#1-3）：删除死代码，风险最低
2. P4（#17-22）：消除重复逻辑，防止后续修改遗漏
3. P1 中优先级（#4-8）：移除向后兼容参数/路径
4. P1 低优先级（#9-13）：清理无用 import
5. P2（#14-16）：消除透传 wrapper 和内联重复
6. P5（#24-25）：测试文件清理
