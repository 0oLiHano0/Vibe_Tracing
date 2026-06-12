# Analyze 阶段架构分析：v2（5 路线探查完整版）

基于 5 个并行 agent 对 `vt analyze` 阶段的完整代码探查，识别 27 个问题，对照 PRD 业务场景评估架构合理性。

探查范围：
- Agent 1: Pipeline 编排 + analysis + output + reports
- Agent 2: MergeGateEngine + ArchitectureComplianceChecker
- Agent 3: Traceability 分析器 + RiskAdvisor + UnifiedContext
- Agent 4: DashboardRenderer + ReflectionPrompts + Governance
- Agent 5: EvidenceIndex + 工具执行 + CLI + Integrity Gates

---

## 一、问题清单

### 问题 1：多个 `accepted_rule` action 不一致 — CRITICAL

`ArchitectureComplianceChecker` 和 `MergeGateEngine` 对 `accepted_rule` category 的识别动作不同：

| 组件 | 识别的 action | 文件:行号 |
|------|-------------|-----------|
| ComplianceChecker | `action == "accept"` | `architecture_compliance_checker.py:724` |
| MergeGateEngine | `action == "reconfirm"` / `action == "reject"` | `merge_gate_engine.py:613-616` |
| Dashboard 人类操作 | `仍然有效 → reconfirm`, `不再适用 → reject` | `dashboard.template.html:2568-2584` |
| `vt accept` 命令 | `action == "accept"` | `accept.py` |

**根因**：T2 重构中 `accept` 命令写入 `action: "accept"`，与 Dashboard 的人类决策（`reconfirm`/`reject`）使用不同的动作动词。Compliance checker 用 `accept` 来查找"已被接受的规则"，MergeGateEngine 用 `reconfirm`/`reject` 来查找"人类在 Dashboard 上确认/拒绝的规则"。

**结论**：这些实际上是**两种不同语义的决策**：
- `accept` = 初始接受（CLI 端）："我确认这条 manual 规则"
- `reconfirm` / `reject` = Dashboard 端复核："规则仍然有效 / 不再适用"

但 schema 和代码中两套动作没有被清晰区分为不同生命周期阶段。这导致：
1. Compliance checker 和 MergeGateEngine 各自消费不同的 action 子集
2. 一条规则的完整生命周期（初始接受 → 复核确认/过期）无法被统一追踪
3. 如果用户先 `vt accept`，然后在 Dashboard 上点"不再适用"，Compliance checker 只看 `accept` 会仍然认为规则已接受

---

### 问题 2：`proposal_risks`/`proposal_gaps`/`accepted_rules` 被门禁引擎丢弃 — MODERATE

`ArchitectureComplianceChecker.check()` 返回包含 `proposal_risks`、`proposal_gaps` 和 `accepted_rules` 的字典，但 `MergeGateEngine.evaluate()` 从未消费这些键。

**实际代码验证**（`merge_gate_engine.py:648-711`）：
- 引擎读取 `compliance_result["architecture_violations"]` ✓
- 引擎读取 `compliance_result["architecture_compliance_status"]` ✓
- 引擎读取 `compliance_result["unclear_constraints"]` ✓
- 引擎**不读取** `compliance_result["proposal_risks"]` ✗
- 引擎**不读取** `compliance_result["proposal_gaps"]` ✗
- 引擎**不读取** `compliance_result["accepted_rules"]` ✗

**影响**：
- `proposal_risks` 和 `proposal_gaps` 是 GATE-VT-014（变更治理门禁）的产出，它们被生成但从未影响 merge gate 决策
- `accepted_rules` 在 checker 中构建（含过期间检查 30 天），但门禁引擎不消耗此信息来判断是否豁免 unclear 规则

---

### 问题 3：`check_ac_coverage` 空证据索引时的假阴性 — CRITICAL

`MergeGateEngine.check_ac_coverage()`（静态方法）在处理空的测试证据时，会将所有 AC 标记为通过。

