# Original User Request

## Initial Request — 2026-06-22T10:17:40Z

对 Vibe Tracing 项目的数据库操作层进行重构与扩展：将 `src/vibe_tracing/infra/db.py` 拆分为 `infra/db/` 子包，并扩展 requirements 及 acceptance_criteria 的建表与基本装载/查询逻辑。

Working directory: /Users/lihan/Project/Vibe_Tracing
Integrity mode: development

## Requirements

### R1. 数据库子模块拆分 (db split)
将现有单文件 `src/vibe_tracing/infra/db.py` 拆分为 `src/vibe_tracing/infra/db/` 子包，结构包括：
- `__init__.py`: 集中导出对外接口，保持与原 db.py 的 import 向上兼容。
- `schema.py`: 数据库初始化与表结构定义（`init_in_memory_db`）。
- `loaders.py`: 数据泵加载函数（`load_tasks`, `load_claims`, `load_staged_files`, `load_initial_cache`, `load_prd`）。
- `queries.py`: SQL 关系查询函数（`check_ac_coverage`, `check_coverage_violations`, `check_requirement_coverage`, `check_claim_evidence`, `get_full_chain`）。
- `exports.py`: 数据状态导出与清理（`upsert_test_result`, `upsert_coverage_report`, `purge_stale_cache`）。

### R2. 扩展新表结构与装载逻辑 (PRD Schema & Loaders)
- 在 `schema.py` 中为 `init_in_memory_db()` 新增 `requirements` 与 `acceptance_criteria` 两张表：
  ```sql
  CREATE TABLE requirements (
      req_id   TEXT PRIMARY KEY,
      title    TEXT NOT NULL,
      priority TEXT NOT NULL,
      category TEXT NOT NULL
  );
  CREATE TABLE acceptance_criteria (
      ac_id               TEXT PRIMARY KEY,
      req_id              TEXT NOT NULL,
      title               TEXT NOT NULL,
      is_testing_required INTEGER NOT NULL -- 0 表示否，1 表示是
  );
  ```
- 在 `loaders.py` 中新增 `load_prd(conn, prd)` 函数，将 `PrdParseResult` 数据映射写入 to 上述新表中。

### R3. SQL 查询层扩展与重构 (SQL queries)
- 在 `queries.py` 中新增三个查询函数：
  - `check_requirement_coverage(conn: sqlite3.Connection) -> List[dict]`: 
    返回结构 `[{"req_id": "...", "title": "...", "priority": "...", "status": "...", "task_count": ...}, ...]`
  - `check_claim_evidence(conn: sqlite3.Connection) -> List[dict]`: 
    返回结构 `[{"claim_id": "...", "related_task": "...", "status": "...", "test_count": ..., "passed_count": ...}, ...]`
  - `get_full_chain(conn: sqlite3.Connection) -> List[dict]`:
    大 JOIN 串联 requirements -> acceptance_criteria -> tasks -> claims -> claim_test_refs -> test_results -> coverage_reports
- 在 `queries.py` 中重构 `check_ac_coverage(conn: sqlite3.Connection) -> List[dict]`，将 SQL 起点改为从 `acceptance_criteria` 表出发进行 `LEFT JOIN` 查询，不再从 `task_acs` 出发。

## Verification Resources
- 项目中现有的单元测试套件：`pytest tests/`。
- 新增的单元测试 `tests/test_db_query_functions.py` 用以专项验证 R3 新查询函数及重构函数结果的正确性。

## Acceptance Criteria

### 编译与兼容性
- [ ] 所有原模块对 `vibe_tracing.infra.db` 的 import 不需要修改，包拆分后能够通过 `__init__.py` 保持 100% 的向上兼容。
- [ ] 整个项目（包括 CLI 和其他 domain 模块）无 any `ImportError`，代码全量编译/静态语法检查通过。

### 功能与测试
- [ ] 单元测试 `tests/test_db_schema.py` 运行通过，成功验证表创建和数据 load 的流程。
- [ ] 新建的单元测试 `tests/test_db_query_functions.py` 覆盖所有新增和重构的查询函数，SQL 语法在 SQLite 内存库中完全正确，且返回结构（Keys）与设计完全对齐。
- [ ] 运行 `pytest tests/` 全量通过，无 any regression 衰退。
