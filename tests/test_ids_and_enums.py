"""
Tests for core ID validation (ids.py) and enumerations (enums.py).

Every test function declares which AC IDs it covers in its docstring.
"""

import pytest

from vibe_tracing.core.ids import validate_id, get_id_type
from vibe_tracing.core.enums import CoverageStatus, Severity, ErrorCode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_valid(id_str: str) -> None:
    """Assert that validate_id returns (True, '')."""
    ok, msg = validate_id(id_str)
    assert ok is True, f"Expected valid for {id_str!r}, got error: {msg}"
    assert msg == ""


def _assert_invalid(id_str: str) -> None:
    """Assert that validate_id returns (False, non-empty-message)."""
    ok, msg = validate_id(id_str)
    assert ok is False, f"Expected invalid for {id_str!r}"
    assert isinstance(msg, str) and len(msg) > 0, (
        f"Error message should be a non-empty string, got: {msg!r}"
    )


# ===========================================================================
# ID Validation — valid formats
# ===========================================================================


class TestValidIds:
    """AC-VT-001-03 — valid ID formats for all 13 ID types."""

    def test_req_id_valid(self):
        """covers: AC-VT-001-03"""
        _assert_valid("REQ-VT-001")
        _assert_valid("REQ-VT-999")
        _assert_valid("REQ-VT-0")

    def test_ac_id_valid(self):
        """covers: AC-VT-001-03"""
        _assert_valid("AC-VT-001-01")
        _assert_valid("AC-VT-100-99")
        _assert_valid("AC-VT-0-0")

    def test_task_id_valid(self):
        """covers: AC-VT-001-03"""
        _assert_valid("TASK-VT-001")
        _assert_valid("TASK-VT-999")

    def test_dod_id_valid(self):
        """covers: AC-VT-001-03"""
        _assert_valid("DOD-VT-001-01")
        _assert_valid("DOD-VT-100-05")

    def test_mod_id_valid(self):
        """covers: AC-VT-001-03"""
        _assert_valid("MOD-VT-001")
        _assert_valid("MOD-VT-42")

    def test_gate_id_valid(self):
        """covers: AC-VT-001-03"""
        _assert_valid("GATE-VT-001")
        _assert_valid("GATE-VT-10")

    def test_forbid_id_valid(self):
        """covers: AC-VT-001-03"""
        _assert_valid("FORBID-VT-001")
        _assert_valid("FORBID-VT-9")

    def test_principle_id_valid(self):
        """covers: AC-VT-001-03"""
        _assert_valid("PRINCIPLE-VT-001")
        _assert_valid("PRINCIPLE-VT-100")

    def test_phase_id_valid(self):
        """covers: AC-VT-001-03"""
        _assert_valid("PHASE-VT-001")
        _assert_valid("PHASE-VT-5")

    def test_project_id_valid(self):
        """covers: AC-VT-001-03"""
        _assert_valid("PROJECT-VT")

    def test_evidence_id_valid(self):
        """covers: AC-VT-001-03"""
        _assert_valid("EVIDENCE-VT-001")
        _assert_valid("EVIDENCE-VT-50")

    def test_risk_id_valid(self):
        """covers: AC-VT-001-03"""
        _assert_valid("RISK-VT-001")
        _assert_valid("RISK-VT-7")

    def test_claim_id_valid(self):
        """covers: AC-VT-001-03"""
        _assert_valid("CLAIM-VT-001")
        _assert_valid("CLAIM-VT-200")


# ===========================================================================
# ID Validation — invalid formats
# ===========================================================================


