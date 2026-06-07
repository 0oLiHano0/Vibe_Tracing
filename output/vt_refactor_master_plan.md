# Vibe Tracing 全局设计与行动方案

> 综合 `vt_user_dev_phase.md`（现状审计）与 `traceability_graph_architecture.md`（目标架构），形成从"发现问题"到"解决问题"的完整行动链。

---

## 一、 全局视角：从哪来到哪去

### 现状诊断（As-Is）

`vt analyze` 的当前管道流存在三类系统性问题：

```
┌─ 逻辑缺陷 ──────────────────────────────────────────────┐
│  [HIGH] MergeGateEngine: blocked 时吞掉 fail 级警告       │
│         → 用户需要多轮 analyze 才能发现全部问题            │
└──────────────────────────────────────────────────────────┘
┌─ 重复计算 ──────────────────────────────────────────────┐
│  [HIGH] SHA-256 哈希计算 2 次 (Gate 1 + Step 5)          │
│  [HIGH] EvidenceIndexBuilder 全量重加载 4 组输入文件       │
│  [MEDIUM] Schema 校验执行 2 次 (Step 1.1 + Step 4a/4b)  │
└──────────────────────────────────────────────────────────┘
┌─ 死逻辑 ────────────────────────────────────────────────┐
│  [HIGH] ToolEvidenceAdapter 已废弃但仍被使用               │
│  [MEDIUM] tests/ 目录兜底产生无来源孤儿证据               │
│  [MEDIUM] tests/ 兜底的 covers 为空，无法关联 REQ/AC     │
│  [LOW] hashlib 局部导入，重构时易致 NameError             │
└──────────────────────────────────────────────────────────┘
```

### 目标架构（To-Be）

```
┌─ Single-Pass Loader ────────────────────────────────────┐
│  文件只读一次 → Schema 校验只执行一次 → 输出 UnifiedContext │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─ Domain Validators ────────────────────────────────────┐
│  各 Analyzer 接收 UnifiedContext，直接遍历强类型对象关系   │
│  运行时谓词（文件存在性/时间戳）作为外置检查依附于内存模型  │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─ MergeGateEngine ──────────────────────────────────────┐
│  不论是否 Blocked，完整记录所有 warnings 到 reasons       │
└────────────────────────────────────────────────────────┘
```

### 设计决策

> [!IMPORTANT]
> **不采用通用图引擎**。采用强类型领域对象树（`UnifiedContext`），各 Analyzer 直接基于 Python 属性引用遍历——这以最 Pythonic 的方式实现了有向图拓扑查询，同时保留类型安全和 IDE 可推导性。
>
> **重构优先级**：以解决实际痛点（重复 I/O、信息丢失）为第一优先级。

---

## 二、 问题 → 方案映射表

| # | 问题 | 严重度 | 根因 | 解决方案 | 归属 Step |
|---|---|---|---|---|---|
| 1 | MergeGateEngine blocked 时吞掉 fail 级警告 | HIGH | `if gate_decision != "blocked"` 限制 | 移除限制，独立评估所有条件 | Step 2 |
| 2 | EvidenceIndexBuilder 全量重加载输入文件 | HIGH | `build()` 忽略传入参数，内部重新实例化所有 Loader | 接受 `UnifiedContext`，删除内部 Loader | Step 1 |
| 3 | SHA-256 哈希计算 2 次 | HIGH | Gate 1 和 Step 5 独立计算 | 复用 Gate 1 结果，删除 Step 5 二次计算 | Step 1 |
| 4 | Schema 校验执行 2 次 | MEDIUM | Step 1.1 校验后，TaskLoader/ClaimLoader 再次校验 | Loader 接受 `skip_schema=True` 或只校验一次 | Step 1 |
| 5 | ToolEvidenceAdapter 废弃但仍使用 | HIGH | EvidenceIndexBuilder 内部使用废弃类解析 tool_reports | 统一使用 ToolExecutionEngine 的解析逻辑 | Step 1 |
| 6 | tests/ 目录兜底产生孤儿证据 | MEDIUM | 无 claim/task 声明路径时回退到整个 tests/ | 移除兜底逻辑，无路径则不执行工具 | Step 1 |
| 7 | tests/ 兜底的 covers 为空 | MEDIUM | 依赖 docstring 提取，无声明则为空 | 随 #6 一并移除 | Step 1 |
| 8 | hashlib 局部导入 | LOW | 条件导入标准库 | 移至函数顶部 | Step 1 |

