# 阶段 6 修复方案

## 背景

代码审查发现 2 个严重级 bug，均导致数据流断裂，门禁判定不可信。同步审查了 7 个相关测试文件，发现测试层整体性地使用与生产环境不一致的数据值，系统性掩盖了 bug。

---

## 修复步骤

### 步骤 1：修复覆盖率缓存路径 ✅ 已完成

- **文件**：`src/vibe_tracing/infra/db/loaders.py`
- **行号**：167
- **变更**：`cache_path.parent` → `cache_path.parent.parent`

```python
# 修改前
if source_path and not (cache_path.parent / source_path).is_file():
# 修改后
if source_path and not (cache_path.parent.parent / source_path).is_file():
```

- **根因**：`cache_path = Path(project_root/output/evidences)`，`parent` = `output/`，拼出 `output/src/...` 永不命中
- **影响**：覆盖率缓存恢复可用，跨次运行的覆盖率数据得以继承

> **实际执行**：`loaders.py:167` 修改完成，相关测试 2 tests passed。变更量 1 行。

### 步骤 2：修复 SQL outcome 字面量（3 处） ✅ 已完成

- **文件**：`src/vibe_tracing/infra/db/queries.py`
- **变更**：

| 行号 | 函数 | 修改前 | 修改后 |
|------|------|--------|--------|
| 48 | `check_ac_coverage` | `tr.outcome != 'passed'` | `tr.outcome != 'covered'` |
| 78 | `check_requirement_coverage` | `tr.outcome != 'passed'` | `tr.outcome != 'covered'` |
| 102 | `check_claim_evidence` | `tr.outcome = 'passed'` | `tr.outcome = 'covered'` |

- **根因**：SQL 硬编码了 pytest 原生 outcome `'passed'`，但写入侧已将 pytest outcome 映射为 CoverageStatus 枚举值（`'covered'` / `'violated'` 等）。`test_results.outcome` 列中 `'passed'` 永不出现——`tr.outcome != 'passed'` 恒为 true，`tr.outcome = 'passed'` 恒为 false。
- **影响**：有通过测试的 AC/需求/Claim 全部被误判为 `test_failed`

> **实际执行**：`queries.py` 3 处 `'passed'` → `'covered'` 修改完成。生产代码修复正确，无需额外变更。注意：当前 SQL CASE WHEN 中使用的是字面量 `'covered'`，未引用 `CoverageStatus.COVERED.value`——此为最低修复策略，详见末尾"实际执行记录"章节 Category 2 发现。

### 步骤 3：测试文件清理

两个 bug 之所以逃过现有测试，根因是测试数据与生产数据使用了不同的值域——测试直接写 `"passed"/"failed"`，生产写入 `"covered"/"violated"`。需统一测试数据到 CoverageStatus 值域，同时清理架构残留和无效测试。

#### 3a. test_evidence_builder.py — 修正测试数据值域 ✅ 已完成

- **文件**：`tests/test_evidence_builder.py`
- **问题**：全部 12 处 `status="passed"` / `outcome` 断言使用 `"passed"` 或 `"failed"`（行 57、68、102、119、127、147、160、192、247、290、303）。这些值绕过 CoverageStatus 枚举，模拟了不存在的"pytest 原生 outcome 直达 DB"路径。
- **变更**：
  - `status="passed"` → `status=CoverageStatus.COVERED.value`（即 `"covered"`）
  - `status="failed"` → `status=CoverageStatus.VIOLATED.value`（即 `"violated"`）
  - 对应断言同步更新：`assert ... outcome == "covered"` 等
- **验证**：使用 CoverageStatus 创建候选对象后，builder merge/apply 行为与生产一致

> **实际执行**：11 处值域修正（`status` 和 `outcome` 断言），12 tests passed。变更量中等。

#### 3b. test_db_schema.py — 修正测试数据值域 ✅ 已完成

- **文件**：`tests/test_db_schema.py`
- **问题**：所有 `upsert_test_result` 调用均使用 `"passed"` 或 `"failed"` 作为 outcome（行 61、64、67、70、109、115、142、148、182、202、208、234、240）。共 14 处。
- **变更**：
  - `outcome="passed"` → `outcome=CoverageStatus.COVERED.value`
  - `outcome="failed"` → `outcome=CoverageStatus.VIOLATED.value`
- **验证**：upsert 和 purge 语义不变（INSERT OR REPLACE 对任何值均等），值域修正后与生产对齐

> **实际执行**：13 处值域修正（`outcome` 参数），9 tests passed。变更量中等。

#### 3c. test_db_query_functions.py — 整体重构 ✅ 已完成

