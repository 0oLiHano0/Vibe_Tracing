# Vibe Tracing 语义对账协议实施计划

本计划引入**"基于确定性协议的代理自我语义审计机制"**。VT 自身保持 100% 确定性、零 LLM 依赖，利用 Coding Agent 自身的大模型完成需要语义判断的审计任务。

## 一、 核心设计原则

1. **VT 是协议制定者，不是语义裁判**：VT 定义"什么需要审计"和"审计通过的条件"，但不执行语义判断。
2. **两阶段协议**：generate（VT 生成 pending 审计单）→ verify（VT 验证 Agent 填充的审计结果）。两个阶段在同一次 `vt analyze` 中执行，但 Agent 需要两次调用才能完成完整流程。
3. **分层防御**：Gate 2.5 反向校验（结构性 WARNING）+ Semantic Audit（语义性 BLOCKING），互补不重叠。
4. **仅审计质量演进变更**：功能性 task 的代码变更由 AC 校验覆盖，不需要额外语义审计。仅当代码变更的覆盖 task 属于 `quality_evolution` 类别时触发。

---

## 二、 架构分层

```
Gate 2 幽灵代码检测（已实现，BLOCKED）
  ├── 检查：staged 代码文件是否有 staged claim
  ├── 性质：结构性检查（纯规则，无 LLM）
  └── 输出：BLOCKED（exit 2）

Gate 2.5 反向覆盖校验（已实现，分层输出）
  ├── 检查：staged 代码文件 → 覆盖 task 状态
  ├── 无覆盖 task → BLOCKED（exit 2，等同幽灵代码）
  ├── 有覆盖 task 但 task 未修改 → WARNING（提醒更新 task 状态）
  └── 性质：结构性检查（纯规则，无 LLM）

Semantic Audit（本计划新增，BLOCKING 级别）
  ├── 检查：quality_evolution 代码变更 → Agent 是否给出语义合理解释
  ├── 性质：语义性检查（VT 生成单据，Agent 填充理由）
  └── 输出：BLOCKED（exit 2，阻断提交）
```

**设计原则：AI Agent 极易忽略非阻断性警告。** 凡是必须遵守的规则，必须以 BLOCKED（exit 2）阻断。WARNING 仅用于提醒性事项（如 task 状态更新建议）。

---

## 三、 两阶段工作流

### 阶段 1：VT 生成审计单（`vt analyze` 第 1 次）

```
vt analyze
  → SemanticAuditor.generate_tickets()
    → 扫描 staged 代码文件 (git diff --cached)
    → 通过 claims 关联 task
    → 过滤：仅 task.category == "quality_evolution"
    → 对每个命中的文件：
      → 生成 ticket: {file_path, task_id, ac_ids, file_hash, status: "pending"}
      → 写入 .vibetracing/semantic_audit.json
  → SemanticAuditor.verify_tickets()
    → 检查当前变更集的 tickets
    → 发现 pending → return BLOCKED
  → vt analyze 退出码 2
```

### 阶段 2：Agent 填充审计理由

```
Agent 检测到 exit code 2
  → 读取 .vibetracing/semantic_audit.json 中 status=="pending" 的条目
  → 对每个 pending ticket：
    → 调用 LLM 分析代码变更的语义合理性
    → 填写 audit_reason（必须非空）
    → 更新 status 为 "passed"
  → git add .vibetracing/semantic_audit.json
```

### 阶段 3：VT 验证审计结果（`vt analyze` 第 2 次 / git commit）

```
vt analyze（或 pre-commit hook）
  → SemanticAuditor.verify_tickets()
    → 对每个当前变更集的 ticket：
      → status != "passed" → BLOCKED
      → audit_reason 为空 → BLOCKED
      → file_hash 不匹配 → BLOCKED（代码被二次修改，需重新审计）
      → 全部通过 → return PASS
  → vt analyze 继续后续分析
```

---

## 四、 与现有机制的关系

| 机制 | 层级 | 检查内容 | 输出 | 状态 |
|---|---|---|---|---|
| Gate 2 幽灵代码 | 结构 | 代码文件是否有 claim | BLOCKED | 已实现 |
| Gate 2.5 正向校验 | 结构 | 新 task 的 AC 是否新鲜 | WARNING | 已实现 |
| Gate 2.5 反向校验 — 无覆盖 task | 结构 | staged 代码文件无任何 claim 覆盖 | **BLOCKED** | **待升级** |
| Gate 2.5 反向校验 — task 未修改 | 结构 | 有覆盖 task 但 task 未在本次 commit 修改 | WARNING | 已实现 |
| Semantic Audit | 语义 | quality_evolution 代码变更是否有合理解释 | BLOCKED | **待实现** |

