# VT 噪音消除措施改进方案

**日期**: 2026-06-08
**状态**: ✅ 已实施（进化轮次 d 全部完成）
**关联**: [待研究问题 - 第二节](vt_pending_issues_20260608.md)

---

## 一、核心问题与方向重定义

### 1.1 死循环的本质

当前 VT 存在一个结构性死循环：

```
Agent 产生噪音 → 噪音被消除 → 人类看不到全貌 → 人类无法决策
→ Agent 继续推进 → 产生更多待决策事项 → 噪音更多 → 更多消除
→ 人类更看不懂 → 决策更难 → Agent 进入死循环
```

**根因**：该人类决策的地方，没有给人类接手的窗口。噪音消除的实质是把人类挡在了决策门外。

### 1.2 从第一性原则出发

人类决策业务需求是否已经实现，用的是**逻辑思维而非阅读代码**。人类关心的链路是：

```
PRD 需求 → 架构设计 → 开发任务 → 代码实现 → 测试验证 → 交付验收
```

每个环节人类需要判断：

| 环节 | 人类判断 | 当前状态 |
|---|---|---|
| PRD→架构 | 架构设计是否覆盖了我的需求？ | 被 accepted_by 隐藏 |
| 架构→任务 | 任务是否把设计拆解完整了？ | 被 stale 机制掩盖 |
| 任务→代码 | 代码实现是否遵守了架构约束？ | 9 条门禁静默跳过 |
| 代码→测试 | 测试是否覆盖了业务场景？ | exit code 5/2 不产生证据 |
| 变更管理 | 这个变更我接受吗？ | 变更被消除而非记录 |

### 1.3 方向重定义

**从"分层呈现"到"决策平台"**：

| | 原方案（分层呈现） | 新方案（决策平台） |
|---|---|---|
| **定位** | 报告工具（被动呈现） | 决策平台（主动交互） |
| **人类角色** | 读者（看报告） | 决策者（点按钮） |
| **噪音处理** | 在报告层保留，门禁层隐藏 | 分流：噪音→决策请求→人类处理 |
| **信息流动** | 单向（VT→人类） | 双向（VT→人类→VT→Agent） |
| **死循环** | 缓解但不根治 | 在决策节点打断 |

**核心思路**：让人类通过 dashboard 页面作出该做的决策，Agent 的噪音减少，人类视图和 Agent 视图自然分离。Agent 视图可以充分按照效率打造，人类只需要关注页面上的决策按钮。

### 1.4 双核心用户

VT 有两个核心用户，不能偏废：

| 用户 | 使用场景 | 需要什么 |
|---|---|---|
| **AI Coding Agent** | 每次代码变更时调用 `vt analyze` | 明确的行动清单：下一步该做什么 |
| **人类（业务方） | 验收时打开 dashboard | 可理解的决策项：这个功能完成了吗？ |

**Agent 是 VT 的主要使用者**（高频、自动化），**人类是最终决策者**（低频、但关键）。如果 Agent 不能在 VT 指引下运行在正确路径上，人类做出的决策将毫无意义。

---

## 二、人类视图：如何让没有开发经验的人类看懂

### 2.1 核心原则：VT 技术数据 → 业务语言翻译

VT 已经采集了完整的证据链和门禁判断信息。问题不是"信息不够"，而是"信息没有被翻译成人类能理解的语言"。

**翻译逻辑**：VT 的每一条技术数据都对应一个业务含义。Dashboard 的职责是建立这个映射关系，让人类不需要理解技术就能做出判断。

### 2.2 决策点 A：需求是否被架构覆盖

**VT 已有数据**：`traceability_report.json` 中的 `requirement_coverage` 字段，包含每个 REQ 关联了哪些 AC、task、claim。

**翻译方式**——不要展示"架构"这个概念，用需求→功能的拆解关系：

```
需求 REQ-001："用户能够执行一致性分析"

这个需求被拆成了 3 个具体功能：
  ✓ AC-001 "命令行输入能被解析"
    → 有开发任务 ✓  有代码实现 ✓  有测试保障 ✓

  ✓ AC-002 "分析结果能输出到文件"
    → 有开发任务 ✓  有代码实现 ✓  有测试保障 ✓

  ✗ AC-003 "错误输入能给出提示"
    → 有开发任务 ✓  有代码实现 ✓  没有测试 ✗

需要您判断：AC-003 没有测试保障，这个功能是否需要补充测试？
[需要补充测试] [当前可接受]
```

**人类只需看**：我的需求被拆成了几个功能？每个功能有没有测试保障？没有保障的那个，我接受吗？

### 2.3 决策点 B：代码是否遵守了设计约束

**VT 已有数据**：`architecture_compliance_status`（每条规则的检查结果）、`architecture_violations`（违规列表）。

**翻译方式**——不要展示规则 ID 和技术术语，用"做了/没做到"：

```
代码质量检查结果：

做到了：
  ✓ 所有输入文件格式正确
  ✓ 每个需求都有对应的任务
  ✓ 每个任务都有对应的代码声明

没做到：
  ✗ 3 个功能没有测试保障
    具体：AC-003（错误提示）、AC-007（日志输出）、AC-012（配置加载）

您之前确认过：
  • "功能必须有测试" — 2026-06-01 确认，已过期（超过 30 天）
    此规则仍然有效吗？ [仍然有效] [不再适用]
```

**人类只需看**：哪些做到了？哪些没做到？我之前确认的规则还有效吗？

### 2.4 决策点 C：测试是否覆盖了业务场景

**VT 已有数据**：`evidence_index.json` 中 source_type=tool 的条目（pytest/mypy 结果）、source_type=test 的条目。

**翻译方式**——不要展示 exit code 和工具名称，用"测试了/没测试"：

```
测试覆盖情况：

已测试的功能（有测试保障）：
  ✓ AC-001 命令行解析 — 15 个测试通过
  ✓ AC-002 文件输出 — 8 个测试通过

未测试的功能（没有测试保障）：
  ✗ AC-003 错误提示 — 没有找到测试

工具检查盲区（无法自动检查）：
  ⚠ src/config.py — 检查工具运行了但没有找到测试
    此文件可能不需要测试，也可能遗漏了

需要您判断：
  • AC-003 是否需要补充测试？ [需要] [不需要]
  • config.py 是否需要补充测试？ [需要] [不需要] [不确定]
```

**人类只需看**：哪些功能有测试？哪些没有？没有的我接受吗？

### 2.5 决策点 D：变更是否接受

**VT 已有数据**：`traceability_report.json` 中的 `gaps` 和 `risks`，包括新增的和预存的。

**翻译方式**——不要展示 claim_id 和 technical debt 术语，用"新问题/老问题"：

```
本次变更的情况：

新引入的问题（本次代码变更带来的）：
  • cli.py 中新增了一个固定的文件路径
    如果将来路径需要变更，程序需要修改
    建议：改为可配置项
    [必须修复] [可以接受] [延后处理]

之前就存在的问题（本次未变更，但问题仍在）：
  • config.py 缺少输入检查
    如果输入格式错误，程序可能崩溃
    已存在：3 个迭代
    [本次处理] [继续延后]

本次变更的总体判断：
  ✓ 新功能有代码实现
  ✓ 设计约束基本遵守
  ✗ 部分功能缺少测试
  [接受本次变更] [需要补充后再接受]
```

**人类只需看**：这次变更引入了什么新问题？老问题处理了吗？我接受这次变更吗？

### 2.6 决策点 E：任务是否完成

**VT 已有数据**：`task_list.json` 中的 task status、关联的 claim、evidence。

**翻译方式**——用需求链路的完整性来呈现：

```
任务 TASK-VT-001："实现命令行解析功能"

关联的需求：REQ-001 "用户能够执行一致性分析"
关联的验收标准：AC-001 "命令行输入能被解析"

完成情况：
  ✓ 代码已实现（3 个文件变更）
  ✓ 测试已编写（15 个测试通过）
  ✓ 设计约束已遵守

此任务可以标记为完成吗？ [确认完成] [需要补充]
```

