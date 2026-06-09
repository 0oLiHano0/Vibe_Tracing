# 工具执行关联问题调研报告

**日期**: 2026-06-09
**状态**: 待修复
**关联**: AC-VT-009-* 覆盖率缺口反复出现

---

## 一、问题现象

evo round d 中为 AC-VT-009-03/04/08/09/10/11/13/14/15/16/17 添加了 26 个测试（`test_ac_vt_009_coverage.py`），`vt analyze` 报告 0 个 AC 缺口。但在下一次提交中，这些缺口重新出现。

---

## 二、根因定位

### 核心问题：测试证据是无状态的

VT 的 AC 覆盖率检测是两阶段流水线：

**阶段 A：证据生成**（`_execute_tools()` → `tool_evidence_adapter.py`）
- 从 claims 的 `test_refs` 收集测试文件路径
- **只对 staged 文件运行 pytest**
- 解析 pytest 输出，从测试函数 docstring 中提取 `covers: AC-VT-*` 标记
- 生成 `ToolEvidenceCandidate`（source_type="test"）

**阶段 B：缺口分析**（`ac_test_analyzer.py`）
- 过滤 `source_type == "test"` AND `status == "covered"` 的证据
- 对每个 AC，检查是否有 passing test evidence 的 `covers` 列表包含该 AC
- 如果没有且 requirement 是 MUST 级，生成 gap

### 关键代码路径

```
cli.py:935-951 — staged 文件过滤
  git diff --cached --name-only → staged_files
  test_paths = [p for p in test_paths if p in staged_files]
  → 非 staged 的测试文件被排除
```

```
evidence_index_builder.py:43 — 每次运行重建索引
  EvidenceIndexBuilder.build() 从零构建
  → 上一次运行的测试证据不保留
```

```
ac_test_analyzer.py:40-45 — 只看 source_type="test"
  claim 级证据 (source_type="claim") 不满足 AC 覆盖
  → claim 的 test_refs 只决定运行哪些文件，不提供覆盖证据
```

### 因果链

```
commit N: test_ac_vt_009_coverage.py 是新文件 → staged → pytest 运行
  → docstring 提取 covers: AC-VT-009-* → 证据生成 → AC 覆盖 ✓

commit N+1: test_ac_vt_009_coverage.py 未修改 → 不在 staged_files
  → pytest 不运行 → 无测试证据 → AC 覆盖 ✗ → 重新出现 gap
```

**这是设计问题，不是偶发 bug。每次提交，如果测试文件不在 staged 中，其覆盖证据就丢失。**

---

## 三、额外发现

AC-VT-009-07（"零提示词 AI 引导与脚手架机制"）**从未被任何测试覆盖**。`test_ac_vt_009_coverage.py` 覆盖了 03/04/08/09/10/11/13/14/15/16/17，但遗漏了 07。这个 AC 会一直作为 gap 出现。

---

## 四、解决方案

### 方案 A：持久化测试证据（推荐）

**思路**：`evidence_index.json` 不应每次从零重建。如果测试文件未被修改，应保留上一次运行的证据。

**实现**：
1. `EvidenceIndexBuilder.build()` 加载已有的 `output/evidence_index.json`
2. 对于未 staged 的测试文件，保留其已有的 evidence 条目
3. 对于 staged 的测试文件，重新运行 pytest 并更新证据

**优点**：最小改动，不改变工具执行逻辑
**缺点**：需要管理证据的新鲜度（文件修改后旧证据需要清除）

### 方案 B：claim test_refs 直接提供覆盖证据

**思路**：如果 claim 的 `test_refs` 包含 `test_ac_vt_009_coverage.py`，且该文件存在且有 `covers: AC-VT-009-*` docstring，直接视为有覆盖（不依赖 pytest 运行）。

**实现**：
1. `AcTestAnalyzer.analyze()` 除了检查 `source_type="test"` 证据外，还扫描 claims 的 `test_refs`
2. 对每个 test_ref，用 AST 解析 docstring 提取 `covers` 标记
3. 将这些也视为覆盖证据

**优点**：不依赖 pytest 运行，claim 就是覆盖声明
**缺点**：需要 AST 解析所有 test_refs 文件（性能开销）

### 方案 C：扩大 pytest 运行范围

**思路**：pre-commit 模式下，不仅运行 staged 测试文件，还运行所有 claims 的 `test_refs`。

**实现**：修改 `cli.py:935-951`，将 staged 过滤改为：
```python
# staged 代码文件：只运行 staged 的
source_paths = [p for p in source_paths if p in staged_files]
# 测试文件：运行所有 claim test_refs（不限于 staged）
# test_paths 保持不变，不做 staged 过滤
```

**优点**：简单直接
**缺点**：每次提交运行所有测试，可能很慢

### 方案对比

| 方案 | 可靠性 | 性能 | 复杂度 |
|---|---|---|---|
| A: 持久化证据 | 高 | 高（只运行 staged） | 中 |
| B: claim test_refs 覆盖 | 高 | 中（AST 解析） | 低 |
| C: 扩大运行范围 | 高 | 低（运行所有测试） | 低 |

**推荐方案 A**：最符合 VT 的设计哲学——证据是持久化产物，不是临时输出。

---

## 五、原子化任务

- [ ] **Task ID**: FIX-TASK-006
  - **Action**: MODIFY
  - **Target File**: `src/vibe_tracing/evidence_index_builder.py`
  - **Instruction**: `build()` 方法加载已有的 `output/evidence_index.json`，对于未 staged 的测试文件保留其已有证据条目，对于 staged 的测试文件重新生成证据。
  - **AC**: 未 staged 的测试文件的覆盖证据在下一次运行中保留

- [ ] **Task ID**: FIX-TASK-007
  - **Action**: MODIFY
  - **Target File**: `tests/test_ac_vt_009_coverage.py`
  - **Instruction**: 为 AC-VT-009-07 添加测试覆盖（当前遗漏）。
  - **AC**: `vt analyze` 不再报告 AC-VT-009-07 缺口
