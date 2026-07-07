# 历史债务机制：重构设计

> 版本：v1
> 日期：2026-07-03
> 状态：重构设计
> 前置文档：`design_historical_debt_mechanism.md` v3、`design_rule_engine.md` v3、`design_rule_engine_formal_fsm.md` v2、`spec_stage7_business_logic_v2.md`
> 本文档是上述四份文档的延续，定义从当前代码实现到目标架构的重构路径。

---

## 1. 顶层约束

| # | 原则 | 说明 |
|---|------|------|
| P1 | 不考虑向后兼容 | 项目开发重构阶段，不保留旧架构代码、不写兼容层、不保留旧字段 |
| P2 | 不接受打补丁式重构 | 从源头彻底适配，接受无上限的重构范围 |
| P3 | 不得过度设计 | 无必要勿增实体，不为假想的未来需求预留抽象 |
| P4 | 不得重复代码逻辑 | 同一逻辑只存在一处，跨模块复用通过函数调用 |
| P5 | 测试文件视同业务代码 | 设计阶段列出影响清单但不设计测试细节 |

---

## 2. 重构范围

### 2.1 一句话描述

将 `MergeGateEngine` 中交织的信号计算、状态判定、门禁聚合三职责拆分为独立模块，引入 Issue 结构化模型和五状态 FSM，在 pipeline 阶段 7 与阶段 8 之间插入解释层 + 决策层。

### 2.2 不在范围内

- 阶段 1-6 的加载、工具执行、证据构建逻辑不变
- `queries.py` 的 SQL 查询不变（数据源不变）
- `schema.py` 的 DB 表结构不变
- `loaders.py` 的数据灌入逻辑不变
- `compliance/checker.py` 的架构合规检查不变
- `risk/advisor.py` 的风险生成逻辑不变
- `staleness.py` 的过期标记逻辑不变（stale 过滤仍在阶段 7 之后执行）
- `finalize.py` 和 `init.py` 的核心逻辑不变

### 2.3 变更分类

| 类别 | 文件 | 变更类型 |
|------|------|---------|
| 新增 | `domain/debt/` 包（5 个模块） | 全新 |
| 新增 | `domain/gate/classifier.py` | 全新 |
| 重写 | `domain/gate/engine.py` | 大幅瘦身 |
| 修改 | `cli/analyze/pipeline.py` | 插入阶段 7.5 |
| 修改 | `cli/analyze/db_analysis.py` | gap 结构化 |
| 修改 | `cli/analyze/reports.py` | report 结构演进 |
| 修改 | `cli/analyze/output.py` | 终端输出适配 |
| 修改 | `infra/validation/schemas/traceability_report.schema.json` | schema 演进 |
| 重写 | `templates/dashboard.template.html` 的 JS 分类逻辑 | 消费结构化数据 |
| 不变 | `domain/gate/claim_coverage.py` | 阶段 2 幽灵代码检测，与阶段 7.5 无关，不改动 |

---

## 3. 数据模型

### 3.1 Issue（核心模型）

```python
# domain/gate/classifier.py 内定义

@dataclass(frozen=True)
class Issue:
    issue_id: str              # 自动生成，格式 ISSUE-{seq}
    issue_type: IssueType      # 六维分类
    severity: Severity         # BLOCK | WARNING
    fingerprint: str           # SHA-256(issue_type + gap_target 规范化字符串)
    task_id: Optional[str]     # 静态归属，来自 claim.related_task 或 task 推导
    gap_targets: tuple         # 核销匹配键集合，frozenset 语义
    description: str           # 人类可读描述（替代当前 gate_reasons 中的文本）

class IssueType(str, Enum):
    BROKEN_CHAIN     = "broken_chain"
    MISALIGNED_CHAIN = "misaligned_chain"
    ISOLATED_TASK    = "isolated_task"
    NO_CLAIM         = "no_claim"
    TASK_FAILED      = "task_failed"
    TASK_SUBSTANDARD = "task_substandard"

class Severity(str, Enum):
    BLOCK   = "BLOCK"
    WARNING = "WARNING"
```

### 3.2 ClassifyResult（阶段 7.5 输出）

```python
# domain/debt/signals.py 内定义

@dataclass
class ClassifyResult:
    issue: Issue
    observed: bool
    activated: bool
    resolved: bool
    accepted: bool
    state: IssueState          # FSM 输出

class IssueState(str, Enum):
    CURRENT_BLOCK   = "CURRENT_BLOCK"
    CURRENT_WARNING = "CURRENT_WARNING"
    HISTORICAL      = "HISTORICAL"
    RESOLVED        = "RESOLVED"
    ACCEPTED        = "ACCEPTED"
```

### 3.3 Issue 构造规格