---

## 三、 行动方案

### Step 1：UnifiedContext + 单次加载 + 死逻辑清理

**目标**：消灭重复 I/O，清理死代码，建立强类型领域模型。

**改动清单**：

| 序号 | 改动 | 涉及文件 | 解决问题 |
|---|---|---|---|
| 1.1 | 新建 `UnifiedContext` 强类型领域对象树 | `src/vibe_tracing/context.py` (新) | 架构基础 |
| 1.2 | `cli.py` 头部组装 `UnifiedContext`（单次加载+校验+解析） | `src/vibe_tracing/cli.py` | #2, #3, #4 |
| 1.3 | `EvidenceIndexBuilder.build()` 接受 `ctx: UnifiedContext` | `src/vibe_tracing/evidence_index_builder.py` | #2, #5 |
| 1.4 | 移除 `EvidenceIndexBuilder` 内部的 Loader 实例化 | `src/vibe_tracing/evidence_index_builder.py` | #2 |
| 1.5 | 移除 `ToolEvidenceAdapter` 的使用，统一用 `ToolExecutionEngine` | `src/vibe_tracing/evidence_index_builder.py` | #5 |
| 1.6 | 删除 `ToolEvidenceAdapter` 类 | `src/vibe_tracing/tool_evidence_adapter.py` | #5 |
| 1.7 | 四个 Analyzer 的 `analyze()`/`check()` 改为接受 `ctx: UnifiedContext` | 4 个 Analyzer 文件 | #2 |
| 1.8 | 删除 Step 5 中的二次 SHA-256 哈希计算 | `src/vibe_tracing/cli.py:712-733` | #3 |
| 1.9 | `TaskLoader`/`ClaimLoader` 跳过重复 Schema 校验 | `src/vibe_tracing/task_loader.py`, `claim_loader.py` | #4 |
| 1.10 | 移除 `tests/` 目录兜底逻辑 | `src/vibe_tracing/cli.py:797-801` | #6, #7 |
| 1.11 | `import hashlib` 移至 `run_analyze()` 函数顶部 | `src/vibe_tracing/cli.py` | #8 |
| 1.12 | 更新全量测试，确保无回归 | `tests/` | 验证 |

**UnifiedContext 领域模型**：

```python
@dataclass
class UnifiedContext:
    config: Dict[str, Any]
    prd: PrdParseResult
    constraints: Optional[Dict[str, Any]]
    tasks: Optional[TaskListLoadResult]
    claims: List[Any]                    # Claim objects
    tool_evidence: List[ToolEvidenceCandidate]  # 运行时生成
    manifest: InputManifest              # RawInputLoader 输出

    # 辅助方法
    def find_task(self, task_id: str) -> Optional[Task]: ...
    def find_requirement(self, req_id: str) -> Optional[Requirement]: ...
    def find_ac(self, ac_id: str) -> Optional[AcceptanceCriteria]: ...
```

**验证标准**：
- `RawInputLoader.load()` 执行次数 = 1
- `PrdParser.parse_file()` 执行次数 = 1
- `SchemaValidator` 对每个文件校验次数 = 1
- SHA-256 计算次数 = 1
- 全量测试通过

---

### Step 2：MergeGateEngine 逻辑修复

**目标**：不论 Gate Decision 如何，完整记录所有问题到 reasons。

**改动清单**：

| 序号 | 改动 | 涉及文件 |
|---|---|---|
| 2.1 | 移除 `if gate_decision != "blocked":` 限制 | `src/vibe_tracing/merge_gate_engine.py:132` |
| 2.2 | 将 fail 条件（unclear constraints, REQ/task gaps, should risks）独立评估 | `src/vibe_tracing/merge_gate_engine.py` |
| 2.3 | Gate Decision 优先级保持 `blocked > fail > pass`，但 reasons 包含全部 | `src/vibe_tracing/merge_gate_engine.py` |
| 2.4 | 新增测试：blocked 场景下 reasons 包含 fail 级警告 | `tests/test_merge_gate_engine.py` |