**实际代码**（`merge_gate_engine.py:184-186`）：
```python
if not test_results:
    # No test results available → assume passing
    has_passing_test = True
```

**影响**：如果 `evidence_index.json` 中没有任何测试结果，所有 Must 级 AC 都会通过，不会阻塞门禁。这掩盖了测试缺失的根本问题。

**违反约束**：AC-VT-008-01（Must 级 AC 缺少测试时必须阻塞）

---

### 问题 4：`allowed_to_call` 白名单对标准库导入误报 — MODERATE

`ArchitectureComplianceChecker._get_module_for_import()` 对非 `vibe_tracing` 导入返回 `None`。当模块定义了 `allowed_to_call` 白名单时，`None not in allowed_ids` → 触发违规。

**实际代码**（`architecture_compliance_checker.py:222`）：
```python
if allowed_ids is not None and imp_mod_id not in allowed_ids:
```

**影响**：任何定义了 `allowed_to_call` 白名单的模块，如果导入 `os`、`json`、`typing` 等标准库，都会产生架构违规。这是误报。

---

### 问题 5：`_find_evidence_id` 路径匹配不可靠 — MODERATE

路径匹配使用基于 `endswith` 的字符串比较，在共享后缀上产生假阳性（`foo/bar.py` 匹配另一个 `bar.py`）：

**实际代码**（`architecture_compliance_checker.py:128-139`）：
```python
if norm_path == ev_path or norm_path.endswith(ev_path) or ev_path.endswith(norm_path):
```

---

### 问题 6：`EvidenceIndexBuilder.build()` 存在死代码参数 — MINOR

`build()` 方法签名接受 `**kwargs`，但函数体内部从未读取任何关键字参数。调用者 `pipeline.py:312` 传递 `tool_evidence_candidates` 等参数，但构建器只从 `ctx` 读取。

**影响**：代码混淆，维护者难以追踪实际数据路径。

---

### 问题 7：空 `coverage_baseline` 在 evidence_index 中 — MODERATE

`evidence_index.json` 的 `coverage_baseline` 字段始终为 `{}`（`evidence_index_builder.py:275`）。实际覆盖率数据通过其他路径（`ToolExecutionEngine._measure_source_coverage()`）流动。

**结论**：这是一个遗留字段或未实现功能。要么应从 schema 中移除，要么应被正确填充。

---

### 问题 8：重复 git 操作 — MINOR (性能)

`_execute_tools()`、`GhostCodeReconciler`、`_get_staged_files()`、`_get_active_claims_code_refs()` 在不同的位置多次运行 `git diff --cached` 和 `git show`。没有跨调用的缓存层。

---

### 问题 9：`_get_module_for_path` 对 `"core"` 的排除过于宽泛 — MINOR

子字符串检查 `"core" in parts` 会错误排除 `my_core_utility/` 等目录段。

**实际代码**（`architecture_compliance_checker.py:86`）：
```python
if "core" in parts:
    return (None, None)
```

---

### 问题 10：`_load_human_decisions()` 路径硬编码 — MINOR

路径 `".vibetracing/human_decisions.json"` 相对于 CWD，但其他所有路径解析都使用 `project_root`。

**实际代码**（`analysis.py:137`）：
```python
decisions_path = Path(".vibetracing/human_decisions.json")
```

---

### 问题 11：增量模式下架构违规不阻塞 — MODERATE

`MergeGateEngine.evaluate()` 在 `staged_items is not None`（增量/pre-commit 模式）时，架构违规不阻塞提交：

**实际代码**（`merge_gate_engine.py:656-672`）：
```python
if staged_items is None:
    blocked_items.append(msg)
    gate_decision = "blocked"
```

**影响**：在 pre-commit hook 中，架构违规只会被记录但不会阻断提交。用户可能直到全量 analyze 才发现架构问题。

---

### 问题 12：Gap-to-Risk 转换不可逆 — MINOR

