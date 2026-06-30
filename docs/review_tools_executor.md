# 模块审核报告：infra/tools/executor.py

## 审核概览
- **审核日期**：2026-06-30
- **审核范围**：
  - `infra/tools/executor.py`（587 行）— 工具执行引擎
  - `infra/tools/parsers.py`（442 行）— 工具输出解析器（被 executor 调用）
  - `infra/tools/resolver.py`（47 行）— 工具可用性检测（被 executor 调用）
- **架构约束参考**：MOD-VT-012（tool_execution_engine）

## 三大原则评估

| 原则 | 评估 |
|------|------|
| 第一性原则 | 明确服务于"VT 自主执行白名单中验证工具"这个核心目的。`execute_from_claims` 作为唯一入口，从 claims 收集路径 → 执行工具 → 解析输出 → 返回结构化结果，链路完整。 |
| 剃刀原则 | 大部分代码简洁清晰，但有两处可简化：2 个未使用的 import、`_measure_source_coverage` 中的重复逻辑 |
| 零历史债务 | 未发现历史架构残留 |

## 逐维度审核结果

### 维度 1：明确范围 ● **pass**

**文件职责**：

| 文件 | 行数 | 职责 |
|------|:----:|------|
| `executor.py` | 587 | 工具执行引擎，编排 precheck → 路径收集 → 执行 → 解析 → 统计 |
| `parsers.py` | 442 | 5 个工具输出解析器（pytest、ruff、mypy、bandit、coverage） |
| `resolver.py` | 47 | 工具可用性检测 + `python3 -m` 回退 |
| `__init__.py` | 10 | 包导出 |

依赖清晰：
- `executor.py` → 调用 `parsers.py` 的解析函数 + `resolver.py` 的 ToolResolver
- `parsers.py` → 纯函数，无 infra 内部依赖
- `resolver.py` → 纯函数，仅依赖标准库 + sys

**架构约束**：MOD-VT-012 允许调用 MOD-VT-005（evidence_builder）。`executor.py` 从 `domain.evidence.candidate` 导入 `ToolEvidenceCandidate` 和 `ToolExecutionResult` — 这与 evidence_builder 同属 `domain/evidence/` 包，在 allowed 范围内。

---

### 维度 2：中文注释维护 ● **warn**

**情况**：模块 docstring 为英文，所有函数 docstring 为英文。关键业务逻辑无行内中文注释。

虽然代码本身可读性尚可（英文注释质量不错），但违反了 VT 项目"非开发背景业务方能理解"的要求。

**需要补充中文注释的位置**：

| 位置 | 问题 |
|------|------|
| 模块级 docstring（第 1-9 行） | 英文，需补充中文说明 |
| `ToolExecutionEngine` 类 docstring（第 54-60 行） | 英文 |
| `_build_command`（第 100-125 行） | 英文 |
| `_run_subprocess`（第 131-188 行） | 英文 |
| `execute_tool`（第 239-288 行） | 英文 |
| `execute_from_claims`（第 407-530 行） | 英文—核心入口方法，业务方最需要理解的部分 |
| `_measure_source_coverage`（第 290-405 行） | 英文 |

---

### 维度 3：历史架构残留 ● **pass**

**未发现遗留问题**。
- 无 `deprecated`、`FIXME`、`HACK`、`TEMP` 等标记
- 无已删除模块的 import
- 无旧数据结构引用（如 `current.json`、`EVIDENCE-VT-`）
- 代码与 `refactoring_design.md` 当前架构一致

---

### 维度 4：过度设计 ● **warn**

**发现 1：两个未使用的 import（✅ 立即修复，零成本）**

```python
# 第 18 行 — 从未使用
from dataclasses import dataclass, field

# 第 29 行 — 导入但在 executor.py 中从未直接调用
parse_pytest_json,
```

- `dataclass` 和 `field` 在 executor.py 中无任何引用
- `parse_pytest_json` 由 `parsers.py` 内部的 `parse_pytest_output` 调用，但 executor.py 自身不直接使用它

**发现 2：`_measure_source_coverage` 的 evidence_index 路径和 file 路径存在重复**

第 316-350 行（evidence_index 路径）与第 352-405 行（file 路径）做的是几乎相同的事情：遍历文件、检查 percent、创建 `ToolEvidenceCandidate`。差异仅在数据源（dict vs JSON 文件）和对应的安全守卫（`isinstance` checks vs file I/O 错误处理）。

建议提取一个 `_build_coverage_candidates(files: dict, pass_threshold: float) -> list` 共享方法，消除两段重复的"遍历 files → 创建 candidates"逻辑。

---

### 维度 5：逻辑优化空间 ● **warn**

**发现 1：`execute_tool` 的 `{output_path}` 检测可简化**

第 254-258 行：
```python
effective_output = ""
if "{output_path}" in template:
    tmp_dir = self.project_root / ".vibetracing" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    effective_output = str(tmp_dir / f"vt_{tool_category}_{uuid.uuid4().hex}.json")
```

如果模板没有 `{output_path}`，`_build_command` 会将其替换为空字符串。这个 if 块其实可移动到 `_build_command` 内部，避免在 executor 层做模板字符串检测。

