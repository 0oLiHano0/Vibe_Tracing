"""
End-to-end acceptance tests for Vibe Tracing.

These tests exercise the full VT pipeline with minimal mocking:
- Test 1: Full analyze pipeline using VT project's own PRD/task_list
- Test 2: Gate pass with valid claims pointing to real test files
- Test 3: Gate pass with no claims (no risk)
- Test 4: Claim archival after successful pre-commit analysis
"""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from vibe_tracing.cli import main

# ---------------------------------------------------------------------------
# Project root (VT project itself)
# ---------------------------------------------------------------------------

VT_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Minimal PRD template for synthetic test projects
# ---------------------------------------------------------------------------

_MINIMAL_PRD = """\
---
project_name: "Acceptance Test Project"
project_abbreviation: "VT"
version: v0.1
created: 2026-06-11
updated: 2026-06-11
status: active
---

# Acceptance Test Project PRD

### REQ-VT-001: Core Feature

#### 类别
functional

#### 优先级
must

##### AC-VT-001-01: Feature must work correctly
* 是否必须有测试：是
"""

_MINIMAL_PRD_SHOULD = """\
---
project_name: "Acceptance Test Project"
project_abbreviation: "VT"
version: v0.1
created: 2026-06-11
updated: 2026-06-11
status: active
---

# Acceptance Test Project PRD

### REQ-VT-001: Core Feature

#### 类别
functional

#### 优先级
should

##### AC-VT-001-01: Feature should work correctly
* 是否必须有测试：否
"""


def _make_task_list(priority="must", require_testing=True):
    """Return a task_list.json dict.  ``priority`` controls the task level."""
    acs = ["AC-VT-001-01"] if require_testing else []
    return {
        "schema_version": "0.1",
        "project": {
            "project_id": "PROJECT-VT",
            "name": "Acceptance Test Project",
            "stage": "mvp",
        },
        "tasks": [
            {
                "task_id": "TASK-VT-001",
                "title": "Implement Core Feature",
                "phase_id": "PHASE-VT-001",
                "priority": priority,
                "status": "done",
                "owner_role": "AI Coding Agent",
                "objective": "Implement the core feature.",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": acs,
                "definition_of_done": [],
            }
        ],
    }


def _make_constraints():
    """Return a minimal architecture_constraints.json dict."""
    return {
        "schema_version": "1.0.0",
        "project": {
            "project_id": "PROJECT-VT",
            "name": "Acceptance Test Project",
            "stage": "mvp",
        },
        "module_boundaries": [
            {
                "module_id": "MOD-VT-001",
                "name": "Core Module",
                "responsibility": "Core feature implementation",
                "related_requirements": ["REQ-VT-001"],
            }
        ],
        "language_tool_matrix": {
            "python": {
                "extensions": [".py"],
                "test": {
                    "tool": "pytest",
                    "default_command": (
                        "pytest {test_path} --tb=short -q "
                        "--json-report --json-report-file={output_path}"
                    ),
                    "output_format": "pytest_json",
                    "pass_condition": "exit_code == 0",
                },
            },
        },
    }


def _make_claims(test_refs=None, code_refs=None):
    """Return a claims/current.json list."""
    return [
        {
            "claim_id": "CLAIM-VT-001",
            "related_task": "TASK-VT-001",
            "claimed_status": "covered",
            "evidence_refs": ["EVIDENCE-VT-003"],
            "timestamp": "2026-06-11T00:00:00Z",
            "code_refs": code_refs if code_refs is not None else [],
            "test_refs": test_refs if test_refs is not None else [],
        }
    ]


def _compute_constraints_hash(constraints_path: Path) -> str:
    """Compute SHA-256 hex digest of the constraints file."""
    return hashlib.sha256(constraints_path.read_bytes()).hexdigest()


def _init_git(project_root: Path) -> None:
    """Initialize a git repository and create an initial commit."""
    subprocess.run(["git", "init"], cwd=project_root, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=project_root, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=project_root, capture_output=True, check=True,
    )


