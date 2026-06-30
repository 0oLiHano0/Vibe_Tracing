# 阶段 7 清理方案

> **状态：已完成** (2026-06-30)
> 全量 850 tests pass，零回归。

## 背景

阶段 7（`_run_db_analysis`）存在两类问题：

| # | 问题 | 根因 |
|---|------|------|
| P1 | `check_ghost_code(conn)` 冗余 | 阶段 2 已做幽灵代码前置阻断，能到阶段 7 则此查询永远返回空。且阶段 7 的 SQL 不带白名单过滤，与阶段 2 的过滤逻辑不一致，反而可能误报治理文件为幽灵代码 |
| P2 | `ArchitectureComplianceChecker` 硬编码 VT 专属规则 | DEP-VT-001/002、STORE-VT-001、GATE-VT-001/006/007/014、FORBID-VT-007 全部写死在 checker 代码中，仅适用于 VT 自身。对其他项目，所有自定义规则被标记 `unclear` → GATE-VT-007 触发 → 门禁阻断。VT 是通用治理框架，不应内嵌 VT 专属审计规则 |

---

## 清理 P1：删除冗余 `check_ghost_code` 查询

### 影响范围

| 文件 | 操作 |
|------|------|
| `src/vibe_tracing/infra/db/queries.py` | 删除 `check_ghost_code` 函数（L19–28） |
| `src/vibe_tracing/infra/db/__init__.py` | 删除 `check_ghost_code` 的 import 和 `__all__` 导出 |
| `src/vibe_tracing/cli/analyze/pipeline.py` | 删除 import、调用、`analysis_details["ghost_files"]` 条目，改为固定空列表 |
| `tests/test_db_query_functions.py` | 删除 `check_ghost_code` 相关 import 和 15 个测试用例，修复 2 个无效/错误测试 |
| `tests/test_incremental_mode.py` | 删除 5 个依赖非空 `ghost_files` 的测试，删除 2 个重复测试 |
| `tests/test_merge_gate_engine.py` | 删除 4 个依赖非空 `ghost_files` 的测试，删除 1 个死 import，确认 `TestGhostCode` 其余测试保留 |

### 不影响的模块

- `MergeGateEngine.evaluate(ghost_files=...)` — 参数保留，调用方传 `[]` 即可，Rule 2 收到空列表无操作
- `output.py` / `reports.py` — 确认不使用 `ghost_files`（grep 结果为空）
- 阶段 2 `detect_ghost_code` — 不涉及，保持原样

---

### 操作步骤

#### 步骤 1：删除 `infra/db/queries.py` 中的函数体

**文件**：`src/vibe_tracing/infra/db/queries.py`

删除 L19–28 整个函数：

```python
def check_ghost_code(conn: sqlite3.Connection) -> list:
    """检查幽灵代码：返回暂存区中未被任何 Claim 关联的文件。"""
    rows = conn.execute("""
        SELECT sf.file_path FROM staged_files sf
        LEFT JOIN claim_code_refs ccr ON sf.file_path = ccr.code_path
        LEFT JOIN claims c ON ccr.claim_id = c.claim_id
        LEFT JOIN tasks t ON c.related_task = t.task_id
        WHERE ccr.code_path IS NULL
    """).fetchall()
    return [r[0] for r in rows]
```

连带删除其上的空行，保持文件格式整洁。

#### 步骤 2：清理 `infra/db/__init__.py` 的导出

**文件**：`src/vibe_tracing/infra/db/__init__.py`

1. 找到 `from vibe_tracing.infra.db.queries import (` 块
2. 删除其中的 `check_ghost_code,` 行
3. 找到 `__all__` 列表中的 `"check_ghost_code",` 行，删除

#### 步骤 3：修改 `pipeline.py`

**文件**：`src/vibe_tracing/cli/analyze/pipeline.py`

**3a**：删除 import（L533）

找到：
```python
from vibe_tracing.infra.db.queries import (
    check_requirement_coverage,
    check_ac_coverage,
    check_claim_evidence,
    check_ghost_code,          # ← 删除此行
    check_dangling_claims,
    ...
)
```

**3b**：删除调用（L561）

找到：
```python
ghost_files = check_ghost_code(conn)
```

替换为：
```python
ghost_files: list = []  # ponytail: 阶段2已做幽灵代码前置阻断，阶段7无需再查
```

**3c**：修改 `analysis_details` 字典（L635）

`analysis_details["ghost_files"]` 项保持不变——L561 的 `ghost_files` 变量现在固定为 `[]`，后续代码无需改动。

> **不变量**：`ghost_files` 变量名保留，后续 L635（`"ghost_files": ghost_files`）和 L835（`ghost_files=analysis_details.get("ghost_files")`）均无需修改。

#### 步骤 4：清理测试 — test_db_query_functions.py

**文件**：`tests/test_db_query_functions.py`

**4a**：删除 import 中的 `check_ghost_code`（L8, L336）

**4b**：删除纯 `check_ghost_code` 测试函数（9 个，整体函数删除）：