- **文件**：`tests/test_db_query_functions.py`
- **当前规模**：约 1200 行，50+ 测试函数
- **问题清单**：

  | # | 问题 | 位置 | 处理 |
  |---|------|------|------|
  | 1 | USING_REAL_IMPL fallback 机制 | 行 1-207 | 删除。代码库已稳定，无需 fallback；fallback SQL 语法与真实 queries.py 不同步，是过渡期残留 |
  | 2 | 查询测试数据使用 `"passed"/"failed"` | 30+ 处 upsert 调用 | 全部替换为 CoverageStatus 值 |
  | 3 | load_initial_cache 测试路径错误 | 行 1149-1168 `test_adversarial_load_initial_cache_missing_source_path` | 修正：`cache_dir = tmp_path / "output" / "evidences"`，源文件建在 `tmp_path / source_path`（parent.parent），验证文件存在时记录被加载、不存在时被跳过 |
  | 4 | 过度工程化—Tier 1-4 框架 | 整个文件 | 精简。9 个查询函数 ~72 个测试显著过度，将同模式变体合并为参数化测试（如 `_empty_database` 5 个重复 → 1 个参数化） |
  | 5 | 重复测试 | adversarial 测试（行 992、1013 等）与 Tier 2 边界测试（行 557、635 等）高度重复 | 合并。adversarial 测试中独有的断言保留，冗余部分删除 |
  | 6 | fallback 实现中的硬编码 `'passed'` | 行 111-112、135 | 随 fallback 机制一并删除（问题 1） |

- **变更**：
  1. 删除 `USING_REAL_IMPL` 门控及所有 fallback 实现（行 1-207），直接 `from vibe_tracing.infra.db import ...` 所有函数
  2. 全局替换 `upsert_test_result(conn, ..., "passed", ...)` → `upsert_test_result(conn, ..., "covered", ...)`，`"failed"` → `"violated"`
  3. 全部断言中的 `"passed"` / `"failed"` 同步替换为 `"covered"` / `"violated"`
  4. 修正 `test_adversarial_load_initial_cache_missing_source_path`：cache_dir 设为 `tmp_path / "output" / "evidences"`，源文件建在 `tmp_path / "src/file.py"`
  5. 精简重复/过度测试，合并为参数化

> **实际执行**：整体重构完成。删除 fallback 机制（~200 行），28 处值域修正，修正 `load_initial_cache` 路径测试（`cache_dir = tmp_path / "output" / "evidences"`），合并空数据库参数化（5 个重复 → 1 个 `@pytest.mark.parametrize`），去重 adversarial/Tier2 冗余测试。93 tests passed。变更量巨大。

#### 3d. test_db_import.py — 删除 ✅ 已完成

- **文件**：`tests/test_db_import.py`
- **问题**：架构残留。
  - 类名/注释使用 "Layer 1 Format Validation" / "Layer 2 Relation Validation"——代码库中已不存在此组织方式
  - 仅 3 个测试（`load_tasks`、`check_dangling_claims`、`check_ghost_code`），均为非阶段 6 函数，且逻辑已被 `test_db_query_functions.py` 覆盖
  - 导入了 `upsert_test_result` 但未使用
- **变更**：直接删除

> **实际执行**：文件已删除。全量测试 881 tests passed（无回归）。

### 步骤 4：验证 ✅ 已完成

- 运行 `pytest tests/test_evidence_builder.py tests/test_db_schema.py tests/test_db_query_functions.py tests/test_evidence_merge_result.py -v`，确认全部通过
- 运行全量测试套件，确认无回归
- 手工验证端到端流程：`vt analyze` → 检查阶段 7 gaps 中 `test_failed` 仅针对实际失败的测试出现

> **实际执行**：全量 881/881 tests passed，无回归。e2e `vt analyze` 验证：无 "Error building evidence" 错误，无 `test_failed` 误报（仅真正失败的测试被标记为 `test_failed`），覆盖率缓存 JSON 生成正确（`output/evidences/test_results.json` + `coverage_reports.json`）。

---

## 关联影响

- Bug 2 修复后，`_db_result_to_gaps()`（`pipeline.py:425-553`）中 `test_failed` 分支将首次被正确触发。此前这些代码路径可被执行但输入数据因 bug 不可信。
- `MergeGateEngine` 的 blocked 判定可能发生变化——此前因测试被误判失败而导致的不当阻断将消失。
- 测试值域统一后，未来 `test_results.outcome` 字段的任何变更都能被测试捕获，不再出现"测试通过但生产错误"的假阴性。

---

## 实际执行记录

### 执行概览

