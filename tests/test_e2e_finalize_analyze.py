"""
End-to-end tests for the full boundary convergence workflow:
finalize -> analyze -> tool execution -> evidence generation (TASK-VT-043).

Each test simulates the complete workflow using mocked subprocess to avoid
requiring real tool installations.
"""

import json
import re
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vibe_tracing.cli import run_finalize, run_analyze


@pytest.fixture(autouse=True)
def mock_shutil_which(monkeypatch):
    """Mock shutil.which so the pre-flight dependency check passes
    even when tools like pytest/mypy are not installed in the test env."""
    _real_which = shutil.which

    def mock_which(cmd):
        return _real_which(cmd) or f"/usr/bin/{cmd}"

    monkeypatch.setattr(shutil, "which", mock_which)


# ---------------------------------------------------------------------------
# Constants & Helpers
# ---------------------------------------------------------------------------

PRD_CONTENT = """\
---
project_name: "Test Project"
project_abbreviation: "VT"
version: v0.1
created: 2026-06-03
updated: 2026-06-03
status: active
---

# Test Project PRD

### REQ-VT-001: Core Feature

#### 优先级
must

##### AC-VT-001-01: Feature must work correctly
* 是否必须有测试：是
"""


def _make_config():
    """Return a minimal config.json dict (no language yet)."""
    return {
        "project_id": "PROJECT-VT",
        "project_prefix": "VT",
        "project_name": "Test Project",
        "paths": {
            "prd": "docs/prd.md",
            "architecture_constraints": "docs/architecture_constraints.json",
            "task_list": "docs/task_list.json",
            "agent_claims": ".vibetracing/agent_claims.json",
            "output_dir": "output",
        },
    }


