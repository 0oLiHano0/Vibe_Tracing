# Pipeline 阶段二重构计划

## 1. 问题定义

### 当前实现的问题

阶段二（Claim 覆盖前置检查）通过 `GhostCodeReconciler` 执行幽灵代码检测，但该类违反了流水线的阶段职责划分：

| 操作 | 设计归属 | 实际执行位置 |
|------|----------|-------------|
| 创建内存数据库 | 阶段 4 | **阶段 2**（`GhostCodeReconciler` 自建 DB） |
| 灌入 staged_files + claims | 阶段 5 | **阶段 2**（`load_staged_files` + `load_claims`） |
| 执行 SQL 查询 | 阶段 7 | **阶段 2**（`check_ghost_code`） |
| 从磁盘读取 task_list.json | 阶段 1 | **阶段 2**（`read_task_list`） |
| 从磁盘读取 prd.md | 阶段 1 | **阶段 2**（`read_prd_ac_ids`） |

这导致：
- DB 重复创建（阶段 2 临时 DB + 阶段 4 正式 DB）
- 数据重复灌入（Claims 在阶段 2 和阶段 5 各灌入一次）
- 磁盘 I/O 重复（阶段 1 已读取的数据，阶段 2 重新从磁盘读取）

### 设计目标

1. 阶段二的业务逻辑（幽灵代码检测、任务覆盖检查、AC 新鲜度检查）下沉到 `domain/gate/` 层
2. 阶段二的调度入口内联到 `pipeline.py`，删除 `gates.py`
3. 基于阶段一已加载的内存数据，用纯 Python set 操作完成检测，不创建 DB，不读磁盘
4. `change_proposal.py` 接受 `constraints_data` 参数，消除重复磁盘读取
5. 删除 `infra/governance/` 包（所有函数变为死代码）
6. Git 工具函数 inline 到调用方，删除 `infra/git/` 包
7. 删除 `gates_only` 模式（业务价值不成立，节省 ~100ms 不值得维护独立代码路径）
8. 统一 `staged_files` 获取：pipeline 入口调用一次，传递给阶段 2 和阶段 3

---

## 2. 重构方案

### 架构分层

```
cli/analyze/pipeline.py          ← 调度层：阶段 2 内联逻辑（获取 staged_files + 调用 domain + 翻译退出码）
    ↓
domain/gate/claim_coverage.py    ← 业务层：纯内存 set 操作，判定幽灵代码/任务覆盖/AC 新鲜度
    ↓
domain/context.py:UnifiedContext ← 数据层：阶段一已加载的所有输入数据
```

**`gates.py` 删除**：重构后 `gates.py` 仅剩一个约 15 行的薄函数，职责与 `pipeline.py` 阶段 2 完全重叠，没有独立存在的必要。其逻辑直接内联到 `pipeline.py` 的阶段 2 中。

### 核心思路

幽灵代码检测的本质是集合差集：

```
幽灵代码 = 暂存区业务文件 - 所有 Claim 的 code_refs（去除 # 后缀）
```

阶段一已将所有 Claims 加载到 `ctx.claims_list`（`Claim` 对象，含 `code_refs` 字段），无需重新读取磁盘或查询 DB。

**关键细节**：`code_refs` 可能包含行号锚点（如 `"src/foo.py#L42"`），必须用 `.split("#")[0]` 去除后再做集合运算，否则 `src/foo.py` 无法匹配 `src/foo.py#L42`，产生假阳性幽灵文件。

### 数据来源映射

| 检查项 | 当前数据来源 | 重构后数据来源 |
|--------|-------------|---------------|
| 幽灵代码检测 | DB：`check_ghost_code(conn)` | 内存：`ctx.claims_list` → `claim.code_refs` |
| 白名单过滤 | 硬编码 + `resolve_path` | 内存：`ctx.config` + `resolve_path`（仅构建路径，不读文件） |
| 治理边界过滤 | 磁盘：`load_boundary(project_root)` | 内存：`load_boundary(project_root, ctx.constraints)` |
| 任务覆盖检查 | 磁盘：`read_task_list()` | 内存：`ctx.task_result` |
| AC 新鲜度检查 | 磁盘：`read_prd_ac_ids()` + `check_prd_exists()` | 内存：`ctx.prd`（`PrdParseResult`） |

### 日志职责划分

重构后的日志体系遵循"CLI 层负责日志，Domain 层纯逻辑"原则：

| 层 | 模块 | 日志职责 |
|----|------|---------|
| CLI 调度层 | `pipeline.py` | `phase_end` 事件（含 `duration_ms`、`gate_result`）、`staged_files_unavailable` 警告、用户错误输出到 stderr |
| Domain 业务层 | `claim_coverage.py` | **不做日志** — 返回结果对象，由调用方决定如何记录 |
| CLI 工具层 | `finalize.py` inline | `git_show_error`、`git_uncommitted_check_error` 异常日志 |

**日志获取方式**：`vt_logger` 由 `pipeline.py` 阶段 1 初始化，后续阶段直接使用同一实例。inline 的 git 函数通过 `OperationalLogger.get()` 获取（与现有模式一致）。

### API 适配：dict → dataclass

旧代码（`GhostCodeReconciler`）从磁盘读取 JSON 后直接操作原始 dict。重构后操作阶段一已反序列化的强类型对象，API 不同：

**Claims 访问方式**：

| 旧代码（dict） | 新代码（dataclass） |
|---------------|-------------------|
| `claim.get("related_task", "")` | `claim.related_task` |
| `claim.get("code_refs", [])` | `claim.code_refs` |
| `code_ref.split("#")[0]` | `code_ref.split("#")[0]`（不变，code_refs 含行号锚点时必须去除） |

