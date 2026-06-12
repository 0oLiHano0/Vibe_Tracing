# Analyze 阶段实施计划 — 原子化任务列表

基于 `analyze_phase_architecture_analysis.md` 的 27 个问题，按文件边界拆分 8 个原子任务。每个任务一个 subagent 可独立执行，任务间通过 git 状态传递依赖。

---

## 设计原则

1. **一个任务 = 改一个或一组内聚文件** — subagent 无需阅读其他任务
2. **每个任务包含精确的文件路径、变更位置、修改内容和验收标准**
3. **P0 bug 优先** — 第一个 wave 覆盖所有 P0+P1 问题
4. **不考虑向后兼容** — 可以推倒重构

## 依赖关系

```
Wave 1（全并行 — 7 个任务互不干扰）:
  T1: merge_gate_engine.py
  T2: architecture_compliance_checker.py
  T3: analysis.py + tools.py
  T4: reports.py + evidence_index_builder.py
  T5: dashboard_renderer.py + formatting.py
  T6: reflection_prompts.py + governance.py + ghost_code_reconciler.py
  T7: human_decisions.schema.json（更新 schema）

Wave 2:
  T8: 集成测试（依赖 T1~T7）
```

---

## T1: merge_gate_engine.py — 修复 5 个 Bug

**文件**：`src/vibe_tracing/merge_gate_engine.py`

**问题覆盖**：

| # | 问题 | 行号范围 | 严重度 |
|---|------|---------|--------|
| 3 | `check_ac_coverage` 空证据索引假阴性 | ~184-186 | CRITICAL |
| 2 | `proposal_risks`/`proposal_gaps` 未被门禁消费 | ~648-672 | CRITICAL |
| 11 | 增量模式不阻塞架构违规 | ~656-672 | MODERATE |
| 14 | 子字符串检测自引用风险 | ~352 | MINOR |
| 15 | 覆盖率阈值 80% 硬编码 | ~496 | MINOR |

### 变更 1：修复假阴性（`check_ac_coverage` 静态方法）

**当前代码**（约第 184-186 行）：
```python
if not test_results:
    # No test results available → assume passing
    has_passing_test = True
```

**改为**：
```python
if not test_results:
    has_passing_test = False
```

### 变更 2：消费 proposal_risks 和 proposal_gaps

在 `evaluate()` 方法中，读取 `compliance_result` 时增加对 `proposal_risks` 和 `proposal_gaps` 的处理（约第 648-672 行之后插入）：

```python
# 1.4 Process proposal risks from architecture change governance
if compliance_result:
    for risk in compliance_result.get("proposal_risks", []):
        risk_id = risk.get("risk_id", "")
        desc = risk.get("description", "")
        hint = resolve_hint(_gate_hints.get("proposal_risk", {}), "level1")
        msg = hint.format(risk_id=risk_id, desc=desc) if hint else f"架构变更提案风险 ({risk_id}): {desc}"
        reasons.append(self._tag_reason(msg, None, staged_items))
        if staged_items is None:
            blocked_items.append(msg)
            gate_decision = "blocked"

    for gap in compliance_result.get("proposal_gaps", []):
        gap_id = gap.get("item_id", "")
        reason_text = gap.get("reason", "")
        msg = f"架构变更治理缺口 ({gap_id}): {reason_text}"
        reasons.append(self._tag_reason(msg, None, staged_items))
        if staged_items is None:
            blocked_items.append(msg)
            gate_decision = "blocked"
```

### 变更 3：增量模式改为也阻塞架构违规

当前逻辑（约第 656-672 行）：`if staged_items is None: blocked_items.append(msg)` 只在全量模式下阻塞。改为也阻塞增量模式下的 must 级违规：

```python
# 改为：去掉 staged_items is None 的守卫
blocked_items.append(msg)
gate_decision = "blocked"
```

### 变更 4：子字符串替换为结构化识别

当前（约第 352 行）：
```python
is_self_ref = "only self-referential" in desc or "self-referential" in desc
```

改为检查 risk 对象的结构化字段（如果存在 `risk_category` 字段）：
```python
risk_category = risk.get("risk_category", "")
is_self_ref = risk_category == "self_referential_claim"
```

如果 risk 对象确实没有结构化字段，保留子字符串匹配作为 fallback。

### 变更 5：覆盖率阈值可配置

当前硬编码 80%。在 `_compute_gate_decision` 方法开头从 `self` 读取（或参数传入）阈值，默认仍为 80：
```python
coverage_threshold = getattr(self, 'coverage_threshold', 80)
```

### 验收标准
1. 空证据索引时 AC 不再假通过
2. proposal_risks/gaps 被门禁引擎消费（在 reasons 和 blocked_items 中出现）
3. 增量模式下 must 级架构违规也阻断提交
4. 自引用风险通过结构化字段识别（不再依赖子字符串）
5. 覆盖率阈值可通过属性配置
6. `pytest tests/test_merge_gate_engine.py` 全部通过

