# 重构：Stage 2 / Stage 7 共享 Claim 命中计算

## 问题

Stage 2（幽灵代码检测）和 Stage 7（陈旧项标记）各自独立遍历 `claims_list`，
计算"哪些 Claim 的 refs 命中 staged_files"。遍历模式相同，产出不同。

### 现存 Bug

`_collect_claimed_files()` 只收集 `code_refs`，忽略 `test_refs`。
只修改测试文件（已在 Claim 的 `test_refs` 中声明）时被误判为幽灵代码：

```yaml
# CLAIM-VT-042
code_refs: ["src/foo.py"]
test_refs: ["tests/test_foo.py"]
```

`git add tests/test_foo.py` → `tests/test_foo.py ∉ all_claimed` → 阻断。
`test_refs` 的语义是"此 Claim 声明了这些测试作为证据"——该文件已被治理，不是幽灵代码。

## 方案

### 核心决策：Pipeline 调度一次，分发给各 Stage

```
Pipeline 层:
  staged_files, all_claimed, affected_claim_ids = _prepare_stage_inputs(ctx)
                                                  └── find_claimed_and_affected()
  ├─→ Stage 2: detect_ghost_code(staged_files, all_claimed, ctx)
  └─→ Stage 7: mark_staleness(gaps, risks, affected_claim_ids, ...)
```

与 `staged_files` 同等对待——一次计算，多处传递。这是 pipeline 调度层的本职：
决定什么数据在什么时机被计算，然后分发给需要的阶段。**让各 stage 各自调用同一个函数
才是放弃了调度职责**——pipeline 不再知道两个 stage 共享了这个计算，也无法保证只算一次。

### 共享函数：放入 `domain/gate/claim_coverage.py`

```python
def find_claimed_and_affected(
    claims_list: list,
    staged_files: set[str],
) -> tuple[set[str], set[str]]:
    """一次遍历 claims_list，同时产出 Stage 2 和 Stage 7 所需的数据。

    Returns:
        all_claimed:         所有被 Claim 覆盖的文件路径（code_refs + test_refs）
        affected_claim_ids:  refs 命中 staged_files 的 Claim ID 集合
    """
    all_claimed: set[str] = set()
    affected_claim_ids: set[str] = set()

    for claim in claims_list:
        cid = claim.claim_id
        for ref in (claim.code_refs or []) + (claim.test_refs or []):
            path = ref.split("#")[0].split("::")[0]
            if not path:
                continue
            all_claimed.add(path)
            if path in staged_files:
                affected_claim_ids.add(cid)

    return all_claimed, affected_claim_ids
```

### Pipeline 调用点

```python
# pipeline.py — 紧接 staged_files 获取之后，Stage 2 之前
from vibe_tracing.domain.gate.claim_coverage import find_claimed_and_affected

staged_files = _get_staged_files()
all_claimed, affected_claim_ids = find_claimed_and_affected(
    ctx.claims_list, staged_files,
)

# Stage 2: 幽灵代码检测
result = detect_ghost_code(ctx, staged_files, all_claimed=all_claimed)

# ... Stage 3-6 ...

# Stage 7: 分析（传入 affected_claim_ids，避免内联重算）
merged_gaps, ... = _run_db_analysis(
    conn, ctx, project_root,
    staged_files=staged_files,
    affected_claim_ids=affected_claim_ids,  # 新增
    human_decisions=human_decisions,
)
```

### 调用方变更

| 调用方 | 变更 |
|--------|------|
| `pipeline.py` | 加一行 `find_claimed_and_affected()` 调用，结果分别传入 Stage 2 和 7 |
| `claim_coverage.py:detect_ghost_code()` | `all_claimed` 改为参数传入（不再内部计算），`GhostCodeResult` 不新增字段 |
| `claim_coverage.py:_collect_claimed_files()` | **删除**——遍历逻辑已提升到 pipeline 层 |
| `staleness.py:mark_staleness()` | 删除内联 affected-claim 计算（行 91-106），改为接收 `affected_claim_ids` 参数 |
| `staleness.py:determine_affected_items()` | 改为接收 `affected_claim_ids` 参数，仅做 claim→task→req/ac 传播 |
| `_run_analysis_phase()` | `_determine_affected_items()` 调用传入预计算的 `affected_claim_ids` |
| `_run_db_analysis()` | 透传 `affected_claim_ids` 给 `mark_staleness()` |

### 消除的代码

```
claim_coverage.py  _collect_claimed_files:         -9 行  (删除)
staleness.py       mark_staleness 内联计算:        -16 行
staleness.py       determine_affected_items 首轮:   -10 行
─────────────────────────────────────────────────────────
删除: ~35 行
新增: claim_coverage.py find_claimed_and_affected  +25 行
新增: pipeline.py 调用 + 传参                       +5 行
─────────────────────────────────────────────────────────
净减: ~5 行。核心收益不是代码量，是消除重复遍历 + 修复
      test_refs 遗漏 Bug。
```

### 不改的部分

- `mark_staleness` 的 claim→task→req/ac 传播逻辑（staleness.py:108-148）—— Stage 7 独有业务，不共享
- `_run_analysis_phase` 的 `directly_staged_items` 计算（pipeline.py:700-706）—— 从 CLAIM-*.json 文件名直接提取，不依赖 refs 遍历

## 影响范围

| 文件 | 操作 |
|------|------|
| `domain/gate/claim_coverage.py` | 修改（新增 `find_claimed_and_affected` + 删除 `_collect_claimed_files` + `detect_ghost_code` 签名字段） |
| `domain/gate/staleness.py` | 修改（`mark_staleness` / `determine_affected_items` 签名） |
| `cli/analyze/pipeline.py` | 修改（加调用点 + 传参） |

## 测试

- 现有测试全部保持通过——行为不变
- 新增：仅 staged `test_refs` 文件不触发幽灵代码阻断（覆盖 Bug 修复）
