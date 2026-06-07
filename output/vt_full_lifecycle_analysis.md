# Vibe Tracing 全生命周期逻辑链分析

> 综合设计阶段 (`vt_user_design_phase.md`) 与开发阶段 (`vt_user_dev_phase.md`)，从第一性原则审视从 `vt init` 到 `vt analyze` 的完整数据流与治理链路。

---

## 一、 全局生命周期

```
vt init          vt finalize           vt analyze (repeated)
   │                  │                      │
   ▼                  ▼                      ▼
┌──────┐        ┌──────────┐          ┌──────────────┐
│脚手架│ ──→    │ 设计基线  │ ──→     │ 开发质量门禁  │
│生成  │        │ 锁定     │          │ 校验         │
└──────┘        └──────────┘          └──────────────┘
   │                  │                      │
   ▼                  ▼                      ▼
config.json      config.json            config.json
prd.md (空)      prd.md (已写)          prd.md (可能已改)
constraints (空)  constraints (已写)     constraints (受哈希保护)
task_list (空)    task_list (未提交)     task_list (AI 填充)
claims (空)       claims (未提交)        claims (AI 填充)
                                   + code (AI 编写)
                                   + test (AI 编写)
                                   + tool reports (工具执行)
```

---

## 二、 阶段间契约：config.json 是唯一桥梁

`config.json` 是设计阶段到开发阶段的**唯一结构化契约**。它存储了 finalize 写入的关键字段，analyze 读取这些字段来建立治理基线：

| 字段 | finalize 写入 | analyze 读取 | 契约作用 |
|---|---|---|---|
| `language` | 从 constraints 提取 | 工具执行阶段必须 | 确定运行哪些验证工具 |
| `validation_tools` | 从 language_tool_matrix 提取 | 工具执行阶段白名单 | 限定工具类别 |
| `architecture_constraints_hash` | SHA256(constraints) | Gate 1 防篡改校验 | constraints 完整性保护 |
| `prd_hash` | SHA256(prd.md) | Gate 1 PRD 漂移检测 | PRD 完整性保护 |
| `finalize_constraints_path` | 相对路径 | 仅 re-finalize 时使用 | analyze 不直接使用 |
| `finalize_git_commit` | git rev-parse HEAD | 仅 re-finalize 时使用 | analyze 不直接使用 |

---

## 三、 受保护资产 vs 未保护资产

### 受保护（finalize 提交 + 哈希校验）

| 资产 | 保护机制 | 保护强度 |
|---|---|---|
| `architecture_constraints.json` | finalize 提交 + SHA256 哈希 + Gate 1 校验 | **强**：篡改即阻断 |
| `prd.md` | finalize 提交 + SHA256 哈希 + Gate 1 漂移检测 + 映射校验 | **强**：漂移触发重新映射校验 |
| `config.json` | finalize 提交 | **中**：可被手动编辑 |
| `architecture_change_log.md` | finalize 提交（如存在） | **中**：内容未校验 |

### 未受保护（不参与 finalize 提交）

| 资产 | 为何不保护 | 风险 |
|---|---|---|
| `task_list.json` | 开发阶段产物，finalize 时为空模板 | 无基线，靠 TaskLoader 交叉校验 |
| `agent_claims.json` | 开发阶段产物，finalize 时为空模板 | 无基线，靠 ClaimLoader 交叉校验 |
| 代码文件 | 开发阶段产物 | 无基线，靠 Claim 声明 + 架构合规校验 |
| 测试文件 | 开发阶段产物 | 无基线，靠 docstring covers 声明 |

---

## 四、 设计阶段校验 vs 开发阶段校验：覆盖矩阵

| 校验类型 | 设计阶段 (finalize) | 开发阶段 (analyze) | 状态 |
|---|---|---|---|
| PRD 结构（REQ/AC 层级/重复） | ❌ 不校验 | ✅ PrdParser | 已覆盖 |
| PRD ↔ Architecture 映射 | ✅ 死链检测 + MUST 覆盖 | ✅ Gate 1.6 映射校验 | **已修复** |
| Architecture Schema | ❌ 不校验 | ✅ SchemaValidator | 已覆盖 |
| Task ↔ PRD 交叉引用 | ❌ 无 task | ✅ TaskLoader | 已覆盖 |
| Task ↔ Architecture 交叉引用 | ❌ 无 task | ✅ TaskLoader | 已覆盖 |
| Claim ↔ Task 交叉引用 | ❌ 无 claim | ✅ ClaimLoader | 已覆盖 |
| AC ↔ Test 覆盖 | ❌ 无 test | ✅ AcTestAnalyzer | 已覆盖 |
| REQ ↔ Task 覆盖 | ❌ 无 task | ✅ RequirementTaskAnalyzer | 已覆盖 |
| 架构合规（import 规则） | ❌ 无代码 | ✅ ArchitectureComplianceChecker | 已覆盖 |
| 防篡改（constraints 哈希） | ✅ 写入哈希 | ✅ Gate 1 校验 | 已覆盖 |
| 防篡改（PRD 哈希） | ✅ 写入哈希 | ✅ Gate 1.5 漂移检测 | **已修复** |
| 工具执行 | ❌ 不执行 | ✅ ToolExecutionEngine | 已覆盖 |