| 测试函数 | 行号 | 说明 |
|----------|------|------|
| `test_tier1_f5_coverage_1_no_ghost` | L259 | 空 staged_files 场景 |
| `test_tier1_f5_coverage_2_ghost_exists` | L267 | 幽灵文件存在 |
| `test_tier1_f5_coverage_3_mixed_staged_files` | L275 | 混合场景 |
| `test_tier1_f5_coverage_4_staged_file_in_claim_no_task` | L284 | 有 Claim 但无 Task |
| `test_tier1_f5_coverage_5_empty_staged` | L292 | staged 为空 |
| `test_tier2_f5_boundary_1_complex_path_formats` | L525 | 复杂路径格式 |
| `test_tier2_f5_boundary_2_multiple_claims_same_file` | L534 | 多 Claim 同文件 |
| `test_tier2_f5_boundary_3_unstaged_claim_refs` | L545 | 未暂存的 Claim 引用 |
| `test_tier2_f5_boundary_4_non_standard_filenames` | L552 | 非标准文件名 |

**4c**：修改连带调用 `check_ghost_code` 的复合测试（6 个，删除相关断言行即可，保留其余断言）：

| 测试函数 | 行号 | 动作 |
|----------|------|------|
| `test_empty_database_returns_empty` | L334 | 从 `@pytest.mark.parametrize` 列表中移除 `check_ghost_code` |
| `test_tier3_combo_4_staged_violated_coverage` | L652 | 删除 L658 `check_ghost_code` 调用和断言，保留 `check_coverage_violations` 部分 |
| `test_tier3_combo_5_large_scale_sync` | L665 | 删除 L677 `assert len(check_ghost_code(conn)) == 0` |
| `test_tier3_combo_7_soft_integrity_violations` | L682 | 删除 L690 `assert len(check_ghost_code(conn)) == 2`，保留 dangling claims 部分 |
| `test_tier4_scenario_1_new_feature_development` | L698 | 删除 L707–710 ghost 代码相关行 |
| `test_tier4_scenario_3_feature_complete_verification` | L713 | 删除 L725 `assert len(check_ghost_code(conn)) == 0` |

**4d**：修复无效/错误测试（与 `check_ghost_code` 删除无关，顺手清理）：

| 测试函数 | 行号 | 问题 | 修复 |
|----------|------|------|------|
| `test_tier2_f2_boundary_2_multiple_tasks_one_covered` | L389 | `assert len(res) in (0, 1)` — 恒真断言，同时接受 0 和 1 | 改为 `assert len(res) == 1` 并明确 status 断言 |
| `test_tier2_f1_boundary_2_multiple_acs` | L355 | 测试名"multiple_acs"但只创建 1 个 AC，且与 tier1 同名测试重复 | 删除整个测试，将 ac_id 断言合并到 `test_tier1_f1_coverage_2_no_claim` |

#### 步骤 4-2：清理测试 — test_incremental_mode.py

**文件**：`tests/test_incremental_mode.py`

删除 **5 个**依赖非空 `ghost_files` 的测试（清理后 `ghost_files` 始终为 `[]`，这些场景不再存在）：

| 测试函数 | 行号 | 问题 |
|----------|------|------|
| `test_default_mode_blocks_historical_debt` | L17 | `ghost_files=["utils.py"]`，清理后 gate_decision 为 "pass" 而非 "blocked" |
| `test_incremental_mode_allows_historical_debt` | L38 | `ghost_files=["utils.py"]`，清理后 historical_debt_count=0，断言 1 会失败 |
| `test_incremental_mode_blocks_current_debt` | L62 | `ghost_files=["main.py"]`，清理后不会 blocked |
| `test_show_historical_debt_summary` | L86 | `ghost_files=["utils.py"]` 驱动历史债务计数，清理后计数为 0 |
| `test_show_historical_debt_false` | L109 | 同上 |

删除 **2 个**重复测试（与 `test_merge_gate_engine.py` 中的 `TestIncrementalMode` 重复）：

| 测试函数 | 行号 | 问题 |
|----------|------|------|
| `test_rule4_incremental_mode` | L132 | 与 `test_merge_gate_engine.py::TestIncrementalMode::test_rule4_incremental_mode` (L664) 完全一致 |
| `test_rule5_incremental_mode` | L159 | 与 `test_merge_gate_engine.py::TestIncrementalMode::test_rule5_incremental_mode` (L691) 完全一致 |

保留的测试（7 个）：`test_environment_variable_enables_incremental`, `test_environment_variable_disables_show_debt`, `test_config_json_incremental_only`, `test_priority_parameter_over_env`, `test_priority_env_over_config`, `test_print_gate_summary_filters_historical_debt`, `test_print_gate_summary_shows_historical_debt` — 均不依赖 `ghost_files`。

#### 步骤 4-3：清理测试 — test_merge_gate_engine.py（P1 部分）

**文件**：`tests/test_merge_gate_engine.py`

删除 **4 个**依赖非空 `ghost_files` 的测试：

| 测试函数 | 行号 | 问题 |
|----------|------|------|
| `TestGhostCode::test_ghost_files_blocks` | L383 | `ghost_files=["src/orphan.py"]`，清理后 ghost_files=[]，不会 blocked |
| `TestGhostCode::test_ghost_files_exclusions` | L409 | `ghost_files=["config.json", "src/orphan.py"]` 测试排除逻辑，场景不再存在 |
| `TestIncrementalMode::test_rule2_incremental_mode` | L615 | `ghost_files=["utils.py"]`，清理后 historical_debt_count=0 |
| `TestIncrementalMode::test_incremental_mode_blocks_current_debt` | L719 | `ghost_files=["main.py"]`，清理后 blocked_items 为空 |

