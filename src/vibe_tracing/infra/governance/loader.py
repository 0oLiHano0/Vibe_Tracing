"""Governance data loaders.

I/O operations for loading governance data from filesystem.
Extracted from domain/governance/ghost_code.py and change_proposal.py
to maintain proper layer separation (domain = pure logic, infra = I/O).
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from vibe_tracing.infra.logging.logger import OperationalLogger


def read_claims_from_filesystem(claims_dir: Path) -> List[dict]:
    """Read all CLAIM-*.json files from the claims directory on disk.

    Args:
        claims_dir: Path to the claims directory.

    Returns:
        List of claim dicts.
    """
    all_claims = []
    if not claims_dir.is_dir():
        return all_claims
    for claim_file in sorted(claims_dir.glob("CLAIM-*.json")):
        try:
            data = json.loads(claim_file.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else [data]
            for item in items:
                # Skip template records
                if item.get("claim_id", "").endswith("-9999"):
                    continue
                # Skip claims missing required fields
                if not item.get("claim_id") or not item.get("related_task"):
                    continue
                all_claims.append(item)
        except (json.JSONDecodeError, OSError) as exc:
            OperationalLogger.get().debug(
                "claim_file_load_failed",
                f"Could not load claim file {claim_file}",
                exc=exc,
            )
    return all_claims


def read_task_list(project_root: Path) -> Optional[dict]:
    """Read task_list.json from the filesystem.

    Args:
        project_root: Project root directory.

    Returns:
        Task list dict or None if not found.
    """
    task_list_path = project_root / "docs" / "task_list.json"
    try:
        return json.loads(task_list_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        OperationalLogger.get().warning(
            "task_list_load_failed", "Could not load task_list.json", exc=exc
        )
        return None


def read_prd_ac_ids(project_root: Path) -> Set[str]:
    """Parse PRD content from filesystem and extract all AC IDs.

    Args:
        project_root: Project root directory.

    Returns:
        Set of AC ID strings.
    """
    prd_path = project_root / "docs" / "prd.md"
    try:
        content = prd_path.read_text(encoding="utf-8")
        ac_pattern = re.compile(r"AC-[A-Z]+-\d+-\d+")
        return set(ac_pattern.findall(content))
    except OSError as exc:
        OperationalLogger.get().warning(
            "prd_ac_parse_failed", "Could not read PRD for AC extraction", exc=exc
        )
        return set()


def check_prd_exists(project_root: Path) -> bool:
    """Check if PRD file exists.

    Args:
        project_root: Project root directory.

    Returns:
        True if prd.md exists.
    """
    return (project_root / "docs" / "prd.md").is_file()


def read_constraints_file(constraints_path: Path) -> Tuple[Optional[bytes], Optional[str]]:
    """Read constraints file and compute SHA256 hash.

    Args:
        constraints_path: Path to architecture_constraints.json.

    Returns:
        Tuple of (file_bytes, sha256_hex) or (None, None) on error.
    """
    try:
        file_bytes = constraints_path.read_bytes()
        sha256_hex = hashlib.sha256(file_bytes).hexdigest()
        return file_bytes, sha256_hex
    except OSError as exc:
        OperationalLogger.get().warning(
            "constraints_read_failed", "Could not read constraints file", exc=exc
        )
        return None, None


def read_constraints_json(constraints_path: Path) -> Optional[dict]:
    """Read and parse constraints JSON file.

    Args:
        constraints_path: Path to architecture_constraints.json.

    Returns:
        Parsed dict or None on error.
    """
    try:
        return json.loads(constraints_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        OperationalLogger.get().warning(
            "constraints_parse_failed", "Could not parse constraints file", exc=exc
        )
        return None