---

## 五、 数据流完整链路

### 5.1 设计阶段数据流

```
人类输入
  ├─ --name "项目名"
  └─ --prefix "简称"
        │
        ▼
    vt init
        │
        ├─→ config.json (project_id, prefix, name, 空 finalize 字段)
        ├─→ prd.md (draft 模板, status: draft)
        ├─→ architecture_constraints.json (空骨架 + language_tool_matrix)
        ├─→ task_list.json (空骨架)
        ├─→ agent_claims.json (空数组)
        └─→ .vibetracing/prompts/prd_analysis.md (AI 分析指南)
        │
        ▼
    人类/AI 编写 PRD 和架构约束
        │
        ├─ prd.md: REQ + AC + 优先级 + 必测标记
        └─ architecture_constraints.json: 模块边界 + 规则 + 工具矩阵
        │
        ▼
    vt finalize
        │
        ├─ 前置校验：config.json + constraints 存在性
        ├─ PRD ↔ Architecture 映射校验
        │   ├─ 死链检测：constraints 引用的 REQ 必须存在于 PRD
        │   ├─ MUST 覆盖：MUST 级 REQ 必须有架构支撑
        │   └─ SHOULD/COULD 缺失仅警告
        ├─ 计算 constraints SHA256
        ├─ 计算 prd SHA256
        ├─ 幂等检查：hash/language/tools 未变化则跳过
        ├─ 写入 config.json (language, tools, constraints_hash, prd_hash, path)
        ├─ git add (prd + constraints + config + change_log)
        ├─ git commit --no-verify
        ├─ git rev-parse HEAD → finalize_git_commit
        └─ git commit --amend (注入 commit hash)
```

### 5.2 开发阶段数据流

