"""Tests for prd_arch_validator — reusable PRD<->Architecture mapping validation."""

import pytest
from dataclasses import dataclass, field
from typing import List

from vibe_tracing.prd_arch_validator import (
    MappingResult,
    PathValidationResult,
    validate_prd_architecture_mapping,
    validate_prd_architecture_mapping_from_path,
    _collect_related_reqs,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

@dataclass
class _FakeRequirement:
    """Minimal stand-in for prd_parser.Requirement."""
    req_id: str
    priority: str  # "must", "should", "could"
    title: str = ""
    acceptance_criteria: List = field(default_factory=list)


# ── _collect_related_reqs unit tests ────────────────────────────────────────

def test_collect_related_reqs_from_dict():
    data = {
        "design_rules": [
            {"rule_id": "D1", "related_requirements": ["REQ-001", "REQ-002"]},
            {"rule_id": "D2", "related_requirements": ["REQ-003"]},
        ]
    }
    assert _collect_related_reqs(data) == {"REQ-001", "REQ-002", "REQ-003"}


def test_collect_related_reqs_from_nested():
    data = {
        "top_key": {
            "nested": {
                "related_requirements": ["REQ-100"],
            },
            "related_requirements": ["REQ-200"],
        }
    }
    assert _collect_related_reqs(data) == {"REQ-100", "REQ-200"}


def test_collect_related_reqs_from_list():
    data = [
        {"related_requirements": ["REQ-A"]},
        {"related_requirements": ["REQ-B"]},
    ]
    assert _collect_related_reqs(data) == {"REQ-A", "REQ-B"}


def test_collect_related_reqs_empty():
    assert _collect_related_reqs({}) == set()
    assert _collect_related_reqs([]) == set()


# ── MappingResult properties ────────────────────────────────────────────────

def test_mapping_result_defaults():
    r = MappingResult()
    assert r.has_dead_links is False
    assert r.has_must_uncovered is False
    assert r.is_valid is True


def test_mapping_result_with_dead_links():
    r = MappingResult(dead_links=["REQ-999"])
    assert r.has_dead_links is True
    assert r.is_valid is False


def test_mapping_result_with_must_uncovered():
    r = MappingResult(must_uncovered=["REQ-001"])
    assert r.has_must_uncovered is True
    assert r.is_valid is False


def test_mapping_result_with_only_should_uncovered():
    r = MappingResult(should_uncovered=["REQ-002"])
    assert r.is_valid is True


# ── validate_prd_architecture_mapping ───────────────────────────────────────

def test_dead_link_detected():
    """Constraints reference REQ-VT-999 but PRD doesn't have it."""
    prd_reqs = [_FakeRequirement("REQ-VT-001", "must")]
    constraints = {
        "design_rules": [
            {
                "rule_id": "D1",
                "related_requirements": ["REQ-VT-999"],
            }
        ]
    }

    result = validate_prd_architecture_mapping(prd_reqs, constraints)

    assert result.has_dead_links is True
    assert "REQ-VT-999" in result.dead_links
    assert result.is_valid is False


def test_must_uncovered():
    """PRD has MUST REQ but constraints have no matching module."""
    prd_reqs = [
        _FakeRequirement("REQ-VT-001", "must"),
        _FakeRequirement("REQ-VT-002", "must"),
    ]
    constraints = {
        "design_rules": [
            {
                "rule_id": "D1",
                "related_requirements": ["REQ-VT-001"],
            }
        ]
    }

    result = validate_prd_architecture_mapping(prd_reqs, constraints)

    assert result.has_dead_links is False
    assert result.has_must_uncovered is True
    assert "REQ-VT-002" in result.must_uncovered
    assert result.is_valid is False


def test_should_uncovered_only_warning():
    """PRD has SHOULD REQ without mapping -> should_uncovered non-empty but is_valid True."""
    prd_reqs = [
        _FakeRequirement("REQ-VT-001", "must"),
        _FakeRequirement("REQ-VT-002", "should"),
    ]
    constraints = {
        "design_rules": [
            {
                "rule_id": "D1",
                "related_requirements": ["REQ-VT-001"],
            }
        ]
    }

    result = validate_prd_architecture_mapping(prd_reqs, constraints)

    assert result.has_dead_links is False
    assert result.has_must_uncovered is False
    assert len(result.should_uncovered) == 1
    assert "REQ-VT-002" in result.should_uncovered
    assert result.is_valid is True


def test_all_valid():
    """All mappings correct -> is_valid True, all lists empty."""
    prd_reqs = [
        _FakeRequirement("REQ-VT-001", "must"),
        _FakeRequirement("REQ-VT-002", "must"),
    ]
    constraints = {
        "design_rules": [
            {
                "rule_id": "D1",
                "related_requirements": ["REQ-VT-001"],
            },
            {
                "rule_id": "D2",
                "related_requirements": ["REQ-VT-002"],
            },
        ]
    }

    result = validate_prd_architecture_mapping(prd_reqs, constraints)

    assert result.has_dead_links is False
    assert result.has_must_uncovered is False
    assert result.should_uncovered == []
    assert result.is_valid is True


def test_empty_prd_requirements():
    """No PRD requirements -> no validation issues."""
    result = validate_prd_architecture_mapping([], {"design_rules": []})

    assert result.dead_links == []
    assert result.must_uncovered == []
    assert result.should_uncovered == []
    assert result.is_valid is True


def test_empty_constraints():
    """Constraints with no related_requirements sections."""
    prd_reqs = [_FakeRequirement("REQ-VT-001", "must")]
    constraints = {"project": {"language": "python"}}

    result = validate_prd_architecture_mapping(prd_reqs, constraints)

    assert result.has_dead_links is False
    assert result.has_must_uncovered is True
    assert "REQ-VT-002" not in result.must_uncovered
    assert "REQ-VT-001" in result.must_uncovered


def test_could_level_uncovered():
    """COULD-level REQ without mapping -> appears in should_uncovered."""
    prd_reqs = [
        _FakeRequirement("REQ-VT-001", "must"),
        _FakeRequirement("REQ-VT-003", "could"),
    ]
    constraints = {
        "design_rules": [
            {
                "rule_id": "D1",
                "related_requirements": ["REQ-VT-001"],
            }
        ]
    }

    result = validate_prd_architecture_mapping(prd_reqs, constraints)

    assert result.is_valid is True
    assert "REQ-VT-003" in result.should_uncovered


def test_multiple_dead_links_sorted():
    """Multiple dead links are returned sorted."""
    prd_reqs = [_FakeRequirement("REQ-VT-001", "must")]
    constraints = {
        "design_rules": [
            {"rule_id": "D1", "related_requirements": ["REQ-VT-999", "REQ-VT-100"]},
        ]
    }

    result = validate_prd_architecture_mapping(prd_reqs, constraints)

    assert result.dead_links == ["REQ-VT-100", "REQ-VT-999"]


def test_nested_constraints_structure():
    """Constraints with nested dicts still extract related_requirements correctly."""
    prd_reqs = [_FakeRequirement("REQ-VT-001", "must")]
    constraints = {
        "module_boundaries": [
            {
                "rule_id": "MOD-001",
                "modules": {
                    "core": {
                        "related_requirements": ["REQ-VT-001"],
                    }
                },
            }
        ]
    }

    result = validate_prd_architecture_mapping(prd_reqs, constraints)

    # The nested related_requirements are found by _collect_related_reqs (for dead link check)
    # but NOT by the top-level section scan (covered_reqs), so it counts as uncovered
    assert result.has_dead_links is False
    assert result.has_must_uncovered is True


def test_project_prefix_unused():
    """project_prefix parameter has no effect on results (API symmetry)."""
    prd_reqs = [_FakeRequirement("REQ-VT-001", "must")]
    constraints = {
        "design_rules": [
            {"rule_id": "D1", "related_requirements": ["REQ-VT-001"]},
        ]
    }

    r1 = validate_prd_architecture_mapping(prd_reqs, constraints, project_prefix="VT")
    r2 = validate_prd_architecture_mapping(prd_reqs, constraints, project_prefix="OTHER")

    assert r1.is_valid == r2.is_valid
    assert r1.must_uncovered == r2.must_uncovered


# ── AC-VT-009-15: PRD<->Architecture mapping validation during analyze ────

class TestACVT00915MappingValidation:
    """Tests satisfying AC-VT-009-15 acceptance criteria."""

    def test_dead_link_detection(self):
        """Constraints referencing non-existent REQs should be detected.

        AC-VT-009-15 requirement 1: Dead link detection — constraints
        referencing REQs that don't exist in PRD → BLOCKED.
        """
        prd_reqs = [_FakeRequirement("REQ-VT-001", "must")]
        constraints = {
            "design_rules": [
                {"rule_id": "D1", "related_requirements": ["REQ-VT-002"]},
            ]
        }

        result = validate_prd_architecture_mapping(prd_reqs, constraints)

        assert result.has_dead_links is True
        assert "REQ-VT-002" in result.dead_links
        assert result.is_valid is False

    def test_dead_link_detection_multiple(self):
        """Multiple dead links from different constraint sections are all detected."""
        prd_reqs = [_FakeRequirement("REQ-VT-001", "must")]
        constraints = {
            "design_rules": [
                {"rule_id": "D1", "related_requirements": ["REQ-VT-999"]},
            ],
            "module_boundaries": [
                {"rule_id": "MOD-001", "related_requirements": ["REQ-VT-888"]},
            ],
        }

        result = validate_prd_architecture_mapping(prd_reqs, constraints)

        assert result.has_dead_links is True
        assert set(result.dead_links) == {"REQ-VT-888", "REQ-VT-999"}
        assert result.is_valid is False

    def test_must_coverage_detection(self):
        """MUST-level constraint items must be covered by PRD.

        AC-VT-009-15 requirement 2: MUST coverage detection — MUST-level
        items in constraints must be covered.
        """
        prd_reqs = [_FakeRequirement("REQ-VT-001", "must")]
        constraints = {
            "design_rules": [
                {"rule_id": "D1", "related_requirements": ["REQ-VT-001"]},
            ]
        }

        result = validate_prd_architecture_mapping(prd_reqs, constraints)

        assert result.has_must_uncovered is False
        assert result.must_uncovered == []
        assert result.is_valid is True

    def test_must_uncovered_detected(self):
        """MUST-level REQ without architecture mapping triggers validation failure."""
        prd_reqs = [
            _FakeRequirement("REQ-VT-001", "must"),
            _FakeRequirement("REQ-VT-002", "must"),
        ]
        constraints = {
            "design_rules": [
                {"rule_id": "D1", "related_requirements": ["REQ-VT-001"]},
            ]
        }

        result = validate_prd_architecture_mapping(prd_reqs, constraints)

        assert result.has_dead_links is False
        assert result.has_must_uncovered is True
        assert "REQ-VT-002" in result.must_uncovered
        assert result.is_valid is False

    def test_valid_mapping_passes(self):
        """Valid PRD<->Arch mapping should pass validation.

        AC-VT-009-15: No dead links, all MUST REQs covered → is_valid True.
        """
        prd_reqs = [
            _FakeRequirement("REQ-VT-001", "must"),
            _FakeRequirement("REQ-VT-002", "should"),
        ]
        constraints = {
            "design_rules": [
                {"rule_id": "D1", "related_requirements": ["REQ-VT-001", "REQ-VT-002"]},
            ]
        }

        result = validate_prd_architecture_mapping(prd_reqs, constraints)

        assert result.dead_links == []
        assert result.must_uncovered == []
        assert result.should_uncovered == []
        assert result.is_valid is True

    def test_valid_mapping_passes_with_mixed_sections(self):
        """Valid mapping across multiple constraint sections."""
        prd_reqs = [
            _FakeRequirement("REQ-VT-001", "must"),
            _FakeRequirement("REQ-VT-002", "must"),
            _FakeRequirement("REQ-VT-003", "should"),
        ]
        constraints = {
            "design_rules": [
                {"rule_id": "D1", "related_requirements": ["REQ-VT-001"]},
            ],
            "module_boundaries": [
                {"rule_id": "MOD-001", "related_requirements": ["REQ-VT-002", "REQ-VT-003"]},
            ],
        }

        result = validate_prd_architecture_mapping(prd_reqs, constraints)

        assert result.is_valid is True
        assert result.dead_links == []
        assert result.must_uncovered == []
        assert result.should_uncovered == []


# ── Additional edge-case tests ─────────────────────────────────────────────

class TestDeadLinkEdgeCases:
    """Additional dead link detection scenarios."""

    def test_dead_link_in_nested_structure_detected(self):
        """Dead links inside nested dicts are still detected via _collect_related_reqs."""
        prd_reqs = [_FakeRequirement("REQ-VT-001", "must")]
        constraints = {
            "module_boundaries": [
                {
                    "rule_id": "MOD-001",
                    "modules": {
                        "core": {
                            "related_requirements": ["REQ-VT-001"],
                        },
                        "plugin": {
                            "related_requirements": ["REQ-VT-MISSING"],
                        },
                    },
                }
            ]
        }

        result = validate_prd_architecture_mapping(prd_reqs, constraints)

        assert result.has_dead_links is True
        assert "REQ-VT-MISSING" in result.dead_links

    def test_no_dead_links_when_all_reqs_exist(self):
        """No dead links when every constraint reference maps to an existing PRD REQ."""
        prd_reqs = [
            _FakeRequirement("REQ-VT-001", "must"),
            _FakeRequirement("REQ-VT-002", "should"),
            _FakeRequirement("REQ-VT-003", "could"),
        ]
        constraints = {
            "design_rules": [
                {"rule_id": "D1", "related_requirements": ["REQ-VT-001", "REQ-VT-002"]},
                {"rule_id": "D2", "related_requirements": ["REQ-VT-003"]},
            ]
        }

        result = validate_prd_architecture_mapping(prd_reqs, constraints)

        assert result.dead_links == []
        assert result.has_dead_links is False


class TestMustCoverageEdgeCases:
    """Additional MUST-level coverage scenarios."""

    def test_partial_must_coverage(self):
        """Some MUST REQs covered, some not -- uncovered list only has the missing ones."""
        prd_reqs = [
            _FakeRequirement("REQ-VT-001", "must"),
            _FakeRequirement("REQ-VT-002", "must"),
            _FakeRequirement("REQ-VT-003", "must"),
        ]
        constraints = {
            "design_rules": [
                {"rule_id": "D1", "related_requirements": ["REQ-VT-001", "REQ-VT-003"]},
            ]
        }

        result = validate_prd_architecture_mapping(prd_reqs, constraints)

        assert result.has_must_uncovered is True
        assert result.must_uncovered == ["REQ-VT-002"]

    def test_all_must_covered_should_uncovered(self):
        """All MUST REQs covered but SHOULD REQs uncovered -> is_valid True."""
        prd_reqs = [
            _FakeRequirement("REQ-VT-001", "must"),
            _FakeRequirement("REQ-VT-002", "should"),
            _FakeRequirement("REQ-VT-003", "could"),
        ]
        constraints = {
            "design_rules": [
                {"rule_id": "D1", "related_requirements": ["REQ-VT-001"]},
            ]
        }

        result = validate_prd_architecture_mapping(prd_reqs, constraints)

        assert result.has_dead_links is False
        assert result.has_must_uncovered is False
        assert result.is_valid is True
        assert set(result.should_uncovered) == {"REQ-VT-002", "REQ-VT-003"}

    def test_all_must_and_should_covered(self):
        """All MUST and SHOULD REQs covered -> no issues."""
        prd_reqs = [
            _FakeRequirement("REQ-VT-001", "must"),
            _FakeRequirement("REQ-VT-002", "should"),
        ]
        constraints = {
            "design_rules": [
                {"rule_id": "D1", "related_requirements": ["REQ-VT-001", "REQ-VT-002"]},
            ]
        }

        result = validate_prd_architecture_mapping(prd_reqs, constraints)

        assert result.is_valid is True
        assert result.must_uncovered == []
        assert result.should_uncovered == []

    def test_must_covered_across_multiple_sections(self):
        """MUST REQs can be covered by different constraint sections."""
        prd_reqs = [
            _FakeRequirement("REQ-VT-001", "must"),
            _FakeRequirement("REQ-VT-002", "must"),
            _FakeRequirement("REQ-VT-003", "must"),
        ]
        constraints = {
            "design_rules": [
                {"rule_id": "D1", "related_requirements": ["REQ-VT-001"]},
            ],
            "module_boundaries": [
                {"rule_id": "MOD-001", "related_requirements": ["REQ-VT-002", "REQ-VT-003"]},
            ],
        }

        result = validate_prd_architecture_mapping(prd_reqs, constraints)

        assert result.is_valid is True
        assert result.must_uncovered == []


class TestConstraintStructureEdgeCases:
    """Tests for unusual constraint structures."""

    def test_empty_list_in_constraint_section(self):
        """A constraint section that is an empty list contributes no coverage."""
        prd_reqs = [_FakeRequirement("REQ-VT-001", "must")]
        constraints = {
            "design_rules": [],
        }

        result = validate_prd_architecture_mapping(prd_reqs, constraints)

        assert result.has_dead_links is False
        assert result.has_must_uncovered is True
        assert "REQ-VT-001" in result.must_uncovered

    def test_constraint_list_item_without_related_requirements(self):
        """List items without 'related_requirements' key don't contribute coverage."""
        prd_reqs = [_FakeRequirement("REQ-VT-001", "must")]
        constraints = {
            "design_rules": [
                {"rule_id": "D1", "description": "Some rule without req mapping"},
            ]
        }

        result = validate_prd_architecture_mapping(prd_reqs, constraints)

        assert result.has_dead_links is False
        assert result.has_must_uncovered is True
        assert "REQ-VT-001" in result.must_uncovered

    def test_non_list_constraint_section_ignored_for_coverage(self):
        """Dict-typed constraint sections don't count toward top-level coverage."""
        prd_reqs = [_FakeRequirement("REQ-VT-001", "must")]
        constraints = {
            "project": {"language": "python", "related_requirements": ["REQ-VT-001"]},
        }

        result = validate_prd_architecture_mapping(prd_reqs, constraints)

        # No dead link (nested related_requirements found by _collect_related_reqs)
        assert result.has_dead_links is False
        # But not counted as covered (only top-level list sections count)
        assert result.has_must_uncovered is True
        assert "REQ-VT-001" in result.must_uncovered

    def test_mixed_valid_and_dead_links(self):
        """Mix of valid and dead links -- only dead ones appear in dead_links."""
        prd_reqs = [_FakeRequirement("REQ-VT-001", "must")]
        constraints = {
            "design_rules": [
                {
                    "rule_id": "D1",
                    "related_requirements": ["REQ-VT-001", "REQ-VT-GHOST"],
                }
            ]
        }

        result = validate_prd_architecture_mapping(prd_reqs, constraints)

        assert result.has_dead_links is True
        assert result.dead_links == ["REQ-VT-GHOST"]
        assert result.is_valid is False


class TestCollectRelatedReqsEdgeCases:
    """Additional _collect_related_reqs edge cases."""

    def test_collect_from_mixed_structure(self):
        """Mixed dict and list nesting is traversed correctly."""
        data = {
            "section_a": [
                {"related_requirements": ["REQ-1"]},
                {"nested": {"related_requirements": ["REQ-2"]}},
            ],
            "section_b": {
                "related_requirements": ["REQ-3"],
            },
        }
        assert _collect_related_reqs(data) == {"REQ-1", "REQ-2", "REQ-3"}

    def test_collect_with_duplicate_reqs(self):
        """Duplicate related_requirements IDs are deduplicated."""
        data = {
            "a": [{"related_requirements": ["REQ-1", "REQ-2"]}],
            "b": [{"related_requirements": ["REQ-2", "REQ-3"]}],
        }
        assert _collect_related_reqs(data) == {"REQ-1", "REQ-2", "REQ-3"}

    def test_collect_string_values_ignored(self):
        """String values (not dicts or lists) are safely ignored."""
        data = {"key": "just a string", "other": 42}
        assert _collect_related_reqs(data) == set()

    def test_collect_empty_related_requirements(self):
        """Empty related_requirements list contributes nothing."""
        data = {"rules": [{"related_requirements": []}]}
        assert _collect_related_reqs(data) == set()


class TestMappingResultPropertyEdgeCases:
    """Additional MappingResult property tests."""

    def test_both_dead_links_and_must_uncovered(self):
        """Both dead links and MUST uncovered -> is_valid False."""
        r = MappingResult(dead_links=["REQ-999"], must_uncovered=["REQ-001"])
        assert r.has_dead_links is True
        assert r.has_must_uncovered is True
        assert r.is_valid is False

    def test_should_uncovered_property(self):
        """should_uncovered property reflects the list content."""
        r = MappingResult(should_uncovered=["REQ-003", "REQ-004"])
        assert len(r.should_uncovered) == 2
        assert r.is_valid is True  # should_uncovered alone doesn't make it invalid


# ── validate_prd_architecture_mapping_from_path tests ──────────────────────

class TestValidateFromPath:
    """Tests for the file-I/O variant validate_prd_architecture_mapping_from_path."""

    def test_prd_not_found_returns_skip(self, tmp_path):
        """When prd.md doesn't exist, returns exit_code=0 with a warning message."""
        from unittest.mock import patch, MagicMock

        project_root = tmp_path
        constraints_data = {"design_rules": []}

        result = validate_prd_architecture_mapping_from_path(project_root, constraints_data)

        assert result.exit_code == 0
        assert result.message is not None
        assert "prd.md not found" in result.message

    def test_parse_error_returns_skip(self, tmp_path):
        """When PRD parsing raises, returns exit_code=0 with error message."""
        from unittest.mock import patch, MagicMock

        prd_path = tmp_path / "docs" / "prd.md"
        prd_path.parent.mkdir(parents=True, exist_ok=True)
        prd_path.write_text("# Invalid PRD")

        with patch("vibe_tracing.prd_parser.PrdParser") as mock_parser_cls:
            mock_parser_cls.return_value.parse_file.side_effect = Exception("parse error")

            result = validate_prd_architecture_mapping_from_path(
                tmp_path, {"design_rules": []}
            )

        assert result.exit_code == 0
        assert result.message is not None
        assert "parse error" in result.message

    def test_empty_requirements_returns_skip(self, tmp_path):
        """When PRD has no requirements, returns exit_code=0 with skip message."""
        from unittest.mock import patch, MagicMock
        from vibe_tracing.prd_parser import PrdParseResult

        prd_path = tmp_path / "docs" / "prd.md"
        prd_path.parent.mkdir(parents=True, exist_ok=True)
        prd_path.write_text("# PRD with no requirements")

        mock_result = PrdParseResult(requirements=[])

        with patch("vibe_tracing.prd_parser.PrdParser") as mock_parser_cls:
            mock_parser_cls.return_value.parse_file.return_value = mock_result

            result = validate_prd_architecture_mapping_from_path(
                tmp_path, {"design_rules": []}
            )

        assert result.exit_code == 0
        assert result.message is not None
        assert "未发现需求" in result.message

    def test_dead_link_returns_exit_code_1(self, tmp_path):
        """When dead links detected, returns exit_code=1."""
        from unittest.mock import patch
        from vibe_tracing.prd_parser import PrdParseResult

        prd_path = tmp_path / "docs" / "prd.md"
        prd_path.parent.mkdir(parents=True, exist_ok=True)
        prd_path.write_text("# PRD")

        fake_req = _FakeRequirement("REQ-VT-001", "must")
        mock_result = PrdParseResult(requirements=[fake_req])

        with patch("vibe_tracing.prd_parser.PrdParser") as mock_parser_cls:
            mock_parser_cls.return_value.parse_file.return_value = mock_result

            constraints = {
                "design_rules": [
                    {"rule_id": "D1", "related_requirements": ["REQ-VT-GHOST"]},
                ]
            }
            result = validate_prd_architecture_mapping_from_path(tmp_path, constraints)

        assert result.exit_code == 1
        assert result.message is not None
        assert "REQ-VT-GHOST" in result.message
        assert result.result is not None
        assert result.result.has_dead_links is True

    def test_must_uncovered_returns_exit_code_1(self, tmp_path):
        """When MUST REQs uncovered, returns exit_code=1."""
        from unittest.mock import patch
        from vibe_tracing.prd_parser import PrdParseResult

        prd_path = tmp_path / "docs" / "prd.md"
        prd_path.parent.mkdir(parents=True, exist_ok=True)
        prd_path.write_text("# PRD")

        fake_reqs = [
            _FakeRequirement("REQ-VT-001", "must"),
            _FakeRequirement("REQ-VT-002", "must"),
        ]
        mock_result = PrdParseResult(requirements=fake_reqs)

        with patch("vibe_tracing.prd_parser.PrdParser") as mock_parser_cls:
            mock_parser_cls.return_value.parse_file.return_value = mock_result

            constraints = {
                "design_rules": [
                    {"rule_id": "D1", "related_requirements": ["REQ-VT-001"]},
                ]
            }
            result = validate_prd_architecture_mapping_from_path(tmp_path, constraints)

        assert result.exit_code == 1
        assert result.message is not None
        assert "REQ-VT-002" in result.message
        assert result.result is not None
        assert result.result.has_must_uncovered is True

    def test_valid_mapping_returns_exit_code_0(self, tmp_path):
        """When all checks pass, returns exit_code=0 with no error message."""
        from unittest.mock import patch
        from vibe_tracing.prd_parser import PrdParseResult

        prd_path = tmp_path / "docs" / "prd.md"
        prd_path.parent.mkdir(parents=True, exist_ok=True)
        prd_path.write_text("# PRD")

        fake_reqs = [
            _FakeRequirement("REQ-VT-001", "must"),
            _FakeRequirement("REQ-VT-002", "should"),
        ]
        mock_result = PrdParseResult(requirements=fake_reqs)

        with patch("vibe_tracing.prd_parser.PrdParser") as mock_parser_cls:
            mock_parser_cls.return_value.parse_file.return_value = mock_result

            constraints = {
                "design_rules": [
                    {"rule_id": "D1", "related_requirements": ["REQ-VT-001", "REQ-VT-002"]},
                ]
            }
            result = validate_prd_architecture_mapping_from_path(tmp_path, constraints)

        assert result.exit_code == 0
        assert result.result is not None
        assert result.result.is_valid is True

    def test_should_uncovered_returns_warning(self, tmp_path):
        """When only SHOULD REQs uncovered, returns exit_code=0 with warning."""
        from unittest.mock import patch
        from vibe_tracing.prd_parser import PrdParseResult

        prd_path = tmp_path / "docs" / "prd.md"
        prd_path.parent.mkdir(parents=True, exist_ok=True)
        prd_path.write_text("# PRD")

        fake_reqs = [
            _FakeRequirement("REQ-VT-001", "must"),
            _FakeRequirement("REQ-VT-002", "should"),
        ]
        mock_result = PrdParseResult(requirements=fake_reqs)

        with patch("vibe_tracing.prd_parser.PrdParser") as mock_parser_cls:
            mock_parser_cls.return_value.parse_file.return_value = mock_result

            constraints = {
                "design_rules": [
                    {"rule_id": "D1", "related_requirements": ["REQ-VT-001"]},
                ]
            }
            result = validate_prd_architecture_mapping_from_path(tmp_path, constraints)

        assert result.exit_code == 0
        assert result.message is not None
        assert "非 MUST" in result.message
        assert result.result is not None
        assert len(result.result.should_uncovered) == 1