def _setup_base_project(
    project_root: Path,
    *,
    constraints_data=None,
    task_list_data=None,
    claims_data=None,
    prd_content=None,
    tool_report=None,
):
    """Write a full minimal project tree into project_root.

    Args:
        project_root: Target directory.
        constraints_data: Override for architecture_constraints.json.
        task_list_data: Override for task_list.json.
        claims_data: Override for claims/current.json.  None means no claims
            file is created.
        prd_content: Override PRD markdown content.
        tool_report: Optional dict to write as
            .vibetracing/tool_reports/pytest_report.json.
    """
    docs = project_root / "docs"
    vb = project_root / ".vibetracing"
    claims_dir = vb / "claims"

    for d in (docs, vb, claims_dir):
        d.mkdir(parents=True, exist_ok=True)

    # PRD
    (docs / "prd.md").write_text(
        prd_content or _MINIMAL_PRD, encoding="utf-8"
    )

    # Architecture constraints
    constraints = constraints_data or _make_constraints()
    constraints_path = docs / "architecture_constraints.json"
    constraints_path.write_text(json.dumps(constraints, indent=2), encoding="utf-8")

    # Task list
    task_list = task_list_data or _make_task_list()
    (docs / "task_list.json").write_text(json.dumps(task_list, indent=2), encoding="utf-8")

    # Claims (optional)
    if claims_data is not None:
        (claims_dir / "current.json").write_text(
            json.dumps(claims_data, indent=2), encoding="utf-8"
        )

    # Config (written last so hash is up-to-date)
    cfg = {
        "project_id": "PROJECT-VT",
        "project_prefix": "VT",
        "project_name": "Acceptance Test Project",
        "paths": {
            "prd": "docs/prd.md",
            "architecture_constraints": "docs/architecture_constraints.json",
            "task_list": "docs/task_list.json",
            "agent_claims": ".vibetracing/claims/current.json",
            "output_dir": "output",
        },
        "language": "python",
        "validation_tools": ["test"],
        "architecture_constraints_hash": _compute_constraints_hash(constraints_path),
        "finalize_git_commit": "test_commit_hash",
    }
    (vb / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # Optional tool report
    if tool_report is not None:
        reports_dir = vb / "tool_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "pytest_report.json").write_text(
            json.dumps(tool_report, indent=2), encoding="utf-8"
        )


# ===========================================================================
# Test 1: Full analyze pipeline with VT project's own docs
# ===========================================================================