| 步骤 | 描述 | 变更量 | 测试结果 |
|------|------|--------|----------|
| 1 | `cache_path.parent` → `cache_path.parent.parent` | 1 行 | 2 tests passed |
| 2 | 3 处 `'passed'` → `'covered'` | 3 行 | 生产代码修复正确 |
| 3a | test_evidence_builder.py 值域修正 | 11 处 | 12 tests passed |
| 3b | test_db_schema.py 值域修正 | 13 处 | 9 tests passed |
| 3c | test_db_query_functions.py 整体重构 | ~200 行删除 + 28 处修正 | 93 tests passed |
| 3d | test_db_import.py 删除 | 整个文件 | 全量无回归 |
| 4 | 全量验证 | — | 881/881 passed |

### Category 1 发现（已修复）

上述 6 个步骤涵盖的全部问题，均为测试与生产值域不一致导致的假阴性或数据流断裂，已全部修复。

### Category 2 发现（业务代码异常，仅记录未修改）

以下问题在审查过程中发现，属于业务代码层面的设计改进空间，不在本次最小修复范围内：

| # | 发现 | 位置 | 说明 |
|---|------|------|------|
| C2-1 | SQL CASE WHEN 使用字面量字符串，未引用 CoverageStatus 枚举 | `infra/db/queries.py` 全部 `check_*` 函数 | 当前 SQL 中直接写 `'covered'`、`'test_failed'`、`'no_task_for_ac'` 等字符串。`refactoring_design.md §6.3` 要求"必须引用 CoverageStatus 枚举，禁止硬编码字符串"——当前实现是"最低修复"（改值不改引用方式）。若未来 CoverageStatus 枚举值变更，SQL 字面量不会同步报错，需手工排查。建议后续用 `CoverageStatus.COVERED.value` 替换 SQL 中的字面量。 |
| C2-2 | ToolEvidenceCandidate.status 类型注解为 `str`，未约束为 CoverageStatus 值域 | `domain/evidence/candidate.py:18` | 注解 `status: str` + 注释 `# CoverageStatus enum value` 无法在类型检查层面阻止传入非法字符串。建议注解改为 `status: str` 并在 docstring 中明确值域，或使用 `Literal` 类型。 |
| C2-3 | load_initial_cache 路径解析假设 cache_dir 深度固定 | `infra/db/loaders.py:167` | `cache_path.parent.parent` 假设 `cache_dir` 在 `{project_root}/output/evidences/` 深度。若传入其他深度的 cache_dir，parent 解析将指向错误目录。建议改为接受显式 `project_root` 参数。 |
| C2-4 | 阶段 6 异常捕获未使用 OperationalLogger | `cli/analyze/pipeline.py:359-361` | `except Exception as exc: print(..., file=sys.stderr)` 未调用 `vt_logger.exception()`，异常信息不会写入 JSON Lines 运行日志。后续排查阶段 6 错误时只能依赖终端输出，无法从结构化日志定位。 |
| C2-5 | load_initial_cache 测试结果默认值 `"failed"` 未对齐 CoverageStatus | `infra/db/loaders.py:145` | `outcome = rec.get("outcome", "failed")` — 当 JSON 缓存记录的 outcome 字段缺失时，默认回退为 `"failed"`。但 `test_results.outcome` 列存储的是 CoverageStatus 枚举值（`"covered"`/`"violated"` 等），`"failed"` 不是合法值。若缓存文件因历史原因缺少 outcome 字段，写入的值将破坏下游 SQL 查询的 `tr.outcome` 比较逻辑。应改为 `CoverageStatus.VIOLATED.value`（即 `"violated"`）。 |
| C2-6 | load_initial_cache 覆盖率默认值 `"violated"` 未改枚举引用 | `infra/db/loaders.py:173` | `status = rec.get("status", "violated")` — 行 145 同类问题（C2-5）已修，行 173 遗漏。功能等价（`"violated" == CoverageStatus.VIOLATED.value`），纯风格不一致。应改为 `CoverageStatus.VIOLATED.value`。 |
| C2-7 | 外层 except Exception 未接入 OperationalLogger | `cli/analyze/pipeline.py:423-425` | `run_analyze()` 的全局兜底 `except Exception` 仅 `print()` 不调用 `vt_logger.exception()`。C2-4 只修了阶段 6 内层（行 359），外层是阶段 2-8 的全局捕获点——任何非 `_GateBlocked` 异常都不会写入结构化日志。`vt_logger` 已在阶段 1 初始化，直接可用。 |

### 总结

6 个步骤全部完成，核心 Bug（覆盖率缓存路径错误 + SQL outcome 值域错误）已修复，测试层值域已与生产对齐。发现 7 项 Category 2 设计改进点——其中 C2-1~C2-5 已修复，C2-6~C2-7 待处理。

---

## Category 2 修复方案

### C2-1：SQL CASE WHEN 引入 CoverageStatus 枚举引用

**位置**：`infra/db/queries.py` 全部 `check_*` 函数的 SQL 字符串