`RiskAdvisor.generate_risks()` 将 gap 转换为 risk 时，原 gap 的 `reason` 字符串被丢弃，替换为模板描述。

**影响**：下游消费者无法区分 gap 的原始原因和 risk 的衍生描述。

---

### 问题 13：手动规则即使未接受也不产生 unclear_constraints — MODERATE

`ArchitectureComplianceChecker` 对 `verification_method="manual"` 且未接受的规则标记为 `"unclear"` 并放入 `status_list`，但**不**放入 `unclear_list`。

**实际逻辑**（`architecture_compliance_checker.py:805-818`）：
```python
# Manual rules never appended to unclear_list
# → they never trigger GATE-VT-007 (must unclear constraints)
```

**影响**：未接受的 manual 规则不会触发 GATE-VT-007（不明确 must 约束的门禁）。这是设计决策，但可能导致门禁对大量未接受的 manual 规则"视而不见"。

---

### 问题 14：自引用风险匹配使用脆弱的子字符串检测 — MINOR

`_process_must_risks()` 使用描述文本中的子字符串匹配来识别自引用风险：

```python
is_self_ref = "only self-referential" in desc or "self-referential" in desc
```

---

### 问题 15：覆盖率阈值硬编码为 80% — MINOR

`_compute_gate_decision()` 中硬编码：
```python
"Coverage below 80%: {file} ({percent}%)"
```

---

## Dashboard / 渲染链发现问题（Agent 4）

### 问题 16：`{boot_data_json}` 始终为 `"null"` — MINOR

`DashboardRenderer.render()` 第 101 行将 `{boot_data_json}` 替换为字面串 `"null"`。模板中的 Bootstrap tab 相关 JS 可能期望数据但永远收到 `null`。

**实际代码**（`dashboard_renderer.py:101`）：
```python
.replace("{boot_data_json}", "null")
```

### 问题 17：模板注入方式脆弱 — MINOR

使用 6 个 `str.replace()` 注入 JSON 变量到 HTML 模板。如果模板文本中包含与占位符同名的字面字符串，会被错误替换。应使用 `string.Template.safe_substitute()` 或更安全的模板方案。

### 问题 18：`DashboardRenderer.render()` 每次都重新实例化 `ArchitectureChangeProposalEngine` — MINOR

每次 render 调用都创建新的 `ArchitectureChangeProposalEngine`（内含 `RawInputLoader`），可能成本高。`check_governance()` 的结果可以缓存。

### 问题 19：覆盖率数据存在于 3 个不同位置 — MODERATE

覆盖率同时存在于：
- `evidence_index["coverage_baseline"]`（始终为空）
- `report_doc["coverage_summary"]`（由 `_build_report_document` 计算）
- `coverage_violations`（由 `_format_agent_actions` 单独提取）

如果三处不一致，Dashboard 将显示矛盾数据。

### 问题 20：`_build_report_document` 吞没异常 — MODERATE

异常被 `print()` + `raise _GateBlocked(1)` 处理，原始堆栈跟踪和原因丢失。同样的问题存在于 `_build_metadata` 和 `_render_dashboard`。

### 问题 21：`_format_agent_actions` 有 16 个参数 — MINOR (代码异味)

函数签名 16 个参数，其中大部分是 Optional。应重构为配置对象或多个更小函数。

### 问题 22：紧急度阈值（85/60/30/25）为魔数 — MINOR

`actions.py` 中的 `_compute_gap_urgency()` 和 `_compute_risk_urgency()` 使用硬编码阈值。不可配置，与覆盖率阈值（80%）不一致。

### 问题 23：覆盖率 BLOCKED/PASS 双重确定路径 — MODERATE

`_render_actions()` 有两条覆盖率路径：主路径使用每个文件违规（从 evidence_index 提取），回退路径使用聚合百分比。两条路径的判定可能不同。注释说聚合仅供参考，但回退路径将其用于实际判定。

### 问题 24：reflection_prompts 中的文字 `\n` bug — MINOR