六维分类到 Issue 的映射规则：

| issue_type | severity | task_id 来源 | gap_targets 构造 | description 来源 |
|------------|----------|-------------|-----------------|-----------------|
| BROKEN_CHAIN | BLOCK | claim→related_task 或 task 推导 | `{source_id}→{target_id}` | 引用不存在的具体描述 |
| MISALIGNED_CHAIN | BLOCK | task_id | `{task_id}:{mismatch_type}` | 错位类型描述 |
| ISOLATED_TASK | WARNING | task_id | `{task_id}:{missing_type}` | 缺失关联类型 |
| NO_CLAIM | BLOCK | task_id | `{task_id}:no_claim` | 无声明描述 |
| TASK_FAILED | BLOCK | claim→related_task | `{claim_id}:{test_ref}` | 失败测试描述 |
| TASK_SUBSTANDARD | WARNING | claim→related_task | `{claim_id}:{metric}:{path}` | 不达标指标描述 |

### 3.4 指纹算法

```
fingerprint = SHA-256(f"{issue_type.value}|{sorted(gap_targets)[0]}|...")
```

指纹输入：issue_type + gap_targets 的规范化拼接。同一问题类型 + 同一匹配键 = 同一指纹。修复后重新出现 = gap_targets 变化 = 新指纹 = 与 baseline 中旧指纹不匹配。

### 3.5 Issue Baseline 文件格式

```json
// .vibetracing/issue_baseline.json
{
  "schema_version": "1.0.0",
  "architecture_hash": "abc123...",
  "prd_hash": "def456...",
  "created_at": "2026-07-03T10:00:00Z",
  "created_at_commit": "79c301a",
  "fingerprints": [
    "sha256:a1b2c3...",
    "sha256:d4e5f6..."
  ]
}
```

---

## 4. 模块设计

### 4.1 新增模块清单

```
src/vibe_tracing/
├── domain/
│   ├── gate/
│   │   ├── classifier.py      ← 新增：raw gap → Issue 分类器
│   │   ├── engine.py          ← 重写：瘦身为纯门禁聚合器
│   │   ├── claim_coverage.py  ← 保留：幽灵代码检测（pipeline 阶段 2 使用）
│   │   └── staleness.py       ← 不变
│   └── debt/
│       ├── __init__.py
│       ├── fingerprint.py     ← 新增：指纹计算
│       ├── baseline.py        ← 新增：baseline 读写
│       ├── signals.py         ← 新增：信号计算
│       ├── fsm.py             ← 新增：状态函数 F
│       └── redemption.py      ← 新增：覆盖核销匹配
```

### 4.2 `domain/gate/classifier.py`

**职责**：将阶段 7 的 raw gaps/risks 转换为 `List[Issue]`。

**输入**：
- `analysis_details: dict` — `run_db_analysis()` 的完整输出（含 ac_gaps, dangling_claims, claim_evidence_gaps, cov_violations, lint_violations, invalid_task_references, isolated_tasks, module_mismatches, arch_orphans）
- `claims_list: List[Claim]` — 用于 task_id 推导
- `human_decisions: dict` — 用于标记 accepted

**输出**：`List[Issue]`

**分类逻辑**：

```
输入源                          → issue_type          → severity
─────────────────────────────────────────────────────────────────
dangling_claims                 → BROKEN_CHAIN         → BLOCK
invalid_task_references         → BROKEN_CHAIN         → BLOCK
module_code_path_mismatch       → MISALIGNED_CHAIN     → BLOCK
invalid_ac_parent               → MISALIGNED_CHAIN     → BLOCK
isolated_tasks                  → ISOLATED_TASK        → WARNING
arch_orphans                    → ISOLATED_TASK        → WARNING
ac_gaps(no_claim_for_task)      → NO_CLAIM             → BLOCK
claim_evidence_gaps(test_failed)→ TASK_FAILED          → BLOCK
ac_gaps(test_failed)            → TASK_FAILED          → BLOCK
coverage_violations             → TASK_SUBSTANDARD     → WARNING
lint_violations                 → TASK_SUBSTANDARD     → WARNING
```

**注意**：`ghost_files` 不在此表中。幽灵代码在 pipeline 阶段 2（`claim_coverage.py`）已被检测并直接阻断提交，不会流入阶段 7.5。阶段 7.5 的 NO_CLAIM 数据来源仅为 `ac_gaps` 中 status 为 `no_claim_for_task` 的条目——task 状态为 done 但无对应 Claim，由 DB 查询 `check_ac_coverage` 产出。两者是不同路径、不同阶段、不同语义。

**task_id 推导规则**：