**现状**：SQL 中直接硬编码了 `'covered'`、`'violated'`、`'verified'` 等字面量。虽然步骤 2 已将值从 `'passed'` 纠正为 `'covered'`，但 SQL 字符串中仍是字面量而非 Python 枚举引用。若 CoverageStatus 枚举值后续变更，SQL 不会同步报错。

**约束**：`refactoring_design.md` §6.3 明确要求——"所有 check_* 的 SQL CASE WHEN 必须引用 CoverageStatus 枚举，禁止硬编码字符串"。

**分析：SQL 字面量分为两类**

SQL 中出现的字符串分两种性质，需区别对待：

| 类别 | 示例 | 是否 CoverageStatus 成员 | 是否需改为枚举引用 |
|------|------|--------------------------|---------------------|
| **A: CoverageStatus 值** | `'covered'`、`'violated'` | 是（`COVERED` / `VIOLATED`） | **是** |
| **B: SQL 内部状态标签** | `'no_task_for_ac'`、`'test_failed'`、`'task_missing'`、`'verified'` 等 | 否，由 `_db_result_to_gaps()` 消费 | 否。但这些标签中 `'verified'` 语义等同于 `'covered'`（均表示"无问题"），在 HAVING 子句中承担相同角色，应统一为 `CoverageStatus.COVERED.value` |

**A 类字面量全量清单**（需替换为 `CoverageStatus.XXX.value`）：

| 行号 | 函数 | 当前字面量 | 替换为 | SQL 位置 |
|------|------|-----------|--------|----------|
| 12 | `check_coverage_violations` | `'violated'` | `CoverageStatus.VIOLATED.value` | WHERE |
| 48 | `check_ac_coverage` | `'covered'`（`tr.outcome !=`） | `CoverageStatus.COVERED.value` | CASE WHEN（步骤 2 已修值，改引用） |
| 49 | `check_ac_coverage` | `'covered'`（ELSE） | `CoverageStatus.COVERED.value` | CASE WHEN |
| 60 | `check_ac_coverage` | `'covered'`（HAVING） | `CoverageStatus.COVERED.value` | HAVING |
| 78 | `check_requirement_coverage` | `'covered'`（`tr.outcome !=`） | `CoverageStatus.COVERED.value` | CASE WHEN（步骤 2 已修值，改引用） |
| 79 | `check_requirement_coverage` | `'covered'`（ELSE） | `CoverageStatus.COVERED.value` | CASE WHEN |
| 88 | `check_requirement_coverage` | `'covered'`（HAVING） | `CoverageStatus.COVERED.value` | HAVING |
| 102 | `check_claim_evidence` | `'covered'`（`tr.outcome =`） | `CoverageStatus.COVERED.value` | CASE WHEN（步骤 2 已修值，改引用） |
| 103 | `check_claim_evidence` | `'verified'`（ELSE） | `CoverageStatus.COVERED.value` | CASE WHEN（语义对齐，`'verified'` → `'covered'`） |
| 110 | `check_claim_evidence` | `'verified'`（HAVING） | `CoverageStatus.COVERED.value` | HAVING（随 ELSE 同步变更） |

共 10 处。其中行 48/78/102 已在步骤 2 将值从 `'passed'` 改为 `'covered'`，本次将其从字面量改为 f-string 嵌入枚举引用。行 103/110 的 `'verified'` 变更为 `'covered'` 将同步影响 HAVING 子句和 `_db_result_to_gaps()` 对 `claim_evidence` 结果的处理——需确认 `_db_result_to_gaps:519-551` 中不依赖 `'verified'` 字面量（当前已不依赖，它只消费 `'task_missing'`、`'task_not_done'`、`'no_tests'`、`'test_missing'`、`'test_failed'`，不消费 `'verified'`）。

**修复策略**：方案 A——SQL 字符串用 f-string 嵌入 `CoverageStatus.XXX.value`。枚举值固定，无 SQL 注入风险。

**步骤**：
1. 在 `queries.py` 顶部确认已导入 `CoverageStatus`
2. 将上述 10 处字面量替换为 f-string 引用（SQL 字符串改为 f-string 格式）
3. 确认 `_db_result_to_gaps()` 不依赖 `'verified'` 字面量（CASE WHEN ELSE 标签变更不影响其分支逻辑）
4. 运行 `pytest tests/test_db_query_functions.py -v`，全部通过

---

### C2-2：ToolEvidenceCandidate.status 运行时值域校验

**位置**：`domain/evidence/candidate.py:18`

**现状**：
```python
status: str  # CoverageStatus enum value
```
注解为 `str`，注释说明应为 CoverageStatus 枚举值，但无运行时强制校验。