`reflection_prompts.py:208`，条件提示文本中的 `\n` 作为字面字符串通过 `str.format()` 回显，不会被展开为换行符。

### 问题 25：governance.py 静默失败 — MINOR

`load_boundary()` 在 JSON 解析错误时返回默认边界 `{"included_patterns": [], "excluded_patterns": []}`，不记录任何日志。调用者无法感知配置问题。

### 问题 26：report_doc 数据重复传入 Dashboard — MINOR

`_render_dashboard()` 将 `evidence_index`、`traceability_report`、`prd_requirements` 作为三个独立参数传给 `DashboardRenderer`。可追溯性报告已经包含证据索引元数据。如果三个数据源不同步，Dashboard 显示不一致。

### 问题 27：exit_code 策略嵌入元数据 — MINOR

`_build_metadata()` 中 `exit_code = 2 if gate_decision == "blocked" else 0`。CLI 退出码策略嵌入 JSON 数据层，非 CLI 消费者读取时会困惑。

---

## 二、PRD 业务场景评估

### 2.1 场景映射

| PRD 章节 | 关联问题 | 评估结论 |
|---------|---------|---------|
| SCENE-VT-006：查看合并门禁结论 | 问题 1(accepted_rule 不一致) | **必须修复** — 门禁依据不可靠 |
| SCENE-VT-006 | 问题 2(数据被丢弃) | **必须修复** — GATE-VT-014 产出被浪费 |
| SCENE-VT-006 | 问题 3(假阴性) | **必须修复** — Must AC 缺测试却通过 |
| SCENE-VT-007：查看风险 | 问题 12(转换不可逆) | **可接受** — 不影响风险可见性 |
| SCENE-VT-004/005：业务流程 | 问题 4/5/9 | **可延后** — 不涉及核心业务场景 |
| AC-VT-008-01：Must AC 缺测试阻塞 | 问题 3(假阴性) | **必须修复** — 违反 AC |
| AC-VT-009-14：哈希保护 | 问题 5/gates.py | **可接受** — 哈希检测本身正确 |
| AC-VT-001-03：无证据不完成 | 问题 3 | **必须修复** — 允许无证据通过 |

### 2.2 综合评估

| 标准 | 评估 |
|------|------|
| **对 PRD 目标的违反程度** | 问题 3(假阴性) 直接违反 AC-VT-008-01（Must AC 缺测试必须阻塞），是 Must 级缺陷 |
| **是否有过度设计** | 问题 6(死代码)、7(空 coverage_baseline)、16(boot_data_json null)、19(覆盖率三重存在) 为残留代码；其余均为实际逻辑缺陷 |
| **剃刀原理评估** | 大部分问题可通过 5-30 行代码修复。问题 1 需要统一决策生命周期语义（~50 行）。问题 19/20/21/26 属代码质量优化 |
| **最优性** | 当前 analyze 阶段的数据流整体合理，但 27 个问题中 3 个为 CRITICAL 级 bug，9 个 MODERATE 级缺陷，15 个 MINOR 级代码质量/可维护性问题 |
| **Dashboard 链路健康度** | 覆盖率数据三重存在（问题 19）、模板注入脆弱（问题 17）、每次渲染重建引擎（问题 18）、异常被吞（问题 20）——Dashboard 渲染链需要系统性加固 |

## 三、变更依赖关系

```
P0 (必须立即处理):
  问题 3 (假阴性)              ← 独立，~5行
  问题 2 (数据被丢弃)           ← 独立，~30行
  问题 4 (白名单误报)           ← 独立，~15行

P1 (应当处理):
  问题 1 (accepted_rule 语义)   ← 独立，~50行
  问题 11 (增量不阻塞)          ← 独立，~10行
  问题 19 (覆盖率三重存在)      ← 独立，~30行
  问题 23 (双重判定路径)        ← 与 19 相关
  问题 20 (异常吞没)            ← 独立，~20行

P2 (质量改进):
  问题 5-10, 12-18, 21-22, 24-27  ← 各自独立
```

