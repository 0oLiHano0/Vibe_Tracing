# directly_staged_items 构建逻辑缺陷分析

**日期**: 2026-06-09
**状态**: 待修复
**关联**: EVO-TASK-011 (Claim 自动失效机制), EVO-TASK-012 (变更分离机制)

---

## 一、问题描述

当 `agent_claims.json` 被 staged 时，**所有** claims 都被视为"直接修改"，而非仅实际被修改的 claim。这导致旧 claims 的预存风险被错误地标记为 `[当前]` 问题，阻断提交。

**实际发生**：
- 提交中只有 CLAIM-VT-066 被修改（新增了 `tests/test_merge_gate_engine.py` 到 code_refs）
- 但 34 个 claims 全部被加入 `directly_staged_items`
- 旧 claims 引用的被修改文件（如 cli.py）被工具标记为 "violated"
- `_is_current()` 判定这些 claims 为"当前问题" → 门禁 BLOCKED

**预期行为**：
- 只有 CLAIM-VT-066 应被视为"直接修改"
- 其余 33 个 claims 应被视为"间接影响"，标记为 `[预存]`

---

## 二、根因定位

**文件**: `src/vibe_tracing/cli.py` 第 1690 行

```python
if claims_file_rel in staged_files:
    directly_staged_claims = set(affected_claims)  # ← BUG
```

**问题**：`affected_claims` 来自 `_determine_affected_items()`，该函数通过 `code_refs`/`test_refs` 路径匹配 staged files。当 `agent_claims.json` 和大量代码文件同时被 staged 时，几乎所有 claims 都有至少一个 `code_refs` 或 `test_refs` 路径匹配 staged 文件，导致全部进入 `affected_claims`。

**调用链**：
```
staged_files = {agent_claims.json, cli.py, merge_gate_engine.py, ...}
  → _determine_affected_items(staged_files, claims_list, ctx)
    → 遍历每个 claim 的 code_refs/test_refs
    → 几乎所有 claim 都有 code_refs 匹配 staged 的 .py 文件
    → affected_claims = {CLAIM-VT-005, 031, 033, ..., 066}  # 全部 34 个
  → directly_staged_claims = set(affected_claims)  # 全部 34 个
```

**核心矛盾**：`_determine_affected_items()` 设计用于"哪些 claims 受 staged 文件影响"，不是"哪些 claims 被直接修改"。这两个概念被混为一谈。

---

## 三、解决方案：per-claim 内容哈希

### 设计思路

**不解析 git diff**，而是在数据结构层面解决：每个 claim 携带一个内容哈希。哈希变化 = claim 变化。

这是 EVO-TASK-011（Claim 自动失效机制）的核心数据结构，同时解决了"直接修改检测"和"claim 自动失效"两个问题。

### 数据结构变更

在 `agent_claims.json` 的每个 claim 中新增 `content_hash` 字段：

```json
{
    "claim_id": "CLAIM-VT-066",
    "content_hash": "a1b2c3d4e5f6",
    "related_task": "TASK-VT-064",
    "code_refs": ["..."],
    "test_refs": ["..."],
    "timestamp": "2026-06-09T00:37:16Z"
}
```

### 哈希计算

```python
def _compute_claim_hash(claim: Dict) -> str:
    """计算 claim 的内容哈希（排除 hash 和 timestamp 本身）。"""
    import hashlib, json
    content = {k: v for k, v in claim.items() if k not in ("content_hash", "timestamp")}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:16]
```

### 变更检测

```python
def _get_directly_modified_claims(
    old_claims: List[Dict],
    new_claims: List[Dict],
) -> Set[str]:
    """通过比较 per-claim 内容哈希检测实际修改的 claims。"""
    old_hashes = {c["claim_id"]: c.get("content_hash") for c in old_claims}
    new_hashes = {c["claim_id"]: c.get("content_hash") for c in new_claims}

    modified = set()
    for claim_id, new_hash in new_hashes.items():
        old_hash = old_hashes.get(claim_id)
        if old_hash is None:
            modified.add(claim_id)  # 新增
        elif old_hash != new_hash:
            modified.add(claim_id)  # 内容变化
    return modified
```

### 集成到 cli.py

```python
# 从 git 获取旧版本 claims
old_claims_json = git_show(project_root, "HEAD:.vibetracing/agent_claims.json")
old_claims = json.loads(old_claims_json) if old_claims_json else []
new_claims = [asdict(c) for c in claims_list]

directly_staged_claims = _get_directly_modified_claims(old_claims, new_claims)
```

### 哈希维护

在所有修改 claim 的操作中重新计算 `content_hash`：
- `vt accept` 命令
- claims 文件的手动编辑（下次 `vt analyze` 时自动修复）
- 批量迁移脚本（一次性为所有现有 claims 填充 hash）

---

## 四、与 git diff 方案的对比

