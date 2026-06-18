# Analyze 重构执行计划

> **本文档是什么**：跟踪 `vt analyze` 流水线重构的执行进度。回答"现在走到哪了？下一步做什么？"。
>
> **如何使用**：
> 1. 顶部"当前状态总览"快速了解全局进度
> 2. "Phase 详细任务"中找到下一个可执行的 Phase，按步骤推进
> 3. 每完成一个步骤，在 checkbox 中打勾 `[x]`
> 4. 偏离点跟踪表记录执行中发现的偏差，按优先级排序
>
> **参考文档**：`docs/analyze_redesign.md`（完整设计文档，九章分阶段实施计划）

---

## 一、 当前状态总览

### Phase 完成状态

| Phase | 名称 | 状态 | 说明 |
|---|---|---|---|
| Phase 1 | 基础层（infra/ + analyzers/ + db.py） | ✅ 已完成 | 目录移动 + db.py + validate_* 迁移到 validation 模块 |
| Phase 2 | 领域层移动 + Claim 加载重构 | ✅ 已完成 | domain/ 移动完成、claim_loader 重构完成（旧字段已删除） |
| Phase 3 | 编排层移动 + 证据构建重构 | ❌ 未开始 | commands/ 仍在原位，cli/ 目录尚未建立 |
| Phase 4 | 门禁引擎 SQL 化 | ❌ 未开始 | merge_gate_engine.py 未改 |
| Phase 5 | 幽灵代码检测 SQL 化 | ❌ 未开始 | ghost_code_reconciler.py 未改 |
| Phase 6 | 流水线集成 | ❌ 未开始 | pipeline.py 未改，仍引用 current.json |
| Phase 7 | Dashboard 模板迁移 + 清理 | ❌ 未开始 | dashboard 未适配新 evidence 格式 |

### 已完成的额外工作

| 工作项 | 状态 | 说明 |
|---|---|---|
| infra/db.py 实现 | ✅ | 522 行，DDL + 8 张表 + 双层校验 + SQL 查询 + UPSERT API，全部接口已实现 |
| infra/validation/ 模块 | ✅ | checks.py(335) + ids.py(141) + schema_validator.py(301)，格式校验规则已实现并添加 OperationalLogger |
| validation 子包结构完善 | ✅ | `infra/validation/` 子包已创建（checks.py + ids.py + schema_validator.py + schemas/），ids.py 和 schema_validator.py 已从 infra/ 迁入 infra/validation/，schemas/ 已从 src/vibe_tracing/schemas/ 迁入 infra/validation/schemas/ |
| validation OperationalLogger 日志 | ✅ | validation 模块已添加 OperationalLogger 日志（validation_start / validation_complete / schema_violation / invalid_id / duplicate_id / unsafe_path 等事件） |
| core/ 目录清理 | ✅ | 已删除，内容移至 infra/ |
| traceability/ 目录清理 | ✅ | 已删除，内容移至 analyzers/ |
| Claim 数据类清理 | ✅ | claimed_status、credibility、evidence_refs 字段已从 Claim dataclass 中删除 |
| validation 第一层校验收拢 | ✅ | db.py 中 `validate_task`/`validate_claim`/`validate_test_result`/`validate_coverage_report` + `_RE_TASK`/`_RE_CLAIM` 已全部删除，`load_tasks`/`load_claims` 改为纯数据泵。`validate_test_result`/`validate_coverage_report` 的 schema 迁移在 Phase 3 步骤 10 执行 |

### 关键偏离

| 偏离项 | 说明 |
|---|---|
| Phase 执行顺序偏离 | 原计划 Phase 1→2→3，实际 Phase 2 先于 Phase 3 完成（domain/ 移动 + claim_loader 重构），但 cli/ 目录（Phase 3）未动 |
| commands/ 目录残留 | `commands/` 目录及其中 10 个 analyze 子模块仍在原位，import 路径全部仍是 `vibe_tracing.commands.*` |
| cli.py 未迁移 | `cli.py` 仍在根目录，未移入 `cli/main.py`，仍引用 `vibe_tracing.commands.*` |
| db.py 零调用 | db.py 接口完整实现，但 pipeline.py 未调用任何 db 函数（init_in_memory_db、load_tasks 等） |
| current.json 仍被引用 | pipeline.py、ghost_code_reconciler.py、doctor.py、tools.py 等多处仍引用 `claims/current.json` |
| evidence_index.json 仍被使用 | pipeline.py 仍输出单一 evidence_index.json，未拆分为 evidences/ |

---

## 二、 Phase 依赖关系

```
Phase 1 (infra/ + db.py)
  ├──→ Phase 2 (domain/ + claim_loader) ──→ Phase 3 (cli/ + evidence_builder) ──→ Phase 6 ──→ Phase 7
  ├──→ Phase 4 (gate engine SQL) ──────────────────────────────────────────────────┘
  └──→ Phase 5 (ghost code SQL) ──────────────────────────────────────────────────┘
```

| Phase | 核心产出 | 前置 | 可并行 |
|---|---|---|---|
| 1 | `infra/` + `analyzers/` 移动 + `infra/db.py` | — | — |
| 2 | `domain/` 移动 + `claim_loader` 重构 | Phase 1 | — |
| 3 | `cli/` 移动 + `evidence_builder` 重构 | Phase 1, 2 | — |
| 4 | `merge_gate_engine` SQL 化 | Phase 1 | 可与 Phase 2, 3 并行 |
| 5 | `ghost_code_reconciler` SQL 化 | Phase 1 | 可与 Phase 4 并行 |
| 6 | 流水线集成 | Phase 1-5 | — |
| 7 | Dashboard + 清理 | Phase 6 | — |

---

## 三、 Phase 详细任务清单

---

### Phase 1：基础层（infra/ + analyzers/ + db.py） — 🔄 进行中

**目标**：建立四层目录骨架，移动叶子模块（无重构），新建 `infra/db.py`。

**前置条件**：无。

#### 目录移动（已完成）

