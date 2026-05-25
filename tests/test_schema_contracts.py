"""
Tests for JSON Schema contracts defined in schemas/.

Covers:
  AC-VT-001-01 — Each data structure has a machine-verifiable JSON Schema.
  AC-VT-001-02 — Schemas enforce required fields and reject invalid documents.
  AC-VT-002-01 — ID patterns are validated via regex constraints.
"""

import json
import pytest
from pathlib import Path
from jsonschema import validate, ValidationError

SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"


def load_schema(name: str) -> dict:
    """Load a JSON schema from the schemas/ directory by filename."""
    return json.loads((SCHEMAS_DIR / name).read_text())


# ---------------------------------------------------------------------------
# Helpers — minimal valid documents for each schema
# ---------------------------------------------------------------------------


def _minimal_task_list() -> dict:
    """Return a minimal valid task_list document."""
    return {
        "schema_version": "1.0.0",
        "project": {
            "project_id": "PROJECT-VT",
            "name": "Vibe Tracing",
            "stage": "alpha",
        },
        "tasks": [
            {
                "task_id": "TASK-VT-001",
                "title": "Sample task",
                "phase_id": "PHASE-VT-01",
                "priority": "must",
                "status": "todo",
                "owner_role": "developer",
                "objective": "Do something useful.",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [
                    {
                        "dod_id": "DOD-VT-001-01",
                        "description": "Criterion met.",
                    }
                ],
            }
        ],
    }