类型：`ctx.claims_list: List[Claim]`，`Claim` 定义于 `infra/loader/claim_loader.py:12`

**Tasks 访问方式**：

| 旧代码（dict） | 新代码（dataclass） |
|---------------|-------------------|
| `task.get("task_id", "")` | `task.task_id` |
| `task.get("related_acceptance_criteria", [])` | `task.related_acceptance_criteria` |
| `task_list_data.get("tasks", [])` | `ctx.task_result.tasks` |

类型：`ctx.task_result: TaskListLoadResult`，`Task` 定义于 `infra/loader/task_loader.py:23`

**PRD AC 提取方式**：

| 旧代码（磁盘 + regex） | 新代码（dataclass 遍历） |
|----------------------|------------------------|
| `re.compile(r"AC-[A-Z]+-\d+-\d+").findall(prd_text)` | `{ac.ac_id for req in ctx.prd.requirements for ac in req.acceptance_criteria}` |

类型：`ctx.prd: PrdParseResult` → `requirements: List[Requirement]` → `acceptance_criteria: List[AcceptanceCriteria]`，定义于 `infra/loader/prd_parser.py:28`

---

## 3. 实施步骤

### 步骤 1：新建 `domain/gate/claim_coverage.py` — 业务逻辑层

**文件**：`src/vibe_tracing/domain/gate/claim_coverage.py`（新建）

**职责**：纯内存规则判定，无 I/O，无副作用，**不做日志记录**（日志由调用方 `pipeline.py` 负责）。接收 `UnifiedContext` + staged_files 集合，返回检查结果。

**接口设计**：

```python
@dataclass
class ClaimCoverageResult:
    """阶段二检查结果。"""
    ghost_files: set              # 幽灵代码文件集合（空 = 通过）
    task_coverage_blocked: list   # 任务覆盖阻断项（空 = 通过）
    ac_freshness_warnings: list   # AC 新鲜度警告（空 = 无警告）

    @property
    def is_pass(self) -> bool:
        return not self.ghost_files and not self.task_coverage_blocked


def check_claim_coverage(
    ctx: UnifiedContext,
    staged_files: set,
    project_root: Path,
) -> ClaimCoverageResult:
    """阶段二核心逻辑：幽灵代码检测 + 任务覆盖检查 + AC 新鲜度检查。

    纯内存操作，不创建 DB，不读磁盘。
    """
    ...
```

**内部辅助函数**（注意：操作 dataclass 而非 dict）：

- `_filter_business_files(staged_files, project_root, ctx)` — 白名单 + 治理边界过滤
- `_detect_ghost_files(business_files, ctx)` — `business_files - {ref.split("#")[0] for claim in ctx.claims_list for ref in claim.code_refs}`（code_refs 可能含行号锚点如 `"src/foo.py#L42"`，必须去除 `#` 后缀再做集合差集，否则产生假阳性）
- `_check_task_coverage(business_files, ctx)` — 遍历 `ctx.task_result.tasks`，用 `task.task_id` 和 `task.related_acceptance_criteria` 访问字段
- `_check_ac_freshness(ctx)` — 遍历 `ctx.prd.requirements` → `req.acceptance_criteria` → `ac.ac_id`，无需 regex

**Nullable Guard 规则**（`UnifiedContext` 中以下字段可能为 `None`）：

| 字段 | 类型 | Guard 逻辑 |
|------|------|-----------|
| `ctx.task_result` | `Optional[TaskListLoadResult]` | `None` 时跳过 `_check_task_coverage` 和 `_check_ac_freshness`，不报错 |
| `ctx.constraints` | `Optional[Dict[str, Any]]` | `None` 时 `load_boundary` 返回默认空边界（`included_patterns=[], excluded_patterns=[]`），即不做边界过滤 |
| `ctx.claims_list` | `List[Claim]` | 永远是列表（默认 `[]`），无需 guard |
| `ctx.prd` | `PrdParseResult` | 永远存在（阶段 1 强校验），无需 guard |

**数据流**：

```
输入：ctx (UnifiedContext) + staged_files (set) + project_root (Path)
  ↓
白名单过滤：去除 .git/, output/, .vibetracing/claims/, 治理输入文件
  ↓
治理边界过滤：load_boundary(ctx.constraints) + is_in_scope()
  │  ctx.constraints 为 None → 返回默认空边界（不过滤）
  ↓
幽灵代码检测：business_files - {ref.split("#")[0] for claim in ctx.claims_list for ref in claim.code_refs}
  │  ctx.claims_list 为空 → 所有业务文件均为幽灵代码
  │  code_refs 含 "#L42" 后缀 → 必须 strip 再做差集
  ↓
任务覆盖检查：ctx.task_result 中是否存在 claim.related_task
  │  ctx.task_result 为 None → 跳过，不报错
  ↓
AC 新鲜度检查：ctx.prd 中是否存在 task.related_acceptance_criteria
  │  ctx.task_result 为 None → 跳过，不报错
  ↓
输出：ClaimCoverageResult
```

---

### 步骤 2：重构 `pipeline.py` — 内联阶段 2 + 删除 gates_only + 统一 staged_files

**删除文件**：`src/vibe_tracing/cli/analyze/gates.py`

**修改文件**：
- `src/vibe_tracing/cli/analyze/pipeline.py`
- `src/vibe_tracing/cli/main.py`（删除 `--gates-only` CLI 参数）

**改动 1：删除 gates_only**