| 原路径 | 新路径 | 状态 |
|---|---|---|
| `core/enums.py` | `infra/enums.py` | ✅ |
| `core/ids.py` | `infra/validation/ids.py` | ✅ |
| `governance.py` | `infra/governance.py` | ✅ |
| `git_utils.py` | `infra/git_utils.py` | ✅ |
| `schema_validator.py` | `infra/validation/schema_validator.py` | ✅ |
| `operational_logger.py` | `infra/operational_logger.py` | ✅ |
| `hint_loader.py` | `infra/hint_loader.py` | ✅ |
| `tool_resolver.py` | `infra/tool_resolver.py` | ✅ |
| `traceability/__init__.py` | `analyzers/__init__.py` | ✅ |
| `traceability/ac_test_analyzer.py` | `analyzers/ac_test_analyzer.py` | ✅ |
| `traceability/claim_evidence_analyzer.py` | `analyzers/claim_evidence_analyzer.py` | ✅ |
| `traceability/requirement_task_analyzer.py` | `analyzers/requirement_task_analyzer.py` | ✅ |

#### Import 路径替换

| 替换规则 | 涉及文件数 | 状态 |
|---|---|---|
| `vibe_tracing.core.enums` → `vibe_tracing.infra.enums` | 7 | ✅ |
| `vibe_tracing.core.ids` → `vibe_tracing.infra.ids` | 10 | ✅ |
| > 注：`ids.py` 已进一步迁入 `infra/validation/ids.py`（最终路径 `vibe_tracing.infra.validation.ids`） | — | ✅ |
| `vibe_tracing.governance` → `vibe_tracing.infra.governance` | 3 | ✅ |
| `vibe_tracing.git_utils` → `vibe_tracing.infra.git_utils` | 3 | ✅ |
| `vibe_tracing.schema_validator` → `vibe_tracing.infra.schema_validator` | 6 | ✅ |
| > 注：`schema_validator.py` 已进一步迁入 `infra/validation/schema_validator.py`（最终路径 `vibe_tracing.infra.validation.schema_validator`） | — | ✅ |
| `vibe_tracing.operational_logger` → `vibe_tracing.infra.operational_logger` | 16 | ✅ |
| `vibe_tracing.hint_loader` → `vibe_tracing.infra.hint_loader` | 8 | ✅ |
| `vibe_tracing.tool_resolver` → `vibe_tracing.infra.tool_resolver` | 2 | ✅ |
| `vibe_tracing.traceability` → `vibe_tracing.analyzers` | 1 | ✅ |
| `grep -r "vibe_tracing.core\.\|vibe_tracing.traceability\." src/ tests/` 无结果 | — | ✅ |

#### infra/db.py 实现

- [x] DDL 建表（8 张表：tasks, task_acs, claims, claim_code_refs, claim_test_refs, test_results, coverage_reports, staged_files）
- [x] 格式校验（第一层）：validate_task / validate_claim / validate_test_result / validate_coverage_report
- [x] 数据泵（写入）：load_tasks / load_claims / load_staged_files / load_initial_cache
- [x] UPSERT API：upsert_test_result / upsert_coverage_report
- [x] 陈旧缓存清除：purge_stale_cache
- [x] 关系校验（第二层）：check_ac_coverage / check_coverage_violations / check_ghost_code / check_dangling_claims / check_test_dead_links / check_active_task_coverage
- [x] 数据导出：export_test_results / export_coverage_reports / persist_evidences
- [x] 零依赖约束（不导入任何 vibe_tracing.* 模块）

#### 测试

- [x] `tests/test_db_schema.py` — DDL + Upsert 测试
- [x] `tests/test_db_import.py` — 双层校验测试

#### 遗留未完成项

- [x] `schema_validator.py` 路径发现更新 — 已完成，当前使用 `Path(__file__).parent / "schemas"`（schemas 在同级 validation/ 目录下）
- [x] `operational_logger.py` logs 目录路径发现更新 — 已完成，使用 `project_root / ".vibetracing" / "logs"` 路径，不依赖自身包位置
- [ ] 删除空旧目录 `core/`、`traceability/` — ✅ 已完成

#### 验收标准

- [x] `pytest` 全量通过
- [x] `infra/db.py` 不导入任何 `vibe_tracing.*` 模块
- [x] 所有关系校验使用 LEFT JOIN 软校验（无硬 FK）
- [x] `purge_stale_cache()` 防止幽灵测试
- [x] `grep -r "vibe_tracing.core\.\|vibe_tracing.traceability\." src/ tests/` 无结果
- [x] `core/` 和 `traceability/` 目录已删除

**Phase 1 评估**：db.py 已实现但零调用。需要在 Phase 6（流水线集成）中接入 pipeline。

---

### Phase 2：领域层移动 + Claim 加载重构（domain/） — ✅ 已完成

**目标**：将 17 个领域模块移入 `domain/`，同时重构 `claim_loader.py`。

**前置条件**：Phase 1 完成。

#### 目录移动

| 原路径 | 新路径 | 状态 |
|---|---|---|
| `context.py` | `domain/context.py` | ✅ |
| `task_loader.py` | `domain/task_loader.py` | ✅ |
| `prd_parser.py` | `domain/prd_parser.py` | ✅ |
| `raw_input_loader.py` | `domain/raw_input_loader.py` | ✅ |
| `tool_evidence_adapter.py` | `domain/tool_evidence_adapter.py` | ✅ |
| `architecture_compliance_checker.py` | `domain/architecture_compliance_checker.py` | ✅ |
| `architecture_change_proposal.py` | `domain/architecture_change_proposal.py` | ✅ |
| `risk_advisor.py` | `domain/risk_advisor.py` | ✅ |
| `traceability_report_builder.py` | `domain/traceability_report_builder.py` | ✅ |
| `prd_arch_validator.py` | `domain/prd_arch_validator.py` | ✅ |
| `dashboard_renderer.py` | `domain/dashboard_renderer.py` | ✅ |
| `decision_server.py` | `domain/decision_server.py` | ✅ |
| `reflection_prompts.py` | `domain/reflection_prompts.py` | ✅ |
| `claim_loader.py` | `domain/claim_loader.py` | ✅ |
| `evidence_index_builder.py` | `domain/evidence_index_builder.py` | ✅ |
| `merge_gate_engine.py` | `domain/merge_gate_engine.py` | ✅ |
| `ghost_code_reconciler.py` | `domain/ghost_code_reconciler.py` | ✅ |

