# VT 进化计划 v2：决策平台

## 一、目标

VT 从"报告工具"升级为"决策平台"。核心闭环：

```
Agent 运行 vt analyze
  → 获得按优先级排序的行动清单
  → 执行任务
  → 门禁仍阻塞（需要人类决策）
  → 人类在 Dashboard 点击决策按钮
  → 决策写入 human_decisions.json
  → Agent 再次运行 vt analyze
  → Gate Engine 读取人类决策，解除对应阻塞
  → Agent 继续执行
```

**当前断点**：Dashboard 有决策 UI 但没有服务端接收决策；Gate Engine 不读取人类决策；CLI pipeline 顺序错误。

**成功标准**：人类在 Dashboard 做决策 → 门禁自动解除 → Agent 能继续工作。

---

## 二、架构决策

### 决策 1：Gate Engine 必须感知人类决策

当前 `merge_gate_engine.evaluate()` 不接受人类决策参数。`_apply_human_decisions()` 在 cli.py 中 gate engine 运行之后才执行——顺序错误。

**决定**：`evaluate()` 新增 `human_decisions` 参数，在计算 `gate_decision` 时直接消费。

### 决策 2：Decision Server 必须存在

Dashboard 通过 `POST /api/decisions` 提交决策。没有 server，决策只存在浏览器 localStorage，CLI 读不到。

**决定**：创建 `decision_server.py`，Flask 单文件，JSON 文件存储。不做认证、不做数据库。

### 决策 3：技术债在功能开发中自然解决

不设独立的"技术债清理批次"。当功能任务触及某个文件时，顺带解决该文件中的技术债。

**决定**：每个任务标注"附带清理"项。Phase 1 完成后，剩余未触及的债在 Phase 2 集中处理。

---

## 三、技术债管理策略

### 债务登记表

| ID | 债务描述 | 状态 | 解决任务 |
|---|---|---|---|
| DEBT-001 | `_load_hints`/`_resolve_hint` 在 6 个文件中重复 | ✅ 已解决 | TASK-003 + TASK-004 |
| DEBT-002 | `claim_fingerprints.json` 冗余（数据已在 evidence_index 中） | ✅ 已解决 | TASK-008 + TASK-009 |
| DEBT-003 | `coverage_baseline.json` 冗余 | ✅ 已解决 | TASK-008 + TASK-009 |
| DEBT-004 | `_check_invalidation` 用 hash 比较，应改为动态验证 | ✅ 已解决 | TASK-007 |
| DEBT-005 | `_get_related_code` 读取文件内容但从未使用 | ✅ 已解决 | TASK-009 |
| DEBT-006 | 治理边界函数分散在 cli.py 和 ghost_code_reconciler.py | ✅ 已解决 | TASK-010 |
| DEBT-007 | Dashboard 交互功能无自动化测试 | ✅ 已解决 | TASK-011 |
| DEBT-008 | Agent 行动清单无优先级排序 | ✅ 已解决 | TASK-006 |

### 原则

- **每个任务只解决自己触及的债务**，不跨文件找债
- **Phase 1 是功能驱动**，债务解决是附带产物
- **Phase 2 是剩余清理**，只处理 Phase 1 未触及的债务
- **每个任务完成后运行验证命令**，确认不破坏现有功能

---

## 四、子代理工作协议

每个任务委派给 subagent 时，subagent 收到的信息结构：

```
目标：一句话说明要做什么
目标文件：要修改的文件路径
前置依赖：必须先完成的任务 ID（如有）
变更内容：具体要改什么（函数签名、新增字段、删除逻辑等）
验证命令：subagent 完成后必须运行的命令
范围限制：明确告诉 subagent 不要碰什么
附带清理：该文件中需要顺带解决的技术债（如有）
```

**Subagent 不需要读 PRD、architecture_constraints.json 或本计划文档。** 任务本身包含足够的上下文。

**验收协议**：每个任务完成后，我（决策者）运行验证命令确认。Phase 结束时运行验证检查点。

---

## 五、执行计划

### Phase 1：决策平台核心闭环（5 个任务）

目标：打通"人类决策 → 门禁解除"的完整链路。

---

#### TASK-001：创建 Decision Server

