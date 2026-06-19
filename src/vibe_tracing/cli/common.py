"""
Shared utilities used across command modules.
"""

import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Optional, Set, Tuple

from vibe_tracing.domain.raw_input_loader import RawInputLoader
from vibe_tracing.domain.prd_parser import PrdParser
from vibe_tracing.domain.task_loader import TaskLoader
from vibe_tracing.domain.claim_loader import ClaimLoader
from vibe_tracing.domain.context import UnifiedContext


class _GateBlocked(Exception):
    """Raised when an integrity gate blocks the analysis pipeline."""
    def __init__(self, exit_code: int = 1):
        self.exit_code = exit_code


def _load_context(
    project_root: Path,
) -> Tuple[UnifiedContext, RawInputLoader]:
    """Load all input files, validate schemas, and build UnifiedContext.

    Raises _GateBlocked with exit_code=1 on any validation failure.
    """
    raw_loader = RawInputLoader(project_root)
    manifest = raw_loader.load()

    config_prefix = raw_loader.config_data.get("project_prefix", "VT")
    from vibe_tracing.infra import validation as ids
    ids.set_project_prefix(config_prefix)

    # Check for missing required files
    if manifest.has_required_errors:
        for record in manifest.inputs_used:
            if record.is_required and record.status != "ok":
                print(
                    f"Error loading required file {record.file_key} ({record.file_path}): {record.error_message}",
                    file=sys.stderr,
                )
        raise _GateBlocked(1)

    # Check for malformed files
    for record in manifest.inputs_used:
        if record.status not in ("ok", "missing"):
            print(
                f"Error loading file {record.file_key} ({record.file_path}): {record.error_message}",
                file=sys.stderr,
            )
            raise _GateBlocked(1)

    # 统一格式校验
    from vibe_tracing.infra.validation import validate_inputs
    schemas_dir = project_root / "schemas"
    if not schemas_dir.is_dir():
        schemas_dir = Path(__file__).parents[1] / "infra" / "validation" / "schemas"
    validation_result = validate_inputs(manifest, config_prefix, schemas_dir=schemas_dir)
    if not validation_result.is_valid:
        print(validation_result.format_errors(), file=sys.stderr)
        raise _GateBlocked(1)

    records_dict = {r.file_key: r for r in manifest.inputs_used}
    prd_record = records_dict.get("prd")
    task_list_record = records_dict.get("task_list")
    constraints_record = records_dict.get("architecture_constraints")
    claims_record = records_dict.get("agent_claims")

    if not prd_record or prd_record.status != "ok":
        print("Error: PRD file missing or failed to load.", file=sys.stderr)
        raise _GateBlocked(1)

    # Parse PRD — use already-loaded content to avoid re-reading from disk
    prd_parser = PrdParser()
    prd_res = prd_parser.parse_text(prd_record.content)
    if not prd_res.is_valid:
        print(f"PRD parsing error: {'; '.join(prd_res.errors)}", file=sys.stderr)
        raise _GateBlocked(1)

    is_draft = (prd_res.status == "draft")

    # Verify required files exist if not draft
    if not is_draft:
        if not task_list_record or task_list_record.status != "ok":
            print(
                f"Error loading required file task_list ({raw_loader.get_path('task_list')}): File not found",
                file=sys.stderr,
            )
            raise _GateBlocked(1)
        if not constraints_record or constraints_record.status != "ok":
            print(
                f"Error loading required file architecture_constraints ({raw_loader.get_path('architecture_constraints')}): File not found",
                file=sys.stderr,
            )
            raise _GateBlocked(1)

    # Load tasks
    task_res = None
    if task_list_record and task_list_record.status == "ok":
        task_list_path = Path(task_list_record.file_path)
        task_loader = TaskLoader()
        arch_data = constraints_record.content if constraints_record and constraints_record.status == "ok" else None
        task_res = task_loader.load_and_validate(
            task_list_path, prd_res, arch_data=arch_data, content=task_list_record.content
        )
        if not task_res.is_valid:
            print(
                f"Task list validation error: {'; '.join(task_res.errors)}",
                file=sys.stderr,
            )
            raise _GateBlocked(1)

    # Load claims
    claims_list = []
    if claims_record and claims_record.status == "ok" and task_res:
        claims_path = Path(claims_record.file_path)
        claim_loader = ClaimLoader()
        claim_res_loader = claim_loader.load(
            claims_path, task_res, content=claims_record.content
        )
        if not claim_res_loader.is_valid:
            print(
                f"Agent claims validation error: {'; '.join(claim_res_loader.errors)}",
                file=sys.stderr,
            )
            raise _GateBlocked(1)
        claims_list = claim_res_loader.claims

    # 加载 human_decisions
    human_decisions_data = None
    for record in manifest.inputs_used:
        if record.file_key == "human_decisions" and record.status == "ok" and record.content is not None:
            human_decisions_data = record.content
            break

    ctx = UnifiedContext(
        config=raw_loader.config_data,
        prd=prd_res,
        constraints=constraints_record.content if constraints_record and constraints_record.status == "ok" else None,
        task_result=task_res,
        claims_list=claims_list,
        manifest=manifest,
        human_decisions=human_decisions_data,
        config_prefix=config_prefix,
    )
    return ctx, raw_loader


def _rel_path_str(p: Path, project_root: Path) -> str:
    """Return a relative path string if p is under project_root, else the full path."""
    try:
        if p.is_absolute() and (project_root in p.parents or p == project_root):
            return str(p.relative_to(project_root))
    except Exception:
        pass
    return str(p)


def _get_staged_files(project_root: Path) -> Set[str]:
    """Get the set of staged file paths from ``git diff --cached``.

    Returns an empty set if git is unavailable or no files are staged.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return {f for f in result.stdout.splitlines() if f.strip()}
    except Exception:
        pass
    return set()


def _determine_affected_items(
    staged_files: Set[str],
    claims_list: list,
    ctx: UnifiedContext,
) -> Tuple[Set[str], Set[str], Set[str]]:
    """Determine which claims, requirements, and ACs are affected by staged changes.

    A claim is *affected* if any of its ``code_refs`` or ``test_refs`` paths
    appear in *staged_files*.  A requirement / AC is affected when it is
    covered by a task that has at least one affected claim.

    Returns ``(affected_claim_ids, affected_req_ids, affected_ac_ids)``.
    """
    affected_claims: Set[str] = set()
    affected_reqs: Set[str] = set()
    affected_acs: Set[str] = set()

    for claim in claims_list:
        claim_id = claim.claim_id
        for ref in (claim.code_refs or []) + (claim.test_refs or []):
            path = ref.split("#")[0]
            if path in staged_files:
                affected_claims.add(claim_id)
                break

    # Map affected claims -> tasks -> requirements / ACs
    if affected_claims and ctx.task_result and ctx.task_result.tasks:
        affected_task_ids = {
            claim.related_task
            for claim in claims_list
            if claim.claim_id in affected_claims
        }
        for task in ctx.task_result.tasks:
            if task.task_id in affected_task_ids:
                for req_id in (task.related_requirements or []):
                    affected_reqs.add(req_id)
                for ac_id in (task.related_acceptance_criteria or []):
                    affected_acs.add(ac_id)

    return affected_claims, affected_reqs, affected_acs


def _file_sha256(path: Path) -> Optional[str]:
    """Compute SHA-256 hex digest of a file."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, IOError):
        return None