```
AI Agent 操作
  ├─ 编写代码 (src/)
  ├─ 编写测试 (tests/)
  ├─ 填充 task_list.json (REQ/AC 引用)
  ├─ 填充 agent_claims.json (Task 引用 + evidence_refs)
  └─ git add + git commit (触发 pre-commit hook)
        │
        ▼
    vt analyze [--pre-commit]
        │
        ├─ ① 加载原始输入 (UnifiedContext, Single-Pass)
        │   ├─ config.json → project_prefix, language, hashes
        │   ├─ prd.md → 必须存在
        │   ├─ architecture_constraints.json → 可选
        │   ├─ task_list.json → 可选
        │   ├─ agent_claims.json → 可选
        │   └─ tool_reports/*.json → 可选
        │
        ├─ ② Gate 1: 防篡改 + 漂移检测
        │   ├─ 1a. SHA256(constraints) == config.constraints_hash? → 篡改即阻断
        │   ├─ 1b. SHA256(prd) == config.prd_hash? → 不同则标记 prd_drifted
        │   └─ 1c. PRD↔Arch 映射校验（当 prd_drifted 或 constraints 变化时）
        │       ├─ 死链：constraints 引用的 REQ 不存在于 PRD → 阻断
        │       ├─ MUST 无覆盖：MUST 级 REQ 无架构支撑 → 阻断
        │       └─ SHOULD/COULD 无覆盖 → 警告
        │
        ├─ ③ Gate 2/2.5: Pre-commit 专用 (仅 --pre-commit)
        │   ├─ 幽灵代码检测：staged 业务代码 vs active claims
        │   └─ AC 新鲜度：新增 task 引用的 AC vs staged PRD
        │
        ├─ ④ Schema 校验 (task_list, constraints, claims)
        │
        ├─ ⑤ PRD 解析 (PrdParser)
        │   ├─ 提取 REQ/AC/优先级/必测
        │   └─ 结构校验 (层级/重复/父级)
        │
        ├─ ⑥ Task 校验 (TaskLoader)
        │   ├─ isolated check (strict_link: AND)
        │   ├─ 架构孤儿检测
        │   ├─ 交叉校验 → PRD (REQ/AC 存在性)
        │   └─ 交叉校验 → Architecture (modules/constraints)
        │
        ├─ ⑦ Claim 校验 (ClaimLoader)
        │   ├─ 交叉校验 → Task (related_task 存在性)
        │   └─ completed claim 必须有外部 evidence
        │
        ├─ ⑧ 工具执行 (ToolExecutionEngine)
        │   ├─ 预飞依赖检查 (shutil.which)
        │   ├─ 收集执行路径 (claims + tasks)
        │   └─ 执行 pytest/ruff/mypy/bandit/coverage
        │
        ├─ ⑨ 证据索引构建 (EvidenceIndexBuilder + UnifiedContext)
        │   ├─ Tasks → source_type: "task"
        │   ├─ Claims → source_type: "claim"
        │   ├─ Code refs → source_type: "code"
        │   └─ Tool results → source_type: "test"/"tool"
        │
        ├─ ⑩ Claim 可信度评估
        │   ├─ high: evidence 指向 test/tool
        │   ├─ medium: 非代码任务且交付物存在
        │   └─ low_confidence: 其他
        │
        ├─ ⑪ 四路分析器并行执行
        │   ├─ REQ 覆盖：每个 MUST REQ → 是否有 task 覆盖
        │   ├─ AC 测试覆盖：每个 MUST+必测 AC → 是否有 passing test
        │   ├─ Claim 证据一致性：外部证据/文件路径/时间戳
        │   └─ 架构合规：import 规则/模块边界/存储禁令
        │
        ├─ ⑫ 风险评估 (RiskAdvisor)
        │   └─ gaps + claims + compliance → unified risks
        │
        ├─ ⑬ 门禁决策 (MergeGateEngine)
        │   ├─ blocked: AC gap / must risk / 自引用 / 架构违规
        │   ├─ fail: REQ gap / task gap / should risk / 模糊约束
        │   └─ pass: 所有规则通过
        │
        └─ ⑭ 产物输出
            ├─ evidence_index.json
            ├─ traceability_report.json
            ├─ dashboard.html
            └─ run_metadata.json
```

---

## 六、 逻辑断裂点分析与解决方案

### 断裂 1：PRD 修改不触发重新映射校验 [已解决]

**场景**：finalize 后，人类修改 PRD 新增 `REQ-VT-002`（MUST 级），但未更新 constraints。

**根因**：PRD↔Architecture 映射校验仅在 `vt finalize` 时执行一次，`vt analyze` 不重新执行。

**解决方案**：PRD 哈希保护 + analyze 中持续映射校验。

**改动**：

1. `vt finalize` 时同时计算并存储 `prd_hash`：
```python
# cli.py run_finalize()
prd_hash = hashlib.sha256(Path(prd_path).read_bytes()).hexdigest()
config["prd_hash"] = prd_hash
```

2. `vt analyze` Gate 1 扩展：
```python
# Gate 1: Anti-Tampering + Drift Detection
# 1a. Constraints 完整性（现有）
computed_c_hash = hashlib.sha256(constraints_path.read_bytes()).hexdigest()
if stored_c_hash and stored_c_hash != computed_c_hash:
    FATAL: exit 1

# 1b. PRD 漂移检测（新增）
computed_p_hash = hashlib.sha256(prd_path.read_bytes()).hexdigest()
stored_p_hash = config.get("prd_hash")
prd_drifted = (stored_p_hash is not None and stored_p_hash != computed_p_hash)
if prd_drifted:
    WARNING: "PRD 已从基线漂移，重新验证映射关系"

# 1c. PRD↔Arch 映射校验（新增，每次执行）
if constraints_loaded and prd_loaded:
    mapping_errors = validate_prd_architecture_mapping(prd_res, constraints_content)
    if mapping_errors.has_dead_links: BLOCKED
    if mapping_errors.must_uncovered: BLOCKED
    if mapping_errors.should_uncovered: WARNING
```

3. 将 `_validate_prd_architecture_mapping()` 从 `cli.py` 提取为可复用模块。

**行为变化**：
- PRD 未漂移 + constraints 未变 → 映射校验仍执行（幂等，无额外开销）
- PRD 漂移 → WARNING + 映射校验 → 死链/MUST 无覆盖则阻断
- PRD 未漂移但 constraints 被篡改 → Gate 1a 阻断（现有逻辑）

---

### 断裂 2：task_list 与 PRD 的时序依赖 [已解决]

**场景**：AI Agent 先写 task_list（引用 `AC-VT-001-01`），后修改 PRD 将 AC 重命名。

