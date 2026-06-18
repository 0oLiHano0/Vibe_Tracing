"""
原始输入加载器 — Vibe Tracing 的纯文件读取层。

重要：本模块是纯文件加载层，不执行任何治理、门禁、覆盖或风险判定。
它只负责读取文件并报告加载状态。
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from vibe_tracing.infra.enums import ErrorCode


@dataclass
class InputFileRecord:
    """单个输入文件的加载结果记录。"""

    file_key: str  # 文件标识符，如 "prd"、"task_list"、"agent_claims"
    file_path: str  # 文件路径（绝对或相对）
    is_required: bool  # 是否为必需文件
    status: str  # 加载状态："ok"、"missing"、"parse_error"、"read_error"
    error_code: Optional[str] = None  # 失败时的 ErrorCode 枚举值
    error_message: str = ""  # 错误描述信息
    content: Optional[Any] = None  # 已解析的内容（dict/list/str，加载失败为 None）
    sha256_hash: Optional[str] = None  # 文件原始字节的 SHA-256 哈希


@dataclass
class RawInputManifest:
    """所有原始输入文件加载结果的汇总。"""

    inputs_used: List[InputFileRecord] = field(default_factory=list)  # 所有文件的加载记录
    has_required_errors: bool = False  # 是否有必需文件加载失败
    error_count: int = 0  # 加载失败的文件总数
    tool_report_files: List[str] = field(default_factory=list)  # 工具报告文件路径列表


class RawInputLoader:
    """加载 Vibe Tracing 分析运行所需的所有原始输入文件。

    重要：本加载器不执行任何治理、门禁、覆盖或风险判定。
    它只负责读取文件并报告加载状态。
    """

    REQUIRED_FILES = {
        "prd": "docs/prd.md",
    }

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.config_data = self._load_config()

    def _load_config(self) -> dict:
        """加载 .vibetracing/config.json 配置文件。"""
        config_path = self.project_root / ".vibetracing/config.json"
        if config_path.exists():
            try:
                with config_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def get_path(self, key: str) -> Path:
        """解析文件路径：优先从 config.json 读取，否则使用默认路径。"""
        # For agent_claims: always resolve to the claims directory
        if key == "agent_claims":
            claims_dir = self.project_root / ".vibetracing" / "claims"
            if claims_dir.is_dir() and list(claims_dir.glob("CLAIM-*.json")):
                return claims_dir
            current_json = claims_dir / "current.json"
            if current_json.exists():
                return current_json
            # Return the directory path (ClaimLoader handles empty dirs)
            return claims_dir

        # 优先检查 config.json 中的自定义路径
        paths = self.config_data.get("paths", {})
        if key in paths:
            return self.project_root / paths[key]

        # 回退到标准默认路径
        defaults = {
            "prd": "docs/prd.md",
            "architecture_constraints": "docs/architecture_constraints.json",
            "task_list": "docs/task_list.json",
            "output_dir": "output",
        }
        fallback_rel = defaults.get(key)
        if not fallback_rel:
            raise ValueError(f"Unknown path key: {key}")
        resolved = self.project_root / fallback_rel
        return resolved

    def load(self) -> RawInputManifest:
        """加载所有必需和可选的输入文件。

        返回 RawInputManifest。不会抛出异常 — 所有错误都记录在 InputFileRecord 中。
        """
        manifest = RawInputManifest()

        # 加载 PRD（在加载层始终为必需）
        prd_path = self.get_path("prd")
        prd_record = self._load_file("prd", prd_path, is_required=True)
        manifest.inputs_used.append(prd_record)
        if prd_record.status != "ok":
            manifest.has_required_errors = True
            manifest.error_count += 1

        # 加载其他治理文件（在加载层始终为可选）
        optional_keys = ["architecture_constraints", "task_list", "agent_claims"]
        for file_key in optional_keys:
            resolved_path = self.get_path(file_key)
            record = self._load_file(file_key, resolved_path, is_required=False)
            manifest.inputs_used.append(record)
            if record.status not in ("ok", "missing"):
                manifest.error_count += 1

        # 扫描工具报告文件
        tool_reports_dir = self.project_root / ".vibetracing" / "tool_reports"
        if tool_reports_dir.is_dir():
            for f in sorted(tool_reports_dir.glob("*.json")):
                manifest.tool_report_files.append(str(f))

        return manifest


    def _load_file(
        self, file_key: str, abs_path: Path, is_required: bool
    ) -> InputFileRecord:
        """加载单个文件或目录。JSON 文件解析为 dict/list，MD 文件读取为文本字符串。

        对于 agent_claims，支持目录模式：加载目录下所有 CLAIM-*.json 文件并合并。

        返回包含状态和内容的 InputFileRecord，不会抛出异常。
        """
        import glob as _glob_mod

        path_str = str(abs_path)

        # 目录模式：agent_claims 支持 CLAIM-*.json 批量加载
        if abs_path.is_dir() and file_key == "agent_claims":
            claim_files = sorted(_glob_mod.glob(str(abs_path / "CLAIM-*.json")))
            if not claim_files:
                # 尝试 current.json (backward compat)
                current_json = abs_path / "current.json"
                if current_json.exists():
                    return self._load_file(file_key, current_json, is_required)
                return InputFileRecord(
                    file_key=file_key,
                    file_path=path_str,
                    is_required=is_required,
                    status="missing",
                    error_message=f"No CLAIM-*.json files found in {path_str}",
                )
            all_claims = []
            for fp in claim_files:
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        all_claims.extend(data)
                    else:
                        all_claims.append(data)
                except Exception as exc:
                    return InputFileRecord(
                        file_key=file_key,
                        file_path=path_str,
                        is_required=is_required,
                        status="parse_error",
                        error_code=ErrorCode.INVALID_INPUT.value,
                        error_message=f"Failed to read/parse {fp}: {exc}",
                    )
            # Compute hash from all claim files combined
            h = hashlib.sha256()
            for fp in claim_files:
                h.update(Path(fp).read_bytes())
            return InputFileRecord(
                file_key=file_key,
                file_path=path_str,
                is_required=is_required,
                status="ok",
                content=all_claims,
                sha256_hash=h.hexdigest(),
            )

        # 文件不存在
        if not abs_path.exists():
            error_code = ErrorCode.MISSING_INPUT.value if is_required else None
            return InputFileRecord(
                file_key=file_key,
                file_path=path_str,
                is_required=is_required,
                status="missing",
                error_code=error_code,
                error_message=f"File not found: {path_str}" if is_required else "",
            )

        # 读取文件原始字节并计算哈希
        try:
            raw_bytes = abs_path.read_bytes()
            file_hash = hashlib.sha256(raw_bytes).hexdigest()
            raw_text = raw_bytes.decode("utf-8")
        except Exception as exc:
            return InputFileRecord(
                file_key=file_key,
                file_path=path_str,
                is_required=is_required,
                status="read_error",
                error_code=ErrorCode.INVALID_INPUT.value,
                error_message=f"Could not read file: {exc}",
            )

        # 按文件扩展名解析内容
        suffix = abs_path.suffix.lower()
        if suffix == ".json":
            try:
                content = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                return InputFileRecord(
                    file_key=file_key,
                    file_path=path_str,
                    is_required=is_required,
                    status="parse_error",
                    error_code=ErrorCode.INVALID_INPUT.value,
                    error_message=f"JSON parse error: {exc}",
                )
        else:
            # 非 JSON 文件（如 .md）作为纯文本处理
            content = raw_text

        return InputFileRecord(
            file_key=file_key,
            file_path=path_str,
            is_required=is_required,
            status="ok",
            content=content,
            sha256_hash=file_hash,
        )

