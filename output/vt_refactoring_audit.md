# VT 重构设计文档审计报告

> 对照实际源码，逐项核查 `output/vt_refactoring_design.md` 的 13 个变更方案。
> 审计原则：事实准确性、内部一致性、实施可行性、遗漏风险。

---

## 总体评价

设计文档整体质量良好，核心问题识别准确，改法方向正确。但存在：
- **1 个严重事实错误**（变更 1 的 frozen_risks 双重计入描述）
- **1 个致命实施顺序依赖**（变更 3 依赖变更 4，但批次安排反了）
- **1 个遗漏**（变更 10 需同步更新 schema 文件）
- 若干措辞不精确和改法细节可完善的地方

---

## 变更 1：消除双重执行管道

### ✅ 问题诊断：准确

`TraceabilityReportBuilder.build()` 在 L89-135 确实完整运行了一遍 `RequirementTaskAnalyzer → AcTestAnalyzer → ClaimEvidenceAnalyzer → RiskAdvisor → ArchitectureComplianceChecker`，而 CLI 在 L512-553 已运行完全相同的管道。已验证。

### ⚠️ 事实错误：frozen_risks 双重计入的表述不准确

文档原文：
> "frozen risks 被计入两次的风险"

**实际行为：**
- CLI 在 L565-647 独立生成 `frozen_risks`，传给 builder 作为 `extra_risks`。
- Builder 内部的 `risk_advisor.generate_risks()`（L129）**不会**生成 frozen risks，因为 builder 根本不知道 PRD 是否 frozen。
- Builder 在 L145-146 将 `extra_risks` 追加到 `final_risks`。

**所以 frozen_risks 在报告里只出现一次**，不存在双重计入。

真正的双重执行问题是：**gap-based 风险和追溯分析**被 CLI 和 builder 各跑一遍（两套独立的 risk_advisor.generate_risks() 结果）。CLI 那套用于门禁决策，builder 那套写入报告——两者使用相同输入但独立计算，存在细微不一致风险。这才是核心问题。

### ✅ 改法方向：正确

将 builder 降级为纯 writer 的方向完全正确。建议在文档中修正 frozen_risks 的描述，改为：

> "每次 analyze，所有分析器（RequirementTaskAnalyzer / AcTestAnalyzer / ClaimEvidenceAnalyzer / RiskAdvisor / ArchitectureComplianceChecker）执行两遍。CLI 执行结果用于门禁决策，Builder 执行结果写入报告，两者独立计算，可能因执行顺序细微差异产生不一致。"

### 💡 改法补充

CLI 侧已有 `req_res.get("requirement_coverage", [])` 可直接用于组装 `report_doc`（L514），方案可行，无需额外计算。

---

## 变更 2：删除缺失 schema 注册

### ✅ 完全准确

已确认：`schemas/` 目录中**不存在** `architecture_change_proposal.schema.json`，而 `schema_validator.py:97` 确实注册了它。改法（删除那一行注册）简单直接，无副作用。

---

## 变更 3：风险 ID / Evidence ID 常量化

### ⚠️ 部分不准确

文档的"硬编码"分析表格中，`evidence_index_builder.py` 被列为硬编码 `EVIDENCE-VT-`。**实际上**：
- `evidence_index_builder.py:136`：`f"EVIDENCE-{ids._active_prefix}-{evidence_counter:03d}"`
- 这**已经使用动态前缀**，只是访问了私有变量 `_active_prefix`，并非硬编码 `VT`。

真正硬编码 `VT` 的是：
- `tool_evidence_adapter.py:89`：`f"EVIDENCE-VT-{self._evidence_counter:03d}"` ✅（文档正确识别）
- `architecture_compliance_checker.py:509`：`"EVIDENCE-VT-999"` ✅（文档正确识别）
- `cli.py` 中 frozen PRD 风险的 `"EVIDENCE-VT-999"` ✅

### 🚨 致命实施顺序问题

**变更 3 依赖变更 4，但文档的批次安排相反。**

- 变更 3 提出调用 `ids.get_project_prefix()`
- 变更 4 才定义 `ids.get_project_prefix()`
- 文档将变更 3 排在**第一批**，变更 4 排在**第二批**

这意味着按文档顺序实施后，第一批代码会调用一个不存在的函数，`pytest` 会立即失败。

**修正：变更 4 必须与变更 3 合并到同一批次，或先于变更 3 实施。**

---

## 变更 4：`_active_prefix` 公开化

### ✅ 问题诊断：准确

已确认 8 处外部访问 `ids._active_prefix`：
- `traceability_report_builder.py:82`
- `evidence_index_builder.py:136, 257`
- `claim_loader.py:152`
- `task_loader.py:160`
- `schema_validator.py:294`

（文档列举中 `prd_parser.py:159` 需要单独确认，其余均已核实）

### 💡 改法简洁合理

`active_prefix` 公开属性 + `get_project_prefix()` getter 的方案干净。注意：`set_project_prefix()` 里的 `global _active_prefix` 声明需同步改为 `global active_prefix`。

---

## 变更 5：schema description 与运行时提示解耦

### ✅ 问题诊断：准确