---

## T2: architecture_compliance_checker.py — 修复 4 个 Bug

**文件**：`src/vibe_tracing/architecture_compliance_checker.py`

**问题覆盖**：

| # | 问题 | 行号范围 | 严重度 |
|---|------|---------|--------|
| 4 | `allowed_to_call` 白名单对标准库误报 | ~222 | CRITICAL |
| 5 | `_find_evidence_id` 路径匹配不可靠 | ~128-139 | MODERATE |
| 9 | `"core" in parts` 排除过宽 | ~86 | MINOR |
| 13 | manual 规则不受 GATE-VT-007 约束 | ~805-818 | MODERATE |

### 变更 1：修复 `allowed_to_call` 白名单误报

**当前代码**（约第 222 行）：
```python
if allowed_ids is not None and imp_mod_id not in allowed_ids:
```

**改为**：跳过非 VT 内部导入（标准库、第三方库不参与白名单校验）：
```python
if allowed_ids is not None and imp_mod_id is not None and imp_mod_id not in allowed_ids:
```

### 变更 2：改进 `_find_evidence_id` 路径匹配

**当前**：使用 `endswith` 可能产生假匹配。

**改为**：使用 `Path` 的规范化 + 后缀级精确匹配：
```python
from pathlib import Path
norm = Path(norm_path)
ev_path_norm = Path(ev_path)
# 精确匹配或从 src 根路径的相对路径匹配
if norm == ev_path_norm or str(norm).endswith(str(ev_path_norm)):
```

更简单的方式：沿用小写 + strip 但增加到 3 个部分的 `parts` 比较：
```python
norm_parts = norm_path.strip("/\\").lower().split("/")[-3:]
if ev_path.strip("/\\").lower().split("/")[-3:] == norm_parts:
```

### 变更 3：修复 `"core" in parts` 排除过宽

**当前代码**（约第 86 行）：
```python
if "core" in parts:
    return (None, None)
```

**改为**：只排除顶层 `vibe_tracing/core/` 路径下的文件：
```python
# parts 是 relative_to(src_dir) 的路径段列表
# vibe_tracing/core/* 才会被排除
if len(parts) >= 2 and parts[0] == "vibe_tracing" and "core" in parts[1:3]:
    return (None, None)
```

### 变更 4：让 manual 规则进入 `unclear_list`

**当前代码**（约第 805-818 行）：手动规则即使未接受也不追加到 `unclear_list`。

改为也追加到 `unclear_list`（这样 GATE-VT-007 会在未接受的手动规则存在时触发）。如果这是有意的设计决策（允许人类在 Dashboard 上稍后确认），则添加注释解释原因：
```python
# Manual rules that are unaccepted DO feed into GATE-VT-007,
# so the gate blocks until human acceptance is provided.
unclear_list.append({"rule_id": r_id, "reason": f"Manual rule {r_id} not yet accepted by human"})
```

### 验收标准
1. 标准库导入不再被白名单误报为违规
2. `_find_evidence_id` 不会跨不相关文件产生假匹配
3. `"core"` 排除只影响 `vibe_tracing/core/` 路径
4. 未接受的手动规则出现在 `unclear_constraints` 中（触发 GATE-VT-007）
5. `pytest tests/test_architecture_compliance_checker.py` 全部通过

---

## T3: analysis.py + tools.py — 路径和错误处理

**文件**：`src/vibe_tracing/commands/analyze/analysis.py`、`src/vibe_tracing/commands/analyze/tools.py`

**问题覆盖**：

| # | 问题 | 文件 | 严重度 |
|---|------|------|--------|
| 10 | `_load_human_decisions()` 路径硬编码 | analysis.py:137 | MINOR |

### 变更 1：修复人类决策路径

**当前代码**（`analysis.py:137`）：
```python
decisions_path = Path(".vibetracing/human_decisions.json")
```

**改为**：接受 `project_root` 参数：
```python
def _load_human_decisions(project_root: Optional[Path] = None) -> dict:
    if project_root is None:
        project_root = Path(".")
    decisions_path = project_root / ".vibetracing" / "human_decisions.json"
```

同时更新 `pipeline.py` 中的调用点，传入 `project_root`。

### 验收标准
1. 从非项目根目录运行时也能正确加载 `human_decisions.json`
2. 不改动现有行为
3. `pytest tests/` 全部通过

---

## T4: reports.py + evidence_index_builder.py — 覆盖率数据整合

**文件**：`src/vibe_tracing/commands/analyze/reports.py`、`src/vibe_tracing/evidence_index_builder.py`

**问题覆盖**：

