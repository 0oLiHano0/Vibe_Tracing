"""
VT 共用枚举定义模块

本模块定义了 Vibe Tracing 全项目共用的枚举类型和映射常量，用于约束字段取值范围，
避免在代码各处使用魔法字符串（magic string）。

枚举类型一览：
  - CoverageStatus: 覆盖率/合规状态（如 covered、missing、violated）
  - ErrorCode: 标准化错误码（如 missing_input、schema_violation）

映射常量一览：
  - TASK_STATUS_TO_COVERAGE: 任务状态到覆盖状态的映射字典

使用方式：
  from vibe_tracing.infra.config.enums import CoverageStatus, ErrorCode, TASK_STATUS_TO_COVERAGE
  if status == CoverageStatus.VIOLATED:
      ...
  coverage = TASK_STATUS_TO_COVERAGE.get(task_status, CoverageStatus.MISSING)
"""

from enum import Enum


class CoverageStatus(str, Enum):
    """覆盖率与合规状态枚举。

    用于标识某个追踪元素（需求、验收标准、Claim 等）的覆盖状态。
    在分析器输出、门禁判定、Dashboard 渲染中广泛使用。

    各值含义：
      - COVERED:            完全覆盖（测试通过且显式关联）
      - PARTIAL:            部分覆盖（有关联但不完整）
      - MISSING:            完全未覆盖（无关联的测试或任务）
      - UNCLEAR:            无法确定覆盖状态（证据模糊或缺失）
      - LOW_CONFIDENCE:     低置信度覆盖（有关联但证据不充分）
      - BLOCKED:            被阻止（前置条件不满足，流程无法继续，如门禁拒绝提交、覆盖率未达标）
      - COMPLIANT:          合规（架构约束检查通过）
      - VIOLATED:           违规（架构约束检查未通过）
      - SKIPPED:            跳过（不适用或被排除）
      - NEEDS_REVERIFICATION: 需要重新验证（上次验证结果已过期）
    """

    COVERED = "covered"
    PARTIAL = "partial"
    MISSING = "missing"
    UNCLEAR = "unclear"
    LOW_CONFIDENCE = "low_confidence"
    BLOCKED = "blocked"
    COMPLIANT = "compliant"
    VIOLATED = "violated"
    SKIPPED = "skipped"
    NEEDS_REVERIFICATION = "needs_reverification"


class ErrorCode(str, Enum):
    """标准化错误码枚举。

    用于在日志、报告、门禁输出中统一标识错误类型，
    便于按错误码分类统计和自动化处理。

    各值含义：
      - MISSING_INPUT:           缺少必需的输入文件（如 prd.md、task_list.json）
      - INVALID_INPUT:           输入文件内容不合法（如格式错误、字段缺失）
      - SCHEMA_VIOLATION:        JSON Schema 校验未通过
      - INVALID_ID:              ID 格式不符合命名规范（如 TASK-VT-001）
      - INVALID_STATUS:          状态值不在允许的枚举范围内
      - TOOL_EXECUTION_FAILED:   工具执行失败（如 pytest 崩溃、ruff 超时）
      - MISSING_EVIDENCE:        缺少关联的证据记录（Claim 引用了不存在的测试）
      - SELF_ATTESTATION:        Claim 自证完成（违反单点验证原则）
      - TOOL_NO_TESTS_COLLECTED: 工具执行成功但未收集到任何测试结果
      - TOOL_USAGE_ERROR:        工具使用方式错误（如参数不正确、配置缺失）
    """

    MISSING_INPUT = "missing_input"
    INVALID_INPUT = "invalid_input"
    SCHEMA_VIOLATION = "schema_violation"
    INVALID_ID = "invalid_id"
    INVALID_STATUS = "invalid_status"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"
    MISSING_EVIDENCE = "missing_evidence"
    SELF_ATTESTATION = "self_attestation"
    TOOL_NO_TESTS_COLLECTED = "tool_no_tests_collected"
    TOOL_USAGE_ERROR = "tool_usage_error"


# ── 任务状态到覆盖状态的映射 ─────────────────────────────────────────────────
# 用于将任务的 status 字段映射为 CoverageStatus 枚举值，
# 在分析器中统一判断任务的覆盖贡献。
#
# 映射规则：
#   - done        → COVERED     任务已完成，应有完整覆盖
#   - in_progress → PARTIAL     任务进行中，覆盖部分完成
#   - todo        → MISSING     任务待办，尚未开始覆盖
#   - blocked     → BLOCKED     任务被阻塞，无法推进覆盖
#   - cancelled   → SKIPPED     任务已取消，不参与覆盖计算
TASK_STATUS_TO_COVERAGE: dict[str, CoverageStatus] = {
    "done": CoverageStatus.COVERED,
    "in_progress": CoverageStatus.PARTIAL,
    "todo": CoverageStatus.MISSING,
    "blocked": CoverageStatus.BLOCKED,
    "cancelled": CoverageStatus.SKIPPED,
}
