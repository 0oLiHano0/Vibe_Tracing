# infra/tools 包重构规划：消除 tools.py 编排层

**日期**：2026-06-29
**状态**：待规划（未进入任务清单）

## 问题定义

### 问题 1：三层编排过度设计

当前阶段 3 的调用链是 3 层：

```
pipeline.py (调度)
  └── cli/analyze/tools.py (编排)
        └── infra/tools/executor.py (执行)
```

`tools.py` 在重构 C/D 之后变成了一个约 90 行的薄代理层——读配置、预检、从 claims 收集路径、调用 executor、打印统计。其中 5 件事中有 4 件是直接转发给 executor 的能力，只有"从 claims 收集路径"是 tools.py 自己的逻辑。

pipeline.py 的职责是调度（"什么时候调谁"），不应包含具体业务逻辑。路径收集是工具执行的前置步骤，属于执行引擎内部。

### 问题 2：candidate.py 位置错误导致隐式依赖 + 类型不安全

当前 `ToolEvidenceCandidate` 定义在 `infra/tools/candidate.py`。`domain/evidence/builder.py` 消费它的字段，但通过 `List[Any]` + `getattr()` 鸭子类型访问，**没有显式 import**：

```python
# builder.py:30 — 当前实现
def merge(self, tool_evidence: List[Any]) -> EvidenceMergeResult:
    for ev in (tool_evidence or []):
        source_type = getattr(ev, "source_type", None)  # 鸭子类型
```

依赖方向违反是**隐式的**：builder.py 不知道 `ToolEvidenceCandidate` 的存在，但它的逻辑完全耦合于该 dataclass 的字段结构。如果 `ToolEvidenceCandidate` 新增必填字段或重命名字段，builder.py 会在运行时静默失败（getattr 返回 None），而非编译时报错。

`ToolEvidenceCandidate` 是证据的数据模型，属于 domain 层。infra 层（parsers、executor）生产它，domain 层（EvidenceBuilder）消费它。将它移到 `domain/evidence/` 后，builder.py 可以用精确类型注解 `List[ToolEvidenceCandidate]`，获得类型安全 + 依赖方向显式化。

## 设计目标

1. **修正 candidate.py 位置**：从 `infra/tools/` 移到 `domain/evidence/`，消除隐式依赖，获得类型安全
2. **消除 tools.py**：逻辑全部融入 executor，不是搬到 pipeline.py
3. **路径收集 + 预检 + 执行 + 统计一体化**：executor 接收 claims_list，内部完成全部流程
4. **pipeline.py 只做调度**：一行调用，按返回值决定输出

## 设计规范：executor 内聚，pipeline 纯调度

tools.py 有 4 处 `print(..., file=sys.stderr)` 给 AI Agent 看的修复指南。根源修复要求：**executor 内聚全部逻辑（含预检），pipeline.py 不重复任何 tools.py 的逻辑**。

### 返回值设计：`ToolExecutionResult`

`execute_from_claims()` 不返回裸 `List[ToolEvidenceCandidate]`（空列表丢失失败原因），返回结构化结果：

```python
@dataclass
class ToolExecutionResult:
    """工具执行结果，包含证据候选项和执行元数据。"""
    candidates: List[ToolEvidenceCandidate]
    skipped: bool = False          # True = 预检失败或无代码文件，未执行
    skip_reason: str = ""          # "precheck_failed" | "no_code_files" | "no_extensions"
    missing_tools: List[str] = field(default_factory=list)  # 预检失败时缺失的工具
```

定义位置：`domain/evidence/candidate.py`（与 `ToolEvidenceCandidate` 同包，同属证据数据模型）。

### 职责划分

| 职责 | 归属 | 理由 |
|------|------|------|
| 预检（工具是否可用） | executor | 预检失败 → `skipped=True`，不是调度决策 |
| 路径收集（claims → 文件路径） | executor | 工具执行的前置步骤 |
| 工具执行 | executor | 已有 |
| 统计 + 日志 | executor | 只用 vt_logger，不 print |
| Agent 修复指南 print | pipeline.py | CLI 层负责用户输出 |

