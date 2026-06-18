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

from vibe_tracing.infra.operational_logger import OperationalLogger


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
        from vibe_tracing.infra.hint_loader import resolve_hint

        result = resolve_hint("hello world", "level1")
        assert result == "hello world"
        events = _read_log_events(OperationalLogger.get())
        assert len(events) == 0

    def test_resolve_hint_dict_returns_correct_level(self, tmp_path):
        """Dict hints return the requested level without logging."""
        _init_logger(tmp_path)
        from vibe_tracing.infra.hint_loader import resolve_hint

        result = resolve_hint({"level1": "L1", "level2": "L2"}, "level2")
        assert result == "L2"
        events = _read_log_events(OperationalLogger.get())
        assert len(events) == 0

    def test_resolve_hint_dict_fallback_logs_empty(self, tmp_path):
        """When dict hint resolves to empty, a DEBUG log is emitted."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.infra.hint_loader import resolve_hint

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
        from vibe_tracing.infra.hint_loader import resolve_hint

        result = resolve_hint(42, "level1")
        assert result == ""
        events = _read_log_events(logger)
        fallback_events = _find_event(events, "hint_fallback")
        assert len(fallback_events) == 1
        assert fallback_events[0]["hint_type"] == "int"

    def test_resolve_hint_none_no_log(self, tmp_path):
        """None hint returns empty string without logging (falsy, non-dict, non-string)."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.infra.hint_loader import resolve_hint

        result = resolve_hint(None, "level1")
        assert result == ""
        events = _read_log_events(logger)
        fallback_events = _find_event(events, "hint_fallback")
        assert len(fallback_events) == 0

    def test_resolve_hint_empty_dict_logs_fallback(self, tmp_path):
        """Empty dict hint resolves to empty and logs fallback."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.infra.hint_loader import resolve_hint

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
        import vibe_tracing.domain.tool_evidence_adapter as adapter
        from vibe_tracing.infra.hint_loader import resolve_hint as loader_resolve

        # The module-level resolve_hint should be the same function
        assert adapter.resolve_hint is loader_resolve

    def test_adapter_loads_hints_from_hint_loader(self):
        """tool_evidence_adapter must use load_hints from hint_loader."""
        import vibe_tracing.domain.tool_evidence_adapter as adapter
        from vibe_tracing.infra.hint_loader import load_hints

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
        from vibe_tracing.analyzers.requirement_task_analyzer import RequirementTaskAnalyzer

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
        from vibe_tracing.analyzers.ac_test_analyzer import AcTestAnalyzer

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
        from vibe_tracing.analyzers.claim_evidence_analyzer import ClaimEvidenceAnalyzer

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
        from vibe_tracing.domain.merge_gate_engine import MergeGateEngine
        from vibe_tracing.infra.db import init_in_memory_db

        engine = MergeGateEngine(tmp_path, init_in_memory_db())
        result = engine.evaluate(
            gaps=[], risks=[],
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
        from vibe_tracing.domain.merge_gate_engine import MergeGateEngine
        from vibe_tracing.infra.db import init_in_memory_db

        engine = MergeGateEngine(tmp_path, init_in_memory_db())
        result = engine.evaluate(gaps=[], risks=[])

        events = _read_log_events(logger)
        intermediate_events = _find_event(events, "gate_intermediate")
        assert len(intermediate_events) == 1
        assert "gate_decision" in intermediate_events[0]
        assert "any_fail_detected" in intermediate_events[0]
        assert "current_fail_detected" in intermediate_events[0]

    def test_evaluate_logs_claim_existence_check(self, tmp_path):
        """evaluate() must log claim existence check details (SQL-based)."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.domain.merge_gate_engine import MergeGateEngine
        from vibe_tracing.infra.db import init_in_memory_db

        conn = init_in_memory_db()
        engine = MergeGateEngine(tmp_path, conn)
        result = engine.evaluate(
            gaps=[], risks=[],
            staged_items={"src/foo.py"},
        )

        events = _read_log_events(logger)
        claim_events = _find_event(events, "gate_claim_existence")
        assert len(claim_events) == 1
        # SQL-based check returns ghost_count (empty DB = 0 ghosts)
        assert claim_events[0]["ghost_count"] == 0

    def test_evaluate_logs_ac_coverage_check(self, tmp_path):
        """evaluate() must log AC coverage check details (SQL-based)."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.domain.merge_gate_engine import MergeGateEngine
        from vibe_tracing.infra.db import init_in_memory_db

        conn = init_in_memory_db()
        engine = MergeGateEngine(tmp_path, conn)
        result = engine.evaluate(
            gaps=[], risks=[],
        )

        events = _read_log_events(logger)
        ac_events = _find_event(events, "gate_ac_coverage")
        assert len(ac_events) == 1
        # SQL-based check: empty DB has no AC gaps
        assert ac_events[0]["uncovered"] == 0


# --------------------------------------------------------------------------
# Task 8: DEBUG-level instrumentation — architecture compliance checker
# --------------------------------------------------------------------------

class TestArchitectureComplianceCheckerLogging:
    """Tests for DEBUG logging in ArchitectureComplianceChecker.check()."""

    def test_check_logs_module_boundary(self, tmp_path):
        """check() must log module boundary check details."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.domain.architecture_compliance_checker import ArchitectureComplianceChecker

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
        from vibe_tracing.cli.analyze.analysis import _run_claim_tests

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
# Per-item decision trace logging (MergeGateEngine)
# --------------------------------------------------------------------------