- `pipeline.py`：删除 `gates_only` 参数、删除 gates_only 分支（line 244-250）、删除日志中的 `gates_only` 字段
- `main.py`：删除 `--gates-only` argparse 参数定义（line 90-92）、删除 `gates_only=args.gates_only` 传参（line 317）

**改动 2：统一 staged_files 获取 + 日志与错误处理**

pipeline 入口调用一次 `get_staged_files()`，结果传递给阶段 2 和阶段 3：

```python
# ── 阶段 2：Claim 覆盖前置检查（Gate 2）────────────────────────
_t_gates = time.perf_counter()
exit_code = None

# staged_files 获取（原 get_staged_files inline，保持错误处理和日志）
try:
    _git_result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=project_root, capture_output=True, text=True, timeout=10,
    )
    staged_files = (
        {f for f in _git_result.stdout.splitlines() if f.strip()}
        if _git_result.returncode == 0 and _git_result.stdout.strip()
        else set()
    )
except Exception as exc:
    vt_logger.warning("staged_files_unavailable",
                      "Could not get staged files from git", exc=exc)
    staged_files = set()

if is_pre_commit:
    from vibe_tracing.domain.gate.claim_coverage import check_claim_coverage
    result = check_claim_coverage(ctx, staged_files, project_root)
    if not result.is_pass:
        if result.ghost_files:
            files_str = "\n".join(f"  - {f}" for f in sorted(result.ghost_files))
            print(f"发现未经报备的幽灵代码！\n{files_str}\n...", file=sys.stderr)
        if result.task_coverage_blocked:
            print("\n".join(result.task_coverage_blocked), file=sys.stderr)
        exit_code = 1
    elif result.ac_freshness_warnings:
        print("\n".join(result.ac_freshness_warnings), file=sys.stderr)

vt_logger.info("phase_end", "Integrity gates completed",
               phase="integrity_gates",
               duration_ms=int((time.perf_counter() - _t_gates) * 1000),
               gate_result="pass" if exit_code is None else "blocked",
               exit_code=exit_code if exit_code is not None else 0,
               staged_files_count=len(staged_files),
               )
```

阶段 3 调用 `_execute_tools(ctx, project_root, staged_files=staged_files)` 避免重复获取。

**改动 3：清理 import**

- 删除 `from vibe_tracing.cli.analyze.gates import _check_claim_coverage`
- 删除 `gates.py` 文件本身

---

### 步骤 3：删除 `GhostCodeReconciler`

**文件**：`src/vibe_tracing/domain/governance/ghost_code.py`

**操作**：删除整个文件

**理由**：`GhostCodeReconciler` 的唯一调用方是 `gates.py:_gate2_code_claim_alignment()`，步骤 2 已删除该调用方。

---

### 步骤 4：清理 `domain/governance/__init__.py`

**文件**：`src/vibe_tracing/domain/governance/__init__.py`

**改动**：

```python
from vibe_tracing.domain.governance.change_proposal import ArchitectureChangeProposalEngine

__all__ = ["ArchitectureChangeProposalEngine"]
```

---

### 步骤 5：重构 `change_proposal.py` — 接受 `constraints_data` 参数

**文件**：`src/vibe_tracing/domain/governance/change_proposal.py`

**改动**：

1. `__init__` 新增可选参数 `constraints_data: Optional[dict] = None`，存储为 `self.constraints_data`
2. `check_governance` 内部使用 `self.constraints_data` 替代 `read_constraints_json(self.constraints_path)`（line 271）
3. 删除对 `read_constraints_file` 和 `read_constraints_json` 的 import（line 49）

**伪代码**：

```python
# __init__ 新增参数
def __init__(self, project_root, config_data, constraints_data=None, ...):
    self.constraints_data = constraints_data
    ...

# check_governance 内部，line 271 替换为：
curr_data = self.constraints_data or json.loads(self.constraints_path.read_text(encoding="utf-8"))
if curr_data is None:
    return _empty_result()
```

**同步更新调用方**（传入 `ctx.constraints`）：

| 调用方 | 改动 |
|--------|------|
| `cli/analyze/reports.py:182` | `ArchitectureChangeProposalEngine(project_root, config_data=ctx.config, constraints_data=ctx.constraints)` |
| `domain/compliance/checker.py:695` | `ArchitectureChangeProposalEngine(self.project_root, config_data=self.config_data, constraints_data=self.constraints_data)` |
| `cli/finalize.py:94` | 不变（仅调用 `_find_differences()`，不调用 `check_governance()`） |

**效果**：`read_constraints_file` 和 `read_constraints_json` 变为死代码，下一步删除。

---

### 步骤 6：删除 `infra/governance/` 包

**删除文件**：
- `src/vibe_tracing/infra/governance/loader.py`（所有 6 个函数均变为死代码）
- `src/vibe_tracing/infra/governance/__init__.py`

**理由**：
- `read_claims_from_filesystem`、`read_task_list`、`read_prd_ac_ids`、`check_prd_exists` — 仅被 `GhostCodeReconciler` 使用，步骤 3 已删除
- `read_constraints_file`、`read_constraints_json` — 步骤 5 已将 `change_proposal.py` 改为接受 `constraints_data` 参数，不再需要从磁盘读取

---

### 步骤 7：Git 工具函数 inline 到调用方，删除 `infra/git/` 包

**删除文件**：
- `src/vibe_tracing/infra/git/utils.py`
- `src/vibe_tracing/infra/git/__init__.py`

**inline 映射**：