**修复后的逻辑结构**：

```python
def evaluate(self, gaps, risks, compliance_result, prd_status):
    gate_decision = "pass"
    reasons = []
    blocked_items = []

    # --- 始终执行，不论之前是否已 blocked ---

    # 1. Blocked 条件
    for gap in gaps:
        if gap["item_type"] == "ac":
            blocked_items.append(...)
            gate_decision = "blocked"

    for risk in risks:
        if risk["severity"] == "must" or "self-referential" in risk["description"]:
            blocked_items.append(...)
            gate_decision = "blocked"

    # ... 其他 blocked 条件 ...

    # 2. Fail 条件（不再包裹在 if != blocked 中）
    if compliance_result:
        for uc in compliance_result.get("unclear_constraints", []):
            reasons.append(...)   # ← 即使 blocked 也记录
            if gate_decision != "blocked":
                gate_decision = "fail"

    for gap in gaps:
        if gap["item_type"] != "ac":
            reasons.append(...)   # ← 即使 blocked 也记录
            if gate_decision != "blocked":
                gate_decision = "fail"

    for risk in risks:
        if risk["severity"] in ("should", "could"):
            reasons.append(...)   # ← 即使 blocked 也记录
            if gate_decision != "blocked":
                gate_decision = "fail"

    # 3. Pass
    if gate_decision == "pass" and not reasons:
        reasons.append("所有质量门禁规则均已通过。")

    return {"gate_decision": gate_decision, "reasons": reasons, "blocked_items": blocked_items}
```

**验证标准**：
- 当存在 AC gap（blocked）+ REQ gap（fail）时，reasons 同时包含两者
- 当存在 must risk（blocked）+ should risk（fail）时，reasons 同时包含两者
- gate_decision 始终为最高优先级（blocked > fail > pass）

---

### Step 3（可选，按需）：领域对象索引优化

**触发条件**：VT 实体规模增长到 R > 500，或需要跨项目追溯。

**改动方向**：在 `UnifiedContext` 中建立反向索引（`Dict[str, List[Task]]`），将 O(R×E) 列表扫描优化为 O(1) 字典查找。不是图引擎，是领域对象树的哈希表加速。

---

## 四、 重构前后对比

| 维度 | 重构前 | 重构后 (Step 1+2) |
|---|---|---|
| 文件 I/O 次数 | RawInputLoader ×2 | ×1 |
| PRD 解析次数 | PrdParser ×2 | ×1 |
| Task 校验次数 | TaskLoader ×2 | ×1 |
| Claim 校验次数 | ClaimLoader ×2 | ×1 |
| Schema 校验次数 | 每个 JSON 文件 ×2 | ×1 |
| SHA-256 计算次数 | ×2 | ×1 |
| blocked 时 fail 级警告 | 丢失 | 完整记录 |
| 废弃代码 (ToolEvidenceAdapter) | 仍在使用 | 已删除 |
| tests/ 兜底 | 产生孤儿证据 | 已移除 |

---

## 五、 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|---|---|---|---|
| UnifiedContext 改动面过大，引入回归 | 中 | 高 | 先写测试再改代码；每个 Analyzer 独立迁移，逐个验证 |
| EvidenceIndexBuilder 的 tool_reports 解析逻辑迁移不完整 | 低 | 中 | ToolExecutionEngine 已有完整的解析逻辑，直接复用 |
| MergeGateEngine 修复后测试用例不足 | 低 | 中 | 补充 blocked+fail 共存场景的测试 |
| Analyzer 签名变更导致外部调用方不兼容 | 低 | 低 | VT 是 CLI 工具，无外部 API 消费者 |

---

## 六、 交付顺序

