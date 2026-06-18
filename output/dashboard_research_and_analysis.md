# Vibe Tracing Dashboard 待决策数据与设计机制调研报告

本报告汇总了关于 Vibe Tracing Dashboard 中“待决策事项”信息缺失缺陷的定位分析，以及针对 AI Coding Agent 开发特点的架构设计研讨。

---

## 一、 Dashboard 待决策事项缺少必要信息的缺陷分析

### 1. 缺陷现象描述
在 Dashboard 的“待决策事项”标签页中，当存在“未接受的架构规则”时，决策卡片仅显示规则 ID（例如 `PRINCIPLE-VT-002`）和一条通用的机器原因（`Manual verification rule PRINCIPLE-VT-002 requires human acceptance.`），缺乏对该规则实际业务含义和具体要求的描述（如规则的 Title 和 Description），导致人类项目经理/架构师无法直接做出决策。

### 2. 数据传递与内联文件机制
Dashboard 采用**完全自包含、离线可运行**的设计，数据传递通过以下方式实现：
* **生成路径**：执行 `vt analyze` 时，命令行工具调用 `src/vibe_tracing/dashboard_renderer.py`，加载 HTML 模板 `src/vibe_tracing/templates/dashboard.template.html`，把分析产生的 JSON 结果直接替换嵌入到输出文件 `output/dashboard.html` 的 `<script type="application/json">` 标签中。
* **数据源**：嵌入的数据中，`trace-report-json` (对应 `output/traceability_report.json`) 包含了两个关键字段：
  1. `unclear_constraints`：存储不明确约束的简略信息（只含有 `rule_id` 和 `reason`）。
  2. `architecture_compliance_status`：存储所有架构约束规则的**完整定义**，其中包含 `rule_id`、`title`（规则名称）和 `description`（规则具体描述）。

### 3. 根本原因定位
缺陷存在于前端解析逻辑中（位于 `dashboard.template.html` 的 `extractPendingDecisions` 函数第 `F` 部分）：
```javascript
// F. Unaccepted manual rules from unclear_constraints
if (reportData.unclear_constraints) {
    reportData.unclear_constraints.forEach(function(uc) {
        var ruleId = uc.rule_id || '';
        var reason = uc.reason || '';
        ...
        decisions.push({
            id: 'unclear-' + ruleId,
            category: 'accepted_rule',
            targetId: ruleId,
            categoryLabel: '未接受的架构规则',
            icon: 'shield-alert',
            title: ruleId, // 🔴 问题：直接将 rule_id 用作 Title，而不是可读的规则 Title
            status: 'pending',
            question: '此 manual 规则需要人工确认。是否接受？',
            actions: ['接受', '拒绝'],
            evidenceChain: [
                {label: '规则 ID', value: ruleId},
                {label: '原因', value: reason} // 🔴 问题：证据链中仅包含简略原因，没有规则具体描述（description）
            ]
        });
    });
}
```
**缺陷根本原因**：前端提取待决策架构规则时，**仅仅读取了简略的 `unclear_constraints` 结构，未能在 `architecture_compliance_status` 列表中通过 `rule_id` 匹配检索出该规则对应的 `title` 和 `description`**，从而导致卡片展示的信息不全。

---

## 二、 交互决策的本地通信设计原由

* **设计现状**：Dashboard 通过请求本地 Flask 后台 `http://localhost:5000/api/decisions`（`decision_server.py`）来存储用户的“接受/拒绝”结果到本地磁盘 `.vibetracing/human_decisions.json`。
* **为何不能直接调用 Python 脚本**：由于 Dashboard 运行在标准网页浏览器中，受到**浏览器安全沙箱限制**，网页无法直接调用本地文件系统或执行本地命令行/Python 文件。因此，必须依靠一个极其轻量级的本地 HTTP 服务作为桥梁，实现沙箱前端与本地磁盘文件系统的安全交互。

---

## 三、 VT 核心治理机制与 AI Coding Agent 特点匹配度分析

### 建议：将“技术债务”更名为“证据债务（Evidence Debt）”
*传统的“技术债务”常指代码异味、架构不合理。但在 VT 中，我们并不检测代码复杂度，而是检测“有无客观证据证明其正确性”。改用**“证据债务”**可以精准表达“缺少客观验证事实支持”的治理本意，避免概念混淆。*