| 维度 | git diff 方案 | per-claim 哈希方案 |
|---|---|---|
| 可靠性 | 低（文本解析脆弱） | 高（哈希比较确定性） |
| 格式变化 | 误判（空格、逗号） | 不受影响 |
| claim 重排序 | 误判 | 不受影响 |
| 非 git 场景 | 失效 | 正常工作 |
| 与 EVO-TASK-011 关系 | 独立补丁 | 正好是 011 的核心机制 |
| 历史债务依赖 | 适配当前混乱状态 | 面向最终方案设计 |

**结论**：per-claim 哈希是面向最终状态的方案，不因历史债务而降低设计质量。历史债务（现有 claims 缺少 `content_hash`）通过独立的迁移任务解决。

---

## 五、影响范围

| 文件 | 行号 | 影响 |
|---|---|---|
| `src/vibe_tracing/cli.py` | 1688-1692 | 构建 directly_staged_claims 的逻辑 |
| `src/vibe_tracing/merge_gate_engine.py` | 120 | risk_staged 使用 directly_staged_items |
| `.vibetracing/agent_claims.json` | 全文件 | 新增 content_hash 字段 |
| `src/vibe_tracing/claim_loader.py` | 加载逻辑 | 哈希校验 |
| `tests/test_merge_gate_engine.py` | 743-911 | 测试补充 |

---

## 六、原子化任务

- [x] **Task ID**: FIX-TASK-001
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**: 新增 `_compute_claim_hash(claim)` 和 `_get_directly_modified_claims(old_claims, new_claims)` 函数。在 `_evaluate_and_output()` 中，通过 `git show HEAD:.vibetracing/agent_claims.json` 获取旧版本 claims，与当前 claims 比较哈希，仅将哈希变化的 claims 加入 `directly_staged_claims`。替换第 1688-1692 行的构建逻辑。
  - **AC**: 当只有 CLAIM-VT-066 的 content_hash 变化时，`directly_staged_claims` 只包含 CLAIM-VT-066
  - **前置依赖**: 无

- [x] **Task ID**: FIX-TASK-002
  - **Action**: MODIFY
  - **Target File**: `.vibetracing/agent_claims.json`
  - **Instruction**: 批量为所有现有 claims 计算并填充 `content_hash` 字段。编写一次性迁移脚本，遍历所有 claims，调用 `_compute_claim_hash()` 写入结果。
  - **AC**: 所有 claims 都有 `content_hash` 字段，值为 16 字符十六进制字符串
  - **前置依赖**: FIX-TASK-001（需要 `_compute_claim_hash` 函数）

- [x] **Task ID**: FIX-TASK-003
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/claim_loader.py`
  - **Instruction**: 在 claim 加载时校验 `content_hash`。如果 claim 缺少 `content_hash`，自动计算并补写。如果 `content_hash` 与实际内容不匹配，重新计算并更新。
  - **AC**: 加载 claims 时自动修复缺失或不匹配的 content_hash
  - **前置依赖**: FIX-TASK-001

- [x] **Task ID**: FIX-TASK-004
  - **Action**: MODIFY
  - **Target File**: `tests/test_merge_gate_engine.py`
  - **Instruction**: 新增测试验证 per-claim 哈希的精确过滤：
    1. 两个 claims 列表，只有 1 个 claim 的 content_hash 不同 → 只有该 claim 被检测为修改
    2. 新增 claim（old 中不存在）→ 被检测为修改
    3. claim 删除（new 中不存在）→ 不影响检测
    4. content_hash 缺失时的降级行为
  - **AC**: 4 个新测试全部通过
  - **前置依赖**: FIX-TASK-001

- [x] **Task ID**: FIX-TASK-005
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`, `src/vibe_tracing/claim_loader.py`
  - **Instruction**: 在所有修改 claim 的代码路径中，调用 `_compute_claim_hash()` 更新 `content_hash`：
    - `vt accept` 命令中修改 claim 后
    - claim_loader 中自动修复 hash 后回写文件
    - 任何新增/修改 claim 的地方
  - **AC**: 修改 claim 后 content_hash 自动更新
  - **前置依赖**: FIX-TASK-001, FIX-TASK-003

---

## 七、与 EVO-TASK-011 的关系

本方案**就是** EVO-TASK-011（Claim 自动失效机制）的核心数据结构。per-claim 内容哈希同时解决两个问题：

1. **直接修改检测**（本问题）：比较新旧 claims 的 hash，识别实际修改的 claims
2. **Claim 自动失效**（EVO-TASK-011）：比较 claim 的 hash 与引用文件的 hash，检测 claim 是否需要重新验证

EVO-TASK-011 的完整实现还包括：
- 存储每个 claim 引用文件的 hash 到 `claim_fingerprints.json`
- 在 `vt analyze` 时比较文件当前 hash 与存储的 hash
- 将 hash 不匹配的 claim 标记为 `needs_reverification`

本方案只实现第一层（per-claim 自身 hash），EVO-TASK-011 实现第二层（per-claim 引用文件 hash）。两层独立，本方案不依赖 EVO-TASK-011 的完整实现。