class TestMergeGatePerItemLogging:
    """Tests for per-item DEBUG logging in MergeGateEngine gap/risk/AC evaluation."""

    def test_must_gap_eval_log_emitted(self, tmp_path):
        """_process_must_gaps must emit gate_gap_eval for each AC gap item."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.domain.merge_gate_engine import MergeGateEngine
        from vibe_tracing.infra.db import init_in_memory_db

        engine = MergeGateEngine(tmp_path, init_in_memory_db())
        gaps = [
            {
                "item_id": "AC-VT-001-01",
                "item_type": "ac",
                "target_id": "AC-VT-001-01",
                "reason": "Must AC missing test coverage.",
            }
        ]
        engine.evaluate(gaps=gaps, risks=[])

        events = _read_log_events(logger)
        gap_events = _find_event(events, "gate_gap_eval")
        assert len(gap_events) >= 1
        ev = gap_events[0]
        assert ev["item_id"] == "AC-VT-001-01"
        assert ev["item_type"] == "ac"
        assert ev["is_stale"] is False
        assert ev["is_human_resolved"] is False
        assert ev["final_status"] == "blocked"
        assert "Must AC missing test coverage" in ev["reason"]

    def test_must_gap_eval_human_resolved(self, tmp_path):
        """gate_gap_eval must show human_resolved status when human decision matches."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.domain.merge_gate_engine import MergeGateEngine
        from vibe_tracing.infra.db import init_in_memory_db

        engine = MergeGateEngine(tmp_path, init_in_memory_db())
        gaps = [
            {
                "item_id": "AC-VT-001-01",
                "item_type": "ac",
                "target_id": "AC-VT-001-01",
                "reason": "Missing test.",
            }
        ]
        engine.evaluate(
            gaps=gaps, risks=[],
            human_decisions={"decisions": [
                {"action": "mark_complete", "targetId": "AC-VT-001-01", "category": ""},
            ]},
        )

        events = _read_log_events(logger)
        gap_events = _find_event(events, "gate_gap_eval")
        assert len(gap_events) >= 1
        ev = gap_events[0]
        assert ev["is_human_resolved"] is True
        assert ev["final_status"] == "human_resolved"
        assert ev["human_decision_type"] == "mark_complete"

    def test_must_risk_eval_log_emitted(self, tmp_path):
        """_process_must_risks must emit gate_risk_eval for each risk item."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.domain.merge_gate_engine import MergeGateEngine
        from vibe_tracing.infra.db import init_in_memory_db

        engine = MergeGateEngine(tmp_path, init_in_memory_db())
        risks = [
            {
                "risk_id": "RISK-VT-001",
                "severity": "must",
                "description": "Self-referential claim found.",
                "suggested_action": "Add external evidence.",
                "business_impact": "Violates no-self-attestation.",
            }
        ]
        engine.evaluate(gaps=[], risks=risks)

        events = _read_log_events(logger)
        risk_events = _find_event(events, "gate_risk_eval")
        assert len(risk_events) >= 1
        ev = risk_events[0]
        assert ev["risk_id"] == "RISK-VT-001"
        assert ev["severity"] == "must"
        assert ev["is_human_resolved"] is False
        assert ev["final_status"] == "blocked"

    def test_must_risk_eval_accepted(self, tmp_path):
        """gate_risk_eval must show accepted status when human accepts risk."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.domain.merge_gate_engine import MergeGateEngine
        from vibe_tracing.infra.db import init_in_memory_db

        engine = MergeGateEngine(tmp_path, init_in_memory_db())
        risks = [
            {
                "risk_id": "RISK-VT-001",
                "target_id": "RISK-VT-001",
                "severity": "must",
                "description": "Critical risk.",
                "suggested_action": "Accept for now.",
                "business_impact": "Low impact.",
            }
        ]
        engine.evaluate(
            gaps=[], risks=risks,
            human_decisions={"decisions": [
                {"action": "accept_risk", "targetId": "RISK-VT-001", "category": ""},
            ]},
        )

        events = _read_log_events(logger)
        risk_events = _find_event(events, "gate_risk_eval")
        assert len(risk_events) >= 1
        ev = risk_events[0]
        assert ev["is_human_resolved"] is True
        assert ev["final_status"] == "accepted"
        assert ev["human_decision_type"] == "accept_risk"

    def test_gate_ac_check_log_emitted(self, tmp_path):
        """check_ac_coverage must emit gate_ac_coverage for AC coverage check (SQL-based)."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.domain.merge_gate_engine import MergeGateEngine
        from vibe_tracing.infra.db import init_in_memory_db

        engine = MergeGateEngine(tmp_path, init_in_memory_db())
        engine.evaluate(
            gaps=[], risks=[],
        )

        events = _read_log_events(logger)
        # SQL-based AC coverage check emits gate_ac_coverage (not per-item gate_ac_check)
        ac_events = _find_event(events, "gate_ac_coverage")
        assert len(ac_events) >= 1
        # Empty DB means 0 uncovered ACs
        assert ac_events[0]["uncovered"] == 0

    def test_gate_ac_check_covered_ac(self, tmp_path):
        """gate_ac_coverage must be emitted when AC coverage check runs (SQL-based)."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.domain.merge_gate_engine import MergeGateEngine
        from vibe_tracing.infra.db import init_in_memory_db

        engine = MergeGateEngine(tmp_path, init_in_memory_db())
        engine.evaluate(
            gaps=[], risks=[],
        )

        events = _read_log_events(logger)
        # SQL-based check emits gate_ac_coverage (not per-item gate_ac_check)
        ac_events = _find_event(events, "gate_ac_coverage")
        assert len(ac_events) >= 1
        # Empty DB: no uncovered ACs


