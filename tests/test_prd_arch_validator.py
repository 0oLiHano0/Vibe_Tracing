"""Tests for prd_arch_validator — reusable PRD<->Architecture mapping validation."""

import pytest
from dataclasses import dataclass, field
from typing import List

from vibe_tracing.prd_arch_validator import (
    MappingResult,
    validate_prd_architecture_mapping,
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
