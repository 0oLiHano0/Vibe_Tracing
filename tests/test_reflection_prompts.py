"""Tests for post-analyze meta-cognitive reflection prompts."""

import json

from vibe_tracing.reflection_prompts import (
    check_uncovered_scopes,
    load_dimensions,
    render_reflection_prompts,
)

_EMPTY_TASK_LIST = {"tasks": []}


class TestCheckUncoveredScopes:
    """Test the uncovered scope detection function."""

    def test_all_covered(self):
        """Files present in task code_refs are not reported."""
        task_list = {
            "tasks": [
                {"code_refs": ["src/foo.py", "src/bar.py"]},
            ]
        }
        result = check_uncovered_scopes(["src/foo.py", "src/bar.py"], task_list)
        assert result == []

    def test_none_covered(self):
        """Files absent from all task code_refs are all reported."""
        task_list = {"tasks": [{"code_refs": ["src/other.py"]}]}
        result = check_uncovered_scopes(["src/foo.py", "src/bar.py"], task_list)
        assert result == ["src/bar.py", "src/foo.py"]

    def test_partial_coverage(self):
        """Mix of covered and uncovered files."""
        task_list = {
            "tasks": [
                {"code_refs": ["src/foo.py#L1-L10"]},
            ]
        }
        result = check_uncovered_scopes(
            ["src/foo.py", "src/bar.py", "src/baz.py"], task_list
        )
        assert result == ["src/bar.py", "src/baz.py"]

    def test_strips_line_range_suffix(self):
        """Line-range suffixes (e.g. #L1-L10) are stripped when matching."""
        task_list = {
            "tasks": [{"code_refs": ["src/foo.py#L5-L20"]}]
        }
        result = check_uncovered_scopes(["src/foo.py"], task_list)
        assert result == []

    def test_empty_tasks_list(self):
        """Empty tasks list means all affected files are uncovered."""
        result = check_uncovered_scopes(["src/a.py"], {"tasks": []})
        assert result == ["src/a.py"]

    def test_empty_affected_files(self):
        """No affected files means nothing to report."""
        task_list = {"tasks": [{"code_refs": ["src/a.py"]}]}
        result = check_uncovered_scopes([], task_list)
        assert result == []

    def test_multiple_tasks(self):
        """Code refs from multiple tasks are aggregated."""
        task_list = {
            "tasks": [
                {"code_refs": ["src/a.py"]},
                {"code_refs": ["src/b.py"]},
            ]
        }
        result = check_uncovered_scopes(["src/a.py", "src/b.py", "src/c.py"], task_list)
        assert result == ["src/c.py"]

    def test_task_without_code_refs(self):
        """Tasks without code_refs key are handled gracefully."""
        task_list = {"tasks": [{"task_id": "TASK-001"}]}
        result = check_uncovered_scopes(["src/a.py"], task_list)
        assert result == ["src/a.py"]

    def test_result_is_sorted(self):
        """Uncovered files are returned in sorted order."""
        task_list = {"tasks": []}
        result = check_uncovered_scopes(["z.py", "a.py", "m.py"], task_list)
        assert result == ["a.py", "m.py", "z.py"]