**人类只需看**：这个任务对应我的哪个需求？代码写了没？测试过了没？能完成吗？

### 2.7 翻译映射表

| VT 技术数据 | 业务语言 | 人类需要的判断 |
|---|---|---|
| `requirement_coverage` 缺失 | "这个需求没有被任何功能覆盖" | 我的需求漏了吗？ |
| ac gap（无测试） | "这个功能没有测试保障" | 这个功能需要测试吗？ |
| `architecture_violation` | "代码违反了设计约束" | 这个违规我能接受吗？ |
| tool evidence skipped | "这个文件没有被检查过" | 这个文件需要检查吗？ |
| stale risk | "这个问题之前就存在，一直没处理" | 这次要处理吗？ |
| `accepted_by` + `stale_acceptance` | "您之前确认过这个规则，但已经过期了" | 这个规则还有效吗？ |
| task status=done + claim 完整 | "这个任务代码和测试都有了" | 可以标记完成吗？ |

**这个映射关系在 dashboard 模板中硬编码**，因为 VT 的数据结构是已知的、稳定的。

---

## 三、Agent 视图：让 Agent 运行在正确路径上

### 3.1 Agent 当前的问题

当前 `vt analyze` 的 stdout 输出是统计摘要：

```
Gate decision: BLOCKED
Gaps: 12
Risks: 5
Evidence candidates: 47
```

这对 Agent 来说**信息不足**。Agent 知道被阻断了，但不知道**具体该做什么**。Agent 需要的不是"完整报告"，而是**明确的下一步指令**。

### 3.2 Agent 视图设计：可执行行动清单

**设计原则**：Agent 读完行动清单后，应该能**直接开始工作**，不需要再去读 PRD、读代码、读测试文件。每个行动项必须包含足够的上下文。

**当前问题**：之前的方案只给了"AC-003 没有测试"这样的摘要，Agent 还需要自己去查 AC 的完整描述、相关代码、测试模式。这浪费了 Agent 的时间，也容易走偏。

**正确做法**：VT 已经拥有所有数据（PRD、task_list、claims、evidence、代码），行动清单应该把 Agent 需要的一切**内联呈现**。

```
GATE DECISION: BLOCKED

═══════════════════════════════════════════════════════════════════
ACTION 1 [HIGH] 补充测试：AC-003 "错误输入提示"
═══════════════════════════════════════════════════════════════════

验收标准（来自 PRD）:
  AC-003: 当用户输入无效参数时，程序应输出清晰的错误提示并退出
  严重级别: MUST
  关联需求: REQ-001 "用户能够执行一致性分析"

实现代码（已存在）:
  src/vibe_tracing/cli.py:445-462 — handle_invalid_args()
  ┌─────────────────────────────────────────────────────────┐
  │ def handle_invalid_args(args):                          │
  │     if not args:                                        │
  │         print("Error: no input provided", file=sys.stderr) │
  │         sys.exit(1)                                     │
  │     if not Path(args[0]).exists():                      │
  │         print(f"Error: file not found: {args[0]}", ...) │
  │         sys.exit(1)                                     │
  └─────────────────────────────────────────────────────────┘

需要测试的场景（根据 AC 推导）:
  1. 空参数 → 应输出 "no input provided" 并 exit(1)
  2. 不存在的文件 → 应输出 "file not found" 并 exit(1)
  3. 有效参数 → 不应报错

现有测试（参考风格）:
  tests/test_cli.py:12-28 — test_valid_input_parsing()
  ┌─────────────────────────────────────────────────────────┐
  │ def test_valid_input_parsing(tmp_path):                 │
  │     config = tmp_path / "config.json"                   │
  │     config.write_text('{"project_id": "test"}')         │
  │     result = run_vt(["analyze", str(config)])           │
  │     assert result.returncode == 0                       │
  └─────────────────────────────────────────────────────────┘
  测试框架: pytest + tmp_path fixture
  运行命令: pytest tests/test_cli.py -v

验证标准:
  - pytest tests/test_cli.py -v 中新增 3 个测试全部通过
  - 覆盖 AC-003 的所有场景
  - vt analyze 重新运行后 AC-003 gap 消失

可并行: 无（此项为最高优先级）

═══════════════════════════════════════════════════════════════════
ACTION 2 [HIGH] 修复违规：GATE-VT-004 未通过
═══════════════════════════════════════════════════════════════════

违规规则: GATE-VT-004 "MUST 级 AC 必须有测试覆盖"
违规原因: AC-003 是 MUST 级但无测试
修复方式: 完成 ACTION 1 后此违规自动消除
备选方案: 在 PRD 中将 AC-003 降级为 SHOULD（需人类确认）

可并行: 与 ACTION 1 同源，完成 ACTION 1 即可

═══════════════════════════════════════════════════════════════════
ACTION 3 [MEDIUM] 等待人类决策（DEC-001）
═══════════════════════════════════════════════════════════════════

决策项: DEC-001 "功能必须有测试"规则已过期
决策问题: 此规则仍然有效吗？
当前状态: 等待人类在 dashboard 上确认
影响: 门禁 GATE-VT-004 依赖此规则，确认后门禁行为可能变化

建议操作: 通知人类在 dashboard 上查看 DEC-001
人类操作后: 下次 vt analyze 会自动读取 human_decisions.json

可并行: 是 — 可以先执行 ACTION 1，不依赖此决策

═══════════════════════════════════════════════════════════════════
ACTION 4 [LOW] 预存债务（DEC-005）
═══════════════════════════════════════════════════════════════════

风险: config.py 缺少输入检查
描述: 如果输入格式错误，程序可能崩溃
已存在: 3 个迭代
人类决策: DEC-005 等待人类判断是否本次处理

可并行: 是 — 不影响门禁，可在空闲时处理

═══════════════════════════════════════════════════════════════════
SUMMARY
═══════════════════════════════════════════════════════════════════
已通过: Gate 1 (约束哈希), Gate 2 (幽灵代码), Gate 2.5 (AC 新鲜度)
阻断项: 2 个 HIGH（同源，完成 ACTION 1 即可）
等待人类: 1 项 DEC-001（不阻断，可并行）
预存债务: 1 项 DEC-005（不影响门禁）
建议: 先执行 ACTION 1，同时通知人类处理 DEC-001
```

### 3.3 Agent 的决策循环

Agent 使用 VT 的正确方式：

```python
while True:
    result = vt_analyze()

    if result.gate_decision == "passed":
        # 所有门禁通过，可以提交
        vt_commit()
        break

    # 按优先级执行行动
    for action in result.actions:
        if action.priority == "HIGH":
            execute(action)  # 补充测试、修复违规等
            break
        elif action.priority == "MEDIUM" and action.type == "human_decision":
            # 需要人类决策，通知人类并等待
            notify_human(action)
            wait_for_decision(action.target_id)
            break

    # 循环：再次分析
```

### 3.4 人类决策如何影响 Agent

当人类在 dashboard 上做出决策后，`human_decisions.json` 被更新。Agent 在下一次 `vt analyze` 时：

1. 读取 `human_decisions.json`
2. 如果人类 `accept_gap`：对应 gap 从行动清单中移除，门禁可能解除
3. 如果人类 `reconfirm`：对应规则的过期状态重置
4. 如果人类 `request_action`：对应事项优先级提升为 HIGH

**这就是"人机协作"的完整闭环**：

```
Agent 执行行动 → vt analyze → 门禁未通过 → 存在人类决策请求
     ↑                                          │
     │                                          ↓
     └──── vt analyze ← 人类做出决策 ← Dashboard 展示决策项
           (门禁解除)     (human_decisions.json)
```

