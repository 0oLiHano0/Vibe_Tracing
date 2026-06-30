"""
Vibe Tracing 的工具执行引擎，负责按照 validation_tools 和 language_tool_matrix
配置，执行白名单中的验证工具并将输出标准化为证据候选结构。

职责：
- 解析 language_tool_matrix 配置，构建白名单工具配置表 _tool_configs
- 替换命令模板中的路径占位符，构造可安全执行的命令
- 通过子进程执行工具并捕获 stdout/stderr/exit_code
- 调用 parsers.py 解析函数将工具输出转为 ToolEvidenceCandidate
- 从 coverage baseline JSON 文件提取每文件覆盖数据
- 收集工具执行统计数据，返回 ToolExecutionResult

依赖：
- infra/tools/parsers.py：工具输出解析函数
- infra/tools/resolver.py：工具可用性检测和 python3 -m 命令回退
- domain/evidence/candidate.py：ToolEvidenceCandidate 和 ToolExecutionResult 数据模型

被依赖：
- cli/analyze/pipeline.py：分析流水线通过 execute_from_claims() 调用
- infra/tools/__init__.py：包导出 ToolExecutionEngine

MOD-VT-012: Tool Execution Engine - executes validation tools from whitelist only.
"""

import ast
import json
import re
import shlex
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from vibe_tracing.infra.config.enums import CoverageStatus, ErrorCode
from vibe_tracing.infra.config.hint_loader import load_hints, resolve_hint
from vibe_tracing.infra.logging.logger import OperationalLogger
from vibe_tracing.infra.tools.resolver import ToolResolver
from vibe_tracing.domain.evidence.candidate import ToolEvidenceCandidate, ToolExecutionResult
from vibe_tracing.infra.tools.parsers import (
    parse_pytest_output,
    parse_ruff_output,
    parse_mypy_output,
    parse_bandit_output,
    parse_coverage_json_output,
)


def _safe_format(template: str, **kwargs: Any) -> str:
    """仅替换已知的占位符，保留其他 {token} 字面量不变。"""
    result = template
    for key, value in kwargs.items():
        result = result.replace("{" + key + "}", str(value))
    return result


_tool_hints = load_hints("tool")


# 命令模板中允许替换的占位符集合。
# SEC-VT-001 / DEP-VT-008：仅允许替换路径占位符。
_ALLOWED_PLACEHOLDERS = {"{test_path}", "{source_path}", "{output_path}"}


