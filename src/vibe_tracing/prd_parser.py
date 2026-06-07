import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from collections import Counter

import mistune


@dataclass
class AcceptanceCriteria:
    ac_id: str  # e.g., "AC-VT-001-01"
    title: str  # e.g., "需求必须能关联任务"
    is_testing_required: bool  # True for "是", False for "否", or False/default if invalid/unclear (with error flagged)


@dataclass
class Requirement:
    req_id: str  # e.g., "REQ-VT-001"
    title: str  # e.g., "全链路需求追踪"
    priority: str  # "must", "should", "could", or "unclear" (lowercase)
    category: str  # "functional" or "quality_evolution" (required, no default)
    acceptance_criteria: List[AcceptanceCriteria] = field(default_factory=list)


@dataclass
class PrdParseResult:
    requirements: List[Requirement] = field(default_factory=list)
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    status: str = "active"
    project_name: Optional[str] = None
    project_id: Optional[str] = None


# Module-level mistune AST parser (reusable, stateless)
_md = mistune.create_markdown(renderer="ast")


def parse_front_matter(text: str) -> dict:
    """Parse YAML-like front matter from the top of the markdown text."""
    metadata = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return metadata

    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx == -1:
        return metadata

    for i in range(1, end_idx):
        line = lines[i].strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Remove quotes
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            metadata[key] = val
    return metadata


