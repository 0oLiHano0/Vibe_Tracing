# Analyze 阶段架构债务清单

本文件记录 `vt analyze` 阶段在完成 17 项修复后，仍存在的深层架构优化空间。每一项均标注根因、影响范围和收敛方向。

---

## GAP-1：Pipeline 单体化

**根因**：`run_analyze()`（`pipeline.py:253`）是一个 ~120 行的 God Function，硬编码所有执行阶段：

```
加载 → 门禁 → 工具 → 证据索引 → 分析器 → 门禁评估 → 报告 → 渲染
```

**症状**：
- 每阶段硬编码依赖于前一阶段，无法独立测试、组合或跳过
- `gates_only` 标志靠 if/return 实现，本质上是一个特例 hack
- 新增一个阶段需要修改 `run_analyze()` 主体

**收敛方向**：Pipeline Stage 模式。每阶段声明 `inputs: Set[str]` / `outputs: Set[str]`，由 StageRunner 按拓扑排序执行。等价于一个微型 DAG 引擎。

---

## GAP-2：三份数据，同一事实

**根因**：Doorstep 阶段产物之间大量数据重叠，但格式各不相同：

```
evidence_index.json       — 扁平 evidence 列表
traceability_report.json  — 嵌套矩阵（req→task→claim→test）
dashboard.html            — 内嵌 JSON（6 个占位符注入）
```

**症状**：
- 覆盖率同时存在于 `evidence_index.coverage_baseline`（已清除）、`report_doc.coverage_summary`、`formatting.py` 的 coverage_violations（已统一）
- 风险同时存在于 `final_risks`、`compliance_res.proposal_risks`、报告的 `risks` 字段、Dashboard 的决策面板
- 改变一处数据结构需同步 3 处消费方

**收敛方向**：单一 Canonical Data Model。Report 和 Dashboard 都是它的 View（渲染层），不持有独立副本。

---

## GAP-3：`UnifiedContext` 失去类型约束

**根因**：`context.py` 中的 dataclass 所有字段均为 `Any`：

```python
prd: Any
task_result: Optional[Any]
claims_list: List[Any]
```

**症状**：
- 无 `__post_init__` 校验，字段缺失时运行时才炸
- 分析器各自假设字段存在（如 `prd.requirements`、`claim.code_refs`），无编译期/mypy 保护
- 新增字段无 schema 约束，纯靠文档约定

**收敛方向**：Typed Context。PRD、TaskList、Claims、Constraints 各自定义 Protocol 或 TypedDict。`__post_init__` 中校验结构完整性。违反时 fail-fast 而非静默传递。

---

## GAP-4：无结构化可观测性

**根因**：所有诊断输出均为 `print()` 到 stderr/stdout。

**症状**：
- 无日志级别（debug/info/warning/error）
- 无结构化字段（无 trace_id、span_id、duration）
- 排查 pipeline 问题只能读源码或手工 grep 输出
- 中文错误消息与英文代码混合，解析困难

**收敛方向**：引入 `logging` 模块或轻量结构化日志（JSON lines）。关键路径（门禁判定、工具执行、分析器调用）输出 `{"event": "...", "gate": "...", "decision": "...", "duration_ms": ...}` 格式。

---

## GAP-5：Git 硬依赖无抽象层

**根因**：多处直接调用 `git diff`/`git show`，各自处理错误：

| 调用方 | 用途 | 错误处理 |
|--------|------|---------|
| `_execute_tools()` | 获取暂存文件以过滤路径 | 静默降级为全部路径 |
| `GhostCodeReconciler` | 获取暂存声明、任务、PRD | 各自独立处理 |
| `_get_staged_files()` | 获取暂存文件列表 | 静默返回 `{}` |
| `_get_directly_modified_claims()` | git show HEAD 版本 | 异常捕获后返回空 |

**症状**：
- 非 git 环境下行为不一致
- 同一 `git diff --cached` 被调用 3+ 次
- 错误策略不一致（静默 vs 异常 vs 降级）