1. 数据源直接含 `claim_id` → 查 claims_list 得 `claim.related_task`
2. 数据源直接含 `task_id` → 直接使用
3. 数据源含 `req_id`/`ac_id` → 查 task_list 反推关联 task
4. 无法推导 → `task_id = None`

**去重**：同一 (issue_type, gap_targets) 组合只产出一个 Issue。多个数据源命中同一 gap_targets 时合并 description。

### 4.3 `domain/debt/fingerprint.py`

**职责**：为 Issue 计算稳定指纹。

**接口**：

```python
def compute_fingerprint(issue_type: IssueType, gap_targets: frozenset[str]) -> str:
    """返回 SHA-256 hex digest。"""
```

**实现**：

```python
def compute_fingerprint(issue_type, gap_targets):
    normalized = "|".join(sorted(gap_targets))
    raw = f"{issue_type.value}|{normalized}"
    return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"
```

### 4.4 `domain/debt/baseline.py`

**职责**：Issue baseline 的读写和存在性判定。

**接口**：

```python
class BaselineManager:
    def __init__(self, project_root: Path): ...

    def exists(self) -> bool:
        """`.vibetracing/issue_baseline.json` 是否存在。"""

    def load(self) -> set[str]:
        """返回 fingerprints 集合。文件不存在返回空集合。"""

    def save(self, fingerprints: set[str], meta: dict) -> None:
        """写入 baseline 文件。meta 含 architecture_hash, prd_hash, created_at_commit。"""

    def needs_rebuild(self, architecture_hash: str, prd_hash: str) -> bool:
        """当前 baseline 的架构/prd hash 与给定值不匹配时需要重建。"""
```

**存储路径**：`.vibetracing/issue_baseline.json`

**生命周期**：
- 首次 analyze：`exists() == False` → 生成 baseline
- 后续 analyze：`exists() == True` → 读取 baseline
- re-finalize 后：`needs_rebuild() == True` → 重建 baseline

### 4.5 `domain/debt/signals.py`

**职责**：为每个 Issue 计算四信号 (observed, activated, resolved, accepted)。

**接口**：

```python
@dataclass
class SignalResult:
    observed: bool
    activated: bool
    resolved: bool
    accepted: bool

class SignalComputer:
    def __init__(
        self,
        baseline: set[str],
        commit_task_set: set[str],
        claim_coverage: set[str],
        human_decisions: dict,
    ): ...

    def compute(self, issue: Issue) -> SignalResult: ...
```

**四信号计算逻辑**：

| 信号 | 计算方式 |
|------|---------|
| `observed` | `issue.fingerprint in baseline` |
| `activated` | `issue.task_id is not None and issue.task_id in commit_task_set` |
| `resolved` | `RedemptionEngine.check(issue, claim_coverage)` |
| `accepted` | `issue.fingerprint in human_decisions.accepted_set` |

**commit_task_set 构造**：

```python
# 从 staged 的 CLAIM-*.json 文件推导
commit_task_set = {
    claim.related_task
    for claim in claims_list
    if claim.claim_id in directly_staged_claims
}
```

不使用 `staged_items` 的文件路径交集。分界线是承诺（Task），不是空间重叠（文件路径）。

### 4.6 `domain/debt/fsm.py`

**职责**：纯函数 `F(o, a, r, c, v) → IssueState`。

**接口**：

```python
def classify_state(
    observed: bool,
    activated: bool,
    resolved: bool,
    accepted: bool,
    severity: Severity,
) -> IssueState:
```

**实现**（直接对应 `design_rule_engine_formal_fsm.md` Section 6.2）：

```python
def classify_state(observed, activated, resolved, accepted, severity):
    if resolved:
        return IssueState.RESOLVED
    if accepted:
        return IssueState.ACCEPTED
    if observed and not activated:
        return IssueState.HISTORICAL
    if severity == Severity.BLOCK:
        return IssueState.CURRENT_BLOCK
    return IssueState.CURRENT_WARNING
```

5 行分支，无循环，无外部依赖。可测试性：32 种输入组合穷举。

### 4.7 `domain/debt/redemption.py`

**职责**：判定 issue 的 gap_targets 是否被当前 claims 的覆盖范围全部核销。

**接口**：

```python
class RedemptionEngine:
    def __init__(self, claim_coverage: set[str]): ...

    def check(self, issue: Issue) -> bool:
        """所有 gap_targets 都被 claim_coverage 覆盖时返回 True。"""
```

**覆盖匹配规则**：

gap_target 是一个字符串标识。claim_coverage 是当前所有 claims 声明的覆盖键集合。匹配方式是集合包含：

```python
def check(self, issue: Issue) -> bool:
    return set(issue.gap_targets).issubset(self.claim_coverage)
```

**claim_coverage 构造**：

从当前 claims 列表提取所有覆盖键：