```
Step 1 (UnifiedContext + 死逻辑清理)
  │
  ├─ 1.1  新建 context.py (UnifiedContext 数据结构)
  ├─ 1.2  cli.py 单次加载组装 UnifiedContext
  ├─ 1.3  EvidenceIndexBuilder 接受 UnifiedContext
  ├─ 1.4  移除 EvidenceIndexBuilder 内部 Loader
  ├─ 1.5  移除 ToolEvidenceAdapter 使用
  ├─ 1.6  删除 ToolEvidenceAdapter 类
  ├─ 1.7  四个 Analyzer 签名迁移
  ├─ 1.8  删除二次哈希计算
  ├─ 1.9  Loader 跳过重复 Schema 校验
  ├─ 1.10 移除 tests/ 兜底
  ├─ 1.11 hashlib 移至顶部
  └─ 1.12 全量测试验证
         │
         ▼
Step 2 (MergeGateEngine 修复)
  │
  ├─ 2.1  移除 if != blocked 限制
  ├─ 2.2  独立评估 fail 条件
  ├─ 2.3  reasons 包含完整清单
  └─ 2.4  补充测试
         │
         ▼
Step 3 (可选：索引优化)
  └─ 按需触发
```

> [!NOTE]
> Step 1 和 Step 2 可以并行开发（无代码依赖），但建议 Step 1 先合并（改动面大，需要充分测试），Step 2 随后（改动小，风险低）。

---

## 七、 原子化任务清单

> 每个任务可独立提交、独立核验。按依赖关系组织为 Wave，同一 Wave 内的任务可并行执行。

### 依赖关系总览

```
Wave 0 ── 无依赖，可立即开始（4 个任务并行）
  REFACTOR-001  UnifiedContext 数据结构
  REFACTOR-002  MergeGateEngine 逻辑修复
  REFACTOR-003  hashlib 顶部导入
  REFACTOR-004  移除 tests/ 兜底
       │
       ▼
Wave 1 ── 依赖 Wave 0（3 个任务并行）
  REFACTOR-005  cli.py 构建 UnifiedContext
  REFACTOR-006  cli.py 删除二次哈希 + 提取 Gate 1 结果
  REFACTOR-007  ArchitectureComplianceChecker 接受 constraints 参数
       │
       ▼
Wave 2 ── 依赖 Wave 1（3 个任务并行）
  REFACTOR-008  EvidenceIndexBuilder 接受 UnifiedContext
  REFACTOR-009  TaskLoader/ClaimLoader 跳过重复 Schema 校验
  REFACTOR-010  删除 ToolEvidenceAdapter 类
       │
       ▼
Wave 3 ── 依赖 Wave 2（1 个任务）
  REFACTOR-011  端到端回归验证
```

---

### Wave 0：基础修复（无依赖）

#### REFACTOR-001：定义 UnifiedContext 强类型领域对象

**解决的问题**：无统一的内存数据模型，各组件独立加载文件。

**涉及文件**：
- `src/vibe_tracing/context.py`（新建）

**行动指导**：

1. 创建 `src/vibe_tracing/context.py`，定义以下 dataclass：

```python
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class UnifiedContext:
    """Single source of truth for all parsed analysis inputs."""
    config: Dict[str, Any]
    prd: Any                          # PrdParseResult
    constraints: Optional[Dict[str, Any]] = None
    task_result: Optional[Any] = None  # TaskListLoadResult
    claims_list: List[Any] = field(default_factory=list)
    tool_evidence: List[Any] = field(default_factory=list)  # ToolEvidenceCandidate[]
    manifest: Optional[Any] = None     # InputManifest
    config_prefix: str = "VT"
```

2. 不添加辅助方法（`find_task` 等），保持最小化。后续按需扩展。

3. 新建测试 `tests/test_unified_context.py`：
   - 验证实例化所有字段
   - 验证默认值（`constraints=None`, `claims_list=[]`）
   - 验证 `tool_evidence` 可追加

**核验标准**：
- `python -m pytest tests/test_unified_context.py -v` 全部通过
- `context.py` 无外部依赖（仅 stdlib dataclasses/typing）

---

#### REFACTOR-002：MergeGateEngine 逻辑修复

**解决的问题**：`gate_decision == "blocked"` 时，fail 级警告被静默吞掉。

