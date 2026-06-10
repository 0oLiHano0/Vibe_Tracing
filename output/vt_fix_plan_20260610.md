# VT 问题修复方案

## 问题 1：工具执行的文件筛选逻辑过度工程

### 现象

pre-commit hook 对 83 个 staged 文件执行工具验证，其中包含 `.md`、`.html`、`.toml`、`.json` 文件。mypy 对这些文件报 "mypy usage error (exit code 2)"。

### 根因分析

当前的文件筛选逻辑有 4 层，每层都在试图解决同一个问题："哪些文件该跑哪些工具"。但信息是分散的、重复的、不一致的。

**信息源**：`language_tool_matrix`（architecture_constraints.json）已经定义了完整的映射：

```json
"python": {
  "extensions": [".py"],
  "test": { "tool": "pytest", ... },
  "lint": { "tool": "ruff", ... },
  "type_check": { "tool": "mypy", ... },
  "security": { "tool": "bandit", ... }
}
```

一个字典就包含了"哪些扩展名该跑哪些工具"的完整信息。

**当前的 4 层冗余**：

| 层 | 位置 | 职责 | 问题 |
|---|---|---|---|
| 1 | `_get_code_extensions`（cli.py line 826） | 从**所有语言**收集所有扩展名 | 收集了 `.md`、`.toml` 等非目标语言的扩展名 |
| 2 | `_execute_tools`（cli.py line 927） | 用 Layer 1 的扩展名过滤 claim refs | `.md` 通过过滤（因为 `.md` 在集合中） |
| 3 | `TOOL_FILE_TYPE_MAP`（adapter line 89） | 定义 tool → extensions | 只在 flat-list 分支生效，dict 分支不用 |
| 4 | `PATH_TYPE_TOOL_MAP`（adapter line 102） | 定义 path_type → tools | 不检查扩展名，所有 source 文件都传入 mypy |

**同一个信息（"mypy 只跑 .py 文件"）被表达了 3 次**（Layer 1、Layer 3、language_tool_matrix），而且 3 次之间不一致。

### 修复方案：从信息源驱动，删除冗余层

**核心原则**：`language_tool_matrix[config_language]` 是唯一的信息源。不需要额外的扩展名收集、工具映射或路径类型映射。

**Step 1：删除 `_get_code_extensions` 函数**（cli.py line 826-840）

这个函数从所有语言收集扩展名，是问题的根源。删除它。

**Step 2：简化 `_execute_tools` 的文件筛选**（cli.py line 908-934）

改为从 `language_tool_matrix[config_language]` 直接获取扩展名：

```python
# 旧代码
code_extensions = _get_code_extensions(ltm)

# 新代码
lang_config = ltm.get(config_language, {})
code_extensions = set(lang_config.get("extensions", [".py"]))
```

这确保只有 `.py` 文件进入 `source_paths` 和 `test_paths`。

**Step 3：简化 `execute_all`**（tool_evidence_adapter.py line 926-972）

删除 `TOOL_FILE_TYPE_MAP` 和 `PATH_TYPE_TOOL_MAP` 两个硬编码映射。改为从 `language_tool_matrix[language]` 动态获取：

```python
def execute_all(self, paths, evidence_index=None):
    lang_config = self.language_tool_matrix.get(self.language, {})
    lang_extensions = set(lang_config.get("extensions", []))

    results = []
    for path in paths:
        # 只处理目标语言的文件
        if Path(path).suffix not in lang_extensions:
            continue

        # 根据路径判断是测试文件还是源文件
        is_test = "test" in str(Path(path).parent) or path.startswith("tests/")

        # 从 language_tool_matrix 获取该语言的工具
        for tool_category in self.validation_tools:
            tool_config = lang_config.get(tool_category)
            if not tool_config:
                continue

            # 测试工具只跑测试文件，其他工具只跑源文件
            if tool_category == "test" and not is_test:
                continue
            if tool_category != "test" and is_test:
                continue

            # 执行工具
            ...
```

**关键变化**：
- 扩展名过滤：从 `language_tool_matrix[language].extensions` 获取，不是从所有语言收集
- 工具选择：从 `language_tool_matrix[language]` 获取，不是从硬编码 MAP 获取
- 测试/源文件区分：基于路径模式，不是基于 separate dict 分支

**Step 4：删除冗余的 MAP 定义**（tool_evidence_adapter.py line 89-105）

删除 `TOOL_FILE_TYPE_MAP` 和 `PATH_TYPE_TOOL_MAP`。这些信息已经在 `language_tool_matrix` 中。

### 修改文件

| 文件 | 修改 |
|---|---|
| `cli.py` | 删除 `_get_code_extensions` 函数；简化 `_execute_tools` 的扩展名获取 |
| `tool_evidence_adapter.py` | 重写 `execute_all`；删除 `TOOL_FILE_TYPE_MAP` 和 `PATH_TYPE_TOOL_MAP` |