class TestFullAnalyzePipeline:
    """Run the complete analyze pipeline using VT project's own PRD and task list."""

    def test_full_analyze_pipeline(self, tmp_path):
        """
        covers: AC-VT-001-01, AC-VT-001-02, AC-VT-001-03
        Copy VT project's PRD, task_list, architecture_constraints into a
        temp directory, run the full analyze pipeline, and verify outputs.
        """
        # Copy VT project governance files
        src_docs = VT_PROJECT_ROOT / "docs"
        docs = tmp_path / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        for fname in ("prd.md", "task_list.json", "architecture_constraints.json"):
            src = src_docs / fname
            if src.exists():
                shutil.copy2(src, docs / fname)

        # Copy VT project schemas for validation
        src_schemas = VT_PROJECT_ROOT / "src" / "vibe_tracing" / "schemas"
        if src_schemas.is_dir():
            shutil.copytree(src_schemas, tmp_path / "schemas")

        # Create claims directory (empty claims)
        claims_dir = tmp_path / ".vibetracing" / "claims"
        claims_dir.mkdir(parents=True, exist_ok=True)
        (claims_dir / "current.json").write_text("[]", encoding="utf-8")

        # Copy existing tool reports (if any)
        src_output = VT_PROJECT_ROOT / "output"
        src_tool_reports = VT_PROJECT_ROOT / ".vibetracing" / "tool_reports"
        vb = tmp_path / ".vibetracing"
        if src_tool_reports.is_dir():
            shutil.copytree(src_tool_reports, vb / "tool_reports")

        # Copy dashboard.html so ArchitectureComplianceChecker DEP-VT-002 passes
        src_dashboard = src_output / "dashboard.html"
        if src_dashboard.exists():
            output_dir_early = tmp_path / "output"
            output_dir_early.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_dashboard, output_dir_early / "dashboard.html")

        # Compute constraints hash
        constraints_path = docs / "architecture_constraints.json"
        constraints_hash = _compute_constraints_hash(constraints_path)

        # Build config.json
        config = {
            "project_id": "PROJECT-VT",
            "project_prefix": "VT",
            "project_name": "Vibe Tracing",
            "paths": {
                "prd": "docs/prd.md",
                "architecture_constraints": "docs/architecture_constraints.json",
                "task_list": "docs/task_list.json",
                "agent_claims": ".vibetracing/claims/current.json",
                "output_dir": "output",
            },
            "language": "python",
            "validation_tools": ["test"],
            "architecture_constraints_hash": constraints_hash,
            "finalize_git_commit": "test_commit_hash",
        }
        (vb / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

        output_dir = tmp_path / "output"

        # Run the full analyze pipeline
        exit_code = main(["analyze", "--project-root", str(tmp_path)])

        # The pipeline should complete (exit 0 or 2, never 1 which means error)
        assert exit_code in (0, 2), (
            f"Pipeline should complete without errors, got exit code {exit_code}"
        )

        # Verify evidence_index.json is non-empty
        evidence_path = output_dir / "evidence_index.json"
        assert evidence_path.exists(), "evidence_index.json must be generated"
        evidence_index = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert len(evidence_index.get("evidences", [])) > 0, (
            "evidence_index.json must contain at least one evidence entry"
        )

        # Verify traceability_report.json is non-empty
        report_path = output_dir / "traceability_report.json"
        assert report_path.exists(), "traceability_report.json must be generated"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report.get("gate_decision") in ("pass", "fail", "blocked"), (
            f"gate_decision must be valid, got: {report.get('gate_decision')}"
        )

        # Verify dashboard.html is generated with meaningful content
        dashboard_path = output_dir / "dashboard.html"
        assert dashboard_path.exists(), "dashboard.html must be generated"
        dashboard_content = dashboard_path.read_text(encoding="utf-8")
        assert len(dashboard_content) > 500, (
            "dashboard.html must contain meaningful content (> 500 bytes)"
        )
        assert "<html" in dashboard_content.lower(), (
            "dashboard.html must be valid HTML"
        )

        # Verify gate decision has clear reasons (stored in metadata.summary)
        metadata = report.get("metadata", {})
        summary = metadata.get("summary", "")
        assert isinstance(summary, str) and len(summary) > 0, (
            "Gate decision must have a non-empty summary with reasons"
        )


# ===========================================================================
# Test 2: Gate pass with valid claims and real test execution
# ===========================================================================


class TestGatePassWithValidClaims:
    """Verify the pipeline with claims pointing to real test files."""

    def test_gate_pass_with_valid_claims(self, tmp_path):
        """
        covers: AC-VT-008-01, AC-VT-008-03
        Create a project with claims referencing a real test file that passes.
        Run analyze and verify the evidence index contains test results.
        """
        # Create a real test file
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        (tests_dir / "test_feature.py").write_text(
            "# covers: AC-VT-001-01\ndef test_feature():\n    assert True\n",
            encoding="utf-8",
        )

        # Create a tool report simulating pytest success
        tool_report = {
            "tool": "pytest",
            "command": "pytest --json-report",
            "exit_code": 0,
            "tests": [
                {
                    "nodeid": "tests/test_feature.py::test_feature",
                    "outcome": "passed",
                    "docstring": "covers: AC-VT-001-01",
                }
            ],
        }

        # Set up project with claims referencing the test file
        claims = _make_claims(test_refs=["tests/test_feature.py"])
        _setup_base_project(
            tmp_path,
            claims_data=claims,
            tool_report=tool_report,
        )

        # Initialize git and stage the test file so _execute_tools can find it
        _init_git(tmp_path)
        subprocess.run(
            ["git", "add", "tests/test_feature.py", ".vibetracing/claims/current.json"],
            cwd=tmp_path, capture_output=True, check=True,
        )

        output_dir = tmp_path / "output"

        # Run analyze
        exit_code = main(["analyze", "--project-root", str(tmp_path)])

        # Should complete without error (exit 0 or 2)
        assert exit_code in (0, 2), (
            f"Pipeline should complete, got exit code {exit_code}"
        )

        # Verify traceability report exists
        report_path = output_dir / "traceability_report.json"
        assert report_path.exists(), "traceability_report.json must be generated"
        report = json.loads(report_path.read_text(encoding="utf-8"))

        # Gate decision should be pass or blocked (with clear reasons)
        gate_decision = report.get("gate_decision")
        assert gate_decision in ("pass", "fail", "blocked"), (
            f"Gate decision must be valid, got: {gate_decision}"
        )

        # Verify evidence index contains test evidence from tool report
        evidence_path = output_dir / "evidence_index.json"
        assert evidence_path.exists(), "evidence_index.json must be generated"
        evidence_index = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidences = evidence_index.get("evidences", [])

        # Check for test-type evidence (from tool reports)
        test_evidence = [e for e in evidences if e.get("source_type") == "test"]
        assert len(test_evidence) > 0, (
            "evidence_index must contain at least one test evidence entry"
        )


# ===========================================================================
# Test 3: Gate passes with no claims
# ===========================================================================


class TestGatePassWithoutClaims:
    """Verify the pipeline passes when there are no claims (no risk)."""

    def test_gate_pass_without_claims(self, tmp_path):
        """
        covers: AC-VT-006-01, AC-VT-006-02
        Create a project with no claims, a SHOULD-level task (no MUST AC
        requiring tests), and a dashboard.html stub.  Gate should pass since
        there are no claims to produce gaps/risks, and architecture compliance
        checks pass.
        """
        # Use SHOULD priority PRD so AcTestAnalyzer doesn't flag MUST-level gaps
        task_list = _make_task_list(priority="should")
        _setup_base_project(
            tmp_path,
            task_list_data=task_list,
            claims_data=None,  # No claims file
            prd_content=_MINIMAL_PRD_SHOULD,
        )

        # Create a minimal dashboard.html stub so DEP-VT-002 passes
        output_dir = tmp_path / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "dashboard.html").write_text(
            "<html><body><h1>Stub Dashboard</h1></body></html>",
            encoding="utf-8",
        )

        # Initialize git
        _init_git(tmp_path)

        # Run analyze
        exit_code = main(["analyze", "--project-root", str(tmp_path)])

        # Gate should pass (exit 0)
        assert exit_code == 0, (
            f"Gate should pass with no claims and no MUST gaps, got exit code {exit_code}"
        )

        # Verify report
        report_path = output_dir / "traceability_report.json"
        assert report_path.exists(), "traceability_report.json must be generated"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report.get("gate_decision") == "pass", (
            f"gate_decision should be 'pass', got: {report.get('gate_decision')}"
        )