# --------------------------------------------------------------------------
# Import-level detail logging (ArchitectureComplianceChecker)
# --------------------------------------------------------------------------

class TestComplianceImportLogging:
    """Tests for import-level DEBUG logging in ArchitectureComplianceChecker."""

    def test_module_boundary_logs_allowed_imports(self, tmp_path):
        """Module boundary check must log allowed cross-module imports."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.domain.architecture_compliance_checker import ArchitectureComplianceChecker

        # Create a minimal source file with an import
        src_dir = tmp_path / "src" / "vibe_tracing"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "__init__.py").write_text("")

        # Create a file in MOD-VT-002 that imports from MOD-VT-003
        (src_dir / "raw_input_loader.py").write_text(
            "from vibe_tracing.infra.schema_validator import validate\n"
        )
        # Create the imported module file
        (src_dir / "schema_validator.py").write_text("def validate(): pass\n")

        constraints = {
            "module_boundaries": [
                {
                    "module_id": "MOD-VT-002",
                    "name": "raw_input_loader",
                    "responsibility": "Loader",
                    "allowed_to_call": ["MOD-VT-003"],
                    "forbidden_to_call": [],
                    "owned_files": ["raw_input_loader.py"],
                },
                {
                    "module_id": "MOD-VT-003",
                    "name": "schema_validator",
                    "responsibility": "Validator",
                    "allowed_to_call": [],
                    "forbidden_to_call": [],
                    "owned_files": ["schema_validator.py"],
                },
            ],
            "quality_gates": [],
        }

        checker = ArchitectureComplianceChecker(tmp_path)
        checker.check([], constraints_data=constraints)

        events = _read_log_events(logger)
        allowed_events = _find_event(events, "compliance_import_allowed")
        assert len(allowed_events) >= 1
        ev = allowed_events[0]
        assert "raw_input_loader.py" in ev["file"]
        assert ev["imported_module_id"] == "MOD-VT-003"
        assert ev["module_id"] == "MOD-VT-002"

    def test_module_boundary_logs_violation_imports(self, tmp_path):
        """Module boundary check must log forbidden import violations."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.domain.architecture_compliance_checker import ArchitectureComplianceChecker

        src_dir = tmp_path / "src" / "vibe_tracing"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "__init__.py").write_text("")

        # Create a file in MOD-VT-002 that imports from MOD-VT-006 (forbidden)
        (src_dir / "raw_input_loader.py").write_text(
            "from vibe_tracing.traceability_analyzer import analyze\n"
        )
        (src_dir / "traceability_analyzer.py").write_text("def analyze(): pass\n")

        constraints = {
            "module_boundaries": [
                {
                    "module_id": "MOD-VT-002",
                    "name": "raw_input_loader",
                    "responsibility": "Loader",
                    "allowed_to_call": [],
                    "forbidden_to_call": ["MOD-VT-006"],
                    "owned_files": ["raw_input_loader.py"],
                },
                {
                    "module_id": "MOD-VT-006",
                    "name": "traceability_analyzer",
                    "responsibility": "Analyzer",
                    "allowed_to_call": [],
                    "forbidden_to_call": [],
                    "owned_files": ["traceability_analyzer.py"],
                },
            ],
            "quality_gates": [],
        }

        checker = ArchitectureComplianceChecker(tmp_path)
        checker.check([], constraints_data=constraints)

        events = _read_log_events(logger)
        violation_events = _find_event(events, "compliance_import_violation")
        assert len(violation_events) >= 1
        ev = violation_events[0]
        assert ev["rule_type"] == "forbidden"
        assert ev["imported_module_id"] == "MOD-VT-006"
        assert ev["module_id"] == "MOD-VT-002"

    def test_dep_vt002_logs_dashboard_check(self, tmp_path):
        """DEP-VT-002 must log what was checked in dashboard.html."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.domain.architecture_compliance_checker import ArchitectureComplianceChecker

        # Create a dashboard.html with inline content
        dash_dir = tmp_path / "output"
        dash_dir.mkdir(parents=True, exist_ok=True)
        (dash_dir / "dashboard.html").write_text(
            "<html><head><style>body{}</style></head><body>Hello</body></html>"
        )

        constraints = {"module_boundaries": [], "quality_gates": []}
        checker = ArchitectureComplianceChecker(tmp_path)
        checker.check([], constraints_data=constraints)

        events = _read_log_events(logger)
        dep_events = _find_event(events, "compliance_dep_vt002_check")
        assert len(dep_events) >= 1
        ev = dep_events[0]
        assert ev["external_urls_found"] == 0
        assert ev["status"] == "compliant"
        assert ev["has_inline_css"] is True

    def test_dep_vt002_logs_external_url_violation(self, tmp_path):
        """DEP-VT-002 must log external URLs found in dashboard."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.domain.architecture_compliance_checker import ArchitectureComplianceChecker

        dash_dir = tmp_path / "output"
        dash_dir.mkdir(parents=True, exist_ok=True)
        (dash_dir / "dashboard.html").write_text(
            '<html><head><script src="https://cdn.example.com/lib.js"></script></head></html>'
        )

        constraints = {"module_boundaries": [], "quality_gates": []}
        checker = ArchitectureComplianceChecker(tmp_path)
        checker.check([], constraints_data=constraints)

        events = _read_log_events(logger)
        dep_events = _find_event(events, "compliance_dep_vt002_check")
        assert len(dep_events) >= 1
        ev = dep_events[0]
        assert ev["external_urls_found"] >= 1
        assert ev["status"] == "violated"