**根因**：PRD 修改不触发重新校验，task 引用可能指向已不存在的 AC。

**解决方案**：由断裂 1 的修复自动覆盖。当 PRD 漂移时：
- Gate 1.5 检测到漂移 → WARNING
- Gate 1.6 重新执行映射校验 → 检测到死链
- TaskLoader 交叉校验检测到 task 引用的 AC 不存在于新 PRD → 阻断

**时序无关性**：无论 PRD 和 task_list 的修改时序如何，`vt analyze` 始终基于当前 PRD 校验 task 引用。校验结果是幂等的。

---

### 断裂 3：Claim 声明与实际代码的语义鸿沟 [设计约束]

**场景**：Claim 声明 "covered"，关联 AC 是仪表盘 HTML，但实际代码实现 CSV 导出。

**根因**：VT 的治理模型是声明式的——Claim 声明它做了什么，VT 校验声明的结构一致性，不校验代码语义。

**分析**：这是设计哲学决定，不是缺陷。VT 的目标是"引导 AI Agent 在约束内工作"，而非"验证代码语义正确性"。代码语义验证需要：
- 自然语言理解（PRD 描述 vs 代码实现）
- 运行时行为分析（功能是否按预期工作）

这超出了 VT 的治理范围。

**缓解措施（已实现）**：
- TaskLoader 要求 task 同时关联 REQ 和 AC（`strict_link: true`）
- ClaimEvidenceAnalyzer 检查 completed claim 必须有外部 evidence
- ClaimCredibility 评估 claim 可信度（low_confidence → 风险）
- AcTestAnalyzer 检查 AC 是否有 passing test 覆盖

**可选增强（不在本次重构范围）**：
- 在 Claim 中增加 `description` 字段，要求 AI Agent 描述具体做了什么
- 在 analyze 中对 `description` 与 PRD 的 AC 描述做文本相似度检查
- 但这引入了 NLP 依赖，增加复杂度和不确定性

---

### 断裂 4：工具执行结果与 Claim 可信度的脱钩 [部分解决]

**场景**：测试通过但 docstring 未声明 `covers: AC-VT-001-01`，导致物理通过但逻辑无覆盖。

**根因**：test docstring 是测试与 AC 之间的唯一关联机制。如果 docstring 未声明 `covers`，工具执行产出的 evidence 的 `covers` 为空列表。

**现状分析**：
- `_extract_covers_from_docstring()` 从 docstring 中提取 `covers` 行
- 如果 docstring 没有 `covers` 行，evidence 的 `covers` 为空
- AcTestAnalyzer 找不到覆盖该 AC 的 passing test → gap
- 但 Claim 可能通过 `evidence_refs` 指向该 evidence，ClaimEvidenceAnalyzer 可能认为 claim 有效

**解决方案**：ClaimEvidenceAnalyzer 增加 covers 一致性检查。

**改动**：在 `ClaimEvidenceAnalyzer.analyze()` 中，当 claim 声明 "covered" 时，检查其关联 task 的 AC 是否被 claim 的 test_refs 中的测试实际覆盖：

```python
# 在 ClaimEvidenceAnalyzer 中
if is_completed:
    related_acs = [item for item in task_ev.get("covers", []) if item.startswith("AC-")]
    for ac_id in related_acs:
        # 检查 claim 的 test_refs 中是否有测试覆盖了这个 AC
        covering_tests = [
            t for t in test_evs
            if ac_id in t.get("covers", [])
            and t.get("source_path") in claim.test_refs
        ]
        if not covering_tests:
            # claim 声明完成，但其 test_refs 中没有测试覆盖关联的 AC
            risks.append({
                "risk_category": "test_covers_mismatch",
                "severity": "must",
                "description": f"Claim {claim_id} 声明完成但 test_refs 中无测试覆盖 AC {ac_id}"
            })
```

**行为变化**：
- 测试通过但未声明 covers → AcTestAnalyzer gap（现有）
- Claim 的 test_refs 中的测试未覆盖关联 AC → ClaimEvidenceAnalyzer risk（新增）
- 双重检测：既检查"有没有测试覆盖 AC"，也检查"Claim 声明的测试是否真的覆盖了 AC"

---

### 断裂 5：config.json 路径覆盖无验证 [建议修复]

**场景**：手动编辑 `config.json` 的 `paths` 字段，将 `task_list` 指向不存在的路径。

**根因**：`paths` 字段不被 finalize 锁定，analyze 直接使用 `RawInputLoader.get_path()` 解析路径，不验证路径是否存在。

