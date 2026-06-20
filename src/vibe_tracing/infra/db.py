"""
VT 内存数据库管理模块

为什么需要这个模块：
  VT 的分析流水线需要在多个数据实体（Task、Claim、Test、Coverage）之间
  进行关联查询（如"某个 Claim 引用的测试是否通过"）。旧架构用 Python
  嵌套循环手动拼装字典，容易产生逻辑缝隙。本模块用内存 SQLite 替代，
  通过 SQL JOIN 一次性查出所有关联关系。

核心设计：
  - 双层校验：第一层（格式校验）由 validation 模块负责，第二层（关系校验）
    由本模块的 check_* 函数通过 SQL LEFT JOIN 实现
  - 软外键：不使用物理 FOREIGN KEY 约束，避免单条错误中断整个导入事务
  - UPSERT 缓存：新结果覆盖旧缓存，未重跑的记录通过 carried_over 标记保留
  - 零依赖：仅使用 Python 标准库（sqlite3、json、pathlib），不导入任何
    vibe_tracing.* 模块，防止循环导入

依赖关系：
  本模块是叶子节点，不依赖项目内其他模块。
  被以下模块调用：pipeline.py（调度）、evidence_builder.py（证据构建）、
  ghost_code_reconciler.py（幽灵检测）、merge_gate_engine.py（门禁判定）
"""

import json
import sqlite3
from pathlib import Path


# ── 辅助函数 ─────────────────────────────────────────────────────────────────

def _coerce_strlist(val) -> list:
    """将任意值规范化为字符串列表。

    输入：
        val: 任意类型的值（可能来自 JSON 解析）
    处理逻辑：
        1. 如果是列表，逐元素转字符串
        2. 如果是 None，返回空列表
        3. 如果是单个值，转为单元素列表
    输出：
        返回字符串列表（保证后续 INSERT 操作不会因类型问题失败）
    """
    if isinstance(val, list):
        return [str(x) for x in val]
    if val is None:
        return []
    return [str(val)]


# ── 1. 数据库初始化 ─────────────────────────────────────────────────────────