```python
claim_coverage: set[str] = set()
for claim in claims_list:
    # AC 覆盖
    for ac_id in get_task_acs(claim.related_task):
        claim_coverage.add(ac_id)
    # 测试覆盖
    for test_ref in claim.test_refs:
        claim_coverage.add(f"test:{test_ref}")
    # 代码覆盖
    for code_ref in claim.code_refs:
        claim_coverage.add(f"code:{code_ref}")
```

gap_targets 和 claim_coverage 使用相同的命名空间约定，确保匹配正确。

### 4.8 `domain/gate/engine.py`（重写）

**职责变更**：从 895 行的全功能引擎瘦身为纯门禁聚合器。

**删除的方法/属性**：

| 删除项 | 原因 |
|--------|------|
| `_is_current()` | 被 `SignalComputer.activated` 替代 |
| `_tag_reason()` | 不再使用文本前缀，Issue 携带结构化 state |
| `_historical_debt_count` | 从 `ClassifyResult.state` 统计 |
| `_check_claim_existence()` | 逻辑迁移至 classifier |
| `_check_dangling_claims()` | 逻辑迁移至 classifier |
| `_check_claim_evidence_gaps()` | 逻辑迁移至 classifier |
| `_check_ac_coverage()` | 逻辑迁移至 classifier |
| `_check_invalid_task_references()` | 逻辑迁移至 classifier |
| `_process_must_gaps()` | 逻辑迁移至 classifier + fsm |
| `_process_must_risks()` | 逻辑迁移至 classifier + fsm |
| `_process_should_gaps()` | 逻辑迁移至 classifier + fsm |
| `_process_should_risks()` | 逻辑迁移至 classifier + fsm |
| `_compute_gate_decision()` | 重写为聚合逻辑 |

**新的 evaluate() 接口**：

```python
class MergeGateEngine:
    def evaluate(self, results: list[ClassifyResult]) -> dict:
        """
        输入：已完成信号计算和 FSM 判定的 ClassifyResult 列表
        输出：门禁决策字典
        """
```

**聚合逻辑**：

```python
def evaluate(self, results):
    states = [r.state for r in results]

    has_block = IssueState.CURRENT_BLOCK in states
    has_warning = IssueState.CURRENT_WARNING in states

    if has_block:
        gate_decision = "blocked"
    elif has_warning:
        gate_decision = "warn"
    else:
        gate_decision = "pass"

    reasons = self._build_reasons(results)
    blocked_items = [
        r.issue.issue_id for r in results
        if r.state == IssueState.CURRENT_BLOCK
    ]
    historical_count = sum(
        1 for r in results if r.state == IssueState.HISTORICAL
    )

    return {
        "gate_decision": gate_decision,
        "reasons": reasons,
        "blocked_items": blocked_items,
        "historical_debt_count": historical_count,
        "issues": results,
    }
```

**reasons 构建**：从 `ClassifyResult` 列表生成人类可读文本。每条 reason 格式：

```
[{state}] {issue_type的中文描述}: {description}
```

示例：
```
[CURRENT_BLOCK] 链条中断: Claim CLAIM-VT-001 引用不存在的任务 TASK-999
[HISTORICAL] 任务不达标: Coverage 45.2% < 80% on src/foo.py
```

---

## 5. Pipeline 集成

### 5.1 阶段变更

```
阶段 7: run_db_analysis()
  │  输出不变：analysis_details dict（含 ac_gaps, dangling_claims, claim_evidence_gaps 等）
  │  新增：stale 过滤后输出 active 的 analysis_details
  ▼
阶段 7.5: _run_debt_classification()     ← 新增
  │
  │  Step 1: 构造 commit_task_set
  │    从 directly_staged_claims → claims_list → {claim.related_task}
  │
  │  Step 2: 构造 claim_coverage
  │    从 claims_list → 所有 AC/test/code 覆盖键
  │
  │  Step 3: Classifier 分类
  │    analysis_details → List[Issue]
  │
  │  Step 4: Baseline 管理
  │    BaselineManager.exists()?
  │      否 → 生成 baseline（所有 issue 的 fingerprint）
  │      是 → 读取 baseline
  │      needs_rebuild()? → 重建 baseline
  │
  │  Step 5: 信号计算 + FSM
  │    for issue in issues:
  │      signals = SignalComputer.compute(issue)
  │      state = fsm.classify_state(signals, issue.severity)
  │      results.append(ClassifyResult(issue, signals, state))
  │
  │  输出：List[ClassifyResult]
  ▼
阶段 8: MergeGateEngine.evaluate(results)
  │  输入从 16 个散参数变为 1 个 List[ClassifyResult]
  │  聚合 state → gate_decision
  ▼
阶段 9: 输出（reports, dashboard, terminal）
```

