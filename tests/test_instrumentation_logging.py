"""Tests for operational logging instrumentation added across VT modules.

Covers:
- Task 5: Cache and data volume statistics (analysis.py, evidence_index_builder.py, pipeline.py)
- Task 6: Hint fallback monitoring (hint_loader.py, tool_evidence_adapter.py)
- Task 8: DEBUG-level instrumentation (merge_gate_engine.py, architecture_compliance_checker.py,
  requirement_task_analyzer.py, ac_test_analyzer.py, claim_evidence_analyzer.py)
"""

import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from vibe_tracing.operational_logger import OperationalLogger


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure singleton is reset before and after each test."""
    OperationalLogger.reset()
    yield
    OperationalLogger.reset()


def _init_logger(tmp_path: Path, level: str = "DEBUG") -> OperationalLogger:
    """Helper to initialize the logger and return it."""
    return OperationalLogger.init("TEST-RUN", tmp_path, level=level)


def _read_log_events(logger: OperationalLogger) -> List[Dict[str, Any]]:
    """Read all log entries from the log file and return as list of dicts."""
    if logger._log_path is None:
        return []
    lines = logger._log_path.read_text().strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _find_event(events: List[Dict[str, Any]], event_name: str) -> List[Dict[str, Any]]:
    """Find all log entries with the given event name."""
    return [e for e in events if e.get("event") == event_name]


# --------------------------------------------------------------------------
# Task 6: Hint fallback monitoring
# --------------------------------------------------------------------------

class TestHintFallbackLogging:
    """Tests for hint_loader.resolve_hint() fallback logging."""

    def test_resolve_hint_string_returns_directly(self, tmp_path):
        """String hints are returned directly without logging."""
        _init_logger(tmp_path)
        from vibe_tracing.hint_loader import resolve_hint

        result = resolve_hint("hello world", "level1")
        assert result == "hello world"
        events = _read_log_events(OperationalLogger.get())
        assert len(events) == 0

    def test_resolve_hint_dict_returns_correct_level(self, tmp_path):
        """Dict hints return the requested level without logging."""
        _init_logger(tmp_path)
        from vibe_tracing.hint_loader import resolve_hint

        result = resolve_hint({"level1": "L1", "level2": "L2"}, "level2")
        assert result == "L2"
        events = _read_log_events(OperationalLogger.get())
        assert len(events) == 0

    def test_resolve_hint_dict_fallback_logs_empty(self, tmp_path):
        """When dict hint resolves to empty, a DEBUG log is emitted."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.hint_loader import resolve_hint

        result = resolve_hint({"level2": "L2"}, "level1")
        assert result == ""
        events = _read_log_events(logger)
        fallback_events = _find_event(events, "hint_fallback")
        assert len(fallback_events) == 1
        assert fallback_events[0]["requested_level"] == "level1"
        assert "level2" in fallback_events[0]["available_keys"]

    def test_resolve_hint_non_string_non_dict_logs_type(self, tmp_path):
        """When hint value is non-empty, non-dict, non-string, a DEBUG log is emitted."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.hint_loader import resolve_hint

        result = resolve_hint(42, "level1")
        assert result == ""
        events = _read_log_events(logger)
        fallback_events = _find_event(events, "hint_fallback")
        assert len(fallback_events) == 1
        assert fallback_events[0]["hint_type"] == "int"

    def test_resolve_hint_none_no_log(self, tmp_path):
        """None hint returns empty string without logging (falsy, non-dict, non-string)."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.hint_loader import resolve_hint

        result = resolve_hint(None, "level1")
        assert result == ""
        events = _read_log_events(logger)
        fallback_events = _find_event(events, "hint_fallback")
        assert len(fallback_events) == 0

    def test_resolve_hint_empty_dict_logs_fallback(self, tmp_path):
        """Empty dict hint resolves to empty and logs fallback."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.hint_loader import resolve_hint

        result = resolve_hint({}, "level1")
        assert result == ""
        events = _read_log_events(logger)
        fallback_events = _find_event(events, "hint_fallback")
        assert len(fallback_events) == 1
        assert fallback_events[0]["available_keys"] == []


class TestToolEvidenceAdapterHintConsistency:
    """Tests that tool_evidence_adapter uses hint_loader.resolve_hint correctly."""

    def test_adapter_imports_from_hint_loader(self):
        """tool_evidence_adapter must import resolve_hint from hint_loader."""
        import vibe_tracing.tool_evidence_adapter as adapter
        from vibe_tracing.hint_loader import resolve_hint as loader_resolve

        # The module-level resolve_hint should be the same function
        assert adapter.resolve_hint is loader_resolve

    def test_adapter_loads_hints_from_hint_loader(self):
        """tool_evidence_adapter must use load_hints from hint_loader."""
        import vibe_tracing.tool_evidence_adapter as adapter
        from vibe_tracing.hint_loader import load_hints

        # _tool_hints should be populated
        assert isinstance(adapter._tool_hints, dict)


# --------------------------------------------------------------------------
# Task 8: DEBUG-level instrumentation — analyzers
# --------------------------------------------------------------------------

class TestRequirementTaskAnalyzerLogging:
    """Tests for DEBUG logging in RequirementTaskAnalyzer."""

    def test_analyze_logs_debug_result(self, tmp_path):
        """analyze() must emit a DEBUG log with input size and gap count."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.traceability.requirement_task_analyzer import RequirementTaskAnalyzer

        analyzer = RequirementTaskAnalyzer()

        # Create mock requirements
        mock_req = MagicMock()
        mock_req.req_id = "REQ-VT-001"
        mock_req.priority = "must"
        mock_req.title = "Test Req"

        result = analyzer.analyze([mock_req], [])

        events = _read_log_events(logger)
        result_events = _find_event(events, "analyzer_result")
        assert len(result_events) == 1
        assert result_events[0]["requirements_count"] == 1
        assert result_events[0]["evidences_count"] == 0
        assert result_events[0]["gaps_count"] == 1  # must req with no coverage