# --------------------------------------------------------------------------
# Mapping chain logging (Traceability Analyzers)
# --------------------------------------------------------------------------

class TestRequirementMappingLogging:
    """Tests for per-requirement mapping DEBUG logs."""

    def test_req_mapping_log_emitted(self, tmp_path):
        """RequirementTaskAnalyzer must emit req_mapping for each requirement."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.analyzers.requirement_task_analyzer import RequirementTaskAnalyzer

        analyzer = RequirementTaskAnalyzer()

        mock_req = MagicMock()
        mock_req.req_id = "REQ-VT-001"
        mock_req.priority = "must"
        mock_req.title = "Test Req"

        analyzer.analyze([mock_req], [])

        events = _read_log_events(logger)
        mapping_events = _find_event(events, "req_mapping")
        assert len(mapping_events) >= 1
        ev = mapping_events[0]
        assert ev["req_id"] == "REQ-VT-001"
        assert ev["related_tasks"] == []
        assert ev["coverage_status"] == "missing"

    def test_req_mapping_with_task_evidence(self, tmp_path):
        """req_mapping must include task IDs when task evidence exists."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.analyzers.requirement_task_analyzer import RequirementTaskAnalyzer

        analyzer = RequirementTaskAnalyzer()

        mock_req = MagicMock()
        mock_req.req_id = "REQ-VT-001"
        mock_req.priority = "must"
        mock_req.title = "Test Req"

        evidences = [
            {
                "evidence_id": "EV-001",
                "source_type": "task",
                "status": "covered",
                "covers": ["REQ-VT-001"],
                "details": {"task_id": "TASK-VT-001"},
            }
        ]

        analyzer.analyze([mock_req], evidences)

        events = _read_log_events(logger)
        mapping_events = _find_event(events, "req_mapping")
        assert len(mapping_events) >= 1
        ev = mapping_events[0]
        assert ev["req_id"] == "REQ-VT-001"
        assert "TASK-VT-001" in ev["related_tasks"]
        assert ev["coverage_status"] == "covered"


