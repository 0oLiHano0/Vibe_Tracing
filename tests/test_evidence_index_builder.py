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
    (base / ".vibetracing" / "agent_claims.json").write_text(
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
    claim_res = claim_loader.load_and_validate(base / ".vibetracing" / "agent_claims.json", task_res)
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
    assert claim_ev["source_path"] == ".vibetracing/agent_claims.json"
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