pipeline.py 的调度逻辑：

```python
result = engine.execute_from_claims(ctx.claims_list, project_root)
tool_evidence = result.candidates

if result.skipped:
    if result.skip_reason == "precheck_failed":
        print(f"Missing tools: {', '.join(result.missing_tools)}", ...)
    else:
        print(f"Skipped: {result.skip_reason}", ...)
else:
    for c in tool_evidence:
        if c.error_code is not None:
            # 按 error_type print 修复指南
```

## 目标架构

```
pipeline.py (纯调度：一行调用 + 按返回值 print Agent 修复指南)
  └── infra/tools/executor.py (执行：预检 → 路径提取 → 执行 → 统计 → 日志)
        ├── resolver.py (工具可用性)
        └── parsers.py (输出解析)
```

依赖方向：
```
infra/tools/executor.py → 生产 ToolEvidenceCandidate
     ↓
domain/evidence/builder.py → 消费 ToolEvidenceCandidate
```

`ToolEvidenceCandidate` 定义在 `domain/evidence/`（证据数据模型），infra 层生产它，domain 层消费它。依赖方向 infra → domain。

## 变更步骤

### 步骤 0：修正 candidate.py 位置（前置）

**目的**：修正 domain → infra 的隐式依赖，获得类型安全。

**操作**：
1. 将 `src/vibe_tracing/infra/tools/candidate.py` 移动到 `src/vibe_tracing/domain/evidence/candidate.py`
2. 在同文件新增 `ToolExecutionResult` dataclass（见上方返回值设计）
3. 更新所有导入：
   - `infra/tools/executor.py`：`from vibe_tracing.infra.tools.candidate import ...` → `from vibe_tracing.domain.evidence.candidate import ...`
   - `infra/tools/parsers.py`：同上
   - `infra/tools/__init__.py`：移除 candidate 导出
   - `domain/evidence/__init__.py`：新增 candidate + ToolExecutionResult 导出
   - `cli/analyze/tools.py`：更新导入路径（在 tools.py 被删除前）
4. **根源修复 builder.py 的类型不安全**：
   - `List[Any]` → `List[ToolEvidenceCandidate]`
   - `getattr(ev, "source_type", None)` → `ev.source_type`
   - `getattr(ev, "tool_category", "")` → `ev.tool_category`
   - `getattr(ev, "status", "unknown")` → `ev.status`
   - `getattr(ev, "exit_code", 0)` → `ev.exit_code`
   - `getattr(ev, "command", "")` → `ev.command`
   - `getattr(ev, "details", {}) or {}` → `ev.details`
5. 依赖方向变为 infra → domain（正确）

### 步骤 1：executor.py 新增 `execute_from_claims()` 方法

**修改文件**：`src/vibe_tracing/infra/tools/executor.py`

在 `ToolExecutionEngine` 中新增 `execute_from_claims()` 方法，作为工具执行的**唯一入口**：

```python
def execute_from_claims(
    self,
    claims_list: List[Any],
    project_root: Path,
) -> ToolExecutionResult:
    """从 claims 提取路径、预检、执行工具、返回结构化结果。

    内聚全部逻辑：预检 → 路径收集 → 执行 → 统计 → 日志。
    只用 vt_logger，不 print。pipeline.py 按返回值决定输出。
    """
    # 1. 预检：检查工具可用性（当前 tools.py L36-54）
    #    失败 → vt_logger.warning + return ToolExecutionResult(skipped=True, ...)
    # 2. 从 claims 收集代码文件路径（当前 tools.py L66-87）
    #    无文件 → vt_logger.warning + return ToolExecutionResult(skipped=True, ...)
    # 3. vt_logger.info 记录执行开始
    # 4. 按 test/source 分类路径，直接调用 self.execute_tool() 逐个执行
    #    （不经过 execute_all()，避免路径重复过滤）
    # 5. 附加 coverage baseline 证据（当前 execute_all() 末尾的逻辑）
    # 6. vt_logger 记录统计
    # 7. return ToolExecutionResult(candidates=..., skipped=False)
```