**修复**：在模块级定义合法状态常量，`__post_init__` 中引用。`frozenset` 避免每次构造时重复构建集合（`ToolEvidenceCandidate` 在 `execute_tool` 热路径上每个测试用例创建一个实例）：

```python
from vibe_tracing.infra.config.enums import CoverageStatus

_VALID_STATUSES: frozenset = frozenset(v.value for v in CoverageStatus)

@dataclass
class ToolEvidenceCandidate:
    status: str

    def __post_init__(self):
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                f"status must be a CoverageStatus value, got {self.status!r}"
            )
```

不采用 `Literal` 类型注解——Literal 需枚举全部值，与 CoverageStatus 枚举成员重复维护，变更时易遗漏。

**步骤**：
1. 在 `candidate.py` 中导入 `CoverageStatus`
2. 模块级定义 `_VALID_STATUSES: frozenset = frozenset(v.value for v in CoverageStatus)`
3. 为 `ToolEvidenceCandidate` 添加 `__post_init__` 方法
4. 运行 `pytest tests/test_evidence_builder.py tests/test_tool_execution.py -v`，全部通过

---

### C2-3：load_initial_cache 显式接收 project_root 参数

**位置**：`infra/db/loaders.py:167`

**现状**：
```python
def load_initial_cache(conn, cache_dir: str):
    cache_path = Path(cache_dir)
    ...
    if source_path and not (cache_path.parent.parent / source_path).is_file():
```

`cache_path.parent.parent` 假设 `cache_dir` 深度固定为 `{project_root}/output/evidences/`（3 层）。若未来改为其他目录结构（如直接传 `project_root/evidences/`），路径解析将出错。

**修复**：函数签名增加 `project_root` 参数，移除对目录深度的隐式假设。同时将 `cache_dir` 类型注解从 `str` 修正为 `Path`（调用方 `builder.py:99` 传入的是 `Path` 对象）：

```python
def load_initial_cache(conn: sqlite3.Connection, cache_dir: Path, project_root: Path) -> None:
    cache_path = Path(cache_dir)  # Path(cache_dir) 对 Path 输入是 no-op
    ...
    if source_path and not (project_root / source_path).is_file():
```

**调用方同步修改**（`builder.py:99`）：
```python
# 修改前
load_initial_cache(conn, evidences_dir)

# 修改后
load_initial_cache(conn, evidences_dir, self.project_root)
```

**测试文件同步修改**（`test_db_query_functions.py`，2 处）：

| 行号 | 测试函数 | 修改前 | 修改后 |
|------|----------|--------|--------|
| 875 | `test_adversarial_load_initial_cache_invalid_json` | `load_initial_cache(conn, str(cache_dir))` | `load_initial_cache(conn, cache_dir, tmp_path)` |
| 950 | `test_adversarial_load_initial_cache_missing_source_path` | `load_initial_cache(conn, str(cache_dir))` | `load_initial_cache(conn, cache_dir, tmp_path)` |

`cache_dir` 不再需 `str()` 包装；`tmp_path` 即为 project_root（测试中 cache_dir = `tmp_path / "output" / "evidences"`，project_root = `tmp_path`）。

**步骤**：
1. 修改 `loaders.py:load_initial_cache()` 签名：`cache_dir: str` → `cache_dir: Path`，新增 `project_root: Path`
2. 行 167 改为 `project_root / source_path`
3. 修改 `builder.py:99` 调用点传入 `self.project_root`
4. 修改 `test_db_query_functions.py:875` 和 `:950` 两处调用：去掉 `str()`，新增 `tmp_path`
5. 运行 `pytest tests/ -v -k "load_initial_cache or evidence"`，全部通过

---

### C2-4：阶段 6 异常捕获接入 OperationalLogger

**位置**：`cli/analyze/pipeline.py:359-361`

**现状**：
```python
except Exception as exc:
    print(f"Error building evidence: {exc}", file=sys.stderr)
    return 1
```

`vt_logger` 已在阶段 6 之前初始化（行 204-209），但异常分支未调用 `vt_logger.exception()`。

**修复策略**：在 print 之后增加日志记录：

```python
except Exception as exc:
    print(f"Error building evidence: {exc}", file=sys.stderr)
    try:
        vt_logger.exception("evidence_build_failed",
                           "Error building evidence in stage 6",
                           exc=exc)
    except Exception:
        pass  # logger 自身异常不应影响退出码
    return 1
```

**步骤**：
1. 修改 `pipeline.py:359-361`，增加 `vt_logger.exception()` 调用
2. 外层 `try/except` 守卫 logger 自身异常
3. 运行 `pytest tests/ -v`，确认无回归
4. 确认 JSON Lines 日志中 `evidence_build_failed` 事件在异常场景下正确记录