| 函数 | 原位置 | inline 到 | 新实现 |
|------|--------|-----------|--------|
| `get_staged_files` | `infra/git/utils.py:83` | `cli/analyze/pipeline.py`（阶段 2） | 内联 `subprocess.run(["git", "diff", "--cached", "--name-only"])`，见步骤 2 |
| `git_show` | `infra/git/utils.py:16` | `cli/finalize.py:81` + `domain/governance/change_proposal.py:251` | 内联 `subprocess.run(["git", "show", f"{commit}:{path}"])` |
| `git_has_uncommitted_changes` | `infra/git/utils.py:43` | `cli/finalize.py:104` | 内联 `subprocess.run(["git", "diff", "--name-only", "--", path])` + `["git", "diff", "--cached", "--name-only", "--", path]` |

**说明**：每个函数本质上是一行 subprocess 调用的薄包装，inline 后消除模块依赖。

**日志与错误处理规范**（与现有 git 函数保持一致）：

| 函数 | 异常处理 | 日志 | 降级值 |
|------|---------|------|--------|
| `get_staged_files` | `except Exception` | `vt_logger.warning("staged_files_unavailable", ...)` | `set()` |
| `git_show` | `except Exception` | `vt_logger.exception("git_show_error", ...)` | `None` |
| `git_has_uncommitted_changes` | `except Exception` | `vt_logger.exception("git_uncommitted_check_error", ...)` | `False` |

**日志事件命名规范**：snake_case，与现有 `"git_utils_error"` 风格一致。inline 后事件名更精确（`"git_show_error"` 而非笼统的 `"git_utils_error"`）。

**同步删除/清理测试**：

- `tests/test_git_utils.py` — 删除（测试已删除的模块）
- `tests/test_cli_analyze.py:1511-1516` — 删除 `test_get_staged_files_no_git`（测试已 inline 的函数）

**同步清理 import**：

| 文件 | 删除的 import |
|------|--------------|
| `cli/analyze/pipeline.py` | `from vibe_tracing.infra.git.utils import get_staged_files` |
| `cli/analyze/tools.py` | `from vibe_tracing.infra.git.utils import get_staged_files` |
| `cli/finalize.py` | `from vibe_tracing.infra.git.utils import git_show, git_has_uncommitted_changes` |
| `domain/governance/change_proposal.py` | `from vibe_tracing.infra.git.utils import git_show` |

**注意**：`domain/governance/ghost_code.py` 也 import 了 `get_staged_files`，但步骤 3 已删除该文件，无需额外处理。

**注意**：`tools.py` 中的 `get_staged_files` 调用（staged 文件扩展名检查）也需要 inline 或改为从 pipeline 传入。考虑到 tools.py 在阶段 3 被调用时 pipeline.py 已获取过 staged_files，更优的做法是将 staged_files 作为参数传入 `_execute_tools()`，而非 tools.py 自行调用。

---

### 步骤 8：重写测试

**删除**：`tests/test_ghost_code_reconciler.py`

**新建**：`tests/test_stage2_claim_coverage.py`

测试用例迁移映射：

| 旧测试（GhostCodeReconciler） | 新测试（check_claim_coverage） |
|-------------------------------|-------------------------------|
| `TestNoStagedCodeFiles` | 暂存区无业务代码 → 通过 |
| `TestNoClaimsFile` | 无 Claims 但有 staged 代码 → 阻断 |
| `TestClaimsCoverCodeRefs` | Claims 完全覆盖 staged 文件 → 通过 |
| `TestClaimsCoverCodeRefs`（部分覆盖） | Claims 部分覆盖 → 阻断，列出幽灵文件 |
| `TestEmptyClaimsArray` | Claims 列表为空 + 有 staged 代码 → 阻断 |
| `TestClaimsReferenceNonExistentFile` | Claims 引用不在 staged 中的文件 → 通过（不影响） |
| `TestWhitelistLogic` | 白名单文件过滤 |
| `TestTaskCoverageCheck` | 任务覆盖检查 |
| `TestACFreshnessCheck` | AC 新鲜度检查（仅警告） |
| `TestMalformedClaimsWarning` | 不适用（阶段 1 已完成解析，传入的是 Claim 对象） |
| `TestReadClaimsFromFilesystem` | 不适用（不再从磁盘读取） |
| `TestGitNotInstalled` | Git 不可用时的优雅降级 |

**新增测试**：

- 治理边界过滤（`boundary.json` include/exclude 模式）
- 非 pre-commit 模式跳过检查
- `ctx.claims_list` 为空列表时的行为
- `ClaimCoverageResult` 的 `is_pass` 属性
- `code_refs` 含行号锚点（`"src/foo.py#L42"`）时正确匹配 `src/foo.py`
- `ctx.task_result` 为 `None` 时跳过任务覆盖和 AC 新鲜度检查
- `ctx.constraints` 为 `None` 时跳过治理边界过滤

**同步清理 gates_only 相关测试**：

- `tests/test_timing_instrumentation.py:124-127` — 删除 `gates_only` 字段断言

---

### 步骤 9：运行测试并验证

```bash
# 运行阶段二相关测试
pytest tests/test_stage2_claim_coverage.py -v

# 运行全量测试确保无回归
pytest tests/ -v

# 验证 DB 相关测试不受影响（Stage 7 仍使用 check_ghost_code）
pytest tests/test_db_query_functions.py -v -k ghost
pytest tests/test_merge_gate_engine.py -v -k ghost
```

---

## 4. 不受影响的模块

以下模块**不参与本次重构**：

