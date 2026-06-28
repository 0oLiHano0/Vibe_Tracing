"""原始输入加载器 — Vibe Tracing 的纯文件读取层。

重要：本模块是纯文件加载层，不执行任何治理、门禁、覆盖或风险判定。
它只负责读取文件并报告加载状态。

配置加载和路径解析由 infra/loader/config.py 提供。
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from vibe_tracing.infra.config.enums import ErrorCode
from vibe_tracing.infra.loader.config import REQUIRED_FILES, resolve_path

# 输入文件加载状态
STATUS_OK = "ok"
STATUS_MISSING = "missing"
STATUS_PARSE_ERROR = "parse_error"
STATUS_READ_ERROR = "read_error"


@dataclass
class InputFileRecord:
    """单个输入文件的加载结果记录。"""

    file_key: str  # 文件标识符，如 "prd"、"task_list"、"agent_claims"
    file_path: str  # 文件路径（绝对或相对）
    is_required: bool  # 是否为必需文件
    status: str  # 加载状态：STATUS_OK / STATUS_MISSING / STATUS_PARSE_ERROR / STATUS_READ_ERROR
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


class RawInputLoader:
    """加载 Vibe Tracing 分析运行所需的所有原始输入文件。

    重要：本加载器不执行任何治理、门禁、覆盖或风险判定。
    它只负责读取文件并报告加载状态。

    config_data 必须由调用方显式传入（通过 load_config() 获取）。
    loader 实例不持有隐式 I/O 能力。
    """

    def __init__(self, project_root: Path, config_data: dict) -> None:
        """初始化 RawInputLoader。

        Args:
            project_root: 项目根目录
            config_data: 项目配置字典（由 load_config() 获取）
        """
        self.project_root = Path(project_root)
        self._config_data = config_data

    def load(self) -> RawInputManifest:
        """加载所有必需和可选的输入文件。

        返回 RawInputManifest。不会抛出异常 — 所有错误都记录在 InputFileRecord 中。
        """
        manifest = RawInputManifest()

        # 加载必需文件（从 REQUIRED_FILES 驱动）
        for file_key in REQUIRED_FILES:
            resolved = resolve_path(self.project_root, self._config_data, file_key)
            record = self._load_file(file_key, resolved, is_required=True)
            manifest.inputs_used.append(record)
            if record.status != STATUS_OK:
                manifest.has_required_errors = True
                manifest.error_count += 1

        # 加载可选文件
        optional_keys = [
            "architecture_constraints",
            "task_list",
            "agent_claims",
            "human_decisions",
        ]
        for file_key in optional_keys:
            resolved = resolve_path(self.project_root, self._config_data, file_key)
            record = self._load_file(file_key, resolved, is_required=False)
            manifest.inputs_used.append(record)
            if record.status not in (STATUS_OK, STATUS_MISSING):
                manifest.error_count += 1

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
                return InputFileRecord(
                    file_key=file_key,
                    file_path=path_str,
                    is_required=is_required,
                    status=STATUS_MISSING,
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
                        status=STATUS_PARSE_ERROR,
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
                status=STATUS_OK,
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
                status=STATUS_MISSING,
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
                status=STATUS_READ_ERROR,
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
                    status=STATUS_PARSE_ERROR,
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
            status=STATUS_OK,
            content=content,
            sha256_hash=file_hash,
        )