**涉及文件**：
- `src/vibe_tracing/merge_gate_engine.py`
- `tests/test_merge_gate_engine.py`

**行动指导**：

1. 修改 `evaluate()` 方法，移除 `if gate_decision != "blocked":` 限制（line 132）。

2. 将 blocked 和 fail 的评估逻辑改为两个独立的循环块：
   - **Block 评估**：遍历 gaps/risks/compliance，设置 `gate_decision = "blocked"`。
   - **Fail 评估**：独立遍历，**始终**将 fail 级问题追加到 `reasons`，仅在 `gate_decision != "blocked"` 时升级 `gate_decision`。

3. 伪代码结构：
```python
def evaluate(self, gaps, risks, compliance_result, prd_status):
    gate_decision = "pass"
    reasons = []
    blocked_items = []

    if prd_status == "draft":
        return {"gate_decision": "draft_approved", ...}

    # --- Phase 1: Blocked conditions ---
    # (existing blocked logic, unchanged)
    ...

    # --- Phase 2: Fail conditions (ALWAYS runs) ---
    # Unclear constraints
    if compliance_result:
        for uc in compliance_result.get("unclear_constraints", []):
            msg = f"存在不明确的架构约束规则 ({uc['rule_id']}): {uc['reason']}"
            reasons.append(msg)
            if gate_decision != "blocked":
                gate_decision = "fail"

    # Non-AC gaps
    for gap in gaps:
        if gap.get("item_type") != "ac":
            msg = f"非阻塞缺口 ({gap['item_type']} {gap['item_id']}): {gap['reason']}"
            reasons.append(msg)
            if gate_decision != "blocked":
                gate_decision = "fail"

    # Should/could risks
    for risk in risks:
        if risk.get("severity") in ("should", "could"):
            msg = f"低/中风险 ({risk.get('risk_id')}): {risk.get('description')}"
            reasons.append(msg)
            if gate_decision != "blocked":
                gate_decision = "fail"

    # --- Phase 3: Pass ---
    if gate_decision == "pass" and not reasons:
        reasons.append("所有质量门禁规则均已通过，无阻塞项或风险项。")

    return {"gate_decision": gate_decision, "reasons": reasons, "blocked_items": blocked_items}
```

4. 新增测试用例（在 `tests/test_merge_gate_engine.py` 中）：
   - **blocked + fail 共存**：构造 AC gap（blocked）+ REQ gap（fail）输入，验证 `gate_decision == "blocked"` 且 `reasons` 同时包含 AC gap 和 REQ gap 的描述。
   - **blocked + should risk 共存**：构造 must risk（blocked）+ should risk（fail）输入，验证 reasons 包含两者。
   - **纯 pass**：无 gaps 无 risks，验证 pass。
   - **纯 blocked**：仅 AC gap，验证 blocked 且 reasons 仅包含 blocked 原因。

**核验标准**：
- `python -m pytest tests/test_merge_gate_engine.py -v` 全部通过（含新增用例）
- 现有测试无回归

---

#### REFACTOR-003：hashlib 移至 run_analyze 函数顶部

**解决的问题**：`import hashlib` 在 Gate 1 的 `if` 块内条件导入，重构时易致 NameError。

**涉及文件**：
- `src/vibe_tracing/cli.py`

**行动指导**：

1. 在 `run_analyze()` 函数顶部的 import 区域添加 `import hashlib`。
2. 删除 Gate 1（约 line 547）内部的 `import hashlib`。

**核验标准**：
- `grep -n "import hashlib" src/vibe_tracing/cli.py` 仅出现一次，位于函数顶部
- `python -m pytest tests/test_cli_analyze.py -v` 通过

---

#### REFACTOR-004：移除 tests/ 目录兜底逻辑

**解决的问题**：无 claim/task 声明路径时回退到整个 `tests/` 目录，产生无来源孤儿证据。

**涉及文件**：
- `src/vibe_tracing/cli.py`

**行动指导**：

1. 删除 `cli.py` 中约 line 797-801 的兜底逻辑：
```python
# 删除以下代码
if not execution_paths:
    tests_dir = project_root / "tests"
    if tests_dir.is_dir():
        execution_paths.append("tests/")
```