| 模块 | 原因 |
|------|------|
| `infra/db/queries.py:check_ghost_code()` | 阶段 7 使用（`_run_db_analysis` 中调用） |
| `infra/db/loaders.py:load_staged_files()` | 阶段 7 使用（DB 灌入） |
| `tests/test_db_query_functions.py` | 测试 DB 查询层，与阶段 2 无关 |
| `tests/test_merge_gate_engine.py` | 测试阶段 8 门禁引擎，与阶段 2 无关 |
| `tests/test_incremental_mode.py` | 测试增量模式，与阶段 2 无关 |
| `cli/finalize.py` | 仅 inline git 函数调用，业务逻辑不变 |

---

## 5. 验收标准

| # | 检查项 | 判定 |
|---|--------|------|
| 1 | 阶段二不再创建 DB 连接 | `pipeline.py` 阶段 2 中无 `init_in_memory_db` 调用 |
| 2 | 阶段二不再从磁盘读取 Claims | 无 `read_claims_from_filesystem` 调用 |
| 3 | 阶段二不再从磁盘读取 task_list | 无 `read_task_list` 调用 |
| 4 | 阶段二不再从磁盘读取 PRD | 无 `read_prd_ac_ids` 调用 |
| 5 | 幽灵代码检测使用 Python set 操作 | `business_files - all_claimed` |
| 6 | `code_refs` 行号锚点已去除 | `ref.split("#")[0]` |
| 7 | Nullable guard 完整 | `task_result=None` 跳过检查、`constraints=None` 跳过边界过滤 |
| 8 | 业务逻辑在 `domain/gate/claim_coverage.py` | 纯内存操作，无 I/O，无副作用 |
| 9 | `gates.py` 已删除 | 阶段 2 逻辑内联到 `pipeline.py` |
| 10 | `gates_only` 模式已删除 | `pipeline.py` 无 `gates_only` 参数，`main.py` 无 `--gates-only` CLI 参数 |
| 11 | `staged_files` 统一获取 | pipeline 入口调用一次，阶段 2/3 共用，无重复 subprocess |
| 12 | `GhostCodeReconciler` 类已删除 | 文件不存在 |
| 13 | `change_proposal.py` 接受 `constraints_data` 参数 | `check_governance` 不再从磁盘读取 constraints |
| 14 | `infra/governance/` 包已删除 | `loader.py` 和 `__init__.py` 均不存在 |
| 15 | `infra/git/` 包已删除 | `utils.py` 和 `__init__.py` 均不存在 |
| 16 | Git 函数已 inline | `get_staged_files` 在 `pipeline.py` 中、`git_show` 在 `finalize.py` + `change_proposal.py` 中、`git_has_uncommitted_changes` 在 `finalize.py` 中 |
| 17 | `tests/test_git_utils.py` 已删除 | 测试文件不存在 |
| 18 | 所有现有测试通过 | `pytest tests/ -v` 全绿 |
| 19 | 阶段 7 的 `check_ghost_code` DB 查询不受影响 | `test_db_query_functions.py` 通过 |

---

## 6. 第二阶段收敛：废除非 git 分支 + 阶段二仅做幽灵代码检测

### 6.1 问题定义

当前阶段二存在两个架构问题：

**问题 1：`is_pre_commit` 分支增加无谓复杂度**

`is_pre_commit` 参数控制阶段二是否执行。但 VT 的治理入口是 git pre-commit hook（`vt init` 安装），每次 `git commit` 都会强制执行 `vt analyze --pre-commit`。不存在"不带 `--pre-commit` 运行 analyze"的业务场景。

保留 `is_pre_commit` 是在为不存在的场景增加分支复杂度。

**问题 2：阶段二混入了不属于自己的检查**

当前阶段二包含三项检查：

| 检查 | 阶段二 | 阶段七（DB 分析） | 重复？ |
|------|--------|------------------|--------|
| 幽灵代码检测 | `_detect_ghost_files` (Python set) | `check_ghost_code` (SQL) | 是 |
| 任务覆盖检查 | `_check_task_coverage` (Python) | `check_requirement_coverage` (SQL) | 是 |
| AC 新鲜度检查 | `_check_ac_freshness` (Python) | `check_ac_coverage` (SQL) | 是 |

任务覆盖和 AC 新鲜度是全量分析的一部分，属于阶段七的职责。阶段二的唯一业务问题是："本次提交的代码文件是否都被 Claim 覆盖？"

### 6.2 设计目标

1. 删除 `is_pre_commit` 参数，阶段二始终执行
2. 阶段二仅做幽灵代码检测，删除任务覆盖和 AC 新鲜度检查
3. 更新 git hook 和 `vt init` 安装脚本
4. 消除 `output.py` 中的 `is_pre_commit` 分支

### 6.3 实施步骤

#### 步骤 10：简化 `domain/gate/claim_coverage.py`

**文件**：`src/vibe_tracing/domain/gate/claim_coverage.py`

**现状**：已简化为仅做幽灵代码检测（`detect_ghost_code` 函数 + `GhostCodeResult` 数据类）。步骤 10 本身已完成。

**后续联动**：步骤 11 将在此基础上进一步修改——导出 `build_governance_whitelist`、简化 `detect_ghost_code` 签名（删除 `project_root`）、`_filter_business_files` 改用 ctx 预计算数据。

**验收**：文件中无 `_check_task_coverage`、`_check_ac_freshness`、`ClaimCoverageResult`。

---

#### 步骤 11：预计算白名单 + 治理边界 — 消除阶段二重复计算

**问题 1：白名单重复计算**

阶段二的 `_build_whitelist` 从 `ctx.config` 调用 `resolve_path` 构建白名单路径集合，与阶段一加载文件时的路径解析完全重复。

**问题 2：治理边界重复计算**