def _make_constraints(include_language=True):
    """Return architecture_constraints.json dict.

    When ``include_language`` is True, ``project.language`` is set so that
    ``run_finalize`` can read it.  The caller is responsible for removing it
    before passing the data to ``run_analyze`` (which validates against a
    schema that does not yet include the ``language`` property).
    """
    project = {
        "project_id": "PROJECT-VT",
        "name": "Test Project",
        "stage": "mvp",
    }
    if include_language:
        project["language"] = "python"

    return {
        "schema_version": "1.0.0",
        "project": project,
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


def _make_task_list():
    """Return a minimal valid task_list.json dict."""
    return {
        "schema_version": "0.1",
        "project": {
            "project_id": "PROJECT-VT",
            "name": "Test Project",
            "stage": "mvp",
        },
        "tasks": [
            {
                "task_id": "TASK-VT-001",
                "title": "Implement Core Feature",
                "phase_id": "PHASE-VT-001",
                "priority": "must",
                "status": "done",
                "owner_role": "AI Coding Agent",
                "objective": "Implement the core feature requested by the PRD.",
                "related_requirements": ["REQ-VT-001"],
                "related_acceptance_criteria": ["AC-VT-001-01"],
                "definition_of_done": [],
            }
        ],
    }


def _make_claims(
    evidence_refs=None,
    test_refs=None,
    code_refs=None,
    claimed_status="covered",
):
    """Return a minimal valid agent_claims.json list.

    Args:
        evidence_refs: Override evidence references.  Defaults to
            ``["EVIDENCE-VT-003"]`` which is the expected tool-evidence ID
            when there is 1 task + 1 claim + 0 code_refs (the task gets
            EVIDENCE-VT-001, the claim gets EVIDENCE-VT-002, and tool
            evidence starts at EVIDENCE-VT-003).
        test_refs: Test file paths referenced by the claim.
        code_refs: Code file paths referenced by the claim.
        claimed_status: The claim's status.  Use "covered" for completed
            claims or "unclear" for claims without external evidence.
    """
    if evidence_refs is None:
        evidence_refs = ["EVIDENCE-VT-003"]
    return [
        {
            "claim_id": "CLAIM-VT-001",
            "related_task": "TASK-VT-001",
            "claimed_status": claimed_status,
            "evidence_refs": evidence_refs,
            "timestamp": "2026-06-03T00:00:00Z",
            "code_refs": code_refs if code_refs is not None else [],
            "test_refs": test_refs if test_refs is not None else [
                "tests/test_feature.py",
            ],
        }
    ]


def _setup_project(
    base: Path,
    *,
    constraints_data=None,
    claims_data=None,
    create_test_file: bool = True,
) -> None:
    """Write a full mock project tree into *base*.

    By default the constraints include ``project.language`` so that
    ``run_finalize`` can extract it.  The caller must strip that field
    (or call ``_finalize_and_prepare_constraints``) before running
    ``run_analyze``.
    """
    (base / ".vibetracing").mkdir(parents=True, exist_ok=True)
    (base / "docs").mkdir(parents=True, exist_ok=True)

    # config.json (pre-finalize -- no language)
    (base / ".vibetracing" / "config.json").write_text(
        json.dumps(_make_config(), indent=2), encoding="utf-8"
    )

    # architecture_constraints.json (with language for finalize)
    constraints = constraints_data if constraints_data is not None else _make_constraints()
    (base / "docs" / "architecture_constraints.json").write_text(
        json.dumps(constraints, indent=2), encoding="utf-8"
    )

    # task_list.json
    (base / "docs" / "task_list.json").write_text(
        json.dumps(_make_task_list(), indent=2), encoding="utf-8"
    )

    # agent_claims.json
    claims = claims_data if claims_data is not None else _make_claims()
    (base / ".vibetracing" / "agent_claims.json").write_text(
        json.dumps(claims, indent=2), encoding="utf-8"
    )

    # prd.md
    (base / "docs" / "prd.md").write_text(PRD_CONTENT, encoding="utf-8")

    # Optional test file so path validation succeeds
    if create_test_file:
        (base / "tests").mkdir(exist_ok=True)
        (base / "tests" / "test_feature.py").write_text(
            "# covers: AC-VT-001-01\ndef test_feature():\n    pass\n",
            encoding="utf-8",
        )


def _finalize_and_prepare_constraints(base: Path, constraints_data: dict) -> None:
    """Run ``finalize`` and then rewrite constraints without ``project.language``.

    ``run_finalize`` reads ``project.language`` from the raw JSON (no schema
    validation).  ``run_analyze`` validates the same file against a schema that
    does not yet include the ``language`` property, so we strip it after
    finalization has written the language to ``config.json``.
    """
    import hashlib

    exit_code = run_finalize(base)
    assert exit_code == 0, "finalize must succeed"

    # Remove language from project so schema validation in analyze passes
    sanitized = json.loads(json.dumps(constraints_data))
    sanitized["project"].pop("language", None)
    constraints_path = base / "docs" / "architecture_constraints.json"
    constraints_path.write_text(json.dumps(sanitized, indent=2), encoding="utf-8")

    # Update config: set finalize_git_commit (tmp dirs lack a git repo) and
    # refresh architecture_constraints_hash to match the rewritten file.
    cfg_path = base / ".vibetracing" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if not cfg.get("finalize_git_commit"):
        cfg["finalize_git_commit"] = "test_commit_hash"
    cfg["architecture_constraints_hash"] = hashlib.sha256(
        constraints_path.read_bytes()
    ).hexdigest()
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _make_pytest_report(tests):
    """Return a pytest JSON report dict."""
    return {"tests": tests}


def _write_pytest_report_file(cmd_str: str, report_data: dict) -> None:
    """Extract ``--json-report-file=...`` from *cmd_str* and write *report_data*."""
    match = re.search(r"--json-report-file=(\S+)", cmd_str)
    if match:
        report_path = Path(match.group(1))
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report_data), encoding="utf-8")


def _get_risks_of_type(report: dict, item_type: str) -> list:
    """Return risks from the traceability report matching *item_type*."""
    return [
        r for r in report.get("risks", []) if r.get("item_type") == item_type
    ]


