"""
Traceability Report Builder for Vibe Tracing.

Writes a pre-assembled, schema-compliant traceability report document to disk.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from vibe_tracing.schema_validator import SchemaValidator


class TraceabilityReportBuilder:
    """Orchestrates all traceability analyzers and compiles the final report."""

    def __init__(self, project_root: Path) -> None:
        """Initialize the builder with project root and schema validator."""
        self.project_root = project_root
        self.schemas_dir = project_root / "schemas"
        if not self.schemas_dir.is_dir():
            self.schemas_dir = Path(__file__).parent / "schemas"
        self.schema_validator = SchemaValidator(self.schemas_dir)

    def build(
        self,
        report_doc: Dict[str, Any],
        output_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Write a pre-assembled traceability report document to disk and validate it.

        Args:
            report_doc: The fully assembled report dictionary.
            output_path: Output path for the traceability_report.json.

        Returns:
            The validated report dictionary.

        Raises:
            ValueError: If writing or validation fails.
        """
        # Write output file
        if output_path is None:
            output_path = self.project_root / "output" / "traceability_report.json"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(report_doc, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            raise ValueError(f"Failed to write traceability report: {exc}")

        # Validate report against schema (in-memory, no disk re-read)
        val_res = self.schema_validator.validate_dict(
            report_doc, "traceability_report"
        )
        if not val_res.is_valid:
            error_msg = f"Generated report failed schema validation: {val_res.message}"
            if val_res.field_path:
                error_msg += f" at field '{val_res.field_path}'"
            raise ValueError(error_msg)

        return report_doc
