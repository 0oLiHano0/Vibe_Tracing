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

### 问题 2：candidate.py 位置错误导致 domain 依赖 infra

当前 `ToolEvidenceCandidate` 定义在 `infra/tools/candidate.py`，但被 `domain/evidence/builder.py` 导入：

```
infra/tools/executor.py → 生产 List[ToolEvidenceCandidate]
     ↓ （pipeline.py 局部变量传递）
domain/evidence/builder.py → 消费 ToolEvidenceCandidate 的字段
```

**domain 层导入了 infra 层的类**——这违反架构分层原则。domain 应该是纯业务逻辑层，不应该知道 infra 的存在。

`ToolEvidenceCandidate` 是证据的数据模型，属于 domain 层。infra 层（parsers、executor）生产它，domain 层（EvidenceBuilder）消费它。依赖方向应该是 infra → domain（正确），而不是 domain → infra（当前，错误）。

## 设计目标

1. **修正 candidate.py 位置**：从 `infra/tools/` 移到 `domain/evidence/`，修正依赖方向
2. **消除 tools.py**：调用链从 3 层变 2 层
3. **路径收集下沉到 executor**：executor 接收 claims_list，内部完成路径提取
4. **pipeline.py 只做调度**：一行调用，不含业务逻辑

## 目标架构

```
pipeline.py (调度)
  └── infra/tools/executor.py (执行：路径提取 → 预检 → 执行 → 统计 → 日志)
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

**目的**：修正 domain → infra 的错误依赖方向。

**操作**：
1. 将 `src/vibe_tracing/infra/tools/candidate.py` 移动到 `src/vibe_tracing/domain/evidence/candidate.py`
2. 更新所有导入：
   - `infra/tools/executor.py`：`from vibe_tracing.infra.tools.candidate import ...` → `from vibe_tracing.domain.evidence.candidate import ...`
   - `infra/tools/parsers.py`：同上
   - `infra/tools/__init__.py`：更新导出
   - `domain/evidence/builder.py`：更新导入路径
   - `cli/analyze/tools.py`：更新导入路径（在 tools.py 被删除前）
3. 依赖方向变为 infra → domain（正确）

### 步骤 1：executor.py 新增 `execute_from_claims()` 方法

**修改文件**：`src/vibe_tracing/infra/tools/executor.py`

在 `ToolExecutionEngine` 中新增一个高层方法，接收 claims_list 并完成全部流程：

```python
def execute_from_claims(
    self,
    claims_list: List[Any],
    project_root: Path,
) -> List[ToolEvidenceCandidate]:
    """从 claims 提取路径、预检、执行工具、返回证据候选项。"""
    # 1. 从 claims 收集代码文件路径（当前 tools.py L72-82 的逻辑）
    # 2. 预检（当前 tools.py L34-50 的逻辑，但用 self._tool_configs 驱动）
    # 3. 调用 self.execute_all()（已有）
    # 4. 统计和日志（当前 tools.py L103-140 的逻辑）
```

保留现有的 `execute_all(typed_paths)` 方法不变——它仍然是底层执行接口，供直接调用。

### 步骤 2：迁移日志事件到 executor.py

**修改文件**：`src/vibe_tracing/infra/tools/executor.py`

将 tools.py 中的 7 个日志事件迁移到 executor.py：

| 事件名 | 当前位置 | 迁移后位置 |
|--------|----------|-----------|
| `tool_precheck_failed` | tools.py | `execute_from_claims()` |
| `no_code_extensions` | tools.py | `execute_from_claims()` |
| `no_code_files` | tools.py | `execute_from_claims()` |
| `tool_execution_start` | tools.py | `execute_from_claims()` |
| `tool_files_skipped` | tools.py | `execute_from_claims()` |
| `tool_execution_error` | tools.py | `execute_from_claims()` |
| `tool_execution_complete` | tools.py | `execute_from_claims()` |

executor.py 已有 `subprocess_exec` 和 `subprocess_output` 两个事件，保持不变。

### 步骤 3：pipeline.py 改为直接调用 executor

**修改文件**：`src/vibe_tracing/cli/analyze/pipeline.py`

**当前**（pipeline.py:272）：

```python
tool_evidence = _execute_tools(ctx, project_root)
```

**改为**：

```python
engine = ToolExecutionEngine(
    language_tool_matrix=ctx.config["language_tool_matrix"],
    language=ctx.config["language"],
    validation_tools=list(ctx.config["language_tool_matrix"]
                          .get(ctx.config["language"], {}).keys()),
    project_root=project_root,
    coverage_baseline_path=str(project_root / "coverage.json"),
)
tool_evidence = engine.execute_from_claims(ctx.claims_list, project_root)
```

### 步骤 4：删除 tools.py

**删除文件**：`src/vibe_tracing/cli/analyze/tools.py`

**删除引用**：`pipeline.py` 中的 `from vibe_tracing.cli.analyze.tools import _execute_tools`

### 步骤 5：更新测试

**修改文件**：

| 文件 | 变更 |
|------|------|
| `tests/test_tool_execution.py` | 如有测试直接调用 `_execute_tools`，改为调用 `execute_from_claims` |
| `tests/test_cli_analyze.py` | 如有测试引用 tools.py，更新导入 |
| `tests/test_integration_v3.py` | 如有测试引用 tools.py，更新导入 |

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
| `infra/tools/candidate.py` | **移动**到 `domain/evidence/candidate.py`（修正依赖方向） |
| `infra/tools/executor.py` | 更新 candidate 导入 + 新增 `execute_from_claims()` + 日志事件 |
| `infra/tools/parsers.py` | 更新 candidate 导入 |
| `infra/tools/__init__.py` | 移除 candidate 导出 |
| `domain/evidence/builder.py` | 更新 candidate 导入路径 |
| `domain/evidence/__init__.py` | 新增 candidate 导出 |
| `cli/analyze/tools.py` | **删除** |
| `cli/analyze/pipeline.py` | 改为直接调用 executor |
| `infra/tools/resolver.py` | **不变** |

## 风险评估

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| executor.py 职责膨胀 | 低 | `execute_from_claims()` 是高层方法，内部委托给已有的私有方法 |
| 测试覆盖不足 | 中 | 重构前先补充 tools.py 的直接单元测试 |
| 日志事件名变更 | 低 | 事件名不变，只是代码位置变了 |

## 前置条件

- 重构 C（工具列表数据源收敛）已完成 ✅
- 重构 D（删除暂存区过滤和死代码）已完成 ✅
- 重构 E（tools.py 补全日志）已完成 ✅

## 执行顺序

```
步骤 0：candidate.py 移动（修正依赖方向）
  └── 步骤 1-2：executor.py 新增 execute_from_claims() + 日志迁移
        └── 步骤 3：pipeline.py 改为直接调用 executor
              └── 步骤 4：删除 tools.py
                    └── 步骤 5-6：测试 + 文档
```

步骤 0 必须最先执行——它修正了架构违规（domain 依赖 infra），后续步骤依赖正确的依赖方向。
