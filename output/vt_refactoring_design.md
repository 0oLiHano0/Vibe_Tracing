# VT 项目重构设计

> 基于 `vt_architecture_audit.md` 审计结论，按优先级分批实施。

---

## 变更 1：消除 CLI 与 ReportBuilder 的双重执行管道

### 现状

CLI `run_analyze()` 在 L512-553 手动执行完整分析管道（req_analyzer → ac_analyzer → claim_analyzer → compliance_checker → risk_advisor），然后调用 `report_builder.build()` 时，`build()` 内部 L89-146 **再次执行完全相同的管道**。

`TraceabilityReportBuilder` 的 `build()` 签名接收 `prd_requirements`、`claims`、`evidences` 等原始输入，内部自行实例化所有 Analyzer 并重新分析。

注意：`frozen_risks` 本身不会被双重计入——它由 CLI 独立生成（L565-647），传入 builder 作为 `extra_risks`，builder 内部的 `risk_advisor.generate_risks()` 不会生成 frozen risks（builder 不知道 PRD 是否 frozen），只是在 L145-146 追加。所以 frozen_risks 在报告中只出现一次。

真正的问题是：**所有分析器被执行两遍，两套结果独立计算。** CLI 执行结果用于门禁决策，Builder 执行结果写入报告，两者使用相同输入但独立计算，可能因执行顺序细微差异产生不一致。

### 影响

- 每次 `analyze` 命令，所有分析器（RequirementTaskAnalyzer / AcTestAnalyzer / ClaimEvidenceAnalyzer / RiskAdvisor / ArchitectureComplianceChecker）执行两遍
- CLI 的 `merged_gaps` 和 builder 内部的 `merged_gaps` 独立计算，可能产生细微差异
- CLI 的 `final_risks`（用于门禁决策）和 builder 内部的 `final_risks`（写入报告）独立计算，可能不一致

### 改法

**将 `TraceabilityReportBuilder.build()` 从 "orchestrator + writer" 降级为纯 "writer"。**

```python
# traceability_report_builder.py — 新签名
def build(
    self,
    report_doc: Dict[str, Any],       # 已由 CLI 组装完毕的报告文档
    output_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Write a pre-assembled report to disk and validate against schema.

    Args:
        report_doc: Complete report dictionary (assembled by caller).
        output_path: Output path for traceability_report.json.

    Returns:
        The validated report dictionary.

    Raises:
        ValueError: If writing or validation fails.
    """
    if output_path is None:
        output_path = self.project_root / "output" / "traceability_report.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(report_doc, f, indent=2, ensure_ascii=False)

    val_res = self.schema_validator.validate_dict(report_doc, "traceability_report")
    if not val_res.is_valid:
        error_msg = f"Generated report failed schema validation: {val_res.message}"
        if val_res.field_path:
            error_msg += f" at field '{val_res.field_path}'"
        raise ValueError(error_msg)

    return report_doc
```

CLI 侧将报告文档的组装逻辑（当前在 builder L148-168）移入 `run_analyze()`：

```python
# cli.py — 在 L555 之后，组装 report_doc
report_doc = {
    "run_id": evidences_index.get("run_id"),
    "project_id": evidences_index.get("project_id"),
    "scan_time": evidences_index.get("scan_time"),
    "gate_decision": gate_decision,
    "requirement_coverage": req_res.get("requirement_coverage", []),
    "gaps": merged_gaps,
    "risks": final_risks,
    "architecture_compliance_status": compliance_res.get(...) if compliance_res else [],
    "architecture_violations": compliance_res.get(...) if compliance_res else [],
    "unclear_constraints": compliance_res.get(...) if compliance_res else [],
}

report_builder = TraceabilityReportBuilder(project_root)
report_doc = report_builder.build(report_doc, output_path=report_path)
```