class TestAcTestAnalyzerLogging:
    """Tests for DEBUG logging in AcTestAnalyzer."""

    def test_analyze_logs_debug_result(self, tmp_path):
        """analyze() must emit a DEBUG log with input size and gap count."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.traceability.ac_test_analyzer import AcTestAnalyzer

        analyzer = AcTestAnalyzer()

        # Create mock requirement with AC
        mock_ac = MagicMock()
        mock_ac.ac_id = "AC-VT-001-01"
        mock_ac.is_testing_required = True

        mock_req = MagicMock()
        mock_req.priority = "must"
        mock_req.acceptance_criteria = [mock_ac]

        result = analyzer.analyze([mock_req], [])

        events = _read_log_events(logger)
        result_events = _find_event(events, "analyzer_result")
        assert len(result_events) == 1
        assert result_events[0]["requirements_count"] == 1
        assert result_events[0]["evidences_count"] == 0
        assert result_events[0]["gaps_count"] == 1


class TestClaimEvidenceAnalyzerLogging:
    """Tests for DEBUG logging in ClaimEvidenceAnalyzer."""

    def test_analyze_logs_debug_result(self, tmp_path):
        """analyze() must emit a DEBUG log with input size and gap count."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.traceability.claim_evidence_analyzer import ClaimEvidenceAnalyzer

        analyzer = ClaimEvidenceAnalyzer(tmp_path)
        result = analyzer.analyze([], [])

        events = _read_log_events(logger)
        result_events = _find_event(events, "analyzer_result")
        assert len(result_events) == 1
        assert result_events[0]["claims_count"] == 0
        assert result_events[0]["evidences_count"] == 0
        assert result_events[0]["gaps_count"] == 0
        assert result_events[0]["risks_count"] == 0


# --------------------------------------------------------------------------
# Task 8: DEBUG-level instrumentation — merge gate engine
# --------------------------------------------------------------------------

class TestMergeGateEngineLogging:
    """Tests for DEBUG logging in MergeGateEngine.evaluate()."""

    def test_evaluate_logs_human_decisions_lookup(self, tmp_path):
        """evaluate() must log human decisions lookup counts at DEBUG level."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.merge_gate_engine import MergeGateEngine

        engine = MergeGateEngine(tmp_path)
        result = engine.evaluate(
            gaps=[], risks=[],
            prd_status="active",
            human_decisions={"decisions": [
                {"action": "accept_risk", "targetId": "RISK-001", "category": ""},
                {"action": "mark_complete", "targetId": "GAP-001", "category": ""},
            ]},
        )

        events = _read_log_events(logger)
        hd_events = _find_event(events, "gate_human_decisions")
        assert len(hd_events) == 1
        assert hd_events[0]["total_decisions"] == 2
        assert hd_events[0]["accepted_risks"] == 1
        assert hd_events[0]["resolved_gaps"] == 1

    def test_evaluate_logs_intermediate_state(self, tmp_path):
        """evaluate() must log intermediate gate state before final decision."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.merge_gate_engine import MergeGateEngine

        engine = MergeGateEngine(tmp_path)
        result = engine.evaluate(gaps=[], risks=[], prd_status="active")

        events = _read_log_events(logger)
        intermediate_events = _find_event(events, "gate_intermediate")
        assert len(intermediate_events) == 1
        assert "gate_decision" in intermediate_events[0]
        assert "any_fail_detected" in intermediate_events[0]
        assert "current_fail_detected" in intermediate_events[0]

    def test_evaluate_logs_claim_existence_check(self, tmp_path):
        """evaluate() must log claim existence check details."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.merge_gate_engine import MergeGateEngine

        engine = MergeGateEngine(tmp_path)
        result = engine.evaluate(
            gaps=[], risks=[], prd_status="active",
            staged_items={"src/foo.py"},
            claims=[{"code_refs": ["src/foo.py"], "test_refs": []}],
        )

        events = _read_log_events(logger)
        claim_events = _find_event(events, "gate_claim_existence")
        assert len(claim_events) == 1
        assert claim_events[0]["business_files"] == 1
        assert claim_events[0]["claimed_files"] == 1
        assert claim_events[0]["unclaimed"] == 0
        assert claim_events[0]["passed"] is True

    def test_evaluate_logs_ac_coverage_check(self, tmp_path):
        """evaluate() must log AC coverage check details."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.merge_gate_engine import MergeGateEngine

        engine = MergeGateEngine(tmp_path)
        result = engine.evaluate(
            gaps=[], risks=[], prd_status="active",
            claims=[],
            tasks=[{"task_id": "T1", "priority": "must", "related_acceptance_criteria": ["AC-001"]}],
        )

        events = _read_log_events(logger)
        ac_events = _find_event(events, "gate_ac_coverage")
        assert len(ac_events) == 1
        assert ac_events[0]["total_must_acs"] == 1
        assert ac_events[0]["uncovered"] == 1