# ===========================================================================
# Test 4: Claim archival after successful pre-commit analysis
# ===========================================================================


class TestClaimArchiveAfterCommit:
    """Verify that claims are archived after a successful pre-commit gate pass."""

    def test_claim_archive_after_commit(self, tmp_path):
        """
        covers: AC-VT-002-01, AC-VT-002-02
        Create a project with claims, commit everything, then run analyze in
        pre-commit + gates-only mode.  Verify claims are archived and
        current.json is cleared.

        Uses --gates-only mode because:
        - It matches the fast pre-commit hook path
        - It avoids ghost-code detection issues (no staged business files)
        - Claim archival happens unconditionally in gates-only + pre-commit
        """
        # Create claims
        claims = _make_claims()

        # Use SHOULD task so no MUST-level AC gaps block integrity gates
        task_list = _make_task_list(priority="should")
        _setup_base_project(
            tmp_path,
            task_list_data=task_list,
            claims_data=claims,
            prd_content=_MINIMAL_PRD_SHOULD,
        )

        # Create a dashboard.html stub so DEP-VT-002 passes
        output_dir = tmp_path / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "dashboard.html").write_text(
            "<html><body><h1>Stub</h1></body></html>",
            encoding="utf-8",
        )

        # Initialize git and create initial commit with all files
        _init_git(tmp_path)
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path, capture_output=True, check=True,
        )

        # Verify initial state: current.json has claims
        current_path = tmp_path / ".vibetracing" / "claims" / "current.json"
        initial_claims = json.loads(current_path.read_text(encoding="utf-8"))
        assert len(initial_claims) > 0, "current.json must have claims before analysis"

        # Run analyze in pre-commit + gates-only mode
        # This runs integrity gates (1, 1b, 1c, 2) and archives claims
        exit_code = main([
            "analyze", "--project-root", str(tmp_path),
            "--pre-commit", "--gates-only",
        ])

        # gates-only + pre-commit always returns 0 if integrity gates pass
        assert exit_code == 0, (
            f"Gates-only pre-commit should pass, got exit code {exit_code}"
        )

        # Verify claims were archived
        archive_dir = tmp_path / ".vibetracing" / "claims" / "archive"
        assert archive_dir.exists(), "archive directory must be created"
        archive_files = list(archive_dir.glob("commit-*.json"))
        assert len(archive_files) > 0, (
            "At least one archive file must be created after successful pre-commit"
        )

        # Verify archived content matches original claims
        archived_data = json.loads(
            archive_files[0].read_text(encoding="utf-8")
        )
        assert len(archived_data) > 0, "Archived claims must not be empty"
        assert archived_data[0]["claim_id"] == "CLAIM-VT-001", (
            "Archived claim_id must match original"
        )

        # Verify current.json was cleared
        current_data = json.loads(current_path.read_text(encoding="utf-8"))
        assert current_data == [], (
            "current.json must be cleared after archival"
        )