### 5.2 `_run_debt_classification()` 实现规格

```python
def _run_debt_classification(
    project_root: Path,
    analysis_details: dict,
    claims_list: list,
    ctx: UnifiedContext,
    directly_staged_claims: set[str],
    human_decisions: dict,
) -> list[ClassifyResult]:
    """阶段 7.5：解释层 + 决策层。"""

    # 1. commit_task_set
    commit_task_set = {
        claim.related_task
        for claim in claims_list
        if claim.claim_id in directly_staged_claims
    }

    # 2. claim_coverage
    claim_coverage = _build_claim_coverage(claims_list, ctx.task_result)

    # 3. 分类
    classifier = IssueClassifier()
    issues = classifier.classify(analysis_details, claims_list)

    # 4. Baseline
    baseline_mgr = BaselineManager(project_root)
    architecture_hash = ctx.config.get("architecture_constraints_hash", "")
    prd_hash = ctx.config.get("prd_hash", "")

    if not baseline_mgr.exists() or baseline_mgr.needs_rebuild(architecture_hash, prd_hash):
        fingerprints = {issue.fingerprint for issue in issues}
        baseline_mgr.save(fingerprints, {
            "architecture_hash": architecture_hash,
            "prd_hash": prd_hash,
        })

    baseline = baseline_mgr.load()

    # 5. 信号 + FSM
    signal_computer = SignalComputer(
        baseline=baseline,
        commit_task_set=commit_task_set,
        claim_coverage=claim_coverage,
        human_decisions=human_decisions,
    )

    results = []
    for issue in issues:
        signals = signal_computer.compute(issue)
        state = classify_state(
            signals.observed,
            signals.activated,
            signals.resolved,
            signals.accepted,
            issue.severity,
        )
        results.append(ClassifyResult(
            issue=issue,
            observed=signals.observed,
            activated=signals.activated,
            resolved=signals.resolved,
            accepted=signals.accepted,
            state=state,
        ))

    return results
```

### 5.3 pipeline.py 调用点变更

**当前**（`_evaluate_and_output` 内）：

```python
# 阶段 8 辅助：过滤 stale + 构建 staged_items
active_gaps, active_risks, staged_items, directly_staged_items = \
    _run_analysis_phase(ctx, merged_gaps, final_risks, ...)

# 阶段 8 辅助：门禁判定
gate_res = _run_gate_evaluation(
    project_root, active_gaps, active_risks, compliance_res, ctx,
    staged_items, directly_staged_items, human_decisions,
    ghost_files, ac_gaps, dangling_claims, ...  # 16 个参数
)
```

**重构后**：

```python
# 阶段 7 后续：stale 过滤
active_analysis = _filter_stale_analysis(analysis_details, merged_gaps, final_risks)

# 阶段 7.5：分类 + 信号 + FSM
classify_results = _run_debt_classification(
    project_root, active_analysis, claims_list, ctx,
    directly_staged_claims, human_decisions,
)

# 阶段 8：门禁聚合（1 个参数）
gate_res = _run_gate_evaluation(classify_results)
```

### 5.4 `_run_analysis_phase` 重构

当前 `_run_analysis_phase` 的两个职责：
1. 过滤 stale 项 → 保留
2. 构建 staged_items → 删除（被 commit_task_set 替代）

重构后只保留 stale 过滤，输出 active 的 analysis_details dict。不再构建 staged_items。

### 5.5 `_run_gate_evaluation` 重构

当前接收 16 个散参数。重构后接收 1 个 `List[ClassifyResult]`：

```python
def _run_gate_evaluation(results: list[ClassifyResult]) -> dict:
    engine = MergeGateEngine()
    return engine.evaluate(results)
```

---

## 6. db_analysis.py 变更

### 6.1 `run_db_analysis()` 输出结构变更

当前输出：

```python
{
    "ghost_files": [],              # ← 始终为空列表（阶段 2 已前置阻断，死代码）
    "ac_gaps": [...],
    "dangling_claims": [...],
    "claim_evidence_gaps": [...],
    "cov_violations": [...],
    "lint_violations": [...],
    "invalid_task_references": {...},
    "isolated_tasks": [...],
    "module_mismatches": [...],
    "arch_orphans": [...],
}
```

重构后输出结构：删除 `ghost_files` 字段（阶段 2 已前置阻断，此字段始终为空，无存在意义）。其余字段不变，分类逻辑由 classifier 消费。

### 6.2 gap 消息模板变更

当前 `_GAP_MESSAGES` 输出人类可读字符串。重构后 classifier 直接从原始查询结果构造 Issue.description，不再经过消息模板中转。

`_GAP_MESSAGES` 删除。classifier 内部为每种 issue_type 提供 `description` 构造逻辑。