def _minimal_agent_claims() -> list:
    """Return a minimal valid agent_claims document (array)."""
    return [
        {
            "claim_id": "CLAIM-VT-001",
            "related_task": "TASK-VT-001",
            "claimed_status": "covered",
            "evidence_refs": ["EVIDENCE-VT-001"],
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]


def _minimal_evidence_index() -> dict:
    """Return a minimal valid evidence_index document."""
    return {
        "run_id": "run-001",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-01-01T00:00:00Z",
        "evidences": [
            {
                "evidence_id": "EVIDENCE-VT-001",
                "source_type": "test",
                "source_path": "tests/test_foo.py",
                "covers": ["AC-VT-001-01"],
                "status": "covered",
            }
        ],
    }


def _minimal_traceability_report() -> dict:
    """Return a minimal valid traceability_report document."""
    return {
        "run_id": "run-001",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-01-01T00:00:00Z",
        "gate_decision": "pass",
        "requirement_coverage": [
            {
                "req_id": "REQ-VT-001",
                "status": "covered",
                "evidence_ids": ["EVIDENCE-VT-001"],
            }
        ],
        "gaps": [],
        "risks": [
            {
                "risk_id": "RISK-VT-001",
                "description": "Sample risk.",
                "severity": "should",
            }
        ],
    }


# ===========================================================================
# task_list.schema.json
# ===========================================================================


class TestTaskListSchema:
    """Tests for schemas/task_list.schema.json."""

    SCHEMA_NAME = "task_list.schema.json"

    def test_valid_minimal_document(self):
        """
        Validates that a minimal well-formed task_list document passes schema validation.
        Covers: AC-VT-001-01, AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        validate(instance=_minimal_task_list(), schema=schema)

    def test_missing_schema_version_raises(self):
        """
        Validates that omitting 'schema_version' causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_task_list()
        del doc["schema_version"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_project_raises(self):
        """
        Validates that omitting the 'project' object causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_task_list()
        del doc["project"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_tasks_raises(self):
        """
        Validates that omitting the 'tasks' array causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_task_list()
        del doc["tasks"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_project_id_raises(self):
        """
        Validates that omitting 'project.project_id' causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_task_list()
        del doc["project"]["project_id"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_task_required_field_raises(self):
        """
        Validates that omitting a required task field ('title') causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_task_list()
        del doc["tasks"][0]["title"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_priority_enum_raises(self):
        """
        Validates that an invalid 'priority' enum value causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_task_list()
        doc["tasks"][0]["priority"] = "nice-to-have"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_status_enum_raises(self):
        """
        Validates that an invalid 'status' enum value causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_task_list()
        doc["tasks"][0]["status"] = "pending"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_project_id_pattern_raises(self):
        """
        Validates that a malformed 'project_id' (wrong pattern) causes a ValidationError.
        Covers: AC-VT-002-01
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_task_list()
        doc["project"]["project_id"] = "PROJ-001"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_task_id_pattern_raises(self):
        """
        Validates that a malformed 'task_id' pattern causes a ValidationError.
        Covers: AC-VT-002-01
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_task_list()
        doc["tasks"][0]["task_id"] = "TASK-001"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_phase_id_pattern_raises(self):
        """
        Validates that a malformed 'phase_id' pattern causes a ValidationError.
        Covers: AC-VT-002-01
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_task_list()
        doc["tasks"][0]["phase_id"] = "PHASE-01"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_related_requirement_pattern_raises(self):
        """
        Validates that a malformed requirement ID in 'related_requirements' causes a ValidationError.
        Covers: AC-VT-002-01
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_task_list()
        doc["tasks"][0]["related_requirements"] = ["REQ-001"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_ac_pattern_raises(self):
        """
        Validates that a malformed AC ID in 'related_acceptance_criteria' causes a ValidationError.
        Covers: AC-VT-002-01
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_task_list()
        doc["tasks"][0]["related_acceptance_criteria"] = ["AC-001"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_dod_id_pattern_raises(self):
        """
        Validates that a malformed 'dod_id' pattern causes a ValidationError.
        Covers: AC-VT-002-01
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_task_list()
        doc["tasks"][0]["definition_of_done"][0]["dod_id"] = "DOD-001"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_dod_description_raises(self):
        """
        Validates that omitting 'description' from a DoD item causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_task_list()
        del doc["tasks"][0]["definition_of_done"][0]["description"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)


# ===========================================================================
# agent_claims.schema.json
# ===========================================================================


class TestAgentClaimsSchema:
    """Tests for schemas/agent_claims.schema.json."""

    SCHEMA_NAME = "agent_claims.schema.json"

    def test_valid_minimal_document(self):
        """
        Validates that a minimal well-formed agent_claims array passes schema validation.
        Covers: AC-VT-001-01, AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        validate(instance=_minimal_agent_claims(), schema=schema)

    def test_valid_document_with_optional_fields(self):
        """
        Validates that optional fields (code_refs, test_refs, notes) are accepted.
        Covers: AC-VT-001-01
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_agent_claims()
        doc[0]["code_refs"] = ["src/vibe_tracing/core/enums.py"]
        doc[0]["test_refs"] = ["tests/test_foo.py"]
        doc[0]["notes"] = "All good."
        validate(instance=doc, schema=schema)

    def test_missing_claim_id_raises(self):
        """
        Validates that omitting 'claim_id' causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_agent_claims()
        del doc[0]["claim_id"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_related_task_raises(self):
        """
        Validates that omitting 'related_task' causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_agent_claims()
        del doc[0]["related_task"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_claimed_status_raises(self):
        """
        Validates that omitting 'claimed_status' causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_agent_claims()
        del doc[0]["claimed_status"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_evidence_refs_raises(self):
        """
        Validates that omitting 'evidence_refs' causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_agent_claims()
        del doc[0]["evidence_refs"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_timestamp_raises(self):
        """
        Validates that omitting 'timestamp' causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_agent_claims()
        del doc[0]["timestamp"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_claimed_status_enum_raises(self):
        """
        Validates that an invalid 'claimed_status' enum value causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_agent_claims()
        doc[0]["claimed_status"] = "unknown"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_claim_id_pattern_raises(self):
        """
        Validates that a malformed 'claim_id' pattern causes a ValidationError.
        Covers: AC-VT-002-01
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_agent_claims()
        doc[0]["claim_id"] = "CLAIM-001"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_related_task_pattern_raises(self):
        """
        Validates that a malformed 'related_task' ID pattern causes a ValidationError.
        Covers: AC-VT-002-01
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_agent_claims()
        doc[0]["related_task"] = "TASK-001"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_top_level_must_be_array_raises(self):
        """
        Validates that a non-array top-level value causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        with pytest.raises(ValidationError):
            validate(instance={"claim_id": "CLAIM-VT-001"}, schema=schema)


# ===========================================================================
# evidence_index.schema.json
# ===========================================================================


class TestEvidenceIndexSchema:
    """Tests for schemas/evidence_index.schema.json."""

    SCHEMA_NAME = "evidence_index.schema.json"

    def test_valid_minimal_document(self):
        """
        Validates that a minimal well-formed evidence_index document passes schema validation.
        Covers: AC-VT-001-01, AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        validate(instance=_minimal_evidence_index(), schema=schema)

    def test_missing_run_id_raises(self):
        """
        Validates that omitting 'run_id' causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_evidence_index()
        del doc["run_id"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_project_id_raises(self):
        """
        Validates that omitting 'project_id' causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_evidence_index()
        del doc["project_id"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_scan_time_raises(self):
        """
        Validates that omitting 'scan_time' causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_evidence_index()
        del doc["scan_time"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_evidences_raises(self):
        """
        Validates that omitting 'evidences' causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_evidence_index()
        del doc["evidences"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_evidence_id_raises(self):
        """
        Validates that omitting 'evidence_id' from an evidence item causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_evidence_index()
        del doc["evidences"][0]["evidence_id"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_source_type_raises(self):
        """
        Validates that omitting 'source_type' from an evidence item causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_evidence_index()
        del doc["evidences"][0]["source_type"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_source_type_enum_raises(self):
        """
        Validates that an invalid 'source_type' enum value causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_evidence_index()
        doc["evidences"][0]["source_type"] = "document"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_evidence_status_enum_raises(self):
        """
        Validates that an invalid evidence 'status' enum value causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_evidence_index()
        doc["evidences"][0]["status"] = "unknown"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_project_id_pattern_raises(self):
        """
        Validates that a malformed 'project_id' pattern causes a ValidationError.
        Covers: AC-VT-002-01
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_evidence_index()
        doc["project_id"] = "VT-PROJECT"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_evidence_id_pattern_raises(self):
        """
        Validates that a malformed 'evidence_id' pattern causes a ValidationError.
        Covers: AC-VT-002-01
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_evidence_index()
        doc["evidences"][0]["evidence_id"] = "EV-001"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_empty_evidences_array_is_valid(self):
        """
        Validates that an empty 'evidences' array is accepted by the schema.
        Covers: AC-VT-001-01
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_evidence_index()
        doc["evidences"] = []
        validate(instance=doc, schema=schema)


# ===========================================================================
# traceability_report.schema.json
# ===========================================================================


class TestTraceabilityReportSchema:
    """Tests for schemas/traceability_report.schema.json."""

    SCHEMA_NAME = "traceability_report.schema.json"

    def test_valid_minimal_document(self):
        """
        Validates that a minimal well-formed traceability_report document passes schema validation.
        Covers: AC-VT-001-01, AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        validate(instance=_minimal_traceability_report(), schema=schema)

    def test_missing_run_id_raises(self):
        """
        Validates that omitting 'run_id' causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_traceability_report()
        del doc["run_id"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_project_id_raises(self):
        """
        Validates that omitting 'project_id' causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_traceability_report()
        del doc["project_id"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_scan_time_raises(self):
        """
        Validates that omitting 'scan_time' causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_traceability_report()
        del doc["scan_time"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_gate_decision_raises(self):
        """
        Validates that omitting 'gate_decision' causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_traceability_report()
        del doc["gate_decision"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_requirement_coverage_raises(self):
        """
        Validates that omitting 'requirement_coverage' causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_traceability_report()
        del doc["requirement_coverage"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_gaps_raises(self):
        """
        Validates that omitting 'gaps' causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_traceability_report()
        del doc["gaps"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_risks_raises(self):
        """
        Validates that omitting 'risks' causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_traceability_report()
        del doc["risks"]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_gate_decision_enum_raises(self):
        """
        Validates that an invalid 'gate_decision' enum value causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_traceability_report()
        doc["gate_decision"] = "warning"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_requirement_status_enum_raises(self):
        """
        Validates that an invalid 'status' in a requirement_coverage item causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_traceability_report()
        doc["requirement_coverage"][0]["status"] = "unknown"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_risk_severity_enum_raises(self):
        """
        Validates that an invalid 'severity' enum value in a risk causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_traceability_report()
        doc["risks"][0]["severity"] = "critical"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_project_id_pattern_raises(self):
        """
        Validates that a malformed 'project_id' pattern causes a ValidationError.
        Covers: AC-VT-002-01
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_traceability_report()
        doc["project_id"] = "PROJECT-001"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_req_id_pattern_raises(self):
        """
        Validates that a malformed 'req_id' pattern in requirement_coverage causes a ValidationError.
        Covers: AC-VT-002-01
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_traceability_report()
        doc["requirement_coverage"][0]["req_id"] = "REQ-001"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_invalid_risk_id_pattern_raises(self):
        """
        Validates that a malformed 'risk_id' pattern causes a ValidationError.
        Covers: AC-VT-002-01
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_traceability_report()
        doc["risks"][0]["risk_id"] = "RISK-001"
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_gap_required_field_raises(self):
        """
        Validates that omitting a required field in a gap item causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_traceability_report()
        doc["gaps"] = [{"item_id": "REQ-VT-999", "item_type": "requirement"}]
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)

    def test_missing_risk_required_field_raises(self):
        """
        Validates that omitting a required field in a risk item causes a ValidationError.
        Covers: AC-VT-001-02
        """
        schema = load_schema(self.SCHEMA_NAME)
        doc = _minimal_traceability_report()
        doc["risks"][0] = {"risk_id": "RISK-VT-001", "description": "No severity."}
        with pytest.raises(ValidationError):
            validate(instance=doc, schema=schema)