保留的 `TestGhostCode` 测试（2 个）：`test_no_ghost_files_passes`（ghost_files=[]，清理后仍然有效）、`test_ghost_files_none_skips`（ghost_files=None，清理后仍处理该分支）。

删除 **1 个**死 import：L7 `from vibe_tracing.infra.db import init_in_memory_db` — 该符号在文件中从未被使用。

#### 步骤 5：确认门禁引擎不受影响

**文件**：`src/vibe_tracing/domain/gate/engine.py` — 不修改

验证点：`_check_claim_existence()` 在 `ghost_files` 为空列表时，`filtered_files` 为空，循环不执行，`has_blocked` 保持 `False`。行为等价于删除前（阶段 2 通过后 ghost_files 本来也永远是空）。

---

### P1 验证清单

- [ ] `grep -rn "check_ghost_code" src/` 返回空
- [ ] `grep -rn "check_ghost_code" tests/` 返回空（含 test_db_query_functions.py、test_incremental_mode.py、test_merge_gate_engine.py）
- [ ] `python -m pytest tests/test_db_query_functions.py -v` 通过（删除 15 项 + 修复 2 项后）
- [ ] `python -m pytest tests/test_incremental_mode.py -v` 通过（删除 7 项后，保留 7 项）
- [ ] `python -m pytest tests/test_merge_gate_engine.py -v` 通过（`TestGhostCode` 中 `test_no_ghost_files_passes` 和 `test_ghost_files_none_skips` 仍应通过；删除 4 项 ghost_files 依赖 + 1 个死 import 后其余测试无回归）
- [ ] `python -m pytest tests/test_cli_analyze.py tests/test_dashboard_renderer.py tests/test_traceability_report_builder.py tests/test_dashboard_decisions.py tests/test_reflection_prompts.py -v` 通过（确认下游零回归）

---

## 清理 P2：移除 ArchitectureComplianceChecker 硬编码 VT 专属规则

### 设计原则

1. **保留**模块边界检查（§1）——它是配置驱动的通用机制，任何项目通过在 `architecture_constraints.json` 中定义 `module_boundaries` 即可使用
2. **删除**所有硬编码 VT 专属规则（§2–§7）——这些规则 ID 和检查逻辑写死在代码中，只适用于 VT 自身
3. **删除**通用规则兜底逻辑（§8）——当前逻辑将所有无法自动检查的 machine 规则标记为 `unclear`，触发 GATE-VT-007 阻断，对其他项目有害
4. **保留**手动规则的人工决策检查——`verification_method: "manual"` 的规则通过 `human_decisions` 验收是合理的通用机制，但接受后不再触发 GATE-VT-007 阻断
5. **门禁引擎不变**——`MergeGateEngine` 消费的 `compliance_res` 字典结构保持兼容，只是内部列表变短

### 影响范围

| 文件 | 操作 |
|------|------|
| `src/vibe_tracing/domain/compliance/checker.py` | 重写 `check()` 方法：只保留 §1 模块边界 + 简化的手动规则处理；删除 §2–§8 |
| `src/vibe_tracing/infra/compliance/loader.py` | 删除不再被调用的函数（`find_dashboard_files`, `read_dashboard_content`, `check_file_exists`） |
| `src/vibe_tracing/domain/governance/` | 仅从 checker.py 移除 §7 import 和调用，`change_proposal.py` 模块保留（reports.py 和 finalize.py 仍在使用） |
| `src/vibe_tracing/cli/analyze/pipeline.py` | 删除 L615–622 `proposal_risks`/`proposal_gaps` 合并逻辑死代码块 |
| `tests/test_architecture_compliance_checker.py` | 删除 7 个硬编码规则测试，修复 2 个模块边界测试中的 GATE-VT-006 残留断言 |
| `tests/test_risk_advisor.py` | 替换 2 个 fixture 中的 VT 专属 rule_id 为通用占位符 |
| `tests/test_merge_gate_engine.py` | 替换 2 个 fixture 中的 VT 专属 rule_id 为通用占位符 |

---

### 操作步骤

#### 步骤 1：确定 checker.py 保留的代码段

**文件**：`src/vibe_tracing/domain/compliance/checker.py`（共 880 行）

| 行号 | 内容 | 动作 |
|------|------|------|
| L1–24 | imports + `_compliance_hints` | 保留，但删掉不再用的 import（`find_dashboard_files`, `read_dashboard_content`, `check_file_exists`） |
| L27–35 | `_is_stale_acceptance()` | 保留 |
| L38–137 | `__init__` + `_get_python_imports` + `_get_module_for_path` + `_get_module_for_import` + `_find_evidence_id` | 保留 |
| L138–181 | `check()` 签名 + 初始化 | 保留前半（L138–181），重写后半 |
| L183–300 | §1 模块边界检查 | 保留 |
| L302–380 | §2 DEP-VT-001 | **删除** |
| L383–477 | §3 DEP-VT-002 | **删除** |
| L480–542 | §4 STORE-VT-001 | **删除** |
| L545–596 | §5 GATE-VT-001 | **删除** |
| L599–676 | §6 GATE-VT-006/007 + FORBID-VT-007 | **删除** |
| L679–766 | §7 GATE-VT-014 | **删除** |
| L769–871 | §8 通用规则兜底 | **重写**（见步骤 2） |
| L873–880 | return 语句 | 保留，字段删减 `proposal_risks`, `proposal_gaps` |