---

### C2-5：load_initial_cache 测试结果默认值对齐 CoverageStatus

**位置**：`infra/db/loaders.py:145`

**现状**：
```python
outcome = rec.get("outcome", "failed")
```

当 JSON 缓存记录的 `outcome` 字段缺失时，默认回退为 `"failed"`。但 `test_results.outcome` 列存储的是 CoverageStatus 枚举值（`"covered"` / `"violated"` 等），`"failed"` 不是合法值。若缓存文件因历史原因或手动编辑导致 outcome 字段缺失，写入的值将破坏下游 SQL 的 `tr.outcome` 比较逻辑——`"failed"` 既不是 `"covered"`（判定为通过）也不是其他 CoverageStatus 值，行为不可预期。

**修复策略**：默认值改为 `CoverageStatus.VIOLATED.value`（`"violated"`）——语义上，"outcome 缺失"应视为异常状态，等同于失败：

```python
outcome = rec.get("outcome", CoverageStatus.VIOLATED.value)
```

**步骤**：
1. 在 `loaders.py` 顶部确认已导入 `CoverageStatus`
2. 行 145：`"failed"` → `CoverageStatus.VIOLATED.value`
3. 运行 `pytest tests/ -v -k "load_initial_cache"`，全部通过

---

### C2-6：load_initial_cache 覆盖率默认值改枚举引用

**位置**：`infra/db/loaders.py:173`

**现状**：
```python
status = rec.get("status", "violated")
```

C2-5 已将行 145 的 `"failed"` → `CoverageStatus.VIOLATED.value`，行 173 遗漏。功能等价（值相同），仅风格不一致。

**修复**：
```python
status = rec.get("status", CoverageStatus.VIOLATED.value)
```

**步骤**：
1. 行 173：`"violated"` → `CoverageStatus.VIOLATED.value`
2. 运行 `pytest tests/ -v -k "load_initial_cache"`，全部通过

---

### C2-7：外层 except Exception 接入 OperationalLogger

**位置**：`cli/analyze/pipeline.py:423-425`

**现状**：
```python
except Exception as exc:
    print(f"Unexpected error running analyze command: {exc}", file=sys.stderr)
    return 1
```

C2-4 只修了阶段 6 内层 `except`（行 359-361）。此处是 `run_analyze()` 全局兜底——捕获阶段 2-8 的任何非 `_GateBlocked` 异常。`vt_logger` 已在阶段 1 初始化（行 204-209），此处可用。

**修复**（与 C2-4 同模式）：
```python
except Exception as exc:
    print(f"Unexpected error running analyze command: {exc}", file=sys.stderr)
    try:
        vt_logger.exception("run_analyze_failed",
                           "Unexpected error in analyze pipeline",
                           exc=exc)
    except Exception:
        pass
    return 1
```

**步骤**：
1. 在 `except Exception` 分支中增加 `vt_logger.exception()` 调用
2. 外层 `try/except` 守卫 logger 自身异常
3. 运行 `pytest tests/ -v`，确认无回归

---

### Category 2 修复步骤总览

| 步骤 | 描述 | 涉及文件 | 状态 |
|------|------|----------|------|
| C2-1 | SQL 引入 CoverageStatus 枚举引用 | `queries.py` | ✅ 已修复 |
| C2-2 | ToolEvidenceCandidate 运行时值域校验 | `candidate.py` | ✅ 已修复 |
| C2-3 | load_initial_cache 显式接收 project_root | `loaders.py` + `builder.py` + 测试 | ✅ 已修复 |
| C2-4 | 阶段 6 异常接入 OperationalLogger | `pipeline.py` | ✅ 已修复 |
| C2-5 | load_initial_cache 默认值对齐 CoverageStatus | `loaders.py` | ✅ 已修复 |
| C2-6 | load_initial_cache 覆盖率默认值改枚举引用 | `loaders.py` | ✅ 已修复 |
| C2-7 | 外层 except Exception 接入 OperationalLogger | `pipeline.py` | ✅ 已修复 |

全部 7 项 Category 2 已修复。881 tests passed。

---

## Ponytail Audit 清理方案

### 背景

对 `pipeline.py` 阶段 6 及 `domain/evidence/` 包执行 ponytail audit（过度工程审计），发现 8 项清理点。经用户审核：6 项同意并补充影响范围，2 项修正方向。

---

### 步骤 1：删除死 import（3 处，2 文件）

| 文件 | 行号 | 删除项 | 原因 |
|------|------|--------|------|
| `pipeline.py` | 25 | `import json` | 全文件无 `json.` 调用，零引用 |
| `pipeline.py` | 31 | `Tuple`（从 `typing` 导入行中移除） | 全文件无 `Tuple[...]` 使用；`_run_db_analysis` 返回类型已用小写 `tuple` |
| `merge_result.py` | 8 | `Optional`（从 `typing` 导入行中移除） | 全文件无 `Optional[...]` 使用 |