2. 当 `execution_paths` 为空时，直接跳过工具执行（`tool_evidence_candidates` 保持为 `None`）。

3. 确认 `ToolExecutionEngine.execute_all([])` 不会崩溃（返回空列表）。

**核验标准**：
- `python -m pytest tests/test_cli_analyze.py tests/test_tool_execution.py -v` 通过
- 当无 claim 和 task 时，`vt analyze` 不执行任何工具，不产生孤儿证据

---

### Wave 1：cli.py 重构（依赖 Wave 0）

#### REFACTOR-005：cli.py 构建 UnifiedContext 并传递

**解决的问题**：`cli.py` 是唯一 I/O 入口，但未将已解析数据统一传递给下游。

**涉及文件**：
- `src/vibe_tracing/cli.py`

**行动指导**：

1. 在 `run_analyze()` 中，当所有输入加载和校验完成后（约 line 691 之后），组装 `UnifiedContext`：

```python
from vibe_tracing.context import UnifiedContext

ctx = UnifiedContext(
    config=raw_loader.config_data,
    prd=prd_res,
    constraints=constraints_record.content if constraints_record else None,
    task_result=task_res,
    claims_list=claims_list,
    tool_evidence=[],  # 工具执行后填充
    manifest=manifest,
    config_prefix=config_prefix,
)
```

2. 工具执行完成后（约 line 836），将结果注入 `ctx.tool_evidence = tool_evidence_candidates or []`。

3. 将 `ctx` 传入 `EvidenceIndexBuilder.build()` 调用（替换现有 kwargs）：
```python
evidences_index = index_builder.build(output_path=index_path, ctx=ctx)
```

4. 此步骤**不修改** `EvidenceIndexBuilder` 内部逻辑（Wave 2 再改），仅修改调用方式。

**核验标准**：
- `python -m pytest tests/test_cli_analyze.py -v` 通过
- `UnifiedContext` 实例在 `run_analyze()` 中被创建并传入 `build()`
- 现有行为不变（`EvidenceIndexBuilder` 仍内部重加载，但新增了 `ctx` 参数）

---

#### REFACTOR-006：cli.py 删除二次哈希计算，提取 Gate 1 结果

**解决的问题**：SHA-256 哈希在 Gate 1 和 Step 5 各计算一次。

**涉及文件**：
- `src/vibe_tracing/cli.py`

**行动指导**：

1. 在 Gate 1（约 line 546-560）中，将计算结果保存到局部变量：
```python
gate1_hash_valid = True  # 默认通过
if constraints_record and constraints_record.status == "ok":
    computed_hash = hashlib.sha256(Path(constraints_record.file_path).read_bytes()).hexdigest()
    stored_hash = raw_loader.config_data.get("architecture_constraints_hash")
    if stored_hash and stored_hash != computed_hash:
        print("FATAL: ...", file=sys.stderr)
        return 1
    gate1_hash_valid = True  # 通过或跳过
```

2. 在 Step 5（约 line 712-733）中，删除整个二次哈希校验块：
```python
# 删除以下代码块
config_hash = raw_loader.config_data.get("architecture_constraints_hash")
finalize_commit = raw_loader.config_data.get("finalize_git_commit")
if config_hash:
    if not finalize_commit:
        ...
    current_hash = hashlib.sha256(...).hexdigest()
    if current_hash != config_hash:
        ...
```

3. 保留 Step 5 中 `config_language` 检查和 `finalize_commit` 检查（如果需要），但移除哈希重计算。

**核验标准**：
- `grep -n "sha256" src/vibe_tracing/cli.py` 仅出现一次（Gate 1）
- `python -m pytest tests/test_cli_analyze.py tests/test_finalize.py -v` 通过

---

#### REFACTOR-007：ArchitectureComplianceChecker 接受 constraints 参数

**解决的问题**：`check()` 内部重新读取 `architecture_constraints.json`（第三次加载）。

**涉及文件**：
- `src/vibe_tracing/architecture_compliance_checker.py`
- `src/vibe_tracing/cli.py`
- `tests/test_architecture_compliance_checker.py`

