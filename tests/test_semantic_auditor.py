"""Tests for SemanticAuditor -- protocol-based self-semantic audit gate."""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from vibe_tracing.semantic_auditor import SemanticAuditor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_git(project: Path) -> None:
    """Initialise a git repo with an initial commit so HEAD / index exist."""
    subprocess.run(["git", "init"], cwd=project, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=project, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=project, capture_output=True, check=True,
    )
    (project / "placeholder.txt").write_text("init\n")
    subprocess.run(["git", "add", "placeholder.txt"], cwd=project, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=project, capture_output=True, check=True,
    )


def _make_task(task_id: str = "TASK-VT-001", category: str = "quality_evolution",
               ac_ids=None) -> dict:
    return {
        "task_id": task_id,
        "category": category,
        "related_acceptance_criteria": ac_ids or [],
    }


def _make_claim(claim_id: str = "CLAIM-VT-001", task_id: str = "TASK-VT-001",
                code_refs=None) -> dict:
    return {
        "claim_id": claim_id,
        "related_task": task_id,
        "code_refs": code_refs or [],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestQualityEvolutionChangeGeneratesTicket:
    """Staged code file covered by a quality_evolution task must produce a pending ticket."""

    def test_generates_pending_ticket(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        # Write and stage a code file
        code_file = tmp_path / "src" / "foo.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("print('hello')\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        tasks = [_make_task()]
        claims = [_make_claim(code_refs=["src/foo.py"])]

        auditor = SemanticAuditor(tmp_path)
        staged = auditor.get_staged_code_files()
        assert "src/foo.py" in staged

        new_tickets = auditor.generate_tickets(staged, claims, tasks)
        assert len(new_tickets) == 1
        t = new_tickets[0]
        assert t["status"] == "pending"
        assert t["file_path"] == "src/foo.py"
        assert t["file_hash"].startswith("sha256:")
        assert t["audit_reason"] == ""

        # Verify persisted
        loaded = auditor._load_tickets()
        assert len(loaded) == 1
        assert loaded[0]["ticket_id"] == t["ticket_id"]


class TestFunctionalChangeGeneratesTicket:
    """Staged code file covered by a functional task must produce a ticket with audit_level='standard'."""

    def test_ticket_for_functional_task(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "bar.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("x = 1\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        tasks = [_make_task(category="functional")]
        claims = [_make_claim(code_refs=["src/bar.py"])]

        auditor = SemanticAuditor(tmp_path)
        staged = auditor.get_staged_code_files()
        new_tickets = auditor.generate_tickets(staged, claims, tasks)
        assert len(new_tickets) == 1
        t = new_tickets[0]
        assert t["status"] == "pending"
        assert t["file_path"] == "src/bar.py"
        assert t["audit_level"] == "standard"
        assert t["task_id"] == "TASK-VT-001"


class TestPendingTicketBlocksVerify:
    """A pending ticket must cause verify_tickets to return (False, ...)."""

    def test_pending_blocks(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "foo.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("print('a')\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        tasks = [_make_task()]
        claims = [_make_claim(code_refs=["src/foo.py"])]

        auditor = SemanticAuditor(tmp_path)
        staged = auditor.get_staged_code_files()
        auditor.generate_tickets(staged, claims, tasks)

        ok, msg = auditor.verify_tickets(staged)
        assert ok is False
        assert "pending" in msg.lower() or "status" in msg.lower()


class TestPassedTicketWithReasonPasses:
    """A passed ticket with a non-empty reason and matching hash must pass."""

    def test_passed_with_reason(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "foo.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("print('a')\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        # Manually create a passed ticket with correct hash
        auditor = SemanticAuditor(tmp_path)
        file_hash = auditor._compute_staged_file_hash("src/foo.py")
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        ticket = {
            "ticket_id": "AUDIT-VT-001",
            "file_path": "src/foo.py",
            "file_hash": file_hash,
            "task_id": "TASK-VT-001",
            "ac_ids": [],
            "status": "passed",
            "audit_reason": "Semantic review of foo.py completed: no issues found.",
            "created_at": now,
            "updated_at": now,
        }
        auditor._save_tickets([ticket])

        staged = auditor.get_staged_code_files()
        ok, msg = auditor.verify_tickets(staged)
        assert ok is True
        assert msg == ""


class TestEmptyReasonBlocks:
    """A passed ticket with an empty audit_reason must be blocked."""

    def test_empty_reason_blocks(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "foo.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("print('a')\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        auditor = SemanticAuditor(tmp_path)
        file_hash = auditor._compute_staged_file_hash("src/foo.py")
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        ticket = {
            "ticket_id": "AUDIT-VT-001",
            "file_path": "src/foo.py",
            "file_hash": file_hash,
            "task_id": "TASK-VT-001",
            "ac_ids": [],
            "status": "passed",
            "audit_reason": "",
            "created_at": now,
            "updated_at": now,
        }
        auditor._save_tickets([ticket])

        staged = auditor.get_staged_code_files()
        ok, msg = auditor.verify_tickets(staged)
        assert ok is False
        assert "empty" in msg.lower()


class TestHashMismatchResetsToPending:
    """File modified after ticket was created must reset ticket to pending."""

    def test_hash_mismatch_resets(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "foo.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("print('a')\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        # Create a ticket with the current hash
        auditor = SemanticAuditor(tmp_path)
        file_hash = auditor._compute_staged_file_hash("src/foo.py")
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        ticket = {
            "ticket_id": "AUDIT-VT-001",
            "file_path": "src/foo.py",
            "file_hash": file_hash,
            "task_id": "TASK-VT-001",
            "ac_ids": [],
            "status": "passed",
            "audit_reason": "Reason",
            "created_at": now,
            "updated_at": now,
        }
        auditor._save_tickets([ticket])

        # Modify the file and re-stage
        code_file.write_text("print('modified')\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        staged = auditor.get_staged_code_files()
        ok, msg = auditor.verify_tickets(staged)
        assert ok is False
        assert "hash" in msg.lower() or "reset" in msg.lower()

        # Verify the persisted ticket is now pending
        loaded = auditor._load_tickets()
        assert loaded[0]["status"] == "pending"


class TestNoStagedFilesNoop:
    """No staged code files must produce no tickets and verify must pass."""

    def test_no_staged_files(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        auditor = SemanticAuditor(tmp_path)
        staged = auditor.get_staged_code_files()
        assert staged == set()

        tickets = auditor.generate_tickets(staged, [], [])
        assert tickets == []

        ok, msg = auditor.verify_tickets(staged)
        assert ok is True
        assert msg == ""


class TestArchivedTicketsCleanedAfter48h:
    """Archived tickets older than 48 hours must be removed during verify."""

    def test_old_archived_cleaned(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "foo.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("print('a')\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        auditor = SemanticAuditor(tmp_path)
        file_hash = auditor._compute_staged_file_hash("src/foo.py")
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(hours=50)).isoformat().replace("+00:00", "Z")

        # An old archived ticket
        old_ticket = {
            "ticket_id": "AUDIT-VT-OLD",
            "file_path": "src/foo.py",
            "file_hash": file_hash,
            "task_id": "TASK-VT-001",
            "ac_ids": [],
            "status": "archived",
            "audit_reason": "done",
            "created_at": old_time,
            "updated_at": old_time,
        }
        auditor._save_tickets([old_ticket])

        # Add the file to staged so verify touches this ticket
        staged = {"src/foo.py"}
        ok, _msg = auditor.verify_tickets(staged)

        # The old ticket should be cleaned up
        loaded = auditor._load_tickets()
        assert all(t["ticket_id"] != "AUDIT-VT-OLD" for t in loaded)

    def test_recent_archived_kept(self, tmp_path: Path) -> None:
        """Archived tickets younger than 48 hours must NOT be removed."""
        _init_git(tmp_path)

        auditor = SemanticAuditor(tmp_path)
        file_hash = "sha256:deadbeef"
        now = datetime.now(timezone.utc)
        recent_time = (now - timedelta(hours=10)).isoformat().replace("+00:00", "Z")

        recent_ticket = {
            "ticket_id": "AUDIT-VT-REC",
            "file_path": "src/other.py",
            "file_hash": file_hash,
            "task_id": "TASK-VT-001",
            "ac_ids": [],
            "status": "archived",
            "audit_reason": "done",
            "created_at": recent_time,
            "updated_at": recent_time,
        }
        auditor._save_tickets([recent_ticket])

        # Use an empty staged set so verify doesn't interact with tickets
        ok, _msg = auditor.verify_tickets(set())
        loaded = auditor._load_tickets()
        assert any(t["ticket_id"] == "AUDIT-VT-REC" for t in loaded)


class TestGetStagedCodeFiles:
    """Verify staged file detection filters to code extensions."""

    def test_filters_non_code_files(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        py_file = tmp_path / "mod.py"
        py_file.write_text("x=1\n")
        md_file = tmp_path / "readme.md"
        md_file.write_text("# hi\n")
        subprocess.run(["git", "add", str(py_file), str(md_file)],
                       cwd=tmp_path, capture_output=True, check=True)

        auditor = SemanticAuditor(tmp_path)
        staged = auditor.get_staged_code_files()
        assert "mod.py" in staged
        assert "readme.md" not in staged

    def test_typescript_extensions_included(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        for ext in [".py", ".js", ".ts", ".jsx", ".tsx"]:
            f = tmp_path / f"file{ext}"
            f.write_text(f"// {ext}\n")
            subprocess.run(["git", "add", str(f)], cwd=tmp_path, capture_output=True, check=True)

        auditor = SemanticAuditor(tmp_path)
        staged = auditor.get_staged_code_files()
        for ext in [".py", ".js", ".ts", ".jsx", ".tsx"]:
            assert f"file{ext}" in staged


class TestGenerateTicketsIdempotent:
    """Regenerating tickets for the same file+hash must NOT duplicate."""

    def test_no_duplicate_tickets(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "foo.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("print('a')\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        tasks = [_make_task()]
        claims = [_make_claim(code_refs=["src/foo.py"])]

        auditor = SemanticAuditor(tmp_path)
        staged = auditor.get_staged_code_files()

        first = auditor.generate_tickets(staged, claims, tasks)
        assert len(first) == 1

        second = auditor.generate_tickets(staged, claims, tasks)
        assert len(second) == 0  # no new tickets


class TestTicketDataStructure:
    """Verify the full ticket data structure matches spec."""

    def test_ticket_fields(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "mod.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("x = 1\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        tasks = [_make_task(ac_ids=["AC-VT-001-01"])]
        claims = [_make_claim(code_refs=["src/mod.py"])]

        auditor = SemanticAuditor(tmp_path)
        staged = auditor.get_staged_code_files()
        tickets = auditor.generate_tickets(staged, claims, tasks)

        assert len(tickets) == 1
        t = tickets[0]

        # Check all required fields
        assert "ticket_id" in t
        assert t["ticket_id"].startswith("AUDIT-VT-")
        assert t["file_path"] == "src/mod.py"
        assert t["file_hash"].startswith("sha256:")
        assert t["task_id"] == "TASK-VT-001"
        assert t["audit_level"] == "detailed"
        assert t["ac_ids"] == ["AC-VT-001-01"]
        assert t["status"] == "pending"
        assert t["audit_reason"] == ""
        assert "created_at" in t
        assert "updated_at" in t


class TestRequirementsBasedCategoryLookup:
    """Category can be resolved from related_requirements when task has no direct category."""

    def test_quality_evolution_via_requirement(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "refactor.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("# refactored\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        # Task has no direct category, but links to REQ-VT-010 which is quality_evolution
        task = {
            "task_id": "TASK-VT-051",
            "related_requirements": ["REQ-VT-010"],
            "related_acceptance_criteria": ["AC-VT-010-01"],
        }
        claim = _make_claim(task_id="TASK-VT-051", code_refs=["src/refactor.py"])
        requirements = [{"req_id": "REQ-VT-010", "category": "quality_evolution"}]

        auditor = SemanticAuditor(tmp_path)
        staged = auditor.get_staged_code_files()
        tickets = auditor.generate_tickets(staged, [claim], [task], requirements)

        assert len(tickets) == 1
        assert tickets[0]["task_id"] == "TASK-VT-051"

    def test_functional_via_requirement_generates_ticket(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "feature.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("# feature\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        task = {
            "task_id": "TASK-VT-001",
            "related_requirements": ["REQ-VT-001"],
            "related_acceptance_criteria": ["AC-VT-001-01"],
        }
        claim = _make_claim(task_id="TASK-VT-001", code_refs=["src/feature.py"])
        requirements = [{"req_id": "REQ-VT-001", "category": "functional"}]

        auditor = SemanticAuditor(tmp_path)
        staged = auditor.get_staged_code_files()
        tickets = auditor.generate_tickets(staged, [claim], [task], requirements)

        assert len(tickets) == 1
        assert tickets[0]["audit_level"] == "standard"


class TestShortReasonBlocks:
    """A passed ticket with an audit_reason shorter than 20 chars must be blocked."""

    def test_short_reason_blocks(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "foo.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("print('a')\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        auditor = SemanticAuditor(tmp_path)
        file_hash = auditor._compute_staged_file_hash("src/foo.py")
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        ticket = {
            "ticket_id": "AUDIT-VT-001",
            "file_path": "src/foo.py",
            "file_hash": file_hash,
            "task_id": "TASK-VT-001",
            "ac_ids": [],
            "status": "passed",
            "audit_reason": "ok",  # < 20 chars
            "created_at": now,
            "updated_at": now,
        }
        auditor._save_tickets([ticket])

        staged = auditor.get_staged_code_files()
        ok, msg = auditor.verify_tickets(staged)
        assert ok is False
        assert "too short" in msg.lower()


class TestReasonWithoutFilenameBlocks:
    """A passed ticket with an audit_reason that does not contain the filename must be blocked."""

    def test_reason_without_filename_blocks(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "foo.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("print('a')\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        auditor = SemanticAuditor(tmp_path)
        file_hash = auditor._compute_staged_file_hash("src/foo.py")
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        ticket = {
            "ticket_id": "AUDIT-VT-001",
            "file_path": "src/foo.py",
            "file_hash": file_hash,
            "task_id": "TASK-VT-001",
            "ac_ids": [],
            "status": "passed",
            "audit_reason": "This reason is long enough but does not mention the file.",
            "created_at": now,
            "updated_at": now,
        }
        auditor._save_tickets([ticket])

        staged = auditor.get_staged_code_files()
        ok, msg = auditor.verify_tickets(staged)
        assert ok is False
        assert "filename" in msg.lower()


class TestReasonWithFilenameAndLengthPasses:
    """A passed ticket with a reason >= 20 chars containing the filename must pass."""

    def test_valid_reason_passes(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "foo.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("print('a')\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        auditor = SemanticAuditor(tmp_path)
        file_hash = auditor._compute_staged_file_hash("src/foo.py")
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        ticket = {
            "ticket_id": "AUDIT-VT-001",
            "file_path": "src/foo.py",
            "file_hash": file_hash,
            "task_id": "TASK-VT-001",
            "ac_ids": [],
            "status": "passed",
            "audit_reason": "Reviewed foo.py and confirmed semantic correctness.",
            "created_at": now,
            "updated_at": now,
        }
        auditor._save_tickets([ticket])

        staged = auditor.get_staged_code_files()
        ok, msg = auditor.verify_tickets(staged)
        assert ok is True
        assert msg == ""


# ---------------------------------------------------------------------------
# Audit-level specific tests
# ---------------------------------------------------------------------------


class TestAuditLevelOnTickets:
    """Verify that generate_tickets sets the correct audit_level on each ticket."""

    def test_quality_evolution_gets_detailed(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "qe.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("# qe\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        tasks = [_make_task(category="quality_evolution")]
        claims = [_make_claim(code_refs=["src/qe.py"])]

        auditor = SemanticAuditor(tmp_path)
        staged = auditor.get_staged_code_files()
        tickets = auditor.generate_tickets(staged, claims, tasks)
        assert len(tickets) == 1
        assert tickets[0]["audit_level"] == "detailed"

    def test_functional_gets_standard(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "func.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("# func\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        tasks = [_make_task(category="functional")]
        claims = [_make_claim(code_refs=["src/func.py"])]

        auditor = SemanticAuditor(tmp_path)
        staged = auditor.get_staged_code_files()
        tickets = auditor.generate_tickets(staged, claims, tasks)
        assert len(tickets) == 1
        assert tickets[0]["audit_level"] == "standard"

    def test_quality_evolution_via_req_gets_detailed(self, tmp_path: Path) -> None:
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "qe2.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("# qe2\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        task = {
            "task_id": "TASK-VT-052",
            "related_requirements": ["REQ-VT-020"],
            "related_acceptance_criteria": [],
        }
        claim = _make_claim(task_id="TASK-VT-052", code_refs=["src/qe2.py"])
        requirements = [{"req_id": "REQ-VT-020", "category": "quality_evolution"}]

        auditor = SemanticAuditor(tmp_path)
        staged = auditor.get_staged_code_files()
        tickets = auditor.generate_tickets(staged, [claim], [task], requirements)
        assert len(tickets) == 1
        assert tickets[0]["audit_level"] == "detailed"


class TestDetailedAuditLevelVerification:
    """Tickets with audit_level='detailed' require >=50 chars in audit_reason."""

    def test_detailed_short_reason_blocked(self, tmp_path: Path) -> None:
        """A detailed ticket with 20-49 char reason must be blocked."""
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "foo.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("print('a')\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        auditor = SemanticAuditor(tmp_path)
        file_hash = auditor._compute_staged_file_hash("src/foo.py")
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        ticket = {
            "ticket_id": "AUDIT-VT-001",
            "file_path": "src/foo.py",
            "file_hash": file_hash,
            "task_id": "TASK-VT-001",
            "audit_level": "detailed",
            "ac_ids": [],
            "status": "passed",
            "audit_reason": "Reviewed foo.py and it looks correct.",  # 38 chars < 50
            "created_at": now,
            "updated_at": now,
        }
        auditor._save_tickets([ticket])

        staged = auditor.get_staged_code_files()
        ok, msg = auditor.verify_tickets(staged)
        assert ok is False
        assert "too short" in msg.lower()
        assert "50" in msg
        assert "detailed" in msg.lower()

    def test_detailed_long_enough_reason_passes(self, tmp_path: Path) -> None:
        """A detailed ticket with >=50 char reason containing filename must pass."""
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "foo.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("print('a')\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        auditor = SemanticAuditor(tmp_path)
        file_hash = auditor._compute_staged_file_hash("src/foo.py")
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        ticket = {
            "ticket_id": "AUDIT-VT-001",
            "file_path": "src/foo.py",
            "file_hash": file_hash,
            "task_id": "TASK-VT-001",
            "audit_level": "detailed",
            "ac_ids": [],
            "status": "passed",
            "audit_reason": (
                "Semantic review of foo.py completed: the code follows all conventions "
                "and no issues were found during the audit."
            ),
            "created_at": now,
            "updated_at": now,
        }
        auditor._save_tickets([ticket])

        staged = auditor.get_staged_code_files()
        ok, msg = auditor.verify_tickets(staged)
        assert ok is True
        assert msg == ""


class TestStandardAuditLevelVerification:
    """Tickets with audit_level='standard' require >=20 chars in audit_reason."""

    def test_standard_short_reason_blocked(self, tmp_path: Path) -> None:
        """A standard ticket with <20 char reason must be blocked."""
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "bar.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("x = 1\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        auditor = SemanticAuditor(tmp_path)
        file_hash = auditor._compute_staged_file_hash("src/bar.py")
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        ticket = {
            "ticket_id": "AUDIT-VT-001",
            "file_path": "src/bar.py",
            "file_hash": file_hash,
            "task_id": "TASK-VT-001",
            "audit_level": "standard",
            "ac_ids": [],
            "status": "passed",
            "audit_reason": "Looks ok",  # 8 chars < 20
            "created_at": now,
            "updated_at": now,
        }
        auditor._save_tickets([ticket])

        staged = auditor.get_staged_code_files()
        ok, msg = auditor.verify_tickets(staged)
        assert ok is False
        assert "too short" in msg.lower()
        assert "20" in msg
        assert "standard" in msg.lower()

    def test_standard_reason_20_to_49_chars_passes(self, tmp_path: Path) -> None:
        """A standard ticket with 20-49 char reason containing filename must pass."""
        _init_git(tmp_path)

        code_file = tmp_path / "src" / "bar.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("x = 1\n")
        subprocess.run(["git", "add", str(code_file)], cwd=tmp_path, capture_output=True, check=True)

        auditor = SemanticAuditor(tmp_path)
        file_hash = auditor._compute_staged_file_hash("src/bar.py")
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        ticket = {
            "ticket_id": "AUDIT-VT-001",
            "file_path": "src/bar.py",
            "file_hash": file_hash,
            "task_id": "TASK-VT-001",
            "audit_level": "standard",
            "ac_ids": [],
            "status": "passed",
            "audit_reason": "Reviewed bar.py, no issues found.",
            "created_at": now,
            "updated_at": now,
        }
        auditor._save_tickets([ticket])

        staged = auditor.get_staged_code_files()
        ok, msg = auditor.verify_tickets(staged)
        assert ok is True
        assert msg == ""
