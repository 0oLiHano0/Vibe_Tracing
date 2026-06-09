# Claim 自动失效机制 — 第二层实现方案

**日期**: 2026-06-09
**状态**: ✅ 已实施
**关联**: EVO-TASK-011, directly_staged_items_bug_20260609.md

---

## 一、背景

第一层（per-claim 自身哈希）已实现：每个 claim 携带 `content_hash`，通过比较新旧 hash 检测 claim 是否被直接修改。

第二层（claim 引用文件哈希）待实现：检测 claim 引用的文件是否变化，自动标记 claim 为 `needs_reverification`。

**设计规范**已在 `src/vibe_tracing/traceability/claim_evidence_analyzer.py:8-67` 中定义。

---

## 二、数据结构

### claim_fingerprints.json

```json
{
  "CLAIM-VT-005": {
    "timestamp": "2026-06-09T04:00:00Z",
    "fingerprints": {
      "src/vibe_tracing/raw_input_loader.py": "abc123def456...",
      "tests/test_raw_input_loader.py": "789ghi012jkl..."
    }
  },
  "CLAIM-VT-066": {
    "timestamp": "2026-06-09T04:00:00Z",
    "fingerprints": {
      "src/vibe_tracing/cli.py": "mno345pqr678...",
      "src/vibe_tracing/merge_gate_engine.py": "stu901vwx234...",
      "tests/test_merge_gate_engine.py": "yza567bcd890..."
    }
  }
}
```

每个 claim 存储其 `code_refs` + `test_refs` + `evidence_refs` 中所有文件的 SHA-256 哈希。

### 状态生命周期

```
covered → needs_reverification (引用文件 hash 变化)
needs_reverification → covered (重新分析确认证据仍有效)
needs_reverification → violated (重新分析发现证据已损坏)
needs_reverification → blocked (证据文件被删除)
```

---

## 三、实现方案

### 3.1 文件指纹存储

在 `vt analyze` 完成后，遍历所有 claims，计算其引用文件的 SHA-256 哈希，写入 `.vibetracing/claim_fingerprints.json`。

**代码位置**：`cli.py` 的 `_evaluate_and_output()` 函数末尾

```python
def _save_claim_fingerprints(claims_list, project_root):
    """保存所有 claim 引用文件的 SHA-256 指纹。"""
    fingerprints = {}
    for claim in claims_list:
        claim_id = claim.claim_id if hasattr(claim, 'claim_id') else claim.get('claim_id')
        refs = set()
        for ref in (claim.code_refs or []) + (claim.test_refs or []) + (claim.evidence_refs or []):
            path = ref.split("#")[0]
            if path:
                refs.add(path)

        file_hashes = {}
        for ref_path in refs:
            full_path = project_root / ref_path
            if full_path.exists():
                h = _file_sha256(full_path)
                if h:
                    file_hashes[ref_path] = h

        if file_hashes:
            fingerprints[claim_id] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "fingerprints": file_hashes,
            }

    fp_path = project_root / ".vibetracing" / "claim_fingerprints.json"
    fp_path.write_text(json.dumps(fingerprints, indent=2, ensure_ascii=False), encoding="utf-8")
```

### 3.2 失效检测

在 `ClaimEvidenceAnalyzer.analyze()` 开始前，加载 `claim_fingerprints.json`，比较当前文件 hash 与存储的 hash。

**代码位置**：`claim_evidence_analyzer.py` 的 `analyze()` 方法

```python
def _check_invalidation(self, claim, stored_fingerprints):
    """检查 claim 引用的文件是否自上次分析后发生变化。"""
    claim_id = claim.claim_id
    stored = stored_fingerprints.get(claim_id)
    if not stored:
        return None  # 无历史指纹，跳过

    changed_files = []
    for ref_path, old_hash in stored["fingerprints"].items():
        full_path = self.project_root / ref_path
        if not full_path.exists():
            changed_files.append((ref_path, old_hash, "deleted"))
        else:
            current_hash = _file_sha256(full_path)
            if current_hash and current_hash != old_hash:
                changed_files.append((ref_path, old_hash, current_hash))

    if changed_files:
        return {
            "claim_id": claim_id,
            "changed_files": changed_files,
            "stored_timestamp": stored["timestamp"],
        }
    return None
```

### 3.3 新增枚举值

**`core/enums.py`**：

```python
class CoverageStatus(str, Enum):
    # ... 现有值 ...
    NEEDS_REVERIFICATION = "needs_reverification"
```

### 3.4 生成失效风险

当检测到文件变化时，生成一个风险条目：