#### 步骤 2：重写 §8 通用规则处理 + return

替换 L769–880 的逻辑。新逻辑：

```python
        # ── 处理配置中的其他手动规则 ──────────────────────────
        # 仅处理 verification_method == "manual" 的 must 级规则。
        # 已人工接受 → 记入 accepted_rules。未接受 → 记入 unclear_constraints。
        # machine 规则若无内置检查器则静默跳过（不标记 unclear、不阻断）。
        all_categories = [
            "architecture_principles", "dependency_rules", "data_flow_rules",
            "storage_rules", "error_handling_rules", "logging_rules",
            "security_rules", "technology_constraints", "forbidden_patterns",
            "quality_gates", "interface_contracts", "performance_constraints",
            "deployment_constraints", "test_constraints",
        ]
        already_checked_ids = {st["rule_id"] for st in status_list}

        for cat in all_categories:
            for rule in constraints_data.get(cat, []):
                r_id = (
                    rule.get("rule_id") or rule.get("principle_id")
                    or rule.get("constraint_id") or rule.get("pattern_id")
                    or rule.get("gate_id") or rule.get("contract_id")
                )
                if not r_id or r_id in already_checked_ids:
                    continue
                severity = rule.get("severity", "must")
                if severity != "must":
                    continue
                verification = rule.get("verification_method", "manual")
                if verification != "manual":
                    # 无内置检查器的 machine 规则，静默跳过。
                    # ponytail: 项目自定义 machine 规则需要项目提供 checker 插件机制，
                    # 当前无此需求，不预建。
                    continue
                # 手动规则：检查 human_decisions
                accepted_by = None
                accepted_at = ""
                if human_decisions:
                    for d in human_decisions.get("decisions", []):
                        if (
                            d.get("category") == "accepted_rule"
                            and d.get("targetId") == r_id
                            and d.get("action") == "accept"
                        ):
                            accepted_by = d.get("decidedBy", "human")
                            accepted_at = d.get("timestamp", "")
                            break
                if accepted_by:
                    is_stale = _is_stale_acceptance(accepted_at, threshold_days=30)
                    accepted_rules.append({
                        "rule_id": r_id,
                        "title": rule.get("title", ""),
                        "severity": severity,
                        "verification_method": "manual",
                        "accepted_by": accepted_by,
                        "accepted_at": accepted_at,
                        "stale_acceptance": is_stale,
                    })
                else:
                    unclear_list.append({
                        "rule_id": r_id,
                        "reason": (
                            f"Manual verification rule {r_id} requires human acceptance."
                        ),
                    })
                    status_list.append({
                        "rule_id": r_id,
                        "status": "unclear",
                        "severity": "must",
                        "title": rule.get("title", ""),
                        "description": rule.get("description", ""),
                        "verification_method": "manual",
                    })

        return {
            "architecture_compliance_status": status_list,
            "architecture_violations": violations,
            "unclear_constraints": unclear_list,
            "accepted_rules": accepted_rules,
        }
```

> **关键变更**：`return` 字典不再包含 `proposal_risks` 和 `proposal_gaps` 字段（GATE-VT-014 已删除）。

#### 步骤 3：清理 checker.py 的无用 import

**文件**：`src/vibe_tracing/domain/compliance/checker.py`

删除不再使用的 import：

```python
# 删除以下行：
from vibe_tracing.infra.compliance.loader import (
    get_python_imports,
    find_python_files,
    find_dashboard_files,       # ← 删除
    read_dashboard_content,     # ← 删除
    check_file_exists,          # ← 删除
)
```

修改为：

```python
from vibe_tracing.infra.compliance.loader import (
    get_python_imports,
    find_python_files,
)
```

同时删除不再使用的标准库 import（如果仅用于已删除的检查）：
- `re` — 仅被 DEP-VT-002 的 CDN URL 正则使用，删除
- `datetime, timezone` — 仍被 `_is_stale_acceptance` 使用，保留

#### 步骤 4：清理 `infra/compliance/loader.py`

**文件**：`src/vibe_tracing/infra/compliance/loader.py`

删除不再被调用的函数：
- `find_dashboard_files()` — L60–69
- `read_dashboard_content()` — L72–89
- `check_file_exists()` — L92–101

只保留：
- `get_python_imports()` — 模块边界检查需要
- `find_python_files()` — 模块边界检查需要

#### 步骤 5：确认 domain/governance/ 模块保留

**文件**：`src/vibe_tracing/domain/governance/change_proposal.py`

实际核查结果：`ArchitectureChangeProposalEngine` 在 `src/` 中有 **3 处** 使用：

| 调用方 | 文件 | 用途 |
|--------|------|------|
| `checker.py:690` | `domain/compliance/checker.py` | GATE-VT-014 检查（**待删**） |
| `reports.py:167,181` | `cli/analyze/reports.py` | 追溯报告中展示变更提案信息 |
| `finalize.py:101-102` | `cli/finalize.py` | finalize 命令中检测架构约束漂移 |

**动作**：
1. 从 `checker.py` 中删除 `ArchitectureChangeProposalEngine` 的 import（L690-691）和 §7 整段调用代码（L679-766）
2. `change_proposal.py` 模块**保留**，`reports.py` 和 `finalize.py` 继续使用
3. `domain/governance/` 目录**保留**

#### 步骤 6：调整门禁引擎中的 `compliance_res` 消费