`load_boundary(ctx.constraints)` 每次调用都从 dict 中提取 `governance_boundary`。结果是固定的（同一份 constraints），应在阶段一预计算。

**调度 vs 业务逻辑分离原则**：

- 白名单**构建逻辑**（路径解析、relative_to）属于业务规则，应保留在 `domain/gate/claim_coverage.py` 中
- 白名单**调用时机**属于调度逻辑，由 `pipeline.py:_load_context` 决定
- `pipeline.py` 不应内联路径解析代码，只调用 `claim_coverage.py` 导出的辅助函数

**改动 1：`domain/context.py` — UnifiedContext 新增字段**

新增两个字段：

```python
@dataclass
class UnifiedContext:
    ...
    governance_whitelist: Set[str] = field(default_factory=set)   # 治理文件路径集合
    governance_boundary: dict = field(default_factory=dict)        # 治理边界（include/exclude 模式）
```

**改动 2：`domain/gate/claim_coverage.py` — 导出白名单构建辅助函数**

将 `_build_whitelist` 重命名为 `build_governance_whitelist` 并导出。接受 `manifest` 和 `project_root` 参数（避免依赖 `ctx`，消除循环依赖风险）：

**设计决策**：白名单基于 manifest 实际加载的路径（what was loaded），而非 config 声明的路径（what was configured）。理由：manifest 记录的是 VT 实际消费的文件，白名单的目的是排除这些治理输入文件，直接对应关系最准确。同时避免了重复调用 `resolve_path`，消除 config 与 manifest 路径解析逻辑潜在的不一致风险。

```python
def build_governance_whitelist(manifest, project_root: Path) -> Set[str]:
    """从 manifest 记录中构建治理文件白名单路径集合。

    白名单基于 manifest 实际加载的路径（what was loaded），
    而非 config 声明的路径（what was configured）。
    record.file_path 是绝对路径，需转换为相对路径。

    由 pipeline.py 在阶段一调用，结果存入 ctx.governance_whitelist。
    """
    whitelist = {".vibetracing/config.json"}
    for record in manifest.inputs_used:
        if record.status == STATUS_OK:
            try:
                rel = Path(record.file_path).relative_to(project_root)
                whitelist.add(str(rel))
            except (ValueError, OSError):
                pass
    return whitelist
```

删除原 `_build_whitelist` 函数（被 `build_governance_whitelist` 替代）。删除 `resolve_path` 和 `load_boundary` 的原有 import（`load_boundary` 完全移除，`resolve_path` 仅在 `_filter_business_files` 不再使用后从本文件移除）。

`_filter_business_files` 简化为直接使用 `ctx` 中的预计算数据：

```python
from vibe_tracing.infra.config.boundary import is_in_scope

def _filter_business_files(staged_files, ctx):
    """白名单 + 治理边界过滤，使用阶段一预计算的 ctx 数据。"""
    whitelist_prefixes = (".git/", "output/", ".vibetracing/claims/")
    business_files = {
        f for f in staged_files
        if f not in ctx.governance_whitelist
        and not any(f.startswith(p) for p in whitelist_prefixes)
    }
    return {f for f in business_files if is_in_scope(f, ctx.governance_boundary)}
```

**改动 3：`domain/gate/claim_coverage.py:detect_ghost_code` — 签名简化**

白名单和边界已预计算到 `ctx` 中，`detect_ghost_code` 不再需要 `project_root` 参数：

```python
# 旧签名
def detect_ghost_code(ctx, staged_files, project_root) -> GhostCodeResult:

# 新签名
def detect_ghost_code(ctx, staged_files) -> GhostCodeResult:
```

内部调用 `_filter_business_files(staged_files, ctx)` 时不再传 `project_root`。

**改动 4：`pipeline.py:_load_context` — 阶段一预计算（调度层）**

在 `_load_context` 构建 `UnifiedContext` 时，调用 `claim_coverage.py` 导出的辅助函数：

```python
from vibe_tracing.domain.gate.claim_coverage import build_governance_whitelist
from vibe_tracing.infra.config.boundary import load_boundary

# 预计算治理文件白名单（业务逻辑在 claim_coverage.py，此处仅调用）
governance_whitelist = build_governance_whitelist(manifest, project_root)

# 预计算治理边界（load_boundary 是数据转换，属于 infra 层）
constraints_data = constraints_record.content if constraints_record and constraints_record.status == STATUS_OK else None
governance_boundary = load_boundary(project_root, constraints_data=constraints_data)

ctx = UnifiedContext(
    ...
    governance_whitelist=governance_whitelist,
    governance_boundary=governance_boundary,
)
```

**验收**：
- `claim_coverage.py` 无 `load_boundary` import
- `claim_coverage.py` 无 `resolve_path` import（白名单基于 manifest，无需路径解析）
- `claim_coverage.py` 导出 `build_governance_whitelist` 辅助函数
- `claim_coverage.py` 无原 `_build_whitelist` 函数（已被 `build_governance_whitelist` 替代）
- `build_governance_whitelist` 使用 `manifest.inputs_used` 的 `file_path` 构建白名单（非 config + resolve_path）
- `pipeline.py` 不内联路径解析代码，只调用 `build_governance_whitelist`
- `detect_ghost_code` 签名无 `project_root` 参数
- `UnifiedContext` 有 `governance_whitelist` 和 `governance_boundary` 字段

---

#### 步骤 12：更新 `pipeline.py` — 删除 `is_pre_commit`，阶段二始终执行

> 注：原步骤 11，因新增步骤 11（白名单预计算）而顺延。

**文件**：`src/vibe_tracing/cli/analyze/pipeline.py`

**改动 1：`run_analyze` 签名**

