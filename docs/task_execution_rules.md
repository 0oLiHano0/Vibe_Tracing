# Vibe Tracing: 任务执行规则与编码准则 (Task Execution Rules and Coding Guidelines)

本文档概述了 AI 编码代理（AI Coding Agents）在 Vibe Tracing 治理框架下执行任务时必须遵守的严格准则和运行规则。

## 1. 任务生命周期与状态流转 (Task Lifecycle and Transitions)

所有开发任务均在 `docs/task_list.json` 中定义。AI 编码代理必须严格管理任务状态流转：

- **`todo`**：任务开始前的初始状态。
- **`in_progress`**：当 Agent 开始处理任务时设置。Agent 必须在跟踪日志以及 `task.md` 中将状态更新为 `[/]`（代表进行中）。
- **`done`**：**仅在**所有预期交付物均已产出、单元测试已编写并通过、且所有代码均已完成格式化/Linter 检查时设置。
- **`blocked`**：当存在依赖阻塞、缺失必要需求，或**因架构约束限制导致无法实现（实现壁垒）**时设置。

> [!IMPORTANT]
> **架构约束受阻交互规程 (Constraint Blocker Protocol)**:
> 当 AI 编码代理在开发中发现受限于某条架构约束而无法继续完成任务时，必须执行以下步骤：
> 1. 将任务的 `status` 变更为 `blocked`。
> 2. 在 `.vibetracing/agent_claims.json` 中申报一条状态为 `blocked` 的 Claim。
> 3. 在该 Claim 的 `notes` 字段中使用**中文**详细说明碰到的技术壁垒以及约束修改建议。
> 4. VT 质量门禁会识别此状态并在 Dashboard 的概览中显示警告，供项目经理审核并决策是否允许修改架构约束。

> [!WARNING]
> Agent 绝不能在未产生可验证的外部证据的情况下将任务标记为 `done`。自我声明（例如，在没有测试或代码引用的情况下宣称完成）将无法通过质量门禁校验。

---

## 2. 证据驱动的编码准则 (Evidence-Driven Coding Guidelines)

为确保所有实现均可被验证，Agent 必须遵守以下规则：

### A. 测试 Docstring 中的可追溯性标注
每一个单元测试、集成测试或回归测试函数**必须**包含一个 Docstring，声明其覆盖了哪些验收标准（AC）或需求（REQ）。
- 格式：`covers: AC-VT-xxx-xx` 或 `covers: REQ-VT-xxx`
- 示例：
  ```python
  def test_id_validation():
      """
      covers: AC-VT-001-03
      验证无效的 ID 能否被正确识别。
      """
      # 测试代码写在此处
  ```

### B. 路径与引用的完整性
当生成 `.vibetracing/agent_claims.json` 时，所有文件和代码引用（`code_refs` 和 `test_refs`）必须指向代码库中真实存在的文件。
- 指向不存在的路径或行号将触发 MUST 级严重风险并拦截门禁合并。
- 在声明时间戳**之后**修改文件，会使该 Claim 被标记为“过期（outdated）”（属于 SHOULD 级风险），并要求重新生成该 Claim。

---

## 3. Linter 与代码风格标准 (Linter and Code Style Standards)

如果代码违反了风格或语法标准，则不得合并入主分支：
1. **格式化**：所有文件必须通过 `ruff format` 完成格式化。
2. **代码检查**：所有文件必须通过 `ruff check`，且警告和错误数必须为 0。
3. **类型提示**：在任何可能的地方使用标准 Python 类型提示（Type Hinting）。

---

## 4. Agent 的自校验工作流 (Verification Workflow for Agents)

在宣布完成任何任务之前，Agent 必须在本地运行以下流程：
1. 运行 `pytest` 以确保所有测试通过（100% 通过率）。
2. 运行 `ruff check .` 检查是否存在代码违规。
3. 运行 `ruff format --check .` 确保格式化正确。
4. 运行 `vibe-tracing analyze` 在本地执行质量门禁检查，确保门禁裁决决定（Gate Decision）评估为 `pass`。

---

## 5. 自身开发治理变更交互规程 (Self-Governance Change Protocol)

作为 Vibe Tracing 治理自身开发的最高原则，任何对项目特性的修改、重构或架构约束调整，均**严禁**跳过治理流直接编码。所有项目变更必须遵循以下顺序执行：

1. **需求定义（PRD）**：在 [prd.md](file:///Users/lihan/Project/Vibe_Tracing/docs/prd.md) 中更新/添加对应功能的需求描述（`REQ-VT-*`）与验收标准（`AC-VT-*-*`）。
2. **架构规约（Constraints）**：如果涉及模块、依赖或目录变更，在 [architecture_constraints.json](file:///Users/lihan/Project/Vibe_Tracing/docs/architecture_constraints.json) 中更新对应的硬性约束规则或存储规规约。
3. **任务规划（Task List）**：在 [task_list.json](file:///Users/lihan/Project/Vibe_Tracing/docs/task_list.json) 中规划关联本次 AC 验收标准的原子任务项（`TASK-VT-*`），并明确 DoD 条目。
4. **自校验编码与测试**：在任务流下开始编写代码和测试，通过自校验工作流产生通过证据（如测试覆盖与 Claims 申报），最终由合并门禁（Merge Gate）自动审计确认。

> [!CAUTION]
> 任何在未同步更新 PRD、约束和任务列表的情况下直接修改或添加代码的“绕过”行为，均被判定为严重规程违规，合并门禁在分析自身开发时将拦截该合并。