### 风险

- `execute_all` 的调用方可能依赖 dict 格式（`{"test": [...], "source": [...]}`）→ 需要检查所有调用方
- flat-list 分支的逻辑需要保留或迁移 → 需要确认是否有调用方传入 flat list
- 测试文件的判断逻辑（`is_test`）需要与当前的 `test_paths` 生成逻辑一致

---

## 问题 2：claim_credibility 检查是旧设计遗留，不应存在

### 现象

35 个 claim 都产生 "Claim XXXX 声明任务完成但无 VT 执行的工具验证证据" 风险，severity 为 `must`，阻断门禁。

### 根因分析

**旧设计中 claim_credibility 的作用**：

```
Agent 写 Claim → Claim 声明 "我做了这些事"
  → VT 检查 Claim 的 evidence_refs 是否指向有效 evidence
  → 没有证据 → low_confidence → 风险 → 门禁阻断
```

这是"Agent 不能自证完成"原则的实现。Claim 是声明，Evidence 是验证。Gate 检查声明有没有被验证。

**新设计中这个逻辑已无意义**：

新设计的核心转变是 Claim 不再参与门禁判定。Gate 只看工具结果。验证链变为：

```
Agent 写 Claim（指针：test_refs）
  → VT 用 test_refs 跑 pytest（独立验证）
  → 结果写入 evidence_index
  → Gate 检查 evidence_index（工具结果）
```

VT 已经通过跑 pytest 获取了独立证据。不需要再检查"Claim 是否有 evidence_refs"。evidence 是 VT 自己生成的，不是 Agent 声明的。

**claim_credibility 检查在新设计中是多余的**。它检查的是"Claim 的 evidence_refs 是否指向有效的 evidence"，但新设计中：
- Claim 没有 evidence_refs（已从 Schema 删除）
- Evidence 由 VT 自动生成（不依赖 Claim 声明）
- Gate 直接检查 evidence_index（不经过 Claim）

**当前的三层阻断链**：

1. `claim_credibility.py`：Claim 无 evidence_refs → low_confidence（旧逻辑，不应触发）
2. `risk_advisor.py`：low_confidence → must severity 风险（旧逻辑，不应触发）
3. `merge_gate_engine.py`：must severity → 阻断（通用逻辑，正确但被错误输入触发）

问题不在 Gate 层（Layer 3），而在风险生成层（Layer 1 + 2）。修补 severity 或跳过条件是在 Gate 层打补丁，不是从源头解决。

### 修复方案：删除 claim_credibility 检查链

不是修补条件或 severity，而是**删除整个 claim_credibility 检查链**：

**修改文件**：`src/vibe_tracing/claim_credibility.py`

删除或清空 `assess_claim_credibility` 函数。在新设计中，Claim 的可信度由 VT 的工具执行结果决定（pytest 通过 = 可信），不由 Claim 的 evidence_refs 决定。

```python
def assess_claim_credibility(claim, evidence_index):
    """新设计：Claim 可信度由工具执行结果决定，不由 evidence_refs 决定。"""
    return {"credibility": "not_applicable"}
```

**修改文件**：`src/vibe_tracing/risk_advisor.py`

删除对 `claim_credibility` 风险的生成逻辑（line 222-240）。新设计中不存在"Claim 可信度风险"这个概念——VT 自己跑测试，结果就是事实。

**修改文件**：`src/vibe_tracing/cli.py`

如果 cli.py 中有调用 `assess_claim_credibility` 的地方，删除或跳过。

### 为什么这是根因修复

| 修补方案 | 根因方案 |
|---|---|
| 跳过无 evidence_refs 的 claim | 删除 claim_credibility 检查 |
| severity 从 must 降为 should | 删除 claim_credibility 风险生成 |
| Gate 层过滤 claim_credibility 风险 | 从源头不产生这些风险 |

修补方案保留了旧机制但降低了严格度。根因方案删除了在新设计中不应存在的旧机制。

---

## 问题 3：claim_evidence_analyzer 的文件存在性检查是重复且有害的

### 现象

CLAIM-VT-066 的 `code_refs` 中包含 `.vibetracing/claim_fingerprints.json` 和 `.vibetracing/coverage_baseline.json`，两个文件已删除。产生 `non_existent_code_ref` 风险（severity: must），阻断门禁。

这个问题已经修过好几次了（从 claim 中删除引用、添加跳过逻辑），但每次修完数据后，新的 claim 或其他 claim 又会引用被删除的文件，问题反复出现。

### 根因分析

**文件存在性检查存在于 3 个位置**：