---

## 五、 审计单数据结构

文件位置：`.vibetracing/semantic_audit.json`

```json
{
  "schema_version": "1.0.0",
  "tickets": [
    {
      "ticket_id": "AUDIT-VT-001",
      "file_path": "src/vibe_tracing/cli.py",
      "file_hash": "sha256:abcdef123456...",
      "task_id": "TASK-VT-044",
      "ac_ids": ["AC-VT-009-12"],
      "status": "passed",
      "audit_reason": "移除 ctx=None fallback 路径，所有调用方已迁移至 UnifiedContext。删除的代码从未被执行，属于死代码清理。",
      "created_at": "2026-06-07T22:00:00Z",
      "updated_at": "2026-06-07T22:05:00Z"
    }
  ]
}
```

**字段说明**：
- `ticket_id`：唯一标识，格式 `AUDIT-VT-NNN`
- `file_path`：被修改的代码文件路径
- `file_hash`：审计时的文件 SHA-256（staged 版本），用于检测二次修改
- `task_id`：覆盖该文件的 quality_evolution task
- `ac_ids`：task 关联的 AC 列表
- `status`：`pending` | `passed` | `rejected`
- `audit_reason`：Agent 填写的语义审计理由（passed 时必填，非空）
- `created_at` / `updated_at`：时间戳

---

## 六、 触发条件

**仅当以下条件同时满足时**触发语义审计：

1. 代码文件在 staged 变更中（`git diff --cached`）
2. 该文件被某个 claim 的 `code_refs` 覆盖
3. 该 claim 关联的 task 的 `category == "quality_evolution"`

**不触发的情况**：
- 代码文件无覆盖 task → 由 Gate 2 幽灵代码检测处理
- 覆盖 task 的 category 为 `functional` → 由 AC 校验覆盖
- 仅修改了非代码文件（.md, .json, .html）→ 不需要语义审计

---

## 七、 Ticket 清理机制

在 `verify_tickets()` 中执行清理：

1. **Hash 匹配 + passed**：ticket 的 `file_hash` 与当前 staged 文件 hash 一致且 status 为 passed → 保留（供审计追溯）
2. **Hash 不匹配**：代码被二次修改 → 重置为 `pending`，清空 `audit_reason`
3. **Task 状态为 done**：关联 task 已完成 → 标记为 `archived`（不参与后续验证）
4. **定期清理**：超过 48 小时的 `archived` ticket 自动删除（审计单是瞬时校验票据，通过后信息已固化在 Git 历史和治理链路中）

---

## 八、 实施任务

### [NEW] semantic_auditor.py

实现 `SemanticAuditor` 类：

- `__init__(self, project_root: Path)`
- `generate_tickets(staged_files: Set[str], claims: List[dict], tasks: List[dict]) -> List[dict]`
  - 扫描 staged 代码文件
  - 通过 claims 关联 task，过滤 `category == "quality_evolution"`
  - 对未覆盖的文件生成 pending ticket
  - 写入 `.vibetracing/semantic_audit.json`
  - 返回新生成的 tickets
- `verify_tickets(staged_files: Set[str]) -> Tuple[bool, str]`
  - 读取现有 tickets
  - 对 staged 文件关联的 tickets 逐条验证
  - 对 hash 不匹配的 ticket 重置为 pending
  - 清理 archived tickets
  - 返回 (success, warning_message)
- `_compute_file_hash(file_path: str) -> str` — 计算 staged 文件 SHA-256
- `_load_tickets() -> List[dict]` — 读取 semantic_audit.json
- `_save_tickets(tickets: List[dict])` — 写入 semantic_audit.json

### [MODIFY] cli.py

在 `_run_integrity_gates()` 中（Gate 2.5 之后）集成 Semantic Audit：

```python
# Gate 3: Semantic Audit (only for quality_evolution changes)
auditor = SemanticAuditor(project_root)
staged_code_files = auditor.get_staged_code_files()
new_tickets = auditor.generate_tickets(staged_code_files, ctx.claims_list, ctx.task_result.tasks)
success, msg = auditor.verify_tickets(staged_code_files)
if not success:
    print(msg, file=sys.stderr)
    return 2  # BLOCKED
```