- **目标**：创建决策接收服务端
- **目标文件**：`src/vibe_tracing/decision_server.py`（新增）
- **前置依赖**：无
- **变更内容**：
  - Flask 应用，监听 `localhost:5000`
  - `POST /api/decisions`：接收 JSON body `{category, targetId, action, reason, decidedBy}`，生成 `decision_id`（自增），追加到 `.vibetracing/human_decisions.json`
  - `GET /api/decisions`：返回 human_decisions.json 的完整内容
  - `human_decisions.json` 格式：`{"decisions": [{decision_id, category, targetId, action, reason, decidedBy, timestamp}]}`
  - 启动时如果文件不存在则创建空结构
  - CORS 允许 `localhost` 的 Dashboard 访问
- **验证命令**：`python -c "from vibe_tracing.decision_server import app; print('import ok')"`
- **范围限制**：
  - 不做认证、不做数据库、不做 WebSocket
  - 不修改任何现有文件
  - Flask 依赖已在项目中（如未安装则 `pip install flask`）

---

#### TASK-002：Gate Engine 新增人类决策感知

- **目标**：让门禁判定在计算时就考虑人类决策
- **目标文件**：`src/vibe_tracing/merge_gate_engine.py`
- **前置依赖**：无
- **变更内容**：
  - `evaluate()` 函数签名新增 `human_decisions=None` 参数
  - 在 `evaluate()` 内部，处理 risks 时：如果某个 risk 的 `target_id` 匹配 human_decisions 中 `action == "accept_risk"` 的记录，将该 risk 的 severity 降级为 `accepted`，不计入阻塞逻辑
  - 在处理 gaps 时：如果某个 gap 的 `target_id` 匹配 human_decisions 中 `action == "mark_complete"` 的记录，将该 gap 标记为 `human_resolved`
  - gate_decision 计算时，`accepted` 的 risk 和 `human_resolved` 的 gap 不触发阻塞
  - 返回的 gate_res 中新增 `human_decisions_applied` 字段，记录应用了几个人类决策
- **验证命令**：`pytest tests/test_merge_gate_engine.py -v`
- **范围限制**：
  - 不修改 cli.py（TASK-003 负责）
  - 不修改 Dashboard 相关文件
  - 不修改 `evaluate()` 的现有返回结构（只新增字段）
- **附带清理**：无（本文件不涉及其他债务）

---

#### TASK-003：CLI Pipeline 顺序修正 + hints 提取

- **目标**：修正人类决策的应用顺序；提取 hints 加载为独立模块
- **目标文件**：`src/vibe_tracing/cli.py`
- **前置依赖**：TASK-002
- **变更内容**：
  - **顺序修正**：将 `_load_human_decisions()` 的调用移到 `gate_engine.evaluate()` 之前。将 `human_decisions` 作为参数传入 `gate_engine.evaluate(human_decisions=human_decisions)`
  - 删除 `_apply_human_decisions()` 函数及其调用（gate engine 已经直接消费人类决策）
  - **hints 提取**：删除 cli.py 中的 `_load_hints` 和 `_resolve_hint` 函数（约行 1262-1275），改为从 `hint_loader` 模块导入（TASK-004 负责创建该模块，本任务先导入，如模块不存在则创建 stub）
  - 确保 `vt analyze` 的输出中 `human_decisions_applied` 数量正确显示
- **验证命令**：`pytest tests/test_cli_analyze.py -v`
- **范围限制**：
  - 不修改 merge_gate_engine.py（TASK-002 已完成）
  - 不修改 Dashboard 模板
  - 行动清单优先级排序不在本任务范围（TASK-006 负责）
- **附带清理**：解决 DEBT-001 的 cli.py 部分

---

#### TASK-004：创建 hint_loader 模块 + 迁移 5 个文件

- **目标**：消除 `_load_hints`/`_resolve_hint` 的 6 处重复
- **目标文件**：`src/vibe_tracing/hint_loader.py`（新增）+ 5 个现有文件
- **前置依赖**：无（可与 TASK-001/002 并行）
- **变更内容**：
  - 创建 `hint_loader.py`，包含：
    - `load_hints(category)` — 从 `templates/field_hints.json` 加载指定命名空间的 hints，带缓存
    - `resolve_hint(hint_value, level="level1")` — 处理扁平字符串（向后兼容）和结构化对象（level1/level2/level3）
  - 修改以下文件，删除本地 `_load_hints`/`_resolve_hint`，改为从 `hint_loader` 导入：
    - `src/vibe_tracing/merge_gate_engine.py`
    - `src/vibe_tracing/architecture_compliance_checker.py`
    - `src/vibe_tracing/risk_advisor.py`
    - `src/vibe_tracing/claim_loader.py`
    - `src/vibe_tracing/task_loader.py`
  - cli.py 的迁移在 TASK-003 中完成
