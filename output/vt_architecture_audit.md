# VT 项目架构审计报告

> 审计范围：`src/vibe_tracing/` 全部核心路径 + 关键测试  
> 审计原则：**剃刀原则** — 在不降低业务需求实现的前提下，消除过度设计

---

## 一、`schemas/` 目录的必要性分析

### 结论：**保留，但大幅瘦身，并修复其当前的错误用法**

### 当前事实

`schemas/` 目录下有 5 个 JSON Schema 文件，被 `SchemaValidator` 加载，通过 `jsonschema` 库执行验证。它们同时承担了两件事：

| 功能 | 使用方 | 说明 |
|------|--------|------|
| 结构契约验证（必填字段、枚举、类型） | `SchemaValidator.validate_file/dict` | 合理 |
| 运行时错误提示文本生成 | `claim_loader.py`、`task_loader.py`、`schema_validator.py` | **反模式** |

### 有必要保留的理由

1. **跨语言、跨工具的外部契约**。`task_list.json`、`agent_claims.json` 这些文件是由 AI Agent 手写的，不是 Python 代码生成的。JSON Schema 是目前最合适的机器可验证接口契约，Pydantic 模型无法替代这一功能（Pydantic 无法直接校验 AI 写入磁盘的 JSON 文件而不引入额外代码）。

2. **870 行契约测试**（`test_schema_contracts.py`）。这些测试直接测试 schema 约束，属于有效的回归防护。移除 schemas 会让这层保护消失。

3. **`additionalProperties: false`** 在 `agent_claims` 和 `task_list` 上的应用是合理的：防止 AI Agent 写入幻觉字段。

### 存在的真实问题

#### 问题 1：`description` 字段被滥用为运行时提示文本源