# ---------------------------------------------------------------------------
# Test 1: Full happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """finalize -> analyze -> tool evidence -> high credibility -> gate not blocked."""

    def test_full_workflow(self, tmp_path, capsys):
        """
        covers: AC-VT-043-01
        Set up project -> finalize -> analyze (mocked pytest passes) ->
        verify evidence index, tool evidence, high credibility, gate not blocked.
        """
        constraints_data = _make_constraints()
        _setup_project(
            tmp_path,
            constraints_data=constraints_data,
            create_test_file=True,
        )

        # Step 1: Finalize config
        _finalize_and_prepare_constraints(tmp_path, constraints_data)

        config = json.loads(
            (tmp_path / ".vibetracing" / "config.json").read_text(encoding="utf-8")
        )
        assert config["language"] == "python"
        assert "test" in config.get("validation_tools", [])

        # Step 2: Analyze with mocked subprocess (pytest passes)
        output_dir = tmp_path / "output"

        def mock_subprocess(cmd, **kwargs):
            cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)
            _write_pytest_report_file(
                cmd_str,
                _make_pytest_report(
                    [
                        {
                            "nodeid": "tests/test_feature.py::test_feature",
                            "outcome": "passed",
                            "docstring": "covers: AC-VT-001-01",
                        }
                    ]
                ),
            )
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch(
            "vibe_tracing.tool_evidence_adapter.subprocess.run",
            side_effect=mock_subprocess,
        ):
            exit_code = run_analyze(tmp_path, output_dir)

        assert exit_code == 0, "gate should not be blocked"

        # Verify evidence_index.json was generated
        evidence_path = output_dir / "evidence_index.json"
        assert evidence_path.exists(), "evidence_index.json must be created"
        evidence_index = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidences = evidence_index.get("evidences", [])
        assert len(evidences) > 0

        # Verify tool evidence entries exist with source_type "test"
        test_evidence = [e for e in evidences if e.get("source_type") == "test"]
        assert len(test_evidence) > 0, "must have at least one test evidence entry"

        # Verify traceability_report.json was generated
        report_path = output_dir / "traceability_report.json"
        assert report_path.exists(), "traceability_report.json must be created"
        report = json.loads(report_path.read_text(encoding="utf-8"))

        # Verify no claim_credibility risk (means credibility is high)
        credibility_risks = _get_risks_of_type(report, "claim_credibility")
        assert len(credibility_risks) == 0, (
            f"no credibility risk expected for high-credibility claim, "
            f"got: {credibility_risks}"
        )

        # Verify gate decision is not blocked
        gate_decision = report.get("gate_decision", "")
        assert gate_decision != "blocked", (
            f"gate should not be blocked, got: {gate_decision}"
        )


# ---------------------------------------------------------------------------
# Test 2: Finalize prevents analyze without language
# ---------------------------------------------------------------------------


class TestAnalyzeWithoutFinalize:
    """Analyze must fail when config.json has no language (finalize not run)."""

    def test_analyze_requires_finalize(self, tmp_path, capsys):
        """
        covers: AC-VT-043-02
        Run analyze without calling finalize first -> exit 1 with error message.
        Constraints must not have ``language`` in ``project`` so schema
        validation passes; the "not finalized" check reads from config.json.
        """
        # Use constraints without language so schema validation passes
        _setup_project(
            tmp_path,
            constraints_data=_make_constraints(include_language=False),
            create_test_file=True,
        )

        output_dir = tmp_path / "output"

        exit_code = run_analyze(tmp_path, output_dir)
        assert exit_code == 1

        captured = capsys.readouterr()
        assert "Project not finalized" in captured.err


# ---------------------------------------------------------------------------
# Test 3: Low confidence claim blocks gate
# ---------------------------------------------------------------------------