### 3.5 Agent 视图的代码改动

**`cli.py` 中 `vt analyze` 的 stdout 输出重构**：

```python
def _format_agent_actions(gate_decision, active_gaps, active_risks, violations, accepted_rules, decisions, prd_data, task_data, evidence_data):
    """格式化 Agent 可执行的行动清单（含完整上下文）"""
    lines = [f"GATE DECISION: {gate_decision.upper()}", ""]

    actions = []

    # HIGH: 必须级 gap — 内联完整上下文
    for gap in active_gaps:
        if gap.get("severity") == "must" and not gap.get("human_accepted"):
            ac_id = gap["item_id"]
            ac_text = _get_ac_description(ac_id, prd_data)
            related_code = _get_related_code(ac_id, task_data)
            existing_tests = _get_existing_tests(ac_id, task_data, evidence_data)
            test_scenarios = _derive_test_scenarios(ac_text, related_code)

            actions.append({
                "priority": "HIGH",
                "type": "cover_gap",
                "id": ac_id,
                "title": f"补充测试：{ac_id} \"{ac_text}\"",
                "context": {
                    "ac_description": ac_text,
                    "severity": gap.get("severity", "MUST"),
                    "requirement_id": gap.get("requirement_id"),
                    "requirement_text": _get_req_description(gap.get("requirement_id"), prd_data),
                    "implementation_code": related_code,  # 内联代码片段
                    "test_scenarios": test_scenarios,      # 根据 AC 推导的测试场景
                    "existing_test_pattern": existing_tests,  # 项目中的测试风格参考
                    "verification": f"pytest 中新增覆盖 {ac_id} 的测试，vt analyze 后 gap 消失",
                },
            })

    # HIGH: 违规 — 关联到 gap
    for v in violations:
        actions.append({
            "priority": "HIGH",
            "type": "fix_violation",
            "id": v["rule_id"],
            "title": f"修复违规：{v['rule_id']}",
            "context": {
                "rule_text": v.get("description", ""),
                "violation_reason": v.get("reason", ""),
                "fix_via": "完成关联的 gap 修复后自动消除",
                "alternative": "在 PRD 中降级相关 AC（需人类确认）",
            },
        })

    # MEDIUM: 等待人类决策
    for dec in decisions.get("decisions", []):
        if dec.get("status") == "pending":
            actions.append({
                "priority": "MEDIUM",
                "type": "human_decision",
                "id": dec["decision_id"],
                "title": f"等待人类决策（{dec['decision_id']}）",
                "context": {
                    "decision_question": dec.get("question", ""),
                    "current_status": dec.get("status", ""),
                    "impact": dec.get("impact_description", ""),
                    "suggestion": f"通知人类在 dashboard 上查看 {dec['decision_id']}",
                },
            })

    # LOW: 预存债务
    for risk in active_risks:
        if risk.get("stale") and not risk.get("deferred"):
            actions.append({
                "priority": "LOW",
                "type": "stale_debt",
                "id": risk.get("claim_id", "unknown"),
                "title": f"预存债务：{risk.get('title', '')}",
                "context": {
                    "description": risk.get("description", ""),
                    "age": f"{risk.get('age_iterations', '多个')} 个迭代",
                    "impact": risk.get("impact", "不影响门禁"),
                },
            })

    return _render_actions(lines, actions)


def _get_ac_description(ac_id, prd_data):
    """从 PRD 数据中提取 AC 完整描述"""
    # 遍历 prd_data 中的 requirements，找到 ac_id 对应的完整文本
    for req in prd_data.get("requirements", []):
        for ac in req.get("acceptance_criteria", []):
            if ac.get("ac_id") == ac_id:
                return ac.get("description", "")
    return ""


def _get_related_code(ac_id, task_data):
    """从 task_data 中提取 AC 关联的代码片段"""
    code_refs = []
    for task in task_data.get("tasks", []):
        for ac in task.get("related_acs", []):
            if ac == ac_id:
                code_refs.extend(task.get("code_refs", []))
    # 读取代码文件，提取相关函数（限制行数）
    code_snippets = []
    for ref in code_refs[:3]:  # 最多 3 个文件
        path = ref.split("#")[0]
        if Path(path).exists():
            content = Path(path).read_text()
            # 提取相关函数（简化：取前 20 行）
            code_snippets.append({"path": path, "content": content[:500]})
    return code_snippets


def _get_existing_tests(ac_id, task_data, evidence_data):
    """获取项目中现有的测试模式参考"""
    test_refs = []
    for task in task_data.get("tasks", []):
        for ac in task.get("related_acs", []):
            if ac == ac_id:
                test_refs.extend(task.get("test_refs", []))
    # 如果没有直接测试，找同文件的其他测试作为风格参考
    if not test_refs:
        # 从 evidence_data 中找同模块的测试
        pass
    return test_refs[:2]  # 最多返回 2 个参考


def _derive_test_scenarios(ac_text, related_code):
    """根据 AC 描述和代码推导测试场景"""
    scenarios = []
    # 简单的关键字匹配推导
    if "无效" in ac_text or "错误" in ac_text or "invalid" in ac_text.lower():
        scenarios.append("无效输入 → 应输出错误提示并退出")
    if "空" in ac_text or "empty" in ac_text.lower():
        scenarios.append("空输入 → 应有明确的错误提示")
    if "正常" in ac_text or "valid" in ac_text.lower():
        scenarios.append("有效输入 → 应正常处理")
    if not scenarios:
        scenarios.append("根据 AC 描述推导具体测试场景")
    return scenarios


def _render_actions(lines, actions):
    """渲染行动清单为可读文本"""
    for i, action in enumerate(actions, 1):
        lines.append(f"{'=' * 70}")
        lines.append(f"ACTION {i} [{action['priority']}] {action['title']}")
        lines.append(f"{'=' * 70}")
        lines.append("")

        ctx = action.get("context", {})
        for key, value in ctx.items():
            if isinstance(value, list):
                lines.append(f"{key}:")
                for item in value:
                    if isinstance(item, dict):
                        lines.append(f"  {item.get('path', '')}: {item.get('content', '')[:200]}")
                    else:
                        lines.append(f"  - {item}")
            else:
                lines.append(f"{key}: {value}")
        lines.append("")

    return "\n".join(lines)
```

### 3.6 Agent 视图与人类视图的关系

两个视图**不是分离的两套系统，而是同一个数据管道的两个输出**：

```
                    vt analyze
                        │
            ┌───────────┴───────────┐
            ↓                       ↓
      Agent 输出                  报告文件
   (action list)           (traceability_report.json)
   (stdout, 精简)          (完整数据)
            │                       │
            ↓                       ↓
    Agent 执行行动            Dashboard 渲染
    (代码/测试/修复)         (人类决策页面)
            │                 (业务语言翻译)
            ↓                       │
      vt analyze                    ↓
      (再次运行)              人类点击按钮
            │                 (human_decisions.json)
            └───────────┬───────────┘
                        ↓
                  下一轮分析
              （人类决策已生效）
```

---

## 四、两步走策略

### 第一步：Dashboard 决策请求展示 + Agent 行动清单（低成本验证）

**目标**：
- 人类能在 dashboard 上看到所有待决策项，用业务语言理解每个决策
- Agent 能从 `vt analyze` 获得明确的行动清单

**改动范围**：
- Dashboard 模板：新增"待决策"标签页，业务语言翻译
- `cli.py`：`vt analyze` stdout 改为行动清单格式
- `architecture_compliance_checker.py`：accepted_rules 收集
- 无新依赖、无后端

### 第二步：交互式 Dashboard + 决策日志（完整实现）

**目标**：人类在页面上点击决策按钮，决策写入 `human_decisions.json`，Agent 读取并自动调整。

**改动范围**：
- 新增 `.vibetracing/human_decisions.json` 数据结构
- 新增 `decision_server.py` Flask 服务（约 100 行）
- `cli.py` 读取决策日志并应用到报告
- Dashboard 交互按钮