class TestRenderReflectionPrompts:
    """Test the reflection prompt rendering logic."""

    def test_basic_structure(self):
        """All 8 dimensions are present in output."""
        result = render_reflection_prompts(
            gate_decision="pass", gaps=[], risks=[],
            task_list=_EMPTY_TASK_LIST, affected_files=[],
            compliance_result=None,
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
            gate_decision="blocked", gaps=[], risks=[],
            task_list=_EMPTY_TASK_LIST, affected_files=[],
        )
        assert "BLOCKED" in result
        assert "阻断根因" in result

    def test_fail_gate_adds_hint(self):
        """Fail gate triggers deficiency hint."""
        result = render_reflection_prompts(
            gate_decision="fail", gaps=[], risks=[],
            task_list=_EMPTY_TASK_LIST, affected_files=[],
        )
        assert "FAIL" in result
        assert "条件性缺陷" in result

    def test_must_risks_trigger_root_cause_hint(self):
        """Must-severity risks trigger root-cause hint."""
        result = render_reflection_prompts(
            gate_decision="pass",
            gaps=[],
            risks=[{"severity": "must", "description": "test"}],
            task_list=_EMPTY_TASK_LIST, affected_files=[],
        )
        assert "直击物理根因" in result

    def test_low_confidence_triggers_credibility_hint(self):
        """Low-confidence risks trigger credibility hint."""
        result = render_reflection_prompts(
            gate_decision="pass",
            gaps=[],
            risks=[{"confidence": "low_confidence"}],
            task_list=_EMPTY_TASK_LIST, affected_files=[],
        )
        assert "低可信度" in result

    def test_ac_gaps_trigger_bypass_hint(self):
        """AC gaps trigger bypass hint."""
        result = render_reflection_prompts(
            gate_decision="blocked",
            gaps=[{"item_type": "ac", "item_id": "AC-VT-001-01"}],
            risks=[],
            task_list=_EMPTY_TASK_LIST, affected_files=[],
        )
        assert "覆盖缺口" in result

    def test_unclear_constraints_trigger_dead_code_hint(self):
        """Unclear constraints trigger dead code hint."""
        result = render_reflection_prompts(
            gate_decision="pass",
            gaps=[],
            risks=[],
            task_list=_EMPTY_TASK_LIST, affected_files=[],
            compliance_result={"unclear_constraints": [{"rule_id": "TEST-001"}]},
        )
        assert "模糊约束" in result

    def test_pass_no_hints(self):
        """Pass with no issues has no conditional hints."""
        result = render_reflection_prompts(
            gate_decision="pass", gaps=[], risks=[],
            task_list=_EMPTY_TASK_LIST, affected_files=[],
            compliance_result=None,
        )
        assert "BLOCKED" not in result
        assert "FAIL" not in result
        assert "低可信度" not in result
        assert "模糊约束" not in result

    def test_high_gap_count_triggers_redundancy_hint(self):
        """Many gaps trigger redundancy hint."""
        gaps = [{"item_type": "ac", "item_id": f"AC-{i}"} for i in range(6)]
        result = render_reflection_prompts(
            gate_decision="blocked", gaps=gaps, risks=[],
            task_list=_EMPTY_TASK_LIST, affected_files=[],
        )
        assert "冗余数据流转" in result

    def test_uncovered_files_produce_warning(self):
        """Files not covered by any task produce a governance coverage warning."""
        task_list = {"tasks": []}
        result = render_reflection_prompts(
            gate_decision="pass", gaps=[], risks=[],
            task_list=task_list,
            affected_files=["src/foo.py", "src/bar.py"],
        )
        assert "治理覆盖警告" in result
        assert "src/foo.py" in result
        assert "src/bar.py" in result
        assert "docs/task_list.json" in result

    def test_covered_files_produce_no_warning(self):
        """Files covered by tasks produce no governance coverage warning."""
        task_list = {
            "tasks": [{"code_refs": ["src/foo.py", "src/bar.py"]}]
        }
        result = render_reflection_prompts(
            gate_decision="pass", gaps=[], risks=[],
            task_list=task_list,
            affected_files=["src/foo.py", "src/bar.py"],
        )
        assert "治理覆盖警告" not in result

    def test_uncovered_hint_in_dead_code_dimension(self):
        """Uncovered scope triggers the dead_code dimension conditional hint."""
        task_list = {"tasks": []}
        result = render_reflection_prompts(
            gate_decision="pass", gaps=[], risks=[],
            task_list=task_list,
            affected_files=["src/ghost.py"],
        )
        assert "治理链路存在盲区" in result
        assert "1" in result  # uncovered_count = 1


class TestLoadDimensions:
    """Test loading reflection dimensions from JSON template."""

    def test_default_template_loads_8_dimensions(self):
        """Default template file loads exactly 8 dimensions."""
        dims = load_dimensions()
        assert len(dims) == 8
        assert dims[0]["id"] == "deficiencies"
        assert dims[7]["id"] == "dead_code"

    def test_custom_template_path(self, tmp_path):
        """Custom dimensions can be loaded from a user-specified JSON file."""
        custom = {
            "dimensions": [
                {
                    "id": "custom_dim",
                    "index": 1,
                    "title": "Custom Dimension",
                    "prompt": "Custom prompt text?",
                    "conditional_hints": [],
                }
            ]
        }
        custom_file = tmp_path / "custom_reflection.json"
        custom_file.write_text(json.dumps(custom), encoding="utf-8")

        dims = load_dimensions(template_path=str(custom_file))
        assert len(dims) == 1
        assert dims[0]["id"] == "custom_dim"

    def test_custom_dimensions_rendered_in_output(self, tmp_path):
        """Custom dimensions are rendered into the reflection output."""
        custom = {
            "dimensions": [
                {
                    "id": "custom_only",
                    "index": 1,
                    "title": "My Custom Title",
                    "prompt": "My custom prompt?",
                    "conditional_hints": [],
                }
            ]
        }
        custom_file = tmp_path / "custom_reflection.json"
        custom_file.write_text(json.dumps(custom), encoding="utf-8")

        dims = load_dimensions(template_path=str(custom_file))
        result = render_reflection_prompts(
            gate_decision="pass", gaps=[], risks=[],
            task_list=_EMPTY_TASK_LIST, affected_files=[],
            dimensions=dims,
        )
        assert "1. My Custom Title" in result
        assert "My custom prompt?" in result
        # Standard dimensions should NOT be present
        assert "项目不足识别" not in result

    def test_dimensions_idempotent_with_default(self):
        """Rendering with explicitly loaded dimensions matches default rendering."""
        dims = load_dimensions()
        result_explicit = render_reflection_prompts(
            gate_decision="pass", gaps=[], risks=[],
            task_list=_EMPTY_TASK_LIST, affected_files=[],
            dimensions=dims,
        )
        result_default = render_reflection_prompts(
            gate_decision="pass", gaps=[], risks=[],
            task_list=_EMPTY_TASK_LIST, affected_files=[],
        )
        assert result_explicit == result_default
