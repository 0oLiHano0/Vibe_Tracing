"""
Core enumerations and error code constants for Vibe Tracing.
"""

from enum import Enum


class CoverageStatus(str, Enum):
    """Represents the coverage/compliance status of a tracing element."""

    COVERED = "covered"
    PARTIAL = "partial"
    MISSING = "missing"
    UNCLEAR = "unclear"
    LOW_CONFIDENCE = "low_confidence"
    BLOCKED = "blocked"
    COMPLIANT = "compliant"
    VIOLATED = "violated"
    SKIPPED = "skipped"


class Severity(str, Enum):
    """Requirement severity levels (MoSCoW-lite)."""

    MUST = "must"
    SHOULD = "should"
    COULD = "could"


class ErrorCode(str, Enum):
    """Standardised error codes used across the Vibe Tracing tool-chain."""

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
