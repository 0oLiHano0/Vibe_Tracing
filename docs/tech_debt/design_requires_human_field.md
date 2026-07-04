# 设计记录：DetectedIssue.requires_human 显式字段

**状态**：待排期（非 PHASE-VT-015 范围）
**创建**：2026-07-04
**来源**：PHASE-VT-015 review 中识别的遗留功能性问题
**关联**：
- `src/vibe_tracing/cli/analyze/actions.py::_is_human_decision`
- `docs/design_channel_separation.md`（架构级 channel 分离，优先于本条目）
- `docs/tech_debt/ux_action_output_issues.md`（同属 tech_debt 目录的兄弟条目）

---

## 1. 问题陈述

`_is_human_decision(issue)` 通过字符串前缀/子串匹配 issue_id 来判定"该 issue 是否需要人类决策"，与 engine.py 的 issue_id 构造规则形成隐式耦合。一旦 engine 重命名 issue_id 格式，action 层会静默失效，把治理类 issue 错当 Agent-fixable 处理，产出误导性修复 action。

**位置**：`src/vibe_tracing/cli/analyze/actions.py:115-123`

```python
def _is_human_decision(issue: DetectedIssue) -> bool:
    if issue.issue_type == "isolated_task":
        return True
    if issue.issue_id.startswith("chain_broken:proposal"):
        return True
    if ":unclear" in issue.issue_id:
        return True
    return False
```

## 2. 证据链

三条判定规则对应的 engine.py 产出点（耦合面 = 3 个检测器 / 5 个 issue_id 构造点）：

| `_is_human_decision` 规则 | engine.py 检测器 | 行号 | issue_id 示例 |
|---|---|---|---|
| `issue_type == "isolated_task"` | `_check_isolated_tasks` | 564 | `isolated_task:TASK-001` |
| `issue_id.startswith("chain_broken:proposal")` | `_check_proposal_governance`（proposal 分支） | 406 | `chain_broken:proposal:R-001` |
| 同上 | `_check_proposal_governance`（proposal_gap 分支） | 419 | `chain_broken:proposal_gap:G-001` |
| `":unclear" in issue_id` | `_check_unclear_constraints`（unclear 分支） | 497 | `substandard:unclear:R-002` |
| 同上 | `_check_unclear_constraints`（unclear_status 分支） | 515 | `substandard:unclear_status:R-003` |

## 3. 风险评估

| 风险 | 等级 | 说明 |
|---|---|---|
| **静默失效** | 高 | engine 重命名 issue_id（如 `chain_broken:proposal:X` → `governance:proposal_missing:X`）后，action 层不再识别，governance issue 被错误产出 `fix_chain_broken` action |
| **误匹配** | 中 | `:unclear` 子串匹配对未来命名脆弱（如 `no_claim:unclear_doc:X` 会被误判） |
| **可读性差** | 低 | 读者必须跳到 engine.py 才能明白为何 `chain_broken:proposal` 需人类决策 |

## 4. 方案对比

| 方案 | 改动量 | 显式度 | 可扩展性 | 推荐 |
|---|---|---|---|---|
| **A. `requires_human: bool` 字段** | 小（3 检测器 + actions + tests） | ★★★ | ★★ | **推荐** |
| B. `governance_class` 枚举 | 中（新建 Enum + 所有消费方更新） | ★★★ | ★★★ | 暂缓（YAGNI） |
| C. 领域层 policy 函数集中判定 | 小（1 新文件 + 替换 `_is_human_decision`） | ★★ | ★★ | 过渡方案 |
| D. 基于现有字段派生（不改数据类） | 小（仅改 `_is_human_decision`） | ★ | ★ | 不解决耦合 |

## 5. 推荐方案：A

### 5.1 数据模型改动

`src/vibe_tracing/domain/gate/types.py`：

```python
@dataclass(frozen=True)
class DetectedIssue:
    issue_id: str
    issue_type: str
    severity: Severity
    reason: str
    related_task_id: str
    gap_targets: List[str]
    item_id: str
    requires_human: bool = False   # 新增，默认 False（绝大多数 issue 为 Agent-fixable）
```

### 5.2 检测器标记

`src/vibe_tracing/domain/gate/engine.py` 三个检测器的 5 个分支各加 `requires_human=True`：

- `_check_proposal_governance`：`chain_broken:proposal:*` 与 `chain_broken:proposal_gap:*`
- `_check_unclear_constraints`：`substandard:unclear:*` 与 `substandard:unclear_status:*`
- `_check_isolated_tasks`：`isolated_task:*`

### 5.3 Action 层简化

`src/vibe_tracing/cli/analyze/actions.py`：

```python
def _is_human_decision(issue: DetectedIssue) -> bool:
    return issue.requires_human
```

### 5.4 边界考量

- **与 Severity 正交**：`Severity` 决定 gate 阻拦强度，`requires_human` 决定处置主体（人类 vs Agent）。proposal governance 可以是 BLOCK+human 或 WARNING+human。
- **SignalComputer 当前不消费**：仅算五元信号；未来若需影响 `accepted`/`resolved` 信号计算再单独扩展。
- **默认 False**：避免改动非人类决策的所有构造点。

## 6. 测试影响

- `tests/test_collect_issue_actions.py`：约 5-8 个涉及 human-decision 分类的 fixture 需加 `requires_human=True`。
- `tests/test_merge_gate_engine.py`：3 个检测器的 fixture 需加字段。
- 新增断言：`_check_proposal_governance` / `_check_unclear_constraints` / `_check_isolated_tasks` 产出 issue 的 `requires_human` 字段必须为 `True`。

## 7. 落地工作量

约 30 分钟。

## 8. 排期建议

- 可独立作为一个 TASK-VT-XXX（建议编号紧随当前 task_list.json 末位之后）。
- 不必绑定到特定 PHASE；属于"领域模型精度提升"类改进。
- 前置依赖：无；可与任何进行中的 PHASE 并行推进。