class TestAcMappingLogging:
    """Tests for per-AC test mapping DEBUG logs."""

    def test_ac_mapping_log_emitted(self, tmp_path):
        """AcTestAnalyzer must emit ac_mapping for each AC."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.analyzers.ac_test_analyzer import AcTestAnalyzer

        analyzer = AcTestAnalyzer()

        mock_ac = MagicMock()
        mock_ac.ac_id = "AC-VT-001-01"
        mock_ac.is_testing_required = True

        mock_req = MagicMock()
        mock_req.priority = "must"
        mock_req.acceptance_criteria = [mock_ac]

        analyzer.analyze([mock_req], [])

        events = _read_log_events(logger)
        mapping_events = _find_event(events, "ac_mapping")
        assert len(mapping_events) >= 1
        ev = mapping_events[0]
        assert ev["ac_id"] == "AC-VT-001-01"
        assert ev["covered"] is False
        assert ev["uncovered_reason"] == "no_tests"

    def test_ac_mapping_with_passing_test(self, tmp_path):
        """ac_mapping must show covered=True when passing test exists."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.analyzers.ac_test_analyzer import AcTestAnalyzer

        analyzer = AcTestAnalyzer()

        mock_ac = MagicMock()
        mock_ac.ac_id = "AC-VT-001-01"
        mock_ac.is_testing_required = True

        mock_req = MagicMock()
        mock_req.priority = "must"
        mock_req.acceptance_criteria = [mock_ac]

        evidences = [
            {
                "evidence_id": "EV-001",
                "source_type": "test",
                "source_path": "tests/test_foo.py::test_bar",
                "status": "covered",
                "covers": ["AC-VT-001-01"],
                "details": {},
            },
            {
                "evidence_id": "EV-002",
                "source_type": "task",
                "status": "covered",
                "covers": ["AC-VT-001-01"],
                "details": {"task_id": "TASK-001"},
            },
        ]

        analyzer.analyze([mock_req], evidences)

        events = _read_log_events(logger)
        mapping_events = _find_event(events, "ac_mapping")
        assert len(mapping_events) >= 1
        ev = mapping_events[0]
        assert ev["ac_id"] == "AC-VT-001-01"
        assert ev["covered"] is True
        assert ev["parent_task_id"] == "TASK-001"
        assert "tests/test_foo.py::test_bar" in ev["test_refs"]


