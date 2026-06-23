# Phase 10 代码审查报告

> 审查范围：TASK-VT-067 ~ TASK-VT-076（10 个任务，共 929 个测试）
> 测试结论：**929 passed in 6.75s — ✅ 全绿**

---

## 总体评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 功能完整性 | ⭐⭐⭐⭐☆ | 核心功能均已实现，1 个 DoD 违规项 |
| 设计符合度 | ⭐⭐⭐☆☆ | 存在 2 个明显偏离 refactoring_design.md 的问题 |
| 测试覆盖率 | ⭐⭐⭐⭐⭐ | 所有新模块均有配套测试，质量优秀 |
| 代码质量 | ⭐⭐⭐⭐☆ | 代码清晰，注释到位，TODO 有明确标注 |

---

## ✅ 已正确完成的项目

### TASK-VT-067：db 子包拆分（全部 8 项 DoD 通过）

- `infra/db/` 四件套（schema/loaders/queries/exports）结构清晰，`__init__.py` 完整向上兼容导出
- `requirements` 与 `acceptance_criteria` 两张新表已在 `schema.py` 中正确建立
- `check_requirement_coverage`、`check_claim_evidence`、`get_full_chain` 均已实现
- `check_ac_coverage` 已重构为从 `acceptance_criteria` 表出发（含 legacy 模式 fallback）
- `load_prd()` 同时兼容 PrdParseResult 对象、dict、list 三种形式，鲁棒性良好
- `CoverageStatus` 枚举与 `TASK_STATUS_TO_COVERAGE` 均已在 `infra/config/enums.py` 集中定义

### TASK-VT-068：StalenessTracker + EvidenceMergeResult（全部 4 项 DoD 通过）

- `mark_staleness` 位于 `domain/gate/staleness.py`，属于纯函数，不修改原列表
- `staged_files=None` 时直接返回副本，不标 stale ✓
- `EvidenceMergeResult` 有清晰的字段定义和 `is_empty()` 工具方法

### TASK-VT-069：EvidenceBuilder 三段式重构（全部 5 项 DoD 通过）

- `merge()` 纯内存操作，无 DB 依赖
- `apply()` 正确路由 test/coverage 两类 upsert，并调用 `purge_stale_cache`
- `persist()` 只接收 `output_dir` 和 `merge_result`，不依赖 conn
- `__init__` 只接收 `project_root`，无 conn 参数

### TASK-VT-071：UnifiedContext 解耦 tool_evidence（全部 2 项 DoD 通过）

- `tool_evidence` 字段已从 `UnifiedContext` 完全删除，context.py 的注释中也明确说明了设计意图
- pipeline 中 `tool_evidence = _execute_tools(...)` 作为局部变量正确传递至 `EvidenceBuilder.merge()`

### TASK-VT-072：gates.py 重构（部分通过）

- Gate 1/1b/1c 的 constraints_hash/prd_hash 校验代码已删除 ✓
- `_run_integrity_gates` 已瘦身为仅调用 Gate 2（ghost code），结构清晰

### TASK-VT-073：MergeGateEngine 解耦（全部 6 项 DoD 通过）

- `MergeGateEngine.__init__` 不持有 conn ✓
- `evaluate()` 签名接收 `ghost_files`、`ac_gaps`、`dangling_claims`、`claim_evidence_gaps`、`cov_violations` 等参数，完全无 SQL 访问
- `_load_exclusions` 从 config.json 动态读取 ghost code 排除列表 ✓（DOD-073-04 满足）
- Rule 2-8 均已正确挂载（dangling_claims→blocked，test_failed→blocked，no_tests→warning）

### TASK-VT-074：测试更新（部分通过）

- 3 个 analyzer 测试文件已删净，`analyzers/` 目录只剩 `__init__.py`
- `test_evidence_builder.py` 已完整覆盖 merge/apply/persist 三段
- `test_staleness_tracker.py` 有 13 个精细测试
- `test_evidence_merge_result.py` 有专属测试