---

## 五、第一步详细设计

### 5.1 决策项呈现规范

每个决策项必须遵循统一的呈现结构：

```
┌───────────────────────────────────────────────────────────────────┐
│ [状态图标] DEC-XXX: 决策标题（业务语言）                            │
│ ├─ 当前状态：简洁描述                                              │
│ ├─ 需要您判断：明确的问题                                          │
│ ├─ [决策按钮1] [决策按钮2]                                         │
│ │                                                                  │
│ └─ ▶ 查看证据链（默认折叠）                                        │
│     ┌─────────────────────────────────────────────────────────┐   │
│     │ 证据链（逻辑化呈现，从需求到当前状态的完整链路）             │   │
│     │                                                           │   │
│     │ 需求 REQ-001 "用户能够执行一致性分析"                       │   │
│     │   └→ 设计 AC-003 "错误输入能给出提示"                      │   │
│     │       └→ 任务 TASK-VT-001 "实现命令行解析"                 │   │
│     │           └→ 代码 cli.py:445 (已实现)                      │   │
│     │               └→ 测试 ✗ 未找到测试                         │   │
│     │                                                           │   │
│     │ 门禁判断：GATE-VT-004 "MUST 级 AC 必须有测试" → 未通过     │   │
│     │ 关联文件：src/vibe_tracing/cli.py:445                      │   │
│     └─────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────┘
```

**设计原则**：
- **ID 必须可见**：每个决策项有唯一 ID（DEC-XXX），便于人类与 Agent 沟通时引用
- **默认折叠证据链**：人类第一眼看到的是"需要我判断什么"，不是技术细节
- **证据链可展开**：点击"查看证据链"后，展示从需求到当前状态的完整逻辑链路
- **证据链是逻辑化的**：不是原始数据，而是人类能理解的因果关系链

### 5.2 Dashboard "待决策"标签页

从现有数据中提取待决策事项，按分类展示：

#### A. 已确认规则的重新审视

**来源**：`accepted_rules`（措施 1 代码改动后可用）

**页面呈现**：
```
┌───────────────────────────────────────────────────────────────────┐
│ [!] DEC-001: "功能必须有测试"规则已过期                             │
│ ├─ 状态：2026-06-01 确认，已超过 30 天未重新确认                    │
│ ├─ 需要您判断：这个规则仍然有效吗？                                 │
│ ├─ [仍然有效] [不再适用]                                            │
│ │                                                                   │
│ └─ ▶ 查看证据链                                                     │
│     ┌─────────────────────────────────────────────────────────┐    │
│     │ 规则来源：GATE-VT-004                                     │    │
│     │ 规则内容：MUST 级别的验收标准必须有对应的测试覆盖           │    │
│     │ 上次确认：2026-06-01 by human                              │    │
│     │ 过期原因：确认时间超过 30 天阈值                            │    │
│     │ 影响范围：当前有 3 个 MUST 级 AC 依赖此规则                 │    │
│     └─────────────────────────────────────────────────────────┘    │
│                                                                     │
│ [✓] DEC-002: "输入文件必须格式正确"规则有效                          │
│ ├─ 状态：2026-06-08 确认，有效                                      │
│ └─ ▶ 查看证据链                                                     │
└───────────────────────────────────────────────────────────────────┘
```

#### B. 未覆盖的验收标准

**来源**：`gaps` 中 `item_type == "ac"` 的条目

**页面呈现**：
```
┌───────────────────────────────────────────────────────────────────┐
│ ✗ DEC-003: "错误输入提示"功能没有测试保障                           │
│ ├─ 关联需求：REQ-001 "用户能够执行一致性分析"                       │
│ ├─ 当前状态：有代码实现，但没有测试                                  │
│ ├─ 需要您判断：这个功能需要补充测试吗？                              │
│ ├─ [需要补充] [当前可接受]                                           │
│ │                                                                    │
│ └─ ▶ 查看证据链                                                      │
│     ┌─────────────────────────────────────────────────────────┐     │
│     │ 需求 REQ-001 "用户能够执行一致性分析"                       │     │
│     │   └→ 验收标准 AC-003 "错误输入能给出提示"                   │     │
│     │       ├→ 任务 TASK-VT-001 "实现命令行解析"                  │     │
│     │       │   └→ 代码声明 CLAIM-001 (已创建)                    │     │
│     │       │       └→ 代码 src/vibe_tracing/cli.py:445 (已实现)  │     │
│     │       └→ 测试 ✗ 未找到覆盖 AC-003 的测试                    │     │
│     │                                                           │     │
│     │ 门禁判断：GATE-VT-004 "MUST 级 AC 必须有测试" → 未通过     │     │
│     │ 原因：AC-003 是 MUST 级别但无测试覆盖                       │     │
│     └─────────────────────────────────────────────────────────┘     │
└───────────────────────────────────────────────────────────────────┘
```

#### C. 工具盲区

**来源**：`evidence_index.json` 中 status=skipped 的条目

**页面呈现**：
```
┌───────────────────────────────────────────────────────────────────┐
│ ⚠ DEC-004: src/config.py 无法自动检查                              │
│ ├─ 原因：检查工具运行了，但没有找到测试                              │
│ ├─ 需要您判断：此文件是否需要补充测试？                              │
│ ├─ [需要] [不需要] [不确定]                                         │
│ │                                                                   │
│ └─ ▶ 查看证据链                                                     │
│     ┌─────────────────────────────────────────────────────────┐    │
│     │ 工具：pytest                                              │    │
│     │ 执行命令：pytest src/config.py                            │    │
│     │ 退出码：5 (no tests collected)                            │    │
│     │ 含义：pytest 检查了此文件，但文件中没有测试函数             │    │
│     │ 可能原因：                                                │    │
│     │   1. 此文件是纯配置，不需要测试                            │    │
│     │   2. 测试被遗漏，需要补充                                  │    │
│     │ 关联声明：此文件未被任何 claim 的 test_refs 引用            │    │
│     └─────────────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────────────┘
```

#### D. 预存债务

**来源**：`risks` 中 `stale: true` 的条目

**页面呈现**：
```
┌───────────────────────────────────────────────────────────────────┐
│ ⚠ DEC-005: config.py 缺少输入检查（预存问题）                       │
│ ├─ 风险：如果输入格式错误，程序可能崩溃                              │
│ ├─ 已存在：3 个迭代                                                │
│ ├─ 需要您判断：这次要处理吗？                                       │
│ ├─ [本次处理] [继续延后]                                            │
│ │                                                                   │
│ └─ ▶ 查看证据链                                                     │
│     ┌─────────────────────────────────────────────────────────┐    │
│     │ 风险来源：CLAIM-005 "config 模块需要输入验证"              │    │
│     │ 识别时间：3 个迭代前                                       │    │
│     │ 当前状态：文件未变更，风险仍存在                            │    │
│     │ 影响范围：所有使用 config 的模块                            │    │
│     │ 未处理原因：每次迭代都因文件未变更而被标记为 stale           │    │
│     └─────────────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────────────┘
```

#### E. 任务完成确认

**来源**：`task_list.json` 中 status=done 的 task + 关联 evidence

