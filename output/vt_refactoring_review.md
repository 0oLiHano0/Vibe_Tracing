# VT 代码实现审核报告

> 对照设计文档，逐项核查 13 个变更的实际代码实现。
> 审核方法：阅读源文件、grep 关键模式、追踪数据流。

---

## 结论速览

| 变更 | 实现状态 | 严重程度 |
|------|---------|---------|
| 1 — 消除双重管道 | ✅ 正确 | — |
| 2 — 删除幽灵 schema 注册 | ✅ 正确 | — |
| 3 — ID 工厂函数，消除硬编码 VT | ✅ 正确 | — |
| 4 — `_active_prefix` 公开化 | ✅ 正确 | — |
| 5 — schema description 与提示解耦 | ✅ 正确 | — |
| 6 — EvidenceIndexBuilder 接受已解析结果 | 🔴 **存在 Runtime Bug** | **崩溃级** |
| 7 — assess_claim_credibility 迁移 | ✅ 正确 | — |
| 8 — 删除死字段 evidence_id | ✅ 正确 | — |
| 9 — CLI 静态 import | ✅ 正确（含注意事项）| — |
| 10 — 文件映射配置化 | ✅ 正确 | — |
| 11 — 消除 RawInputLoader 冗余实例 | ✅ 正确 | — |
| 12 — 删除装饰性 status_enum | ✅ 正确 | — |
| 13 — FrozenPrdAuditor 提取 | ✅ 正确 | — |

---

## 🔴 变更 6 — 严重 Runtime Bug：`manifest.config_data` 不存在

### 问题描述

`evidence_index_builder.py:80`（caller-provided 模式）：

```python
config_prefix = manifest.config_data.get("project_prefix", "VT") if manifest else "VT"
```

但 `RawInputManifest`（`raw_input_loader.py:31-37`）的数据结构为：

```python
@dataclass
class RawInputManifest:
    inputs_used: List[InputFileRecord] = field(default_factory=list)
    has_required_errors: bool = False
    error_count: int = 0
```

**`RawInputManifest` 根本没有 `config_data` 属性。**

`config_data` 是 `RawInputLoader` **实例**的属性（`raw_input_loader.py:52`：`self.config_data = self._load_config()`），不是 `load()` 返回的 manifest 对象的属性。

### 触发路径

每次 `vt analyze` 都会执行 CLI `L480-487`：

```python
evidences_index = index_builder.build(
    output_path=index_path,
    tool_evidence_candidates=tool_evidence_candidates,
    prd_record=prd_res,       # 传入了 prd_record
    task_result=task_res,     # 传入了 task_result
    claims_list=claims_list,
    manifest=manifest,        # 传入了 manifest（RawInputManifest 对象）
)
```

由于 `prd_record is not None and task_result is not None`，走 caller-provided 分支，立即在 L80 调用 `manifest.config_data.get(...)` → `AttributeError` → `vt analyze` 崩溃。

### 修复方案

**方案（推荐）：** 由 CLI 直接传入已读取的 `config_prefix`，builder 不再访问 manifest：

```python
# evidence_index_builder.py — build() 新增参数
def build(
    self,
    output_path=None,
    tool_evidence_candidates=None,
    prd_record=None,
    task_result=None,
    claims_list=None,
    manifest=None,
    config_prefix: str = "VT",   # 新增：由 caller 传入
) -> Dict[str, Any]:
    if prd_record is not None and task_result is not None:
        from vibe_tracing.core import ids
        ids.set_project_prefix(config_prefix)   # 直接使用，不依赖 manifest
        ...
```

CLI 侧改为：

```python
evidences_index = index_builder.build(
    ...
    manifest=manifest,
    config_prefix=config_prefix,   # 已在 L240 读取
)
```

---

## ✅ 变更 1 — 消除双重执行管道

**核查结论：正确实现。**

- `traceability_report_builder.py`：65 行，纯 writer，仅 `json.dump` + `schema_validator.validate_dict`，无任何分析器调用 ✅
- `cli.py:566-587`：在 gate 决策后组装 `report_doc` 字典，包含 `requirement_coverage`、`gaps`、`risks`、`architecture_compliance_status` 等所有字段 ✅
- `report_builder.build(report_doc, output_path=report_path)` 调用路径正确 ✅

---

## ✅ 变更 2 — 删除幽灵 schema 注册

**核查结论：正确实现。**

`schema_validator.py:91-97` 的 `KNOWN_SCHEMAS` 字典：