**行动指导**：

1. 修改 `check()` 方法签名，新增可选参数：
```python
def check(self, evidences: List[Dict[str, Any]], constraints_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
```

2. 在 `check()` 方法内部，优先使用传入的 `constraints_data`：
```python
if constraints_data is not None:
    constraints = constraints_data
else:
    constraints = self._load_constraints()  # 保留 fallback
```

3. 在 `cli.py` 中调用时传入：
```python
compliance_res = compliance_checker.check(evidence_list, constraints_data=ctx.constraints)
```

4. 新增测试用例：传入 `constraints_data` 时不再读取文件。

**核验标准**：
- `python -m pytest tests/test_architecture_compliance_checker.py -v` 通过
- 传入 `constraints_data` 时，`_load_constraints()` 不被调用

---

### Wave 2：清理冗余（依赖 Wave 1）

#### REFACTOR-008：EvidenceIndexBuilder 接受 UnifiedContext

**解决的问题**：`build()` 内部全量重加载所有输入文件（2 倍 I/O）。

**涉及文件**：
- `src/vibe_tracing/evidence_index_builder.py`
- `tests/test_evidence_index_builder.py`

**行动指导**：

1. 修改 `build()` 方法签名：
```python
def build(self, output_path: Optional[Path] = None, ctx: Optional[UnifiedContext] = None, **kwargs) -> Dict[str, Any]:
```

2. 当 `ctx` 不为 None 时，跳过内部的 Loader/Parser/Loader 调用，直接使用 `ctx` 中的数据：
```python
if ctx is not None:
    prd_res = ctx.prd
    task_res = ctx.task_result
    claims_list = ctx.claims_list
    manifest = ctx.manifest
    config_prefix = ctx.config_prefix
    tool_evidence_candidates = ctx.tool_evidence
else:
    # 保留现有逻辑作为 fallback（向后兼容）
    manifest = self.raw_loader.load()
    ...（现有代码）
```

3. 移除 `__init__` 中 `ctx` 不为 None 时不需要的实例化（`raw_loader`, `prd_parser`, `task_loader`, `claim_loader`）。

4. 新增测试：传入 `ctx` 时验证输出与传入 `None`（走旧路径）时一致。

**核验标准**：
- `python -m pytest tests/test_evidence_index_builder.py -v` 通过
- 传入 `ctx` 时，`RawInputLoader.load()` 不被调用

---

#### REFACTOR-009：TaskLoader/ClaimLoader 跳过重复 Schema 校验

**解决的问题**：`cli.py` Step 1.1 已校验 Schema，Step 4a/4b 再次校验。

**涉及文件**：
- `src/vibe_tracing/task_loader.py`
- `src/vibe_tracing/claim_loader.py`
- `src/vibe_tracing/cli.py`

**行动指导**：

1. 在 `TaskLoader.load_and_validate()` 中新增参数：
```python
def load_and_validate(self, task_list_path, prd_res, arch_data=None, content=None, skip_schema: bool = False) -> TaskListLoadResult:
```

2. 当 `skip_schema=True` 时，跳过 Schema 校验步骤，直接进入解析逻辑。

3. 在 `cli.py` 中调用时传入 `skip_schema=True`：
```python
task_res = task_loader.load_and_validate(
    task_list_path, prd_res, arch_data=arch_data,
    content=task_list_record.content, skip_schema=True
)
```

4. 对 `ClaimLoader.load_and_validate()` 做相同改动。

**核验标准**：
- `python -m pytest tests/test_task_loader.py tests/test_claim_loader.py -v` 通过
- `skip_schema=True` 时不调用 `SchemaValidator.validate_dict()`

---

#### REFACTOR-010：删除 ToolEvidenceAdapter 类

**解决的问题**：废弃类仍在使用，与 `ToolExecutionEngine` 存在两套重复解析逻辑。

**涉及文件**：
- `src/vibe_tracing/tool_evidence_adapter.py`
- `src/vibe_tracing/evidence_index_builder.py`
- `tests/test_tool_evidence_adapter.py`