**影响**：零功能变更，lint 清理。

---

### 步骤 2：删除 claim_res / req_res 死参数（3 文件）

**现状**：`pipeline.py:383-384` 声明 `claim_res = {}` 和 `req_res = {}`，作为"Legacy format"占位符穿透 `_evaluate_and_output` → `_build_report_document`。

**死因**：
- `claim_res`：在 `_evaluate_and_output` 函数体中从未被引用，纯死参数
- `req_res`：穿透到 `reports.py:46` 执行 `req_res.get("requirement_coverage", [])`，因为 `req_res` 永远是 `{}`，结果永远是 `[]`

**变更**：

| 文件 | 位置 | 变更 |
|------|------|------|
| `pipeline.py:383-384` | `run_analyze()` 阶段 7 之后 | 删除 `claim_res = {}` 和 `req_res = {}` 两行 |
| `pipeline.py:397` | `_evaluate_and_output()` 调用 | 移除 `claim_res, req_res` 两个实参 |
| `pipeline.py:856-872` | `_evaluate_and_output()` 签名 | 移除 `claim_res: dict` 和 `req_res: dict` 两个形参 |
| `pipeline.py:922` | `_build_report_document()` 调用 | 移除 `req_res` 实参 |
| `reports.py:31` | `_build_report_document()` 签名 | 移除 `req_res: dict` 形参 |
| `reports.py:46` | `_build_report_document()` 函数体 | `req_res.get("requirement_coverage", [])` → 硬编码 `[]`：<br>`"requirement_coverage": [],` |

**验证**：`pytest tests/ -v` 全量通过，确认无调用方依赖这两个参数。

---

### 步骤 3：删除 is_empty() 死方法 + 测试（2 文件）

**现状**：`merge_result.py:34-40` 定义 `is_empty()` 方法，生产代码中零调用。

**变更**：

| 文件 | 位置 | 变更 |
|------|------|------|
| `merge_result.py` | 行 34-40 | 删除 `is_empty()` 方法（7 行） |
| `test_evidence_merge_result.py` | 行 21-43 | 删除 4 个测试方法：`test_is_empty_true`、`test_is_empty_false_with_test_results`、`test_is_empty_false_with_coverage`、`test_is_empty_false_with_purge` |

**验证**：`pytest tests/test_evidence_merge_result.py -v`，剩余测试（`test_default_initialization`、`test_custom_stats`）通过。

---

### 步骤 4：实现 scan_time（1 文件，1 行修复）

**审计建议**：删除 `"scan_time": ""`（死占位符）。

**用户纠正**：`scan_time` 是 `traceability_report.schema.json` 第 10 行的 `required` 字段，描述为 "ISO-8601 timestamp when the report was generated"。直接删除会导致 schema 校验失败。正确做法是实现它。

**变更**：

| 文件 | 行号 | 修改前 | 修改后 |
|------|------|--------|--------|
| `pipeline.py` | 25（新增） | — | `from datetime import datetime, timezone`（如果不存在；实际已有 `time` 导入，新增 `datetime`） |
| `pipeline.py` | 356 | `"scan_time": "",` | `"scan_time": datetime.now(timezone.utc).isoformat(),` |

> 使用 UTC 时间以避免时区歧义；`datetime.now(timezone.utc).isoformat()` 输出格式 `"2026-06-30T12:34:56.789012+00:00"`，符合 ISO-8601。

**影响**：Dashboard 中 `scan_time` 首次出现真实的生成时间戳。Dashboard template 已有 `|| "MISSING"` fallback，但实际值永远为空——此修复后 fallback 不再触发。

---

### 步骤 5：重构 _db_result_to_gaps() 查表法（1 文件）

**现状**：`pipeline.py:437-565`，129 行，其中约 55 行为重复的 dict append 模式。

**审计原始判断**：15 个相同模式的 dict append。

**用户纠正**：3 个数据源 × 5 个状态 = 15 个分支，但消息模板只有 5 种。AC 部分包含动态 `task_id` 插值（`AC {ac_id} (task {task_id})`），不能简单用同一个 dict append，需要辅助函数处理可选参数。

**重构策略**：提取 5 种消息模板 → 查表映射 `(item_type, status) → message_template`，辅助函数处理 template 格式化：