**页面呈现**：
```
┌───────────────────────────────────────────────────────────────────┐
│ ✓ DEC-006: 任务"实现命令行解析功能"等待确认                         │
│ ├─ 关联需求：REQ-001 "用户能够执行一致性分析"                       │
│ ├─ 完成情况：代码 ✓ | 测试 ✓ | 设计约束 ✓                          │
│ ├─ 可以标记为完成吗？ [确认完成] [需要补充]                          │
│ │                                                                   │
│ └─ ▶ 查看证据链                                                     │
│     ┌─────────────────────────────────────────────────────────┐    │
│     │ 需求 REQ-001 "用户能够执行一致性分析"                       │    │
│     │   └→ 任务 TASK-VT-001 "实现命令行解析"                      │    │
│     │       ├→ 代码声明 CLAIM-001                                │    │
│     │       │   ├→ src/vibe_tracing/cli.py:445 (已实现)           │    │
│     │       │   ├→ src/vibe_tracing/arg_parser.py:12 (已实现)     │    │
│     │       │   └→ src/vibe_tracing/config.py:5 (已实现)          │    │
│     │       └→ 测试                                             │    │
│     │           ├→ tests/test_cli.py (15 个测试通过)              │    │
│     │           └→ tests/test_arg_parser.py (8 个测试通过)        │    │
│     │                                                           │    │
│     │ 门禁检查：                                                  │    │
│     │   ✓ GATE-VT-002 输入格式正确                               │    │
│     │   ✓ GATE-VT-004 AC 有测试覆盖                              │    │
│     │   ✓ GATE-VT-005 声明与代码一致                              │    │
│     └─────────────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────────────┘
```

### 5.3 证据链的数据来源

每个决策项的证据链从 VT 已有数据中提取并逻辑化：

| 决策类型 | 证据链数据来源 | 逻辑化方式 |
|---|---|---|
| 已确认规则 | `accepted_rules` + `architecture_constraints.json` | 规则内容 → 确认历史 → 影响范围 |
| 未覆盖 AC | `gaps` + `requirement_coverage` + `task_list` | 需求 → AC → 任务 → 代码 → 测试缺口 |
| 工具盲区 | `evidence_index.json` skipped 条目 | 工具 → 执行结果 → 可能原因 |
| 预存债务 | `risks` stale 条目 + 关联 claim | 风险来源 → 识别时间 → 未处理原因 |
| 任务确认 | `task_list` + `claims` + `evidence` | 需求 → 任务 → 代码声明 → 测试结果 |

### 5.4 Agent 行动清单

`vt analyze` stdout 改为行动清单格式（详见第三节 3.5）。

### 5.5 数据提取逻辑

```javascript
// 决策项 ID 生成（基于 target_id 的稳定哈希，确保跨运行一致）
function generateDecisionId(category, targetId) {
    // 简单哈希：category + targetId 的组合，确保同一决策项始终有相同 ID
    const key = `${category}:${targetId}`;
    let hash = 0;
    for (let i = 0; i < key.length; i++) {
        hash = ((hash << 5) - hash) + key.charCodeAt(i);
        hash |= 0;
    }
    return `DEC-${Math.abs(hash).toString(16).padStart(4, '0').slice(0, 4).toUpperCase()}`;
}

function extractPendingDecisions(report, evidenceIndex, taskList, requirementCoverage) {
    const decisions = [];

    // A. 已确认规则
    if (report.accepted_rules) {
        for (const rule of report.accepted_rules) {
            const isStale = rule.stale_acceptance;
            decisions.push({
                id: generateDecisionId("accepted_rule", rule.rule_id),
                category: "accepted_rule",
                title: `"${rule.title}"规则${isStale ? '已过期' : '有效'}`,
                rule_id: rule.rule_id,
                status: isStale ? "expired" : "valid",
                question: isStale ? "这个规则仍然有效吗？" : "这个规则需要重新审视吗？",
                actions: isStale ? ["仍然有效", "不再适用"] : [],
                evidence_chain: buildAcceptedRuleChain(rule),
            });
        }
    }

    // B. 未覆盖的验收标准
    if (report.gaps) {
        for (const gap of report.gaps) {
            if (gap.item_type === "ac" && !gap.stale && !gap.human_accepted) {
                decisions.push({
                    id: generateDecisionId("uncovered_ac", gap.item_id),
                    category: "uncovered_ac",
                    title: `"${gap.title || gap.item_id}"功能没有测试保障`,
                    target_id: gap.item_id,
                    status: "uncovered",
                    question: "这个功能需要补充测试吗？",
                    actions: ["需要补充", "当前可接受"],
                    evidence_chain: buildAcGapChain(gap, requirementCoverage),
                });
            }
        }
    }

    // C. 工具盲区
    if (evidenceIndex && evidenceIndex.evidences) {
        for (const ev of evidenceIndex.evidences) {
            if (ev.status === "skipped") {
                decisions.push({
                    id: generateDecisionId("tool_blind_spot", ev.source_path),
                    category: "tool_blind_spot",
                    title: `${ev.source_path} 无法自动检查`,
                    target_id: ev.source_path,
                    status: "skipped",
                    question: "这个文件是否需要补充测试？",
                    actions: ["需要", "不需要", "不确定"],
                    evidence_chain: buildToolBlindSpotChain(ev),
                });
            }
        }
    }

    // D. 预存债务
    if (report.risks) {
        for (const risk of report.risks) {
            if (risk.stale && !risk.deferred) {
                decisions.push({
                    id: generateDecisionId("stale_debt", risk.claim_id || "unknown"),
                    category: "stale_debt",
                    title: `${risk.title || risk.description || '未知风险'}（预存问题）`,
                    target_id: risk.claim_id,
                    status: "stale",
                    question: "这次要处理吗？",
                    actions: ["本次处理", "继续延后"],
                    evidence_chain: buildStaleDebtChain(risk),
                });
            }
        }
    }

    // E. 任务完成确认
    if (taskList) {
        for (const task of taskList) {
            if (task.status === "done") {
                const alreadyDecided = decisions.some(d =>
                    d.category === "task_confirm" && d.target_id === task.task_id
                );
                if (!alreadyDecided) {
                    decisions.push({
                        id: generateDecisionId("task_confirm", task.task_id),
                        category: "task_confirm",
                        title: `任务"${task.title}"等待确认`,
                        target_id: task.task_id,
                        status: "awaiting_confirm",
                        question: "可以标记为完成吗？",
                        actions: ["确认完成", "需要补充"],
                        evidence_chain: buildTaskConfirmChain(task, requirementCoverage),
                    });
                }
            }
        }
    }

    return decisions;
}

// ─── 证据链构建函数 ───

function buildAcceptedRuleChain(rule) {
    return [
        { type: "rule", label: "规则来源", value: rule.rule_id },
        { type: "content", label: "规则内容", value: rule.title },
        { type: "history", label: "上次确认", value: `${rule.accepted_at} by ${rule.accepted_by}` },
        { type: "reason", label: rule.stale_acceptance ? "过期原因" : "状态", value: rule.stale_acceptance ? "确认时间超过 30 天阈值" : "有效期内" },
    ];
}

function buildAcGapChain(gap, requirementCoverage) {
    const chain = [];
    const reqId = gap.requirement_id || findParentRequirement(gap.item_id, requirementCoverage);
    if (reqId) {
        chain.push({ type: "requirement", label: "需求", value: `${reqId} ${getRequirementTitle(reqId, requirementCoverage)}` });
    }
    chain.push({ type: "ac", label: "验收标准", value: `${gap.item_id} ${gap.title || ''}` });
    if (gap.related_tasks) {
        for (const taskId of gap.related_tasks) {
            chain.push({ type: "task", label: "任务", value: taskId });
        }
    }
    chain.push({ type: "test", label: "测试", value: "未找到覆盖此 AC 的测试", status: "fail" });
    chain.push({ type: "gate", label: "门禁判断", value: "GATE-VT-004 MUST 级 AC 必须有测试 → 未通过" });
    return chain;
}

function buildToolBlindSpotChain(evidence) {
    const skipReason = evidence.details?.skip_reason || "未知原因";
    const exitCode = evidence.details?.exit_code || "";
    return [
        { type: "tool", label: "工具", value: evidence.tool_name || "pytest" },
        { type: "execution", label: "执行命令", value: evidence.command || `pytest ${evidence.source_path}` },
        { type: "result", label: "退出码", value: `${exitCode} (${skipReason})` },
        { type: "meaning", label: "含义", value: skipReason === "no tests collected" ? "pytest 检查了此文件，但文件中没有测试函数" : skipReason },
        { type: "possibility", label: "可能原因", value: "1. 此文件是纯配置，不需要测试  2. 测试被遗漏，需要补充" },
    ];
}

function buildStaleDebtChain(risk) {
    return [
        { type: "source", label: "风险来源", value: risk.claim_id || "未知" },
        { type: "description", label: "风险描述", value: risk.title || risk.description || "" },
        { type: "age", label: "已存在", value: `${risk.age_iterations || '多个'} 个迭代` },
        { type: "status", label: "当前状态", value: "文件未变更，风险仍存在" },
        { type: "reason", label: "未处理原因", value: "每次迭代都因文件未变更而被标记为预存" },
    ];
}

function buildTaskConfirmChain(task, requirementCoverage) {
    const chain = [];
    const reqId = task.related_requirement || findParentRequirement(task.task_id, requirementCoverage);
    if (reqId) {
        chain.push({ type: "requirement", label: "需求", value: `${reqId} ${getRequirementTitle(reqId, requirementCoverage)}` });
    }
    chain.push({ type: "task", label: "任务", value: `${task.task_id} "${task.title}"` });
    if (task.related_claims) {
        for (const claimId of task.related_claims) {
            chain.push({ type: "claim", label: "代码声明", value: claimId });
        }
    }
    if (task.code_refs) {
        for (const ref of task.code_refs) {
            chain.push({ type: "code", label: "代码", value: `${ref} (已实现)` });
        }
    }
    if (task.test_refs) {
        for (const ref of task.test_refs) {
            chain.push({ type: "test", label: "测试", value: `${ref} (通过)`, status: "pass" });
        }
    }
    return chain;
}
```