class TestLowConfidenceBlocksGate:
    """Claim with no tool evidence -> low_confidence -> gate blocked."""

    def test_low_confidence_blocks(self, tmp_path, capsys):
        """
        covers: AC-VT-043-03
        Claim has no tool evidence -> low_confidence credibility ->
        credibility risk blocks gate.
        """
        constraints_data = _make_constraints()
        # Use claimed_status="unclear" so claim validation passes even
        # with empty evidence_refs (the "no external evidence" check
        # only applies to "covered"/"compliant" statuses).
        _setup_project(
            tmp_path,
            constraints_data=constraints_data,
            claims_data=_make_claims(
                evidence_refs=[],
                test_refs=[],
                code_refs=[],
                claimed_status="unclear",
            ),
            create_test_file=False,
        )

        _finalize_and_prepare_constraints(tmp_path, constraints_data)

        output_dir = tmp_path / "output"

        # No test_refs means no execution paths -> no tool execution at all
        with patch(
            "vibe_tracing.tool_evidence_adapter.subprocess.run",
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
            exit_code = run_analyze(tmp_path, output_dir)

        # Verify traceability report exists
        report_path = output_dir / "traceability_report.json"
        assert report_path.exists()
        report = json.loads(report_path.read_text(encoding="utf-8"))

        # Verify a claim_credibility risk exists (low_confidence)
        credibility_risks = _get_risks_of_type(report, "claim_credibility")
        assert len(credibility_risks) > 0, (
            "expected a claim_credibility risk for low_confidence claim"
        )

        # Verify gate is blocked
        assert report.get("gate_decision") == "blocked"

        # Verify error output mentions low credibility
        captured = capsys.readouterr()
        assert "low_confidence" in captured.err


# ---------------------------------------------------------------------------
# Test 4: Tool execution failure
# ---------------------------------------------------------------------------


class TestToolExecutionFailure:
    """Tool execution failure -> violated evidence -> gate blocked."""

    def test_pytest_failure_blocks_gate(self, tmp_path, capsys):
        """
        covers: AC-VT-043-04
        Mock pytest returning exit_code=1 -> evidence status 'violated' ->
        gate blocked.
        """
        constraints_data = _make_constraints()
        _setup_project(
            tmp_path,
            constraints_data=constraints_data,
            create_test_file=True,
        )

        _finalize_and_prepare_constraints(tmp_path, constraints_data)

        output_dir = tmp_path / "output"

        # Mock subprocess to simulate pytest failure (no report file, exit=1)
        def mock_subprocess_fail(cmd, **kwargs):
            return MagicMock(returncode=1, stdout="", stderr="FAILED")

        with patch(
            "vibe_tracing.tool_evidence_adapter.subprocess.run",
            side_effect=mock_subprocess_fail,
        ):
            exit_code = run_analyze(tmp_path, output_dir)

        # Verify evidence_index.json was generated
        evidence_path = output_dir / "evidence_index.json"
        assert evidence_path.exists()
        evidence_index = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidences = evidence_index.get("evidences", [])

        # Verify tool evidence has status "violated"
        test_evidence = [e for e in evidences if e.get("source_type") == "test"]
        assert len(test_evidence) > 0, "must have test evidence entries"
        assert any(
            e.get("status") == "violated" for e in test_evidence
        ), "at least one test evidence must be 'violated'"

        # Verify gate is blocked
        report_path = output_dir / "traceability_report.json"
        assert report_path.exists()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report.get("gate_decision") == "blocked"


# ---------------------------------------------------------------------------
# Test 5: Re-finalize is idempotent
# ---------------------------------------------------------------------------


class TestFinalizeIdempotent:
    """Running finalize twice -> 'Already finalized', config unchanged."""

    def test_finalize_idempotent(self, tmp_path, capsys):
        """
        covers: AC-VT-043-05
        Run finalize twice -> second run prints 'Already finalized' and
        config.json is unchanged.
        """
        constraints_data = _make_constraints()
        _setup_project(tmp_path, constraints_data=constraints_data)

        # First finalize
        exit_code = run_finalize(tmp_path)
        assert exit_code == 0

        config_after_first = json.loads(
            (tmp_path / ".vibetracing" / "config.json").read_text(encoding="utf-8")
        )
        assert config_after_first["language"] == "python"
        assert "test" in config_after_first.get("validation_tools", [])

        # Second finalize
        exit_code = run_finalize(tmp_path)
        assert exit_code == 0

        captured = capsys.readouterr()
        assert "Already finalized" in captured.out

        config_after_second = json.loads(
            (tmp_path / ".vibetracing" / "config.json").read_text(encoding="utf-8")
        )
        assert config_after_first == config_after_second, (
            "config.json must not change on second finalize"
        )