#### Import 路径替换

- [x] 所有 `vibe_tracing.context` → `vibe_tracing.domain.context`（7 文件）
- [x] 所有 `vibe_tracing.claim_loader` → `vibe_tracing.domain.claim_loader`（3 文件）
- [x] 所有 `vibe_tracing.task_loader` → `vibe_tracing.domain.task_loader`（4 文件）
- [x] 所有 `vibe_tracing.prd_parser` → `vibe_tracing.domain.prd_parser`（5 文件）
- [x] 所有 `vibe_tracing.raw_input_loader` → `vibe_tracing.domain.raw_input_loader`（3 文件）
- [x] 所有 `vibe_tracing.tool_evidence_adapter` → `vibe_tracing.domain.tool_evidence_adapter`（3 文件）
- [x] 所有 `vibe_tracing.architecture_compliance_checker` → `vibe_tracing.domain.architecture_compliance_checker`（1 文件）
- [x] 所有 `vibe_tracing.architecture_change_proposal` → `vibe_tracing.domain.architecture_change_proposal`（3 文件）
- [x] 所有 `vibe_tracing.risk_advisor` → `vibe_tracing.domain.risk_advisor`（2 文件）
- [x] 所有 `vibe_tracing.traceability_report_builder` → `vibe_tracing.domain.traceability_report_builder`（2 文件）
- [x] 所有 `vibe_tracing.prd_arch_validator` → `vibe_tracing.domain.prd_arch_validator`（3 文件）
- [x] 所有 `vibe_tracing.dashboard_renderer` → `vibe_tracing.domain.dashboard_renderer`（1 文件）
- [x] 所有 `vibe_tracing.reflection_prompts` → `vibe_tracing.domain.reflection_prompts`（1 文件）
- [x] 所有 `vibe_tracing.merge_gate_engine` → `vibe_tracing.domain.merge_gate_engine`（1 文件）
- [x] 所有 `vibe_tracing.evidence_index_builder` → `vibe_tracing.domain.evidence_index_builder`（1 文件）
- [x] 所有 `vibe_tracing.ghost_code_reconciler` → `vibe_tracing.domain.ghost_code_reconciler`（1 文件）

#### 代码重构

- [x] `domain/claim_loader.py`：删除 `claimed_status`、`credibility`、`evidence_refs` 字段（Claim dataclass 现仅保留 claim_id / related_task / code_refs / test_refs / notes / timestamp）
- [x] `domain/claim_loader.py`：`load_and_validate()` → `load()`
- [x] `domain/claim_loader.py`：支持 `CLAIM-*.json` glob 加载
- [x] `architecture_compliance_checker.py`：`_get_module_for_import` 兼容嵌套包路径

#### 验收标准

- [x] `pytest` 全量通过
- [x] `grep -r "from vibe_tracing\.\(context\|claim_loader\|task_loader\|prd_parser\|merge_gate_engine\|evidence_index_builder\|ghost_code_reconciler\) " src/ tests/` 无旧路径
- [x] `domain/claim_loader.py` 支持 `CLAIM-*.json` glob
- [x] `Claim` dataclass 无 `claimed_status`/`credibility`/`evidence_refs` 字段
- [x] `architecture_compliance_checker.py` 的 `_get_module_for_import` 能正确解析 `vibe_tracing.domain.X` 路径

---

### Phase 3：编排层移动 + 证据构建重构（cli/ + evidence_builder） — ❌ 未开始

**目标**：将命令模块移入 `cli/`，同时重构证据构建器。

**前置条件**：Phase 1（db.py）、Phase 2（claim_loader + domain 移动）完成。

#### 目录移动

| 原路径 | 新路径 | 状态 |
|---|---|---|
| `cli.py` | `cli/main.py` | ❌ |
| `commands/common.py` | `cli/common.py` | ❌ |
| `commands/accept.py` | `cli/accept.py` | ❌ |
| `commands/doctor.py` | `cli/doctor.py` | ❌ |
| `commands/finalize.py` | `cli/finalize.py` | ❌ |
| `commands/init.py` | `cli/init_cmd.py` | ❌ |
| `commands/analyze/*`（10 文件） | `cli/analyze/*` | ❌ |

#### 代码重构

- [ ] 重命名 `domain/evidence_index_builder.py` → `domain/evidence_builder.py`
- [ ] 重构 `EvidenceBuilder.build()`：删除 `output_path` 参数，新增显式 `tool_evidence` 参数
- [ ] 删除 mtime 比对逻辑（`_should_regenerate` 闭包）
- [ ] 删除 evidence_id 顺序编号
- [ ] 输出拆分为 `output/evidences/test_results.json` + `coverage_reports.json`
- [ ] 接收 `sqlite3.Connection` 而非自行管理文件
- [ ] `domain/claim_loader.py`：删除 `load()` 中的单文件分支（第 94-105 行 `else` 分支），仅保留 `content` 直接传入和目录 glob 两种模式；删除 docstring 中"向后兼容"描述

#### Import 路径替换

- [ ] `vibe_tracing.commands.common` → `vibe_tracing.cli.common`（6 文件）
- [ ] `vibe_tracing.commands.analyze.*` → `vibe_tracing.cli.analyze.*`（5 文件）
- [ ] 更新 `pyproject.toml` 的 `[project.scripts]` entry_points

#### 测试

- [ ] 重写 `tests/test_evidence_index_builder.py`
- [ ] 更新 `tests/test_schema_contracts.py`
- [ ] 删除空旧目录 `commands/`

#### 执行步骤

