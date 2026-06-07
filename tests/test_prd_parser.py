from pathlib import Path
from vibe_tracing.prd_parser import PrdParser


def test_parse_real_prd():
    """covers: AC-VT-001-01, AC-VT-001-02"""
    parser = PrdParser()
    prd_path = Path("docs/prd.md")
    result = parser.parse_file(prd_path)

    assert result.is_valid is True
    assert len(result.errors) == 0
    assert len(result.requirements) == 10

    # Verify IDs are REQ-VT-001 through REQ-VT-010
    req_ids = [req.req_id for req in result.requirements]
    expected_req_ids = [f"REQ-VT-00{i}" for i in range(1, 10)] + ["REQ-VT-010"]
    assert req_ids == expected_req_ids

    # Check priorities
    priorities = {req.req_id: req.priority for req in result.requirements}
    assert priorities["REQ-VT-001"] == "must"
    assert priorities["REQ-VT-003"] == "should"
    assert priorities["REQ-VT-005"] == "could"
    assert priorities["REQ-VT-009"] == "must"

    # Check some ACs
    req_001 = result.requirements[0]
    assert req_001.req_id == "REQ-VT-001"
    assert len(req_001.acceptance_criteria) == 4

    ac_001_01 = req_001.acceptance_criteria[0]
    assert ac_001_01.ac_id == "AC-VT-001-01"
    assert ac_001_01.title == "需求必须能关联任务"
    assert ac_001_01.is_testing_required is True

    # Check a False testing requirement
    # REQ-VT-004 AC-VT-004-03
    req_004 = next(req for req in result.requirements if req.req_id == "REQ-VT-004")
    ac_004_03 = next(
        ac for ac in req_004.acceptance_criteria if ac.ac_id == "AC-VT-004-03"
    )
    assert ac_004_03.title == "隐藏输入假设必须暴露"
    assert ac_004_03.is_testing_required is False


def test_duplicate_requirement_id():
    """covers: AC-VT-001-01"""
    parser = PrdParser()
    text = """
### REQ-VT-001：全链路需求追踪
#### 类别
functional
#### 优先级
Must

### REQ-VT-001：重复需求
#### 类别
functional
#### 优先级
Should
"""
    result = parser.parse_text(text)
    assert result.is_valid is False
    assert any("Duplicate requirement ID: REQ-VT-001" in err for err in result.errors)


def test_duplicate_ac_id():
    """covers: AC-VT-001-02"""
    parser = PrdParser()
    text = """
### REQ-VT-001：全链路需求追踪
#### 类别
functional
#### 优先级
Must

##### AC-VT-001-01：需求必须能关联任务
* 是否必须有测试：是

##### AC-VT-001-01：重复AC
* 是否必须有测试：否
"""
    result = parser.parse_text(text)
    assert result.is_valid is False
    assert any("Duplicate AC ID: AC-VT-001-01" in err for err in result.errors)


def test_heading_level_mismatch_req():
    """covers: AC-VT-001-01"""
    parser = PrdParser()
    text = """
#### REQ-VT-001：优先级不应该在 Level 4 heading
#### 类别
functional
#### 优先级
Must
"""
    result = parser.parse_text(text)
    assert result.is_valid is False
    assert any(
        "Requirement ID pattern found in heading of level 4" in err
        for err in result.errors
    )


def test_heading_level_mismatch_ac():
    """covers: AC-VT-001-02"""
    parser = PrdParser()
    text = """
### REQ-VT-001：全链路需求追踪
#### 类别
functional
#### 优先级
Must

### AC-VT-001-01：AC不应该在 Level 3 heading
* 是否必须有测试：是
"""
    result = parser.parse_text(text)
    assert result.is_valid is False
    assert any(
        "AC ID pattern found in heading of level 3" in err for err in result.errors
    )


def test_missing_parent_requirement():
    """covers: AC-VT-001-01"""
    parser = PrdParser()
    text = """
### REQ-VT-002：证据驱动的 Agent Claim 校验
#### 类别
functional
#### 优先级
Must

##### AC-VT-001-01：AC的父Requirement REQ-VT-001在文档中不存在
* 是否必须有测试：是
"""
    result = parser.parse_text(text)
    assert result.is_valid is False
    assert any(
        "Parent requirement REQ-VT-001 for AC AC-VT-001-01 is missing from the document"
        in err
        for err in result.errors
    )


