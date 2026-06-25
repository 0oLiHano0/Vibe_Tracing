# CLI 层 YAGNI 精简与重构方案

本方案通过消除叶子节点模块冗余、清理包级 re-exports 污染、修正测试导入路径，来消除 CLI 层在历次重构中残留的过度设计。

---

## 审查要点

> [!IMPORTANT]
> 1. **仅合并叶子节点**：`helpers.py` 是纯叶子依赖（零 cli 内部依赖，仅被 `actions.py` 调用），合并到 `actions.py` 零副作用。`gates.py`、`output.py`、`formatting.py` 有明确职责边界，保留独立。
> 2. **彻底清理测试导入**：测试不再通过 `vibe_tracing.cli` 私有 re-export 导入内部组件，改为直接从物理模块路径导入。
> 3. **动态解析规则类别**：`accept.py` 和 `doctor.py` 中移除硬编码的 Rule Key 列表，直接动态解析 JSON 中的 list 字段。

---

## 开放性问题

无。

---

## 目标 cli/analyze/ 结构

```
cli/analyze/
├── exceptions.py    # _GateBlocked（循环导入隔离点）
├── pipeline.py      # 主流水线编排（调度层，含 _load_context）
├── gates.py         # 门禁检查（Gate 2 前置条件）
├── tools.py         # 工具执行
├── reports.py       # 报告生成（含 _rel_path_str）
├── actions.py       # 行动建议收集 + 辅助查询（吸收 helpers.py）
├── formatting.py    # 行动建议格式化
└── output.py        # 终端渲染
```

从 8 个文件精简为 7 个（合并 helpers.py → actions.py）。

---

## 详细实施步骤

### TASK-VT-100：动态规则 Key 替换

独立于 CLI 精简，消除 accept.py 和 doctor.py 中的硬编码防御性缺陷。

#### [MODIFY] accept.py
- 移除硬编码的 `rule_keys` 数组（第 64–80 行）。
- 修改规则遍历逻辑，改为动态获取 `constraints_data` 中值类型为 `list` 的所有键值对。

#### [MODIFY] doctor.py
- 移除硬编码的 `rule_keys` 数组（第 319–335 行）。
- 修改健康诊断第 5 步（`machine_rule_coverage`）中的规则遍历，同样改为动态遍历 JSON 中所有类型为 `list` 的键。

---

### TASK-VT-101：CLI 层精简

#### Step 1：合并 helpers.py → actions.py

`helpers.py` 是纯叶子节点（零 cli/analyze/ 内部依赖，所有函数仅被 `actions.py` 调用），合并零副作用。

##### [MODIFY] actions.py
- 将 `helpers.py` 中的所有函数直接复制到 `actions.py` 顶部：
  - `_action_hints`（模块级变量）
  - `_hint_title`、`_hint_context`
  - `_get_ac_description`、`_get_req_description`、`_get_related_code`、`_get_existing_tests`
  - `_derive_test_scenarios`
- 移除 `from vibe_tracing.cli.analyze.helpers import ...` 语句。
- 保留 `from vibe_tracing.infra.config.hint_loader import ...`（helpers.py 原有的外部依赖）。

##### [DELETE] helpers.py
- 物理删除。

#### Step 2：清理 __init__.py re-exports

移除所有以 `_` 开头的私有 helper 导出，仅保留公共 API 和 `_GateBlocked`：

```python
from vibe_tracing.cli.main import main
from vibe_tracing.cli.init import run_init
from vibe_tracing.cli.finalize import run_finalize
from vibe_tracing.cli.analyze import run_analyze
from vibe_tracing.cli.doctor import run_doctor
from vibe_tracing.cli.accept import run_accept
from vibe_tracing.cli.analyze.exceptions import _GateBlocked
```

被移除的导出（连同其测试导入修正一并处理）：
- `_load_context`、`_rel_path_str`、`_get_staged_files`、`_determine_affected_items`
- `_validate_constraints_change`、`_print_post_finalize_guidance`
- `_gate2_code_claim_alignment`、`_run_integrity_gates`
- `_execute_tools`、`_check_staged_extensions`
- `_action_hints`、`_hint_title`、`_hint_context`、`_derive_test_scenarios`
- `_get_ac_description`、`_get_req_description`、`_get_related_code`、`_get_existing_tests`
- `_compute_gap_urgency`、`_collect_gap_actions`、`_compute_risk_urgency`
- `_collect_risk_actions`、`_collect_violation_actions`、`_collect_gate_reason_actions`
- `_render_actions`、`_format_agent_actions`
- `_build_report_document`、`_build_metadata`、`_render_dashboard`
- `_print_gate_summary`、`_print_agent_actions`、`_print_reflection_prompts`、`_render_output`
- `_run_analysis_phase`、`_run_gate_evaluation`、`_evaluate_and_output`

#### Step 3：修正测试导入路径

修改 `tests/test_cli_analyze.py` 中所有 `from vibe_tracing.cli import _xxx` 为物理模块路径：

| 原导入 | 新导入 |
|--------|--------|
| `from vibe_tracing.cli import _get_ac_description` | `from vibe_tracing.cli.analyze.actions import _get_ac_description` |
| `from vibe_tracing.cli import _get_req_description` | `from vibe_tracing.cli.analyze.actions import _get_req_description` |
| `from vibe_tracing.cli import _get_related_code` | `from vibe_tracing.cli.analyze.actions import _get_related_code` |
| `from vibe_tracing.cli import _get_existing_tests` | `from vibe_tracing.cli.analyze.actions import _get_existing_tests` |
| `from vibe_tracing.cli import _derive_test_scenarios` | `from vibe_tracing.cli.analyze.actions import _derive_test_scenarios` |
| `from vibe_tracing.cli import _collect_gap_actions` | `from vibe_tracing.cli.analyze.actions import _collect_gap_actions` |
| `from vibe_tracing.cli import _collect_risk_actions` | `from vibe_tracing.cli.analyze.actions import _collect_risk_actions` |
| `from vibe_tracing.cli import _collect_violation_actions` | `from vibe_tracing.cli.analyze.actions import _collect_violation_actions` |
| `from vibe_tracing.cli import _collect_gate_reason_actions` | `from vibe_tracing.cli.analyze.actions import _collect_gate_reason_actions` |
| `from vibe_tracing.cli import _render_actions` | `from vibe_tracing.cli.analyze.formatting import _render_actions` |
| `from vibe_tracing.cli import _format_agent_actions` | `from vibe_tracing.cli.analyze.formatting import _format_agent_actions` |
| `from vibe_tracing.cli import _get_staged_files` | `from vibe_tracing.infra.git.utils import get_staged_files as _get_staged_files` |

同步修正 `tests/test_incremental_mode.py` 中的 `_print_gate_summary` 导入。

删除已废弃逻辑的测试用例。

#### Step 4：删除 _run_integrity_gates alias

`_run_integrity_gates` 是 `_check_claim_coverage` 的别名，零调用方。在 `gates.py` 中删除该别名定义，在 `__init__.py` 中删除对应导出。

---

## 验证计划

### 自动化测试
```bash
.venv/bin/pytest
```

### 手动验证
- 确认 `cli/analyze/helpers.py` 已物理删除。
- 确认 `cli/__init__.py` 中无下划线开头的私有导出残留。
- 确认 `tests/test_cli_analyze.py` 中无 `from vibe_tracing.cli import _` 形式的导入。