**删除 `build()` 中 L89-146 的全部分析器调用**，以及不再需要的 import（`RequirementTaskAnalyzer`、`AcTestAnalyzer`、`ClaimEvidenceAnalyzer`、`RiskAdvisor`、`ArchitectureComplianceChecker`）。

---

## 变更 2：删除 `architecture_change_proposal.schema.json` 注册

### 现状

`schema_validator.py:97` 的 `KNOWN_SCHEMAS` 字典注册了 `"architecture_change_proposal": "architecture_change_proposal.schema.json"`，但 `schemas/` 目录中不存在该文件。当前无代码路径通过 `SchemaValidator` 加载此 schema，所以不崩溃——但这是一个隐藏地雷。

### 影响

任何新代码调用 `schema_validator.validate_file("architecture_change_proposal")` 会抛 `FileNotFoundError`。

### 改法

```python
# schema_validator.py L97 — 删除这一行
# "architecture_change_proposal": "architecture_change_proposal.schema.json",
```

---

## 变更 3：风险 ID / Evidence ID 常量化，消除硬编码 "VT"

### 现状

| 位置 | 硬编码 | 出现次数 |
|------|--------|----------|
| `risk_advisor.py` | `f"RISK-VT-{next_counter:03d}"` | 6 |
| `claim_evidence_analyzer.py` | `f"RISK-VT-{risk_counter:03d}"` | 5 |
| `architecture_change_proposal.py` | `f"RISK-VT-{counter:03d}"` | 4 |
| `cli.py` | `RISK-VT-901`, `RISK-VT-902`, `RISK-VT-{risk_counter}` | 3 |
| `risk_advisor.py` / `cli.py` / `architecture_compliance_checker.py` / `architecture_change_proposal.py` | `"EVIDENCE-VT-999"` | 17 |
| `tool_evidence_adapter.py` | `f"EVIDENCE-VT-{counter:03d}"` | 8 |

注意：`evidence_index_builder.py:136` 已使用动态前缀 `f"EVIDENCE-{ids._active_prefix}-{counter:03d}"`，不属于硬编码（但访问了私有变量 `_active_prefix`，由变更 4 处理）。

代码中已有 `ids._active_prefix` 和 `ids.set_project_prefix()` 机制，但上述硬编码完全没使用它。

### 影响

对任何非 VT 前缀的项目，生成的风险 ID 和证据 ID 格式错误（如 `RISK-VT-001` 对一个前缀为 `CapL` 的项目无意义）。

### 改法

在 `core/ids.py` 中添加工厂函数和哨兵常量（依赖变更 4 提供的 `get_project_prefix()`）：

```python
# core/ids.py — 新增

def make_risk_id(counter: int) -> str:
    """Generate a risk ID using the active prefix: RISK-{prefix}-{counter:03d}"""
    return f"RISK-{get_project_prefix()}-{counter:03d}"

def make_evidence_id(counter: int) -> str:
    """Generate an evidence ID using the active prefix: EVIDENCE-{prefix}-{counter:03d}"""
    return f"EVIDENCE-{get_project_prefix()}-{counter:03d}"

def sentinel_evidence_id() -> str:
    """Return the sentinel evidence ID for 'no real evidence' cases."""
    return f"EVIDENCE-{get_project_prefix()}-999"
```

全局替换：

| 查找 | 替换 |
|------|------|
| `f"RISK-VT-{xxx:03d}"` | `ids.make_risk_id(xxx)` |
| `f"RISK-VT-{xxx}"` | `ids.make_risk_id(xxx)` |
| `"RISK-VT-901"` / `"RISK-VT-902"` | `ids.make_risk_id(901)` / `ids.make_risk_id(902)` |
| `"EVIDENCE-VT-999"` | `ids.sentinel_evidence_id()` |
| `f"EVIDENCE-VT-{counter:03d}"` | `ids.make_evidence_id(counter)` |

涉及文件：`risk_advisor.py`、`claim_evidence_analyzer.py`、`architecture_change_proposal.py`、`architecture_compliance_checker.py`、`cli.py`、`tool_evidence_adapter.py`。

