"""
VT 内存数据库数据加载模块
"""

import json
import sqlite3
from pathlib import Path

from vibe_tracing.infra.config.enums import CoverageStatus


def _coerce_strlist(val) -> list:
    """将任意值规范化为字符串列表。"""
    if isinstance(val, list):
        return [str(x) for x in val]
    if val is None:
        return []
    return [str(val)]


def load_tasks(conn: sqlite3.Connection, tasks: list) -> None:
    """批量加载任务到数据库。"""
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
        for req_id in _coerce_strlist(task.get("related_requirements", [])):
            conn.execute(
                "INSERT OR REPLACE INTO task_requirements (task_id, req_id) VALUES (?, ?)",
                (task["task_id"], req_id),
            )
        for mod_id in _coerce_strlist(task.get("related_modules", [])):
            conn.execute(
                "INSERT OR REPLACE INTO task_modules (task_id, module_id) VALUES (?, ?)",
                (task["task_id"], mod_id),
            )
        for constraint_id in _coerce_strlist(task.get("related_architecture_constraints", [])):
            conn.execute(
                "INSERT OR REPLACE INTO task_constraints (task_id, constraint_id) VALUES (?, ?)",
                (task["task_id"], constraint_id),
            )
    conn.commit()


def load_claims(conn: sqlite3.Connection, claims: list) -> None:
    """批量加载开发声明到数据库。"""
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
    """将 Git 暂存区文件列表写入 staged_files 表。"""
    inserted: list = []
    for f in files:
        conn.execute(
            "INSERT OR REPLACE INTO staged_files (file_path) VALUES (?)",
            (f,),
        )
        inserted.append(f)
    conn.commit()
    return inserted


def load_architecture_constraints(conn: sqlite3.Connection, constraints: dict) -> None:
    """从 architecture_constraints.json 加载模块和约束到数据库。"""
    if not constraints:
        return

    # 加载 module_boundaries
    for mod in constraints.get("module_boundaries", []):
        module_id = mod.get("module_id")
        if module_id:
            conn.execute(
                "INSERT OR REPLACE INTO arch_modules (module_id) VALUES (?)",
                (module_id,),
            )

    # 加载各规则列表中的 constraint_id
    constraint_keys = [
        "architecture_principles",
        "dependency_rules",
        "data_flow_rules",
        "storage_rules",
        "error_handling_rules",
        "logging_rules",
        "security_rules",
        "technology_constraints",
        "forbidden_patterns",
        "quality_gates",
    ]
    id_fields = [
        "principle_id", "constraint_id", "rule_id", "gate_id",
        "pattern_id", "tech_id", "dep_id",
    ]
    for key in constraint_keys:
        for item in constraints.get(key, []):
            for id_field in id_fields:
                constraint_id = item.get(id_field)
                if constraint_id:
                    conn.execute(
                        "INSERT OR REPLACE INTO arch_constraints (constraint_id) VALUES (?)",
                        (constraint_id,),
                    )
                    break

    conn.commit()


def load_initial_cache(conn: sqlite3.Connection, cache_dir: Path, project_root: Path) -> None:
    """从历史缓存文件加载测试和覆盖率数据。"""
    cache_path = Path(cache_dir)

    # 加载测试结果缓存
    test_file = cache_path / "test_results.json"
    if test_file.is_file():
        try:
            with open(str(test_file), "r") as fh:
                records = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"Corrupted or unreadable cache file: {test_file}") from exc
        for rec in records:
            nodeid = rec.get("nodeid", "")
            outcome = rec.get("outcome", CoverageStatus.VIOLATED.value)
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
        try:
            with open(str(cov_file), "r") as fh:
                records = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"Corrupted or unreadable cache file: {cov_file}") from exc
        for rec in records:
            source_path = rec.get("source_path", "")
            # 跳过源文件已不存在的缓存记录（防止幽灵覆盖率数据残留）
            if source_path and not (project_root / source_path).is_file():
                continue
            percent_covered = rec.get("percent_covered", 0.0)
            num_statements = rec.get("num_statements")
            status = rec.get("status", CoverageStatus.VIOLATED.value)
            conn.execute(
                "INSERT OR REPLACE INTO coverage_reports "
                "(source_path, percent_covered, num_statements, status, carried_over) "
                "VALUES (?, ?, ?, ?, 1)",
                (source_path, percent_covered, num_statements, status),
            )
        conn.commit()


def load_prd(conn: sqlite3.Connection, prd) -> None:
    """从 PrdParseResult 对象、字典或列表中提取 requirements 和 ACs 并写入数据库。"""
    if prd is None:
        return

    if isinstance(prd, list):
        requirements = prd
    elif isinstance(prd, dict):
        requirements = prd.get("requirements", [])
    else:
        requirements = getattr(prd, "requirements", [])

    for req in requirements:
        req_is_dict = isinstance(req, dict)
        req_id = req.get("req_id") if req_is_dict else getattr(req, "req_id", None)
        title = req.get("title") if req_is_dict else getattr(req, "title", None)
        priority = req.get("priority") if req_is_dict else getattr(req, "priority", None)
        category = req.get("category") if req_is_dict else getattr(req, "category", None)

        if not req_id:
            continue

        conn.execute(
            "INSERT OR REPLACE INTO requirements (req_id, title, priority, category) "
            "VALUES (?, ?, ?, ?)",
            (req_id, title, priority, category)
        )

        ac_list = req.get("acceptance_criteria", []) if req_is_dict else getattr(req, "acceptance_criteria", [])
        for ac in ac_list:
            ac_is_dict = isinstance(ac, dict)
            ac_id = ac.get("ac_id") if ac_is_dict else getattr(ac, "ac_id", None)
            ac_title = ac.get("title") if ac_is_dict else getattr(ac, "title", None)
            is_testing = ac.get("is_testing_required") if ac_is_dict else getattr(ac, "is_testing_required", False)

            # sqlite3: 1 for True, 0 for False
            is_testing_int = 1 if is_testing else 0

            if not ac_id:
                continue

            conn.execute(
                "INSERT OR REPLACE INTO acceptance_criteria (ac_id, req_id, title, is_testing_required) "
                "VALUES (?, ?, ?, ?)",
                (ac_id, req_id, ac_title, is_testing_int)
            )
    conn.commit()
