# Agent Action 输出 UX 瑕疵（3 项）

**状态**：待排期
**创建**：2026-07-04
**来源**：PHASE-VT-015 验证阶段识别
**关联**：
- `docs/design_agent_action_unification.md`
- `docs/tech_debt/design_requires_human_field.md`（requires_human 字段为独立条目，不在本文范围）

> 本文档记录 PHASE-VT-015 验证过程中发现的 3 个 UX / 实现瑕疵。三者**非架构性问题**（架构级 channel 分离问题见 `docs/design_channel_separation.md`），但影响用户感知与 Agent 消费质量。

---

## UX 瑕疵 1：「预存债务」术语与 OutputState 语义不对齐

### 位置

`src/vibe_tracing/cli/analyze/formatting.py:58`

```python
pre_existing_count = sum(1 for a in actions if 20 <= a.get("urgency", 0) < 80)
lines.append(f"当前变更: {current_change_count} 项 | 预存债务: {pre_existing_count} 项 | 等待人类: {pending_human_count} 项")
```

### 问题

`pre_existing_count` 用 **urgency 区间 `[20, 80)`** 划分「预存债务」，但 urgency 50 的 action 实际是 **CURRENT_WARNING**（activated=true），**不是 HISTORICAL**。同一份终端输出里：

- Gate summary 的 `[预存]`（output.py `_STATE_LABELS`）= **HISTORICAL 状态**
- Agent summary 的 `预存债务: X 项` = **urgency < 80**（含 CURRENT 态）

**同一术语承载两套语义**，用户在 Agent action 区看到 "预存债务: 7 项" 会误以为 HISTORICAL 泄漏到了 Agent（PHASE-VT-015 验证时即产生此误判）。

### 风险等级

**中**（误导用户理解，但不影响功能正确性）

### 建议修复

按 OutputState 对齐命名：

```python
current_block_count = sum(1 for a in actions if a.get("urgency", 0) >= 70 and a.get("priority") == "HIGH")
current_warning_count = sum(1 for a in actions if a.get("urgency", 0) == URGENCY_WARNING)
lines.append(f"当前阻拦: {current_block_count} 项 | 当前告警: {current_warning_count} 项 | 等待人类: {pending_human_count} 项")
```

或直接使用 OutputState 标签（需在 action 中携带 state 字段）。

---

## UX 瑕疵 2：Baseline 快照缺乏更新机制

### 位置

`src/vibe_tracing/domain/gate/baseline.py::BaselineManager.generate_snapshot()`

### 问题

`generate_snapshot()` 仅在 `.vibetracing/baseline.json` 不存在时创建，永不更新。后果：

- baseline 锁定到项目**首次运行**时的 issue 集合
- 之后新产生的 issue（即便与旧 task 关联）一律 `observed=false` → CURRENT
- 长期演进后，baseline 与"当前代码库债务基线"语义持续漂移

PHASE-VT-015 验证时 7 个 CURRENT issue 的 fingerprint 均不在 baseline（526 个）中，根因即此。

### 风险等级

**中**（债务识别精度随项目演进退化）

### 建议修复

`design_rule_engine.md` 未明确 baseline 更新策略。可选方案：

| 方案 | 触发时机 | 优点 | 缺点 |
|---|---|---|---|
| A. `vt finalize` 重建 baseline | 架构定稿时 | 与现有 finalize 流程绑定，语义清晰 | 未 finalize 的项目 baseline 永不过期 |
| B. 周期性刷新 | PHASE 结束 / N 次 analyze 后 | 自动保鲜 | 触发条件难界定 |
| C. 显式 `vt baseline --refresh` | 用户主动 | 人类控制 | 增加 CLI 复杂度 |

推荐 **方案 A**（`vt finalize` 重建），理由：baseline 语义是"架构定稿那一刻的债务快照"，与 finalize 天然匹配。

### 落地前置

需先明确 baseline 的设计意图（是"一次性初始化"还是"债务基线"），再选方案。建议在 `docs/design_rule_engine.md` 的 Baseline 章节补充策略说明。

---

## UX 瑕疵 3：Risk reason 文本重复拼接

### 位置

`src/vibe_tracing/domain/gate/engine.py` 的 risk 类检测器（`_check_must_risks` / `_check_should_risks`）产出的 `reason` 字段

### 问题

终端输出示例：

```
高风险或自引用 (RISK-VT-193): 验收标准 AC-VT-001-01 缺失通过的测试证据。。
为关联 Claim 补充外部验证证据，或将 claimed_status 降级。。为关联 Claim 补充外部验证证据，或将 claimed_status 降级。
```

`reason` 字段本身就把 `suggested_action` 拼了两遍（句号 `。。` 也是格式瑕疵）。来源是 risk 评估器或 engine 的 reason 构造端，**非** action 收集端。

### 风险等级

**低**（输出可读性差，不影响功能）

### 建议修复

1. 检查 `_check_must_risks` / `_check_should_risks` 中 reason 构造逻辑，定位重复拼接点
2. 检查 `field_hints.json` 中 risk 相关 level1 模板是否自带 suggested_action 占位符
3. 规范化句号：hint 模板第一句已含句号时，不再追加

---

## 排期建议

| 项 | 优先级 | 工作量 | 前置依赖 |
|---|---|---|---|
| UX 瑕疵 1（术语对齐） | 中 | 30 分钟 | 无 |
| UX 瑕疵 2（baseline 刷新） | 中 | 2-4 小时（含设计决策） | `design_rule_engine.md` 策略补充 |
| UX 瑕疵 3（reason 拼接） | 低 | 1 小时（含定位） | 无 |

三者可作为独立 TASK 推进，不绑定特定 PHASE。

**注意**：上述 3 项在 channel 分离架构落地后可能需要重新评估（参见 `docs/design_channel_separation.md`）。特别是 UX 瑕疵 1 的"预存债务"标签，若 channel 分离后终端不再承载 HISTORICAL 信息，术语冲突自然消失。