class TestInvalidIds:
    """AC-VT-001-03 — invalid IDs must return (False, non-empty message)."""

    def test_empty_string_invalid(self):
        """covers: AC-VT-001-03"""
        _assert_invalid("")

    def test_blank_string_invalid(self):
        """covers: AC-VT-001-03"""
        _assert_invalid("   ")

    def test_unknown_prefix_invalid(self):
        """covers: AC-VT-001-03"""
        _assert_invalid("UNKNOWN-VT-001")

    def test_wrong_separator_invalid(self):
        """covers: AC-VT-001-03"""
        _assert_invalid("REQ_VT_001")

    def test_missing_vt_segment_invalid(self):
        """covers: AC-VT-001-03"""
        _assert_invalid("REQ-001")

    def test_req_with_two_digit_groups_invalid(self):
        """covers: AC-VT-001-03"""
        # REQ only accepts one digit group; two groups are the AC/DOD format
        _assert_invalid("REQ-VT-001-01")

    def test_ac_with_one_digit_group_invalid(self):
        """covers: AC-VT-001-03"""
        _assert_invalid("AC-VT-001")

    def test_project_vt_with_suffix_invalid(self):
        """covers: AC-VT-001-03"""
        _assert_invalid("PROJECT-VT-001")

    def test_lowercase_prefix_invalid(self):
        """covers: AC-VT-001-03"""
        _assert_invalid("req-vt-001")

    def test_trailing_letters_invalid(self):
        """covers: AC-VT-001-03"""
        _assert_invalid("REQ-VT-001abc")

    def test_non_string_type_returns_false(self):
        """covers: AC-VT-001-03"""
        ok, msg = validate_id(123)  # type: ignore[arg-type]
        assert ok is False
        assert len(msg) > 0

    def test_dod_with_one_digit_group_invalid(self):
        """covers: AC-VT-001-03"""
        _assert_invalid("DOD-VT-001")

    def test_forbid_with_two_digit_groups_invalid(self):
        """covers: AC-VT-001-03"""
        _assert_invalid("FORBID-VT-001-01")


# ===========================================================================
# get_id_type
# ===========================================================================


class TestGetIdType:
    """AC-VT-001-03 — get_id_type returns the correct prefix or raises ValueError."""

    def test_req_type(self):
        """covers: AC-VT-001-03"""
        assert get_id_type("REQ-VT-001") == "REQ"

    def test_ac_type(self):
        """covers: AC-VT-001-03"""
        assert get_id_type("AC-VT-001-01") == "AC"

    def test_task_type(self):
        """covers: AC-VT-001-03"""
        assert get_id_type("TASK-VT-001") == "TASK"

    def test_dod_type(self):
        """covers: AC-VT-001-03"""
        assert get_id_type("DOD-VT-001-01") == "DOD"

    def test_mod_type(self):
        """covers: AC-VT-001-03"""
        assert get_id_type("MOD-VT-001") == "MOD"

    def test_gate_type(self):
        """covers: AC-VT-001-03"""
        assert get_id_type("GATE-VT-001") == "GATE"

    def test_forbid_type(self):
        """covers: AC-VT-001-03"""
        assert get_id_type("FORBID-VT-001") == "FORBID"

    def test_principle_type(self):
        """covers: AC-VT-001-03"""
        assert get_id_type("PRINCIPLE-VT-001") == "PRINCIPLE"

    def test_phase_type(self):
        """covers: AC-VT-001-03"""
        assert get_id_type("PHASE-VT-001") == "PHASE"

    def test_project_type(self):
        """covers: AC-VT-001-03"""
        assert get_id_type("PROJECT-VT") == "PROJECT"

    def test_evidence_type(self):
        """covers: AC-VT-001-03"""
        assert get_id_type("EVIDENCE-VT-001") == "EVIDENCE"

    def test_risk_type(self):
        """covers: AC-VT-001-03"""
        assert get_id_type("RISK-VT-001") == "RISK"

    def test_claim_type(self):
        """covers: AC-VT-001-03"""
        assert get_id_type("CLAIM-VT-001") == "CLAIM"

    def test_unknown_raises_value_error(self):
        """covers: AC-VT-001-03"""
        with pytest.raises(ValueError, match="Unknown ID format"):
            get_id_type("BOGUS-VT-001")

    def test_non_string_raises_value_error(self):
        """covers: AC-VT-001-03"""
        with pytest.raises(ValueError):
            get_id_type(None)  # type: ignore[arg-type]