**删除 `execute_all()`**：tools.py 删除后无外部调用方，`execute_from_claims()` 内部直接调用 `execute_tool()` 逐个执行（含路径分类逻辑），不再经过 `execute_all()` 的二次扩展名过滤。根源消除重复逻辑。

### 步骤 2：迁移全部日志事件到 executor.py

**修改文件**：`src/vibe_tracing/infra/tools/executor.py`

将 tools.py 中的全部 7 个日志事件迁移到 `execute_from_claims()`（仅 vt_logger，不 print）：

| 事件名 | 当前位置 | 迁移后位置 | 备注 |
|--------|----------|-----------|------|
| `tool_precheck_failed` | tools.py | `execute_from_claims()` | vt_logger.warning，返回 `ToolExecutionResult(skipped=True)` |
| `no_code_extensions` | tools.py | `execute_from_claims()` | vt_logger.warning，返回 `ToolExecutionResult(skipped=True)` |
| `no_code_files` | tools.py | `execute_from_claims()` | vt_logger.warning，返回 `ToolExecutionResult(skipped=True)` |
| `tool_execution_start` | tools.py | `execute_from_claims()` | vt_logger.info |
| `tool_files_skipped` | tools.py | `execute_from_claims()` | vt_logger.info |
| `tool_execution_error` | tools.py | `execute_from_claims()` | vt_logger.warning |
| `tool_execution_complete` | tools.py | `execute_from_claims()` | vt_logger.info |

executor.py 已有 `subprocess_exec` 和 `subprocess_output` 两个事件，保持不变。

pipeline.py **不再有任何日志事件**——所有日志由 executor 统一记录。pipeline.py 只负责 print Agent 修复指南（从 `ToolExecutionResult` 读取）。

### 步骤 3：pipeline.py 改为纯调度

**修改文件**：`src/vibe_tracing/cli/analyze/pipeline.py`

**当前**（pipeline.py:272）：

```python
tool_evidence = _execute_tools(ctx, project_root)
```

**改为**（纯调度，零业务逻辑）：

```python
from vibe_tracing.infra.tools.executor import ToolExecutionEngine

config_data = ctx.config
config_language = config_data["language"]
ltm = config_data["language_tool_matrix"]
config_validation_tools = [
    k for k, v in ltm.get(config_language, {}).items() if isinstance(v, dict)
]

engine = ToolExecutionEngine(
    language_tool_matrix=ltm,
    language=config_language,
    validation_tools=config_validation_tools,
    project_root=project_root,
    coverage_baseline_path=str(project_root / "coverage.json"),
)
result = engine.execute_from_claims(ctx.claims_list, project_root)
tool_evidence = result.candidates

# Agent 修复指南（CLI 层唯一职责：用户输出）
if result.skipped:
    if result.skip_reason == "precheck_failed":
        print("\n[AI Agent Repair Guide]", file=sys.stderr)
        print(f"VT depends on tools that are missing: {', '.join(result.missing_tools)}", file=sys.stderr)
        print(f"Action Required: pip install {' '.join(result.missing_tools)}", file=sys.stderr)
    elif result.skip_reason in ("no_code_files", "no_extensions"):
        print(f"Skipping tool execution: {result.skip_reason}.", file=sys.stderr)
else:
    for c in tool_evidence:
        if c.error_code is not None:
            details = c.details or {}
            error_type = details.get("error_type", "unknown")
            if error_type == "timeout":
                print(f"Error: {c.source_path} timed out after {details.get('timeout_seconds', '?')}s.", file=sys.stderr)
            elif error_type == "tool_not_found":
                print(f"Error: tool not found for {c.source_path}.", file=sys.stderr)
            else:
                print(f"Error: {c.source_path} failed (exit code {c.exit_code}). {c.stderr}", file=sys.stderr)
```

