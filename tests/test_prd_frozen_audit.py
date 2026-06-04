"""
Tests for PRD frozen state audit and drift detection (TASK-VT-039).
"""

import json
from pathlib import Path
import pytest
from vibe_tracing.cli import main


@pytest.fixture(autouse=True)
def setup_mock_config(tmp_path):
    (tmp_path / ".vibetracing").mkdir(parents=True, exist_ok=True)
    config_data = {
        "project_id": "PROJECT-VT",
        "project_prefix": "VT",
        "project_name": "Vibe Tracing",
        "language": "python",
        "validation_tools": ["test"],
        "architecture_constraints_hash": "dummy_hash",
        "finalize_git_commit": "abc123deadbeef",
        "finalize_constraints_path": "docs/architecture_constraints.json",
    }
    (tmp_path / ".vibetracing" / "config.json").write_text(
        json.dumps(config_data, indent=2), encoding="utf-8"
    )


def test_analyze_frozen_missing_baseline(tmp_path, capsys):
    """
    covers: AC-VT-009-07
    Verify that if PRD status is 'frozen' but the baseline PRD file is missing,
    a MUST severity risk is raised, blocking the merge gate.
    """
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    (tmp_path / "schemas").mkdir(parents=True, exist_ok=True)

    # Copy real schemas to mock project
    real_schemas = Path(__file__).parent.parent / "src" / "vibe_tracing" / "schemas"
    for schema_file in real_schemas.glob("*.json"):
        (tmp_path / "schemas" / schema_file.name).write_text(
            schema_file.read_text(encoding="utf-8"), encoding="utf-8"
        )

    # Write frozen PRD
    prd_content = """---
status: frozen
---
# Vibe Tracing PRD
## 0. 文档信息
- 当前状态：frozen

## 3. 功能需求
### REQ-VT-001：样例需求
#### 优先级
must
##### AC-VT-001-01：样例验收标准
是否必须有测试：否
"""
    (docs_dir / "prd.md").write_text(prd_content, encoding="utf-8")

    # Write valid task_list.json covering REQ-VT-001
    task_list = {
        "schema_version": "1.0.0",
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
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [
                    {
                        "dod_id": "DOD-VT-001-01",
                        "description": "Code compiles"
                    }
                ],
            }
        ]
    }
    (docs_dir / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
    (docs_dir / "architecture_constraints.json").write_text(
        '{"schema_version": "1.0.0", "project": {"project_id": "PROJECT-VT", "name": "VT", "stage": "mvp"}, "quality_gates": []}',
        encoding="utf-8"
    )

    # Run analyze command
    exit_code = main(["analyze", "--project-root", str(tmp_path)])
    assert exit_code == 2

    # Check report contents
    report_path = tmp_path / "output" / "traceability_report.json"
    assert report_path.is_file()
    with report_path.open("r", encoding="utf-8") as f:
        report_data = json.load(f)
    assert report_data["gate_decision"] == "blocked"
    
    # Must contain RISK-VT-901
    risks = report_data["risks"]
    assert any(r["risk_id"] == "RISK-VT-901" for r in risks)


def test_analyze_frozen_invalid_baseline(tmp_path):
    """
    covers: AC-VT-009-07
    Verify that if the baseline PRD is present but invalid, a MUST severity risk is raised.
    """
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    vt_dir = tmp_path / ".vibetracing"
    vt_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    (tmp_path / "schemas").mkdir(parents=True, exist_ok=True)

    real_schemas = Path(__file__).parent.parent / "src" / "vibe_tracing" / "schemas"
    for schema_file in real_schemas.glob("*.json"):
        (tmp_path / "schemas" / schema_file.name).write_text(
            schema_file.read_text(encoding="utf-8"), encoding="utf-8"
        )

    # Write frozen PRD
    prd_content = """---
status: frozen
---
# Vibe Tracing PRD
## 0. 文档信息
- 当前状态：frozen

## 3. 功能需求
### REQ-VT-001：样例需求
#### 优先级
must
##### AC-VT-001-01：样例验收标准
是否必须有测试：否
"""
    (docs_dir / "prd.md").write_text(prd_content, encoding="utf-8")

    # Write invalid baseline (syntax error: missing required Priority heading under REQ)
    invalid_baseline = """---
status: frozen
---
# Vibe Tracing PRD
## 0. 文档信息
- 当前状态：frozen

## 3. 功能需求
### REQ-VT-001：样例需求
(Missing priority heading)
"""
    (vt_dir / "prd.base.md").write_text(invalid_baseline, encoding="utf-8")

    # Write valid task_list.json & constraints covering REQ-VT-001
    task_list = {
        "schema_version": "1.0.0",
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
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [
                    {
                        "dod_id": "DOD-VT-001-01",
                        "description": "Code compiles"
                    }
                ],
            }
        ]
    }
    (docs_dir / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
    (docs_dir / "architecture_constraints.json").write_text(
        '{"schema_version": "1.0.0", "project": {"project_id": "PROJECT-VT", "name": "VT", "stage": "mvp"}, "quality_gates": []}',
        encoding="utf-8"
    )

    exit_code = main(["analyze", "--project-root", str(tmp_path)])
    assert exit_code == 2

    report_path = tmp_path / "output" / "traceability_report.json"
    with report_path.open("r", encoding="utf-8") as f:
        report_data = json.load(f)
    assert report_data["gate_decision"] == "blocked"
    assert any(r["risk_id"] == "RISK-VT-902" for r in report_data["risks"])


def test_analyze_frozen_drift_block_and_resolve(tmp_path):
    """
    covers: AC-VT-009-07
    Verify that if there is requirement drift without documentation in architecture_change_log.md,
    a MUST risk blocks the gate. Adding the ID to architecture_change_log.md resolves the block.
    """
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    vt_dir = tmp_path / ".vibetracing"
    vt_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    (tmp_path / "schemas").mkdir(parents=True, exist_ok=True)

    real_schemas = Path(__file__).parent.parent / "src" / "vibe_tracing" / "schemas"
    for schema_file in real_schemas.glob("*.json"):
        (tmp_path / "schemas" / schema_file.name).write_text(
            schema_file.read_text(encoding="utf-8"), encoding="utf-8"
        )

    # 1. Write current PRD (with REQ-VT-002 modified / added compared to base)
    prd_content = """---
status: frozen
---
# Vibe Tracing PRD
## 0. 文档信息
- 当前状态：frozen

## 3. 功能需求
### REQ-VT-001：原需求
#### 优先级
must
##### AC-VT-001-01：验收标准1
是否必须有测试：否

### REQ-VT-002：新增需求
#### 优先级
should
##### AC-VT-002-01：验收标准2
是否必须有测试：否
"""
    (docs_dir / "prd.md").write_text(prd_content, encoding="utf-8")

    # 2. Write baseline PRD (only has REQ-VT-001)
    base_content = """---
status: frozen
---
# Vibe Tracing PRD
## 0. 文档信息
- 当前状态：frozen

## 3. 功能需求
### REQ-VT-001：原需求
#### 优先级
must
##### AC-VT-001-01：验收标准1
是否必须有测试：否
"""
    (vt_dir / "prd.base.md").write_text(base_content, encoding="utf-8")

    # Write valid task_list.json covering both requirements to avoid "missing task" risks
    task_list = {
        "schema_version": "1.0.0",
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
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [
                    {
                        "dod_id": "DOD-VT-001-01",
                        "description": "Code compiles"
                    }
                ],
            },
            {
                "task_id": "TASK-VT-002",
                "title": "Implement REQ-VT-002",
                "phase_id": "PHASE-VT-001",
                "priority": "should",
                "status": "done",
                "owner_role": "agent",
                "objective": "Implement REQ-VT-002",
                "related_requirements": ["REQ-VT-002"],
                "related_acceptance_criteria": ["AC-VT-002-01"],
                "definition_of_done": [
                    {
                        "dod_id": "DOD-VT-002-01",
                        "description": "Done"
                    }
                ],
            }
        ]
    }
    (docs_dir / "task_list.json").write_text(json.dumps(task_list), encoding="utf-8")
    (docs_dir / "architecture_constraints.json").write_text(
        '{"schema_version": "1.0.0", "project": {"project_id": "PROJECT-VT", "name": "VT", "stage": "mvp"}, "quality_gates": []}',
        encoding="utf-8"
    )

    # An empty architecture change log
    (docs_dir / "architecture_change_log.md").write_text("# Change Log\n", encoding="utf-8")

    # First run: should be BLOCKED because REQ-VT-002 and AC-VT-002-01 are undocumented drift
    exit_code = main(["analyze", "--project-root", str(tmp_path)])
    assert exit_code == 2

    report_path = tmp_path / "output" / "traceability_report.json"
    with report_path.open("r", encoding="utf-8") as f:
        report_data = json.load(f)
    assert report_data["gate_decision"] == "blocked"
    # Risks should flag REQ-VT-002 and/or AC-VT-002-01
    assert any("REQ-VT-002" in r["description"] for r in report_data["risks"])
    assert any("AC-VT-002-01" in r["description"] for r in report_data["risks"])

    # 3. Write documentation to architecture_change_log.md
    log_content = """# Change Log
- REQ-VT-002: Added new requirement for draft state
- AC-VT-002-01: Associated AC
"""
    (docs_dir / "architecture_change_log.md").write_text(log_content, encoding="utf-8")

    # Second run: should be PASS/FAIL (conditional, not blocked) since drifts are documented
    exit_code = main(["analyze", "--project-root", str(tmp_path)])
    assert exit_code == 0

    with report_path.open("r", encoding="utf-8") as f:
        report_data = json.load(f)
    assert report_data["gate_decision"] in ("pass", "fail")
    # MUST risks from undocumented drifts should be gone
    assert not any(r["severity"] == "must" and ("REQ-VT-002" in r["description"] or "AC-VT-002-01" in r["description"]) for r in report_data["risks"])