---

## 变更 4：`ids._active_prefix` 重命名为公开 API

### 现状

`core/ids.py` 定义 `_active_prefix = "VT"`（前置下划线表示私有），但被 8 处外部模块直接访问：

```
traceability_report_builder.py:82   schema_validator.py:294
evidence_index_builder.py:136       evidence_index_builder.py:257
prd_parser.py:159                   claim_loader.py:152
task_loader.py:160                  claim_evidence_analyzer.py:244
```

### 影响

- 命名误导：私有变量被广泛外部访问
- 并发不安全：模块级可变状态
- 未来重构（如线程本地存储）时需要改 8+ 处

### 改法

```python
# core/ids.py
active_prefix: str = "VT"   # 公开模块属性

def get_project_prefix() -> str:
    """Return the active project prefix."""
    return active_prefix
```

全局替换 `ids._active_prefix` → `ids.get_project_prefix()`（8 处）。

`set_project_prefix()` 中的 `global _active_prefix` 声明同步改为 `global active_prefix`。

---

## 变更 5：schema `description` 与运行时提示文本解耦

### 现状

3 个 schema 文件的 `description` 字段中混入了运行时修复指南（含 `{{PROJECT_PREFIX}}` 占位符）：

| Schema | `{{PROJECT_PREFIX}}` 处数 |
|--------|--------------------------|
| `task_list.schema.json` | 11 |
| `agent_claims.schema.json` | 2 |
| `architecture_constraints.schema.json` | 1 |

这些 description 被三处代码在运行时提取并拼入错误消息：
- `task_loader.py:151-163` — 从 task_list schema 提取
- `claim_loader.py:143-155` — 从 agent_claims schema 提取
- `schema_validator.py:283-298` — `resolve_field_hint()` 通用提取（覆盖所有 schema）

### 影响

- 修改 schema 描述文字会悄然改变运行时错误提示，无类型安全保护
- schema 的 `description` 同时承担"字段定义"和"修复指南"两个职责
- `{{PROJECT_PREFIX}}` 占位符是给代码用的，不是给人类读的文档

### 改法

**原则：`schemas/` 只存纯契约，所有修复指南统一存 `templates/field_hints.json`。**

#### 1. 新建 `src/vibe_tracing/templates/field_hints.json`

与现有 `templates/task_list.template.json`、`templates/config.template.json` 放在同目录，语义一致。按 schema 名称分组，收录所有需要运行时给出修复提示的字段：

```json
{
  "_comment": "运行时修复指南。校验失败时拼入错误消息，引导 AI Agent 修正输入。修改此处即可调整提示文本，不影响 schema 验证规则。",
  "task_list": {
    "task_id": "格式为 TASK-{PROJECT_PREFIX}-NNN，NNN 为三位数字",
    "title": "简洁描述任务内容，不超过 200 字符",
    "phase_id": "格式为 PHASE-{PROJECT_PREFIX}-NNN",
    "priority": "必须为 must / should / could 之一",
    "status": "必须为 todo / in_progress / blocked / done 之一",
    "related_requirements": "每个 ID 格式为 REQ-{PROJECT_PREFIX}-NNN",
    "related_acceptance_criteria": "每个 ID 格式为 AC-{PROJECT_PREFIX}-NNN-NN",
    "project_id": "格式为 PROJECT-{PROJECT_PREFIX}",
    "dod_id": "格式为 DOD-{PROJECT_PREFIX}-NNN-NN"
  },
  "agent_claims": {
    "claim_id": "格式为 CLAIM-{PROJECT_PREFIX}-NNN，NNN 为三位数字",
    "related_task": "格式为 TASK-{PROJECT_PREFIX}-NNN，必须已存在于任务列表"
  },
  "architecture_constraints": {
    "project_id": "格式为 PROJECT-{PROJECT_PREFIX}"
  }
}
```