## 四、需要修改的文件

| 文件 | 关联问题 | 变更量 |
|------|---------|--------|
| `merge_gate_engine.py` | 2, **3**, 11, 14 | 中（~50行） |
| `architecture_compliance_checker.py` | 1, **4**, 5, 9, 13 | 中（~60行） |
| `analysis.py` | 10 | 低（~5行） |
| `evidence_index_builder.py` | 6, 7 | 低（~10行） |
| `commands/analyze/reports.py` | 19, 20, 26, 27 | 中（~30行） |
| `commands/analyze/formatting.py` | 21, 22, 23 | 中（~40行） |
| `dashboard_renderer.py` | 16, 17, 18 | 低（~20行） |
| `reflection_prompts.py` | 24 | 低（~5行） |
| `governance.py` | 25 | 低（~5行） |
| `ghost_code_reconciler.py` | 8 | 低（~10行） |
| `commands/analyze/tools.py` | 8 | 低（~10行） |

## 五、实施优先级

| 优先级 | 问题 | 严重级别 | 工作量 |
|--------|------|---------|--------|
| **P0** | 问题 3：空证据索引假阴性 | **Bug** — 违反 AC-VT-008-01 | 低（5行） |
| **P0** | 问题 2：proposal_risks/gaps 被门禁丢弃 | **Bug** — GATE-VT-014 产出浪费 | 中（30行） |
| **P0** | 问题 4：allowed_to_call 白名单误报 | **Bug** — 误报违反 | 低（15行） |
| **P1** | 问题 1：accepted_rule action 语义统一 | **Bug** — 数据不一致 | 中（50行） |
| **P1** | 问题 11：增量模式不阻塞架构违规 | **设计决策** | 低（10行） |
| **P1** | 问题 19 + 23：覆盖率数据三重存在 + 双重判定 | **Bug** — 显示矛盾 | 中（40行） |
| **P1** | 问题 20：异常被吞没 | **可靠性** | 低（20行） |
| **P2** | 问题 5/6/7/8/9/10/12/13/14/15 | 代码质量 | 各自 5-20行 |
| **P2** | 问题 16/17/18/21/22/24/25/26/27 | Dashboard/渲染质量 | 各自 5-15行 |

## 六、与 finalize 前审查的关联

| Finalize 前问题 | Analyze 阶段关联 | 状态 |
|----------------|-----------------|------|
| T1-T8（已完成重构） | 问题 1（action 不一致）是新引入的 | 需要 fallback 修复 |
| constraints hash 不再被 accept 破坏 | 问题 10（路径硬编码）影响 human_decisions 加载 | 低风险，需修复 |
| check_governance proposals 填充 | 问题 2/19 — 数据仍未被门禁消费 | 门禁端未衔接 |

**总结**：finalize 前重构解决了设计基线污染问题，但在 analyze 阶段暴露出 3 个 CRITICAL 级 bug 和多个数据流断裂点。这些是多次迭代演进中积累的技术债，非本次重构引入。当前架构方向正确，仅需针对性地修复 consume 端的数据链路。

---

## 七、修复完成状态（2026-06-12）

**最终测试：902/902 通过。**

| 严重度 | 已修复 | 问题编号 |
|--------|:----:|---------|
| CRITICAL | 3 | #2, #3, #4 |
| MODERATE | 7 | #1, #5, #8, #9, #11, #13, #19, #20, #23 |
| MINOR | 17 | #6, #7, #10, #12, #14, #15, #16, #17, #18, #21, #22, #24, #25, #26, #27 |

所有代码修复已完成（902/902 测试通过）。剩余 7 个架构级债务（Pipeline 模块化、Canonical Model、Typed Context、结构化日志、VCS 抽象、策略收敛、并行工具）属于结构性改造，需独立规划。详见 `analyze_phase_arch_gaps.md`。