| # | 问题 | 文件 | 严重度 |
|---|------|------|--------|
| 6 | `build()` 存在死代码参数 | evidence_index_builder.py | MINOR |
| 7 | 空 `coverage_baseline` | evidence_index_builder.py | MODERATE |
| 19 | 覆盖率数据三重存在 | reports.py + evidence_index_builder.py | MODERATE |
| 20 | 异常被吞没 | reports.py | MODERATE |
| 26 | 冗余数据传递 | reports.py | MINOR |
| 27 | exit_code 策略嵌入 | reports.py | MINOR |

### 变更 1：移除 evidence_index_builder 死代码参数

`build()` 不再接受 `**kwargs`，只从 `ctx` 读取。

### 变更 2：将 `coverage_baseline` 数据实际填充或从 schema 中移除

如果 `coverage_baseline` 是遗留字段：从 evidence_index 的 schema 和 builder 中移除。如果是未来接口：添加注释说明。

### 变更 3：覆盖率数据唯一来源

`coverage_summary` 只在 `report_doc` 中计算一次，`coverage_baseline` 不再生成。`formatting.py` 中的 coverage_violations 从 report_doc 中提取。

### 变更 4：保留异常上下文

所有 `print() + raise _GateBlocked(1)` 改为 `raise _GateBlocked(1) from exc`，保留原始异常链。

### 验收标准
1. `EvidenceIndexBuilder.build()` 签名清洁，无死代码参数
2. 覆盖率只在 `report_doc` 中存在一份
3. 异常上下文不丢失
4. `pytest tests/` 全部通过

---

## T5: dashboard_renderer.py + formatting.py — UI 质量改进

**文件**：`src/vibe_tracing/dashboard_renderer.py`、`src/vibe_tracing/commands/analyze/formatting.py`

**问题覆盖**：

| # | 问题 | 文件 | 严重度 |
|---|------|------|--------|
| 16 | `{boot_data_json}` 始终 `"null"` | dashboard_renderer.py | MINOR |
| 17 | 脆弱的 `str.replace()` 模板注入 | dashboard_renderer.py | MINOR |
| 18 | 每次渲染重建 `ArchitectureChangeProposalEngine` | dashboard_renderer.py | MINOR |
| 21 | 16 参数函数 | formatting.py | MINOR |
| 23 | 覆盖率双重判定 | formatting.py | MODERATE |

### 变更 1：移除 boot_data_json 或实现它

如果 `{boot_data_json}` 是已失效占位符，从模板和渲染代码中移除。如果是预留特性，添加注释说明。

### 变更 2：缓存 `ArchitectureChangeProposalEngine`

在 `DashboardRenderer.__init__` 中创建一次，render 时复用：
```python
if not self._proposal_engine:
    self._proposal_engine = ArchitectureChangeProposalEngine(...)
prop_res = self._proposal_engine.check_governance(...)
```

### 变更 3：统一覆盖率判定路径

`_render_actions()` 中的两条覆盖率路径合并为一条：只使用从 report_doc 中提取的 `coverage_summary`。移除独立从 evidence_index 提取 coverage_violations 的逻辑。

### 变更 4：减少 formatting 函数参数

将多个可选参数打包为 `ActionFormatContext` 数据类。

### 验收标准
1. 无死代码变量
2. 不再每次 render 都重建 proposal engine
3. 覆盖率只在一个地方判定
4. 函数签名简洁
5. `pytest tests/` 全部通过

---

## T6: reflection_prompts.py + governance.py + ghost_code_reconciler.py — 杂项修复

**文件**：`src/vibe_tracing/reflection_prompts.py`、`src/vibe_tracing/governance.py`、`src/vibe_tracing/ghost_code_reconciler.py`

**问题覆盖**：

| # | 问题 | 文件 | 严重度 |
|---|------|------|--------|
| 24 | 文字 `\n` bug | reflection_prompts.py:208 | MINOR |
| 25 | governance 静默失败 | governance.py | MINOR |
| 8 | 重复 git 操作 | ghost_code_reconciler.py + tools.py | MINOR |
| 12 | Gap→Risk 转换不可逆 | risk_advisor.py | MINOR |
| 22 | 魔数紧急度阈值 | actions.py | MINOR |

### 变更 1：修复 `\n` bug

`reflection_prompts.py:208` — 将条件提示文本中的文字 `\n` 改为实际换行符。

### 变更 2：添加 governance 日志

`load_boundary()` 在 JSON 解析失败时打印 warning 到 stderr。

### 变更 3：缓存 git 操作

`ghost_code_reconciler.py` 中的 `_get_staged_files()` 结果在一次 reconcile 调用中缓存复用。

### 变更 4：保留 gap reason

`RiskAdvisor` 在 gap→risk 转换时保留原始 `reason` 字段到 risk 的 `original_reason` 中。