[claim_loader.py L143–155](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/claim_loader.py#L143-L155)、[task_loader.py L151–163](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/task_loader.py#L151-L163) 在业务逻辑中直接解析 schema 文件的 `description` 字段来生成 `【修复指南】` 信息：

```python
# task_loader.py — Loader 直接读 schema 内部结构
schema = self.schema_validator._load_schema("task_list")
task_properties = schema.get("properties", {}).get("tasks", {}).get("items", {}).get("properties", {})

def get_err_msg(field_key: str, base_msg: str) -> str:
    hint = task_properties[field_key].get("description")  # 从 schema description 提取
    ...
```

**问题**：这使得 schema 的 `description` 同时成为文档注释和运行时业务字符串，两个职责合一。改动 schema 描述文字会悄然影响运行时错误提示，没有任何类型安全保护。`resolve_field_hint()` 在 `schema_validator.py` 中有同样问题。

**剃刀建议**：将 `【修复指南】` 文本从 schema `description` 中迁移出来，放入 loader 内部的静态字典，或直接写死到错误消息字符串中。schema 的 `description` 回归其本职：人类可读的文档注释。

#### 问题 2：ID 正则与 `core/ids.py` 完全重复

[agent_claims.schema.json](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/schemas/agent_claims.schema.json) 中：
```json
"claim_id": { "pattern": "^CLAIM-[a-zA-Z0-9_-]+-\\d+$" }
```

[core/ids.py](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/core/ids.py) 中：
```python
("CLAIM", re.compile(rf"^CLAIM-{prefix}-\d+$")),
```

同样的规则写了两遍，且 schema 中的是通配符 `[a-zA-Z0-9_-]+`（接受任何前缀），`ids.py` 中是当前激活前缀的精确匹配。这两者是不一致的：schema 验证会通过 `CLAIM-WRONG-001`，而 `ids.py` 的 `validate_id()` 会拒绝它。**这不是冗余，这是功能不一致。**

**剃刀建议**：接受这种不一致（schema 做结构校验，`ids.py` 做业务级精确校验），但必须在注释中明确说明各自的职责边界，避免后续维护者误以为可以只改一处。

#### 问题 3：`architecture_change_proposal.schema.json` 缺失 — 真实 Bug

[schema_validator.py L97](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/schema_validator.py#L97) 的 `KNOWN_SCHEMAS` 中注册了：
```python
"architecture_change_proposal": "architecture_change_proposal.schema.json",
```

但 `schemas/` 目录中**不存在**这个文件。若任何路径触发对此 schema 的加载，会抛出 `FileNotFoundError`。当前之所以不崩溃，是因为 `architecture_compliance_checker.py` 只在内部调用 `ArchitectureChangeProposalEngine`，没有通过 `SchemaValidator` 验证提案文件。但这是一个隐藏地雷。

---

## 二、架构实现优化点

### 优化点 1：CLI `run_analyze()` 与 `TraceabilityReportBuilder.build()` 的重复执行管道【严重】

这是整个项目最严重的架构问题。

[cli.py L491–539](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/cli.py#L491-L539) 中，CLI 手动运行了完整分析管道：

```python
req_analyzer = RequirementTaskAnalyzer()
req_res = req_analyzer.analyze(...)       # ← 第一次执行

ac_analyzer = AcTestAnalyzer()
ac_res = ac_analyzer.analyze(...)         # ← 第一次执行

claim_analyzer = ClaimEvidenceAnalyzer(project_root)
claim_res = claim_analyzer.analyze(...)   # ← 第一次执行
...
compliance_checker.check(...)             # ← 第一次执行
risk_advisor.generate_risks(...)          # ← 第一次执行
```

然后 [traceability_report_builder.py L90–143](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/traceability_report_builder.py#L90-L143) 的 `build()` 方法**再次完整执行一遍相同的管道**：

```python
req_res = req_analyzer.analyze(...)       # ← 第二次执行
ac_res = ac_analyzer.analyze(...)         # ← 第二次执行
claim_res = claim_analyzer.analyze(...)   # ← 第二次执行
compliance_checker.check(...)             # ← 第二次执行
risk_advisor.generate_risks(...)          # ← 第二次执行
```

**后果**：
1. 每次 `analyze` 命令，所有分析器都执行了两遍（静态分析是幂等的，但浪费且迷惑）
2. CLI 计算的 `gate_decision` 包含 `frozen_risks`，但传入 `report_builder.build()` 的 `extra_risks=frozen_risks` 又被 builder 内部的 risk advisor 再次处理，可能导致风险重复计入
3. CLI 的 `merged_gaps` 和 builder 内部的 `merged_gaps` 是独立计算的，可能产生细微差异

**根因**：`TraceabilityReportBuilder` 被设计为"独立可用的 orchestrator"，而 CLI 又把它当成"最后一步 writer" 来使用，两种用途造成了冲突。

**剃刀建议**：让 `TraceabilityReportBuilder.build()` 接受已计算好的分析结果作为参数（或剥离其内部的分析逻辑），CLI 只调用一次分析管道，将结果传给 builder 写入磁盘并做 schema 验证。

---

### 优化点 2：`EvidenceIndexBuilder` 在 CLI 已加载文件后再次重复加载【中】

[evidence_index_builder.py L26–36](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/evidence_index_builder.py#L26-L36) 在初始化时创建自己的 `RawInputLoader`，在 `build()` 中再次调用 `self.raw_loader.load()`：

```python
manifest = self.raw_loader.load()   # 第二次从磁盘读取所有文件
```

而 CLI 在调用它之前已经完整加载了所有文件（[cli.py L250–289](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/cli.py#L250-L289)）。这意味着每次 `analyze` 命令，`prd.md`、`task_list.json`、`agent_claims.json` 都被**读取了两遍**。

**剃刀建议**：让 `EvidenceIndexBuilder.build()` 接受已解析好的 `task_res`、`claim_res` 等对象作为参数，去掉内部的 `RawInputLoader`。

---

### 优化点 3：`ids._active_prefix` 全局可变状态【中】

[core/ids.py L23](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/core/ids.py#L23) 定义了一个模块级全局变量：

```python
_active_prefix = "VT"
```

整个代码库中有大量这样的访问模式：

```python
from vibe_tracing.core import ids
prefix = ids._active_prefix   # 直接访问私有变量
```

出现在：`schema_validator.py`、`claim_loader.py`、`task_loader.py`、`evidence_index_builder.py`、`traceability_report_builder.py`、`claim_evidence_analyzer.py` 等 6+ 处。

**问题**：
1. 前置下划线表示"私有"，但被广泛外部访问，命名误导性强
2. 模块级可变状态在并发场景（如测试并行）下是线程不安全的
3. 更换前缀后，代码中有多处忘记调用 `ids.set_project_prefix()` 就直接读 `_active_prefix` 的潜在风险

**剃刀建议**：将 `_active_prefix` 重命名为公开的 `active_prefix`，并提供 `get_project_prefix() -> str` 函数替代直接属性访问，便于未来加入线程本地存储。

---

### 优化点 4：CLI `run_analyze()` 使用 `importlib.import_module()` 做已知模块的导入【低】

[cli.py L221–242](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/cli.py#L221-L242) 对所有核心模块使用动态 import：

```python
EvidenceIndexBuilder = importlib.import_module(
    "vibe_tracing.evidence_index_builder"
).EvidenceIndexBuilder
```

共 8 个模块都这样处理。文件顶部已经有正常的静态 import（`from vibe_tracing.raw_input_loader import RawInputLoader` 等）。

这种不一致没有技术理由：这些模块不构成循环依赖（验证方法：`RawInputLoader` 等已在顶部正常导入），动态 import 带来的唯一效果是丢失了类型检查和 IDE 跳转能力。

**剃刀建议**：统一使用顶部静态 import。

---

### 优化点 5：`ToolEvidenceCandidate.evidence_id` 是死字段【低】

[tool_evidence_adapter.py L27–38](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/tool_evidence_adapter.py#L27-L38) 的 `ToolEvidenceCandidate` 有 `evidence_id` 字段，由 `ToolExecutionEngine._next_evidence_id()` 生成（`EVIDENCE-VT-001` 等格式，注意硬编码了 "VT"）。

但在 [evidence_index_builder.py L226–248](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/evidence_index_builder.py#L226-L248) 中：

```python
for cand in report_candidates:
    ev_id = get_next_id()   # ← builder 生成新 ID，完全覆盖 cand.evidence_id
    evidence_dict = {
        "evidence_id": ev_id,   # cand.evidence_id 从未被读取
        ...
    }
```

`ToolEvidenceCandidate.evidence_id` 从未被外部读取或使用。`ToolExecutionEngine._next_evidence_id()` 和 `_evidence_counter` 的唯一用途是填充这个死字段。

**剃刀建议**：从 `ToolEvidenceCandidate` 中移除 `evidence_id` 字段，删除 `_next_evidence_id()` 和 `_reset_counter()` 方法，以及 `_evidence_counter` 属性。

---

### 优化点 6：`run_analyze()` 544 行单函数，Frozen PRD 审计嵌入 CLI【中】

[cli.py L541–625](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/cli.py#L541-L625) 中，Frozen PRD 漂移检测的完整业务逻辑（比较 baseline 与当前 PRD、生成风险记录）内联在 `run_analyze()` 中，约 85 行。这个逻辑属于业务分析层而非 CLI 编排层。

---

## 三、不合理的问题（其余）

### 问题 1：`assess_claim_credibility()` 放在了 Loader 层

[claim_loader.py L270–354](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/claim_loader.py#L270-L354) 中的 `assess_claim_credibility()` 是一个独立的业务分析函数，但它被放在了 `claim_loader.py` 里。`ClaimLoader` 的职责是"加载与验证"，而可信度评估是分析业务逻辑，属于 `traceability/` 层。当前的放置使得调用者（CLI）必须从 loader 模块导入一个分析函数：

```python
from vibe_tracing.claim_loader import ClaimLoader, assess_claim_credibility
```

### 问题 2：风险 ID 硬编码 "VT" 前缀

[claim_evidence_analyzer.py L120](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/traceability/claim_evidence_analyzer.py#L120)：

```python
"risk_id": f"RISK-VT-{risk_counter:03d}",   # 硬编码 VT
```

[risk_advisor.py L107](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/risk_advisor.py#L107)：

```python
"risk_id": f"RISK-VT-{next_counter:03d}",   # 硬编码 VT
```

[cli.py L548–622](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/cli.py#L548-L622)（frozen risks）也全部硬编码 `RISK-VT-xxx`。

这意味着对于任何非 VT 项目，生成的风险 ID 都是错误格式的（`RISK-VT-001` 对一个前缀为 `CapL` 的项目是无意义的）。而系统已经有 `ids._active_prefix` 作为动态前缀，这里没有使用它是一个疏忽。

### 问题 3：`architecture_compliance_checker.py` 在 `check()` 内部再次创建 `RawInputLoader`

[architecture_compliance_checker.py L482–494](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/architecture_compliance_checker.py#L482-L494)：

```python
from vibe_tracing.raw_input_loader import RawInputLoader
raw_loader = RawInputLoader(self.project_root)
required_keys = ["prd", "architecture_constraints", "task_list"]
for key in required_keys:
    resolved_path = raw_loader.get_path(key)
    if not resolved_path.exists():
        ...
```

这是为了检查 `GATE-VT-001`（必需文件是否存在）。但当 `check()` 被调用时，文件必然已经存在（因为调用者已经加载了它们）。这段逻辑在实际运行中永远不会发现缺失文件。这是一个在错误抽象层次执行的检查，同时制造了不必要的文件系统访问和层间耦合（Checker 依赖 Loader）。

### 问题 4：`ArchitectureComplianceChecker` 模块映射硬编码文件名

[architecture_compliance_checker.py L76–103](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/architecture_compliance_checker.py#L76-L103) 和 [L105–138](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/architecture_compliance_checker.py#L105-L138) 用 if-elif 链将文件名映射到模块 ID：

```python
if filename in ("cli.py", "agent_runtime_adapter.py"):
    return "MOD-VT-001", "agent_runtime_adapter"
elif filename in ("raw_input_loader.py", "prd_parser.py", "task_loader.py", "claim_loader.py"):
    return "MOD-VT-002", "raw_input_loader"
...
```

**问题**：任何文件重命名或新文件引入，这个映射会静默失效（文件被当作不属于任何模块，绕过所有约束检查）。没有任何测试保证这个映射的完整性。

**改进方向**：将映射关系迁移到 `architecture_constraints.json` 中（`module_boundaries` 已有 `owned_data` 字段，可扩展为文件路径列表），让约束文件成为真正的 single source of truth。

### 问题 5：`task_list.schema.json` 的 `status_enum`/`priority_enum` 字段定义了类型但 schema 并不校验任务状态与此枚举一致

[task_list.schema.json L37–50](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/schemas/task_list.schema.json#L37-L50) 定义了顶层的 `status_enum` 和 `priority_enum` 数组，但 task 项内部的 `status` 和 `priority` 字段用的是**内联的** `enum: ["todo", "in_progress", "blocked", "done"]`，与顶层的 `status_enum` 字段**没有任何 JSON Schema 引用关系**（JSON Schema 不支持 `$ref` 到同文档的数组内容）。

这意味着 `status_enum` 和 `priority_enum` 字段是装饰性的文档字段，不具备任何验证约束力。用户（AI Agent）可能误以为修改顶层 `status_enum` 会影响验证行为，实际上不会。

### 问题 6：`EVIDENCE-VT-999` 魔法哨兵值散落各处

代码库中出现了 10+ 处 `"EVIDENCE-VT-999"` 作为"无真实证据"的占位符，分布在 `risk_advisor.py`、`architecture_compliance_checker.py`、`cli.py` 等处。这是一个魔法字符串：
- 同样硬编码了 "VT" 前缀
- 没有常量定义，散布各处
- 在 schema 的 `evidence_id` pattern 验证下是合法值（因为 999 满足 `\d+`）

**剃刀建议**：在 `core/` 中定义 `SENTINEL_EVIDENCE_ID = f"EVIDENCE-{active_prefix}-999"` 或类似常量。

---

## 四、优先级汇总

| 编号 | 问题 | 影响 | 难度 | 优先级 |
|------|------|------|------|--------|
| A | 分析管道在 CLI + ReportBuilder 双重执行 | 逻辑正确性隐患 + 性能浪费 | 中 | 🔴 高 |
| B | `architecture_change_proposal.schema.json` 缺失 | 运行时 Bug（隐藏） | 低 | 🔴 高 |
| C | 风险 ID 硬编码 "VT" 前缀 | 多项目支持失效 | 低 | 🟠 中 |
| D | schema `description` 被用作运行时提示文本 | 维护耦合 | 中 | 🟠 中 |
| E | `EvidenceIndexBuilder` 重复加载文件 | 性能 | 低 | 🟠 中 |
| F | `assess_claim_credibility()` 层归属错误 | 代码组织 | 低 | 🟡 低 |
| G | `ToolEvidenceCandidate.evidence_id` 死字段 | 代码膨胀 | 低 | 🟡 低 |
| H | CLI 使用 `importlib` 动态导入已知模块 | 可读性 | 低 | 🟡 低 |
| I | `status_enum`/`priority_enum` 装饰性字段 | 认知误导 | 低 | 🟡 低 |
| J | `EVIDENCE-VT-999` 魔法字符串 | 维护性 | 低 | 🟡 低 |
| K | `ArchitectureComplianceChecker` 文件名映射硬编码 | 静默失效风险 | 高 | 🟠 中 |
| L | `check()` 内部再次实例化 `RawInputLoader` | 层违规 | 低 | 🟡 低 |
