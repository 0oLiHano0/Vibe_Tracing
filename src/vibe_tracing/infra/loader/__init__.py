"""输入数据加载包。

负责从项目文件（PRD、task_list、claims、config）加载并校验数据，
为后续分析流水线提供结构化的领域对象。
"""

from vibe_tracing.infra.loader.config import load_config, resolve_path, REQUIRED_FILES
from vibe_tracing.infra.loader.raw_input import (
    RawInputLoader,
    STATUS_OK,
    STATUS_MISSING,
    STATUS_PARSE_ERROR,
    STATUS_READ_ERROR,
)
from vibe_tracing.infra.loader.prd_parser import PrdParser, PrdParseResult
from vibe_tracing.infra.loader.task_loader import TaskLoader, TaskListLoadResult
from vibe_tracing.infra.loader.claim_loader import ClaimLoader, ClaimListLoadResult

__all__ = [
    "load_config",
    "resolve_path",
    "REQUIRED_FILES",
    "RawInputLoader",
    "STATUS_OK",
    "STATUS_MISSING",
    "STATUS_PARSE_ERROR",
    "STATUS_READ_ERROR",
    "PrdParser",
    "PrdParseResult",
    "TaskLoader",
    "TaskListLoadResult",
    "ClaimLoader",
    "ClaimListLoadResult",
]