**文件**：`src/vibe_tracing/domain/gate/engine.py`

`evaluate()` 方法中引用 `compliance_res` 的位置（L733–775）：

- L733–755（Rule 1.3：`architecture_violations` + `architecture_compliance_status`）→ **保留**，模块边界违反仍走此逻辑
- L758–775（Rule 1.4：`proposal_risks` / `proposal_gaps`）→ **保留代码**，但因 `proposal_risks` 和 `proposal_gaps` 不再出现在 `compliance_res` 中，`compliance_res.get("proposal_risks", [])` 返回空列表，循环零次 → 自然无操作。**无需修改代码**。
- L784–807（Rule 2.1：`unclear_constraints`）→ **保留**，手动规则未接受仍走此逻辑

> **不变量**：`MergeGateEngine` 代码无需改动。`compliance_res` 字典结构兼容——只是字段变少、列表变短。

#### 步骤 7：清理 pipeline.py 中 `compliance_res` 的死代码

**文件**：`src/vibe_tracing/cli/analyze/pipeline.py`

删除 `_run_db_analysis()` 中 L615–622 的死代码块：

```python
    if compliance_res:
        final_risks.extend(compliance_res.get("proposal_risks", []))
        seen_gaps = {(g.get("item_id"), g.get("item_type")) for g in merged_gaps}
        for gap in compliance_res.get("proposal_gaps", []):
            key = (gap.get("item_id"), gap.get("item_type"))
            if key not in seen_gaps:
                seen_gaps.add(key)
                merged_gaps.append(gap)
```

删除原因：P2 移除 GATE-VT-014 后，`compliance_res` 不再包含 `proposal_risks` 和 `proposal_gaps` 字段。`.get()` 永远返回空列表，整个代码块为死代码。按项目规则 T-1、C-1，死代码直接删除。

#### 步骤 8：清理测试 — test_architecture_compliance_checker.py

**文件**：`tests/test_architecture_compliance_checker.py`

**8a**：删除 VT 专属规则测试（7 个）：

| 测试函数 | 行号 | 删除原因 |
|----------|------|----------|
| `test_database_import_violation` | L156 | STORE-VT-001 + GATE-VT-006 专属 |
| `test_agent_runtime_import_violation` | L189 | DEP-VT-001 + GATE-VT-006 专属 |
| `test_clean_workspace` | L126 | 断言 L150–153 依赖 STORE-VT-001/DEP-VT-001/DEP-VT-002 状态 |
| `test_dashboard_compliance_and_violation` | L273 | DEP-VT-002 + GATE-VT-006 专属 |
| `test_missing_required_files` | L313 | GATE-VT-001 + GATE-VT-006 专属 |
| `test_gate_compliance_logic` | L337 | GATE-VT-006/007 元规则专属 |
| `test_check_uses_constraints_data` | L363 | 强关联 STORE-VT-001 + DEP-VT-001 硬编码行为 |

**8b**：修复模块边界测试中的 GATE-VT-006 残留断言（2 个）：

| 测试函数 | 行号 | 修复内容 |
|----------|------|----------|
| `test_forbidden_module_import_violation` | L216 | 删除 `len(violations) == 3` 中的 GATE-VT-006 项，改为 `== 2`；删除 `assert "GATE-VT-006" in rule_ids`；删除 L231–232 合并断言中的 GATE-VT-006 |
| `test_allowed_module_import_violation` | L245 | 删除 `len(violations) == 2` 中的 GATE-VT-006 项，改为 `== 1`；删除 `assert "GATE-VT-006" in rule_ids` |

**8c**：保留的测试（13 个）：

| 保留原因 | 测试 |
|----------|------|
| 构造函数/接口 | `test_init_and_missing_constraints`, `test_check_requires_constraints_data` |
| 手动规则验收 | `test_accepted_rules_collected`, `test_stale_acceptance_detected`, `test_unaccepted_manual_rules_not_in_unclear` |
| 过期判断 | `TestIsStaleAcceptance`（8 个方法） |

#### 步骤 8-2：清理测试 — test_risk_advisor.py

**文件**：`tests/test_risk_advisor.py`

修复 **2 个**使用 VT 专属 rule_id 的 fixture（测试逻辑本身有效，仅 fixture 数据需替换）：

| 测试函数 | 行号 | 修复内容 |
|----------|------|----------|
| `test_compliance_results_to_risks` | L170 | fixture 中 `rule_id: "DEP-VT-001"` 和 `"DEP-VT-002"` → 替换为通用占位符 `"ARCH-RULE-001"` 和 `"ARCH-RULE-002"` |
| `test_compliance_deduplication` | L218 | fixture 中 `rule_id: "DEP-VT-001"` → 替换为 `"ARCH-RULE-001"` |

> 注意：替换仅为 fixture 数据中的字符串，测试的断言逻辑（architecture_violations → 风险转换、去重逻辑）保持不变。

#### 步骤 8-3：清理测试 — test_merge_gate_engine.py（P2 部分）

**文件**：`tests/test_merge_gate_engine.py`

修复 **2 个**使用 VT 专属 rule_id 的 fixture：

| 测试函数 | 行号 | 修复内容 |
|----------|------|----------|
| `test_must_constraint_violated_blocks` | L99 | fixture 中 `"GATE-VT-001"` → 替换为通用占位符 `"ARCH-RULE-MUST-001"` |
| `test_unclear_constraint_produces_fail` | L126 | fixture 中 `"GATE-VT-007"` → 替换为通用占位符 `"ARCH-RULE-UNCLEAR-001"` |