### 变更 5：配置化紧急度阈值

`actions.py` 中的 85/60/30/25 阈值改为从 config 或常量读取。

### 验收标准
1. 文字 `\n` 在反思提示输出中正确渲染为换行
2. governance 配置错误时 stderr 有日志
3. git 操作不重复执行
4. gap reason 不丢失
5. `pytest tests/` 全部通过

---

## T7: human_decisions.schema.json — 完善 action 枚举

**文件**：`src/vibe_tracing/schemas/human_decisions.schema.json`

### 变更

在 schema 的 `action` 枚举定义中添加 `reconfirm` 和 `reject`（如果尚未存在），并添加 `description` 字段区分语义：

```json
"action": {
    "type": "string",
    "enum": ["accept", "reconfirm", "reject", "accept_risk", "mark_complete", "defer"],
    "description": "决策动作类型。accept=初始人工确认（CLI端）；reconfirm=Dashboard端复核确认仍然有效；reject=Dashboard端复核认为不再适用"
}
```

### 验收标准
1. Schema 合法，通过 jsonschema 加载
2. action 枚举包含 reconfirm 和 reject（确认已存在）
3. description 解释了不同 action 的生命周期语义

---

## T8: 集成测试

**文件**：新建 `tests/test_analyze_refactor_integration.py`

**依赖**：T1~T7 全部完成

### 测试场景

| 场景 | 描述 | 验证点 |
|------|------|--------|
| 假阴性修复 | 空证据索引 + Must AC → run analyze | gate_decision = blocked |
| proposal 消费 | 创建有 proposal_risks 的 compliance_result | reasons 和 blocked_items 包含 proposal 内容 |
| 白名单修复 | 模块有 allowed_to_call，导入 os | 不产生违规 |
| 增量模式 | pre-commit 模式 + must 架构违规 | gate_decision = blocked |
| 手动规则 | manual 规则未接受 | unclear_constraints 包含该规则 |
| 覆盖率单一源 | analyze 完成 | report_doc coverage_summary 唯一存在 |
| 异常上下文 | 触发报告生成错误 | 原始异常信息保留 |

### 验收标准
1. 所有 7 个场景通过
2. `pytest tests/` 全部通过

---

## 执行完成状态（2026-06-12）

### 最终测试：902/902 通过

| 任务 | 状态 | 方式 | 说明 |
|------|:----:|------|------|
| T1 merge_gate_engine.py | ✅ | Agent 重跑 | 5 个 Bug 修复，82 测试通过 |
| T2 compliance_checker.py | ✅ | 手动补齐 | 4 个 Bug 修复，22 测试通过 |
| T3 analysis.py + pipeline.py | ✅ | 手动补齐 | 路径硬编码修复 |
| T4 reports.py + evidence_index | ✅ | 手动补齐 | 覆盖率整合 + 异常上下文 + exit_code |
| T5 dashboard + formatting | ✅ | Agent 重跑 | boot_data移除 + 引擎缓存 + 覆盖率统一 + 参数精简，902 测试通过 |
| T6 minor fixes | ✅ | Agent 重跑 | \n bug + 静默失败日志 + gap_reason + 紧急度常量化，902 测试通过 |
| T7 schema | ✅ | 首轮保留 | action 语义说明 |
| T8 集成测试 | ✅ | Agent 重跑 | 7 个端到端场景，10 个测试函数 |

### 实际修复统计

| 严重度 | 修复数 | 问题编号 |
|--------|--------|---------|
| CRITICAL | 3 | #3 假阴性, #2 proposal丢弃, #4 白名单误报 |
| MODERATE | 7 | #1 accepted_rule 语义, #5 路径匹配, #9 core排除, #11 增量阻断, #13 manual规则, #19 覆盖率三重, #20 异常吞没 |
| MINOR | 17 | #6-7 死代码, #10 路径硬编码, #12 gap_reason, #14 自引用, #15 覆盖率阈值, #16-18 boot_data/模板/缓存, #21-27 参数/魔数/治理日志/n bug |

**未完成项（架构债务，延后）**：见 `analyze_phase_arch_gaps.md` 的 7 个架构级优化空间（Pipeline 模块化、Canonical Model、Typed Context、结构化日志、VCS 抽象、策略收敛、并行工具）。这些属于结构性改造，需独立规划。

### 流程教训

1. worktree isolation 模式下 agent 变更在隔离分支上，`git branch -D` 会丢失 commits。正确做法是用 `git worktree remove` 或在 agent 完成后立即 merge。
2. 直接模式（无 isolation）的 agent 变更直接落在 working tree，更可靠但缺少隔离。
3. 核查阶段发现大量遗漏，说明 agent 的"已完成"报告不可完全信赖，必须以实际文件 diff 为准。