**分析**：`paths` 字段是 `vt init` 生成的默认路径映射。如果被手动修改，可能导致 analyze 读取错误的文件。当前 `RawInputLoader.load()` 在文件不存在时返回 `status: "missing"`，不会崩溃，但可能产生误导性结果。

**解决方案**：在 `vt finalize` 时锁定 `paths` 字段，analyze 时验证路径一致性。

**改动**：

1. `vt finalize` 时将 `paths` 写入 config.json 并纳入哈希计算范围（或单独存储 paths_hash）。

2. `vt analyze` 时验证 `paths` 中的每个路径指向的文件是否存在（仅对 required 文件）：
```python
# 在 RawInputLoader.load() 中
for key, path in self.paths.items():
    resolved = self.project_root / path
    if not resolved.exists() and key in ("prd",):
        errors.append(f"Path for '{key}' does not exist: {path}")
```

**优先级**：低。当前行为（返回 missing status）已足够优雅。

---

### 断裂 6：finalize_git_commit 不参与开发阶段治理 [设计决策]

**场景**：`finalize_git_commit` 存储在 config.json 中，但 `vt analyze` 从不读取。

**分析**：`finalize_git_commit` 的唯一用途是在 re-finalize 时通过 `git show {commit}:{path}` 获取基线 constraints 文件，用于比对变更。`vt analyze` 使用 SHA256 哈希（更轻量）来检测篡改，不需要 git commit hash。

**结论**：这是合理的设计分工——finalize 内部用 git commit 做变更比对，analyze 用哈希做完整性校验。两者职责不同，不需要统一。

---

## 七、 治理强度梯度

```
强治理 ────────────────────────────────────────────── 弱治理
   │                                                      │
   │  constraints 哈希保护     Claim ↔ Code 语义关联       │
   │  (Gate 1 阻断)            (设计约束，不校验)          │
   │                                                      │
   │  PRD 哈希 + 映射校验      Code 质量                   │
   │  (Gate 1.5/1.6)           (工具执行，不阻断)          │
   │                                                      │
   │  Task ↔ PRD 交叉引用      需求语义正确性               │
   │  (结构性校验)              (无校验)                    │
   │                                                      │
   │  AC ↔ Test 覆盖           Claim 描述准确性            │
   │  (docstring 声明)          (无校验)                    │
   │                                                      │
   ▼                                                      ▼
 文件级/结构级校验                              语义级/意图级校验
 (VT 治理范围)                                 (VT 不覆盖)
```

---

## 八、 设计决策的内在一致性

### 决策 1：PRD 纳入哈希保护 + 持续映射校验

**理由**：PRD 与 constraints 之间存在强耦合的映射关系（死链检测 + MUST 覆盖）。单方面修改任何一方都会破坏这个关系。PRD 哈希保护不阻止变更，但触发映射重新校验。

**一致性分析**：这保持了"引导而非限制"的哲学——VT 不阻止人类修改 PRD，但确保修改后系统仍处于一致状态。与 constraints 的保护机制对称。

### 决策 2：task_list 不纳入 finalize 提交

**理由**：task_list 是开发阶段产物，finalize 时为空模板。

**一致性分析**：与两阶段架构一致。task_list 的正确性由 TaskLoader 交叉校验保证（与 PRD 和 constraints 的引用关系），不需要基线保护。

### 决策 3：Claim 声明驱动治理

**理由**：VT 的治理模型是"声明式"的——AI Agent 通过 Claim 声明它做了什么，VT 校验声明的一致性。

**一致性分析**：与"引导而非限制"的哲学一致。治理强度依赖于 AI Agent 的诚实度，但通过自引用检测、可信度评估、covers 一致性检查等机制逐层加强。

---

## 九、 全局逻辑链总结

```
设计阶段                    过渡                    开发阶段
─────────────              ─────                   ─────────────
vt init                    (空窗期)                vt analyze
  │                          │                       │
  ├─ 生成脚手架              ├─ AI 写 PRD            ├─ Gate 1a: constraints 哈希
  └─ 安装 pre-commit         ├─ AI 写 constraints    ├─ Gate 1b: PRD 漂移检测
      hook                   ├─ AI 写代码            ├─ Gate 1c: PRD↔Arch 映射校验
                             ├─ AI 写测试            ├─ Schema 校验
vt finalize                  ├─ AI 填 task_list      ├─ PRD 解析
  │                          └─ AI 填 claims         ├─ Task ↔ PRD 交叉
  ├─ PRD↔Arch 映射校验                               ├─ Claim ↔ Task 交叉
  ├─ constraints 哈希                                 ├─ Claim ↔ AC covers 一致性
  ├─ prd 哈希                                         ├─ 工具执行
  └─ git commit                                       ├─ 证据索引
                                                      ├─ 四路分析器
                                                      ├─ 风险评估
                                                      ├─ 门禁决策
                                                      └─ 产物输出

桥梁：config.json (hashes + language + tools)
完整性保护：constraints 哈希 + PRD 哈希 (Gate 1)
持续校验：PRD↔Arch 映射 + Task↔PRD + Claim↔Task + AC↔Test
```

