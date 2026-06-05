# Root Cause Analysis & Fix Plan for Empty JSON Files

您一针见血地指出了问题所在——这是一个**代码逻辑和架构设计上的根本缺陷**，绝不能简单地用“添加垃圾回收（GC）代码”来打补丁掩盖。通过回溯源头逻辑，我整理了导致此问题的两个核心根因，以及对应的根治修复方案。

## 核心根因分析 (Root Cause Analysis)

### 1. 文件生命周期管理倒置（生成大量空文件的直接根因）
在 `tool_evidence_adapter.py` 的 `execute_tool` 方法中，代码逻辑试图“替工具代劳”。它使用了 `tempfile.NamedTemporaryFile(..., delete=False)`。
**逻辑错误点**：`NamedTemporaryFile` 的本质是**立即在磁盘上创建/打开一个文件并占有句柄**，而不是仅仅生成一个“唯一的路径字符串”。
标准的 CLI 工具（如 `pytest`, `coverage json`, `mypy` 等）在生成报告时，都具有自行创建输出文件的能力。VT 在工具运行**前**强制在磁盘上实例化了一个空文件，一旦工具因为任何原因（失败、短路、未安装等）没有向该路径写入数据，这个凭空捏造的 0 字节文件就会永久驻留在磁盘上。

### 2. 命令流控制的逻辑谬误（导致工具短路不写入的根因）
在 `docs/architecture_constraints.json` 中定义的 `coverage` 默认命令存在严重的 Shell 逻辑缺陷：
`"coverage run -m pytest {test_path} && coverage json -o {output_path}"`
**逻辑错误点**：使用了逻辑与 `&&`（短路操作符）。
在代码门禁和测试的语境下，`pytest` 测试不通过（返回非 0 退出码）是极其正常的行为。但是，**测试失败并不等于我们不需要看测试覆盖率**。使用 `&&` 导致一旦测试失败，后半段的 `coverage json` 被强行阻断。工具完全没有机会去生成 JSON 报告，最终使得前一步被强行创建的空文件无内容可写。

### 3. 依赖监测缺失与静默失败（导致 AI Agent 不知如何修复的根因）
在现有的架构中，`ToolExecutionEngine` 依赖 `subprocess.run(..., shell=True)` 来执行工具。如果系统环境中尚未安装该工具（如 `mypy`, `bandit`），Shell 会返回错误码 `127`（Command not found）。
**逻辑错误点**：VT 将退出码 `127` 当作常规的“工具执行失败”，并在内部将其状态标记为 `BLOCKED`，随后静默地继续执行后续步骤，最终仅在长篇的报告中呈现门禁未通过。
**结果**：AI Coding Agent 看到的是复杂的执行失败日志和门禁被 Block 的结论，而缺乏明确的**行动指令 (Actionable Instructions)**，导致 Agent 不知道只需补充安装依赖即可修复问题。

---

## 修复方案 (Implementation Plan)

我们要从源头解决这两个逻辑错误，一劳永逸地消除“空文件堆积”且不引入冗余的清理代码，并在此基础上补齐**依赖监测与自动修复指引**。

### User Review Required
> [!IMPORTANT]
> 此方案包含：1. 剥离空文件的预创建逻辑；2. 修正 Coverage 的短路逻辑；3. 增加依赖准入拦截与 AI 修复指南。请确认以下方案是否符合您的设计期望。

### Proposed Changes

#### [MODIFY] [tool_evidence_adapter.py](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/tool_evidence_adapter.py)
**重构路径生成机制，彻底剥离预先创建文件的副作用。**
移除 `tempfile.NamedTemporaryFile` 这种预占用磁盘的 API。改为使用 `uuid` 仅生成一个绝对不冲突的“字符串路径”，把创建文件的权力交还给真正执行的工具。
如果工具失败，文件就根本不会诞生（源头阻断空文件的产生）。

```diff
-            tmp_file = tempfile.NamedTemporaryFile(
-                dir=str(tmp_dir), suffix=suffix, delete=False, prefix=f"vt_{tool_category}_"
-            )
-            effective_output = tmp_file.name
-            tmp_file.close()
+            import uuid
+            unique_id = uuid.uuid4().hex
+            effective_output = str(tmp_dir / f"vt_{tool_category}_{unique_id}{suffix}")
```

#### [MODIFY] [cli.py](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/cli.py)
**增加 Pre-flight 依赖检查与 AI Agent Repair Guide 输出。**
在 `run_analyze` 执行工具前，基于 `config.json` 中定义启用的 `validation_tools`，解析出对应的可执行二进制文件名称（如 `pytest`, `ruff`, `mypy`, `bandit`, `coverage`）。
利用 `shutil.which` 进行环境探测。如果发现缺失，直接输出针对 AI Agent 的结构化修复指南，并中断流程。

```python
# 示例逻辑：
missing_tools = [tool for tool in required_tools if not shutil.which(tool)]
if missing_tools:
    print(f"\n[AI Agent Repair Guide]")
    print(f"VT depends on tools that are currently missing in the environment: {missing_tools}")
    print(f"Action Required: Please install these dependencies (e.g., pip install {' '.join(missing_tools)}) before running 'vt analyze' again.")
    return 1
```

#### [MODIFY] [architecture_constraints.json](file:///Users/lihan/Project/Vibe_Tracing/docs/architecture_constraints.json)
**修正 coverage 的 Shell 执行逻辑，剥离短路绑定。**
将 `&&` 替换为 `;`（顺序执行）。确保即使 `coverage run` 因为测试用例报错而失败，`coverage json` 也一定会执行，并将成功运行的覆盖率数据写入 `{output_path}`，保证证据链不因测试失败而中断。