- **验证命令**：`pytest tests/test_merge_gate_engine.py tests/test_claim_loader.py tests/test_task_loader.py tests/test_risk_advisor.py tests/test_architecture_compliance_checker.py tests/test_dynamic_hints.py -v`
- **范围限制**：
  - 不修改 `templates/field_hints.json` 的内容
  - 不改变 hints 的语义，只消除代码重复
  - 不修改 cli.py（TASK-003 负责）
- **附带清理**：解决 DEBT-001

---

#### TASK-005：Dashboard 真实 API 集成

- **目标**：Dashboard 决策按钮从 localStorage fallback 改为真实 API 调用
- **目标文件**：`src/vibe_tracing/templates/dashboard.template.html`
- **前置依赖**：TASK-001（Decision Server 必须存在）
- **变更内容**：
  - `submitDecision()` 函数改为优先调用 `POST /api/decisions`，失败时 fallback 到 localStorage
  - 决策历史表改为优先从 `GET /api/decisions` 加载，失败时从 localStorage 加载
  - 新增决策后自动刷新决策历史表
  - 决策卡片的按钮文本保持中文（"重新验证"、"接受风险"、"不再适用"）
- **验证命令**：`python -c "from vibe_tracing.dashboard_renderer import render_dashboard; print('template loads ok')"`
- **范围限制**：
  - 不修改 Dashboard 的 HTML 结构、CSS 样式
  - 不修改决策卡片的渲染逻辑
  - 不修改决策按钮的选项列表
  - 只修改 JS 中的 API 调用逻辑

---

### Phase 1 验证检查点

Phase 1 完成后，运行以下验证：

```bash
# 1. 全量测试通过
pytest tests/ -v

# 2. Decision Server 可启动
python -c "from vibe_tracing.decision_server import app; print('server ok')"

# 3. Gate Engine 接受人类决策
python -c "
from vibe_tracing.merge_gate_engine import MergeGateEngine
e = MergeGateEngine()
# 验证 evaluate 签名包含 human_decisions
import inspect
sig = inspect.signature(e.evaluate)
assert 'human_decisions' in sig.parameters, 'missing human_decisions param'
print('gate engine ok')
"

# 4. CLI 不再有 _apply_human_decisions
grep -c '_apply_human_decisions' src/vibe_tracing/cli.py && echo 'FAIL: still exists' || echo 'cli ok'

# 5. hints 不再重复
for f in merge_gate_engine architecture_compliance_checker risk_advisor claim_loader task_loader; do
  count=$(grep -c 'def _load_hints' src/vibe_tracing/$f.py 2>/dev/null || echo 0)
  if [ "$count" -gt 0 ]; then echo "FAIL: $f still has _load_hints"; fi
done
echo 'hints check done'

# 6. vt analyze 正常运行（在 VT 项目自身上）
vt analyze --gates-only 2>&1 | tail -5
```

**通过条件**：全部 6 项通过。

---

### Phase 2：体验优化 + 剩余债务（6 个任务）

目标：改善 Agent 使用体验，解决 Phase 1 未触及的技术债。

---

#### TASK-006：Agent 行动清单优先级排序

- **目标**：行动清单按紧急度排序，当前变更的问题排在前面
- **目标文件**：`src/vibe_tracing/cli.py`
- **前置依赖**：TASK-003
- **变更内容**：
  - `_collect_gap_actions` 和 `_collect_risk_actions` 返回的 actions 新增 `urgency` 字段（0-100 分）
  - 评分规则：
    - 当前 staged 变更引入的问题：urgency 80-100
    - 预存债务（非当前变更）：urgency 20-40
    - 已知问题（有历史记录）：urgency 50-70
  - `_render_actions` 按 urgency 降序排列
  - SUMMARY 行新增分类统计：`当前变更: X 项 | 预存债务: Y 项 | 等待人类: Z 项`
- **验证命令**：`pytest tests/test_cli_analyze.py -v`
- **范围限制**：
  - 不修改 merge_gate_engine.py
  - 不修改 Dashboard 模板
  - urgency 评分逻辑在 cli.py 内部，不暴露为公共 API

---

#### TASK-007：Claim 失效检测改为动态验证