> P1 步骤 4-3 已处理 `TestGhostCode` 相关删除和死 import。P2 此处仅处理 fixture 中的 VT 规则 ID 替换。`test_architecture_violation_blocks`（L173）使用 `"FORBID-VT-001"`，该规则不属于本次删除范围，无需修改。

#### 步骤 8-4：确认不修改的测试文件

以下 5 个下游测试文件不引用 `check_ghost_code`、VT 专属 rule_id、`proposal_risks`/`proposal_gaps` 或阶段 7 内部结构，无需修改：

| 文件 | 确认方式 |
|------|----------|
| `tests/test_cli_analyze.py` | grep 确认零命中 |
| `tests/test_dashboard_renderer.py` | grep 确认零命中 |
| `tests/test_traceability_report_builder.py` | grep 确认零命中 |
| `tests/test_dashboard_decisions.py` | grep 确认零命中 |
| `tests/test_reflection_prompts.py` | grep 确认零命中（`compliance_result` 参数名不同，使用的 `unclear_constraints`/`architecture_violations` 字段保留） |

---

### P2 验证清单

- [ ] `grep -n "DEP-VT-001\|DEP-VT-002\|STORE-VT-001\|GATE-VT-001\|GATE-VT-006\|GATE-VT-007\|FORBID-VT-007\|GATE-VT-014" src/vibe_tracing/domain/compliance/checker.py` 返回空
- [ ] `grep -n "find_dashboard_files\|read_dashboard_content\|check_file_exists" src/vibe_tracing/domain/compliance/checker.py` 返回空
- [ ] checker.py 只保留 `get_python_imports` 和 `find_python_files` 两个 loader 导入
- [ ] `compliance_res` 字典只含 4 个字段：`architecture_compliance_status`, `architecture_violations`, `unclear_constraints`, `accepted_rules`
- [ ] `grep -rn "ArchitectureChangeProposalEngine" src/vibe_tracing/domain/compliance/checker.py` 返回空（仅 checker.py 中移除，reports.py 和 finalize.py 中仍保留）
- [ ] `python -m pytest tests/test_architecture_compliance_checker.py -v` 通过
- [ ] `python -m pytest tests/test_merge_gate_engine.py -v` 通过
- [ ] `python -m pytest tests/test_risk_advisor.py -v` 通过
- [ ] `python -m pytest tests/test_cli_analyze.py tests/test_dashboard_renderer.py tests/test_traceability_report_builder.py tests/test_dashboard_decisions.py tests/test_reflection_prompts.py -v` 通过（确认下游无回归）
- [ ] `python -m pytest tests/ -v --cov=src/vibe_tracing/domain/compliance` 覆盖率无显著下降

---

## 执行顺序

```
P1 步骤 1–2   → 删除 queries.py + __init__.py 中的 check_ghost_code
P1 步骤 3     → 修改 pipeline.py（import + 调用 → 固定空列表）
P1 步骤 4     → 清理 test_db_query_functions.py（删 9 + 改 6 + 修 2）
P1 步骤 4-2   → 清理 test_incremental_mode.py（删 5 + 删 2 重复）
P1 步骤 4-3   → 清理 test_merge_gate_engine.py P1 部分（删 4 + 删死 import）
P1 步骤 5     → 运行 P1 验证清单
    ↓
P2 步骤 1–3   → 重写 checker.py（保留 §1 + 重写 §8 + 清理 import）
P2 步骤 4     → 清理 infra/compliance/loader.py（删 3 函数）
P2 步骤 5     → 确认 domain/governance/ 模块保留（仅移除 checker.py 中的 §7）
P2 步骤 6     → 确认 gate engine 无需修改
P2 步骤 7     → 删除 pipeline.py L615–622 死代码块
P2 步骤 8     → 清理 test_architecture_compliance_checker.py（删 7 + 修 2）
P2 步骤 8-2   → 修复 test_risk_advisor.py（改 2 个 fixture）
P2 步骤 8-3   → 修复 test_merge_gate_engine.py P2 部分（改 2 个 fixture）
P2 步骤 8-4   → 确认 5 个下游测试文件无需修改
P2 步骤 9     → 运行 P2 验证清单
```

### 测试变更总量

| 文件 | 删 | 改 | 修 | 说明 |
|------|----|----|-----|------|
| `test_db_query_functions.py` | 9 | 6 | 2 | 删纯 F5 测试 + 删复合测试中的断言行 + 修无效/错误测试 |
| `test_incremental_mode.py` | 7 | — | — | 5 个 ghost_files 依赖 + 2 个重复 |
| `test_merge_gate_engine.py` | 5 | 2 | 1 | 4 个 ghost_files + 1 个死 import + 2 个 fixture 改 rule_id |
| `test_architecture_compliance_checker.py` | 7 | 2 | — | 7 个硬编码规则 + 2 个 GATE-VT-006 残留 |
| `test_risk_advisor.py` | — | 2 | — | 2 个 fixture 改 rule_id |
| 下游 5 文件 | — | — | — | 无需修改 |
| **合计** | **28** | **12** | **3** | **43 项** |

---

## P3：修复 id_rules 配置割裂 → strict_link 静默失效

> **状态：待执行**

### 问题