### 1. 30天规则复审机制 —— 防腐与人类在环（Human-in-the-loop）
* **AI Agent 特点**：Agent 修改代码的频次极高，短时间内代码库可能发生剧烈演进。人工审查的规则（如“面向人类的治理表达”）在 30 天的高频迭代中极易发生“渐进式偏离”（Drift）。
* **设计判定**：**符合 AI 开发特点**。30 天过期强制复审为极速运行的 AI Agent 设置了一个定期人类对齐的物理防线，确保架构规约在演进中不会名存实亡。

### 2. 当前任务阻塞，历史债务警告 —— 渐进式治理与快速失败
* **AI Agent 特点**：Agent 缺乏对庞大历史背景的认知。如果因存量历史债务而阻断当前的门禁，Agent 极易在尝试“修复无关历史代码”时陷入逻辑泥潭，甚至引入大范围回归风险。
* **设计判定**：**符合 AI 开发特点**。
  * **当前变更（Staged Items）缺失证据**：直接 `blocked` 阻断合并，要求 Agent 必须对自己本次写的代码质量负责，实现“零新增债务”。
  * **历史存量缺失证据**：判定为 `passed` 警告但不阻断，避免打断 Agent 当前的交付心流。

### 3. 工具盲区中跳过（skipped）状态的警报
* **AI Agent 特点**：Agent 在面临复杂的测试环境时，容易产生“偷懒”或“幻觉”（如创建一个空的 `test_*.py` 规避门禁）。当 `pytest` 返回 Exit Code 5（未收集到任何测试用例）被跳过时，Agent 可能会误以为“测试已写完并通过”。
* **设计判定**：**符合 AI 开发特点**。将“工具未执行”显式定义为“工具盲区”并呈报给人类决策，能够防范 Agent 敷衍门禁。由于浏览器沙箱限制，Dashboard 提供“不需要（跳过）”写入豁免，以及“需要（开发人员线下补充用例并终端重跑 `vt analyze` 以实现重新运行）”的互补设计。

### 4. 基于哈希（Hash）绑定的 Claim 生命周期
* **AI Agent 特点**：Agent 没有跨会话的长期记忆。如果 Agent 宣称完成的 Claim 是永久有效的，一旦后续迭代中其他 Agent 修改了这部分文件，系统将继续维持旧的信任，产生安全漏洞。
* **设计判定**：**核心支柱设计**。将 Claim 与代码及测试文件的 SHA-256 哈希值强制绑定，任何代码变更均会导致旧 Claim 瞬时失效。这用确定性的密码学手段，弥补了 AI Agent 健忘、易出错的局限，强迫其必须在代码变更后重新自检。

---

## 四、架构级复核结论

本节基于 VT 项目源代码实现，对上述分析报告的三章内容进行逐一复核。

### 1. 缺陷分析复核 — 准确 ✓

通过读取 `traceability_report.json` 和 `dashboard.template.html` 的实际代码，确认缺陷真实存在：

- `unclear_constraints` 数组确实只有 `rule_id` 和 `reason` 两个字段（当前共 65 条未接受的 manual 规则）
- `architecture_compliance_status` 数组确实包含每条规则的 `title`（中文标题）和 `description`（中文描述）
- 前端 `extractPendingDecisions` 函数 Section F 确实**没有**做跨数组查找，直接把 `ruleId` 原文当作卡片标题

**实际影响举例**：Dashboard 现在显示 `title: "PRINCIPLE-VT-002"`（只是一串编号），应该显示 `title: "Agent 不能自证完成"` + 对应描述。

**补充**：Dashboard 的"不可验证约束"区域也存在同样缺陷——只显示 `rule_id` 和 `reason`，没有查找 `title`/`description`。这是同一类缺陷的第二个实例。

### 2. 本地通信设计复核 — 准确 ✓

- `decision_server.py` 确实是极轻量 Flask 服务（仅 GET/POST 两个端点）
- 写入目标确实是 `.vibetracing/human_decisions.json`
- 浏览器沙箱限制的解释完全正确

### 3. 设计机制匹配度复核 — 方向正确，两处精度修正

**精度修正 1 — 30 天规则复审**：

报告描述为"物理防线"和"强制复审"。代码实际行为：`_is_stale_acceptance()` 会标记 `stale_acceptance: true`，但**不自动阻断门禁**——过期的规则仍然被视为"已接受"，只是 Dashboard 会提示人类重新确认。**定性：是定期提醒机制，不是强制防线。** 这在当前阶段是合理设计（避免过度阻断），但报告措辞可能给人"自动阻断"的错误印象。