**与步骤 3 原方案的区别**：
- ❌ 原方案：pipeline.py 重复预检逻辑（config 提取 + ToolResolver.is_available + missing 检查）
- ✅ 新方案：pipeline.py 只做"构造 engine → 调用 → 按返回值 print"，预检在 executor 内部完成

### 步骤 4：删除 tools.py + execute_all()

**删除文件**：`src/vibe_tracing/cli/analyze/tools.py`

**删除方法**：`executor.py` 中的 `execute_all(typed_paths)` 方法（无外部调用方）

**删除引用**：`pipeline.py` 中的 `from vibe_tracing.cli.analyze.tools import _execute_tools`

### 步骤 5：更新测试

**实际影响**（已验证）：无测试直接测试 `_execute_tools` 或 `tools.py`。所有测试直接测 `ToolExecutionEngine`。

需更新的导入路径（candidate.py 移动后）：

| 文件 | 当前导入 | 更新为 |
|------|---------|--------|
| `tests/test_tool_execution.py` | `from vibe_tracing.infra.tools.executor import ToolEvidenceCandidate` | `from vibe_tracing.domain.evidence.candidate import ToolEvidenceCandidate` |
| `tests/test_evidence_builder.py` | `from vibe_tracing.infra.tools.executor import ToolEvidenceCandidate` | `from vibe_tracing.domain.evidence.candidate import ToolEvidenceCandidate` |
| `tests/test_integration_v3.py` | `from vibe_tracing.infra.tools.executor import ToolExecutionEngine` | 不变（executor 仍在 infra） |

**新增测试**：`execute_from_claims()` 的返回值 `ToolExecutionResult` 需要覆盖以下场景：
- 预检失败 → `skipped=True, skip_reason="precheck_failed"`
- 无代码文件 → `skipped=True, skip_reason="no_code_files"`
- 正常执行 → `skipped=False, candidates=[...]`
- 执行错误 → `candidates=[...error_code...]`

**删除测试**：如有测试 `execute_all()` 的用例，迁移为测试 `execute_from_claims()`。

### 步骤 6：更新文档

**修改文件**：

| 文件 | 变更 |
|------|------|
| `docs/spec_pipeline_stage_3.md` | 更新代码模块结构（§2），删除 tools.py 的描述，更新 executor.py 的描述 |
| `docs/refactoring_design.md` | 更新阶段 3 的调用链描述 |
| `docs/pipeline_stage-3-refactoring.md` | 新增重构 F 章节 |

## 影响范围

| 文件 | 影响 |
|------|------|
| `infra/tools/candidate.py` | **移动**到 `domain/evidence/candidate.py`（修正隐式依赖） |
| `infra/tools/executor.py` | 更新导入 + 新增 `execute_from_claims()` + **删除 `execute_all()`** + 日志事件 |
| `infra/tools/parsers.py` | 更新 candidate 导入 |
| `infra/tools/__init__.py` | 移除 candidate 导出，移除 `execute_all` 相关 |
| `domain/evidence/builder.py` | **根源修复类型不安全**：`List[Any]` → `List[ToolEvidenceCandidate]`，`getattr()` → 属性访问 |
| `domain/evidence/candidate.py` | 新增 `ToolExecutionResult` dataclass |
| `domain/evidence/__init__.py` | 新增 candidate + ToolExecutionResult 导出 |
| `cli/analyze/tools.py` | **删除** |
| `cli/analyze/pipeline.py` | 改为纯调度（构造 engine → 调用 → 按返回值 print） |
| `infra/tools/resolver.py` | **不变** |
| `tests/test_tool_execution.py` | 更新 `ToolEvidenceCandidate` 导入路径 + `execute_all` → `execute_from_claims` |
| `tests/test_evidence_builder.py` | 更新 `ToolEvidenceCandidate` 导入路径 |
| `tests/test_integration_v3.py` | `execute_all` 测试用例迁移为 `execute_from_claims` |