占位符统一用 `{PROJECT_PREFIX}`，运行时由 `ids.get_project_prefix()` 替换。

#### 2. Loader 侧改为从文件加载

```python
# task_loader.py / claim_loader.py
import json
from pathlib import Path

_HINTS_PATH = Path(__file__).parent / "templates" / "field_hints.json"

def _load_field_hints(schema_name: str) -> Dict[str, str]:
    with _HINTS_PATH.open("r", encoding="utf-8") as f:
        all_hints = json.load(f)
    return all_hints.get(schema_name, {})
```

`task_loader.py` 中 `get_err_msg()` 改为：

```python
_field_hints = _load_field_hints("task_list")

def get_err_msg(field_key: str, base_msg: str) -> str:
    hint = _field_hints.get(field_key)
    if hint:
        from vibe_tracing.core import ids
        hint = hint.replace("{PROJECT_PREFIX}", ids.get_project_prefix())
        return f"{base_msg}【修复指南】{hint}"
    return base_msg
```

`claim_loader.py` 同理，传 `"agent_claims"` 即可。

`schema_validator.py` 的 `resolve_field_hint()`（L283-298）直接删除，不再保留。该函数的调用者是 `validate_dict()` / `validate_file()` 的错误处理路径，删除后这些路径不再附加 hint——loader 层已有自己的 `get_err_msg()` 提供更精确的修复指南，两层 hint 共存反而冗余。

#### 3. 清理 3 个 schema 的 `description` 字段

从 `task_list.schema.json`（11 处）、`agent_claims.schema.json`（2 处）、`architecture_constraints.schema.json`（1 处）的 `description` 中移除 `{{PROJECT_PREFIX}}` 占位符和修复性质的文字，只保留字段定义：

```json
// 改前
"task_id": { "description": "任务ID，必须符合正则格式 `TASK-{{PROJECT_PREFIX}}-\\d+`，例如 `TASK-{{PROJECT_PREFIX}}-001`。" }

// 改后
"task_id": { "description": "任务唯一标识符" }
```

改完后 schema `description` 只回答"这个字段是什么"，不回答"怎么填"。

#### 4. 删除 `schema_validator.py` 中的 `resolve_field_hint()`

该函数（L283-298）的唯一职责是从 schema 提取 `description` 并替换 `{{PROJECT_PREFIX}}`。hints 迁移到独立文件后，该函数不再有调用者，直接删除。

---

## 变更 6：`EvidenceIndexBuilder` 接受已解析结果

### 现状

CLI 在 `run_analyze()` 中已通过 `RawInputLoader.load()` 加载全部文件，通过 `TaskLoader`/`ClaimLoader` 解析。然后 `EvidenceIndexBuilder.build()` 内部 L69 再次 `self.raw_loader.load()`，L95-128 再次 `prd_parser.parse_file()`、`task_loader.load_and_validate()`、`claim_loader.load_and_validate()`。

### 影响

每次 `analyze` 命令，`prd.md`、`task_list.json`、`agent_claims.json` 被读取和解析两遍。

### 改法

**`EvidenceIndexBuilder.build()` 接受已解析好的对象，去掉内部的加载逻辑。**

```python
# evidence_index_builder.py — 新签名
def build(
    self,
    output_path: Optional[Path] = None,
    tool_evidence_candidates: Optional[List] = None,
    # 新增：已解析结果（带类型注解）
    prd_record: Optional[InputRecord] = None,
    task_result: Optional[TaskListLoadResult] = None,
    claims_list: Optional[List[Claim]] = None,
    manifest: Optional[RawInputManifest] = None,
) -> Dict[str, Any]:
```

当 `prd_record` 等参数被传入时，跳过内部的 `self.raw_loader.load()` 和解析逻辑。保留旧参数签名以兼容独立使用场景（如测试）：