**本质**：VT 的治理模型是**分层持续校验式**的——设计阶段在 finalize 时建立基线（双哈希），开发阶段在每次 analyze 时校验所有数据的一致性。constraints 和 PRD 都被哈希保护，映射关系在每次 analyze 时重新验证。系统始终处于可审计的一致状态。

---

## 十、 原子化任务清单

> 每个任务可独立提交、独立核验。按依赖关系组织为 Wave。

### 依赖关系总览

```
Wave 0 ── 无依赖（2 个任务并行）
  LIFE-001  config.template.json 增加 prd_hash 字段
  LIFE-002  提取 PRD↔Arch 映射校验为独立模块
       │
       ▼
Wave 1 ── 依赖 Wave 0（2 个任务并行）
  LIFE-003  vt finalize 存储 prd_hash
  LIFE-004  vt analyze Gate 1b: PRD 漂移检测
       │
       ▼
Wave 2 ── 依赖 Wave 1（1 个任务）
  LIFE-005  vt analyze Gate 1c: PRD↔Arch 映射持续校验
       │
       ▼
Wave 3 ── 无依赖（1 个任务）
  LIFE-006  ClaimEvidenceAnalyzer covers 一致性检查
```

---

### Wave 0：基础准备（无依赖）

#### LIFE-001：config.template.json 增加 prd_hash 字段

**解决的问题**：config.json 模板中无 PRD 哈希字段，无法建立 PRD 基线。

**涉及文件**：
- `src/vibe_tracing/templates/config.template.json`

**行动指导**：

1. 读取 `config.template.json`，找到 `architecture_constraints_hash` 字段。
2. 在其后新增 `prd_hash` 字段，默认值为空字符串：
```json
{
  "architecture_constraints_hash": "",
  "prd_hash": "",
  "finalize_git_commit": "",
  ...
}
```

3. 验证 `vt init` 生成的 config.json 包含 `prd_hash` 字段。

**核验标准**：
- `grep "prd_hash" src/vibe_tracing/templates/config.template.json` 有结果
- `python3 -m pytest tests/test_scaffolding.py -v` 通过

---

#### LIFE-002：提取 PRD↔Architecture 映射校验为独立模块

**解决的问题**：`_validate_prd_architecture_mapping()` 当前内嵌在 `cli.py` 的 `run_finalize()` 中，无法在 `run_analyze()` 中复用。

**涉及文件**：
- `src/vibe_tracing/prd_arch_validator.py`（新建）
- `src/vibe_tracing/cli.py`（重构调用）

**行动指导**：

1. 读取 `cli.py` 中 `run_finalize()` 的 `_validate_prd_architecture_mapping()` 函数（约 line 240-302）。
2. 创建 `src/vibe_tracing/prd_arch_validator.py`，将该函数移入为模块级函数：
```python
from typing import Any, Dict, List
from dataclasses import dataclass

@dataclass
class MappingResult:
    dead_links: List[str]       # constraints 引用的 REQ 不存在于 PRD
    must_uncovered: List[str]   # MUST 级 REQ 无架构支撑
    should_uncovered: List[str] # SHOULD/COULD 级 REQ 无架构映射

    @property
    def has_dead_links(self) -> bool:
        return len(self.dead_links) > 0

    @property
    def has_must_uncovered(self) -> bool:
        return len(self.must_uncovered) > 0

    @property
    def is_valid(self) -> bool:
        return not self.has_dead_links and not self.has_must_uncovered

def validate_prd_architecture_mapping(
    prd_requirements: List[Any],
    constraints_content: Dict[str, Any],
    project_prefix: str = "VT",
) -> MappingResult:
    """
    Validate that architecture constraints correctly reference PRD requirements.
    - Dead links: constraints引用的REQ不存在于PRD → 阻断
    - Must uncovered: MUST级REQ无架构支撑 → 阻断
    - Should uncovered: SHOULD/COULD级缺失 → 警告
    """
    ...
```