删除 `is_pre_commit: bool = False` 参数。更新 docstring。

**改动 2：`run_start` 日志**

删除 `is_pre_commit=is_pre_commit` 字段。

**改动 3：阶段二逻辑**

将当前的条件执行：
```python
exit_code = None
if is_pre_commit:
    from vibe_tracing.domain.gate.claim_coverage import detect_ghost_code
    result = detect_ghost_code(ctx, staged_files, project_root)
    if not result.is_pass:
        ...
        exit_code = 1
```

改为无条件执行（注意：`detect_ghost_code` 签名已在步骤 11 简化，不再需要 `project_root`）：
```python
from vibe_tracing.domain.gate.claim_coverage import detect_ghost_code
result = detect_ghost_code(ctx, staged_files)
exit_code = None
if not result.is_pass:
    files_str = "\n".join(f"  - {f}" for f in sorted(result.ghost_files))
    print(
        "发现未经报备的幽灵代码！\n"
        f"{files_str}\n"
        "上述文件在本次提交中没有对应的【活跃发票】（Claim）。\n"
        "如果它是合法代码，请在 .vibetracing/claims/ 中创建或更新对应的 Claim 文件，"
        "并将其与代码一同提交。",
        file=sys.stderr,
    )
    exit_code = 1
```

**改动 4：`_evaluate_and_output` 调用**

删除 `is_pre_commit=is_pre_commit` 传参。

---

#### 步骤 13：更新 `_evaluate_and_output` 和 `_render_output` — 删除 `is_pre_commit`

**文件**：
- `src/vibe_tracing/cli/analyze/pipeline.py`（`_evaluate_and_output`）
- `src/vibe_tracing/cli/analyze/output.py`（`_render_output`）

**改动 1：`_evaluate_and_output` 签名**

删除 `is_pre_commit: bool = False` 参数。更新 docstring。

**改动 2：`_render_output` 调用**

删除 `is_pre_commit=is_pre_commit` 传参。

**改动 3：`_render_output` 签名和逻辑**

删除 `is_pre_commit: bool = False` 参数。

将当前逻辑：
```python
if not is_pre_commit:
    _print_empty_claims_hint(ctx, staged_files)
```

改为无条件调用：
```python
_print_empty_claims_hint(ctx, staged_files)
```

**安全性**：`_print_empty_claims_hint` 内部有 guard `if not ctx.claims_list and not staged_files`。在 pre-commit 上下文中（有 staged files），hint 不会触发。在手动运行时（无 staged files），hint 会触发。行为正确。

---

#### 步骤 14：更新 `main.py` — 删除 `--pre-commit` CLI 参数

**文件**：`src/vibe_tracing/cli/main.py`

**改动 1：删除 argparse 定义**

删除：
```python
# --pre-commit 模式：仅检查暂存区中的文件，用于 Git pre-commit hook
analyze_parser.add_argument(
    "--pre-commit", action="store_true", help="以 Git pre-commit hook 模式运行（启用幽灵代码检测）"
)
```

**改动 2：删除传参**

删除：
```python
is_pre_commit=args.pre_commit,
```

---

#### 步骤 15：更新 git hook 和 `vt init`

**文件**：
- `src/vibe_tracing/cli/init.py`
- `.git/hooks/pre-commit`

**改动 1：`vt init` 安装脚本**

将：
```python
hook_script = f'#!/bin/sh\nset -e\n# Vibe Tracing Git Guard\n"{python_path}" -m vibe_tracing analyze --pre-commit\n'
```

改为：
```python
hook_script = f'#!/bin/sh\nset -e\n# Vibe Tracing Git Guard\n"{python_path}" -m vibe_tracing analyze\n'
```

**改动 2：直接更新 VT 项目自管理的 hook**

将 `.git/hooks/pre-commit` 中的 `--pre-commit` 删除。直接修改文件，无需版本管理，无需重新 `vt init`。本项目处于开发重构阶段，没有历史债务需要处理，不向后兼容，一切都是为了最终的最优架构服务。

---

#### 步骤 16：更新测试

**改动 1：`tests/test_timing_instrumentation.py:124-126`**

删除 `is_pre_commit` 字段断言：
```python
# 删除：
assert "is_pre_commit" in run_start
```

**改动 2：`tests/test_scaffolding.py:107`**

检查 `test_run_init_pre_commit_hook_uses_sys_executable` 是否引用 `--pre-commit`。如有，更新为不包含 `--pre-commit`。

**改动 3：`tests/test_stage2_claim_coverage.py`**

- 更新 import：`check_claim_coverage` → `detect_ghost_code`，`ClaimCoverageResult` → `GhostCodeResult`
- 删除 `TestClaimCoverageResult` 中的 `test_is_fail_when_task_blocked` 和 `test_is_pass_when_only_ac_warnings`
- 删除整个 `TestTaskCoverage` 类（3 个测试）
- 删除整个 `TestACFreshness` 类（3 个测试）
- 更新 `TestGhostCodeDetection` 和 `TestBoundaryFiltering` 中的调用：`check_claim_coverage(ctx, staged_files, project_root)` → `detect_ghost_code(ctx, staged_files)`（删除 `project_root` 参数），`result.is_pass` → `result.is_pass`（不变），`result.ghost_files` 不变

---

#### 步骤 17：全量测试验证

```bash
pytest tests/ -v
```

确认所有测试通过，无遗留的 `is_pre_commit` 引用。

---

#### 步骤 18：更新文档

以下文档包含对旧 API 的引用，需要同步更新：