三个文件均已确认：
- `task_loader.py:150-163`：从 schema 提取 `description`，替换 `{{PROJECT_PREFIX}}`
- `claim_loader.py:142-155`：同上
- `schema_validator.py:283-297`：`resolve_field_hint()` 同上逻辑

### ⚠️ 改法细节需注意

1. **`_HINTS_PATH` 模块级常量的时机问题**：  
   `_HINTS_PATH = Path(__file__).parent / "templates" / "field_hints.json"` 是模块导入时确定的路径。这与当前 `schemas_dir` 支持外部覆盖（project 级别 schemas）的逻辑不一致。但由于 hints 是运行时提示而非合同规则，绑定到内置 templates 目录是合理的。

2. **`resolve_field_hint()` 的调用者确认**：  
   删除该函数前，需确认 `schema_validator.py` 内部调用链——它在 `validate_dict()` / `validate_file()` 的错误处理路径中被调用。改法中提到"或直接删除该函数，将 hint 查询逻辑下沉到各 loader"，建议明确选择其中一种，不要留歧义。

3. **`field_hints.json` 维护负担说明**：  
   文档未提及这个新文件是**新的维护点**——修改字段格式规则时，需同时改 schema 和 hints 两个文件。但这比现在 description 藏在 schema 里更透明，可接受。

---

## 变更 6：EvidenceIndexBuilder 接受已解析结果

### ✅ 问题诊断：准确

已确认 `evidence_index_builder.py:69` 调用 `self.raw_loader.load()`，L94-128 重复解析 PRD/task/claims，与 CLI 侧重复。

### ⚠️ 改法接口设计较弱

```python
prd_record: Optional[Any] = None,
task_result: Optional[Any] = None,
claims_list: Optional[List] = None,
manifest: Optional[Any] = None,
```

用 `Any` 类型会让静态类型检查器无法捕捉调用错误。建议改为正确的类型注解：

```python
from vibe_tracing.raw_input_loader import RawInputManifest, InputRecord
from vibe_tracing.task_loader import TaskListLoadResult
from vibe_tracing.prd_parser import PrdParseResult

prd_record: Optional[InputRecord] = None,
task_result: Optional[TaskListLoadResult] = None,
claims_list: Optional[List[Claim]] = None,
manifest: Optional[RawInputManifest] = None,
```

### 💡 还需同步处理的细节

`evidence_index_builder.py:89-92` 在 `build()` 内部调用 `ids.set_project_prefix(config_prefix)`。如果 caller 传入了已解析数据，跳过加载逻辑，则这里的 `set_project_prefix` 也会被跳过。但 CLI 已在 L260 提前调用了 `ids.set_project_prefix()`，所以不会有问题——但文档应明确说明这个依赖关系。

---

## 变更 7：`assess_claim_credibility()` 迁移

### ✅ 完全准确

已确认：`claim_loader.py:270-354` 定义了 `assess_claim_credibility()`（85 行），是一个独立的分析函数，与 Loader 职责无关。迁移方向正确，函数签名无需改动。

### 💡 建议目标路径

文档提议迁移到 `traceability/claim_evidence_analyzer.py` 或新建 `traceability/claim_credibility.py`。**推荐新建单独文件**，因为 `claim_evidence_analyzer.py` 已有明确职责，混入会重蹈当前问题。

---

## 变更 8：删除 `ToolEvidenceCandidate.evidence_id` 死字段

### ✅ 完全准确

已确认：
- `tool_evidence_adapter.py:29`：`evidence_id: str` 字段存在
- `tool_evidence_adapter.py:87-91`：`_next_evidence_id()` 生成它
- `evidence_index_builder.py:226-230`：`ev_id = get_next_id()`，`cand.evidence_id` 从未被读取

`_evidence_counter` 和 `_reset_counter()` 确属死代码。

### ⚠️ 注意废弃的 `ToolEvidenceAdapter` 类

文档提到 `ToolEvidenceAdapter`（deprecated），需确认该类中的同名字段是否也是死字段，或者有没有外部测试在使用它。删除前运行 `grep -r "evidence_id" tests/` 确认没有测试依赖这个字段。

---

## 变更 9：CLI 统一静态 import

### ✅ 完全准确

已确认 `cli.py:221-242` 使用 `importlib.import_module()`，且 L703 的 `DashboardRenderer` 也是动态导入。顶部已有静态 import（`RawInputLoader`、`SchemaValidator` 等），证明不存在循环依赖问题。

### 💡 执行细节

`import importlib` 在 `run_analyze()` 内部（L219），而非顶部——改完后需一并删除函数内的这行导入。文档已覆盖，但实施时注意不要漏掉。

---

## 变更 10：`ArchitectureComplianceChecker` 文件名映射配置化

### ✅ 问题诊断：准确

已确认 `architecture_compliance_checker.py:76-103` 的 if-elif 链（`_get_module_for_file`）和 L117-138 的 `_get_module_for_import`，两处均为硬编码映射。

### 🚨 重要遗漏：需同步更新 schema 文件