3. 在 `cli.py` 的 `run_finalize()` 中改为调用新模块：
```python
from vibe_tracing.prd_arch_validator import validate_prd_architecture_mapping
result = validate_prd_architecture_mapping(prd_res.requirements, constraints_content, config_prefix)
if result.has_dead_links: ...
if result.has_must_uncovered: ...
```

4. 新建测试 `tests/test_prd_arch_validator.py`：
   - 死链检测：constraints 引用 REQ-VT-999 但 PRD 中不存在 → `has_dead_links == True`
   - MUST 无覆盖：PRD 有 MUST REQ 但 constraints 无对应模块 → `has_must_uncovered == True`
   - SHOULD 无覆盖：PRD 有 SHOULD REQ 无映射 → `should_uncovered` 非空但 `is_valid == True`
   - 全部通过：所有映射正确 → `is_valid == True`

**核验标准**：
- `python3 -m pytest tests/test_prd_arch_validator.py -v` 通过
- `python3 -m pytest tests/test_finalize.py -v` 通过（现有 finalize 测试不回归）
- `grep -n "_validate_prd_architecture_mapping" src/vibe_tracing/cli.py` 无结果（已移至独立模块）

---

### Wave 1：双端哈希（依赖 Wave 0）

#### LIFE-003：vt finalize 存储 prd_hash

**解决的问题**：finalize 不存储 PRD 哈希，analyze 无法检测 PRD 漂移。

**涉及文件**：
- `src/vibe_tracing/cli.py`（run_finalize）

**行动指导**：

1. 在 `run_finalize()` 中，计算 constraints 哈希的同时计算 PRD 哈希：
```python
prd_path = raw_loader.get_path("prd")
prd_hash = hashlib.sha256(Path(prd_path).read_bytes()).hexdigest()
```

2. 将 `prd_hash` 写入 config.json（与 `architecture_constraints_hash` 一起）：
```python
config["prd_hash"] = prd_hash
```

3. 幂等检查中增加 prd_hash 比对：如果 prd_hash 未变化且 constraints_hash 未变化，则跳过。

4. 更新 finalize 测试，验证 config.json 中包含 `prd_hash` 且值正确。

**核验标准**：
- `python3 -m pytest tests/test_finalize.py -v` 通过
- 手动执行 `vt finalize` 后，`grep "prd_hash" .vibetracing/config.json` 有非空值

---

#### LIFE-004：vt analyze Gate 1b PRD 漂移检测

**解决的问题**：analyze 不检测 PRD 是否从基线漂移。

**涉及文件**：
- `src/vibe_tracing/cli.py`（run_analyze）

**行动指导**：

1. 在 `run_analyze()` 的 Gate 1 逻辑中（约 line 550），constraints 哈希校验之后增加 PRD 哈希校验：
```python
# Gate 1b: PRD drift detection
prd_path = raw_loader.get_path("prd")
if prd_path.exists():
    computed_p_hash = hashlib.sha256(Path(prd_path).read_bytes()).hexdigest()
    stored_p_hash = raw_loader.config_data.get("prd_hash")
    if stored_p_hash and stored_p_hash != computed_p_hash:
        print("WARNING: PRD 已从基线漂移，重新验证映射关系", file=sys.stderr)
        prd_drifted = True
    else:
        prd_drifted = False
else:
    prd_drifted = False
```

2. `prd_drifted` 变量留作 LIFE-005 使用。

3. 此步骤**不阻断**，仅输出 WARNING。阻断逻辑在 LIFE-005 中。

4. 新增测试：
   - PRD 未修改 → 无 WARNING
   - PRD 被修改 → 输出 WARNING 且 `prd_drifted == True`
   - config.json 无 `prd_hash` 字段（旧项目）→ 无 WARNING，跳过检测

**核验标准**：
- `python3 -m pytest tests/test_cli_analyze.py -v` 通过
- 在测试中修改 PRD 后运行 analyze，stderr 包含 "PRD 已从基线漂移"

---

### Wave 2：映射持续校验（依赖 Wave 1）

#### LIFE-005：vt analyze Gate 1c PRD↔Arch 映射持续校验

**解决的问题**：PRD↔Architecture 映射校验仅在 finalize 时执行，analyze 不重新验证。

**涉及文件**：
- `src/vibe_tracing/cli.py`（run_analyze）
- `tests/test_cli_analyze.py`

**行动指导**：