def _strip_front_matter(text: str) -> str:
    """Remove the YAML front matter block so mistune receives clean Markdown."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1:])
    return text


def clean_title(title: str) -> str:
    title = title.strip()
    while title and (title[0] in (":", "：") or title[0].isspace()):
        title = title[1:]
    while title and (title[-1] in (":", "：") or title[-1].isspace()):
        title = title[:-1]
    return title.strip()


def get_parent_req_id(ac_id: str) -> str:
    match = re.match(r"^AC-([a-zA-Z0-9_-]+)-(\d+)-(\d+)$", ac_id)
    if match:
        return f"REQ-{match.group(1)}-{match.group(2)}"
    raise ValueError(f"Invalid AC ID format: {ac_id}")


def _extract_text(token: dict) -> str:
    """Recursively extract plain text from a mistune AST token."""
    if token.get("type") in ("text", "codespan", "raw_html"):
        return token.get("raw", "")
    children = token.get("children") or []
    return "".join(_extract_text(c) for c in children)


def _list_item_texts(list_token: dict) -> List[str]:
    """Return the plain text of each direct list_item in a list token."""
    return [
        _extract_text(item).strip()
        for item in (list_token.get("children") or [])
        if item.get("type") == "list_item"
    ]


def _apply_test_req(
    lines: List[str],
    ac: "AcceptanceCriteria",
    ac_test_found: set,
    errors: List[str],
) -> bool:
    """Check a sequence of text lines for '是否必须有测试'. Returns True if the
    field was found (valid or invalid), False if the field was absent."""
    for line in lines:
        if "是否必须有测试" not in line:
            continue
        ac_test_found.add(id(ac))
        if re.search(r"是否必须有测试[：:]\s*是", line):
            ac.is_testing_required = True
        elif re.search(r"是否必须有测试[：:]\s*否", line):
            ac.is_testing_required = False
        else:
            errors.append(
                f"AC {ac.ac_id} has invalid or different value "
                f"for testing requirement in line: {line}"
            )
        return True
    return False


class PrdParser:
    """Parses Vibe Tracing PRD Markdown files to extract requirements and ACs."""

    def parse_file(self, file_path: Path) -> PrdParseResult:
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception as e:
            return PrdParseResult(
                requirements=[],
                is_valid=False,
                errors=[f"Failed to read file {file_path}: {e}"],
            )
        return self.parse_text(text)

    def parse_text(self, text: str) -> PrdParseResult:
        metadata = parse_front_matter(text)
        prd_prefix = metadata.get("project_abbreviation") or metadata.get("project_prefix") or "VT"
        status = metadata.get("status") or "active"

        from vibe_tracing.core import ids
        prefix = ids.get_project_prefix()

        # Domain-specific ID patterns (not generic Markdown structure)
        # REQ IDs can be either REQ-{prefix}-\d+ or Q-\d+ (quality evolution)
        req_id_pattern = re.compile(rf"(?:REQ-{prefix}-\d+|Q-\d+)")
        ac_id_pattern = re.compile(rf"AC-{prefix}-\d+-\d+")

        # Build AST from body (front matter stripped so mistune won't misparse ---)
        body_text = _strip_front_matter(text)
        tokens = _md(body_text) or []

        requirements: List[Requirement] = []
        errors: List[str] = []
        is_valid = True

        # Tracking sets / lists for post-parse validation
        all_req_ids_seen: List[str] = []
        all_ac_ids_seen: List[str] = []
        all_parsed_ac_ids: set = set()
        priorities_processed: set = set()
        categories_processed: set = set()
        ac_test_found: set = set()  # set of id(AcceptanceCriteria) objects

        # State machine context (single pass)
        current_req: Optional[Requirement] = None
        expect_priority: bool = False
        expect_category: bool = False
        current_ac: Optional[AcceptanceCriteria] = None

        for token in tokens:
            ttype = token.get("type")

            # ── HEADING ──────────────────────────────────────────────────────
            if ttype == "heading":
                level: int = token["attrs"]["level"]
                heading_text: str = _extract_text(token).strip()

                # A new heading always resets expect_priority and expect_category;
                # missing values (if any) are caught in the post-parse check below.
                expect_priority = False
                expect_category = False

                req_ids = req_id_pattern.findall(heading_text)
                ac_ids = ac_id_pattern.findall(heading_text)

                # Level-mismatch structural validation
                if req_ids and level != 3:
                    errors.append(
                        f"Requirement ID pattern found in heading of level {level}: "
                        f"{'#' * level} {heading_text}"
                    )
                    is_valid = False
                if ac_ids and level != 5:
                    errors.append(
                        f"AC ID pattern found in heading of level {level}: "
                        f"{'#' * level} {heading_text}"
                    )
                    is_valid = False

                all_req_ids_seen.extend(req_ids)
                all_ac_ids_seen.extend(ac_ids)

                if level == 3 and req_ids:
                    req_id = req_ids[0]
                    title_part = heading_text[heading_text.index(req_id) + len(req_id):]
                    current_req = Requirement(
                        req_id=req_id,
                        title=clean_title(title_part),
                        priority="unclear",
                        category="unclear",
                        acceptance_criteria=[],
                    )
                    requirements.append(current_req)
                    current_ac = None

                elif level == 4 and "优先级" in heading_text and current_req:
                    expect_priority = True
                    current_ac = None

                elif level == 4 and "类别" in heading_text and current_req:
                    expect_category = True
                    current_ac = None

                elif level == 5 and ac_ids:
                    ac_id = ac_ids[0]
                    title_part = heading_text[heading_text.index(ac_id) + len(ac_id):]

                    all_parsed_ac_ids.add(ac_id)

                    # Parent-child relationship check
                    expected_parent_id = get_parent_req_id(ac_id)
                    if current_req is None or current_req.req_id != expected_parent_id:
                        active_req_id = current_req.req_id if current_req else None
                        errors.append(
                            f"AC {ac_id} is defined under incorrect requirement section "
                            f"(expected parent {expected_parent_id}, active requirement is {active_req_id})"
                        )
                        is_valid = False

                    current_ac = AcceptanceCriteria(
                        ac_id=ac_id,
                        title=clean_title(title_part),
                        is_testing_required=False,
                    )
                    if current_req:
                        current_req.acceptance_criteria.append(current_ac)

                elif level <= 2:
                    # Top-level heading resets all section state
                    current_req = None
                    current_ac = None

                elif level in (3, 4) and not req_ids and not ac_ids:
                    # Non-REQ/AC heading: exit current AC scope
                    if level == 3:
                        current_req = None
                    current_ac = None

            # ── PARAGRAPH (priority value) ────────────────────────────────────
            elif ttype == "paragraph" and expect_priority and current_req:
                priority_val = _extract_text(token).strip()
                val_lower = priority_val.lower()
                expect_priority = False
                priorities_processed.add(current_req.req_id)

                if val_lower in ("must", "should", "could"):
                    current_req.priority = val_lower
                else:
                    errors.append(
                        f"Invalid priority '{priority_val}' for requirement {current_req.req_id}"
                    )
                    current_req.priority = "unclear"
                    is_valid = False

            # ── PARAGRAPH (category value) ────────────────────────────────────
            elif ttype == "paragraph" and expect_category and current_req:
                category_val = _extract_text(token).strip()
                val_lower = category_val.lower()
                expect_category = False
                categories_processed.add(current_req.req_id)

                if val_lower in ("functional", "quality_evolution"):
                    current_req.category = val_lower
                else:
                    errors.append(
                        f"Invalid category '{category_val}' for requirement {current_req.req_id}"
                    )
                    current_req.category = "unclear"
                    is_valid = False

            # ── LIST or PARAGRAPH (AC body: 是否必须有测试) ─────────────────
            # Both list items (*/-) and bare paragraph lines are accepted;
            # the old regex engine matched any line regardless of list syntax.
            elif ttype in ("list", "paragraph") and current_ac is not None:
                if ttype == "list":
                    candidates = _list_item_texts(token)
                else:
                    candidates = [_extract_text(token).strip()]
                found = _apply_test_req(candidates, current_ac, ac_test_found, errors)
                if found and id(current_ac) not in ac_test_found:
                    # _apply_test_req added an error for an invalid value
                    is_valid = False

        # ── POST-PARSE CHECKS ─────────────────────────────────────────────────

        # Missing 是否必须有测试 field in any AC
        for req in requirements:
            for ac in req.acceptance_criteria:
                if id(ac) not in ac_test_found:
                    errors.append(f"AC {ac.ac_id} is missing '是否必须有测试' line")
                    is_valid = False

        # Missing priority section for any requirement
        for req in requirements:
            if req.req_id not in priorities_processed:
                errors.append(f"Priority not found for requirement {req.req_id}")
                req.priority = "unclear"
                is_valid = False

        # Missing category section for any requirement
        for req in requirements:
            if req.req_id not in categories_processed:
                errors.append(f"Category not found for requirement {req.req_id}")
                req.category = "unclear"
                is_valid = False

        # Q-pattern REQ should have quality_evolution category (warning)
        for req in requirements:
            if re.match(r"Q-\d+", req.req_id) and req.category != "quality_evolution":
                errors.append(
                    f"WARNING: Requirement {req.req_id} matches Q-\\d+ pattern "
                    f"but category is '{req.category}' (expected 'quality_evolution')"
                )

        # Duplicate requirement IDs
        for rid, count in Counter(all_req_ids_seen).items():
            if count > 1:
                errors.append(f"Duplicate requirement ID: {rid}")
                is_valid = False

        # Duplicate AC IDs
        for aid, count in Counter(all_ac_ids_seen).items():
            if count > 1:
                errors.append(f"Duplicate AC ID: {aid}")
                is_valid = False

        # AC references a parent requirement that doesn't exist in this document
        parsed_req_ids = {req.req_id for req in requirements}
        for ac_id in all_parsed_ac_ids:
            parent_id = get_parent_req_id(ac_id)
            if parent_id not in parsed_req_ids:
                errors.append(
                    f"Parent requirement {parent_id} for AC {ac_id} is missing from the document"
                )
                is_valid = False

        if errors:
            is_valid = False

        return PrdParseResult(
            requirements=requirements,
            is_valid=is_valid,
            errors=errors,
            status=status,
            project_name=metadata.get("project_name"),
            project_id=f"PROJECT-{prd_prefix}",
        )