- **目标**：claim 失效检测从 hash 比较改为重新验证
- **目标文件**：`src/vibe_tracing/traceability/claim_evidence_analyzer.py`
- **前置依赖**：无
- **变更内容**：
  - `_check_invalidation` 不再加载 `claim_fingerprints.json` 做 hash 比较
  - 改为：对 claim 引用的每个 `code_ref` 和 `test_ref`，检查文件是否存在且内容可读。如果文件不存在，标记 `needs_reverification`。如果文件存在但 hash 与 claim 创建时不同，标记 `needs_reverification`（仍用 hash，但从 evidence_index 获取而非独立文件）
  - evidence_index 中已有的文件 hash 可以复用，不再需要独立的 claim_fingerprints.json
- **验证命令**：`pytest tests/test_claim_evidence_analyzer.py -v`
- **范围限制**：
  - 不删除 claim_fingerprints.json（TASK-008 负责）
  - 不修改 cli.py
  - 保持 `_check_invalidation` 的返回格式不变

---

#### TASK-008：状态文件整合

- **目标**：将 `coverage_baseline.json` 和 `claim_fingerprints.json` 的数据合并到 `evidence_index.json`
- **目标文件**：`src/vibe_tracing/evidence_index_builder.py` + `src/vibe_tracing/tool_evidence_adapter.py` + `src/vibe_tracing/cli.py`
- **前置依赖**：TASK-007
- **变更内容**：
  - `evidence_index_builder.py`：evidence_index.json 新增 `coverage_baseline` 字段，存储每个源文件的覆盖率数据
  - `tool_evidence_adapter.py`：`_measure_source_coverage` 从 evidence_index 读取覆盖率，不再读取 `coverage_baseline.json`
  - `cli.py`：删除 `_save_claim_fingerprints` 函数，不再生成 `claim_fingerprints.json` 和 `coverage_baseline.json`
  - 运行 `vt analyze` 后，这两个文件不再被创建
- **验证命令**：`pytest tests/ -v && vt analyze --gates-only 2>&1 | tail -3`
- **范围限制**：
  - 不删除已有文件（TASK-009 负责）
  - evidence_index.json 的现有字段结构不变，只新增字段

---

#### TASK-009：死代码清理 + 删除冗余文件

- **目标**：清理未使用的代码和冗余状态文件
- **目标文件**：`src/vibe_tracing/cli.py` + `.vibetracing/` 目录
- **前置依赖**：TASK-008
- **变更内容**：
  - `cli.py`：`_get_related_code` 函数删除文件读取逻辑（读取 500 字符但 `content` 字段从未使用），返回格式从 `[{"path": ..., "content": ...}]` 改为 `[path_string]`，更新 `_collect_gap_actions` 中的调用方
  - 删除 `.vibetracing/claim_fingerprints.json`
  - 删除 `.vibetracing/coverage_baseline.json`
  - 确认 `vt analyze` 正常运行，不再依赖这两个文件
- **验证命令**：`pytest tests/test_cli_analyze.py -v && vt analyze --gates-only 2>&1 | tail -3`
- **范围限制**：
  - 不修改 merge_gate_engine.py
  - 不修改 evidence_index_builder.py（TASK-008 已完成）

---

#### TASK-010：治理边界函数提取

- **目标**：将治理边界相关函数提取为独立模块
- **目标文件**：`src/vibe_tracing/governance.py`（新增）+ `src/vibe_tracing/cli.py` + `src/vibe_tracing/ghost_code_reconciler.py`
- **前置依赖**：无
- **变更内容**：
  - 创建 `governance.py`，包含：
    - `load_boundary()` — 加载 architecture_constraints.json 中的 governance_boundary
    - `is_in_scope(filepath, boundary)` — 判断文件是否在治理范围内
    - `partition_by_scope(files, boundary)` — 将文件列表分为 in-scope 和 out-of-scope
  - cli.py 和 ghost_code_reconciler.py 中的对应函数改为从 governance.py 导入
  - 删除两个原模块中的本地实现
- **验证命令**：`pytest tests/ -v`
- **范围限制**：
  - 不修改 architecture_constraints.json
  - 不改变治理边界的语义

---

#### TASK-011：Dashboard 决策功能测试

- **目标**：补充决策平台核心逻辑的自动化测试
- **目标文件**：`tests/test_decision_server.py` + `tests/test_dashboard_decisions.py`
- **前置依赖**：TASK-001
- **变更内容**：
  - `test_decision_server.py`：测试 POST /api/decisions 写入 JSON、GET 返回正确数据、多条决策累积、decision_id 自增、invalid JSON 错误处理
  - `test_dashboard_decisions.py`：测试 `extractPendingDecisions` 从 report 数据中正确提取决策项、`mapActionToApi` 正确映射中文按钮文本到 API action、`generateDecisionId` 对同一 category+targetId 生成稳定 ID