class TestClaimMappingLogging:
    """Tests for per-claim evidence chain DEBUG logs."""

    def test_claim_mapping_log_emitted(self, tmp_path):
        """ClaimEvidenceAnalyzer must emit claim_mapping for each claim."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.analyzers.claim_evidence_analyzer import ClaimEvidenceAnalyzer

        analyzer = ClaimEvidenceAnalyzer(tmp_path)

        mock_claim = MagicMock()
        mock_claim.claim_id = "CLAIM-001"
        mock_claim.claimed_status = "covered"
        mock_claim.related_task = "TASK-001"
        mock_claim.evidence_refs = []
        mock_claim.code_refs = ["src/foo.py"]
        mock_claim.test_refs = ["tests/test_foo.py"]

        analyzer.analyze([mock_claim], [])

        events = _read_log_events(logger)
        mapping_events = _find_event(events, "claim_mapping")
        assert len(mapping_events) >= 1
        ev = mapping_events[0]
        assert ev["claim_id"] == "CLAIM-001"
        assert ev["related_task"] == "TASK-001"
        assert ev["code_refs_count"] == 1
        assert ev["test_refs_count"] == 1
        assert ev["status"] == "missing_refs"

    def test_claim_mapping_valid_status(self, tmp_path):
        """claim_mapping must show valid status when evidence is complete."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.analyzers.claim_evidence_analyzer import ClaimEvidenceAnalyzer

        analyzer = ClaimEvidenceAnalyzer(tmp_path)

        mock_claim = MagicMock()
        mock_claim.claim_id = "CLAIM-001"
        mock_claim.claimed_status = "covered"
        mock_claim.related_task = "TASK-001"
        mock_claim.evidence_refs = ["EV-001"]
        mock_claim.code_refs = []
        mock_claim.test_refs = []

        evidences = [
            {
                "evidence_id": "EV-001",
                "source_type": "tool",
                "source_path": "src/foo.py",
                "status": "covered",
                "covers": [],
                "details": {},
            },
            {
                "evidence_id": "EV-TASK",
                "source_type": "task",
                "source_path": "",
                "status": "covered",
                "covers": [],
                "details": {"task_id": "TASK-001"},
            },
        ]

        analyzer.analyze([mock_claim], evidences)

        events = _read_log_events(logger)
        mapping_events = _find_event(events, "claim_mapping")
        assert len(mapping_events) >= 1
        ev = mapping_events[0]
        assert ev["claim_id"] == "CLAIM-001"
        assert ev["status"] == "valid"


# --------------------------------------------------------------------------
# Subprocess output logging (ToolExecutionEngine)
# --------------------------------------------------------------------------

class TestSubprocessOutputLogging:
    """Tests for subprocess stdout/stderr DEBUG logging."""

    def test_subprocess_output_log_emitted(self, tmp_path):
        """_run_subprocess must emit subprocess_output with stdout/stderr preview."""
        logger = _init_logger(tmp_path)
        from vibe_tracing.domain.tool_evidence_adapter import ToolExecutionEngine

        # Create a minimal language_tool_matrix
        matrix = {
            "python": {
                "extensions": [".py"],
                "test": {
                    "default_command": "echo hello",
                    "output_format": "pytest_json",
                },
            }
        }
        engine = ToolExecutionEngine(
            language_tool_matrix=matrix,
            language="python",
            validation_tools=["test"],
            project_root=tmp_path,
        )

        # Run a simple command via _run_subprocess
        engine._run_subprocess("echo 'test output'")

        events = _read_log_events(logger)
        output_events = _find_event(events, "subprocess_output")
        assert len(output_events) >= 1
        ev = output_events[0]
        assert "echo" in ev["command"]
        assert "test output" in ev["stdout_preview"]
        assert ev["stderr_preview"] == ""