### [MODIFY] ac_freshness_checker.py

升级 `_reverse_check()` 输出级别：

- **无覆盖 task**（staged 代码文件无任何 claim 的 code_refs 覆盖）→ 返回 `(False, message)`，阻断提交（exit 2）。与 Gate 2 幽灵代码检测互补：Gate 2 检查 staged claim 是否存在，反向校验检查 staged 代码是否被 claim 覆盖。
- **有覆盖 task 但 task 未修改** → 保持 `(True, warning)`，提醒 Agent 更新 task 状态。
- 修改 `check()` 返回类型逻辑：forward_warnings + reverse_warnings 中任一为 BLOCKED 级别时，`success=False`。

### [NEW] tests/test_semantic_auditor.py

测试用例：
1. quality_evolution 代码变更 → 生成 pending ticket
2. functional 代码变更 → 不生成 ticket
3. pending ticket → verify 返回 BLOCKED
4. passed + reason 非空 + hash 匹配 → verify 返回 PASS
5. hash 不匹配 → 重置为 pending
6. 无 staged 代码文件 → 不触发审计
7. 多文件部分 pending → BLOCKED

### [MODIFY] schemas/ (可选)

新增 `semantic_audit.schema.json` 校验审计单格式。

---

## 九、 验证计划

### 自动化测试
```bash
python3 -m pytest tests/test_semantic_auditor.py -v
python3 -m pytest tests/ -v  # 全量回归
```

### 手动验证
1. 修改一个被 quality_evolution task 覆盖的文件 → `vt analyze` 生成 pending ticket 并 BLOCKED
2. 编辑 `.vibetracing/semantic_audit.json`，填写 audit_reason，设为 passed → `vt analyze` 放行
3. 再次修改同一文件（hash 变化）→ `vt analyze` 重置为 pending 并 BLOCKED
4. 修改功能性 task 覆盖的文件 → 不触发语义审计

---

## 十、 已实现状态

以下变更已在之前的 EVO 任务中完成，本 plan 不再重复：

| 组件 | 变更 | 状态 |
|---|---|---|
| context.py | UnifiedContext 强类型领域模型 | ✅ 已实现 |
| evidence_index_builder.py | 接受 ctx 参数，移除内部 loader | ✅ 已实现 |
| merge_gate_engine.py | 移除 blocked 时吞掉 fail 的逻辑 | ✅ 已实现 |
| ac_freshness_checker.py | 正向校验（WARNING）+ 反向校验（无覆盖 task → BLOCKED，task 未修改 → WARNING） | ⚠️ 需升级 |
| cli.py | run_analyze 拆分为 5 个子函数 | ✅ 已实现 |
| cli.py | 工具依赖失败注入 BLOCKED 证据 | ✅ 已实现 |
| prd_parser.py | category 必填字段 | ✅ 已实现 |
| reflection_prompts.py | 覆盖校验 WARNING + task_list 必传 | ✅ 已实现 |

---

## 十一、 演进路径：从并存到替代（未来决策点）

**当前决策：保守方案。** 基于规则的检查是确定性的、不可篡改的。Claims + Gate 2/2.5 作为结构性防线保留，Semantic Audit 作为语义性补充。

**未来演进条件：** 当 Semantic Audit 在实际使用中证明 Agent 能持续提供诚实、可靠的 audit_reason 后，可考虑激进简化：

### 阶段 0（当前）：Claims + Audit 并存
```
PRD → Task → Claim → Code → Gate 2/2.5 (结构性) + Semantic Audit (语义性)
```

### 阶段 1（验证通过后）：Audit 替代 Claims
```
PRD → Task → Semantic Audit Ticket → Code → Merge
```
可移除：
- `agent_claims.json` 及其模板、loader
- `ghost_code_reconciler.py`（或简化为 ticket 存在性检查）
- Gate 2.5 反向覆盖校验（`_reverse_check()`）
- Claim 的 evidence_refs / test_refs 交叉校验
- reflection_prompts.py 中凭证真实性维度的 claim 相关提示

**验证标准**：
- Agent 连续 20 次提交的 audit_reason 通过人工抽样审查（非敷衍、非套话）
- audit_reason 能准确描述代码变更的物理行为和业务动机
- 无 Agent 利用 audit_reason 绕过治理的案例

**本计划范围：仅实施 Semantic Audit（阶段 0），不涉及 Claims 移除。**