### TASK-VT-075/076：包结构重组（全部 DoD 通过）

- domain 七大子包（evidence/gate/compliance/risk/loader/report/governance）已创建
- infra 四大子包（db/logging/config/tools/git）已创建
- `domain/__init__.py` 完整聚合了所有公共接口
- 全量 929 个测试无 ImportError

---

## ❌ 问题项

### 问题 1：`evidence_dicts` 中间层仍然存在（违反 DOD-VT-070-03）

**严重程度：高** — 明确 DoD 违规

**位置：** [`pipeline.py:573-681`](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/cli/analyze/pipeline.py#L573-L681)

```python
# TODO: 过度设计待优化 —— evidence_dicts 构建逻辑（~100 行）应迁移到 domain 层
evidence_dicts = []
# ... ~100 行 Task/Claim/Code/Tool 数据翻译 ...
ev["evidence_id"] = f"EVIDENCE-VT-{idx + 1:03d}"   # ← 顺序编号仍保留
evidence_meta = {"run_id": ..., "evidences": evidence_dicts}
```

DoD 明确要求：
- **DOD-VT-070-03**："不再在 pipeline 中拼装和向后传递 evidence_dicts 嵌套结构"
- **refactoring_design.md §7**："删除 pipeline.py evidence_dicts 构建"、"删除 `EVIDENCE-VT-{idx}` 顺序编号"

**根因分析：** `evidence_meta` 仍被传入 `_build_report_document` 和 `_render_output`，报告层还在消费这个结构。正确做法是让报告层直接从 `get_full_chain(conn)` 获取数据，但 Phase 10 没有完成这步改造。

> [!IMPORTANT]
> 这是本轮重构最大的未完成项。`evidence_dicts` 和 `EVIDENCE-VT-{idx}` 编号与设计原则冲突，已留有 TODO 注释，但不应该被标记为 `done`。

---

### 问题 2：`staleness_tracker.py` 的物理位置偏离设计文档

**严重程度：低**

**设计文档（§4.1）：**
```
domain/
└── staleness_tracker.py   # mark_staleness 纯函数（新建）
```

**实际位置：**
```
domain/gate/staleness.py
```

这是一个合理的技术决策（staleness 逻辑紧挨 gate 包），但与设计文档的顶层路径不一致。`domain/gate/__init__.py` 已重新导出 `mark_staleness`，所以导入路径功能正常。

建议补充一句注释或在设计文档中更新这个路径决策。

---

### 问题 3：`EvidenceMergeResult` 的字段与设计文档规格不一致

**严重程度：低**

**设计文档（§5.6）：**
```python
@dataclass
class EvidenceMergeResult:
    to_upsert: List[ToolEvidenceCandidate]
    to_purge: List[str]
    target_files: List[str]
    evidences_dir: Path
```

**实际实现：**
```python
@dataclass
class EvidenceMergeResult:
    test_results_to_upsert: List[Dict[str, Any]]
    coverage_reports_to_upsert: List[Dict[str, Any]]
    files_to_purge: List[str]
    skipped_evidence: List[Dict[str, Any]]
    stats: Dict[str, int]
```

实际实现更精细（区分 test/coverage 两个 upsert 列表，增加 stats），是比设计文档更好的设计，但两者不一致。由于实现更优，建议更新设计文档的接口规格。

---

### 问题 4：`persist()` 签名与设计文档不符

**严重程度：低**

**设计文档（§5.1）：**
```python
def persist(self, output_dir: Path) -> dict:
```

**实际实现：**
```python
def persist(self, output_dir: Path, merge_result: EvidenceMergeResult) -> Dict[str, str]:
```

实际实现多了一个 `merge_result` 参数，这是必要的（因为 persist 直接从内存写 JSON，不需要再查 DB）。此改动合理，但需要同步更新设计文档。

---

### 问题 5：DOD-VT-070-04 的辅助函数未完整实现

**严重程度：低**

DoD 要求实现 `extract_gaps`、`filter_active`、`merge_gaps`、`compute_staged_items` 四个独立辅助函数。

实际实现将这些逻辑内联在了 `_run_db_analysis` 和 `_run_analysis_phase` 中，未按名称独立提取。功能等价，但不符合 DoD 的字面要求，且降低了这些逻辑的可测试性（`test_pipeline.py` 没有覆盖这些内部逻辑）。

---

### 问题 6：`test_pipeline.py` 测试覆盖度不足（对应 DOD-VT-074-08）

**严重程度：中**

DoD 要求：
> "新增 test_pipeline.py（run_analyze 单元测试：gates_only、pre-commit、错误路径）"

实际的 `test_pipeline.py` 只测试了 `_db_result_to_gaps` 辅助函数（18 个测试），**没有**覆盖：
- `run_analyze` 主函数的 `gates_only` 模式
- `run_analyze` 在 pre-commit 模式下的路径
- `run_analyze` 的异常路径（`Exception` → 返回 1）
- `_run_db_analysis` 集成路径

这意味着 pipeline 主流程基本依赖集成测试而非单元测试覆盖。

---

## 📊 DoD 完成情况汇总

| 任务 | DoD 总数 | 通过 | 待修复 |
|------|---------|------|-------|
| TASK-VT-067 | 8 | 8 | 0 |
| TASK-VT-068 | 4 | 4 | 0 |
| TASK-VT-069 | 5 | 5 | 0 |
| TASK-VT-070 | 6 | 4 | 2（DOD-03 违规；DOD-04 部分未达） |
| TASK-VT-071 | 2 | 2 | 0 |
| TASK-VT-072 | 4 | 3 | 1（DOD-03 gates_only 未打印 Rule 提示） |
| TASK-VT-073 | 6 | 6 | 0 |
| TASK-VT-074 | 8 | 5 | 3（DOD-08 gates_only/pre-commit/error path 未覆盖） |
| TASK-VT-075 | 9 | 9 | 0 |
| TASK-VT-076 | 7 | 7 | 0 |
| **合计** | **59** | **53** | **6** |

---

## 🔧 修复建议（优先级排序）

### P1（必须修复，阻断 done 状态）
1. **DOD-VT-070-03**：从 pipeline.py 中彻底删除 `evidence_dicts` 构建逻辑和 `EVIDENCE-VT-{idx}` 顺序编号。需要同步修改 `_build_report_document` 和 `_render_output` 以接受来自 `get_full_chain(conn)` 的数据。

### P2（应当修复）
2. **DOD-VT-074-08**：补充 `test_pipeline.py` 中对 `run_analyze` 主函数的单元测试（gates_only、pre-commit、Exception 路径）。
3. **DOD-VT-072-03**：`gates_only` 模式应在控制台打印 Rule 1/2 通过而 Rule 3-8 需全量分析的提示（当前只打印了 "Skipping analysis."）。

### P3（可在后续周期处理）
4. 更新 `refactoring_design.md` §4.1 以反映 `staleness.py` 的实际位置（`domain/gate/staleness.py`）
5. 更新 `refactoring_design.md` §5.1/5.6 以反映 `persist()` 签名和 `EvidenceMergeResult` 字段的实际规格
6. 提取 `extract_gaps`、`filter_active`、`merge_gaps` 为独立的可测试函数

---

## 亮点表扬

- **`infra/db/loaders.py::load_prd`** 的多态适配（对象/dict/list）设计优雅，兼容性强
- **`EvidenceBuilder`** 三段式重构方向正确，`apply()` 内的 source_type 路由清晰
- **`domain/__init__.py`** 聚合导出设计使外部调用路径统一，降低迁移成本
- **`mark_staleness`** 纯函数实现规范，测试 `test_does_not_modify_original_lists` 验证了不可变性契约
- **929 个测试全绿**，重构过程中零 regression，工程质量有保证