1. 在 `run_analyze()` 的 Gate 1b 之后，增加 Gate 1c：
```python
# Gate 1c: PRD↔Architecture mapping validation
from vibe_tracing.prd_arch_validator import validate_prd_architecture_mapping

if constraints_record and constraints_record.status == "ok" and prd_res:
    mapping_result = validate_prd_architecture_mapping(
        prd_res.requirements,
        constraints_record.content,
        config_prefix,
    )
    if mapping_result.has_dead_links:
        for link in mapping_result.dead_links:
            print(f"BLOCKED: 架构约束引用的 {link} 不存在于 PRD", file=sys.stderr)
        return 1
    if mapping_result.has_must_uncovered:
        for req_id in mapping_result.must_uncovered:
            print(f"BLOCKED: MUST 级 {req_id} 无架构支撑", file=sys.stderr)
        return 1
    for req_id in mapping_result.should_uncovered:
        print(f"WARNING: SHOULD/COULD 级 {req_id} 缺失架构映射", file=sys.stderr)
```

2. 新增测试用例：
   - PRD 新增 MUST REQ 但 constraints 无对应模块 → exit code 1
   - PRD 删除 REQ 但 constraints 仍引用 → exit code 1（死链）
   - PRD 新增 SHOULD REQ 无映射 → WARNING 但不阻断
   - PRD 和 constraints 一致 → 无输出

**核验标准**：
- `python3 -m pytest tests/test_cli_analyze.py -v` 通过（含新增用例）
- `python3 -m pytest tests/test_prd_arch_validator.py -v` 通过

---

### Wave 3：covers 一致性（无依赖）

#### LIFE-006：ClaimEvidenceAnalyzer covers 一致性检查

**解决的问题**：Claim 声明 "covered"，但其 test_refs 中的测试未覆盖关联的 AC。

**涉及文件**：
- `src/vibe_tracing/traceability/claim_evidence_analyzer.py`
- `tests/test_claim_evidence_analyzer.py`

**行动指导**：

1. 在 `ClaimEvidenceAnalyzer.analyze()` 中，当 `is_completed` 为 True 时，增加 covers 一致性检查：

在现有的 "3. AC test coverage checks for the task" 逻辑（约 line 243-280）之后，增加：

```python
# 3b. Covers consistency: claim's test_refs must cover related ACs
if claim.test_refs:
    claim_test_paths = [ref.split("#")[0] for ref in claim.test_refs]
    for ac_id in related_acs:
        # Find test evidences that cover this AC
        ac_covering_tests = [t for t in test_evs if ac_id in t.get("covers", [])]
        # Check if any of those tests are in claim's test_refs
        claim_covers_ac = any(
            t.get("source_path") in claim_test_paths
            for t in ac_covering_tests
        )
        if not claim_covers_ac and ac_covering_tests:
            # Tests exist that cover AC, but none are in claim's test_refs
            reason = (
                f"Claim {claim_id} 声明完成但 test_refs 中无测试覆盖 AC {ac_id}。"
                f"已有的覆盖测试: {[t.get('source_path') for t in ac_covering_tests]}"
            )
            mismatches.append(reason)
            risks.append({
                "risk_id": ids.make_risk_id(risk_counter),
                "description": reason,
                "severity": "must",
                "risk_category": "test_covers_mismatch",
            })
            risk_counter += 1
```

2. 新增测试用例：
   - Claim 的 test_refs 中有测试覆盖 AC → 无 risk
   - Claim 的 test_refs 中无测试覆盖 AC，但其他测试覆盖了 → must risk
   - 无任何测试覆盖 AC → 由 AcTestAnalyzer 检测（现有逻辑）

**核验标准**：
- `python3 -m pytest tests/test_claim_evidence_analyzer.py -v` 通过（含新增用例）

---

### 任务索引

| Task ID | 标题 | Wave | 解决断裂 | 涉及文件 |
|---|---|---|---|---|
| LIFE-001 | config.template 增加 prd_hash | 0 | 断裂 1 基础 | `config.template.json` |
| LIFE-002 | 提取 PRD↔Arch 映射校验模块 | 0 | 断裂 1 基础 | `prd_arch_validator.py` (新), `cli.py` |
| LIFE-003 | finalize 存储 prd_hash | 1 | 断裂 1 | `cli.py` (run_finalize) |
| LIFE-004 | analyze Gate 1b PRD 漂移检测 | 1 | 断裂 1, 2 | `cli.py` (run_analyze) |
| LIFE-005 | analyze Gate 1c 映射持续校验 | 2 | 断裂 1, 2 | `cli.py` (run_analyze) |
| LIFE-006 | Claim↔AC covers 一致性检查 | 3 | 断裂 4 | `claim_evidence_analyzer.py` |