`pipeline.py:552` 从 `ctx.config`（`.vibetracing/config.json`）读取 `id_rules`，但 `id_rules` 仅存在于 `task_list.json`（由 `vibe-tracing init` 写入）。两者间无合并逻辑，`ctx.config.get("id_rules", {})` 始终返回 `{}`，导致 `strict_link` 恒为 `False`。用户在 `task_list.json` 中显式设置 `true`，但运行时被静默忽略。

### 根因

| 写入方 | 读取方 | 结果 |
|--------|--------|------|
| `init.py` → `task_list.template.json` → `docs/task_list.json` | — | `id_rules` 写入数据文件 |
| — | `pipeline.py:552` → `ctx.config` → `.vibetracing/config.json` | 读不到 → 默认 `False` |

### 设计原则

1. **职责分离**：`task_list.json` = 纯任务数据；`config.json` = 治理配置。`id_rules` 是门禁行为配置，归属 `config.json`
2. **无向后兼容**：存量 `task_list.json` 中的 `id_rules` 直接删除。不接受迁移层、兼容读取、双来源合并
3. **死字段清零**：`task_id_format`、`dod_id_format`、`all_positive_status_must_reference_evidence` 无任何 Python 消费者，随 `id_rules` 一同删除。`id_rules` 中唯一有运行时消费者的字段是 `all_tasks_must_link_requirements_and_acceptance_criteria`（`pipeline.py:552`）
4. **Schema 同步清理**：`task_list.schema.json` 中 `id_rules` 属性定义删除（`additionalProperties: false` 下未知属性被拒绝是正确行为——`id_rules` 不应再出现在 `task_list.json` 中）

### 影响范围

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/vibe_tracing/templates/config.template.json` | 新增 `id_rules` | 新项目 init 时写入 `config.json` |
| `src/vibe_tracing/templates/task_list.template.json` | 删除 `id_rules` | 新项目 init 时不再写入 `task_list.json` |
| `src/vibe_tracing/infra/validation/schemas/task_list.schema.json` | 删除 `id_rules` 属性定义 | `additionalProperties: false` 下存量含 `id_rules` 的 `task_list.json` 将被拒绝——需同步删除存量文件中的 `id_rules` |
| `.vibetracing/config.json` | 新增 `id_rules` | VT 自治理：使 VT 自身 `strict_link` 生效 |
| `docs/task_list.json` | 删除 `id_rules` | VT 自治理：防止 schema 校验失败 |
| `docs/spec_pipeline_stage_7.md` | 无需修改 | L52/L143 已正确引用 `ctx.config.id_rules...`，本次修复使代码对齐文档 |

### 不影响的模块

| 模块 | 原因 |
|------|------|
| `pipeline.py:552-555` | 读取逻辑不变——`ctx.config.get("id_rules", {}).get(...)` 在 `config.json` 含 `id_rules` 后自然生效 |
| `infra/db/queries.py:check_isolated_tasks()` | 接口不变——仍接收 `strict_link: bool` 参数 |
| `init.py:render_template()` | 通用字符串替换，`id_rules` 值为纯布尔，无 `{{...}}` 占位符，零影响 |
| `tests/test_db_query_functions.py` | 测试直接传 `strict_link=True/False`，不读配置文件 |
| `tests/test_schema_contracts.py` | `_minimal_task_list()` 不含 `id_rules`，schema 变更后仍通过校验 |
| 所有其他测试文件 | grep 确认零引用 `id_rules`、`task_id_format`、`dod_id_format` |

---

### 操作步骤

#### 步骤 1：config.template.json 新增 id_rules

**文件**：`src/vibe_tracing/templates/config.template.json`

在 `"project_name": "{{PROJECT_NAME}}",` 之后、`"language": "",` 之前插入：

```json
  "id_rules": {
    "all_tasks_must_link_requirements_and_acceptance_criteria": true
  },
```

完整变更（L1–8）：

```diff
 {
   "schema_version": "1.0.0",
   "project_id": "PROJECT-{{PROJECT_PREFIX}}",
   "project_prefix": "{{PROJECT_PREFIX}}",
   "project_name": "{{PROJECT_NAME}}",
+  "id_rules": {
+    "all_tasks_must_link_requirements_and_acceptance_criteria": true
+  },
   "language": "",
   ...
```

> `task_id_format`、`dod_id_format`、`all_positive_status_must_reference_evidence` 不迁移——无代码消费，属死配置。

#### 步骤 2：task_list.template.json 删除 id_rules

**文件**：`src/vibe_tracing/templates/task_list.template.json`

删除 L10–15 整个 `id_rules` 块（含前导空行）：

```diff
    "generated_for": "AI Coding atomic task execution"
  },
-  "id_rules": {
-    "task_id_format": "TASK-{{PROJECT_PREFIX}}-序号",
-    "dod_id_format": "DOD-{{PROJECT_PREFIX}}-任务序号-子序号",
-    "all_tasks_must_link_requirements_and_acceptance_criteria": true,
-    "all_positive_status_must_reference_evidence": true
-  },
  "phases": [],
```

保留 `"project"` 块的闭合 `},` 与 `"phases"` 之间的逗号结构。

#### 步骤 3：task_list.schema.json 删除 id_rules 属性定义

**文件**：`src/vibe_tracing/infra/validation/schemas/task_list.schema.json`

删除 L14–36 的 `"id_rules"` 属性定义（含其前导空行，保持 JSON 格式整洁）：

```diff
    "schema_version": { ... },