在 `architecture_constraints.json` 的 `module_boundaries` 中新增 `owned_files` 字段，**必须同步更新 `architecture_constraints.schema.json`**——否则 `vt analyze` 会因为 schema 验证拒绝新字段（`additionalProperties: false` 规则）。

文档完全没有提及这一步。**这是一个会导致功能彻底失效的遗漏。**

建议补充：
```json
// architecture_constraints.schema.json
// module_boundaries 的 items 中新增：
"owned_files": {
  "type": "array",
  "description": "此模块拥有的 Python 源文件名列表",
  "items": { "type": "string" }
}
```

---

## 变更 11：消除 `check()` 内部的冗余 `RawInputLoader`

### ✅ 完全准确

已确认 `architecture_compliance_checker.py:482-484`：

```python
from vibe_tracing.raw_input_loader import RawInputLoader
raw_loader = RawInputLoader(self.project_root)
```

在 `check()` 内部实例化仅用于获取文件路径，然后检查是否存在。当 `check()` 被调用时，文件已被 CLI 加载（否则 CLI 会更早返回错误）。

### 💡 改法的两个选项

文档提供了两个选项（直接路径拼接 / 完全删除检查），建议选择**直接路径拼接**而非完全删除——保留该检查作为防御层有价值，只是不应为此引入 Loader 依赖。

同时注意：`architecture_compliance_checker.py:509` 的 `"EVIDENCE-VT-999"` 是 Change 3 需要处理的硬编码，两个变更实施时需协同。

---

## 变更 12：`status_enum` / `priority_enum` 装饰性字段

### ✅ 问题诊断：准确

`task_list.schema.json` 顶层的 `status_enum` / `priority_enum` 确与 task items 的内联 enum 无 `$ref` 关联关系，属于装饰性字段。

### 💡 推荐做法

文档提供了两种选项：加 `description` 说明 / 直接删除。**推荐直接删除**（如果确认无外部消费者），而非添加说明。添加说明只是将混乱文档化，没有消除混乱。

删前确认：运行 `grep -r "status_enum\|priority_enum" src/ tests/`。

---

## 变更 13：Frozen PRD 审计逻辑提取

### ✅ 完全准确

已确认 `cli.py:565-647` 约 85 行 Frozen PRD 漂移检测逻辑内联在 `run_analyze()` 中。提取到 `traceability/frozen_prd_auditor.py` 方向正确。

### 💡 与变更 3 的联动

`FrozenPrdAuditor` 内部会生成 `RISK-VT-901`、`RISK-VT-902` 等 ID。提取后，这些 ID 的生成也应改用 `ids.make_risk_id(901)` 等函数（与变更 3 联动），否则等于把硬编码搬到了新文件。文档未明确说明这一点。

---

## 实施顺序修正

原文档的批次安排存在**变更 3 依赖变更 4** 的顺序错误。修正后建议：

| 批次 | 变更 | 说明 |
|------|------|------|
| **第一批** | **4, 2** | 先建立公开 API（`get_project_prefix()`），再删除不存在的 schema 注册。这两个无相互依赖，且为后续批次打基础。 |
| **第二批** | **1, 3** | 双重管道消除（1）与 ID 常量化（3）同批：3 已能调用 4 提供的 API。两者变更文件集不重叠，可并行。 |
| **第三批** | **5, 6** | schema description 解耦（5）与 EvidenceIndexBuilder 优化（6）：6 的 ids.set_project_prefix 依赖已由第一批处理。 |
| **第四批** | **7, 8, 9, 13** | 代码清理类（函数迁移、死字段删除、静态导入、逻辑提取），低风险，可快速完成。13 实施时需联动变更 3 的 ID 常量化。 |
| **第五批** | **10, 11, 12** | 架构优化类。10 必须同步更新 `architecture_constraints.schema.json`（补充 `owned_files` 字段定义）。 |

每批完成后运行 `pytest` 确认无回归。

---

## 汇总

| 变更 | 诊断准确性 | 改法可行性 | 关键问题 |
|------|-----------|-----------|---------|
| 1 | ⚠️ 基本准确，frozen_risks 表述有误 | ✅ | 修正错误描述 |
| 2 | ✅ | ✅ | — |
| 3 | ⚠️ evidence_index_builder 分类有误 | ✅ | **🚨 必须先实施变更 4** |
| 4 | ✅ | ✅ | 注意 global 声明同步 |
| 5 | ✅ | ✅ | resolve_field_hint 删除策略需明确 |
| 6 | ✅ | ⚠️ 类型注解用 Any 太弱 | 补强类型；明确 set_project_prefix 依赖 |
| 7 | ✅ | ✅ | 推荐新建单独文件 |
| 8 | ✅ | ✅ | 删前 grep 确认测试无依赖 |
| 9 | ✅ | ✅ | 注意清理函数内的 import importlib |
| 10 | ✅ | ⚠️ | **🚨 遗漏：必须同步更新 schema 文件** |
| 11 | ✅ | ✅ | 注意联动变更 3 的 EVIDENCE-VT-999 |
| 12 | ✅ | ✅ | 推荐直接删除而非添加说明 |
| 13 | ✅ | ✅ | 实施时联动变更 3 的 ID 常量化 |