## 风险评估

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| executor.py 职责膨胀 | 低 | `execute_from_claims()` 是高层方法，内部委托给已有的私有方法（`execute_tool`、`_measure_source_coverage`、`_run_subprocess`） |
| `__init__.py` 导出变更影响外部导入 | 中 | `infra/tools/__init__.py` 移除 `ToolEvidenceCandidate` 导出，需更新 `test_tool_execution.py`、`test_evidence_builder.py` 的导入路径 |
| `execute_all()` 删除影响 | 中 | tools.py 删除后无外部调用方，但需确认 `test_integration_v3.py` 中的 `execute_all` 测试用例迁移为 `execute_from_claims` |
| 日志事件名变更 | 低 | 事件名不变，只是代码位置变了 |

## 前置条件

- 重构 C（工具列表数据源收敛）已完成 ✅
- 重构 D（删除暂存区过滤和死代码）已完成 ✅
- 重构 E（tools.py 补全日志）已完成 ✅

## 执行顺序

```
步骤 0：candidate.py 移动 + builder.py 类型修复 + 新增 ToolExecutionResult
  └── 步骤 1-2：executor.py 新增 execute_from_claims()（唯一入口）+ 删除 execute_all() + 日志迁移
        └── 步骤 3：pipeline.py 改为纯调度（构造 → 调用 → 按返回值 print）
              └── 步骤 4：删除 tools.py
                    └── 步骤 5-6：测试 + 文档
```

步骤 0 必须最先执行——它修正了架构违规（隐式依赖 + 类型不安全），后续步骤依赖正确的依赖方向和 `ToolExecutionResult` 返回值类型。

---

## 重构 G：execute_tool() YAGNI 清理

**状态**：已完成 ✅
**前置条件**：重构 F 已完成 ✅

### 问题定义

`execute_tool()` 的 8 个步骤中有 4 个是 YAGNI：

| # | 步骤 | 行数 | 判定 | 理由 |
|---|------|------|------|------|
| 1 | 白名单校验 | L293-313（20 行） | **死代码** | `execute_from_claims()` 只遍历 `self.validation_tools` 并显式传入 `tool_config=config`，永远不会触发 `tool_config is None` |
| 2 | 路径安全校验 | L319-334（15 行） | **双重防御** | 路径来自 claims 的 `code_refs`/`test_refs`（相对路径如 `src/module.py`），`project_root / relative_path` 永远在 project_root 内。`../` 已被 `infra/validation/checks.py` 格式校验拒绝 |
| 4 | 安全过滤 | L135-152（`_sanitize_path_value`） | **过度设计** | 输入链已可信（claims 格式校验 → 路径安全校验），shell 元字符过滤是对不可信输入的防御 |
| 8 | 标记类别 | 8 个 return 点各调一次 `_stamp_category()` | **冗余** | 每个解析器已知自己的类别，可在调用时一次性设置 |

额外发现：
- `execute_tool()` 的 `tool_config` 可选参数：生产代码 always 传入，测试代码依赖 `get_tool_config()` 回退——可简化签名
- `test_path`/`source_path`/`output_path` 三个可选参数：**零调用方使用**，纯向后兼容残留
- 错误处理有 3 个分支（timeout/not_found/generic）构造几乎相同的 candidate——可合并

### 设计目标

1. 删除 4 个 YAGNI 步骤（白名单校验、路径安全校验、安全过滤、标记类别）
2. 简化 `execute_tool()` 签名：去掉 4 个未使用的可选参数
3. 合并 3 个错误分支为 1 个
4. `python3 -m` 回退机制保留但精确化

### 目标代码