### 6.3 `_db_result_to_gaps()` 变更

当前将查询结果转为 `{item_id, item_type, reason}` 字典。重构后保留此结构但 `reason` 字段改为更结构化的描述（保留字符串，但内容更精确），供 classifier 消费。

---

## 7. traceability_report.json 演进

### 7.1 结构变更

**删除字段**：

| 字段 | 原因 |
|------|------|
| `gate_reasons` | 被 `issues` 替代。reasons 文本从 issues 自动生成，不再独立存储 |
| `gate_blocked_items` | 被 `issues` 中 `state == CURRENT_BLOCK` 的条目替代 |
| `historical_debt_count` | 从 `issues` 中 `state == HISTORICAL` 计数 |
| `incremental_mode` | 不再需要此模式标志 |

**新增字段**：

```json
{
  "issues": [
    {
      "issue_id": "ISSUE-001",
      "issue_type": "broken_chain",
      "state": "CURRENT_BLOCK",
      "severity": "BLOCK",
      "fingerprint": "sha256:a1b2c3...",
      "task_id": "TASK-001",
      "gap_targets": ["CLAIM-VT-001→TASK-999"],
      "description": "Claim CLAIM-VT-001 引用不存在的任务 TASK-999",
      "observed": false,
      "activated": true,
      "resolved": false,
      "accepted": false
    }
  ]
}
```

**保留字段**：

`run_id`, `project_id`, `scan_time`, `gate_decision`, `requirement_coverage`, `gaps`, `risks`, `architecture_compliance_status`, `architecture_violations`, `unclear_constraints`, `accepted_rules`, `metadata`

### 7.2 Schema 变更

`traceability_report.schema.json` 新增 `issues` 字段定义：

```json
"issues": {
  "type": "array",
  "items": {
    "type": "object",
    "required": ["issue_id", "issue_type", "state", "severity", "fingerprint"],
    "properties": {
      "issue_id": { "type": "string" },
      "issue_type": {
        "type": "string",
        "enum": ["broken_chain", "misaligned_chain", "isolated_task",
                 "no_claim", "task_failed", "task_substandard"]
      },
      "state": {
        "type": "string",
        "enum": ["CURRENT_BLOCK", "CURRENT_WARNING", "HISTORICAL",
                 "RESOLVED", "ACCEPTED"]
      },
      "severity": {
        "type": "string",
        "enum": ["BLOCK", "WARNING"]
      },
      "fingerprint": { "type": "string" },
      "task_id": { "type": ["string", "null"] },
      "gap_targets": {
        "type": "array",
        "items": { "type": "string" }
      },
      "description": { "type": "string" },
      "observed": { "type": "boolean" },
      "activated": { "type": "boolean" },
      "resolved": { "type": "boolean" },
      "accepted": { "type": "boolean" }
    }
  }
}
```

`required` 数组新增 `"issues"`。

### 7.3 gate_decision 语义变更

当前 `gate_decision` 的枚举值：`pass`, `fail`, `blocked`, `draft_approved`

重构后：

| 当前值 | 重构后 | 条件 |
|--------|--------|------|
| `blocked` | `blocked` | 存在 `state == CURRENT_BLOCK` 的 issue |
| `fail` | 删除 | 合并入 `blocked`（当前 fail 和 blocked 的区分来自 incremental_only 模式，该模式删除） |
| `pass` | `pass` | 无 CURRENT_BLOCK 且无 CURRENT_WARNING |
| `draft_approved` | `draft_approved` | PRD 草稿阶段的特殊放行，保留 |

新增 `warn` 枚举值：存在 CURRENT_WARNING 但无 CURRENT_BLOCK 时。

最终枚举：`pass`, `warn`, `blocked`, `draft_approved`

---

## 8. Dashboard 变更

### 8.1 JS 分类逻辑重写

**删除**：`evaluatePipeline()` 函数（L897-1044）中的子串匹配逻辑。

**替代**：直接从 `traceability_report.issues` 读取结构化数据。

```javascript
function renderIssues(issues) {
    const byType = groupBy(issues, i => i.issue_type);
    const byState = groupBy(issues, i => i.state);

    // Pipeline 六维展示
    renderPipelineStage('broken_chain', byType['broken_chain'] || []);
    renderPipelineStage('misaligned', byType['misaligned_chain'] || []);
    renderPipelineStage('isolated', byType['isolated_task'] || []);
    renderPipelineStage('no_claim', byType['no_claim'] || []);
    renderPipelineStage('task_failed', byType['task_failed'] || []);
    renderPipelineStage('substandard', byType['task_substandard'] || []);

    // 历史债务 tab
    renderHistoricalDebts(byState['HISTORICAL'] || []);
}
```

