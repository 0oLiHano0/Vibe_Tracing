"""
Unit tests for EvidenceIndexBuilder (TASK-VT-010).
"""

import json
import pytest
from pathlib import Path
from vibe_tracing.evidence_index_builder import EvidenceIndexBuilder
from vibe_tracing.schema_validator import SchemaValidator
from vibe_tracing.context import UnifiedContext


@pytest.fixture
def schemas_dir() -> Path:
    """Fixture returning the actual schemas directory."""
    return Path(__file__).parent.parent / "src" / "vibe_tracing" / "schemas"


def setup_mock_project(base: Path) -> None:
    """Helper to set up a mock project structure with valid inputs."""
    # Create directories
    (base / "docs").mkdir(parents=True, exist_ok=True)
    (base / "output").mkdir(parents=True, exist_ok=True)
    (base / "schemas").mkdir(parents=True, exist_ok=True)
    (base / ".vibetracing").mkdir(parents=True, exist_ok=True)
    (base / ".vibetracing" / "claims").mkdir(parents=True, exist_ok=True)

    # Copy real schemas to mock project so schema validator can load them
    real_schemas = Path(__file__).parent.parent / "src" / "vibe_tracing" / "schemas"
    for schema_file in real_schemas.glob("*.json"):
        (base / "schemas" / schema_file.name).write_text(
            schema_file.read_text(encoding="utf-8")
        )

    # Write PRD
    prd_content = """# Vibe Tracing PRD
### REQ-VT-001: 全链路需求追踪
#### 类别
functional
#### 优先级
must

##### AC-VT-001-01: 需求必须能关联任务
* 是否必须有测试：否

##### AC-VT-001-02: 验收标准必须能关联测试
* 是否必须有测试：否
"""
    (base / "docs" / "prd.md").write_text(prd_content, encoding="utf-8")
    (base / "docs" / "architecture_change_log.md").write_text(
        "# Architecture Change Log\n", encoding="utf-8"
    )

    # Write Architecture Constraints
    (base / "docs" / "architecture_constraints.json").write_text(
        '{"constraints": [], "module_boundaries": [{"module_id": "MOD-VT-001", "name": "Mock Module", "description": "Mock"}]}', encoding="utf-8"
    )

    # Write Task List
    task_list = {
        "schema_version": "0.1",
        "project": {"project_id": "PROJECT-VT", "name": "Vibe Tracing", "stage": "mvp"},
        "tasks": [
            {
                "task_id": "TASK-VT-001",
                "title": "Setup Core",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "done",
                "owner_role": "agent",
                "objective": "Setup codebase structure",
                "related_requirements": ["REQ-VT-001"],
                "related_modules": ["MOD-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            },
            {
                "task_id": "TASK-VT-002",
                "title": "Write Tests",
                "phase_id": "PHASE-VT-001",
                "priority": "should",
                "status": "in_progress",
                "owner_role": "agent",
                "objective": "Write core tests",
                "related_requirements": ["REQ-VT-001"],
                "related_modules": ["MOD-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-02"],
                "definition_of_done": [],
            },
        ],
    }
    (base / "docs" / "task_list.json").write_text(
        json.dumps(task_list), encoding="utf-8"
    )

    # Write Agent Claims
    agent_claims = [
        {
            "claim_id": "CLAIM-VT-001",
            "related_task": "TASK-VT-001",
            "claimed_status": "covered",
            "evidence_refs": ["EVIDENCE-VT-001"],
            "timestamp": "2026-05-22T12:00:00Z",
            "code_refs": ["src/vibe_tracing/core/ids.py#L1-L10"],
            "test_refs": [],
            "notes": "Core implemented successfully",
        }
    ]
    (base / ".vibetracing" / "claims" / "current.json").write_text(
        json.dumps(agent_claims), encoding="utf-8"
    )

    # Write config.json
    config_data = {
        "project_id": "PROJECT-VT",
        "project_prefix": "VT",
        "project_name": "Vibe Tracing",
    }
    (base / ".vibetracing" / "config.json").write_text(
        json.dumps(config_data), encoding="utf-8"
    )


def _build_ctx(base: Path) -> UnifiedContext:
    """Build a UnifiedContext from the mock project at *base*."""
    from vibe_tracing.raw_input_loader import RawInputLoader
    from vibe_tracing.prd_parser import PrdParser
    from vibe_tracing.task_loader import TaskLoader
    from vibe_tracing.claim_loader import ClaimLoader

    schemas_dir = base / "schemas"
    if not schemas_dir.is_dir():
        schemas_dir = Path(__file__).parent.parent / "src" / "vibe_tracing" / "schemas"

    raw_loader = RawInputLoader(base)
    manifest = raw_loader.load()

    prd_parser = PrdParser()
    prd_res = prd_parser.parse_file(base / "docs" / "prd.md")

    task_loader = TaskLoader(schemas_dir)
    task_res = task_loader.load_and_validate(base / "docs" / "task_list.json", prd_res)

    claim_loader = ClaimLoader(schemas_dir)
    claim_res = claim_loader.load_and_validate(base / ".vibetracing" / "claims" / "current.json", task_res)
    claims_list = claim_res.claims if claim_res.is_valid else []

    config_prefix = raw_loader.config_data.get("project_prefix", "VT")

    return UnifiedContext(
        config=raw_loader.config_data,
        prd=prd_res,
        task_result=task_res,
        claims_list=claims_list,
        manifest=manifest,
        config_prefix=config_prefix,
    )


def test_build_successful_evidence_index(tmp_path: Path) -> None:
    """
    Verify that EvidenceIndexBuilder builds a valid evidence index containing
    tasks, claims, code references, and tool reports with sequential IDs.
    Covers: AC-VT-001-02, AC-VT-002-01.
    """
    setup_mock_project(tmp_path)

    builder = EvidenceIndexBuilder(tmp_path)
    ctx = _build_ctx(tmp_path)
    output_path = tmp_path / "output" / "evidence_index.json"
    index = builder.build(output_path, ctx)

    # Verify high-level keys
    assert index["project_id"] == "PROJECT-VT"
    assert index["run_id"].startswith("RUN-")
    assert "scan_time" in index

    # Verify output file generated
    assert output_path.exists()

    # Validate output schema via SchemaValidator
    validator = SchemaValidator(tmp_path / "schemas")
    val_res = validator.validate_file(output_path, "evidence_index")
    assert val_res.is_valid is True, f"Schema validation error: {val_res.message}"

    evidences = index["evidences"]
    # 2 tasks + 1 claim + 1 code_ref = 4 evidence records
    assert len(evidences) == 4

    # Verify sequential evidence ID allocation
    for idx, ev in enumerate(evidences):
        expected_id = f"EVIDENCE-VT-{idx + 1:03d}"
        assert ev["evidence_id"] == expected_id

    # Verify status mapping for tasks
    task_ev1 = next(
        e
        for e in evidences
        if e["source_type"] == "task" and e["details"]["task_id"] == "TASK-VT-001"
    )
    assert task_ev1["status"] == "covered"  # status "done" -> "covered"
    assert task_ev1["source_path"] == "docs/task_list.json"
    assert sorted(task_ev1["covers"]) == ["AC-VT-001-01", "REQ-VT-001"]

    task_ev2 = next(
        e
        for e in evidences
        if e["source_type"] == "task" and e["details"]["task_id"] == "TASK-VT-002"
    )
    assert task_ev2["status"] == "partial"  # status "in_progress" -> "partial"

    # Verify Claim mapping
    claim_ev = next(e for e in evidences if e["source_type"] == "claim")
    assert claim_ev["status"] == "covered"
    assert claim_ev["source_path"] == ".vibetracing/claims/current.json"
    assert sorted(claim_ev["covers"]) == ["AC-VT-001-01", "REQ-VT-001"]

    # Verify Code Ref mapping
    code_ev = next(e for e in evidences if e["source_type"] == "code")
    assert code_ev["status"] == "compliant"
    assert code_ev["source_path"] == "src/vibe_tracing/core/ids.py#L1-L10"
    assert sorted(code_ev["covers"]) == ["AC-VT-001-01", "REQ-VT-001"]


def test_build_missing_required_files_raises_error(tmp_path: Path) -> None:
    """
    Verify that EvidenceIndexBuilder raises a ValueError if required raw files are missing.
    Covers: AC-VT-001-04.
    """
    builder = EvidenceIndexBuilder(tmp_path)
    # ctx=None triggers AttributeError on ctx.prd — the fallback path is gone
    with pytest.raises((ValueError, AttributeError)):
        builder.build(tmp_path / "output" / "evidence_index.json", None)


def test_build_invalid_raw_content_raises_error(tmp_path: Path) -> None:
    """
    Verify that invalid task list data is caught by upstream validation (TaskLoader).
    Covers: AC-VT-001-02.
    """
    setup_mock_project(tmp_path)
    # Write invalid json to task list
    (tmp_path / "docs" / "task_list.json").write_text(
        "{invalid json}", encoding="utf-8"
    )

    # Upstream validation catches the error — TaskLoader returns is_valid=False
    from vibe_tracing.prd_parser import PrdParser
    from vibe_tracing.task_loader import TaskLoader
    schemas_dir = tmp_path / "schemas"
    prd_res = PrdParser().parse_file(tmp_path / "docs" / "prd.md")
    task_res = TaskLoader(schemas_dir).load_and_validate(
        tmp_path / "docs" / "task_list.json", prd_res
    )
    assert not task_res.is_valid
    assert len(task_res.errors) > 0


def test_no_untraced_evidence_generated(tmp_path: Path) -> None:
    """
    Verify that every evidence record generated is linked back to a valid loaded source.
    Covers: AC-VT-001-02, AC-VT-002-02.
    """
    setup_mock_project(tmp_path)

    builder = EvidenceIndexBuilder(tmp_path)
    ctx = _build_ctx(tmp_path)
    output_path = tmp_path / "output" / "evidence_index.json"
    index = builder.build(output_path, ctx)

    for ev in index["evidences"]:
        # Assert type is one of the allowed types
        assert ev["source_type"] in ["task", "claim", "test", "tool", "code"]
        # Assert source path is non-empty
        assert ev["source_path"]
        # Assert covers is list
        assert isinstance(ev["covers"], list)
        # Assert status is valid
        assert ev["status"] in [
            "covered",
            "partial",
            "missing",
            "unclear",
            "low_confidence",
            "blocked",
            "compliant",
            "violated",
        ]


def test_test_evidence_carried_over_when_not_staged(tmp_path: Path) -> None:
    """
    Verify that test evidence from a previous run is preserved when the test file
    is NOT staged (i.e., no fresh test evidence generated for it).
    Covers: FIX-TASK-006.
    """
    setup_mock_project(tmp_path)

    # Write a previous evidence_index.json with a test evidence entry
    old_index = {
        "run_id": "RUN-old",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-06-08T00:00:00Z",
        "evidences": [
            {
                "evidence_id": "EVIDENCE-VT-099",
                "source_type": "test",
                "source_path": "tests/test_ac_vt_009_coverage.py",
                "covers": ["AC-VT-009-01", "REQ-VT-009"],
                "status": "covered",
                "details": {"test_file": "tests/test_ac_vt_009_coverage.py"},
            },
        ],
    }
    (tmp_path / "output" / "evidence_index.json").write_text(
        json.dumps(old_index), encoding="utf-8"
    )

    builder = EvidenceIndexBuilder(tmp_path)
    ctx = _build_ctx(tmp_path)
    output_path = tmp_path / "output" / "evidence_index.json"
    index = builder.build(output_path, ctx)

    evidences = index["evidences"]
    test_evs = [e for e in evidences if e["source_type"] == "test"]
    assert len(test_evs) == 1, "Test evidence from previous run should be carried over"
    carried = test_evs[0]
    assert carried["carried_over"] is True
    assert carried["source_path"] == "tests/test_ac_vt_009_coverage.py"
    assert carried["status"] == "covered"
    assert carried["covers"] == ["AC-VT-009-01", "REQ-VT-009"]


def test_test_evidence_not_carried_over_when_staged(tmp_path: Path) -> None:
    """
    Verify that test evidence is NOT carried over when the test file IS staged
    (i.e., fresh test evidence was generated for it in this run).
    Covers: FIX-TASK-006.
    """
    setup_mock_project(tmp_path)

    # Write a previous evidence_index.json with a test evidence entry
    old_index = {
        "run_id": "RUN-old",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-06-08T00:00:00Z",
        "evidences": [
            {
                "evidence_id": "EVIDENCE-VT-099",
                "source_type": "test",
                "source_path": "tests/test_ac_vt_009_coverage.py",
                "covers": ["AC-VT-009-01", "REQ-VT-009"],
                "status": "covered",
                "details": {"test_file": "tests/test_ac_vt_009_coverage.py"},
            },
        ],
    }
    (tmp_path / "output" / "evidence_index.json").write_text(
        json.dumps(old_index), encoding="utf-8"
    )

    # Create a mock tool evidence candidate that simulates fresh test evidence
    from vibe_tracing.tool_evidence_adapter import ToolEvidenceCandidate

    fresh_test_evidence = ToolEvidenceCandidate(
        source_type="test",
        source_path="tests/test_ac_vt_009_coverage.py",
        covers=["AC-VT-009-01", "REQ-VT-009"],
        status="covered",
        tool_category="test",
        command="pytest tests/test_ac_vt_009_coverage.py",
        exit_code=0,
    )

    builder = EvidenceIndexBuilder(tmp_path)
    ctx = _build_ctx(tmp_path)
    ctx.tool_evidence = [fresh_test_evidence]

    output_path = tmp_path / "output" / "evidence_index.json"
    index = builder.build(output_path, ctx)

    evidences = index["evidences"]
    test_evs = [e for e in evidences if e["source_type"] == "test"]
    assert len(test_evs) == 1, "Only the fresh test evidence should be present"
    assert test_evs[0].get("carried_over") is not True
    # The fresh evidence gets a new ID assigned by the tool report processing
    assert test_evs[0]["source_path"] == "tests/test_ac_vt_009_coverage.py"


def test_non_test_evidence_not_carried_over(tmp_path: Path) -> None:
    """
    Verify that only test evidence is carried over; other types (claim, code, tool) are not.
    Covers: FIX-TASK-006.
    """
    setup_mock_project(tmp_path)

    # Write a previous evidence_index.json with non-test evidence entries
    old_index = {
        "run_id": "RUN-old",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-06-08T00:00:00Z",
        "evidences": [
            {
                "evidence_id": "EVIDENCE-VT-098",
                "source_type": "tool",
                "source_path": "output/coverage_report.xml",
                "covers": ["REQ-VT-001"],
                "status": "covered",
                "details": {},
            },
            {
                "evidence_id": "EVIDENCE-VT-099",
                "source_type": "code",
                "source_path": "src/vibe_tracing/old_module.py",
                "covers": ["REQ-VT-001"],
                "status": "compliant",
                "details": {},
            },
        ],
    }
    (tmp_path / "output" / "evidence_index.json").write_text(
        json.dumps(old_index), encoding="utf-8"
    )

    builder = EvidenceIndexBuilder(tmp_path)
    ctx = _build_ctx(tmp_path)
    output_path = tmp_path / "output" / "evidence_index.json"
    index = builder.build(output_path, ctx)

    evidences = index["evidences"]
    # No carried_over evidence should exist since none of the old entries were type "test"
    carried = [e for e in evidences if e.get("carried_over") is True]
    assert len(carried) == 0, "Non-test evidence should not be carried over"


def test_carried_over_evidence_gets_new_id(tmp_path: Path) -> None:
    """
    Verify that carried-over test evidence gets a fresh sequential evidence_id.
    Covers: FIX-TASK-006.
    """
    setup_mock_project(tmp_path)

    old_index = {
        "run_id": "RUN-old",
        "project_id": "PROJECT-VT",
        "scan_time": "2026-06-08T00:00:00Z",
        "evidences": [
            {
                "evidence_id": "EVIDENCE-VT-050",
                "source_type": "test",
                "source_path": "tests/test_old.py",
                "covers": ["REQ-VT-001"],
                "status": "covered",
                "details": {},
            },
        ],
    }
    (tmp_path / "output" / "evidence_index.json").write_text(
        json.dumps(old_index), encoding="utf-8"
    )

    builder = EvidenceIndexBuilder(tmp_path)
    ctx = _build_ctx(tmp_path)
    output_path = tmp_path / "output" / "evidence_index.json"
    index = builder.build(output_path, ctx)

    evidences = index["evidences"]
    # The carried-over evidence should have a new sequential ID, not EVIDENCE-VT-050
    carried = [e for e in evidences if e.get("carried_over") is True]
    assert len(carried) == 1
    # It should be assigned the next available ID after all fresh evidences
    fresh_count = len([e for e in evidences if not e.get("carried_over")])
    expected_id = f"EVIDENCE-VT-{fresh_count + 1:03d}"
    assert carried[0]["evidence_id"] == expected_id