```python
# Step 1: 使用传入的数据，或自行加载
if prd_record is not None and task_result is not None:
    # 使用 caller 提供的已解析数据
    # 注意：caller 必须已调用 ids.set_project_prefix()，CLI 在 L260 已完成此步骤
    config_prefix = manifest.config_data.get("project_prefix", "VT") if manifest else "VT"
    ids.set_project_prefix(config_prefix)  # 仍需调用，确保 prefix 正确
    ...
else:
    # 独立模式：自行加载（保留原有逻辑）
    manifest = self.raw_loader.load()
    ...
```

注意：`evidence_index_builder.py:89-92` 在 `build()` 内部调用 `ids.set_project_prefix(config_prefix)`。当 caller 传入已解析数据时，这段代码仍需执行以确保 prefix 正确——CLI 在 L260 已提前调用过，但 `build()` 不应依赖 caller 的调用顺序，应自行保证。

CLI 侧传入已有的解析结果：

```python
evidences_index = index_builder.build(
    output_path=index_path,
    tool_evidence_candidates=tool_evidence_candidates,
    prd_record=prd_record,
    task_result=task_res,
    claims_list=claims_list,
    manifest=manifest,
)
```

---

## 变更 7：`assess_claim_credibility()` 迁移到 traceability 层

### 现状

`claim_loader.py:270-354` 定义了 `assess_claim_credibility()`，这是一个独立的业务分析函数（评估 claim 可信度、生成 warning），不属于 Loader 的"加载与验证"职责。CLI 从 loader 模块导入它：

```python
from vibe_tracing.claim_loader import assess_claim_credibility
```

### 影响

代码组织混乱，Loader 层被污染了分析逻辑。

### 改法

将 `assess_claim_credibility()` 移动到新建的 `traceability/claim_credibility.py`（不放入 `claim_evidence_analyzer.py`——该文件已有明确职责，混入会重蹈当前问题）。CLI 改为：

```python
from vibe_tracing.traceability.claim_credibility import assess_claim_credibility
```

函数签名和逻辑不变，仅文件位置迁移。

---

## 变更 8：删除 `ToolEvidenceCandidate.evidence_id` 死字段

### 现状

`tool_evidence_adapter.py:29` 定义 `evidence_id: str`，`ToolExecutionEngine._next_evidence_id()` 生成 `EVIDENCE-VT-001` 等格式的 ID 填充它。但 `evidence_index_builder.py:226` 中：

```python
ev_id = get_next_id()   # builder 生成新 ID
evidence_dict = {
    "evidence_id": ev_id,   # cand.evidence_id 从未被读取
    ...
}
```

`cand.evidence_id` 在整个 `src/` 中**零读取**。

### 影响

- 8 处 `_next_evidence_id()` 调用生成无用 ID
- `_evidence_counter` 和 `_reset_counter()` 也是死代码
- `ToolEvidenceAdapter`（deprecated）中同样的死字段

### 改法

1. 从 `ToolEvidenceCandidate` 中移除 `evidence_id` 字段
2. 删除 `ToolExecutionEngine` 中的 `_next_evidence_id()`、`_reset_counter()`、`_evidence_counter`
3. 删除所有 `_next_evidence_id()` 调用（8 处构造 `ToolEvidenceCandidate` 时传入的 `evidence_id=self._next_evidence_id()` 参数）
4. 同样清理 deprecated 的 `ToolEvidenceAdapter` 中的对应代码

删除前先运行 `grep -r "evidence_id" tests/` 确认没有测试依赖 `ToolEvidenceCandidate.evidence_id` 字段。

---

## 变更 9：CLI 统一使用静态 import

### 现状

`cli.py:221-242` 对 9 个核心模块使用 `importlib.import_module()` 动态导入，而文件顶部已有正常的静态 import（`RawInputLoader`、`SchemaValidator` 等）。这些模块不构成循环依赖（顶部 import 已证明）。

### 影响

丢失类型检查、IDE 跳转能力，无任何技术收益。

### 改法