### 8.2 状态展示映射

| state | Dashboard 展示 | 颜色 | 是否阻拦 |
|-------|---------------|------|---------|
| CURRENT_BLOCK | 红色标记 | 🔴 | 是 |
| CURRENT_WARNING | 黄色标记 | 🟡 | 否 |
| HISTORICAL | 灰色标记，保留 severity 颜色 | ⚪(🔴/🟡) | 否 |
| RESOLVED | 不展示（已从活跃列表移除） | — | — |
| ACCEPTED | 蓝色标记，附原因 | 🔵 | 否 |

### 8.3 删除的功能

- `[当前]`/`[预存]` 文本前缀渲染
- `evaluatePipeline()` 中的 `gate_reasons` 子串匹配
- `renderHistoricalDebts()` 中基于文本前缀的过滤
- `localStorage` 白名单管理（被 `human_decisions.json` 替代）

---

## 9. output.py 终端输出变更

### 9.1 当前输出格式

```
[当前] 链条中断: Claim CLAIM-VT-001 引用不存在的任务 TASK-999
[预存] 任务不达标: Coverage 45.2% < 80% on src/foo.py
📊 3 historical debts exist
```

### 9.2 重构后输出格式

```
■ CURRENT_BLOCK │ 链条中断 │ Claim CLAIM-VT-001 引用不存在的任务 TASK-999
□ HISTORICAL    │ 任务不达标 │ Coverage 45.2% < 80% on src/foo.py
─── 历史债务: 1 笔 │ 当前阻塞: 1 项 │ 当前告警: 0 项
```

### 9.3 实现

`_render_output()` 接收 `gate_res["issues"]: List[ClassifyResult]`，按 state 分组输出。不再使用 `_tag_reason()` 的文本前缀。

---

## 10. Baseline 生命周期

### 10.1 生成时机

```
vt init
  → 不生成 baseline

vt finalize（首次）
  → 不生成 baseline（只锁定架构 hash）

vt analyze（首次，finalize 之后）
  → 阶段 7.5 检测到 baseline 不存在
  → 执行完整检测，得到 N 个 issue
  → 将所有 fingerprint 写入 baseline
  → 本次评估中：所有 issue 的 observed = true
  → 根据 activated 判定 state：
      activated=true → CURRENT_BLOCK/WARNING
      activated=false → HISTORICAL

vt analyze（后续）
  → 阶段 7.5 读取 baseline
  → fingerprint ∈ baseline → observed = true
  → fingerprint ∉ baseline → observed = false（新 issue）

vt finalize（re-finalize，架构变更后）
  → 更新 config.json 中的 hash
  → 不直接触发 baseline 重建

vt analyze（re-finalize 后的首次）
  → 阶段 7.5 检测 needs_rebuild() == true
  → 重建 baseline（旧 baseline 覆盖）
```

### 10.2 首次 analyze 的 observed 语义

首次 analyze 时 baseline 不存在。处理策略：

1. 执行完整检测，得到 issues
2. 生成 baseline（写入所有 fingerprint）
3. **本次评估中，所有 issue 标记为 observed = true**

理由：首次 analyze 是"系统首次认知"，所有检测到的 issue 都是"已被系统认知"的。如果标记为 observed = false，首次运行会把所有存量问题当作 CURRENT_BLOCK 阻拦，违反"历史债务不惩罚当前工作"原则。

### 10.3 与 finalize 的关联

| finalize 输出 | baseline 消费方式 |
|--------------|-----------------|
| `architecture_constraints_hash` | baseline.meta.architecture_hash |
| `prd_hash` | baseline.meta.prd_hash |
| `finalize_git_commit` | baseline.meta.created_at_commit（取 analyze 时的 git commit，非 finalize commit） |

baseline 的 `needs_rebuild()` 比较 `architecture_hash` 和 `prd_hash`。任一不匹配 → 重建。

---

## 11. 影响清单

### 11.1 业务代码影响

