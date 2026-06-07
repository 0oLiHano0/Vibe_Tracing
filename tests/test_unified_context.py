"""Tests for UnifiedContext domain model."""

from vibe_tracing.context import UnifiedContext


class TestUnifiedContext:
    """Verify UnifiedContext dataclass behaviour."""

    def test_instantiation_with_all_fields(self):
        """All fields can be set explicitly."""
        config = {"key": "value"}
        prd = {"title": "Test PRD"}
        constraints = {"max_tasks": 10}
        task_result = {"tasks": []}
        claims = [{"id": "C001"}]
        evidence = [{"tool": "pytest"}]
        manifest = {"inputs": ["prd.md"]}

        ctx = UnifiedContext(
            config=config,
            prd=prd,
            constraints=constraints,
            task_result=task_result,
            claims_list=claims,
            tool_evidence=evidence,
            manifest=manifest,
            config_prefix="MY_APP",
        )

        assert ctx.config is config
        assert ctx.prd is prd
        assert ctx.constraints is constraints
        assert ctx.task_result is task_result
        assert ctx.claims_list is claims
        assert ctx.tool_evidence is evidence
        assert ctx.manifest is manifest
        assert ctx.config_prefix == "MY_APP"

    def test_default_values(self):
        """Optional fields default to None/empty as expected."""
        ctx = UnifiedContext(config={"k": "v"}, prd="dummy")

        assert ctx.constraints is None
        assert ctx.task_result is None
        assert ctx.claims_list == []
        assert ctx.tool_evidence == []
        assert ctx.manifest is None
        assert ctx.config_prefix == "VT"

    def test_tool_evidence_appendable(self):
        """tool_evidence list can be mutated after construction."""
        ctx = UnifiedContext(config={}, prd=None)
        assert ctx.tool_evidence == []

        ctx.tool_evidence.append({"tool": "ruff", "status": "pass"})
        ctx.tool_evidence.append({"tool": "pytest", "status": "pass"})

        assert len(ctx.tool_evidence) == 2
        assert ctx.tool_evidence[0]["tool"] == "ruff"

    def test_config_prefix_default_is_vt(self):
        """config_prefix defaults to 'VT' when not specified."""
        ctx = UnifiedContext(config={}, prd=None)
        assert ctx.config_prefix == "VT"

    def test_config_prefix_override(self):
        """config_prefix can be overridden."""
        ctx = UnifiedContext(config={}, prd=None, config_prefix="CUSTOM")
        assert ctx.config_prefix == "CUSTOM"

    def test_claims_list_independent_instances(self):
        """Each instance gets its own claims_list (no shared default)."""
        ctx1 = UnifiedContext(config={}, prd=None)
        ctx2 = UnifiedContext(config={}, prd=None)

        ctx1.claims_list.append({"id": "C001"})
        assert len(ctx1.claims_list) == 1
        assert len(ctx2.claims_list) == 0