在 `cli.py` 顶部统一使用静态 import：

```python
from vibe_tracing.evidence_index_builder import EvidenceIndexBuilder
from vibe_tracing.traceability_report_builder import TraceabilityReportBuilder
from vibe_tracing.merge_gate_engine import MergeGateEngine
from vibe_tracing.architecture_compliance_checker import ArchitectureComplianceChecker
from vibe_tracing.traceability.requirement_task_analyzer import RequirementTaskAnalyzer
from vibe_tracing.traceability.ac_test_analyzer import AcTestAnalyzer
from vibe_tracing.traceability.claim_evidence_analyzer import ClaimEvidenceAnalyzer
from vibe_tracing.risk_advisor import RiskAdvisor
```

删除 `cli.py:219` 的 `import importlib` 和 L221-242 的 9 处 `importlib.import_module()` 调用。

同理 L703 的 `DashboardRenderer` 动态导入也改为静态导入。

---

## 变更 10：`ArchitectureComplianceChecker` 文件名映射迁移到约束文件

### 现状

`architecture_compliance_checker.py:76-103` 用 if-elif 链将文件名映射到模块 ID：

```python
if filename in ("cli.py", "agent_runtime_adapter.py"):
    return "MOD-VT-001", "agent_runtime_adapter"
elif filename in ("raw_input_loader.py", "prd_parser.py", ...):
    return "MOD-VT-002", "raw_input_loader"
...
```

`_get_module_for_import()` L105-138 有类似的映射。两处都是硬编码，无测试覆盖，文件重命名或新增文件会导致静默失效。

### 影响

映射完整性无保障，新增文件可能绕过所有架构约束检查。

### 改法

**必须同步更新 `architecture_constraints.schema.json`**——在 `module_boundaries` 的 items 中新增 `owned_files` 字段定义，否则 `vt analyze` 会因为 schema 验证拒绝新字段（`additionalProperties: false` 规则）：

```json
// architecture_constraints.schema.json — module_boundaries items 中新增
"owned_files": {
  "type": "array",
  "description": "此模块拥有的 Python 源文件名列表",
  "items": { "type": "string" }
}
```

然后在 `architecture_constraints.json` 的 `module_boundaries` 中扩展 `owned_files` 字段：

```json
{
  "module_boundaries": [
    {
      "module_id": "MOD-VT-001",
      "module_name": "agent_runtime_adapter",
      "owned_files": ["cli.py", "agent_runtime_adapter.py"],
      "owned_data": ["CLI commands", "agent runtime interface"],
      ...
    },
    {
      "module_id": "MOD-VT-002",
      "module_name": "raw_input_loader",
      "owned_files": ["raw_input_loader.py", "prd_parser.py", "task_loader.py", "claim_loader.py"],
      ...
    }
  ]
}
```

`_get_module_for_file()` 改为从约束文件加载映射：

```python
def _get_module_for_file(self, file_path: str) -> Tuple[Optional[str], Optional[str]]:
    filename = Path(file_path).name
    for boundary in self.constraints.get("module_boundaries", []):
        if filename in boundary.get("owned_files", []):
            return boundary["module_id"], boundary["module_name"]
    return None, None
```

同理 `_get_module_for_import()` 也从约束文件派生。

---

## 变更 11：消除 `check()` 内部的冗余 `RawInputLoader`

### 现状

`architecture_compliance_checker.py:482-484` 在 `check()` 内部创建 `RawInputLoader` 来检查 `GATE-VT-001`（必需文件是否存在）。但 `check()` 被调用时，文件必然已经存在（因为调用者已加载了它们）。

### 影响

- 不必要的文件系统访问
- Checker 层依赖 Loader 层（层违规）
- 该检查在实际运行中永远不会发现缺失文件

### 改法

直接从 `self.project_root` 拼路径，不引入 `RawInputLoader`：