---

## 六、第二步详细设计

### 6.1 架构设计

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Dashboard  │────→│  Decision API    │────→│ human_decisions │
│  (HTML/JS)   │←────│  (Flask/FastAPI) │←────│     .json       │
└──────────────┘     └──────────────────┘     └────────┬────────┘
                                                       │
                                                       ↓
                                              ┌─────────────────┐
                                              │  vt analyze     │
                                              │  (读取决策日志)  │
                                              └─────────────────┘
                                                       │
                                                       ↓
                                              ┌─────────────────┐
                                              │  Agent 行动清单  │
                                              │  (已决策项排除)  │
                                              └─────────────────┘
```

### 6.2 决策日志数据结构

**`.vibetracing/human_decisions.json`**：

```json
{
    "version": "1.0",
    "decisions": [
        {
            "decision_id": "DEC-001",
            "timestamp": "2026-06-08T14:30:00Z",
            "category": "accepted_rule",
            "target_id": "GATE-VT-004",
            "action": "reconfirm",
            "reason": "此规则仍然有效",
            "decided_by": "product_owner"
        },
        {
            "decision_id": "DEC-002",
            "timestamp": "2026-06-08T14:31:00Z",
            "category": "uncovered_ac",
            "target_id": "AC-003",
            "action": "accept_gap",
            "reason": "此功能在当前迭代不需要测试",
            "decided_by": "product_owner"
        },
        {
            "decision_id": "DEC-003",
            "timestamp": "2026-06-08T14:32:00Z",
            "category": "stale_debt",
            "target_id": "CLAIM-005",
            "action": "defer",
            "reason": "此问题可在下个迭代处理",
            "decided_by": "product_owner"
        }
    ]
}
```

**决策动作枚举**：

| action | 含义 | 对 Agent 的影响 |
|---|---|---|
| `reconfirm` | 重新确认规则仍然有效 | 更新 `accepted_at`，重置过期计时 |
| `reject` | 拒绝/撤回确认 | 移除 `accepted_by`，规则重新进入门禁检查 |
| `accept_gap` | 接受此缺口 | gap 标记为"已知晓"，不阻断门禁 |
| `defer` | 延后处理 | 标记为延后，下个迭代重新出现 |
| `request_action` | 要求 Agent 处理 | Agent 在下次 analyze 时优先处理此项 |

### 6.3 Decision API

**最小 API**（3 个端点）：

```
GET  /api/decisions              # 获取所有决策记录
POST /api/decisions              # 提交新决策
GET  /api/pending                # 获取待决策事项
```

**实现**：Flask 最小应用，约 100 行代码。写入 `.vibetracing/human_decisions.json`，无需数据库。

### 6.4 Agent 读取决策日志

```python
def _load_human_decisions() -> Dict:
    decisions_path = Path(".vibetracing/human_decisions.json")
    if not decisions_path.exists():
        return {"version": "1.0", "decisions": []}
    return json.loads(decisions_path.read_text())

def _apply_decisions(report_doc: Dict, decisions: Dict) -> Dict:
    """将人类决策应用到报告中"""
    for decision in decisions.get("decisions", []):
        category = decision.get("category")
        target_id = decision.get("target_id")
        action = decision.get("action")

        if category == "accepted_rule" and action == "reconfirm":
            for rule in report_doc.get("accepted_rules", []):
                if rule.get("rule_id") == target_id:
                    rule["accepted_at"] = decision["timestamp"]
                    rule["stale_acceptance"] = False

        elif category == "uncovered_ac" and action == "accept_gap":
            for gap in report_doc.get("gaps", []):
                if gap.get("item_id") == target_id:
                    gap["human_accepted"] = True

        elif category == "stale_debt" and action == "defer":
            for risk in report_doc.get("risks", []):
                if risk.get("claim_id") == target_id:
                    risk["deferred"] = True

        elif category == "accepted_rule" and action == "reject":
            # 需要通过 vt accept --revoke 命令处理
            pass

    return report_doc
```

---

## 七、噪音消除措施的具体技术改进

以下措施作为技术基础，需要先完成。

### 7.1 措施 1+2：`accepted_by` 可见化

**`architecture_compliance_checker.py:700-728`**：

```python
if verification == "manual":
    accepted_by = rule.get("accepted_by")
    if accepted_by:
        accepted_at = rule.get("accepted_at", "")
        is_stale = _is_stale_acceptance(accepted_at, threshold_days=30)
        accepted_rules.append({
            "rule_id": r_id,
            "title": rule.get("title", ""),
            "severity": severity,
            "verification_method": "manual",
            "accepted_by": accepted_by,
            "accepted_at": accepted_at,
            "stale_acceptance": is_stale,
        })
        continue
```

**修复注释/代码矛盾**（`:710-728`）：删除 `:723-728` 的 `unclear_list.append` 代码块。

**新增辅助函数**：

```python
def _is_stale_acceptance(accepted_at: str, threshold_days: int = 30) -> bool:
    if not accepted_at:
        return False
    try:
        accepted_time = datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - accepted_time).days > threshold_days
    except (ValueError, TypeError):
        return False
