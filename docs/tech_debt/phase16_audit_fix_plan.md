# PHASE-VT-016 一期 MVP 治理审查与修复方案

**审查日期**: 2026-07-04
**审查方法**: 4 个 subagent 并行审查 + 3 个 subagent 根因分析
**审查依据**: `docs/design_channel_separation.md` + `docs/business_task_reflection_trajectory.md`
**设计文档补完**: 本次审查发现 2 处设计文档缺口，已在 `docs/design_channel_separation.md` 中补完

---

## 1. 审查发现总览

| # | 严重度 | 问题 | 根因分类 | 设计文档状态 |
|---|---|---|---|---|
| H1 | 高 | acceptance_summary 计算值未回写 task_sessions.json | 设计文档歧义 | **已补完** §3.2.1 步骤 3 |
| ~~H2~~ | ~~中~~ | ~~traceability_report.json 缺 acceptance_summary key~~ | **误报（已撤销）** | 无需修改 |
| H3 | 高 | config.json 缺 model 字段 + schema_version 未升级 | 设计文档缺口 + 范围遗漏 | **已补完** §5.1 步骤 0 |
| M1 | 中 | 19 个 task phase_id "PHASE-VT-05" vs "PHASE-VT-005" | 数据质量 + schema 校验缺口 | 数据修复 |
| M2 | 中 | TASK-VT-192~198 status "todo" vs claim "completed" | 流程缺口（人工维护遗漏） | 纯数据修复 |
| ~~M3~~ | ~~中~~ | ~~task_list.json 缺 closed 布尔字段~~ | **设计决策驳回** | 不回写 task_list.json |
| M4 | 中 | ac_missing_evidence 缺 business_impact 标注 | 实现缺口（atomic_scope vs ai_coding_guidance 歧义） | 数据修复 |

---

## 2. 根因分析

### H1: acceptance_summary 回写断裂

**设计文档内部矛盾**：
- §3.3.2 schema 示例显示 acceptance_summary 全 6 字段有真实值
- §3.2.1 编排步骤只指定写 `delivery`，build_list 结果路由到 stdout
- 两者之间**缺少回写步骤**

**实际行为**：`session.py` update_sessions 写入 `AcceptanceSummary(delivery=...)` 仅填充 delivery，其余字段为默认零值。`AcceptanceSummaryBuilder.build_list()` 计算的 resolved_block/resolved_warning/remaining_warning/severe_risks/recommendation 在 stdout 渲染后丢弃。

**影响**：Dashboard 验收存档面板（`acceptance_archive`）显示全零值。

### H2: ~~traceability_report 缺 key~~（已撤销）

审计误计 key 数量（称 5 个，实际一期 4 个）和章节号（称 §3.2.4，实际 §3.2.3）。设计文档 §3.2.1 明确写验收摘要走 stdout "不经过 report_doc 中转"，实现完全符合规范。

### H3: config.json model 字段缺失

**设计文档定义了目标状态但未分配实施步骤**：
- §3.3.3 要求 config.json schema_version "1.1.0" + model 字段
- §5.1 实施步骤 0~6 中**没有任何步骤**负责 config.json 迁移
- config.template.json 也未更新，`vt init` 生成的新 config 同样不合规

### M1: phase_id 格式不一致

19 个历史 task 使用 "PHASE-VT-05"（2 位），phases 数组定义 "PHASE-VT-005"（3 位）。JSON schema pattern `^PHASE-[a-zA-Z0-9_-]+-\\d+$` 接受任意位数，无参照完整性检查。

### M2: task status 不同步

TASK-VT-192~198 实现完成后，Agent 创建了 claim（claimed_status: "completed"）但未同步更新 task_list.json 的 status 字段。这是**人工/Agent 维护流程缺口**，非系统设计缺陷。task_list.json 的 status 由人类/Agent 手动维护，VT 不自动回写。

### M3: ~~task_list.json closed 字段~~（设计决策驳回）

业务规范 §5.2 要求 closed 字段回写，但架构设计评审中已驳回此方案："让输出层反向写入输入文件会造成文件权限语义混乱"。task_list.json 保持**只读输入**定位，task 的 CLOSED 状态仅在 `task_sessions.json` 中维护。Agent 可通过 `vt analyze --task-status` 查询 task 关闭状态。

### M4: ac_missing_evidence 标注遗漏

TASK-VT-193 的 `ai_coding_guidance` 显式列出 ac_missing_evidence，但 `atomic_scope` 用"等"字模糊收尾。实现者按 atomic_scope 执行，遗漏了该条目。

---

## 3. 设计文档补完记录

以下 2 处已在 `docs/design_channel_separation.md` 中补完：

| 补完位置 | 内容 | 解决问题 |
|---|---|---|
| §3.2.1 步骤 3 | 新增"验收摘要回写"子步骤：build_list 返回的 list[dict] **过滤 task_id/iterations 后**写回 session_mgr 并 _save()；标注此方法为 CLOSED task 唯一合法的二次写操作 | H1 |
| §3.2.1 步骤 3 | 明确"task_list.json 保持只读"决策，记录驳回理由 | M3 |
| §3.5 数据流图 | 增加 `writeback_acceptance_summaries` 路径 | H1 |
| §5.1 步骤 0（新增） | config.json schema 迁移：template 增加 model + schema 升级 1.1.0 | H3 |
| §5.1 步骤 3 | 扩展核心产出：验收摘要回写 | H1 |
| §5.2 断言点 9-10 | 新增回写验证断言 + config 迁移断言 | H1, H3 |

---