| 文档 | 行号 | 当前内容 | 更新为 |
|------|------|----------|--------|
| `docs/spec_pipeline_stage_2.md` | 10 | `pre-commit 标志 \| 命令行参数 --pre-commit` | 删除该行 |
| `docs/spec_pipeline_stage_2.md` | 65-67 | `check_claim_coverage()` + `is_pre_commit` 条件 | 改为 `detect_ghost_code()`，无条件执行 |
| `docs/spec_pipeline_stage_2.md` | 99-110 | 任务覆盖检查 + AC 新鲜度检查步骤 | 删除这两个步骤 |
| `docs/spec_pipeline_stage_2.md` | 119-136 | `ClaimCoverageResult` 输出结构 | 改为 `GhostCodeResult`（仅 `ghost_files` + `is_pass`） |
| `docs/spec_pipeline_stage_2.md` | 全文 | 整体重写 | 反映简化后的架构（仅幽灵代码检测，无 `is_pre_commit`） |
| `docs/refactoring_design.md` | 62 | `check_claim_coverage(ctx, staged_files, project_root)` | 改为 `detect_ghost_code(ctx, staged_files)`（无 `project_root`） |
| `docs/refactoring_design.md` | 77 | `check_claim_coverage(ctx, staged_files, project_root)` | 改为 `detect_ghost_code(ctx, staged_files)`（无 `project_root`） |
| `docs/spec_pipeline_stage_1.md` | 265 | `is_pre_commit`, `gates_only` | 删除这两个字段 |
| `docs/prd.md` | 1381 | `vt analyze --pre-commit --gates-only` | 改为 `vt analyze` |

**验收**：`grep -rn "is_pre_commit\|pre_commit\|check_claim_coverage\|ClaimCoverageResult\|task_coverage\|ac_freshness" docs/` 返回空（除 `pipeline_stage-2-refacting.md` 规划文档本身）。

---

### 6.4 验收标准

| # | 检查项 | 判定 |
|---|--------|------|
| 1 | `pipeline.py` 无 `is_pre_commit` 参数 | ✅ `run_analyze` 和 `_evaluate_and_output` 签名中不存在 |
| 2 | `output.py` 无 `is_pre_commit` 参数 | ✅ `_render_output` 签名中不存在 |
| 3 | `main.py` 无 `--pre-commit` CLI 参数 | ✅ argparse 定义不存在 |
| 4 | 阶段二无条件执行 | ✅ `pipeline.py` 中无 `if is_pre_commit:` 分支 |
| 5 | `claim_coverage.py` 仅做幽灵代码检测 | ✅ 无 `_check_task_coverage`、`_check_ac_freshness` |
| 6 | `detect_ghost_code` 签名无 `project_root` | ✅ 白名单已预计算到 ctx |
| 7 | `claim_coverage.py` 导出 `build_governance_whitelist` | ✅ 路径解析逻辑在 domain 层，pipeline.py 仅调用 |
| 8 | `pipeline.py` 不内联路径解析代码 | ✅ 白名单构建通过 `build_governance_whitelist` 调用 |
| 9 | git hook 无 `--pre-commit` | ✅ `.git/hooks/pre-commit` 内容不含 `--pre-commit` |
| 10 | `vt init` 安装脚本无 `--pre-commit` | ✅ `init.py` 中 hook_script 不含 `--pre-commit` |
| 11 | 所有测试通过 | ✅ `pytest tests/ -v` 916 passed |
| 12 | 代码无遗留引用 | ✅ `grep -rn "is_pre_commit\|--pre-commit" src/ tests/` 返回空 |
| 13 | 文档无遗留引用 | ✅ docs 中无旧 API 引用（仅剩 DB 查询函数名和 git hook 概念名） |

**说明**：`cli/analyze/__init__.py` 只是 re-export `run_analyze`，签名变化自动生效，无需额外改动。

### 6.5 变更影响范围

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `domain/gate/claim_coverage.py` | 修改 | 导出 `build_governance_whitelist`，`detect_ghost_code` 删除 `project_root` 参数，`_filter_business_files` 使用 ctx 预计算数据 |
| `domain/context.py` | 修改 | 新增 `governance_whitelist` 和 `governance_boundary` 字段 |
| `cli/analyze/pipeline.py` | 修改 | 删除 `is_pre_commit`，阶段二无条件执行；`_load_context` 调用 `build_governance_whitelist` 预计算白名单 |
| `cli/analyze/output.py` | 修改 | 删除 `is_pre_commit`，`_print_empty_claims_hint` 无条件调用 |
| `cli/analyze/__init__.py` | 无改动 | re-export `run_analyze`，签名变化自动生效 |
| `cli/main.py` | 修改 | 删除 `--pre-commit` argparse 参数 |
| `cli/init.py` | 修改 | hook 安装脚本删除 `--pre-commit` |
| `.git/hooks/pre-commit` | 修改 | 删除 `--pre-commit` |
| `tests/test_timing_instrumentation.py` | 修改 | 删除 `is_pre_commit` 断言 |
| `tests/test_scaffolding.py` | 检查 | 确认是否需要更新 |
| `tests/test_stage2_claim_coverage.py` | 修改 | 删除 task coverage 和 AC freshness 测试，更新 `detect_ghost_code` 调用（无 `project_root`） |
| `docs/spec_pipeline_stage_2.md` | 重写 | 反映简化后的架构 |
| `docs/refactoring_design.md` | 修改 | 更新阶段二描述 |
| `docs/spec_pipeline_stage_1.md` | 修改 | 删除 `is_pre_commit`/`gates_only` 日志字段 |
| `docs/prd.md` | 修改 | 更新 hook 命令描述 |