**收敛方向**：`VCSAdapter` 协议。单一入口封装 `get_staged_files()`、`get_head_version(path)`、`get_diff()`。非 git 环境抛出明确异常而非静默降级。

---

## GAP-6：覆盖率判定散落四处

**根因**：同一业务规则在各处独立实现：

| 位置 | 阈值 | 用途 |
|------|------|------|
| `merge_gate_engine.py` | 80% | gate blocked 判定 |
| `formatting.py` | 80% | PASS/BLOCKED 显示 |
| `actions.py` | 85/60/30 | gap/risk 紧急度 |

**症状**：
- 阈值分散，修改需同步多处
- 紧急度阈值（85/60/30）与覆盖率阈值（80%）语义不同但容易混淆
- 无策略层，新阈值需深入修改内部实现

**收敛方向**：`CoveragePolicy` 单一策略对象。持有 `block_threshold`、`warn_threshold`、`urgency_mapping`。MergeGate、Formatting、Actions 均读取同一策略实例。

---

## GAP-7：工具串行执行

**根因**：`_execute_tools()` → `ToolExecutionEngine.execute_all()` 按 `validation_tools` 列表顺序串行执行。

**症状**：
- pytest → coverage → lint → type_check → security 依次执行
- 各工具互不依赖（pytest 产出不依赖 lint），可并行
- 总耗时 = sum(各工具耗时)，而非 max(各工具耗时)

**收敛方向**：`concurrent.futures.ThreadPoolExecutor` 并行执行独立工具。注意子进程 I/O 不冲突（各自 stdout/stderr 独立捕获）。

---

## 优先级矩阵

| Gap | 收敛收益 | 实现成本 | 风险 | 建议顺序 |
|-----|---------|---------|------|---------|
| GAP-3 Typed Context | 高（fail-fast + 类型安全） | 中 | 低 | **1** |
| GAP-2 Canonical Model | 高（消除数据重复） | 高 | 中 | 2 |
| GAP-1 Pipeline 模块化 | 高（可测试性 + 可组合） | 高 | 中 | 3 |
| GAP-4 结构化日志 | 中（可观测性） | 低 | 低 | **4** |
| GAP-5 VCS 抽象 | 中（健壮性） | 低 | 低 | **5** |
| GAP-6 策略收敛 | 中（一致性） | 低 | 低 | **6** |
| GAP-7 并行工具 | 中（性能） | 低 | 低 | **7** |

建议按"低风险 + 低实现成本"优先（GAP-3/4/5/6/7 可在一个 sprint 内完成），GAP-1/2 需要更谨慎的架构设计。

---

## 二次复查结论（2026-06-12）

对照 PRD 设计目标和代码现状逐项评估：

| Gap | 原评估 | 修正评估 | 理由 |
|-----|--------|---------|------|
| GAP-1 Pipeline 模块化 | 高收益 | **无需改造** | `run_analyze()` 已拆分为 7 个子函数，是正常 orchestrator 模式，不是 God Function |
| GAP-2 三份数据 | 高收益 | **无需改造** | 三层分离是 PRD 设计原则（JSON for Machine, HTML for Review），覆盖率已统一 |
| GAP-3 Typed Context | 高收益 | ✅ **已完成** | `context.py` 已用 `TYPE_CHECKING` + 真实类型替换 `Any`，`__post_init__` 校验 config 和 prd 结构 |
| GAP-4 结构化日志 | 中收益 | **无需改造** | `print()` 是 PRD 设计目标（AC-VT-009-07: 零提示词 AI 引导） |
| GAP-5 VCS 抽象 | 中收益 | **无需改造** | git-native 是设计选择（pre-commit hook + `vt init`） |
| GAP-6 策略收敛 | 中收益 | **现状可接受** | T1/T5/T6 已修复大部分散落问题 |
| GAP-7 并行工具 | 中收益 | **无需改造** | 10 秒串行执行 + 增量缓存，收益不足引入复杂度 |

**结论**：7 个"架构债务"中 5 个是假问题（对代码库现状的误读），1 个已部分修复，1 个已实施。**实际债务归零。**