**精度修正 2 — 哈希绑定层次**：

报告只提到 Claim 与代码/测试文件的 SHA-256 绑定。实际 VT 有三层哈希机制：

| 层级 | 对象 | 用途 |
|------|------|------|
| Layer 1 | Claim 内容哈希（`content_hash`，16 位截断 SHA-256） | 检测 claim 定义本身是否变化 |
| Layer 2 | 文件 SHA-256（代码/测试文件） | 检测代码变更导致 claim 需要重新验证 |
| Layer 3 | 治理文件哈希（PRD + constraints） | Gate 1 防篡改，保护设计基线不被静默修改 |

报告只覆盖了 Layer 2，但 Layer 1 和 Layer 3 同样是核心设计。特别是 Layer 3——`vt finalize` 锁定的 `constraints_hash` 和 `prd_hash` 被写入 `config.json`，后续 `vt analyze` 会对比检测是否有人篡改了设计文件。

**其他三个设计模式（当前任务阻塞/历史债务警告、工具盲区跳过状态、Claim 生命周期）的分析均与代码实现一致，无修正。**

---

## 五、原子化修复计划

以下任务按 subagent 可独立执行的粒度设计，每个任务包含完整的目标、文件、修改内容和验收标准。

### T1：Dashboard 决策卡片丰富 title/description

- **目标**：修复"待决策事项"中架构规则卡片只显示 rule_id 编号的问题
- **涉及文件**：`src/vibe_tracing/templates/dashboard.template.html`
- **修改位置**：`extractPendingDecisions` 函数 Section F（约第 2452-2480 行）
- **具体修改**：
  1. 在 Section F 中，用 `uc.rule_id` 在 `reportData.architecture_compliance_status` 数组中查找匹配项（`archRules.find(r => r.rule_id === ruleId)`）
  2. 将匹配项的 `title` 赋给决策卡片的 `title` 字段（替换当前直接使用 `ruleId`）
  3. 将匹配项的 `description` 加入 `evidenceChain` 数组，label 为"规则描述"
  4. 保留 `rule_id` 作为额外证据链条目
- **验收标准**：运行 `vt analyze` 后，Dashboard 中每张待决策卡片显示中文标题（如"Agent 不能自证完成"）而非编号（如"PRINCIPLE-VT-002"），且证据链包含规则描述
- **可调度性**：独立任务，不依赖其他任务

### T2：Dashboard 不可验证约束区域丰富 title/description

- **目标**：修复"不可验证约束"区域只显示 rule_id 的同类问题
- **涉及文件**：`src/vibe_tracing/templates/dashboard.template.html`
- **修改位置**：不可验证约束渲染器（约第 2149-2161 行）
- **具体修改**：
  1. 在该渲染器中，同样用 `uc.rule_id` 查找 `reportData.architecture_compliance_status` 匹配项
  2. 将 `title` 和 `description` 展示在约束卡片中
- **验收标准**：不可验证约束区域每条规则显示中文标题和描述
- **可调度性**：与 T1 同文件但不同函数，建议合并为一个 subagent 任务（减少上下文传递，避免 git 冲突）

### T3：验证修复效果

- **目标**：确认 T1/T2 修复后 Dashboard 正确显示
- **涉及文件**：无代码修改，仅验证
- **具体操作**：
  1. 运行 `python3 -m vibe_tracing analyze` 生成新 dashboard
  2. 检查 `output/dashboard.html` 中待决策卡片是否显示中文标题
  3. 检查不可验证约束区域是否显示中文标题和描述
- **验收标准**：所有 manual 规则的决策卡片均显示中文标题 + 描述，不可验证约束区域同理
- **可调度性**：依赖 T1+T2 完成后执行

### 调度方案

```
并行阶段：
  T1 + T2 → 合并为一个 subagent（同文件修改，避免冲突）

串行阶段：
  T1+T2 完成后 → T3（验证）
```

### 验证方式

1. `python3 -m vibe_tracing analyze` 生成新报告和 dashboard
2. 浏览器打开 `output/dashboard.html`
3. 检查"待决策事项"标签页：每张卡片标题应为中文（如"Agent 不能自证完成"），不是 rule_id 编号
4. 检查"不可验证约束"区域：每条规则应显示中文标题和描述
5. 运行 `python3 -m pytest tests/ -x` 确认无回归
