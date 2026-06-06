# Agile Governance & Traceability Chain Refactoring

通过深度梳理 Vibe Tracing (VT) 的基线控制与敏捷开发需求，我们决定对系统的自举架构进行一次底层逻辑升级。核心目标是**在保证架构控制力（防止绕过架构直接开发）的前提下，释放任务列表（Task List）的流转自由度**。

## 架构逻辑重构说明 (Architectural Shift)

1. **废除“泛化元任务”机制**：
   之前利用 `TASK-VT-999` 作为所有配置文件修改的收件箱，虽然解决了机器验证的闭环，但掩盖了真实的业务动因。我们将废除这一设定，回归敏捷本质：**对 PRD 和架构的任何修改，都必须由具体的业务或重构 Task 驱动**。

2. **基线与控制区的责任分离**：
   - **设计基线 (Design Baseline)**：`prd.md` 和 `architecture_constraints.json` 是神圣的契约。对其修改必须持有明确的、指向具体开发/设计任务的 Agent Claim。
   - **动态账本 (Dynamic Ledger)**：`task_list.json` 是规划黑板。为了避免“申请通行证的通行证”死锁，它将被放入幽灵代码扫描的白名单，允许自由流转。

3. **构建强制追溯拓扑 (Forced Traceability Topology)**：
   为防止 `task_list.json` 成为绕过架构设计的后门，我们在核心模型引擎中建立拓扑强制约束：**需求(REQ) <- 任务(Task) -> 模块(MOD)**。任何任务如果缺失 `related_modules`，即被判定为“架构孤儿”，验证引擎将爆红阻断。这倒逼开发者在面对新需求时，必须审视并确认架构边界。

---

## Proposed Changes

### 1. Ghost Code 拦截器机制调整

#### [MODIFY] `src/vibe_tracing/ghost_code_reconciler.py`
- 将 `docs/task_list.json` 重新加入到 `self.whitelist_paths` 中。
- **逻辑影响**：这意味着开发者或 AI Agent 自由拆分、更新任务时，不需要再伪造或提交无意义的 Claim。

### 2. 引入“强制架构归属”校验

#### [MODIFY] `src/vibe_tracing/task_loader.py`
- 在 `validate_data` 遍历 `task_list` 时增加强制校验逻辑：
  - 检查每一个解析出的 Task，验证其 `related_modules` 列表。
  - 如果 `len(related_modules) == 0`，则引发 Schema 级别的错误（例如：“Task [ID] is an architectural orphan. It must be bounded to at least one module in architecture_constraints.json”）。
- **逻辑影响**：虽然任务列表可以自由编辑，但任何新加入的、或已有的开发任务，如果不明确其在架构上的归属模块，就无法通过 `vt analyze` 的验证，系统整体状态将被标红。

### 3. 清理废弃的元治理机制

#### [MODIFY] `src/vibe_tracing/templates/task_list.template.json`
- 彻底移除 `TASK-{{PROJECT_PREFIX}}-999` 的预置定义。
- 将模板恢复为仅包含核心范例任务。

#### [MODIFY] `docs/task_list.json` (当前项目状态)
- 移除目前存在的 `TASK-VT-999` 任务，保持 VT 自身项目的整洁。

### 4. 测试套件对齐

#### [MODIFY] `tests/test_scaffolding.py` & `tests/test_dynamic_prefix.py`
- 将之前因为 `TASK-VT-999` 而修改的 `assert len(tasks_data["tasks"]) == 1` 断言恢复为 `0`（针对脚手架生成空列表的期望）。
- 更新相关的 `test_task_loader.py` 测试，确保所有模拟的任务数据都包含至少一个 `related_modules`，以适配新的强校验规则，并补充对“架构孤儿”报错的专门测试。

---

## User Review Required

> [!IMPORTANT]
> **关于全盘强制模块映射的例外考量：**
> 如果我们实施“强制架构归属”，意味着即便是纯文本的文档修改任务（如“校对英文文档”）也必须归属于某个架构 Module。
> 
> **方案 A (推荐)**：保持绝对强制。建议在 `architecture_constraints.json` 的 `module_boundaries` 中设置一个类似于 `MOD-VT-DOCS`（文档模块）或 `MOD-VT-OPS`（运维模块）的边界。这样强迫架构设计做到 100% MECE（相互独立，完全穷尽）。
> **方案 B**：放宽限制，允许部分特定状态或标记的 Task 豁免。
> 
> 当前计划将按**方案 A（绝对强制）**执行，以追求最高级别的理论严密性。请确认是否同意。

---

## Verification Plan

### Automated Tests
- 执行 `python3 -m pytest tests/`，必须达到 100% 通过率。
- 重点关注新增的 `test_task_loader.py::test_architectural_orphan_rejection`，确保无模块归属的任务被精准拦截。

### Manual Verification
- 运行 `vt analyze`，确保当前 Vibe Tracing 项目本身由于补齐了所有的模块依赖，可以顺畅通过验证。
- 尝试手动在 `docs/task_list.json` 中新增一个不带 `related_modules` 的任务，运行 `vt analyze`，预期看到明确的阻断报错和修复指导。