```python
def execute_tool(
    self,
    tool_category: str,
    path: str,
) -> List[ToolEvidenceCandidate]:
    """Execute a single tool for a given path and return evidence candidates.

    Pre-conditions (guaranteed by execute_from_claims):
        - tool_category is in self._tool_configs (whitelist)
        - path is a relative path inside project_root (claims validation)
    """
    tool_config = self._tool_configs[tool_category]

    # 1. 命令生成：从模板替换占位符
    template = tool_config.get("default_command", "")
    effective_test = path  # test_path 和 source_path 统一为 path
    effective_source = path

    # output_path：仅当模板含 {output_path} 时生成临时文件
    effective_output = ""
    if "{output_path}" in template:
        tmp_dir = self.project_root / ".vibetracing" / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        effective_output = str(tmp_dir / f"vt_{tool_category}_{uuid.uuid4().hex}.json")

    try:
        command = self._build_command(
            template,
            test_path=effective_test,
            source_path=effective_source,
            output_path=effective_output,
        )
    except ValueError as exc:
        return [self._blocked_candidate(path, tool_category, stderr=str(exc))]

    # 2. python3 -m 回退：工具不在 PATH 时，回退到 sys.executable -m
    command = ToolResolver.resolve_command(command)

    # 3. 执行子进程
    exit_code, stdout, stderr, exec_error = self._run_subprocess(command)

    if exec_error:
        details = {"error_type": exec_error}
        if exec_error == "timeout":
            details["timeout_seconds"] = self.timeout
        return [self._blocked_candidate(
            path, tool_category, command=command,
            exit_code=-1, stderr=stderr, details=details,
        )]

    # 4. 解析输出 + 标记类别
    output_format = tool_config.get("output_format", "")
    candidates = self._parse_output(
        output_format, stdout, stderr, exit_code, command, path,
    )
    for c in candidates:
        c.tool_category = tool_category
    return candidates
```

### python3 -m 回退的精确执行方式

`ToolResolver.resolve_command()` 的回退逻辑：

```
输入: "ruff check src/module.py --output-format=json"
处理:
  1. 按 ";" 分割（支持复合命令）
  2. 取每段第一个 token 作为工具名: "ruff"
  3. shutil.which("ruff") 检查是否在 PATH 中
  4. 不在 → 拼接: "{sys.executable} -m ruff check src/module.py --output-format=json"
     在   → 原样返回
输出: "/usr/bin/python3 -m ruff check src/module.py --output-format=json"
```

`sys.executable` 是当前运行 VT 的 Python 解释器路径（如 `/usr/bin/python3` 或 venv 中的 `python3`），确保使用正确的 Python 环境。

**保留此机制**：不同用户的 PATH 配置不同，`python3 -m` 回退是实际场景中的必要容错。但 `_build_command()` 中的 `_sanitize_path_value()` 可删除——路径已可信。

### _build_command() 简化

当前 `_build_command()` 内部调用 `_sanitize_path_value()` 做 shell 元字符过滤。简化后：

```python
def _build_command(self, template, test_path="", source_path="", output_path="") -> str:
    """Substitute placeholders in a command template.

    Only {test_path}, {source_path}, {output_path} are replaced.
    Path values are quoted via shlex.quote() for defense-in-depth.
    """
    cmd = template
    cmd = cmd.replace("{test_path}", shlex.quote(test_path))
    cmd = cmd.replace("{source_path}", shlex.quote(source_path))
    cmd = cmd.replace("{output_path}", shlex.quote(output_path))

    remaining = re.findall(r"\{[a-z_]+\}", cmd)
    if remaining:
        raise ValueError(f"Unresolved placeholders: {remaining}")
    return cmd
```

保留 `shlex.quote()`（一行代码，零成本防御），删除 `_sanitize_path_value()` 和 `_SAFE_PATH_PATTERN`。

### 辅助方法：_blocked_candidate + _parse_output

