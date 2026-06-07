"""Tests for post-analyze meta-cognitive reflection prompts."""

from vibe_tracing.reflection_prompts import render_reflection_prompts


class TestRenderReflectionPrompts:
    """Test the reflection prompt rendering logic."""

    def test_basic_structure(self):
        """All 8 dimensions are present in output."""
        result = render_reflection_prompts(
            gate_decision="pass", gaps=[], risks=[], compliance_result=None
        )
        assert "1. 项目不足识别 (Deficiencies)" in result
        assert "2. 架构精简度评估 (Simplicity)" in result
        assert "3. 彻底根因修复验证 (Root-Cause Fix)" in result
        assert "4. 计算与逻辑冗余 (Redundancy)" in result
        assert "5. 凭证真实性 (Credibility)" in result
        assert "6. 代码认知复杂度 (Cognitive Complexity)" in result
        assert "7. 豁免与绕过机制 (Exception & Bypass)" in result
        assert "8. 残留与死代码清理 (Dead Code)" in result
        assert "元认知反思提示" in result

    def test_blocked_gate_adds_hint(self):
        """Blocked gate triggers deficiency hint."""
        result = render_reflection_prompts(
            gate_decision="blocked", gaps=[], risks=[]
        )
        assert "BLOCKED" in result
        assert "阻断根因" in result

    def test_fail_gate_adds_hint(self):
        """Fail gate triggers deficiency hint."""
        result = render_reflection_prompts(
            gate_decision="fail", gaps=[], risks=[]
        )
        assert "FAIL" in result
        assert "条件性缺陷" in result

    def test_must_risks_trigger_root_cause_hint(self):
        """Must-severity risks trigger root-cause hint."""
        result = render_reflection_prompts(
            gate_decision="pass",
            gaps=[],
            risks=[{"severity": "must", "description": "test"}],
        )
        assert "直击物理根因" in result

    def test_low_confidence_triggers_credibility_hint(self):
        """Low-confidence risks trigger credibility hint."""
        result = render_reflection_prompts(
            gate_decision="pass",
            gaps=[],
            risks=[{"confidence": "low_confidence"}],
        )
        assert "低可信度" in result

    def test_ac_gaps_trigger_bypass_hint(self):
        """AC gaps trigger bypass hint."""
        result = render_reflection_prompts(
            gate_decision="blocked",
            gaps=[{"item_type": "ac", "item_id": "AC-VT-001-01"}],
            risks=[],
        )
        assert "覆盖缺口" in result

    def test_unclear_constraints_trigger_dead_code_hint(self):
        """Unclear constraints trigger dead code hint."""
        result = render_reflection_prompts(
            gate_decision="pass",
            gaps=[],
            risks=[],
            compliance_result={"unclear_constraints": [{"rule_id": "TEST-001"}]},
        )
        assert "模糊约束" in result

    def test_pass_no_hints(self):
        """Pass with no issues has no conditional hints."""
        result = render_reflection_prompts(
            gate_decision="pass", gaps=[], risks=[], compliance_result=None
        )
        assert "BLOCKED" not in result
        assert "FAIL" not in result
        assert "低可信度" not in result
        assert "模糊约束" not in result

    def test_high_gap_count_triggers_redundancy_hint(self):
        """Many gaps trigger redundancy hint."""
        gaps = [{"item_type": "ac", "item_id": f"AC-{i}"} for i in range(6)]
        result = render_reflection_prompts(
            gate_decision="blocked", gaps=gaps, risks=[]
        )
        assert "冗余数据流转" in result