```python
KNOWN_SCHEMAS = {
    "task_list": "task_list.schema.json",
    "agent_claims": "agent_claims.schema.json",
    "evidence_index": "evidence_index.schema.json",
    "traceability_report": "traceability_report.schema.json",
    "architecture_constraints": "architecture_constraints.schema.json",
}
```

`architecture_change_proposal` 键已删除。grep 确认：`schema_validator.py` 中无任何 `architecture_change_proposal` 字符串 ✅

---

## ✅ 变更 3 — ID 工厂函数，消除硬编码 VT

**核查结论：正确实现。**

`core/ids.py:65-77` 新增：

```python
def make_risk_id(counter: int) -> str:
    return f"RISK-{get_project_prefix()}-{counter:03d}"

def make_evidence_id(counter: int) -> str:
    return f"EVIDENCE-{get_project_prefix()}-{counter:03d}"

def sentinel_evidence_id() -> str:
    return f"EVIDENCE-{get_project_prefix()}-999"
```

全局 grep 验证：
- `src/` 目录下 `RISK-VT` 出现：仅 `ids.py:16` 的 docstring 注释，无业务代码硬编码 ✅
- `src/` 目录下 `EVIDENCE-VT` 出现：仅 `ids.py:15` 的 docstring 注释 ✅

---

## ✅ 变更 4 — `_active_prefix` 公开化

**核查结论：正确实现。**

`core/ids.py:23`：`active_prefix = "VT"`（去掉了下划线）
`core/ids.py:60-62`：新增 `get_project_prefix()` getter
`set_project_prefix()` 内部：`global active_prefix`（同步修改）

全局 grep 验证：`src/` 目录下 `_active_prefix` 零结果——所有 8 处外部访问已全部替换为 `ids.get_project_prefix()` ✅

---

## ✅ 变更 5 — schema description 与运行时提示解耦

**核查结论：正确实现。**

- `templates/field_hints.json` 已创建（22 行），结构与设计文档完全一致 ✅
- 使用 `{PROJECT_PREFIX}` 占位符（单花括号，非双花括号），与 `ids.get_project_prefix()` 替换逻辑匹配 ✅
- `task_loader.py:17-25`：`_HINTS_PATH` 模块级常量 + `_task_field_hints` 模块级加载 ✅
- `claim_loader.py:17-25`：同上，加载 `agent_claims` hints ✅
- `get_err_msg()` 在两个 loader 中均使用 `ids.get_project_prefix()` 而非 `ids._active_prefix` ✅
- `schema_validator.py`：`resolve_field_hint()` 已完全删除（grep 确认零结果）✅

**注意事项（非 bug）：** `_task_field_hints` 和 `_claim_field_hints` 在模块导入时就加载文件。若 `templates/field_hints.json` 不存在，`import vibe_tracing.task_loader` 本身就会抛 `FileNotFoundError`。这是已知的权衡，不影响正常使用。

---

## ✅ 变更 7 — `assess_claim_credibility` 迁移

**核查结论：正确实现。**

- `traceability/claim_credibility.py` 已创建（100 行），函数签名与原版完全一致 ✅
- `claim_loader.py`：全文无 `assess_claim_credibility`（grep 确认零结果）——旧函数已完全删除 ✅
- `cli.py:23`：`from vibe_tracing.traceability.claim_credibility import assess_claim_credibility` ✅

---

## ✅ 变更 8 — 删除 `ToolEvidenceCandidate.evidence_id` 死字段

**核查结论：正确实现。**

`tool_evidence_adapter.py` 全文 grep `evidence_id`：**零结果** ✅

`evidence_index_builder.py:254`：`ev_id = get_next_id()` 由 builder 侧统一分配，不依赖 `cand.evidence_id` ✅

---

## ✅ 变更 9 — CLI 静态 import

**核查结论：正确实现，保留一处无关的 importlib 属正常。**

`cli.py:23-33` 所有核心模块已改为静态 import：
- `EvidenceIndexBuilder`、`TraceabilityReportBuilder`、`MergeGateEngine`
- `ArchitectureComplianceChecker`、`RequirementTaskAnalyzer`、`AcTestAnalyzer`
- `ClaimEvidenceAnalyzer`、`FrozenPrdAuditor`、`RiskAdvisor`、`DashboardRenderer`

`cli.py:13` 保留 `import importlib.resources as pkg_resources`——这是 `run_init()` 读取 package 内置模板文件所需，与"动态模块加载"无关，保留正确 ✅