| 文件 | 影响程度 | 变更描述 |
|------|---------|---------|
| `domain/gate/engine.py` | **重写** | 895 行 → ~150 行。删除全部检测和信号逻辑，只保留聚合 |
| `domain/gate/classifier.py` | **新增** | ~200 行。六维分类 + Issue 构造 |
| `domain/debt/__init__.py` | **新增** | 空文件 |
| `domain/debt/fingerprint.py` | **新增** | ~20 行 |
| `domain/debt/baseline.py` | **新增** | ~80 行 |
| `domain/debt/signals.py` | **新增** | ~60 行 |
| `domain/debt/fsm.py` | **新增** | ~20 行 |
| `domain/debt/redemption.py` | **新增** | ~40 行 |
| `cli/analyze/pipeline.py` | **修改** | 插入阶段 7.5，简化阶段 8 调用，删除 `_run_analysis_phase` 中的 staged_items 构建 |
| `cli/analyze/db_analysis.py` | **修改** | 删除 `_GAP_MESSAGES`，调整 gap 输出格式 |
| `cli/analyze/reports.py` | **修改** | report 结构适配（issues 替代 gate_reasons） |
| `cli/analyze/output.py` | **修改** | 终端输出从文本前缀改为结构化格式 |
| `infra/validation/schemas/traceability_report.schema.json` | **修改** | 新增 issues 字段，删除旧字段 |
| `templates/dashboard.template.html` | **修改** | JS 分类逻辑重写 |
| `domain/gate/staleness.py` | **不变** | stale 过滤逻辑不变 |
| `domain/gate/claim_coverage.py` | **不变** | 幽灵代码检测仍在 pipeline 阶段 2 使用 |
| `infra/db/queries.py` | **不变** | SQL 查询不变 |
| `infra/db/schema.py` | **不变** | DB 表结构不变 |
| `infra/db/loaders.py` | **不变** | 数据灌入不变 |
| `domain/compliance/checker.py` | **不变** | 架构合规检查不变 |
| `domain/risk/advisor.py` | **不变** | 风险生成不变 |
| `cli/finalize.py` | **不变** | 文件级 hash 逻辑不变 |
| `cli/init.py` | **不变** | 模板脚手架不变 |

### 11.2 测试文件影响清单

以下测试文件需要适配重构，但不在本文档中设计测试细节：

| 测试文件 | 影响原因 |
|---------|---------|
| `tests/test_gate_engine*.py` | engine.py 接口完全变更，需重写 |
| `tests/test_staleness*.py` | staged_items 相关测试需删除或适配 |
| `tests/test_pipeline*.py` | pipeline 阶段变更，需适配 |
| `tests/test_db_analysis*.py` | gap 输出格式变更 |
| `tests/test_reports*.py` | report 结构变更 |
| `tests/test_dashboard*.py` | Dashboard 数据消费变更 |
| `tests/test_output*.py` | 终端输出格式变更 |
| 新增 `tests/test_classifier*.py` | classifier 单元测试 |
| 新增 `tests/test_fsm*.py` | FSM 32 种组合穷举测试 |
| 新增 `tests/test_baseline*.py` | baseline 生命周期测试 |
| 新增 `tests/test_signals*.py` | 信号计算测试 |
| 新增 `tests/test_redemption*.py` | 核销匹配测试 |
| 新增 `tests/test_fingerprint*.py` | 指纹稳定性测试 |

---

## 12. 重构执行顺序

```
Phase 1 — 核心模型 + FSM（无外部依赖，可独立验证）
  1.1 定义 Issue, IssueType, Severity, IssueState, ClassifyResult 数据模型
  1.2 实现 fsm.py（5 行分支）
  1.3 实现 fingerprint.py
  1.4 编写 FSM 穷举测试（32 种组合）
  1.5 编写指纹稳定性测试

Phase 2 — 分类器（依赖 Phase 1 的数据模型）
  2.1 实现 classifier.py
  2.2 从 engine.py 迁移检测逻辑到 classifier
  2.3 删除 engine.py 中的检测方法
  2.4 删除 _GAP_MESSAGES

Phase 3 — 信号层 + Baseline（依赖 Phase 1 + Phase 2）
  3.1 实现 baseline.py
  3.2 实现 redemption.py
  3.3 实现 signals.py
  3.4 编写 baseline 生命周期测试
  3.5 编写信号计算测试

Phase 4 — Pipeline 集成（依赖 Phase 1-3）
  4.1 在 pipeline.py 中插入阶段 7.5
  4.2 重写 engine.py 为纯聚合器
  4.3 重写 _run_gate_evaluation()
  4.4 删除 _run_analysis_phase 中的 staged_items 构建
  4.5 适配 output.py 终端输出

Phase 5 — 输出层适配（依赖 Phase 4）
  5.1 修改 reports.py（report 结构演进）
  5.2 修改 traceability_report.schema.json
  5.3 重写 dashboard.template.html 的 JS 分类逻辑
  5.4 删除 dashboard 中的 evaluatePipeline() 子串匹配

Phase 6 — 清理
  6.1 删除 engine.py 中所有已迁移的方法
  6.2 删除 pipeline.py 中不再使用的参数传递
  6.3 删除 dashboard 中不再使用的 [当前]/[预存] 渲染逻辑
  6.4 更新所有受影响的测试文件
```

Phase 1-3 可独立验证（纯函数 + 数据模型）。Phase 4 是集成点。Phase 5 是输出适配。Phase 6 是清理。