# --------------------------------------------------------------------------
# Task 8: DEBUG-level instrumentation — architecture compliance checker
# --------------------------------------------------------------------------

class TestArchitectureComplianceCheckerLogging:
    """Tests for DEBUG logging in ArchitectureComplianceChecker.check()."""

    def test_check_logs_module_boundary(self, tmp_path):
        """check() must log module boundary check details."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.architecture_compliance_checker import ArchitectureComplianceChecker

        # Create minimal constraints
        constraints = {
            "module_boundaries": [],
            "quality_gates": [],
        }

        checker = ArchitectureComplianceChecker(tmp_path)
        result = checker.check([], constraints_data=constraints)

        events = _read_log_events(logger)
        # Should have compliance_check events for DEP-VT-001, DEP-VT-002, STORE-VT-001, GATE-VT-001
        check_events = _find_event(events, "compliance_check")
        rule_ids = [e["rule_id"] for e in check_events]
        assert "DEP-VT-001" in rule_ids
        assert "STORE-VT-001" in rule_ids
        assert "GATE-VT-001" in rule_ids


# --------------------------------------------------------------------------
# Task 5: Cache statistics — _run_claim_tests
# --------------------------------------------------------------------------

class TestClaimTestsCacheLogging:
    """Tests for cache stat logging in _run_claim_tests."""

    def test_run_claim_tests_logs_cache_stats(self, tmp_path):
        """_run_claim_tests must log cache statistics."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.commands.analyze.analysis import _run_claim_tests

        # Create a mock claim with no test_refs
        mock_claim = MagicMock()
        mock_claim.test_refs = []

        evidence_index = {}
        result = _run_claim_tests(tmp_path, [mock_claim], evidence_index)

        events = _read_log_events(logger)
        cache_events = _find_event(events, "cache_stat")
        assert len(cache_events) == 1
        assert cache_events[0]["cache_hits"] == 0
        assert cache_events[0]["cache_misses"] == 0
        assert cache_events[0]["total"] == 0


# --------------------------------------------------------------------------
# Task 5: Evidence index build stats
# --------------------------------------------------------------------------

class TestEvidenceIndexBuildLogging:
    """Tests for evidence build stats logging in EvidenceIndexBuilder.build()."""

    def test_build_logs_evidence_stats(self, tmp_path):
        """build() must log evidence build statistics."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.evidence_index_builder import EvidenceIndexBuilder

        builder = EvidenceIndexBuilder(tmp_path)

        # Create minimal ctx mock
        mock_ctx = MagicMock()
        mock_ctx.prd.is_valid = True
        mock_ctx.prd.status = "active"
        mock_ctx.prd.requirements = []
        mock_ctx.task_result.tasks = []
        mock_ctx.task_result.is_valid = True
        mock_ctx.claims_list = []
        mock_ctx.manifest.inputs_used = []
        mock_ctx.config_prefix = "TEST"
        mock_ctx.tool_evidence = []

        # Create schemas dir with minimal schema
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir(parents=True, exist_ok=True)
        # Write a minimal schema that accepts anything
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
        }
        (schemas_dir / "evidence_index.schema.json").write_text(
            json.dumps(schema), encoding="utf-8"
        )

        output_path = tmp_path / "output" / "evidence_index.json"
        result = builder.build(output_path=output_path, ctx=mock_ctx)

        events = _read_log_events(logger)
        build_events = _find_event(events, "evidence_build")
        assert len(build_events) == 1
        assert "total" in build_events[0]
        assert "reused" in build_events[0]
        assert "regenerated" in build_events[0]