```python
{
    "risk_id": "RISK-INVALIDATED-CLAIM-VT-005",
    "risk_category": "claim_invalidated_by_file_change",
    "severity": "must",
    "claim_id": "CLAIM-VT-005",
    "description": "Claim CLAIM-VT-005 引用的文件已变化，需要重新验证",
    "changed_files": ["src/vibe_tracing/raw_input_loader.py"],
    "suggested_action": "重新运行 vt analyze 验证证据是否仍然有效，或手动确认 claim 仍然正确"
}
```

### 3.5 Dashboard 集成

- 新增 `needs_reverification` 标签样式（琥珀色/黄色）
- 在"待决策"标签页中，自动生成失效 claim 的决策卡片：
  - "Claim 证据可能已变化。重新验证还是接受风险？"
  - 按钮：[重新验证] [接受风险]

---

## 四、原子化任务

- [x] **Task ID**: CLAIM-TASK-001
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/core/enums.py`
  - **Instruction**: `CoverageStatus` 新增 `NEEDS_REVERIFICATION = "needs_reverification"`
  - **AC**: 枚举值可导入，`CoverageStatus.NEEDS_REVERIFICATION.value == "needs_reverification"`
  - **前置依赖**: 无

- [x] **Task ID**: CLAIM-TASK-002
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/traceability/claim_evidence_analyzer.py`
  - **Instruction**:
    1. 新增 `_check_invalidation(claim, stored_fingerprints)` 方法
    2. 在 `analyze()` 开始前加载 `claim_fingerprints.json`
    3. 对每个 claim 调用 `_check_invalidation`
    4. 如果检测到文件变化，生成 `claim_invalidated_by_file_change` 风险
    5. 将 claim 的 evidence 状态标记为 `needs_reverification`
  - **AC**: 当引用文件 hash 变化时，claim 被标记为 needs_reverification 并生成风险
  - **前置依赖**: CLAIM-TASK-001

- [x] **Task ID**: CLAIM-TASK-003
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/cli.py`
  - **Instruction**:
    1. 新增 `_save_claim_fingerprints(claims_list, project_root)` 函数
    2. 在 `_evaluate_and_output()` 末尾调用，保存所有 claim 引用文件的 SHA-256 指纹
    3. 新增 `_file_sha256(path)` 工具函数（或复用 claim_evidence_analyzer 中的）
  - **AC**: `vt analyze` 运行后 `.vibetracing/claim_fingerprints.json` 被创建/更新
  - **前置依赖**: 无

- [x] **Task ID**: CLAIM-TASK-004
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/templates/dashboard.template.html`
  - **Instruction**:
    1. 新增 `needs_reverification` 标签样式（琥珀色）
    2. 在"待决策"标签页中，为失效 claim 自动生成决策卡片
    3. 决策卡片问题："Claim 证据可能已变化。重新验证还是接受风险？"
    4. 按钮：[重新验证] [接受风险]
  - **AC**: Dashboard 显示失效 claim 的决策卡片
  - **前置依赖**: CLAIM-TASK-002

- [x] **Task ID**: CLAIM-TASK-005
  - **Action**: MODIFY
  - **Target File**: `tests/test_claim_evidence_analyzer.py`
  - **Instruction**: 新增测试覆盖：
    1. 文件 hash 变化 → claim 标记为 needs_reverification
    2. 文件 hash 不变 → claim 保持 covered
    3. 文件被删除 → claim 标记为 blocked
    4. 无历史指纹 → 跳过检查
    5. fingerprint 文件不存在 → 跳过检查
  - **AC**: 5 个新测试全部通过
  - **前置依赖**: CLAIM-TASK-002

- [x] **Task ID**: CLAIM-TASK-006
  - **Action**: MODIFY
  - **Target File**: `.vibetracing/claim_fingerprints.json`（新增）
  - **Instruction**: 首次运行时，为所有现有 claims 生成初始指纹快照。作为迁移任务。
  - **AC**: 所有 claims 都有对应的指纹记录
  - **前置依赖**: CLAIM-TASK-003

---

## 五、预期效果

实施后：
- 当 `cli.py` 被修改时，所有引用 `cli.py` 的 claims 自动标记为 `needs_reverification`
- Dashboard 显示失效 claim 的决策卡片，人类可以决定"重新验证"或"接受风险"
- Agent 行动清单中，失效 claim 生成 MEDIUM 优先级行动项
- 旧 claims 不再产生大量 "violated" 风险——取而代之的是精确的 "needs_reverification" 标记
- 门禁不再因旧 claims 引用被修改文件而 BLOCKED