- **验证命令**：`pytest tests/test_decision_server.py tests/test_dashboard_decisions.py -v`
- **范围限制**：
  - 不修改生产代码
  - 只补充测试

---

### Phase 2 验证检查点

```bash
# 1. 全量测试通过
pytest tests/ -v

# 2. 冗余文件已删除
test -f .vibetracing/claim_fingerprints.json && echo 'FAIL' || echo 'fingerprints deleted'
test -f .vibetracing/coverage_baseline.json && echo 'FAIL' || echo 'baseline deleted'

# 3. hints 不再重复（所有模块）
for f in cli merge_gate_engine architecture_compliance_checker risk_advisor claim_loader task_loader; do
  count=$(grep -c 'def _load_hints\|def _resolve_hint' src/vibe_tracing/$f.py 2>/dev/null || echo 0)
  if [ "$count" -gt 0 ]; then echo "FAIL: $f still has local hints functions"; fi
done
echo 'hints dedup done'

# 4. governance 模块可导入
python -c "from vibe_tracing.governance import load_boundary, is_in_scope, partition_by_scope; print('governance ok')"

# 5. vt analyze 完整运行
vt analyze 2>&1 | tail -10
```

**通过条件**：全部 5 项通过。

---

## 六、依赖图

```
Phase 1:
  TASK-001 (decision_server) ──────────┐
  TASK-002 (gate engine) ──→ TASK-003 (cli pipeline)
  TASK-004 (hint_loader) ─────────────→ TASK-003
  TASK-001 ────────────────────────────→ TASK-005 (dashboard API)

Phase 2:
  TASK-003 ──→ TASK-006 (action priority)
  TASK-007 (claim dynamic) ──→ TASK-008 (state merge) ──→ TASK-009 (dead code)
  TASK-010 (governance) ── 独立
  TASK-001 ──→ TASK-011 (tests)
```

**关键路径**：TASK-001 → TASK-005 → Phase 1 检查点 → TASK-006 → Phase 2 检查点

**可并行**：
- TASK-001 + TASK-002 + TASK-004（修改不同文件）
- TASK-007 + TASK-010（修改不同文件）

**必须串行**：
- TASK-002 → TASK-003（cli 调用 gate engine 新签名）
- TASK-003 → TASK-006（都修改 cli.py）
- TASK-007 → TASK-008 → TASK-009（数据依赖）

---

## 七、债务解决跟踪

Phase 1 完成后更新：

| ID | 债务 | 状态 | 解决任务 |
|---|---|---|---|
| DEBT-001 | hints 重复 | ✅ 已解决 | TASK-003 + TASK-004 |
| DEBT-002 | claim_fingerprints 冗余 | ⏳ 待 Phase 2 | TASK-008 |
| DEBT-003 | coverage_baseline 冗余 | ⏳ 待 Phase 2 | TASK-008 |
| DEBT-004 | claim hash 比较 | ⏳ 待 Phase 2 | TASK-007 |
| DEBT-005 | _get_related_code 死代码 | ⏳ 待 Phase 2 | TASK-009 |
| DEBT-006 | 治理边界分散 | ⏳ 待 Phase 2 | TASK-010 |
| DEBT-007 | Dashboard 测试缺失 | ⏳ 待 Phase 2 | TASK-011 |
| DEBT-008 | 行动清单无优先级 | ✅ 已解决 | TASK-006 |

Phase 2 完成后，所有债务应标记为 ✅ 已解决。

---

## 八、风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| TASK-003 修改 cli.py 幅度大 | 可能引入回归 | 拆分为顺序修正和 hints 提取两个 commit，分别验证 |
| TASK-004 修改 5 个文件 | 每个文件都可能破坏现有测试 | 每个文件迁移后单独运行对应测试 |
| Decision Server 依赖 Flask | 新增外部依赖 | 检查 pyproject.toml 是否已有 Flask，如无则添加 |
| Phase 2 任务可能因 Phase 1 回归而阻塞 | 整体延迟 | Phase 1 检查点必须全部通过才进入 Phase 2 |

---

## 九、预计耗时

- Phase 1：5 个任务，约 45-60 分钟
- Phase 2：6 个任务，约 60-75 分钟
- 验证检查点：每次约 5 分钟
- **总计：约 2-2.5 小时**