class ToolExecutionEngine:
    """
    根据 language_tool_matrix 配置执行白名单中的验证工具。

    仅允许白名单中的工具，命令模板通过占位符替换填充，拒绝任意命令。

    职责：
    - 构建白名单工具配置：初始化时将 validation_tools 转为 _tool_configs 字典
    - 执行单个工具：execute_tool() 处理命令构建→执行→解析→候选生成完整流程
    - 批量执行：execute_from_claims() 从 claims 收集路径并逐文件执行所有配置工具
    - 覆盖率基线：从 coverage baseline JSON 文件读取每文件覆盖数据
    - 解析测试 docstring：使用 AST 提取测试函数文档中的覆盖声明
    """

    DEFAULT_TIMEOUT = 120  # seconds

    def __init__(
        self,
        language_tool_matrix: Dict[str, Dict[str, Any]],
        language: str,
        validation_tools: List[str],
        project_root: Path,
        timeout: int = DEFAULT_TIMEOUT,
        coverage_baseline_path: Optional[str] = None,
    ) -> None:
        """
        Args:
            language_tool_matrix: 来自 architecture_constraints.json 的完整工具矩阵。
            language: 当前激活的语言键（如 "python"）。
            validation_tools: 需要运行的工具类别列表（如 ["test", "lint"]）。
            project_root: 项目工作区根目录的绝对路径。
            timeout: 子进程超时时间（秒）。
            coverage_baseline_path: coverage baseline JSON 文件的可选路径。
        """
        self.language_tool_matrix = language_tool_matrix
        self.language = language
        self.validation_tools = list(validation_tools)
        self.project_root = project_root
        self.timeout = timeout
        self.coverage_baseline_path = coverage_baseline_path

        # 构建白名单工具配置映射：{category -> tool_config_dict}
        lang_matrix = self.language_tool_matrix.get(self.language, {})
        self._tool_configs: Dict[str, Dict[str, Any]] = {}
        for category in self.validation_tools:
            if category in lang_matrix:
                self._tool_configs[category] = lang_matrix[category]

    # ------------------------------------------------------------------
    # 命令模板替换
    # ------------------------------------------------------------------

    def _build_command(
        self,
        template: str,
        test_path: str = "",
        source_path: str = "",
        output_path: str = "",
    ) -> str:
        """替换命令模板中的占位符，构造最终执行命令。

        仅允许替换 {test_path}、{source_path}、{output_path} 三个占位符。
        路径值使用 shlex.quote() 引用以防止 shell 注入。
        如果模板中仍有未识别的占位符（如 {unknown}），直接抛 ValueError 阻断执行。

        SEC-VT-001 / DEP-VT-008：仅允许替换路径占位符。
        """
        cmd = template
        cmd = cmd.replace("{test_path}", shlex.quote(test_path) if test_path else "")
        cmd = cmd.replace("{source_path}", shlex.quote(source_path) if source_path else "")
        cmd = cmd.replace("{output_path}", shlex.quote(output_path) if output_path else "")

        remaining = re.findall(r"\{[a-z_]+\}", cmd)
        if remaining:
            hint = resolve_hint(_tool_hints.get("unresolved_placeholders", {}), "level1")
            msg = _safe_format(hint,
                remaining=remaining, allowed_placeholders=', '.join(sorted(_ALLOWED_PLACEHOLDERS)),
            ) if hint else f"Unresolved placeholders in command: {remaining}. Only {', '.join(sorted(_ALLOWED_PLACEHOLDERS))} are permitted."
            raise ValueError(msg)
        return cmd

    # ------------------------------------------------------------------
    # 子进程执行
    # ------------------------------------------------------------------

    def _run_subprocess(
        self, command: str
    ) -> Tuple[int, str, str, Optional[str]]:
        """
        通过子进程执行工具命令字符串。

        使用 shell=True，但仅接收经过 _build_command 模板验证的命令，
        不会接受任意命令。记录子进程耗时和输出预览，日志失败不阻断执行。

        异常映射：
          TimeoutExpired  → "timeout"   (error_type)
          FileNotFound    → "not_found" (error_type) — 通常由 resolver 处理
          PermissionError → "permission" (error_type)
          OSError         → "os_error"  (error_type) — 操作系统级错误兜底

        Returns:
            (exit_code, stdout, stderr, error_message_or_none)
        """
        try:
            cmd_name = command.split()[0] if command else ""
            _t = time.perf_counter()
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            duration_ms = int((time.perf_counter() - _t) * 1000)
            try:
                from vibe_tracing.infra.logging.logger import OperationalLogger
                vt_logger = OperationalLogger.get()
                vt_logger.info("subprocess_exec", "Tool subprocess completed",
                               command=cmd_name,
                               duration_ms=duration_ms,
                               exit_code=result.returncode,
                               stdout_size=len(result.stdout or ""),
                               stderr_size=len(result.stderr or ""))
                vt_logger.debug("subprocess_output", "Subprocess stdout/stderr",
                                command=cmd_name,
                                stdout_preview=(result.stdout or "")[:500],
                                stderr_preview=(result.stderr or "")[:500])
            except Exception:
                pass  # Never block on logging
            return result.returncode, result.stdout, result.stderr, None
        except subprocess.TimeoutExpired:
            hint = resolve_hint(_tool_hints.get("execution_timeout", {}), "level1")
            source_path = command.split()[0] if command else ""
            msg = _safe_format(hint, source_path=source_path, timeout_seconds=self.timeout) if hint else f"Tool execution timed out after {self.timeout}s"
            return -1, "", msg, "timeout"
        except FileNotFoundError:
            hint = resolve_hint(_tool_hints.get("binary_not_found", {}), "level1")
            cmd_token = command.split()[0] if command else ""
            msg = _safe_format(hint, command=cmd_token, tool_name=cmd_token) if hint else f"Tool binary not found: {cmd_token}"
            return -1, "", msg, "not_found"
        except PermissionError:
            hint = resolve_hint(_tool_hints.get("permission_denied", {}), "level1")
            msg = _safe_format(hint, command=command) if hint else f"Permission denied executing: {command}"
            return -1, "", msg, "permission"
        except OSError as exc:
            hint = resolve_hint(_tool_hints.get("subprocess_os_error", {}), "level1")
            msg = _safe_format(hint, exc=exc) if hint else f"OS error executing tool: {exc}"
            return -1, "", msg, "os_error"

    # ------------------------------------------------------------------
    # 公开执行 API
    # ------------------------------------------------------------------

    # 表示"工具无法处理该文件"的退出码，而非真正的失败。
    # 当返回这些退出码时，不生成任何证据。
    PYTEST_SKIP_EXIT_CODES = {2, 5}  # 2 = 使用错误, 5 = 未收集到测试
    MYPY_SKIP_EXIT_CODES = {2}  # 2 = 使用错误

    def _blocked_candidate(
        self, path: str, tool_category: str, *,
        command: str = "", exit_code: int = -1,
        stderr: str = "", details: dict = None,
    ) -> ToolEvidenceCandidate:
        """创建已预置 tool_category 的 BLOCKED 候选。"""
        c = ToolEvidenceCandidate(
            source_type="tool", source_path=path, covers=[],
            status=CoverageStatus.BLOCKED.value,
            error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
            command=command, exit_code=exit_code,
            stderr=stderr, details=details or {},
        )
        c.tool_category = tool_category
        return c

    def _parse_output(
        self, output_format: str,
        stdout: str, stderr: str, exit_code: int,
        command: str, path: str,
    ) -> List[ToolEvidenceCandidate]:
        """根据 output_format 将输出分派给对应的解析器。"""
        parsers = {
            "pytest_json": lambda: parse_pytest_output(
                stdout, stderr, exit_code, command, path,
                self.project_root, self.PYTEST_SKIP_EXIT_CODES,
                self._get_test_docstring, self._extract_covers_from_docstring,
            ),
            "ruff_json": lambda: parse_ruff_output(stdout, stderr, exit_code, command, path),
            "mypy_json": lambda: parse_mypy_output(stdout, stderr, exit_code, command, path, self.MYPY_SKIP_EXIT_CODES),
            "bandit_json": lambda: parse_bandit_output(stdout, stderr, exit_code, command, path, self.project_root),
            "coverage_json": lambda: parse_coverage_json_output(stdout, stderr, exit_code, command, path),
        }
        parser = parsers.get(output_format)
        if parser:
            return parser()
        hint = resolve_hint(_tool_hints.get("unsupported_output_format", {}), "level1")
        msg = _safe_format(hint, output_format=output_format) if hint else f"Unsupported output format: {output_format}"
        return [self._blocked_candidate(path, "", stderr=msg)]

    def execute_tool(
        self,
        tool_category: str,
        path: str,
    ) -> List[ToolEvidenceCandidate]:
        """对给定路径执行单个工具并返回证据候选列表。

        流程：命令模板 → 占位符替换 → 命令解析（python3 -m 回退）→
              子进程执行 → 输出解析 → 标记 tool_category → 返回候选列表

        前置条件（由 execute_from_claims 保证）：
            - tool_category 在白名单 self._tool_configs 中
            - path 是 project_root 内的相对路径

        工具执行错误（超时、未找到、权限、OS 错误）以 blocked candidate 返回，
        不会向上抛异常。
        """
        tool_config = self._tool_configs[tool_category]
        template = tool_config.get("default_command", "")

        # 仅在模板需要时生成 output_path
        effective_output = ""
        if "{output_path}" in template:
            tmp_dir = self.project_root / ".vibetracing" / "tmp"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            effective_output = str(tmp_dir / f"vt_{tool_category}_{uuid.uuid4().hex}.json")

        # 从模板构建命令
        try:
            command = self._build_command(
                template, test_path=path, source_path=path, output_path=effective_output,
            )
        except ValueError as exc:
            return [self._blocked_candidate(path, tool_category, stderr=str(exc))]

        # python3 -m 回退：如果二进制文件不在 PATH 中，尝试 python3 -m <tool>
        command = ToolResolver.resolve_command(command)

        # 执行工具
        exit_code, stdout, stderr, exec_error = self._run_subprocess(command)

        if exec_error:
            details = {"error_type": exec_error}
            if exec_error == "timeout":
                details["timeout_seconds"] = self.timeout
            return [self._blocked_candidate(
                path, tool_category, command=command,
                exit_code=-1, stderr=stderr, details=details,
            )]

        # 解析输出 + 标记 category
        output_format = tool_config.get("output_format", "")
        candidates = self._parse_output(output_format, stdout, stderr, exit_code, command, path)
        for c in candidates:
            c.tool_category = tool_category
        return candidates

    def _measure_source_coverage(
        self,
        baseline_path: Optional[str] = None,
        pass_threshold: float = 80.0,
    ) -> List[ToolEvidenceCandidate]:
        """从预构建的 baseline 文件测量逐文件源码覆盖率。

        读取 coverage baseline JSON 文件中的每文件覆盖数据，
        为每个源文件生成一个 ToolEvidenceCandidate，标记为 COMPLIANT 或 VIOLATED。

        JSON 文件格式约定：{"files": {"<file_path>": {"percent_covered": 85.5, "num_statements": 42}}}

        Args:
            baseline_path: 可选参数，指向 coverage baseline JSON 文件路径。
                为 None 时返回空列表。
            pass_threshold: 覆盖率阈值，高于此值为 COMPLIANT，低于为 VIOLATED（默认 80%）。

        Returns:
            每源文件对应一个 ToolEvidenceCandidate。无 baseline 数据时返回空列表。
        """
        # 未配置 baseline 路径，无数据可用
        if baseline_path is None:
            return []

        baseline_file = Path(baseline_path)

        if not baseline_file.is_file():
            return []

        try:
            with baseline_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            OperationalLogger.get().debug("tool_output_parse_failed", "Could not parse coverage baseline file", path=str(baseline_path))
            return []

        files = data.get("files")
        if not isinstance(files, dict):
            return []

        return self._build_coverage_candidates(files, pass_threshold)


    def _build_coverage_candidates(
        self, files: dict, pass_threshold: float,
    ) -> list:
        """从 coverage 文件字典构建 ToolEvidenceCandidate 列表。

        遍历 files 字典中的每文件覆盖数据，校验每个条目，
        根据阈值计算 COMPLIANT/VIOLATED 状态，每个有效源文件返回一个候选。

        Args:
            files: {source_path: {"percent_covered": float, "num_statements": int, ...}} 格式的文件数据。
            pass_threshold: 合规覆盖率阈值，高于此值为 COMPLIANT。

        Returns:
            tool_category="coverage" 的 ToolEvidenceCandidate 列表。
        """
        candidates = []
        for source_path, file_data in files.items():
            if not isinstance(file_data, dict):
                continue

            percent = file_data.get("percent_covered")
            num_stmts = file_data.get("num_statements", 0)
            if percent is None:
                continue

            percent_f = float(percent)
            status = (
                CoverageStatus.COMPLIANT.value
                if percent_f >= pass_threshold
                else CoverageStatus.VIOLATED.value
            )

            candidates.append(
                ToolEvidenceCandidate(
                    source_type="tool",
                    source_path=source_path,
                    covers=[],
                    status=status,
                    tool_category="coverage",
                    details={
                        "percent_covered": percent_f,
                        "num_statements": int(num_stmts),
                        "measurement": "baseline",
                    },
                )
            )

        return candidates

    def execute_from_claims(
        self,
        claims_list: List[Any],
        project_root: Path,
    ) -> ToolExecutionResult:
        """从 claims 执行白名单工具，这是工具执行的唯一个人口。

        这是 cli/analyze/pipeline.py 调用的唯一个人口方法。
        内部包含 5 个阶段：
          1. 预检查：验证 _tool_configs 不为空
          2. 路径收集：从 claims 的 test_refs 和 code_refs 收集文件路径
          3. 逐文件执行：按工具分类对每个路径调用 execute_tool()
          4. 覆盖率：追加从 coverage baseline 提取的 per-file 证据
          5. 统计：记录已执行数、阻塞数、跳过数
        全程使用 vt_logger 记录，无 print() 调用。

        Args:
            claims_list: 包含 test_refs 和 code_refs 的 Claim 对象列表。
            project_root: 项目根目录。

        Returns:
            包含 candidates 和元数据的 ToolExecutionResult。
        """
        vt_logger = OperationalLogger.get()

        # --- 1. 预检查：验证所需工具二进制文件是否可用 ---
        lang_config = self.language_tool_matrix.get(self.language, {})
        code_extensions = set(lang_config.get("extensions", [".py"]))
        if not code_extensions:
            vt_logger.warning("no_code_extensions", "No code extensions defined in language_tool_matrix")
            return ToolExecutionResult(candidates=[], skipped=True, skip_reason="no_extensions")

        required_binaries: set = set()
        for category in self.validation_tools:
            tool_cfg = self._tool_configs.get(category, {})
            tool_name = tool_cfg.get("tool")
            if tool_name:
                required_binaries.add(tool_name)

        missing = sorted(t for t in required_binaries if not ToolResolver.is_available(t))
        if missing:
            vt_logger.warning("tool_precheck_failed", "Tool dependency pre-check failed",
                              missing_tools=missing)
            return ToolExecutionResult(candidates=[], skipped=True,
                                      skip_reason="precheck_failed", missing_tools=missing)

        # --- 2. 从 claims 收集路径（测试 vs 源文件） ---
        test_paths: List[str] = []
        source_paths: List[str] = []
        seen_paths: set = set()

        for claim in claims_list:
            for ref in claim.test_refs:
                path_only = ref.split("#")[0]
                if (path_only and Path(path_only).suffix in code_extensions
                        and path_only not in seen_paths
                        and (project_root / path_only).exists()):
                    test_paths.append(path_only)
                    seen_paths.add(path_only)
            for ref in claim.code_refs:
                path_only = ref.split("#")[0]
                if (path_only and Path(path_only).suffix in code_extensions
                        and path_only not in seen_paths
                        and (project_root / path_only).exists()):
                    source_paths.append(path_only)
                    seen_paths.add(path_only)

        if not test_paths and not source_paths:
            vt_logger.warning("no_code_files", "No code files found in claims")
            return ToolExecutionResult(candidates=[], skipped=True, skip_reason="no_code_files")

        total_paths = len(test_paths) + len(source_paths)
        vt_logger.info("tool_execution_start", "Starting tool execution",
                       total_paths=total_paths,
                       test_paths=len(test_paths),
                       source_paths=len(source_paths))

        # --- 3. 按路径执行工具，根据 test/source 类型路由 ---
        all_candidates: List[ToolEvidenceCandidate] = []
        typed_paths = [(p, "test") for p in test_paths] + [(p, "source") for p in source_paths]

        for path, path_type in typed_paths:
            for category in self.validation_tools:
                if category == "coverage":
                    continue  # batch tool, handled below
                config = self._tool_configs.get(category)
                if config is None:
                    continue
                if path_type == "test" and category != "test":
                    continue
                if path_type == "source" and category == "test":
                    continue

                candidates = self.execute_tool(
                    tool_category=category,
                    path=path,
                )
                all_candidates.extend(candidates)

        # --- 4. 追加来自 baseline 的每文件覆盖率证据 ---
        all_candidates.extend(self._measure_source_coverage(
            baseline_path=self.coverage_baseline_path,
        ))

        # --- 5. 统计日志 ---
        executed_count = len(all_candidates)
        blocked_count = sum(1 for c in all_candidates if c.error_code is not None)
        skipped_count = sum(1 for c in all_candidates if c.status == "skipped")

        if skipped_count > 0:
            vt_logger.info("tool_files_skipped", "Some files skipped by tool engine",
                           skipped_count=skipped_count)

        for c in all_candidates:
            if c.error_code is not None:
                details = c.details or {}
                error_type = details.get("error_type", "unknown")
                vt_logger.warning("tool_execution_error", "Tool execution error",
                                  source_path=c.source_path,
                                  error_type=error_type,
                                  exit_code=c.exit_code)

        vt_logger.info("tool_execution_complete", "Tool execution completed",
                       executed_count=executed_count,
                       blocked_count=blocked_count,
                       skipped_count=skipped_count)

        return ToolExecutionResult(candidates=all_candidates)

    # ------------------------------------------------------------------
    # 测试 docstring / covers 提取
    # ------------------------------------------------------------------

    def _get_test_docstring(self, nodeid: str) -> Optional[str]:
        """使用 AST 从 Python 源文件中提取测试函数/方法的 docstring。"""
        try:
            parts = nodeid.split("::")
            file_rel_path = parts[0]
            file_path = self.project_root / file_rel_path
            if not file_path.is_file():
                return None

            with file_path.open("r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(file_path))

            current_node: ast.AST = tree
            target_names = parts[1:]

            for name in target_names:
                clean_name = name.split("[")[0]
                found = False
                for node in ast.iter_child_nodes(current_node):
                    if (
                        isinstance(
                            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                        )
                        and node.name == clean_name
                    ):
                        current_node = node
                        found = True
                        break
                if not found:
                    return None

            if isinstance(current_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return ast.get_docstring(current_node)
        except Exception:
            pass
        return None

    def _extract_covers_from_docstring(self, docstring: Optional[str]) -> List[str]:
        """从包含 'covers' 的 docstring 行中提取 AC 或 REQ ID。"""
        if not docstring:
            return []
        covers_ids = []
        for line in docstring.splitlines():
            if "covers" in line.lower():
                matches = re.findall(
                    r"\b(AC-VT-\d+-\d+|REQ-VT-\d+)\b", line, re.IGNORECASE
                )
                for m in matches:
                    val = m.upper()
                    if val not in covers_ids:
                        covers_ids.append(val)
        return covers_ids