**行动指导**：

1. 确认 REFACTOR-008 已完成（`EvidenceIndexBuilder` 已使用 `UnifiedContext.tool_evidence`）。

2. 在 `evidence_index_builder.py` 中，移除 `ToolEvidenceAdapter` 的 import 和实例化。

3. 对于 `.vibetracing/tool_reports/*.json` 的遗留文件解析，改为使用 `ToolExecutionEngine` 的静态解析方法（或在 `UnifiedContext` 构建阶段由 `cli.py` 统一解析）。

4. 从 `tool_evidence_adapter.py` 中删除 `ToolEvidenceAdapter` 类（保留 `ToolExecutionEngine` 类）。

5. 删除或更新 `tests/test_tool_evidence_adapter.py` 中针对 `ToolEvidenceAdapter` 的测试（保留 `ToolExecutionEngine` 的测试）。

**核验标准**：
- `grep -r "ToolEvidenceAdapter" src/` 无结果
- `python -m pytest tests/ -v` 全部通过
- `tool_evidence_adapter.py` 中仅保留 `ToolExecutionEngine` 和 `ToolEvidenceCandidate`

---

### Wave 3：端到端验证（依赖 Wave 2）

#### REFACTOR-011：全量回归验证

**解决的问题**：确保所有重构无功能回归。

**涉及文件**：无代码改动，仅验证。

**行动指导**：

1. 运行全量测试：
```bash
python -m pytest tests/ -v --tb=short
```

2. 手动执行 `vt analyze` 并验证：
   - `output/evidence_index.json` 内容正确
   - `output/traceability_report.json` 内容正确
   - `output/dashboard.html` 可正常打开
   - `output/run_metadata.json` gate_decision 正确

3. 验证重复计算消除：
   - 在 `RawInputLoader.load()` 入口添加临时计数器，确认只执行 1 次
   - 在 `PrdParser.parse_file()` 入口添加临时计数器，确认只执行 1 次
   - 在 `hashlib.sha256()` 调用处添加临时计数器，确认只执行 1 次

4. 验证 MergeGateEngine 修复：
   - 构造包含 AC gap + REQ gap 的输入，确认 reasons 包含两者
   - 确认 `gate_decision == "blocked"` 且 reasons 不为空

5. 移除所有临时计数器。

**核验标准**：
- `python -m pytest tests/ -v` 全部通过
- `vt analyze` 端到端执行成功
- 重复计算已消除（各 Loader/Parser 执行 1 次）
- MergeGateEngine blocked 时 reasons 包含完整缺陷清单

---

### 任务索引

| Task ID | 标题 | Wave | 解决问题 | 涉及文件 |
|---|---|---|---|---|
| REFACTOR-001 | 定义 UnifiedContext 数据结构 | 0 | 架构基础 | `context.py` (新) |
| REFACTOR-002 | MergeGateEngine 逻辑修复 | 0 | blocked 吞掉 fail 警告 | `merge_gate_engine.py` |
| REFACTOR-003 | hashlib 移至顶部 | 0 | 局部导入 NameError 风险 | `cli.py` |
| REFACTOR-004 | 移除 tests/ 兜底 | 0 | 孤儿证据 | `cli.py` |
| REFACTOR-005 | cli.py 构建 UnifiedContext | 1 | 统一数据传递 | `cli.py` |
| REFACTOR-006 | 删除二次哈希计算 | 1 | 重复计算 | `cli.py` |
| REFACTOR-007 | ArchCompliance 接受 constraints | 1 | 第三次文件加载 | `architecture_compliance_checker.py` |
| REFACTOR-008 | EvidenceIndexBuilder 接受 ctx | 2 | 2 倍 I/O | `evidence_index_builder.py` |
| REFACTOR-009 | Loader 跳过重复 Schema | 2 | 2 倍 Schema 校验 | `task_loader.py`, `claim_loader.py` |
| REFACTOR-010 | 删除 ToolEvidenceAdapter | 2 | 废弃代码 | `tool_evidence_adapter.py` |
| REFACTOR-011 | 端到端回归验证 | 3 | 全量验证 | 无代码改动 |
