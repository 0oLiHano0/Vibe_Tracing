"""Tests for UnifiedContext domain model."""

import pytest
from vibe_tracing.domain.context import UnifiedContext


class _MockPrd:
    """Minimal stand-in for PrdParseResult with a requirements attribute."""
    requirements = []
    status = "active"


class TestUnifiedContext:
    """Verify UnifiedContext dataclass behaviour."""

    def test_instantiation_with_all_fields(self):
        """All fields can be set explicitly."""
        config = {"key": "value"}
        prd = _MockPrd()
        constraints = {"max_tasks": 10}
        task_result = {"tasks": []}
        claims = [{"id": "C001"}]
        manifest = {"inputs": ["prd.md"]}

        ctx = UnifiedContext(
            config=config,
            prd=prd,
            constraints=constraints,
            task_result=task_result,
            claims_list=claims,
            manifest=manifest,
            config_prefix="MY_APP",
        )

        assert ctx.config is config
        assert ctx.prd is prd
        assert ctx.constraints is constraints
        assert ctx.task_result is task_result
        assert ctx.claims_list is claims
        assert ctx.manifest is manifest
        assert ctx.config_prefix == "MY_APP"

    def test_default_values(self):
        """Optional fields default to None/empty as expected."""
        ctx = UnifiedContext(config={"k": "v"}, prd=_MockPrd())

        assert ctx.constraints is None
        assert ctx.task_result is None
        assert ctx.claims_list == []
        assert ctx.manifest is None
        assert ctx.config_prefix == "VT"

    def test_no_tool_evidence_field(self):
        """tool_evidence is NOT a field on UnifiedContext (pipeline-local variable)."""
        ctx = UnifiedContext(config={}, prd=_MockPrd())
        assert not hasattr(ctx, "tool_evidence")

    def test_config_prefix_default_is_vt(self):
        """config_prefix defaults to 'VT' when not specified."""
        ctx = UnifiedContext(config={}, prd=_MockPrd())
        assert ctx.config_prefix == "VT"

    def test_config_prefix_override(self):
        """config_prefix can be overridden."""
        ctx = UnifiedContext(config={}, prd=_MockPrd(), config_prefix="CUSTOM")
        assert ctx.config_prefix == "CUSTOM"

    def test_claims_list_independent_instances(self):
        """Each instance gets its own claims_list (no shared default)."""
        ctx1 = UnifiedContext(config={}, prd=_MockPrd())
        ctx2 = UnifiedContext(config={}, prd=_MockPrd())

        ctx1.claims_list.append({"id": "C001"})
        assert len(ctx1.claims_list) == 1
        assert len(ctx2.claims_list) == 0

    def test_post_init_rejects_invalid_config(self):
        """__post_init__ raises TypeError for non-dict config."""
        with pytest.raises(TypeError, match="config must be a dict"):
            UnifiedContext(config="bad", prd=_MockPrd())

    def test_post_init_rejects_prd_without_requirements(self):
        """__post_init__ raises TypeError for prd without requirements attr."""
        with pytest.raises(TypeError, match="prd must have a 'requirements' attribute"):
            UnifiedContext(config={}, prd="bad")