# ===========================================================================
# CoverageStatus enum
# ===========================================================================


class TestCoverageStatus:
    """AC-VT-002-01 — all 8 CoverageStatus values must exist."""

    def test_all_coverage_status_values_exist(self):
        """covers: AC-VT-002-01"""
        expected = {
            "covered",
            "partial",
            "missing",
            "unclear",
            "low_confidence",
            "blocked",
            "compliant",
            "violated",
            "skipped",
            "needs_reverification",
        }
        actual = {member.value for member in CoverageStatus}
        assert actual == expected, (
            f"Missing values: {expected - actual}; Extra values: {actual - expected}"
        )

    def test_coverage_status_is_str_enum(self):
        """covers: AC-VT-002-01"""
        assert isinstance(CoverageStatus.COVERED, str)
        assert CoverageStatus.COVERED == "covered"

    def test_coverage_status_count(self):
        """covers: AC-VT-002-01"""
        assert len(CoverageStatus) == 10

    @pytest.mark.parametrize(
        "value",
        [
            "covered",
            "partial",
            "missing",
            "unclear",
            "low_confidence",
            "blocked",
            "compliant",
            "violated",
            "skipped",
        ],
    )
    def test_coverage_status_lookup_by_value(self, value: str):
        """covers: AC-VT-002-01"""
        member = CoverageStatus(value)
        assert member.value == value


# ===========================================================================
# Severity enum
# ===========================================================================


class TestSeverity:
    """AC-VT-006-02 — all Severity values must exist."""

    def test_all_severity_values_exist(self):
        """covers: AC-VT-006-02"""
        expected = {"must", "should", "could"}
        actual = {member.value for member in Severity}
        assert actual == expected

    def test_severity_is_str_enum(self):
        """covers: AC-VT-006-02"""
        assert isinstance(Severity.MUST, str)
        assert Severity.MUST == "must"

    def test_severity_count(self):
        """covers: AC-VT-006-02"""
        assert len(Severity) == 3

    @pytest.mark.parametrize("value", ["must", "should", "could"])
    def test_severity_lookup_by_value(self, value: str):
        """covers: AC-VT-006-02"""
        member = Severity(value)
        assert member.value == value


# ===========================================================================
# ErrorCode enum
# ===========================================================================


class TestErrorCode:
    """AC-VT-008-03 — all ErrorCode values must exist."""

    def test_all_error_code_values_exist(self):
        """covers: AC-VT-008-03"""
        expected = {
            "missing_input",
            "invalid_input",
            "schema_violation",
            "invalid_id",
            "invalid_status",
            "tool_execution_failed",
            "missing_evidence",
            "self_attestation",
            "tool_no_tests_collected",
            "tool_usage_error",
        }
        actual = {member.value for member in ErrorCode}
        assert actual == expected, (
            f"Missing values: {expected - actual}; Extra values: {actual - expected}"
        )

    def test_error_code_is_str_enum(self):
        """covers: AC-VT-008-03"""
        assert isinstance(ErrorCode.INVALID_ID, str)
        assert ErrorCode.INVALID_ID == "invalid_id"

    def test_error_code_count(self):
        """covers: AC-VT-008-03"""
        assert len(ErrorCode) == 10

    @pytest.mark.parametrize(
        "value",
        [
            "missing_input",
            "invalid_input",
            "schema_violation",
            "invalid_id",
            "invalid_status",
            "tool_execution_failed",
            "missing_evidence",
            "self_attestation",
            "tool_no_tests_collected",
            "tool_usage_error",
        ],
    )
    def test_error_code_lookup_by_value(self, value: str):
        """covers: AC-VT-008-03"""
        member = ErrorCode(value)
        assert member.value == value