```

**门禁重分类**（Phase 2）：

| 门禁 | 当前 | 已有分析器覆盖 | 建议 |
|---|---|---|---|
| GATE-VT-002~005, 008, 010, 011 | manual | 各有对应分析器 | 改为 machine |
| GATE-VT-009 | manual | 无 | 保持 manual |
| GATE-VT-012 | manual | 设计约束 | 保持 manual |

### 7.2 措施 3：Exit Code 5/2 产生 `skipped` 证据

**`core/enums.py`**：新增 `CoverageStatus.SKIPPED`、`ErrorCode.TOOL_NO_TESTS_COLLECTED`、`ErrorCode.TOOL_USAGE_ERROR`。

**`tool_evidence_adapter.py:251-253`**：`return []` 改为返回 status=skipped 的候选。

**`schemas/evidence_index.schema.json`**：status enum 加入 `"skipped"`。

### 7.3 措施 4：Stale 呈现优化

**Dashboard**：Risks & Gaps 标签页增加"显示预存债务"toggle，stale 项半透明 + `[预存]` 标签。

**`cli.py:1130`** 附近：stale 项存在时打印 stderr WARNING。

### 7.4 措施 5：非代码文件产生 `skipped` 证据

**`cli.py:904-914`** 附近：过滤后路径生成 skipped 候选，复用措施 3 的枚举。

---

## 八、跨切面决策

| 决策项 | 结论 | 理由 |
|---|---|---|
| VT 定位 | 决策平台（双核心用户） | Agent 需要行动清单，人类需要决策按钮 |
| 人类视图 | 业务语言翻译 | 不展示技术术语，用"做到了/没做到" |
| Agent 视图 | 行动清单（非统计摘要） | Agent 需要知道"下一步做什么" |
| Decision API | Flask 最小应用 | 3 个端点，约 100 行，无数据库 |
| 决策存储 | `human_decisions.json` | 与现有契约文件体系一致 |
| Agent 读取决策 | analyze 流程前置步骤 | 决策先于分析，已决策项自动排除 |
| `accepted_by` 过期 | 30 天默认 + 可配置 | stale 不阻断门禁，仅触发决策请求 |

---

## 九、实施顺序

```
Phase 0: Schema 更新
  └─ evidence_index.schema.json 加 "skipped" status

Phase 1: 技术基础（措施 1+3 的代码改动）
  ├─ architecture_compliance_checker.py accepted_rules 收集
  ├─ core/enums.py SKIPPED 枚举
  ├─ tool_evidence_adapter.py skipped 候选
  └─ cli.py 报告组装

Phase 2: 第一步 — Agent 行动清单 + Dashboard 决策展示
  ├─ cli.py vt analyze stdout 改为行动清单格式
  ├─ dashboard.template.html "待决策"标签页（业务语言翻译）
  └─ 数据提取逻辑（从 report + evidence 中提取待决策项）

Phase 3: 措施 4+5（stale 呈现 + 非代码文件 skipped）
  ├─ dashboard stale toggle + 样式
  ├─ cli.py 非代码文件 skipped 候选
  └─ tool_execution_warnings 报告字段

Phase 4: 第二步 — 交互式 Dashboard
  ├─ .vibetracing/human_decisions.json 数据结构
  ├─ decision_server.py Flask 服务
  ├─ cli.py 读取决策日志 + 应用到报告
  └─ dashboard 交互按钮 + 决策提交
