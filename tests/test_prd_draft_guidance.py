"""
Tests for PRD draft state and zero-prompt guidance loop (TASK-VT-039).
"""

import json
from pathlib import Path
from vibe_tracing.cli import main


def test_analyze_draft_phase_guidance(tmp_path, capsys):
    """
    covers: AC-VT-009-07
    Verify that when PRD status is 'draft' and no tasks/claims are present,
    vibe-tracing analyze runs successfully with exit code 0, outputs 'draft_approved'
    decision, and prints the friendly zero-prompt guidance pointing to prd_analysis.md.
    """
    # 1. Setup mock directories
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vibetracing" / "prompts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "schemas").mkdir(parents=True, exist_ok=True)

    # Copy real schemas to mock project so schema validator can load them
    real_schemas = Path(__file__).parent.parent / "src" / "vibe_tracing" / "schemas"
    for schema_file in real_schemas.glob("*.json"):
        (tmp_path / "schemas" / schema_file.name).write_text(
            schema_file.read_text(encoding="utf-8"), encoding="utf-8"
        )

    # 2. Write PRD in 'draft' status
    prd_content = """---
status: draft
---
# Vibe Tracing PRD

## 0. 文档信息
- 当前状态：draft

## 3. 功能需求
### REQ-VT-001：样例需求
#### 优先级
must
##### AC-VT-001-01：样例验收标准
是否必须有测试：否
"""
    (docs_dir / "prd.md").write_text(prd_content, encoding="utf-8")

    # Also write a dummy config to configure paths (optional but good practice)
    config = {
        "paths": {
            "prd": "docs/prd.md"
        }
    }
    (tmp_path / ".vibetracing" / "config.json").write_text(
        json.dumps(config), encoding="utf-8"
    )

    # Create dummy prompts/prd_analysis.md just to simulate its existence
    (tmp_path / ".vibetracing" / "prompts" / "prd_analysis.md").write_text(
        "# 7 Step PRD Analysis Method", encoding="utf-8"
    )

    # 3. Run analyze command
    exit_code = main(["analyze", "--project-root", str(tmp_path)])
    assert exit_code == 0

    # 4. Verify stdout guidance output
    captured = capsys.readouterr()
    assert "Analysis complete. Gate decision: DRAFT_APPROVED" in captured.out
    assert "项目处于需求草稿阶段（draft），跳过强阻塞门禁规则校验。" in captured.out
    assert ".vibetracing/prompts/prd_analysis.md" in captured.out
    assert "7 步分析法" in captured.out

    # 5. Verify traceability report
    report_path = tmp_path / "output" / "traceability_report.json"
    assert report_path.is_file()
    with report_path.open("r", encoding="utf-8") as f:
        report_data = json.load(f)
    assert report_data["gate_decision"] == "draft_approved"