```python
# architecture_compliance_checker.py check() 内
required_paths = {
    "prd": self.project_root / "docs" / "prd.md",
    "architecture_constraints": self.constraints_path,
    "task_list": self.project_root / "docs" / "task_list.json",
}
missing_files = [name for name, p in required_paths.items() if not p.exists()]
```

或者更激进：直接删除这段检查，因为调用者已保证文件存在。保留检查的话，至少不再引入 `RawInputLoader` 依赖。

---

## 变更 12：`status_enum` / `priority_enum` 装饰性字段处理

### 现状

`task_list.schema.json` 顶层定义了 `status_enum` 和 `priority_enum` 数组，但 task 项内部的 `status`/`priority` 使用内联 `enum`，两者无 JSON Schema `$ref` 关系。顶层枚举是装饰性的。

### 影响

AI Agent 可能误以为修改顶层 `status_enum` 会影响验证行为。

### 改法

**直接删除**这两个字段（而非添加说明——添加说明只是将混乱文档化，没有消除混乱）。

删除前运行 `grep -r "status_enum\|priority_enum" src/ tests/` 确认无外部消费者。

---

## 变更 13：Frozen PRD 审计逻辑从 CLI 提取

### 现状

`cli.py:541-625` 中，Frozen PRD 漂移检测的完整业务逻辑（比较 baseline 与当前 PRD、生成 risk 记录）内联在 `run_analyze()` 中，约 85 行。这个逻辑属于业务分析层而非 CLI 编排层。

### 影响

- `run_analyze()` 已超过 450 行，可读性差
- Frozen PRD 审计无法被其他入口复用
- 风险 ID 硬编码（`RISK-VT-901`、`RISK-VT-902`）

### 改法

新建 `traceability/frozen_prd_auditor.py`：

```python
from vibe_tracing.core import ids

class FrozenPrdAuditor:
    def __init__(self, project_root: Path, prd_parser: PrdParser):
        self.project_root = project_root
        self.prd_parser = prd_parser

    def audit(self, prd_status: str, prd_requirements: List[Any]) -> List[Dict[str, Any]]:
        """Check for PRD drift when status is frozen. Returns list of risk dicts."""
        if prd_status != "frozen":
            return []
        # 使用 ids.make_risk_id() 代替硬编码 "RISK-VT-xxx"
        risk_id = ids.make_risk_id(901)  # 替代原来的 "RISK-VT-901"
        ...
```

CLI 改为：

```python
from vibe_tracing.traceability.frozen_prd_auditor import FrozenPrdAuditor
auditor = FrozenPrdAuditor(project_root, prd_parser)
frozen_risks = auditor.audit(prd_res.status, prd_res.requirements)
```

注意：提取后的 `FrozenPrdAuditor` 内部必须使用 `ids.make_risk_id()` 生成风险 ID（与变更 3 联动），否则等于把硬编码搬到了新文件。

---

## 实施顺序

| 批次 | 变更 | 理由 |
|------|------|------|
| **第一批** | 4, 2 | 先建立公开 API（`get_project_prefix()`），再删除不存在的 schema 注册。无相互依赖，为后续批次打基础。 |
| **第二批** | 1, 3 | 双重管道消除（1）与 ID 常量化（3）同批：3 的工厂函数依赖 4 提供的 `get_project_prefix()`。两者变更文件集不重叠，可并行。 |
| **第三批** | 5, 6 | schema description 解耦（5）与 EvidenceIndexBuilder 优化（6）：6 的 `ids.set_project_prefix` 依赖已由第一批处理。 |
| **第四批** | 7, 8, 9, 13 | 代码清理类（函数迁移、死字段删除、静态导入、逻辑提取），低风险。13 实施时需联动变更 3 的 `ids.make_risk_id()`。 |
| **第五批** | 10, 11, 12 | 架构优化类。10 必须同步更新 `architecture_constraints.schema.json`（补充 `owned_files` 字段定义）。 |

每批完成后运行 `pytest` 确认无回归。