def test_nesting_mismatch():
    """covers: AC-VT-001-01"""
    parser = PrdParser()
    text = """
### REQ-VT-001：全链路需求追踪
#### 类别
functional
#### 优先级
Must

### REQ-VT-002：证据驱动的 Agent Claim 校验
#### 类别
functional
#### 优先级
Must

##### AC-VT-001-01：AC物理上在 REQ-VT-002 下面，但 ID 属于 REQ-VT-001
* 是否必须有测试：是
"""
    result = parser.parse_text(text)
    assert result.is_valid is False
    assert any(
        "AC AC-VT-001-01 is defined under incorrect requirement section" in err
        for err in result.errors
    )


def test_invalid_priority_value():
    """covers: AC-VT-001-01"""
    parser = PrdParser()
    text = """
### REQ-VT-001：全链路需求追踪
#### 类别
functional
#### 优先级
high
"""
    result = parser.parse_text(text)
    assert result.is_valid is False
    assert result.requirements[0].priority == "unclear"
    assert any(
        "Invalid priority 'high' for requirement REQ-VT-001" in err
        for err in result.errors
    )


def test_missing_priority_heading():
    """covers: AC-VT-001-01"""
    parser = PrdParser()
    text = """
### REQ-VT-001：全链路需求追踪
#### 类别
functional
"""
    result = parser.parse_text(text)
    assert result.is_valid is False
    assert result.requirements[0].priority == "unclear"
    assert any(
        "Priority not found for requirement REQ-VT-001" in err for err in result.errors
    )


def test_missing_testing_required_field():
    """covers: AC-VT-001-02"""
    parser = PrdParser()
    text = """
### REQ-VT-001：全链路需求追踪
#### 类别
functional
#### 优先级
Must

##### AC-VT-001-01：需求必须能关联任务
"""
    result = parser.parse_text(text)
    assert result.is_valid is False
    assert result.requirements[0].acceptance_criteria[0].is_testing_required is False
    assert any(
        "AC AC-VT-001-01 is missing '是否必须有测试' line" in err
        for err in result.errors
    )


def test_malformed_testing_required_field():
    """covers: AC-VT-001-02"""
    parser = PrdParser()
    text = """
### REQ-VT-001：全链路需求追踪
#### 类别
functional
#### 优先级
Must

##### AC-VT-001-01：需求必须能关联任务
* 是否必须有测试：不确定
"""
    result = parser.parse_text(text)
    assert result.is_valid is False
    assert result.requirements[0].acceptance_criteria[0].is_testing_required is False
    assert any(
        "AC AC-VT-001-01 has invalid or different value for testing requirement in line"
        in err
        for err in result.errors
    )


def test_missing_category_heading():
    """Missing category section should produce an error."""
    parser = PrdParser()
    text = """
### REQ-VT-001：全链路需求追踪
#### 优先级
Must
"""
    result = parser.parse_text(text)
    assert result.is_valid is False
    assert result.requirements[0].category == "unclear"
    assert any(
        "Category not found for requirement REQ-VT-001" in err
        for err in result.errors
    )


def test_invalid_category_value():
    """Invalid category value should produce an error."""
    parser = PrdParser()
    text = """
### REQ-VT-001：全链路需求追踪
#### 类别
invalid_value
#### 优先级
Must
"""
    result = parser.parse_text(text)
    assert result.is_valid is False
    assert result.requirements[0].category == "unclear"
    assert any(
        "Invalid category 'invalid_value' for requirement REQ-VT-001" in err
        for err in result.errors
    )


def test_valid_category_functional():
    """functional category should parse correctly."""
    parser = PrdParser()
    text = """
### REQ-VT-001：全链路需求追踪
#### 类别
functional
#### 优先级
Must
"""
    result = parser.parse_text(text)
    assert result.requirements[0].category == "functional"


def test_valid_category_quality_evolution():
    """quality_evolution category should parse correctly."""
    parser = PrdParser()
    text = """
### Q-001：质量演进需求
#### 类别
quality_evolution
#### 优先级
Should
"""
    result = parser.parse_text(text)
    assert result.requirements[0].category == "quality_evolution"


def test_q_pattern_category_mismatch_warning():
    """Q-\\d+ pattern REQ without quality_evolution category should emit warning."""
    parser = PrdParser()
    text = """
### Q-001：质量演进需求
#### 类别
functional
#### 优先级
Should
"""
    result = parser.parse_text(text)
    # Q-pattern mismatch is a warning (appended to errors but doesn't invalidate)
    assert any(
        "Q-\\d+ pattern" in err and "quality_evolution" in err
        for err in result.errors
    )


def test_category_case_insensitive():
    """Category parsing should be case-insensitive."""
    parser = PrdParser()
    text = """
### REQ-VT-001：全链路需求追踪
#### 类别
FUNCTIONAL
#### 优先级
Must
"""
    result = parser.parse_text(text)
    assert result.requirements[0].category == "functional"
