# Vibe Tracing 极简流水线重构规划 (V3 vs V4 方案对比)

为了方便您进行架构选型，我将完全基于代码解耦的 **V3 (Config-is-King)** 方案与基于流程隔离的 **V4 (Finalize-as-a-Committer)** 方案进行全景式的平行展示。

---

# 方案 V3：Config-is-King 范式 (代码级彻底解耦)

**核心哲学**：将架构的“设计期”与“运行期”在代码结构上彻底切断。遵循极致的奥卡姆剃刀，杀死所有的防腐层 Hash 对比。

## 1. 核心模型
*   **设计图纸归设计**：`docs/architecture_constraints.json` 纯粹变成一张草图。
*   **编译产生权威**：`vt finalize` 被重构为一个“编译器”。它读取草图中的执行规则（如 `language_tool_matrix`），提取后写入 `.vibetracing/config.json` 中。
*   **执行层完全盲视**：`vt analyze` 彻底失去读取 `docs/` 目录图纸的权限，它**只能且只认** `.vibetracing/config.json` 进行门禁判定。

## 2. 防腐层与 Hook 逻辑
*   **防篡改**：完全不需要算 Hash。因为 `vt analyze` 不读草图，所以 AI 在本地怎么乱改图纸都无法降低门禁标准，除非它运行 `vt finalize` 重新编译。
*   **Git Hook (Pre-commit)**：
    *   **关卡 1（防幽灵代码）**：提取暂存区代码，核对 `agent_claims.json`。
    *   **关卡 2（强制编译拦截）**：如果暂存区有 `architecture_constraints.json`，则检查是否同时存在更新后的 `.vibetracing/config.json`。如果不在，拦截报错：“必须先运行 `vt finalize` 编译生效”。

## 3. 致命缺陷 (被否决原因)
*   **切断了神圣证据链**：因为 `vt analyze` 为了防篡改而瞎掉了双眼（不读架构源文件），它无法在门禁时获取规则的标题、描述等丰富语义，**导致最终生成的 Traceability Report 变成了毫无意义的死链**，无法实现“PRD -> 架构 -> 任务 -> 代码”的完美映射。

---

# 方案 V4：Finalize-as-a-Committer 范式 (流程级物理隔离)

**核心哲学**：保留底层强悍的证据链解析能力，但在 Git 生命周期上进行独裁式划分。用“Git 权限收拢”来替代繁重的代码重构，解决死锁。

## 1. 核心模型
*   **保留完整的溯源解析**：`vt analyze` **保持现状**，继续读取 `architecture_constraints.json`，以确保生成的证据链（Traceability Chain）拥有 100% 的原始语义和映射关系。
*   **Finalize 成为唯一提交者**：这是整个 V4 的精髓。架构设计文件（如 `architecture_constraints.json` 和 `prd.md`）**被剥夺了通过常规 `git commit` 提交的资格**。
*   如果任何人修改了架构图纸，他们必须运行 `vt finalize`。这个命令会在内部：
    1.  校验日志并计算 Hash。
    2.  直接代替用户在底层执行免检提交：`git commit -m "chore: VT architecture baseline finalized" --no-verify`。

## 2. 防腐层与 Hook 逻辑
在这个干净的模型下，因为合法修改架构的途径（`vt finalize`）直接绕过了 Hook，日常的 `git commit` 变成了纯粹的“打工人专属命令”。此时 Hook 触发的 `vt analyze` 逻辑变得极其简单刚猛：

*   **防篡改（查 Hash）**：`vt analyze` 上来就查本地图纸的 Hash 是否匹配 Config。如果不匹配，直接物理击杀。
    *   *潜台词：“你用常规 commit 触发了 Hook，说明你在提交业务代码。但你的架构地基却被篡改了，拒绝服务！”*
*   **防幽灵代码（查 Claims）**：提取 `git diff --cached` 里的纯业务代码，去 `agent_claims.json` 核对发票。没有发票直接拦截。

## 3. V4 的实施成本与收益
*   **收益**：完美保住了 Vibe Tracing 的灵魂证据链（PRD -> 代码）；完美消灭了“修改架构即死锁”的问题；AI 偷改架构必被拦截。
*   **实施动作**：
    1.  重构 `run_finalize`，赋予其调用 `subprocess` 执行 `git commit --no-verify` 的能力，并检查暂存区是否不纯净（如果混入了业务代码则报错退出）。
    2.  编写极简的 Git Pre-commit 钩子分发脚本。
    3.  在 `run_analyze` 开头增加基于 `git diff` 的幽灵代码排查关卡。

---

## User Review Required

> [!IMPORTANT]
> 这份对比文档完整呈现了两次思维迭代的过程。
> 
> *   **V3** 追求代码层面的解耦和极简，但代价是牺牲了核心业务目标（证据链溯源）。
> *   **V4** 则跳出了代码视角的局限，利用软件工程的协作生命周期（Git 行为管控）实现了四两拨千斤的物理防线，保全了核心资产。
> 
> 请您详细审阅并对比这两种范式。如果您确认 V4 范式是我们要前行的终极方向，请下达开发指令！
