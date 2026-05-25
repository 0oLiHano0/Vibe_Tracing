import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from collections import Counter


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
    acceptance_criteria: List[AcceptanceCriteria] = field(default_factory=list)


@dataclass
class PrdParseResult:
    requirements: List[Requirement] = field(default_factory=list)
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)


# Patterns
REQ_ID_PATTERN = re.compile(r"REQ-VT-\d+")
AC_ID_PATTERN = re.compile(r"AC-VT-\d+-\d+")
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")
TEST_REQ_PATTERN = re.compile(r"是否必须有测试[：:]\s*(是|否)")
TEST_REQ_LINE_PATTERN = re.compile(r"是否必须有测试")
PRIORITY_HEADING_PATTERN = re.compile(r"^####\s+优先级")


def clean_title(title: str) -> str:
    title = title.strip()
    while title and (title[0] in (":", "：") or title[0].isspace()):
        title = title[1:]
    while title and (title[-1] in (":", "：") or title[-1].isspace()):
        title = title[:-1]
    return title.strip()


def get_parent_req_id(ac_id: str) -> str:
    match = re.match(r"^AC-VT-(\d+)-(\d+)$", ac_id)
    if match:
        return f"REQ-VT-{match.group(1)}"
    raise ValueError(f"Invalid AC ID format: {ac_id}")


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
        lines = text.splitlines()

        requirements: List[Requirement] = []
        errors: List[str] = []
        is_valid = True

        # Track all ID occurrences in headings to check for duplicates
        all_req_ids_in_headings = []
        all_ac_ids_in_headings = []

        # First pass to check duplicate IDs and heading level mismatches
        for line in lines:
            heading_match = HEADING_PATTERN.match(line)
            if heading_match:
                level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()

                req_ids = REQ_ID_PATTERN.findall(heading_text)
                ac_ids = AC_ID_PATTERN.findall(heading_text)

                all_req_ids_in_headings.extend(req_ids)
                all_ac_ids_in_headings.extend(ac_ids)

                if req_ids and level != 3:
                    errors.append(
                        f"Requirement ID pattern found in heading of level {level}: {line.strip()}"
                    )
                    is_valid = False
                if ac_ids and level != 5:
                    errors.append(
                        f"AC ID pattern found in heading of level {level}: {line.strip()}"
                    )
                    is_valid = False

        # Duplicate ID check
        req_counts = Counter(all_req_ids_in_headings)
        for rid, count in req_counts.items():
            if count > 1:
                errors.append(f"Duplicate requirement ID: {rid}")
                is_valid = False

        ac_counts = Counter(all_ac_ids_in_headings)
        for aid, count in ac_counts.items():
            if count > 1:
                errors.append(f"Duplicate AC ID: {aid}")
                is_valid = False

        current_req: Optional[Requirement] = None
        priorities_processed = set()
        all_parsed_ac_ids = set()

        for i, line in enumerate(lines):
            heading_match = HEADING_PATTERN.match(line)
            if heading_match:
                level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()

                # Check if it's a valid requirement heading
                if level == 3:
                    req_match = REQ_ID_PATTERN.search(heading_text)
                    if req_match:
                        req_id = req_match.group(0)
                        title_part = heading_text[req_match.end() :]
                        title = clean_title(title_part)

                        # Create requirement
                        current_req = Requirement(
                            req_id=req_id,
                            title=title,
                            priority="unclear",
                            acceptance_criteria=[],
                        )
                        requirements.append(current_req)

                # Check if it's a valid AC heading
                elif level == 5:
                    ac_match = AC_ID_PATTERN.search(heading_text)
                    if ac_match:
                        ac_id = ac_match.group(0)
                        title_part = heading_text[ac_match.end() :]
                        title = clean_title(title_part)

                        all_parsed_ac_ids.add(ac_id)

                        # Parent-child mismatch check
                        expected_parent_id = get_parent_req_id(ac_id)
                        if (
                            current_req is None
                            or current_req.req_id != expected_parent_id
                        ):
                            active_req_id = current_req.req_id if current_req else None
                            errors.append(
                                f"AC {ac_id} is defined under incorrect requirement section "
                                f"(expected parent {expected_parent_id}, active requirement is {active_req_id})"
                            )
                            is_valid = False

                        # Parse testing requirement
                        # Search subsequent lines until next heading of any level
                        ac_lines = []
                        for j in range(i + 1, len(lines)):
                            nxt_line = lines[j]
                            if HEADING_PATTERN.match(nxt_line):
                                break
                            ac_lines.append(nxt_line)

                        is_testing_required = False
                        test_req_line_found = False
                        for ac_line in ac_lines:
                            if TEST_REQ_LINE_PATTERN.search(ac_line):
                                test_req_line_found = True
                                test_match = TEST_REQ_PATTERN.search(ac_line)
                                if test_match:
                                    is_testing_required = test_match.group(1) == "是"
                                else:
                                    errors.append(
                                        f"AC {ac_id} has invalid or different value for testing requirement in line: {ac_line.strip()}"
                                    )
                                    is_valid = False
                                break

                        if not test_req_line_found:
                            errors.append(
                                f"AC {ac_id} is missing '是否必须有测试' line"
                            )
                            is_valid = False

                        ac_obj = AcceptanceCriteria(
                            ac_id=ac_id,
                            title=title,
                            is_testing_required=is_testing_required,
                        )

                        if current_req:
                            current_req.acceptance_criteria.append(ac_obj)

                # Check for priority heading under the active requirement
                elif level == 4 and PRIORITY_HEADING_PATTERN.match(line):
                    if current_req:
                        priorities_processed.add(current_req.req_id)
                        # Find first non-blank line
                        priority_val = None
                        for j in range(i + 1, len(lines)):
                            nxt_line = lines[j]
                            stripped_nxt = nxt_line.strip()
                            if not stripped_nxt:
                                continue
                            if HEADING_PATTERN.match(nxt_line):
                                break
                            priority_val = stripped_nxt
                            break

                        if priority_val:
                            val_lower = priority_val.lower()
                            if val_lower in ("must", "should", "could"):
                                current_req.priority = val_lower
                            else:
                                errors.append(
                                    f"Invalid priority '{priority_val}' for requirement {current_req.req_id}"
                                )
                                current_req.priority = "unclear"
                                is_valid = False
                        else:
                            errors.append(
                                f"Priority not found for requirement {current_req.req_id}"
                            )
                            current_req.priority = "unclear"
                            is_valid = False

        # Post-parse checks: check if any requirement's priority heading is missing
        for req in requirements:
            if req.req_id not in priorities_processed:
                errors.append(f"Priority not found for requirement {req.req_id}")
                req.priority = "unclear"
                is_valid = False

        # Missing parent requirement check
        parsed_req_ids = {req.req_id for req in requirements}
        for ac_id in all_parsed_ac_ids:
            parent_id = get_parent_req_id(ac_id)
            if parent_id not in parsed_req_ids:
                errors.append(
                    f"Parent requirement {parent_id} for AC {ac_id} is missing from the document"
                )
                is_valid = False

        # Double check in case any errors were added but is_valid was not set to False
        if errors:
            is_valid = False

        return PrdParseResult(
            requirements=requirements, is_valid=is_valid, errors=errors
        )