`tool_evidence_adapter` 的 import 在 `cli.py:407` 仍是函数内部 lazy import：`from vibe_tracing.tool_evidence_adapter import ToolExecutionEngine`。这是因为工具执行引擎在非 draft 且有约束时才加载——属于有意的延迟加载，可接受。

---

## ✅ 变更 10 — 架构合规检查器文件映射配置化

**核查结论：正确实现，数据已验证。**

`architecture_compliance_checker.py:61-88`：`_get_module_for_path()` 已改为遍历 `self.constraints.get("module_boundaries", [])` 并查找 `owned_files` ✅

`architecture_compliance_checker.py:89-118`：`_get_module_for_import()` 从 `owned_files` 派生，使用 `owned.removesuffix(".py") == sub` 匹配 ✅

`boundary["name"]` 字段——**已验证正确**：grep `docs/architecture_constraints.json` 确认每个 module boundary 使用 `"name"` 字段（如 `"name": "agent_runtime_adapter"`），与代码中 `boundary["name"]` 一致 ✅

`architecture_constraints.schema.json` 包含 `owned_files` 字段定义（grep 确认 L144），schema 验证不会拒绝此新字段 ✅

`docs/architecture_constraints.json` 中 10 个 module_boundary 均已添加 `owned_files` 数组 ✅

---

## ✅ 变更 11 — 消除 check() 内部冗余 RawInputLoader

**核查结论：正确实现。**

`architecture_compliance_checker.py:463-475`：GATE-VT-001 检查使用直接路径构造：

```python
required_paths = {
    "prd": self.project_root / "docs" / "prd.md",
    "architecture_constraints": self.constraints_path,
    "task_list": self.project_root / "docs" / "task_list.json",
}
```

无 `RawInputLoader` 实例化 ✅

L490：`"evidence_id": ids.sentinel_evidence_id()` 使用工厂函数，联动变更 3 ✅

---

## ✅ 变更 12 — 删除装饰性 status_enum / priority_enum

**核查结论：正确实现。**

grep `task_list.schema.json` 中 `status_enum`：**零结果** ✅

---

## ✅ 变更 13 — FrozenPrdAuditor 提取

**核查结论：正确实现，联动正确。**

- `traceability/frozen_prd_auditor.py` 已创建（111 行）✅
- 全部风险 ID 使用 `ids.make_risk_id(901)`、`ids.make_risk_id(902)`、`ids.make_risk_id(910..N)` ✅
- 全部哨兵证据 ID 使用 `ids.sentinel_evidence_id()` ✅
- `cli.py:31`：静态 import `FrozenPrdAuditor` ✅
- `cli.py:554-556`：调用正确 ✅

---

## 需要立即修复的 Bug

### 修复位置：[evidence_index_builder.py](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/evidence_index_builder.py#L78-L86)

将 L80 的 `manifest.config_data.get(...)` 改为接受显式 `config_prefix` 参数：

**evidence_index_builder.py** — build() 签名修改：
```python
def build(
    self,
    output_path: Optional[Path] = None,
    tool_evidence_candidates: Optional[List] = None,
    prd_record: Optional[Any] = None,
    task_result: Optional[Any] = None,
    claims_list: Optional[List] = None,
    manifest: Optional[Any] = None,
    config_prefix: str = "VT",   # 新增参数
) -> Dict[str, Any]:
    if prd_record is not None and task_result is not None:
        from vibe_tracing.core import ids
        ids.set_project_prefix(config_prefix)
        prd_res = prd_record
        task_res = task_result
        claims = claims_list or []
        task_list_record = None
        claims_record = None
        if manifest:
            records_dict = {r.file_key: r for r in manifest.inputs_used}
            task_list_record = records_dict.get("task_list")
            claims_record = records_dict.get("agent_claims")
    else:
        # 独立模式不变...
```

**cli.py** — index_builder.build() 调用处新增一个参数：
```python
evidences_index = index_builder.build(
    output_path=index_path,
    tool_evidence_candidates=tool_evidence_candidates,
    prd_record=prd_res,
    task_result=task_res,
    claims_list=claims_list,
    manifest=manifest,
    config_prefix=config_prefix,   # 新增：传入已读取的 prefix
)
```

`config_prefix` 在 CLI `L240` 已有：`config_prefix = raw_loader.config_data.get("project_prefix", "VT")`。