```diff
-        "default_command": "coverage run -m pytest {test_path} && coverage json -o {output_path}",
+        "default_command": "coverage run -m pytest {test_path} ; coverage json -o {output_path}",
```

## Verification Plan
1. 修改上述两处代码后，在存在失败测试的用例下运行 `vt analyze`。
2. 验证 `.vibetracing/tmp/` 目录下：
   - 不再有任何 0 字节的空 JSON 文件产生。
   - `coverage` 工具即使在测试失败的情况下，依然能正确生成覆盖率 JSON 报告文件。

---

## 实施计划 (Implementation Tasks)

> **设计原则**：三个根因修复互不耦合，可并行委派。每个任务自包含：修改什么、改到什么程度、如何验证。

### Phase-VT-FIX: 空文件根因消除

#### TASK-FIX-001: 重构路径生成机制 — 消除空文件源头

| 字段 | 值 |
|---|---|
| **目标文件** | `src/vibe_tracing/tool_evidence_adapter.py` |
| **修改范围** | `ToolExecutionEngine.execute_tool()` 方法，第 648-658 行 |
| **依赖** | 无，可独立执行 |

**改动内容**：
```diff
- tmp_file = tempfile.NamedTemporaryFile(
-     dir=str(tmp_dir), suffix=suffix, delete=False, prefix=f"vt_{tool_category}_"
- )
- effective_output = tmp_file.name
- tmp_file.close()
+ import uuid
+ unique_id = uuid.uuid4().hex
+ effective_output = str(tmp_dir / f"vt_{tool_category}_{unique_id}{suffix}")
```

**附加清理**：
- 移除文件顶部 `import tempfile`（若无其他引用）

**DoD**：
1. `effective_output` 是纯字符串路径，磁盘上不会预先产生文件
2. 工具成功执行时，文件由工具自身创建（如 `coverage json -o`、`bandit -f json -o`）
3. 工具失败时，磁盘上无任何残留空文件
4. 现有测试 `tests/test_tool_evidence_adapter.py` 全部通过

---

#### TASK-FIX-002: 修正 coverage 短路逻辑 — 解除测试失败对报告的阻断

| 字段 | 值 |
|---|---|
| **目标文件** | `docs/architecture_constraints.json` |
| **目标文件（模板）** | `src/vibe_tracing/templates/architecture_constraints.template.json` |
| **修改范围** | `language_tool_matrix.python.coverage.default_command` |
| **依赖** | 无，可独立执行 |

**改动内容**：
```diff
- "default_command": "coverage run -m pytest {test_path} && coverage json -o {output_path}"
+ "default_command": "coverage run -m pytest {test_path} ; coverage json -o {output_path}"
```

**两个文件都需同步修改**（constraints 和 template）。

**DoD**：
1. 即使 `pytest` 返回非零退出码，`coverage json` 依然执行
2. 测试失败场景下，覆盖率 JSON 报告正常生成并包含 `totals.percent_covered`

---

#### TASK-FIX-003: 增加 Pre-flight 依赖检查与 AI Agent 修复指南

| 字段 | 值 |
|---|---|
| **目标文件** | `src/vibe_tracing/cli.py` |
| **修改范围** | `run_analyze()` 函数，工具执行前插入检查逻辑（约第 517 行前） |
| **依赖** | 无，可独立执行 |

**改动内容**：

在 `run_analyze()` 中，进入工具执行分支前，新增依赖准入检查：

```python
import shutil

# 从 language_tool_matrix 解析需要的二进制工具名
required_binaries = set()
ltm = constraints_content.get("language_tool_matrix", {})
lang_tools = ltm.get(config_language, {})
for category in config_validation_tools:
    tool_cfg = lang_tools.get(category, {})
    tool_name = tool_cfg.get("tool")
    if tool_name:
        required_binaries.add(tool_name)

missing = sorted(t for t in required_binaries if not shutil.which(t))
if missing:
    print(f"\n[AI Agent Repair Guide]", file=sys.stderr)
    print(f"VT depends on tools that are missing: {', '.join(missing)}", file=sys.stderr)
    print(f"Action: pip install {' '.join(missing)}", file=sys.stderr)
    return 1
```

**DoD**：
1. 缺失工具时，流程中断并输出结构化修复指南（工具名 + pip install 命令）
2. 所有工具就绪时，流程正常继续，无额外输出
3. 行为可通过 `--dry-run` 或 mock `shutil.which` 测试验证

---

#### TASK-FIX-004: 端到端验证与空文件清理

| 字段 | 值 |
|---|---|
| **目标** | 验证三项修复的组合效果 |
| **依赖** | TASK-FIX-001, TASK-FIX-002, TASK-FIX-003 全部完成 |

**验证步骤**：
1. 清空 `.vibetracing/tmp/` 目录
2. 运行 `vt analyze`（在存在失败测试的场景下）
3. 确认：
   - tmp 目录下无 0 字节 JSON 文件
   - coverage 工具在测试失败时仍生成有效报告
   - 缺失工具时输出 AI Agent 修复指南
4. 运行现有测试套件确认无回归

---

### 任务依赖图

```
TASK-FIX-001 ──┐
               ├──→ TASK-FIX-004 (端到端验证)
TASK-FIX-002 ──┤
               │
TASK-FIX-003 ──┘
```

TASK-FIX-001/002/003 互不依赖，可并行委派。TASK-FIX-004 等待三者完成后执行。