1. 创建 `cli/`、`cli/analyze/` 目录
2. 移动 16 个文件（cli.py + commands/*）
3. 创建 `cli/__init__.py`（re-export 入口）
4. 批量替换 import 路径
5. 更新 `pyproject.toml`
6. 重构 `EvidenceBuilder`（含 Schema 交接：先创建新 Schema 并注册到 validation 模块，再删除旧 `evidence_index.schema.json`，保证原子性——同一 commit 内完成，避免中间状态 pipeline 失败）
   - [ ] `build()` 签名简化为 `build(ctx)`——删除 `output_path` 和 `tool_evidence` 参数，`tool_evidence` 直接从 `ctx.tool_evidence` 获取
7. 重构 `raw_input_loader.py` + `claim_loader.py` — claims 加载从单文件改为 git staged 多文件（**P0，validation 前置条件**）：
    - **raw_input_loader.py**：
      - 删除 `defaults` 中 `"agent_claims": ".vibetracing/claims/current.json"` 的 hardcode 路径，改为 `".vibetracing/claims"`
      - `get_path("agent_claims")` 不再返回单一文件路径，改为返回 claims 目录路径
      - `_load_file()` 对 `agent_claims` 走新分支 `_load_claims_dir()`，其余 key 逻辑不变
      - 新增 `_load_claims_dir(claims_dir)`：扫描目录下所有 `CLAIM-*.json`，逐文件 JSON 解析后合并为 list，返回 `InputFileRecord(content=合并后的list)`
      - 新增 `_find_active_claims(claims_dir)`：通过 git 命令识别活跃 claims 文件
      - 对非 pre-commit 模式：三源合并（`git diff --cached` + `git diff` + `git status`），过滤 `CLAIM-*.json`
      - 对 pre-commit 模式：仅使用 `git diff --cached` 识别暂存区中的 `CLAIM-*.json`
      - manifest 中 `agent_claims` record 的 `file_path` 改为目录路径，`content` 为合并后的 claim list
    - **claim_loader.py**：
      - 删除 `load()` 中的单文件分支（第 94-105 行 `else` 分支），即不再支持 `claims_path` 指向单个 `.json` 文件
      - 仅保留两种模式：`content` 直接传入（内存/测试场景）或 `claims_path.is_dir()` 目录 glob
      - 删除 docstring 中"向后兼容的 current.json 模式"描述
    - **此步骤是 validation 模块正常工作的前置条件**：validate_inputs() 依赖 manifest 中的 content 进行校验，如果 claims 仍从 current.json 加载，校验的是旧格式
    - 参考设计：`docs/architecture_vision.md` section 三.1 "一任务一声明文件"
8. 重写相关测试
9. 运行 `pytest` 全量测试
10. 将 db.py 的 `validate_test_result`/`validate_coverage_report` 逻辑迁移到 validation 模块：
    - 新建 `validation/checks.py` 中的 `_check_test_results()` 和 `_check_coverage_reports()` 函数
    - 在 `validation/schema_validator.py` 的 `KNOWN_SCHEMAS` 中注册 `test_results` 和 `coverage_reports`
    - 在 `validation/checks.py` 的 `_check_schemas` 中添加 `test_results` 和 `coverage_reports` 的映射
    - 从 db.py 的 `load_initial_cache`/`upsert_test_result`/`upsert_coverage_report` 中移除格式校验调用
11. 将 db.py 的 `validate_task`/`validate_claim` 逻辑迁移到 validation 模块：
    - 在 `validation/checks.py` 中确保 `_check_id_formats` 和 `_check_path_safety` 覆盖 db.py 原有的校验规则
    - 从 db.py 的 `load_tasks`/`load_claims` 中移除 `validate_task`/`validate_claim` 调用
    - 更新 db.py 的 `load_tasks`/`load_claims` 注释，明确"数据已通过 validation 模块校验"
    - 运行 `pytest` 确认无回归
12. 删除空旧目录 `commands/`
13. 删除 `.vibetracing/claims/current.json` 和 `.vibetracing/claims/archive/` 目录（原则：历史债务完全清理，不保留旧架构文件）

#### db.py → validation 归口映射表

以下 4 个 validate_* 函数和 2 个正则变量需从 db.py 迁移到 validation 模块：

| db.py 函数/变量 | 校验规则 | 目标位置 | 迁移方式 |
|---|---|---|---|
| `validate_task` (L87-110) | task_id 正则 `TASK-[A-Z]+-\d{3,4}` | `validation/checks.py` → `_check_id_formats` + JSON Schema enum | task_id 正则已被 `ids.validate_id()` 覆盖；priority/status 枚举由 `task_list.schema.json` 的 enum 校验覆盖。删除 `validate_task`，load_tasks 不再调用 |
| `validate_claim` (L113-146) | claim_id 正则、related_task 正则、code_refs/test_refs 路径安全 | `validation/checks.py` → `_check_id_formats` + `_check_path_safety` | claim_id/related_task 正则已被 `ids.validate_id()` 覆盖；路径安全已被 `_check_path_safety` 覆盖。删除 `validate_claim`，load_claims 不再调用 |
| `validate_test_result` (L149-171) | nodeid 非空+`::` 格式、outcome 枚举、exit_code 非负 | `validation/checks.py` → 新增 `_check_test_results` + `test_results.schema.json` | 需新建 `test_results.schema.json`（nodeid pattern、outcome enum、exit_code minimum），注册到 SchemaValidator，`_check_schemas` 添加映射 |
| `validate_coverage_report` (L174-207) | source_path 路径安全、percent_covered 0-100、status 枚举 | `validation/checks.py` → 新增 `_check_coverage_reports` + `coverage_reports.schema.json` | 需新建 `coverage_reports.schema.json`（source_path pattern、percent_covered minimum/maximum、status enum），注册到 SchemaValidator，`_check_schemas` 添加映射 |
| `_RE_TASK` (L83) | 正则 `^TASK-[A-Z]+-\d{3,4}$` | 删除 | 已被 `validation/ids.py` 的 TASK 正则覆盖（且 ids.py 支持项目前缀，更完整） |
| `_RE_CLAIM` (L84) | 正则 `^CLAIM-[A-Z]+-\d{3,4}$` | 删除 | 已被 `validation/ids.py` 的 CLAIM 正则覆盖 |

**迁移顺序**：
1. Phase 1 步骤 10：迁移 `validate_task` + `validate_claim` + 删除 `_RE_TASK`/`_RE_CLAIM`
2. Phase 3 步骤 11：迁移 `validate_test_result` + `validate_coverage_report`（依赖新 Schema 文件）

**迁移后 db.py 的 load_* 函数变化**：

```python
# 迁移前（当前）
def load_tasks(conn, tasks):
    for task in tasks:
        errs = validate_task(task)  # ← 校验
        if errs: ...
        conn.execute("INSERT ...")

# 迁移后（目标）
def load_tasks(conn, tasks):
    for task in tasks:
        # 前置条件：数据已通过 validation/checks.py 的 validate_inputs() 校验
        conn.execute("INSERT ...")  # ← 仅 INSERT
```

#### 验收标准

- [ ] `pytest` 全量通过
- [ ] `grep -r "from vibe_tracing\.commands" src/ tests/` 无结果
- [ ] `vt analyze` 生成 `output/evidences/test_results.json` + `coverage_reports.json`
- [ ] 新 JSON 通过 Schema 校验
- [ ] `output/evidence_index.json` 不再生成
- [ ] db.py 的 `validate_task`/`validate_claim` 已移除，`load_*` 函数仅执行 INSERT
- [ ] validation 模块覆盖 task_list 和 agent_claims 的全部第一层格式校验规则
- [ ] `grep -rn "current\.json" src/` 无结果（`raw_input_loader.py`、`claim_loader.py`、`init_cmd.py`、`doctor.py`、`tools.py`、`output.py`、`evidence_index_builder.py`、`ghost_code_reconciler.py` 均无 `current.json` 引用）
- [ ] `claim_loader.py` 的 `load()` 无单文件分支（`else: json.load(claims_path)` 已删除）
- [ ] `raw_input_loader.py` 的 `defaults["agent_claims"]` 指向目录而非文件

---

### Phase 4：门禁引擎 SQL 化（merge_gate_engine） — ❌ 未开始

**目标**：将门禁判定逻辑从 Python 嵌套循环改为 SQL 查询。

**前置条件**：Phase 1（db.py）完成。可与 Phase 2、3 并行。

**涉及文件**：

| 操作 | 文件 |
|---|---|
| 重构 | `domain/merge_gate_engine.py` |
| 更新 | `tests/test_merge_gate_engine.py` |
| 更新 | `tests/test_quality_gates.py` |
| 更新 | `tests/test_integration_v3.py` |
| 更新 | `tests/test_e2e_samples.py` |

#### 执行步骤

- [ ] 构造函数新增 `conn: sqlite3.Connection` 参数
- [ ] `evaluate()` 签名从 11 参数简化为 4 参数：`(compliance_res, staged_items, directly_staged_items, human_decisions)`
- [ ] 删除静态方法 `check_claim_exists()`，替代：`db.check_ghost_code(conn)`
- [ ] 删除静态方法 `check_ac_coverage()`，替代：`db.check_ac_coverage(conn)`
- [ ] `_compute_gate_decision()` 中的覆盖率检查提取为 `db.check_coverage_violations(conn)`
- [ ] 内部调用 `db.check_ac_coverage(conn)`、`db.check_coverage_violations(conn)` 获取判定数据
- [ ] 保留 `_is_current()`、`_tag_reason()` 辅助方法
- [ ] 保留 `_process_must_gaps/risks`、`_process_should_gaps/risks` 处理逻辑
- [ ] 更新所有测试文件中的构造函数调用和 `evaluate()` 参数

#### 验收标准

- [ ] `pytest tests/test_merge_gate_engine.py` 通过
- [ ] `pytest tests/test_quality_gates.py` 通过
- [ ] 无 Python 嵌套循环遍历 `evidence_index` 的代码残留
- [ ] `evaluate()` 签名为 4 参数

---

### Phase 5：幽灵代码检测 SQL 化（ghost_code_reconciler） — ❌ 未开始

**目标**：删除 `git show HEAD`，幽灵代码检测改为 SQL 查询。

**前置条件**：Phase 1（db.py）完成。可与 Phase 4 并行。

**涉及文件**：

| 操作 | 文件 |
|---|---|
| 重构 | `domain/ghost_code_reconciler.py` |
| 更新 | `tests/test_ghost_code_reconciler.py` |
| 更新 | `tests/test_integration_v3.py` |

#### 执行步骤

- [ ] 构造函数新增 `conn: sqlite3.Connection` 参数
- [ ] 删除 `_get_active_claims_code_refs()` 中的 `git show HEAD` 子进程
- [ ] 活跃 Claim 识别改为：staged_files 匹配 `CLAIM-*.json`
- [ ] 幽灵代码检测改为 `db.check_ghost_code(conn)` SQL 查询
- [ ] 保留 `reconcile()` 方法名（不重命名为 `check()`）
- [ ] 保留 `_check_task_coverage()` 和 `_check_ac_freshness()`（Gate 2.5 逻辑）
- [ ] 保留 `_is_whitelisted()` 白名单机制
- [ ] 更新测试文件

#### 验收标准

- [ ] `pytest tests/test_ghost_code_reconciler.py` 通过
- [ ] 无 `git show HEAD` 子进程调用残留
- [ ] 无 `claims/current.json` 文件读取残留
- [ ] Gate 2.5 AC 新鲜度检查正常工作

---

### Phase 6：流水线集成 — ❌ 未开始

**目标**：将前 5 个 Phase 的模块变更集成到流水线编排层。

**前置条件**：Phase 1-5 全部完成。

**涉及文件**：

| 操作 | 文件 |
|---|---|
| 重构 | `cli/analyze/pipeline.py` |
| 修改 | `cli/common.py` |
| 修改 | `cli/analyze/tools.py` |
| 修改 | `cli/analyze/analysis.py` |
| 修改 | `cli/analyze/reports.py` |
| 修改 | `cli/analyze/output.py` |
| 修改 | `cli/main.py`（清理 re-export） |
| 修改 | `domain/context.py` |
| 修改 | `cli/doctor.py` |
| 修改 | `cli/init_cmd.py` |
| 修改 | `docs/architecture_constraints.json` |
| 删除 | `.vibetracing/claims/current.json` |
| 删除 | `.vibetracing/claims/archive/` |
| 更新 | `tests/test_cli_analyze.py` |
| 更新 | `tests/test_integration_v3.py` |
| 删除测试 | `test_integration_v3.py` 中的 `TestRunClaimTests` + `TestArchiveClaims` |
| 删除测试 | `test_timing_instrumentation.py` 中的 `TestRunClaimTestsTiming` |
| 删除测试 | `test_instrumentation_logging.py` 中的 `TestClaimTestCacheStats` |

#### 执行步骤

- [ ] `cli/common.py`：`_load_context` 中 claims 加载已由 Phase 3 step 8 完成（raw_input_loader 输出 content → claim_loader.load(content=...)），Phase 6 不需重复操作
- [ ] `cli/analyze/tools.py`：删除 `_archive_claims` 函数
- [ ] `cli/analyze/analysis.py`：删除 `_run_claim_tests` 函数
- [ ] `cli/analyze/pipeline.py`：
  - [ ] 新增 `init_in_memory_db()` 调用
  - [ ] 新增 `db.load_tasks()` / `db.load_claims()` / `db.load_staged_files()` / `db.load_initial_cache()` 调用
  - [ ] `EvidenceBuilder` 接收 `conn`
  - [ ] `MergeGateEngine` 接收 `conn`
  - [ ] 删除 `_archive_claims` 调用
  - [ ] 删除 `_run_claim_tests` 调用
  - [ ] 删除 `evidence_index["test_results"]` 跳过判断逻辑（pipeline.py:349），统一由 `execute_all()` 处理
  - [ ] `_auto_generate_claim_from_staged()` 改为写入 `CLAIM-{prefix}-{seq}.json`，编号逻辑：glob `.vibetracing/claims/CLAIM-{prefix}-*.json` → 提取所有编号 → 取 max+1 → 零填充为 3 位
  - [ ] `conn.close()` 在 finally 块中
- [ ] `cli/analyze/reports.py`：适配 evidence 拆分格式
- [ ] `cli/analyze/output.py`：Dashboard 内嵌数据改为三份 JSON
- [ ] `cli/main.py`：清理 `_archive_claims` / `_run_claim_tests` 的 re-export
- [ ] `cli/doctor.py`：
  - [ ] 删除硬编码 `current.json` 路径（第 40 行），改为 `ClaimLoader().load(claims_path)` 加载多文件
  - [ ] 删除 Check 1 `evidence_refs_integrity`（claim 的 `evidence_refs` 字段已在 Phase 2 删除，该检查已无意义）
  - [ ] Check 2 `file_refs_integrity` 逻辑不变（检查 code_refs/test_refs 磁盘存在性，与数据来源解耦）
  - [ ] 新增 Check：逐个 claim 的 `related_task` 是否存在于 task_list 中（复用 `db.check_dangling_claims(conn)` 或等效 SQL）
- [ ] `cli/init_cmd.py`：
  - [ ] 不再创建 `current.json` 和 `archive/` 目录
  - [ ] 创建 `.vibetracing/claims/` 目录 + `.gitkeep`
  - [ ] `config.template.json` 的 `paths.agent_claims` 默认值改为 `.vibetracing/claims`（目录路径）
  - [ ] 不创建初始 `CLAIM-*.json` 模板文件（Claim 由 Agent 在开发过程中按需创建）
- [ ] `docs/architecture_constraints.json`：
  - [ ] `module_boundaries` 中所有 `owned_files` 更新为嵌套包路径
  - [ ] `claims/current.json` 引用改为 `claims/CLAIM-*.json`
  - [ ] `evidence_index.json` 引用改为 `evidences/test_results.json` + `evidences/coverage_reports.json`
  - [ ] `governance_boundary` 中的 `included_patterns` 更新
  - [ ] **修改后必须重新执行 `vt finalize`**，更新 `architecture_constraints_hash` 基线，否则 Gate 1 哈希校验会阻断 `vt analyze`
- [ ] 删除 `.vibetracing/claims/current.json` 和 `archive/` 目录
- [ ] 清理被删除函数的测试类
- [ ] 运行 `pytest` 全量测试

#### 验收标准

- [ ] `pytest` 全量通过
- [ ] `vt analyze --pre-commit` 端到端可运行
- [ ] `vt analyze` 完整运行，生成 `output/evidences/` 目录
- [ ] `vt doctor` 正常运行，不报 `current.json` 或 `evidence_index.json` 缺失
- [ ] `vt init` 创建 `CLAIM-*.json` 模板而非 `current.json`
- [ ] 无 `current.json`、`_archive_claims`、`_run_claim_tests` 的任何引用残留
- [ ] `architecture_constraints.json` 中无旧路径引用
- [ ] Gate 决策正确（blocked/pass）

---

### Phase 7：Dashboard 模板迁移 + 清理 — ❌ 未开始

**目标**：适配 Dashboard 模板到新 evidence 格式，清理所有遗留文件。

**前置条件**：Phase 6 完成。

**涉及文件**：

| 操作 | 文件 |
|---|---|
| 修改 | `templates/dashboard.template.html` |
| 修改 | `domain/dashboard_renderer.py` |
| 删除 | `output/evidence_index.json`（如仍存在） |
| 新建 | `tests/test_dashboard_template.py`（验证模板渲染不报错） |

#### 执行步骤

- [ ] 模板变量变更：
  - [ ] 删除 `evidence_idx_json` 注入变量
  - [ ] 新增 `test_results_json` + `coverage_reports_json` 注入变量
  - [ ] `evidenceIndex.evidences[]` 引用改为 `testResults[]` + `coverageReports[]`
- [ ] JavaScript 函数迁移：
  - [ ] `jumpToEvidence(evidence_id)` → `jumpToTest(nodeid)` + `jumpToCoverage(source_path)`
  - [ ] `reqCoverageMap` 构建逻辑改为从两个数组分别构建
  - [ ] `renderCoverageHeatmap()` 改为读取 `coverageReports[]`
  - [ ] Claim-Evidence 关联渲染改为通过 `nodeid`/`source_path` 匹配
  - [ ] Evidence Tab 改为分别渲染 Test Results 和 Coverage 两个子 Tab
  - [ ] 搜索功能改为搜索扁平字段
- [ ] `domain/dashboard_renderer.py`：注入新的模板变量
- [ ] 删除残留的 `output/evidence_index.json`
- [ ] 运行 `vt analyze`，在浏览器中打开 `output/dashboard.html` 验证所有 Tab

#### 验收标准

- [ ] `pytest` 全量通过
- [ ] Dashboard 在浏览器中正常渲染所有 Tab
- [ ] Evidence Tab 显示 Test Results 和 Coverage 两个子区域
- [ ] 点击 AC/Claim 能跳转到对应的测试结果
- [ ] 搜索功能正常工作
- [ ] 无 `evidence_id`、`evidenceIndex`、`e.details` 的引用残留

---

## 四、 偏离点跟踪表

以下是审计中发现的所有偏离项，按优先级排序。执行时逐项检查，完成后打勾。

| # | GAP 编号 | 涉及文件 | 优先级 | 简述 | 状态 |
|---|---|---|---|---|---|
| 1 | GAP-CMD-001 | `commands/` 整个目录 | P0 | commands/ 目录未迁入 cli/，10 个 analyze 子模块仍在原位 | [ ] |
| 2 | GAP-CMD-002 | `cli.py` | P0 | cli.py 未迁移为 cli/main.py，仍引用 `vibe_tracing.commands.*` | [ ] |
| 3 | GAP-CMD-003 | `cli.py` re-export | P0 | cli.py 仍 re-export `_archive_claims` 和 `_run_claim_tests` | [ ] |
| 4 | GAP-DB-001 | `pipeline.py` | P0 | pipeline.py 未调用 `init_in_memory_db()` 或任何 db 函数 | [ ] |
| 5 | GAP-DB-002 | `pipeline.py` | P0 | pipeline.py 仍输出单一 `evidence_index.json`，未拆分 | [ ] |
| 6 | GAP-CLAIM-001 | `pipeline.py` | P0 | `_auto_generate_claim_from_staged()` 仍写入 `claims/current.json`（第 63 行），需改为写入 `CLAIM-*.json`（每次运行持续产生旧架构产物） | [ ] |
| 7 | GAP-CLAIM-002 | `ghost_code_reconciler.py` | P1 | ghost_code_reconciler.py 仍引用 `claims/current.json` 路径 | [ ] |
| 8 | GAP-CLAIM-003 | `doctor.py` | P1 | doctor.py 检查 `claims/current.json` 是否存在（第 40 行），需改为检查 `claims/` 目录或 glob `CLAIM-*.json` | [ ] |
| 9 | GAP-CLAIM-004 | `tools.py` | P0 | `_archive_claims()` 读取 `current.json` 并移动到 archive（第 271 行）→ **彻底删除该函数**（每次 pipeline 运行持续产生旧架构副作用） | [ ] |
| 10 | GAP-CLAIM-005 | `config.template.json` | P1 | 模板仍引用 `claims/current.json`（每次 `vt init` 会生成指向旧架构路径的配置，是债务源头） | [ ] |
| 11 | GAP-CLAIM-006 | `prd_analysis.template.md` | P1 | 模板仍引用 `claims/current.json`（Agent 生成分析文档时会复制旧架构路径） | [ ] |
| 12 | GAP-CLAIM-007 | `field_hints.json` | P2 | hints 仍引用 `claims/current.json` 和 `evidence_index.json` | [ ] |
| 12b | GAP-CLAIM-008 | `raw_input_loader.py` | P0 | claims 加载仍 hardcode `current.json` 路径，需改为 git staged 多文件 `CLAIM-*.json`。**此 GAP 是 validation 模块正常工作的前置条件** | [ ] |
| 12c | GAP-CLAIM-009 | `claim_loader.py` | P0 | `load()` 仍保留单文件分支（第 94-105 行），支持 `claims_path` 指向 `current.json`。需删除该分支，仅保留 content 直接传入和目录 glob 两种模式 | [ ] |
| 12d | GAP-CLAIM-010 | `init_cmd.py` | P1 | `vt init` 仍创建 `current.json` 模板文件，需改为创建 `claims/` 目录 + `.gitkeep`（不创建 claim 模板文件，Claim 由 Agent 按需创建） | [ ] |
| 12e | GAP-CLAIM-011 | `output.py` | P3 | 错误提示仍引导用户手动创建 `current.json`，需改为 `CLAIM-*.json` | [ ] |
| 12f | GAP-CLAIM-012 | `evidence_index_builder.py` | P1 | fallback 路径仍硬编码 `current.json`（第 128 行），需删除该 fallback，manifest 中的 content 已由 raw_input_loader 提供 | [ ] |
| 13 | GAP-EVID-001 | `pipeline.py` | P1 | `_run_claim_tests()` 仍存在且被调用 | [ ] |
| 14 | GAP-EVID-002 | `analysis.py` | P1 | `_run_claim_tests()` 函数定义仍存在 | [ ] |
| 15 | GAP-EVID-003 | `evidence_index_builder.py` | P1 | 类名仍为 `EvidenceIndexBuilder`，未重命名为 `EvidenceBuilder` | [ ] |
| 16 | GAP-EVID-004 | `evidence_index_builder.py` | P1 | 仍使用 mtime 比对逻辑，未改为 SQLite UPSERT | [ ] |
| 17 | GAP-EVID-005 | `infra/validation/schemas/evidence_index.schema.json` | P2 | 旧 schema 仍存在，未被拆分 schema 替代 | [ ] |
| 18 | GAP-GATE-001 | `merge_gate_engine.py` | P1 | 构造函数未接收 `conn` 参数 | [ ] |
| 19 | GAP-GATE-002 | `merge_gate_engine.py` | P1 | `evaluate()` 仍为 11 参数签名 | [ ] |
| 20 | GAP-GHOST-001 | `ghost_code_reconciler.py` | P1 | 构造函数未接收 `conn` 参数 | [ ] |
| 21 | GAP-GHOST-002 | `ghost_code_reconciler.py` | P1 | 仍使用 `git show HEAD` 子进程 | [ ] |
| 22 | GAP-TEST-001 | `test_integration_v3.py` | P2 | `TestArchiveClaims` 测试类待删除 | [ ] |
| 23 | GAP-TEST-002 | `test_integration_v3.py` | P2 | `TestRunClaimTests` 测试类待删除 | [ ] |
| 24 | GAP-TEST-003 | `test_timing_instrumentation.py` | P2 | `TestRunClaimTestsTiming` 测试类待删除 | [x] |
| 25 | GAP-TEST-004 | `test_instrumentation_logging.py` | P2 | `TestClaimTestCacheStats` 测试类待删除 | [x] |
| 26 | GAP-CONS-001 | `architecture_constraints.json` | P2 | `module_boundaries` 中仍使用旧路径 | [ ] |
| 27 | GAP-CONS-002 | `architecture_constraints.json` | P2 | 仍引用 `claims/current.json` 和 `evidence_index.json` | [ ] |
| 28 | GAP-DASH-001 | `dashboard.template.html` | P3 | 模板仍绑定 `evidenceIndex.evidences[]` | [ ] |
| 29 | GAP-DASH-002 | `dashboard.template.html` | P3 | 仍使用 `e.details.outcome` 嵌套字段 | [ ] |
| 30 | GAP-DASH-003 | `dashboard_renderer.py` | P3 | 仍注入 `evidence_idx_json` 变量 | [ ] |
| 31 | GAP-VAL-001 | `db.py` + `infra/validation/checks.py` | P2 | db.py 与 validation/checks.py 的校验功能重叠 → Phase 1 task/claim 校验已迁移 ✅，Phase 3 test_result/coverage 校验待迁移 | [x] |
| 32 | GAP-DOC-001 | `docs/architecture_vision.md` | P2 | architecture_vision.md 未提及 infra/validation/ 是第一层格式校验的实现 | [ ] |
| 33 | GAP-DOCTOR-001 | `doctor.py` | P1 | Check 1 `evidence_refs_integrity` 检查 claim 的 `evidence_refs` 字段（第 198-220 行），但该字段已在 Phase 2 删除 → **删除该检查** | [ ] |
| 34 | GAP-FINALIZE-001 | `docs/analyze_execution_plan.md` | P1 | Phase 6 修改 `architecture_constraints.json` 后必须重新执行 `vt finalize` 更新哈希基线，否则 Gate 1 阻断 | [ ] |
| 35 | GAP-PIPE-001 | `pipeline.py` | P1 | pipeline.py:349 直接检查 `evidence_index["test_results"]` 是否为空来决定跳过重跑，删除 `_run_claim_tests` 后此判断需同步移除 | [ ] |

### 优先级说明

- **P0**：阻断性问题，Phase 3 无法开始的前提
- **P1**：核心功能缺失，影响 Phase 4-6 的执行
- **P2**：清理项，影响 Phase 6-7 的完成度
- **P3**：Dashboard 适配，仅影响 Phase 7

---

## 五、 下一步建议

### 推荐执行路径

```
当前状态 → Phase 3（cli/ 移动 + evidence_builder 重构）
          ├──→ Phase 4（gate engine SQL 化）  [可并行]
          └──→ Phase 5（ghost code SQL 化）   [可并行]
                    ↓
                  Phase 6（流水线集成）
                    ↓
                  Phase 7（Dashboard + 清理）
```

**当前阻塞项**：Phase 3 是下一个必须执行的 Phase。Phase 4 和 Phase 5 只依赖 Phase 1（db.py 已完成），理论上可与 Phase 3 并行，但由于 Phase 4/5 的测试文件与 Phase 3 的测试清理有重叠（如 `test_integration_v3.py`），并行会增加测试维护负担。建议按串行执行以减少冲突风险。

**预估工作量**：

| Phase | 预估步骤数 | 复杂度 |
|---|---|---|
| Phase 3 | ~12 步 | 高（目录移动 + evidence_builder 重写 + Schema 变更） |
| Phase 4 | ~9 步 | 中（evaluate 签名简化 + SQL 替换） |
| Phase 5 | ~8 步 | 中（删除 git show + SQL 替换） |
| Phase 6 | ~13 步 | 高（pipeline 重编排 + 多文件适配 + 测试清理） |
| Phase 7 | ~10 步 | 中（JS 函数迁移 + 模板验证） |

---

## 六、 风险与缓解

| 风险 | 影响 Phase | 缓解措施 |
|---|---|---|
| import 路径替换遗漏 | Phase 3 | 每个 Phase 结束后运行 `grep` 验证无旧路径残留 |
| ~~SQLite FK 在内存模式不生效~~ | ~~Phase 3~~ | ~~已删除~~：所有 FK 均为软校验（LEFT JOIN），DDL 无 FOREIGN KEY 声明，不需要 PRAGMA。与 `architecture_vision.md` 5.5 节一致 |
| 移动 + 重构同 Phase 导致 diff 过大 | Phase 3 | 拆为两个 commit：先移动（纯 import 变更），再重构（逻辑变更） |
| evidence 格式变更导致分析器异常 | Phase 3, 6 | 分析器接口不变，但需验证 `evidence_list` 的数据结构兼容性 |
| Dashboard 模板 JS 逻辑复杂 | Phase 7 | 按函数逐一迁移，每个函数迁移后在浏览器中验证 |
| 测试文件大量修改引入回归 | Phase 3-6 | 每个 Phase 结束后 `pytest` 全量通过才进入下一 Phase |
| commands/ 残留目录导致 import 冲突 | Phase 3 | Phase 3 完成后立即删除空 commands/ 目录 |