**发现 2：`_get_test_docstring` 方法（第 536-571 行）可能应移到 parsers.py**

这个方法使用 AST 解析 Python 文件提取 docstring，逻辑上属于"工具输出解析"范畴而非"工具执行"范畴。放在 executor.py 中是因为 `_parse_output` 的回调 `get_test_docstring` 来自 executor 实例。但可以用函数引用跨模块传递。

**不是问题**：`execute_from_claims` 方法 82 行，虽然超 50 行，但其中清晰的注释段落分隔了 5 个逻辑阶段（precheck → path collection → execution → coverage → stats），拆分反而会降低可读性。

---

### 维度 6：异常捕获与日志规范 ● **pass**

执行 vt-error-logging-audit 检查结果：

| # | 检查项 | 适用 | 判定 | 说明 |
|---|--------|:----:|:----:|------|
| 1 | Logger 获取模式 | ⚡ 视需要 | ✅ | 使用 `OperationalLogger.get()`，符合内部模块规范 |
| 4 | 事件命名规范 | ✅ 必须 | ✅ | 事件名清晰：`subprocess_exec`、`tool_execution_start`、`tool_execution_complete`、`tool_execution_error`、`tool_precheck_failed` 等 |
| 6 | 输出通道分层 | N/A | ✅ | 零 `print(stderr)` 调用，所有信息通过 logger 或返回值传递 |

**亮点**：
- `_run_subprocess` 第 155-168 行的日志守卫 `except Exception: pass  # Never block on logging` — 符合项目规范 ✅
- `execute_from_claims` 不直接 print，返回结构化 `ToolExecutionResult` 让调用方（CLI 层 pipeline.py）决定如何展示 — 符合分层规范 ✅
- 异常分类精准：`TimeoutExpired` / `FileNotFoundError` / `PermissionError` / `OSError` 分别处理，每种有专属 error_type

**建议**：`_measure_source_coverage` 第 366 行 `OperationalLogger.get().debug("tool_output_parse_failed", ...)` 在解析失败时只打了 DEBUG 级别的日志。如果 coverage baseline 文件频繁解析失败，适合提升到 WARNING 级别。但不是阻塞项。

---

### 维度 7：根因分析 ● **warn**

**发现 `_measure_source_coverage` 是"追加补丁"的典型案例**

查看方法名和文档——"Measure per-source-file coverage from a pre-built baseline"。该方法最初只有"从文件读取"（第 352-405 行）。后来增加了"从 evidence_index 读取"的路径（第 316-350 行）。

补丁本质：
- **症状**：调用方 `execute_from_claims` 没有预先准备 evidence_index，所以需要第二个数据源
- **补丁**：加了一条 else-if 分支，读文件
- **根因**：`execute_from_claims` 仅在第 503-505 行简单调用 `self._measure_source_coverage(baseline_path=self.coverage_baseline_path)`，不传 `evidence_index`。所以第一条路径永远是 dead code（evidence_index 始终为 None）

```python
# 第 503-505 行
all_candidates.extend(self._measure_source_coverage(
    baseline_path=self.coverage_baseline_path,
))
# evidence_index 参数未被传入，使用了默认值 None
```

这导致 `_measure_source_coverage` 中第 316 行的判断 `if evidence_index and ...` **永远不成立**，该分支是死代码。唯一的实际路径是 fallback 的文件读取。

**根因修复建议**：
1. 确认两个路径是否都需要（如果 evidence_index 路径永远不走，删除第 316-350 行死代码）
2. 如果未来需要 evidence_index 路径，修改 `execute_from_claims` 的调用签名传入 evidence_index

---

## 汇总

| 维度 | 判定 |
|------|:----:|
| 1. 明确范围 | ✅ pass |
| 2. 中文注释 | ⚠️ warn |
| 3. 历史残留 | ✅ pass |
| 4. 过度设计 | ⚠️ warn |
| 5. 逻辑优化 | ⚠️ warn |
| 6. 异常日志 | ✅ pass |
| 7. 根因分析 | ⚠️ warn |

---

## 优先修复清单

| 优先级 | 维度 | 问题描述 | 建议修复方式 | 影响范围 |
|:------:|:----:|----------|-------------|----------|
| **P0** | 过度设计 | `from dataclasses import dataclass, field` 未使用 | 删除第 18 行 import | `executor.py` |
| **P0** | 过度设计 | `parse_pytest_json` 导入但未直接使用 | 从 import 列表删除 | `executor.py` |
| **P1** | 根因分析 | `_measure_source_coverage` 第 316-350 行 evidence_index 路径为死代码（调用方永不为该参数传值） | 删除死代码分支，简化方法 | `executor.py` |
| **P1** | 逻辑优化 | `_measure_source_coverage` 两段代码做相同的事情 | 提取共享方法 `_build_coverage_candidates(files, threshold)` | `executor.py` |
| **P2** | 中文注释 | 模块无中文注释 | 补充模块/类/核心函数的中文 docstring | `executor.py` |
| **P2** | 逻辑优化 | `_get_test_docstring` 放在 executor.py 中，逻辑上属于解析范畴 | 考虑移到 `parsers.py` | `executor.py` + `parsers.py` |