| 位置 | 触发时机 | 检查范围 | 生成风险 |
|---|---|---|---|
| `claim_evidence_analyzer.py` line 491-514 | 每次 `vt analyze` | **所有** claim 的 code_refs + test_refs | `non_existent_code_ref`（must） |
| `cli.py` line 2482-2596 | `vt doctor` | **所有** claim 的 code_refs + test_refs | health check 报告 |
| `claim_credibility.py` line 98 | 每次 `vt analyze` | claim 的 deliverable 路径 | credibility 降级 |

**问题的根源**：`claim_evidence_analyzer.py` 对**所有** claim 检查文件存在性，不只是当前 staged 的 claim。所以：

1. 文件被删除（如 `claim_fingerprints.json`）
2. 历史 claim 仍然引用它 → 产生风险 → 阻断门禁
3. 我们从 claim 中删除引用
4. 但其他 claim 或新 claim 又引用了被删除的文件
5. 循环往复

**我们一直在修数据（从 claim 中删除引用），但检查逻辑会持续对所有 claim 产生风险。** 只要 claim 中有任何一个引用了不存在的文件，就会阻断门禁。

**与新设计的冲突**：新设计中已经有两个独立的文件存在性验证机制：

| 新设计机制 | 检查什么 | 何时触发 |
|---|---|---|
| Gate `check_claim_exists` | staged 文件是否被 claim 覆盖 | 每次 commit |
| VT `_run_claim_tests` | test_refs 是否可运行（不存在 → file_not_found） | 每次 analyze |

这两个机制只检查**当前相关的文件**，不会因为历史 claim 引用了被删除文件而阻断。

### 修复方案：从 claim_evidence_analyzer 移除文件存在性检查

**修改文件**：`src/vibe_tracing/traceability/claim_evidence_analyzer.py`

删除 line 491-514 的文件存在性检查循环。这个检查在新设计中：
- 与 Gate `check_claim_exists` 重复（都检查 code_refs 文件存在性）
- 与 VT `_run_claim_tests` 重复（都检查 test_refs 文件存在性）
- 检查范围过大（所有 claim vs 只检查 staged）
- 导致历史 claim 引用被删除文件时反复阻断门禁

**修改文件**：`src/vibe_tracing/risk_advisor.py`

删除 `non_existent_code_ref` 和 `non_existent_test_ref` 风险类型的处理逻辑（line 79-80），因为 `claim_evidence_analyzer` 不再生成这些风险。

**数据修复**：清理 `.vibetracing/claims/current.json` 中引用已删除文件的 claim（如有残留）。

### 为什么这是根因修复

| 修补方案（之前的做法） | 根因方案 |
|---|---|
| 从 claim 中删除已删除文件的引用 | 删除检查本身 |
| 添加 `.vibetracing/` 跳过逻辑 | Gate 和 VT 已有更精确的检查 |
| 每次都要修数据 | 不再因为历史 claim 产生风险 |

修补方案是"修数据让检查通过"。根因方案是"删除在新设计中重复且有害的检查"。

---

## 修改文件汇总

| 问题 | 文件 | 修改内容 |
|---|---|---|
| 1 | `cli.py` | 删除 `_get_code_extensions`；简化 `_execute_tools` 扩展名获取 |
| 1 | `tool_evidence_adapter.py` | 重写 `execute_all`；删除 `TOOL_FILE_TYPE_MAP` 和 `PATH_TYPE_TOOL_MAP` |
| 2 | `claim_credibility.py` | 清空 `assess_claim_credibility`，返回 not_applicable |
| 2 | `risk_advisor.py` line 222-240 | 删除 claim_credibility 风险生成逻辑 |
| 2 | `cli.py` | 删除对 `assess_claim_credibility` 的调用 |
| 3 | `claim_evidence_analyzer.py` line 491-514 | 删除文件存在性检查循环 |
| 3 | `risk_advisor.py` line 79-80 | 删除 non_existent_ref 风险处理 |
| 3 | `.vibetracing/claims/current.json` | 清理引用已删除文件的 claim |

## 执行顺序

1. 问题 3（删除重复检查 + 数据清理）→ 从源头消除反复出现的问题
2. 问题 2（删除 claim_credibility 检查链）→ 消除旧设计遗留
3. 问题 1（execute_all 重构）→ 需要仔细测试，影响面最大

## 验证方案

```bash
# 1. 全量测试通过
pytest tests/ -x -q

# 2. mypy 不再对非 Python 文件报错
git add docs/prd.md pyproject.toml CLAUDE.md
vt analyze --pre-commit 2>&1 | grep -c 'mypy usage error'
# expected: 0

# 3. claim_credibility 风险不再阻断门禁
vt analyze 2>&1 | grep '当前变更.*预存债务'
# expected: 当前变更的 HIGH 数量大幅减少

# 4. CLAIM-VT-066 不再产生 non_existent_code_ref 风险
vt analyze 2>&1 | grep 'non-existent.*claim_fingerprints'
# expected: 0 匹配
```
