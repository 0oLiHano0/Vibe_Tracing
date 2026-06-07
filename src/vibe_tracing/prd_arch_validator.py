"""
Reusable PRD <-> Architecture mapping validator.

Extracts the mapping validation logic from cli.py so it can be reused
by both run_finalize() and run_analyze().
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class MappingResult:
    """Result of PRD<->Architecture mapping validation."""

    dead_links: List[str] = field(default_factory=list)
    must_uncovered: List[str] = field(default_factory=list)
    should_uncovered: List[str] = field(default_factory=list)

    @property
    def has_dead_links(self) -> bool:
        return len(self.dead_links) > 0

    @property
    def has_must_uncovered(self) -> bool:
        return len(self.must_uncovered) > 0

    @property
    def is_valid(self) -> bool:
        return not self.has_dead_links and not self.has_must_uncovered


def _collect_related_reqs(data: Any) -> set:
    """Recursively collect all related_requirements IDs from nested structures."""
    reqs = set()
    if isinstance(data, dict):
        if "related_requirements" in data:
            reqs.update(data["related_requirements"])
        for v in data.values():
            reqs.update(_collect_related_reqs(v))
    elif isinstance(data, list):
        for item in data:
            reqs.update(_collect_related_reqs(item))
    return reqs


def validate_prd_architecture_mapping(
    prd_requirements: List[Any],
    constraints_content: Dict[str, Any],
    project_prefix: str = "VT",
) -> MappingResult:
    """
    Validate that architecture constraints correctly reference PRD requirements.

    Checks:
    - Dead links: constraints referencing REQs that don't exist in PRD -> dead_links
    - Must uncovered: MUST-level REQs without architecture support -> must_uncovered
    - Should uncovered: SHOULD/COULD-level REQs without architecture mapping -> should_uncovered

    Args:
        prd_requirements: List of requirement objects with .req_id and .priority attributes.
        constraints_content: Parsed architecture_constraints.json content.
        project_prefix: Project prefix (unused, kept for API symmetry with callers).

    Returns:
        MappingResult with validation findings.
    """
    result = MappingResult()

    req_ids = {r.req_id: r.priority for r in prd_requirements}
    if not req_ids:
        return result

    # Collect all related_requirements from architecture constraints
    arch_reqs = _collect_related_reqs(constraints_content)

    # Dead link detection: constraints referencing REQs that don't exist in PRD
    dead_links = arch_reqs - set(req_ids.keys())
    result.dead_links = sorted(dead_links)

    # Collect REQs covered by architecture constraints (top-level list sections)
    covered_reqs = set()
    for section_key, section_val in constraints_content.items():
        if isinstance(section_val, list):
            for rule in section_val:
                if isinstance(rule, dict) and "related_requirements" in rule:
                    covered_reqs.update(rule["related_requirements"])

    # Core coverage check: MUST-level REQs must have architecture support
    must_reqs = {rid for rid, p in req_ids.items() if p == "must"}
    result.must_uncovered = sorted(must_reqs - covered_reqs)

    # Non-core coverage warning: SHOULD/COULD-level REQs without mapping
    should_could_reqs = {rid for rid, p in req_ids.items() if p in ("should", "could")}
    result.should_uncovered = sorted(should_could_reqs - covered_reqs)

    return result


@dataclass
class PathValidationResult:
    """Result wrapper for validate_prd_architecture_mapping_from_path.

    Combines error/warning messages with the validation result.
    """

    exit_code: int
    message: Optional[str] = None
    result: Optional[MappingResult] = None


def validate_prd_architecture_mapping_from_path(
    project_root: Path,
    constraints_data: dict,
) -> PathValidationResult:
    """
    Load PRD from disk and validate PRD <-> Architecture mapping.

    This is the file-I/O variant used by run_finalize() and run_analyze().
    It reads docs/prd.md, parses it, then delegates to
    validate_prd_architecture_mapping().

    Returns:
        PathValidationResult with exit_code (0=pass, 1=fail),
        optional message for printing, and the underlying MappingResult.
    """
    from vibe_tracing.prd_parser import PrdParser

    prd_path = project_root / "docs" / "prd.md"
    if not prd_path.exists():
        return PathValidationResult(
            exit_code=0,
            message="Warning: prd.md not found, skipping PRD <-> Architecture mapping validation.",
        )

    try:
        prd_parser = PrdParser()
        prd_res = prd_parser.parse_file(prd_path)
    except Exception as e:
        return PathValidationResult(
            exit_code=0,
            message=f"Warning: 无法解析 PRD，跳过映射校验: {e}",
        )

    if not prd_res.requirements:
        return PathValidationResult(
            exit_code=0,
            message="Warning: PRD 中未发现需求，跳过映射校验。",
        )

    result = validate_prd_architecture_mapping(
        prd_res.requirements, constraints_data,
    )

    if result.has_dead_links:
        return PathValidationResult(
            exit_code=1,
            message=f"Error: 架构约束引用了 PRD 中不存在的需求: {', '.join(result.dead_links)}",
            result=result,
        )

    if result.has_must_uncovered:
        return PathValidationResult(
            exit_code=1,
            message=f"Error: 以下 MUST 级需求缺少架构支撑: {', '.join(result.must_uncovered)}",
            result=result,
        )

    if result.should_uncovered:
        return PathValidationResult(
            exit_code=0,
            message=f"Warning: 以下非 MUST 级需求缺少架构映射: {', '.join(result.should_uncovered)}",
            result=result,
        )

    return PathValidationResult(exit_code=0, result=result)