-   "id_rules": {
-     "type": "object",
-     "description": "ID生成规则以及其他验证规则约束配置说明。",
-     "additionalProperties": false,
-     "properties": {
-       "task_id_format": { ... },
-       "dod_id_format": { ... },
-       "all_tasks_must_link_requirements_and_acceptance_criteria": { ... },
-       "all_positive_status_must_reference_evidence": { ... }
-     }
-   },
    "phases": { ... },
```

> **Breaking change**：`additionalProperties: false`（L8）下，存量含 `id_rules` 的 `task_list.json` 将触发 schema 校验失败 → `vt analyze` 以 code 1 退出。需同步执行步骤 5 删除存量文件中的 `id_rules`。

#### 步骤 4：VT 自治理 — config.json 新增 id_rules

**文件**：`.vibetracing/config.json`

在 `"project_id": "PROJECT-VT",` 之后插入：

```diff
 {
   "schema_version": "1.0.0",
   "project_id": "PROJECT-VT",
+  "id_rules": {
+    "all_tasks_must_link_requirements_and_acceptance_criteria": true
+  },
   "paths": {
```

> 此后 VT 对自身执行 `vt analyze` 时，`strict_link = True`，隔离任务检查使用严格（AND）模式。

#### 步骤 5：VT 自治理 — task_list.json 删除 id_rules

**文件**：`docs/task_list.json`

删除 L14–19 的 `id_rules` 块：

```diff
    "generated_for": "AI Coding atomic task execution"
  },
-  "id_rules": {
-    "task_id_format": "TASK-VT-序号",
-    "dod_id_format": "DOD-VT-任务序号-子序号",
-    "all_tasks_must_link_requirements_and_acceptance_criteria": true,
-    "all_positive_status_must_reference_evidence": true
-  },
  "phases": [
```

> 此步骤与步骤 3 配套：删除 schema 定义后，若 `docs/task_list.json` 仍含 `id_rules`，下次 `vt analyze` 将因 `additionalProperties: false` 被门禁阻断。

#### 步骤 6：确认无需修改的文件

| 文件 | 确认方式 | 结论 |
|------|----------|------|
| `pipeline.py` | L552–555 读取逻辑 `ctx.config.get("id_rules", {}).get(...)` 不变 | 无需修改 |
| `queries.py` | `check_isolated_tasks(conn, strict_link)` 签名不变 | 无需修改 |
| `init.py` | `render_template()` 通用替换，`id_rules` 值无 `{{...}}` 占位符 | 无需修改 |
| `tests/test_db_query_functions.py` | 测试直接传 `strict_link=True/False` 参数 | 无需修改 |
| `tests/test_schema_contracts.py` | `_minimal_task_list()` 不含 `id_rules` | 无需修改 |
| `docs/spec_pipeline_stage_7.md` | L52/L143 已引用 `ctx.config.id_rules...`，与修复后行为一致 | 无需修改 |

---

### P3 验证清单

- [ ] `grep -rn "id_rules" src/vibe_tracing/templates/task_list.template.json` 返回空
- [ ] `grep -rn "all_positive_status_must_reference_evidence\|task_id_format\|dod_id_format" src/` 返回空（死字段已从模板和 schema 中清除）
- [ ] `grep "all_positive_status_must_reference_evidence\|task_id_format\|dod_id_format" .vibetracing/config.json` 返回空（死字段未迁入 VT 自治理配置）
- [ ] `grep "all_positive_status_must_reference_evidence\|task_id_format\|dod_id_format" docs/task_list.json` 返回空（死字段已从 VT 自治理数据文件清除）
- [ ] `grep -rn "id_rules" src/vibe_tracing/infra/validation/schemas/task_list.schema.json` 返回空
- [ ] `grep "id_rules" src/vibe_tracing/templates/config.template.json` 命中 1 处（新增的配置项）
- [ ] `grep "id_rules" .vibetracing/config.json` 命中 1 处（VT 自治理配置）
- [ ] `grep "id_rules" docs/task_list.json` 返回空（VT 自治理数据文件已清理）
- [ ] `python -m pytest tests/test_db_query_functions.py -v` 通过（`check_isolated_tasks` 测试零回归）
- [ ] `python -m pytest tests/test_schema_contracts.py -v` 通过（schema 校验测试零回归）
- [ ] `python -m pytest tests/test_cli_analyze.py tests/test_merge_gate_engine.py tests/test_incremental_mode.py -v` 通过（下游零回归）
- [ ] `vt analyze` 执行成功（VT 自治理：`strict_link=True` 生效，无 schema 校验失败）

---

### P3 变更总量

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/vibe_tracing/templates/config.template.json` | 改 | 新增 3 行 `id_rules`（仅 `all_tasks_must_link_requirements_and_acceptance_criteria`） |
| `src/vibe_tracing/templates/task_list.template.json` | 改 | 删除 6 行 `id_rules` |
| `src/vibe_tracing/infra/validation/schemas/task_list.schema.json` | 改 | 删除 23 行 `id_rules` 属性定义 |
| `.vibetracing/config.json` | 改 | 新增 3 行 `id_rules` |
| `docs/task_list.json` | 改 | 删除 6 行 `id_rules` |
| 测试文件 | — | 无需修改 |
| **合计** | **5 文件** | 新增 6 行，删除 35 行 |