## 4. 修复方案

### 4.1 H1: acceptance_summary 回写

**影响文件**：
- `src/vibe_tracing/cli/analyze/pipeline.py` — build_list 之后调用回写
- `src/vibe_tracing/domain/task/session.py` — 新增 `writeback_acceptance_summaries(summaries: list[dict])` 公开方法

**修复逻辑**：
```python
# pipeline.py _evaluate_and_output 步骤 3，build_list 之后
if acceptance_summaries:
    session_mgr.writeback_acceptance_summaries(acceptance_summaries)
```

```python
# session.py 新增方法
# CLOSED task 唯一合法的二次写操作，专用于补全验收摘要字段。
# update_sessions 对 CLOSED task 的保护在此不适用——回写发生在
# 同一次 analyze run 中，CLOSED 与回写之间无外部状态变化。
def writeback_acceptance_summaries(self, summaries: list[dict]) -> None:
    _EXTRA_KEYS = {"task_id", "iterations"}
    for s in summaries:
        tid = s["task_id"]
        if tid in self._data["tasks"]:
            self._data["tasks"][tid]["acceptance_summary"] = {
                k: v for k, v in s.items() if k not in _EXTRA_KEYS
            }
    self._save()
```

**注意**：`build_list` 返回的 dict 包含 `task_id` 和 `iterations`，这两个字段不在 `AcceptanceSummary` dataclass 中（session.py:47-64）。直接写回会导致 `TaskSession.from_dict` 时 `AcceptanceSummary(**data)` 抛 `TypeError`。必须在写回前过滤。

**测试影响**：`tests/test_task_session_manager.py` 新增回写断言（验证过滤后字段正确 + from_dict 反序列化无异常）；`tests/test_phase1_mvp_e2e.py` 验证 session 文件中 acceptance_summary 非默认值。

### 4.2 H3: config.json schema 迁移

**影响文件**：
- `src/vibe_tracing/templates/config.template.json` — 增加 `"model": ""` 字段，schema_version 升至 `"1.1.0"`
- `src/vibe_tracing/cli/init.py` — 已有 config.json 时检查 schema_version，低于 1.1.0 则补 model 字段
- `src/vibe_tracing/cli/finalize.py` — finalize 写 config 时也检查并补全
- `.vibetracing/config.json` — 手动或自动添加 `"model": "当前模型名"`

**修复逻辑**：
```python
# init.py 或 finalize.py 的 schema 迁移函数
from packaging.version import Version

def _migrate_config_schema(config_path: Path) -> dict:
    data = json.loads(config_path.read_text())
    current = Version(data.get("schema_version", "1.0.0"))
    if current < Version("1.1.0"):
        data.setdefault("model", "")
        data["schema_version"] = "1.1.0"
        config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return data
```

**注意**：版本比较**不能用字符串 `<`**（`"1.10.0" < "1.9.0"` → `True`），必须使用 `packaging.version.Version` 或显式相等比较。

### 4.3 M1: phase_id 数据修复

**影响文件**：`docs/task_list.json`

**修复逻辑**：批量替换 19 个 task 的 `"phase_id": "PHASE-VT-05"` 为 `"phase_id": "PHASE-VT-005"`。

受影响的 task_id：TASK-VT-044 ~ TASK-VT-065（共 19 个）。

### 4.4 M2: task status 数据修复

**数据修复**：`docs/task_list.json` 中 TASK-VT-192~198 的 status 从 `"todo"` 改为 `"done"`。

**无代码修复**：task_list.json 保持只读输入定位，VT 不自动回写 status。未来 task 完成时由人类/Agent 手动更新 task_list.json。

### 4.5 M4: ac_missing_evidence 标注

**影响文件**：`src/vibe_tracing/templates/field_hints.json`

**修复逻辑**：在 `issue_type_impacts` 中新增条目：
```json
"ac_missing_evidence": {
  "business_impact": "high",
  "description": "验收标准缺少测试覆盖证据"
}
```

---

## 5. 修复优先级与工时估算

| 优先级 | 修复项 | 类型 | 工时 | 依赖 |
|---|---|---|---|---|
| 1 | H1 验收摘要回写 | 代码 | 0.5d | 无 |
| 2 | H3 config.json 迁移 | 代码 + 模板 | 0.5d | 无 |
| 3 | M1 phase_id 数据修复 | 数据 | 0.1d | 无 |
| 4 | M2 task status 数据修复 | 数据 | 0.05d | 无 |
| 5 | M4 field_hints 补条目 | 数据 | 0.05d | 无 |
| **合计** | | | **~1.2d** | |

**修复顺序理由**：H1（功能性缺陷，影响 Dashboard 数据正确性）→ H3（影响 session model 字段）→ M1/M2/M4（纯数据修补，可批量执行）。

---

## 6. 不在本次修复范围

| # | 问题 | 理由 |
|---|---|---|
| ~~M3~~ | ~~task_list.json closed 字段~~ | **设计决策驳回**：task_list.json 保持只读输入，CLOSED 状态仅在 task_sessions.json 维护 |
| L1 | 62/75 源码文件无 claim 覆盖 | 仅 PHASE-VT-013/016 有 claim，历史模块待后续 phase 补齐 |
| L2 | 33/48 测试文件无 claim 覆盖 | 同上 |
| L3 | PHASE-VT-016 claims 的 AC 引用过于泛化 | 需要 PRD 新增 phase 专属 AC，属于 PRD 维护而非代码修复 |
| L4 | task_sessions.json 尚未创建 | 需 pipeline 端到端运行后自然生成 |