```python
def _blocked_candidate(
    self, path: str, tool_category: str, *,
    command: str = "", exit_code: int = -1,
    stderr: str = "", details: dict = None,
) -> ToolEvidenceCandidate:
    """Create a BLOCKED candidate with tool_category pre-set."""
    c = ToolEvidenceCandidate(
        source_type="tool", source_path=path, covers=[],
        status=CoverageStatus.BLOCKED.value,
        error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
        command=command, exit_code=exit_code,
        stderr=stderr, details=details or {},
    )
    c.tool_category = tool_category
    return c

def _parse_output(
    self, output_format: str,
    stdout: str, stderr: str, exit_code: int,
    command: str, path: str,
) -> List[ToolEvidenceCandidate]:
    """Dispatch to the appropriate parser based on output_format."""
    parsers = {
        "pytest_json": lambda: parse_pytest_output(
            stdout, stderr, exit_code, command, path,
            self.project_root, self.PYTEST_SKIP_EXIT_CODES,
            self._get_test_docstring, self._extract_covers_from_docstring,
        ),
        "ruff_json": lambda: parse_ruff_output(stdout, stderr, exit_code, command, path),
        "mypy_json": lambda: parse_mypy_output(stdout, stderr, exit_code, command, path, self.MYPY_SKIP_EXIT_CODES),
        "bandit_json": lambda: parse_bandit_output(stdout, stderr, exit_code, command, path, self.project_root),
        "coverage_json": lambda: parse_coverage_json_output(stdout, stderr, exit_code, command, path),
    }
    parser = parsers.get(output_format)
    if parser:
        return parser()
    return [self._blocked_candidate(path, "", stderr=f"Unsupported output format: {output_format}")]
```

### 删除项

| 删除目标 | 位置 | 理由 |
|---------|------|------|
| `_validate_path()` 方法 | executor.py | 路径已由 claims 格式校验保证安全 |
| `_sanitize_path_value()` 方法 | executor.py | 输入链已可信，`shlex.quote()` 足够 |
| `_SAFE_PATH_PATTERN` 常量 | executor.py | 随 `_sanitize_path_value` 一起删除 |
| `is_allowed_tool()` 方法 | executor.py | 零调用方（`execute_from_claims` 用 `self._tool_configs.get()` 代替） |
| `get_tool_config()` 方法 | executor.py | 零生产调用方（直接用 `self._tool_configs[category]`） |
| `_stamp_category()` 方法 | executor.py | 改为在 execute_tool 和 _parse_output 后一次性设置 |
| `execute_tool()` 的 4 个可选参数 | executor.py | `tool_config`/`test_path`/`source_path`/`output_path` 零调用方使用 |

### 变更步骤

| 步骤 | 操作 | 影响文件 |
|------|------|----------|
| G-1 | 新增 `_blocked_candidate()` 和 `_parse_output()` 辅助方法 | executor.py |
| G-2 | 简化 `_build_command()`：删除 `_sanitize_path_value` 调用，保留 `shlex.quote()` | executor.py |
| G-3 | 重写 `execute_tool()`：简化签名 + 删除 4 个 YAGNI 步骤 + 合并错误分支 | executor.py |
| G-4 | 删除 `_validate_path`、`_sanitize_path_value`、`_SAFE_PATH_PATTERN`、`is_allowed_tool`、`get_tool_config`、`_stamp_category` | executor.py |
| G-5 | 更新测试：移除对已删除方法的直接测试，补充 `_blocked_candidate` 和 `_parse_output` 测试 | tests/test_tool_execution.py |

### 风险评估

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| 删除路径安全校验后引入路径遍历 | 低 | claims 格式校验已拒绝 `../`，`_build_command` 保留 `shlex.quote()` |
| 删除白名单校验后传入非法类别 | 无 | `execute_from_claims` 已过滤，`self._tool_configs[category]` 会 KeyError（fail-fast） |
| 测试覆盖不足 | 中 | 步骤 G-5 更新测试，916 测试基线 |