def init_in_memory_db() -> sqlite3.Connection:
    """创建内存 SQLite 数据库并建表。

    输入：
        无参数
    前置条件：
        无
    处理逻辑：
        1. 创建 :memory: SQLite 连接
        2. 关闭 WAL 和 synchronous 模式（内存数据库无需持久化保证，提升性能）
        3. 创建 8 张表：tasks、task_acs、claims、claim_code_refs、
           claim_test_refs、test_results、coverage_reports、staged_files
    输出：
        返回数据库连接（由 pipeline.py 接管生命周期，运行结束后关闭）

    设计决策：
      - 不声明 FOREIGN KEY，所有关系校验通过 check_* 函数的 LEFT JOIN 实现
      - 理由：硬 FK 会在第一个错误记录时中断事务，导致用户无法一次性看到所有错误
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")

    conn.executescript("""
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY,
            priority TEXT NOT NULL,
            status   TEXT NOT NULL
        );
        CREATE TABLE task_acs (
            task_id TEXT,
            ac_id   TEXT,
            PRIMARY KEY (task_id, ac_id)
        );
        CREATE TABLE claims (
            claim_id     TEXT PRIMARY KEY,
            related_task TEXT NOT NULL
        );
        CREATE TABLE claim_code_refs (
            claim_id  TEXT,
            code_path TEXT,
            PRIMARY KEY (claim_id, code_path)
        );
        CREATE TABLE claim_test_refs (
            claim_id     TEXT,
            test_nodeid  TEXT,
            PRIMARY KEY (claim_id, test_nodeid)
        );
        CREATE TABLE test_results (
            nodeid       TEXT PRIMARY KEY,
            outcome      TEXT NOT NULL,
            exit_code    INTEGER NOT NULL,
            command      TEXT,
            carried_over INTEGER DEFAULT 0
        );
        CREATE TABLE coverage_reports (
            source_path      TEXT PRIMARY KEY,
            percent_covered  REAL NOT NULL,
            num_statements   INTEGER,
            status           TEXT NOT NULL,
            carried_over    INTEGER DEFAULT 0
        );
        CREATE TABLE staged_files (
            file_path TEXT PRIMARY KEY
        );
    """)
    return conn


# ── 2. 数据泵（写入）──────────────────────────────────────────────────────

def load_tasks(conn: sqlite3.Connection, tasks: list) -> None:
    """批量加载任务到数据库。

    输入：
        conn:  数据库连接（由 pipeline.py 通过 init_in_memory_db() 创建）
        tasks: Task 字典列表（由 pipeline.py 从 task_loader 的输出
               [t.__dict__ for t in ctx.task_result.tasks] 转换而来）
    前置条件：
        tasks 已通过 validation/checks.py 的格式校验（task_id 正则、
        priority/status 枚举值、ac_id 正则等）
    处理逻辑：
        1. 每个 Task 的 task_id、priority、status 写入 tasks 表
        2. 每个 Task 的 related_acceptance_criteria 数组拆分为多条
           task_acs 关联记录（一对多关系）
    输出：
        数据库中新增 tasks + task_acs 记录（INSERT OR REPLACE）
    """
    for task in tasks:
        conn.execute(
            "INSERT OR REPLACE INTO tasks (task_id, priority, status) VALUES (?, ?, ?)",
            (task["task_id"], task["priority"], task["status"]),
        )
        for ac in _coerce_strlist(task.get("related_acceptance_criteria", [])):
            conn.execute(
                "INSERT OR REPLACE INTO task_acs (task_id, ac_id) VALUES (?, ?)",
                (task["task_id"], ac),
            )
    conn.commit()


def load_claims(conn: sqlite3.Connection, claims: list) -> None:
    """批量加载开发声明到数据库。

    输入：
        conn:   数据库连接（由 pipeline.py 通过 init_in_memory_db() 创建）
        claims: Claim 字典列表（由 pipeline.py 从 claim_loader 的输出
                [asdict(c) for c in ctx.claims_list] 转换而来）
    前置条件：
        claims 已通过 validation/checks.py 的格式校验（claim_id 正则、
        related_task 正则、code_refs/test_refs 路径安全检查）
    处理逻辑：
        1. 每个 Claim 的 claim_id、related_task 写入 claims 表
        2. 每个 Claim 的 code_refs 数组拆分为多条 claim_code_refs 关联记录
        3. 每个 Claim 的 test_refs 数组拆分为多条 claim_test_refs 关联记录
    输出：
        数据库中新增 claims + claim_code_refs + claim_test_refs 记录
    """
    for claim in claims:
        conn.execute(
            "INSERT OR REPLACE INTO claims (claim_id, related_task) VALUES (?, ?)",
            (claim["claim_id"], claim["related_task"]),
        )
        for ref in _coerce_strlist(claim.get("code_refs", [])):
            if not ref:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO claim_code_refs (claim_id, code_path) VALUES (?, ?)",
                (claim["claim_id"], ref),
            )
        for ref in _coerce_strlist(claim.get("test_refs", [])):
            if not ref:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO claim_test_refs (claim_id, test_nodeid) VALUES (?, ?)",
                (claim["claim_id"], ref),
            )
    conn.commit()


def load_staged_files(conn: sqlite3.Connection, files: set) -> list:
    """将 Git 暂存区文件列表写入 staged_files 表。

    输入：
        conn:  数据库连接（由 pipeline.py 通过 init_in_memory_db() 创建）
        files: 文件路径集合（由 pipeline.py 从 common.py 的
               _get_staged_files() 获取）
    前置条件：
        无（文件路径来自 git 命令输出，格式已保证）
    处理逻辑：
        1. 遍历文件集合，每条路径写入 staged_files 表
    输出：
        数据库中新增 staged_files 记录；返回实际插入的文件路径列表
    """
    inserted: list = []
    for f in files:
        conn.execute(
            "INSERT OR REPLACE INTO staged_files (file_path) VALUES (?)",
            (f,),
        )
        inserted.append(f)
    conn.commit()
    return inserted


def load_initial_cache(conn: sqlite3.Connection, cache_dir: str) -> None:
    """从历史缓存文件加载测试和覆盖率数据。

    输入：
        conn:      数据库连接（由 pipeline.py 通过 init_in_memory_db() 创建）
        cache_dir: 缓存目录路径（由 pipeline.py 传入，通常为 output/evidences/）
    前置条件：
        缓存目录下可能存在 test_results.json 和 coverage_reports.json
        （首次运行时不存在，函数会跳过）
    处理逻辑：
        1. 读取 test_results.json，每条记录写入 test_results 表，
           标记 carried_over=1（表示历史缓存，非本次运行结果）
        2. 读取 coverage_reports.json，每条记录写入 coverage_reports 表，
           标记 carried_over=1
        3. 覆盖率记录：如果 source_path 对应的源文件在磁盘上已不存在，
           跳过该记录（防止幽灵覆盖率数据残留）
    输出：
        数据库中新增带 carried_over=1 标记的历史缓存记录
    """
    cache_path = Path(cache_dir)

    # 加载测试结果缓存
    test_file = cache_path / "test_results.json"
    if test_file.is_file():
        with open(str(test_file), "r") as fh:
            records = json.load(fh)
        for rec in records:
            nodeid = rec.get("nodeid", "")
            outcome = rec.get("outcome", "failed")
            exit_code = rec.get("exit_code", -1)
            command = rec.get("command")
            conn.execute(
                "INSERT OR REPLACE INTO test_results "
                "(nodeid, outcome, exit_code, command, carried_over) "
                "VALUES (?, ?, ?, ?, 1)",
                (nodeid, outcome, exit_code, command),
            )
        conn.commit()

    # 加载覆盖率缓存（跳过源文件已删除的记录）
    cov_file = cache_path / "coverage_reports.json"
    if cov_file.is_file():
        with open(str(cov_file), "r") as fh:
            records = json.load(fh)
        for rec in records:
            source_path = rec.get("source_path", "")
            # 跳过源文件已不存在的缓存记录（防止幽灵覆盖率数据残留）
            if source_path and not (cache_path.parent / source_path).is_file():
                continue
            percent_covered = rec.get("percent_covered", 0.0)
            num_statements = rec.get("num_statements")
            status = rec.get("status", "violated")
            conn.execute(
                "INSERT OR REPLACE INTO coverage_reports "
                "(source_path, percent_covered, num_statements, status, carried_over) "
                "VALUES (?, ?, ?, ?, 1)",
                (source_path, percent_covered, num_statements, status),
            )
        conn.commit()


def upsert_test_result(
    conn: sqlite3.Connection,
    nodeid: str,
    outcome: str,
    exit_code: int,
    command: str,
    carried_over: bool,
) -> None:
    """插入或替换单条测试结果（UPSERT）。

    输入：
        conn:        数据库连接（由 pipeline.py 通过 init_in_memory_db() 创建）
        nodeid:      测试用例唯一标识（由 tool_evidence_adapter 输出，
                     格式如 tests/test_x.py::test_y）
        outcome:     测试结果（passed/failed/skipped）
        exit_code:   进程退出码
        command:     执行的 pytest 命令
        carried_over: True=历史缓存，False=本次运行新结果
    前置条件：
        参数由 tool_evidence_adapter 直接传入，格式已保证
    处理逻辑：
        1. INSERT OR REPLACE：同 nodeid 的记录被覆盖，carried_over 重置
    输出：
        数据库中 test_results 表的一条记录被插入或更新
    """
    conn.execute(
        "INSERT OR REPLACE INTO test_results "
        "(nodeid, outcome, exit_code, command, carried_over) "
        "VALUES (?, ?, ?, ?, ?)",
        (nodeid, outcome, exit_code, command, int(carried_over)),
    )
    conn.commit()


def upsert_coverage_report(
    conn: sqlite3.Connection,
    source_path: str,
    percent_covered: float,
    num_statements: int,
    status: str,
    carried_over: bool,
) -> None:
    """插入或替换单条覆盖率报告（UPSERT）。

    输入：
        conn:            数据库连接（由 pipeline.py 通过 init_in_memory_db() 创建）
        source_path:     源文件路径（由 tool_evidence_adapter 输出）
        percent_covered: 覆盖率百分比（0.0-100.0）
        num_statements:  可执行语句总数
        status:          合规状态（compliant/violated）
        carried_over:    True=历史缓存，False=本次运行新结果
    前置条件：
        参数由 tool_evidence_adapter 直接传入，格式已保证
    处理逻辑：
        1. INSERT OR REPLACE：同 source_path 的记录被覆盖
    输出：
        数据库中 coverage_reports 表的一条记录被插入或更新
    """
    conn.execute(
        "INSERT OR REPLACE INTO coverage_reports "
        "(source_path, percent_covered, num_statements, status, carried_over) "
        "VALUES (?, ?, ?, ?, ?)",
        (source_path, percent_covered, num_statements, status, int(carried_over)),
    )
    conn.commit()


# ── 3. 缓存清理 ────────────────────────────────────────────────────────────

def purge_stale_cache(conn: sqlite3.Connection, target_files: list) -> None:
    """清除目标文件对应的陈旧缓存记录。

    输入：
        conn:         数据库连接（由 pipeline.py 通过 init_in_memory_db() 创建）
        target_files: 本次运行涉及的文件路径列表（由 pipeline.py 从
                      tool_evidence_adapter 的输出提取）
    前置条件：
        load_initial_cache() 已执行（数据库中已有 carried_over=1 的历史记录）
    处理逻辑：
        1. 对每个文件，删除 test_results 中 nodeid 匹配该文件的
           carried_over 记录（防止幽灵测试残留）
        2. 对每个文件，删除 coverage_reports 中 source_path 匹配该文件的
           carried_over 记录（防止幽灵覆盖率残留）

    问题背景：
      UPSERT 只能覆盖已存在的 key。如果用户删除或重命名了测试用例
      （如 test_old → test_new），旧记录 test_old 不会被新结果覆盖，
      将永久残留在数据库中。本函数在 UPSERT 前清理这些陈旧记录。

    输出：
        数据库中陈旧的 carried_over 记录被删除
    """
    for f in target_files:
        conn.execute(
            "DELETE FROM test_results "
            "WHERE (nodeid LIKE ? OR nodeid = ?) AND carried_over = 1",
            (f"{f}::%", f),
        )
        conn.execute(
            "DELETE FROM coverage_reports "
            "WHERE source_path = ? AND carried_over = 1",
            (f,),
        )
    conn.commit()


# ── 4. 关系校验（第二层）──────────────────────────────────────────────────
# 所有 check_* 函数通过 SQL LEFT JOIN 实现软外键校验，
# 一次性返回所有违规记录，不会因单条错误中断事务。

def check_ac_coverage(conn: sqlite3.Connection) -> list:
    """检查 MUST 优先级任务的验收标准（AC）覆盖情况。

    输入：
        conn: 数据库连接（已通过 load_tasks/load_claims/load_initial_cache
              灌入数据）
    前置条件：
        tasks、task_acs、claims、claim_test_refs、test_results 表已有数据
    处理逻辑：
        追踪链路：Task → AC → Claim → Test → 测试结果
        对每个 MUST 优先级的 AC，检查覆盖状态：
        1. 关联的 Claim 是否存在（no_claim_for_task）
        2. Claim 中是否声明了测试（no_tests_declared）
        3. 测试是否实际运行（test_not_run）
        4. 测试是否通过（test_failed）
    输出：
        返回未覆盖的 MUST AC 列表，每项包含 task_id、ac_id、coverage_status
    """
    rows = conn.execute("""
        SELECT ta.task_id, ta.ac_id,
          CASE
            WHEN c.claim_id IS NULL THEN 'no_claim_for_task'
            WHEN ctr.test_nodeid IS NULL THEN 'no_tests_declared'
            WHEN tr.nodeid IS NULL THEN 'test_not_run'
            WHEN SUM(tr.outcome = 'passed') = 0 THEN 'test_failed'
            ELSE 'covered'
          END as coverage_status
        FROM task_acs ta
        JOIN tasks t ON ta.task_id = t.task_id
        LEFT JOIN claims c ON t.task_id = c.related_task
        LEFT JOIN claim_test_refs ctr ON c.claim_id = ctr.claim_id
        LEFT JOIN test_results tr ON ctr.test_nodeid = tr.nodeid
        WHERE t.priority = 'must'
        GROUP BY ta.task_id, ta.ac_id
        HAVING coverage_status != 'covered'
    """).fetchall()
    return [
        {"task_id": r[0], "ac_id": r[1], "coverage_status": r[2]}
        for r in rows
    ]


def check_coverage_violations(conn: sqlite3.Connection) -> list:
    """检查覆盖率违规：返回所有 status='violated' 的覆盖率记录。

    输入：
        conn: 数据库连接
    前置条件：
        coverage_reports 表已有数据
    处理逻辑：
        1. 查询 coverage_reports 表中 status='violated' 的记录
    输出：
        返回违规记录列表，每项包含 source_path、percent_covered
    """
    rows = conn.execute(
        "SELECT source_path, percent_covered FROM coverage_reports "
        "WHERE status = 'violated'"
    ).fetchall()
    return [{"source_path": r[0], "percent_covered": r[1]} for r in rows]


def check_ghost_code(conn: sqlite3.Connection) -> list:
    """检查幽灵代码：返回暂存区中未被任何 Claim 关联的文件。

    输入：
        conn: 数据库连接
    前置条件：
        staged_files、claim_code_refs、claims、tasks 表已有数据
    处理逻辑：
        1. staged_files LEFT JOIN claim_code_refs，取 ccr.code_path IS NULL 的行
        幽灵代码 = 已 staged 的业务代码文件，但没有通过 Claim 的 code_refs
        关联到任何合法任务。这违反了"所有代码变更必须有 Claim 声明"的原则。
    输出：
        返回幽灵代码文件路径列表
    """
    rows = conn.execute("""
        SELECT sf.file_path FROM staged_files sf
        LEFT JOIN claim_code_refs ccr ON sf.file_path = ccr.code_path
        LEFT JOIN claims c ON ccr.claim_id = c.claim_id
        LEFT JOIN tasks t ON c.related_task = t.task_id
        WHERE ccr.code_path IS NULL
    """).fetchall()
    return [r[0] for r in rows]


def check_dangling_claims(conn: sqlite3.Connection) -> list:
    """检查悬空声明：返回指向不存在 Task 的 Claim。

    输入：
        conn: 数据库连接
    前置条件：
        claims、tasks 表已有数据
    处理逻辑：
        1. claims LEFT JOIN tasks，取 t.task_id IS NULL 的行
        悬空声明 = Claim 的 related_task 在 tasks 表中不存在，
        说明 Claim 关联了一个已删除或未创建的任务。
    输出：
        返回悬空声明列表，每项包含 claim_id、related_task
    """
    rows = conn.execute("""
        SELECT c.claim_id, c.related_task FROM claims c
        LEFT JOIN tasks t ON c.related_task = t.task_id
        WHERE t.task_id IS NULL
    """).fetchall()
    return [{"claim_id": r[0], "related_task": r[1]} for r in rows]


def check_test_dead_links(conn: sqlite3.Connection) -> list:
    """检查测试死链：返回 Claim 引用但不存在或未通过的测试。

    输入：
        conn: 数据库连接
    前置条件：
        claim_test_refs、test_results 表已有数据
    处理逻辑：
        1. claim_test_refs LEFT JOIN test_results，取以下两种情况：
           - tr.nodeid IS NULL（测试未运行）
           - tr.outcome != 'passed'（测试运行但未通过）
        测试死链 = Claim 的 test_refs 指向的测试用例无法验证 Claim 的有效性。
    输出：
        返回死链列表，每项包含 claim_id、test_nodeid
    """
    rows = conn.execute("""
        SELECT ctr.claim_id, ctr.test_nodeid FROM claim_test_refs ctr
        LEFT JOIN test_results tr ON ctr.test_nodeid = tr.nodeid
        WHERE tr.nodeid IS NULL OR tr.outcome != 'passed'
    """).fetchall()
    return [{"claim_id": r[0], "test_nodeid": r[1]} for r in rows]


def check_active_task_coverage(conn: sqlite3.Connection) -> list:
    """检查活跃任务的覆盖率：返回 in_progress 任务中未达标或缺失的代码文件。

    输入：
        conn: 数据库连接
    前置条件：
        claim_code_refs、claims、tasks、coverage_reports 表已有数据
    处理逻辑：
        1. 筛选 status='in_progress' 的 Task 关联的 code_path
        2. LEFT JOIN coverage_reports，取缺失（IS NULL）或 violated 的记录
        活跃任务 = 正在开发中的任务，其代码文件必须达标才能提交。
    输出：
        返回未达标记录列表，每项包含 code_path、percent_covered、status
    """
    rows = conn.execute("""
        SELECT ccr.code_path, cr.percent_covered, cr.status
        FROM claim_code_refs ccr
        JOIN claims c ON ccr.claim_id = c.claim_id
        JOIN tasks t ON c.related_task = t.task_id
        LEFT JOIN coverage_reports cr ON ccr.code_path = cr.source_path
        WHERE t.status = 'in_progress'
          AND (cr.source_path IS NULL OR cr.status = 'violated')
    """).fetchall()
    return [
        {"code_path": r[0], "percent_covered": r[1], "status": r[2]}
        for r in rows
    ]


# ── 5. 数据导出 ────────────────────────────────────────────────────────────

def _export_test_results(conn: sqlite3.Connection) -> list:
    """[内部函数] 将 test_results 表全部记录导出为字典列表。

    仅被 persist_evidences() 内部调用，不对外暴露。

    输入：
        conn: 数据库连接
    前置条件：
        test_results 表已有数据
    处理逻辑：
        1. SELECT * 查询全部记录
        2. 通过 PRAGMA table_info 获取列名，将行数据转为字典
    输出：
        返回测试结果字典列表，每个字典包含 nodeid、outcome、exit_code 等字段
    """
    rows = conn.execute("SELECT * FROM test_results").fetchall()
    columns = [d[1] for d in conn.execute("PRAGMA table_info(test_results)").fetchall()]
    return [dict(zip(columns, row)) for row in rows]


def _export_coverage_reports(conn: sqlite3.Connection) -> list:
    """[内部函数] 将 coverage_reports 表全部记录导出为字典列表。

    仅被 persist_evidences() 内部调用，不对外暴露。

    输入：
        conn: 数据库连接
    前置条件：
        coverage_reports 表已有数据
    处理逻辑：
        1. SELECT * 查询全部记录
        2. 通过 PRAGMA table_info 获取列名，将行数据转为字典
    输出：
        返回覆盖率报告字典列表
    """
    rows = conn.execute("SELECT * FROM coverage_reports").fetchall()
    columns = [d[1] for d in conn.execute("PRAGMA table_info(coverage_reports)").fetchall()]
    return [dict(zip(columns, row)) for row in rows]


def persist_evidences(conn: sqlite3.Connection, output_dir: str) -> None:
    """将数据库中的测试和覆盖率数据导出为 JSON 文件。

    输入：
        conn:       数据库连接（由 pipeline.py 通过 init_in_memory_db() 创建）
        output_dir: 输出目录路径（由 pipeline.py 传入，通常为 output/evidences/）
    前置条件：
        test_results 和 coverage_reports 表已有数据（由 EvidenceBuilder 写入）
    处理逻辑：
        1. 调用 export_test_results() 获取测试结果列表
        2. 写入 output/evidences/test_results.json
        3. 调用 export_coverage_reports() 获取覆盖率报告列表
        4. 写入 output/evidences/coverage_reports.json
    输出：
        磁盘上新增/更新 test_results.json 和 coverage_reports.json 文件
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    test_data = _export_test_results(conn)
    with open(str(out / "test_results.json"), "w") as fh:
        json.dump(test_data, fh, indent=2, ensure_ascii=False)

    cov_data = _export_coverage_reports(conn)
    with open(str(out / "coverage_reports.json"), "w") as fh:
        json.dump(cov_data, fh, indent=2, ensure_ascii=False)