```

---

## 十、关键文件索引

| 文件 | 涉及阶段 | 作用 |
|---|---|---|
| `src/vibe_tracing/architecture_compliance_checker.py` | Phase 1 | accepted_rules 收集 |
| `src/vibe_tracing/tool_evidence_adapter.py` | Phase 1 | skipped 候选生成 |
| `src/vibe_tracing/core/enums.py` | Phase 1 | SKIPPED 枚举 |
| `src/vibe_tracing/cli.py` | Phase 1, 2, 3, 4 | 报告组装、Agent 行动清单、决策应用 |
| `src/vibe_tracing/templates/dashboard.template.html` | Phase 2, 3, 4 | 决策展示（业务语言）、交互按钮 |
| `src/vibe_tracing/schemas/evidence_index.schema.json` | Phase 0 | status enum |
| `.vibetracing/human_decisions.json` | Phase 4 | 决策日志（新增） |
| `decision_server.py` | Phase 4 | Decision API（新增） |

---

## 十一、原子化任务列表

### 设计原则

- **单文件隔离**：每个任务只修改一个文件，避免 subagent 交叉编辑
- **依赖显式化**：每个任务标明前置依赖，无依赖的任务可并行
- **粒度控制**：每个任务 100-300 行代码改动，subagent 10-20 分钟可完成
- **验收明确**：每个任务有具体的验收标准（测试命令或检查方式）

### 文件冲突矩阵

| 文件 | Phase 0 | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|---|---|---|---|---|---|
| `evidence_index.schema.json` | **T1** | | | | |
| `core/enums.py` | | **T2** | | | |
| `architecture_compliance_checker.py` | | **T3** | | | |
| `tool_evidence_adapter.py` | | **T4** | | | |
| `cli.py` | | **T5** | **T7** | **T9** | **T12** |
| `dashboard.template.html` | | | **T8** | **T10** | **T13** |
| `decision_server.py` | | | | | **T11** |
| `tests/test_*.py` | | **T6** | | | |

> 规则：同一列（同一 Phase）中，不同任务修改不同文件，可并行。
> 同一文件的不同任务（跨 Phase）必须串行：T5 → T7 → T9 → T12，T8 → T10 → T13。

---

### Phase 0：Schema 更新

#### T1 — evidence_index.schema.json 加入 "skipped" status

- **前置依赖**：无
- **修改文件**：`src/vibe_tracing/schemas/evidence_index.schema.json`
- **改动内容**：在 `status` enum 中加入 `"skipped"` 值
- **验收标准**：`python -c "import json; s=json.load(open('src/vibe_tracing/schemas/evidence_index.schema.json')); assert 'skipped' in s['properties']['evidences']['items']['properties']['status']['enum']"`
- **可并行**：是（无依赖）

---

### Phase 1：技术基础

#### T2 — core/enums.py 新增枚举值

- **前置依赖**：T1（schema 一致性）
- **修改文件**：`src/vibe_tracing/core/enums.py`
- **改动内容**：
  - `CoverageStatus` 新增 `SKIPPED = "skipped"`
  - `ErrorCode` 新增 `TOOL_NO_TESTS_COLLECTED = "tool_no_tests_collected"` 和 `TOOL_USAGE_ERROR = "tool_usage_error"`
- **验收标准**：`python -c "from vibe_tracing.core.enums import CoverageStatus, ErrorCode; assert CoverageStatus.SKIPPED.value == 'skipped'"`
- **可并行**：是（与 T3, T4 并行）

#### T3 — architecture_compliance_checker.py accepted_rules 收集

- **前置依赖**：无
- **修改文件**：`src/vibe_tracing/architecture_compliance_checker.py`
- **改动内容**：
  1. 在 `check()` 方法中新增 `accepted_rules: List[Dict] = []`
  2. 替换 `:702-707` 的 `continue` 逻辑，改为收集到 `accepted_rules`
  3. 修复 `:710-728` 的注释/代码矛盾（删除 `:723-728` 的 `unclear_list.append`）
  4. 新增 `_is_stale_acceptance()` 辅助函数
  5. 返回值 dict 新增 `"accepted_rules"` 键
- **验收标准**：现有测试 `pytest tests/test_architecture_compliance_checker.py -v` 全部通过 + 新增测试验证 accepted_rules 输出
- **可并行**：是（与 T2, T4 并行）

#### T4 — tool_evidence_adapter.py skipped 候选生成

- **前置依赖**：T2（需要 `CoverageStatus.SKIPPED` 和 `ErrorCode` 枚举）
- **修改文件**：`src/vibe_tracing/tool_evidence_adapter.py`
- **改动内容**：
  1. `_parse_pytest_output` 中 `:251-253`：`return []` 改为返回 status=skipped 的候选
  2. `_parse_mypy_output` 中 `:504-506`：同上
  3. 从 `core.enums` 导入 `CoverageStatus`, `ErrorCode`
- **验收标准**：新增测试验证 pytest exit 5 返回 skipped 候选而非空列表
- **可并行**：是（与 T2, T3 并行，但技术上依赖 T2 的枚举值）

#### T5 — cli.py 报告组装扩展

- **前置依赖**：T3（需要 `accepted_rules` 字段）
- **修改文件**：`src/vibe_tracing/cli.py`
- **改动内容**：
  1. `_evaluate_and_output()` 中 `:1231-1247`：`report_doc` 新增 `"accepted_rules"` 字段
  2. `run_analyze()` 中 `:954-955`：新增 `skipped_count` 统计和打印
- **验收标准**：`vt analyze` 运行后 `traceability_report.json` 包含 `accepted_rules` 字段
- **可并行**：否（后续 Phase 依赖此改动）

#### T6 — 补充 accepted_rules 和 skipped 的单元测试

- **前置依赖**：T3, T4
- **修改文件**：`tests/test_architecture_compliance_checker.py`, `tests/test_tool_evidence_adapter.py`
- **改动内容**：
  1. 测试 accepted_by 规则被收集到 accepted_rules（而非静默跳过）
  2. 测试 stale acceptance 逻辑
  3. 测试 pytest exit 5 返回 skipped 候选
  4. 测试注释/代码矛盾修复（未确认的 manual 规则不进入 unclear_list）
- **验收标准**：`pytest tests/test_architecture_compliance_checker.py tests/test_tool_evidence_adapter.py -v` 全部通过
- **可并行**：否（依赖 T3, T4 完成）

---

### Phase 2：Agent 行动清单 + Dashboard 决策展示

#### T7 — cli.py Agent 行动清单格式化

- **前置依赖**：T5（报告组装扩展）
- **修改文件**：`src/vibe_tracing/cli.py`
- **改动内容**：
  1. 新增 `_format_agent_actions()` 函数（含 `_get_ac_description`, `_get_related_code`, `_get_existing_tests`, `_derive_test_scenarios`, `_render_actions` 辅助函数）
  2. `run_analyze()` 末尾调用 `_format_agent_actions()` 输出到 stdout
  3. 数据来源：`ctx.prd`（PRD 解析结果）、`ctx.task_result`（任务列表）、`ctx.tool_evidence`（工具证据）
- **验收标准**：`vt analyze` stdout 输出包含 `GATE DECISION:` 和 `ACTION` 格式的行动清单
- **可并行**：否（后续 T8 依赖此数据结构）

#### T8 — dashboard.template.html "待决策"标签页

- **前置依赖**：T7（需要理解行动清单数据结构）
- **修改文件**：`src/vibe_tracing/templates/dashboard.template.html`
- **改动内容**：
  1. 新增"待决策"标签页（与 Overview, Requirements, Architecture, Risks, Evidence 并列）
  2. 嵌入 `extractPendingDecisions()` JavaScript 函数（含 `generateDecisionId`, `buildAcceptedRuleChain`, `buildAcGapChain`, `buildToolBlindSpotChain`, `buildStaleDebtChain`, `buildTaskConfirmChain`）
  3. 渲染决策卡片：ID + 业务语言标题 + 状态 + 问题 + 按钮 + 折叠证据链
  4. 从 `report` 和 `evidence_index` 内联数据中提取待决策项
- **验收标准**：打开 dashboard HTML，"待决策"标签页显示决策卡片（如有 accepted_rules 或 gaps）
- **可并行**：否

---

### Phase 3：Stale 呈现 + 非代码文件 skipped

#### T9 — cli.py stale WARNING + 非代码文件 skipped 候选

- **前置依赖**：T5
- **修改文件**：`src/vibe_tracing/cli.py`
- **改动内容**：
  1. `:1130` 附近：stale 项存在时打印 stderr WARNING
  2. `:904-914` 附近：过滤后路径生成 skipped 候选（复用 T2 的枚举）
  3. `report_doc` 新增 `"tool_execution_warnings"` 字段
- **验收标准**：stale 项存在时 stderr 有 WARNING；非代码文件引用产生 skipped 证据
- **可并行**：是（与 T10 并行，修改不同文件）

#### T10 — dashboard.template.html stale 呈现优化

- **前置依赖**：T8
- **修改文件**：`src/vibe_tracing/templates/dashboard.template.html`
- **改动内容**：
  1. Risks & Gaps 标签页增加"显示预存债务"toggle
  2. stale 项 CSS 样式（半透明 + 虚线边框 + `[预存]` 标签）
  3. Overview 标签页统计拆分："活动: X | 预存: Y"
  4. Evidence 标签页 status 筛选增加 "skipped" 选项
- **验收标准**：dashboard 中 stale 项可通过 toggle 显示/隐藏，skipped 证据有灰色标签
- **可并行**：是（与 T9 并行）

---

### Phase 4：交互式 Dashboard

#### T11 — decision_server.py Flask 服务

- **前置依赖**：无（新增文件，无冲突）
- **修改文件**：`decision_server.py`（新增）
- **改动内容**：
  1. Flask 最小应用，3 个端点：`GET /api/decisions`, `POST /api/decisions`, `GET /api/pending`
  2. 读写 `.vibetracing/human_decisions.json`
  3. CORS 支持（dashboard 是静态 HTML，需要跨域）
  4. `extractPendingDecisions()` 的 Python 实现（复用 T8 的逻辑）
- **验收标准**：`python decision_server.py` 启动后 `curl localhost:5000/api/decisions` 返回 JSON
- **可并行**：是（与 T12, T13 并行，但 T12, T13 依赖此服务可用）

#### T12 — cli.py 读取决策日志

- **前置依赖**：T5
- **修改文件**：`src/vibe_tracing/cli.py`
- **改动内容**：
  1. 新增 `_load_human_decisions()` 函数
  2. 新增 `_apply_decisions()` 函数
  3. `run_analyze()` 中在报告组装后调用 `_apply_decisions()`
  4. Agent 行动清单中引用 DEC-XXX ID
- **验收标准**：创建 `.vibetracing/human_decisions.json` 测试文件后，`vt analyze` 行动清单中待决策项被正确排除
- **可并行**：是（与 T11, T13 并行）

#### T13 — dashboard.template.html 交互按钮

- **前置依赖**：T8, T11
- **修改文件**：`src/vibe_tracing/templates/dashboard.template.html`
- **改动内容**：
  1. 每个决策卡片增加交互按钮（"仍然有效"/"不再适用"/"需要补充"/"当前可接受"等）
  2. 按钮点击后调用 `POST /api/decisions` 提交决策
  3. 提交后卡片标记为"已决策"，移出待决策列表
  4. 决策日志查看区域（显示历史决策）
- **验收标准**：dashboard 中点击决策按钮后，`.vibetracing/human_decisions.json` 被更新
- **可并行**：是（与 T11, T12 并行）

---

### 任务依赖图

```
T1 (schema)
 ├─→ T2 (enums) ──→ T4 (skipped candidates) ──→ T6 (tests)
 │                                                ↑
 └─→ T3 (accepted_rules) ─────────────────────────┘
      │
      └─→ T5 (report assembly)
           ├─→ T7 (agent action list) ──→ T8 (dashboard pending tab)
           │                                ├─→ T10 (dashboard stale)
           │                                └─→ T13 (dashboard interactive)
           ├─→ T9 (stale + non-code skipped)
           └─→ T12 (load decisions)
           
T11 (decision server) ──→ T13 (dashboard interactive)
```

### 执行调度建议

| 批次 | 任务 | 预计耗时 | 说明 |
|---|---|---|---|
| Batch 1 | T1 | 5 min | Schema 更新，无依赖 |
| Batch 2 | T2, T3 | 15 min | 并行，不同文件 |
| Batch 3 | T4, T5 | 20 min | T4 依赖 T2，T5 依赖 T3 |
| Batch 4 | T6 | 15 min | 测试补充，依赖 T3+T4 |
| Batch 5 | T7 | 20 min | Agent 行动清单，依赖 T5 |
| Batch 6 | T8, T9, T11 | 30 min | T8 依赖 T7，T9 依赖 T5，T11 无依赖，可并行 |
| Batch 7 | T10, T12, T13 | 30 min | T10 依赖 T8，T12 依赖 T5，T13 依赖 T8+T11，可并行 |

**总计**：约 135 分钟（不含测试验证时间）。Batch 2/3/6/7 内部可并行，实际墙钟时间约 90 分钟。