```python
def _gap(item_id: str, item_type: str, status: str, **kwargs) -> dict:
    """Build a gap dict from a message template lookup."""
    _TEMPLATES = {
        ("requirement", "no_task_for_requirement"):  "Requirement {item_id} has no task coverage.",
        ("requirement", "no_claim_for_task"):        "Requirement {item_id} tasks have no claims.",
        ("requirement", "no_tests_declared"):         "Requirement {item_id} claims declare no tests.",
        ("requirement", "test_not_run"):              "Requirement {item_id} has tests that were not run.",
        ("requirement", "test_failed"):               "Requirement {item_id} has failed tests.",
        ("ac", "no_task_for_ac"):                     "AC {item_id} has no task coverage.",
        ("ac", "no_claim_for_task"):                  "AC {item_id} (task {task_id}) has no claims.",
        ("ac", "no_tests_declared"):                  "AC {item_id} (task {task_id}) declares no tests.",
        ("ac", "test_not_run"):                       "AC {item_id} (task {task_id}) has tests that were not run.",
        ("ac", "test_failed"):                        "AC {item_id} (task {task_id}) has failed tests.",
        ("claim", "task_missing"):                    "Claim {item_id} references missing task.",
        ("claim", "task_not_done"):                   "Claim {item_id} task is not done.",
        ("claim", "no_tests"):                        "Claim {item_id} declares no tests.",
        ("claim", "test_missing"):                    "Claim {item_id} has missing tests.",
        ("claim", "test_failed"):                     "Claim {item_id} has failed tests.",
    }
    template = _TEMPLATES.get((item_type, status))
    if template is None:
        return None  # 未知状态跳过（如 coverage_status == "covered"）
    return {
        "item_id": item_id,
        "item_type": item_type,
        "reason": template.format(item_id=item_id, **kwargs),
    }
```

然后 3 个数据源循环简化为查表 + 过滤：

```python
def _db_result_to_gaps(req_coverage, ac_coverage, claim_evidence):
    gaps = []
    for row in req_coverage:
        g = _gap(row["req_id"], "requirement", row["coverage_status"])
        if g: gaps.append(g)
    for row in ac_coverage:
        g = _gap(row["ac_id"], "ac", row["coverage_status"], task_id=row.get("task_id", "unknown"))
        if g: gaps.append(g)
    for row in claim_evidence:
        g = _gap(row["claim_id"], "claim", row["verification_status"])
        if g: gaps.append(g)
    return gaps
```

**预估**：129 行 → ~55 行（-57%），主函数从 129 行缩至 ~15 行循环 + ~30 行模板表 = ~55 行。

**验证**：`pytest tests/test_db_query_functions.py -v`，所有 gap 断言通过。模板表覆盖全部 15 个 `(item_type, status)` 组合，行为等价。

---

### 步骤 6：persist() 返回值 — 保留不变

**审计建议**：`persist()` 返回 `Dict[str, str]` 但唯一生产调用方（`pipeline.py:346`）丢弃返回值，应改为 `-> None`。

**用户否决**：`test_evidence_builder.py` 有 3 个测试方法依赖返回值断言文件路径和读取 JSON 内容：

| 行号 | 测试方法 |
|------|----------|
| 188 | `test_persist_creates_json_files` — 断言 `result["test_results_file"]` / `result["coverage_reports_file"]` 存在且可读取 |
| 222 | `test_persist_empty_merge_result` — 同上模式 |
| 277 | `test_full_pipeline_test_and_coverage` — 同上模式 |

返回值本身无害（返回一个小 dict），改为 `-> None` 的测试重构成本超过收益。**保留不变。**

---

### 步骤 7：验证

1. `pytest tests/test_evidence_merge_result.py -v` — 确认 is_empty 测试删除后剩余测试通过
2. `pytest tests/test_evidence_builder.py -v` — 确认 persist 测试不受影响
3. `pytest tests/ -v` — 全量回归，确认 claim_res/req_res 删除无调用方破坏
4. 手工验证：`vt analyze` → 检查 `output/traceability_report.json` 中 `scan_time` 字段为有效 ISO-8601 时间戳

---

### 变更总览

| 步骤 | 描述 | 涉及文件 | 变更量 |
|------|------|----------|--------|
| 1 | 删除死 import（json, Tuple, Optional） | `pipeline.py`, `merge_result.py` | -3 行 |
| 2 | 删除 claim_res / req_res 死参数 | `pipeline.py`, `reports.py` | -5 行（含签名调整） |
| 3 | 删除 is_empty() + 4 测试 | `merge_result.py`, `test_evidence_merge_result.py` | -7 行生产，-23 行测试 |
| 4 | 实现 scan_time | `pipeline.py` | +1 行 import，1 行修改 |
| 5 | _db_result_to_gaps() 查表法重构 | `pipeline.py` | -74 行（129 → ~55） |
| 6 | persist() 返回值保留 | — | 不变 |

**net: −111 行生产代码，−23 行测试代码，−0 deps。**
