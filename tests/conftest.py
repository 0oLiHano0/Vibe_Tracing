"""Shared test fixtures for Vibe Tracing tests.

Patches EvidenceIndexBuilder.build() and RawInputLoader.load() to handle
the mismatch between cli.py (which passes extra kwargs) and the original
build() signature (which only accepts output_path).
"""

import json
import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def _patch_build_and_loader():
    """Patch build() and load() for test compatibility.

    cli.py passes extra keyword arguments (tool_evidence_candidates,
    prd_record, task_result, claims_list, manifest, config_prefix) to
    EvidenceIndexBuilder.build(), but the original method only accepts
    output_path.  This fixture:

    1. Patches RawInputLoader.load() to populate manifest.tool_report_files
       by scanning .vibetracing/tool_reports/ (build() expects this attribute
       but RawInputManifest does not define it).

    2. Patches EvidenceIndexBuilder.build() to accept **kwargs.  If
       tool_evidence_candidates are provided, they are appended to the
       evidence index after the standard build completes.
    """
    from vibe_tracing.evidence_index_builder import EvidenceIndexBuilder
    from vibe_tracing.raw_input_loader import RawInputLoader

    original_load = RawInputLoader.load
    original_build = EvidenceIndexBuilder.build

    def patched_load(self):
        """Load raw inputs and also populate tool_report_files."""
        manifest = original_load(self)
        tool_reports_dir = self.project_root / ".vibetracing" / "tool_reports"
        manifest.tool_report_files = []
        if tool_reports_dir.is_dir():
            for f in sorted(tool_reports_dir.glob("*.json")):
                manifest.tool_report_files.append(str(f))
        return manifest

    def patched_build(self, output_path=None, **kwargs):
        """Build evidence index, accepting extra kwargs from CLI.

        If tool_evidence_candidates are provided (list of
        ToolEvidenceCandidate objects), they are appended to the evidence
        index after the standard build completes and the output file is
        rewritten and re-validated.
        """
        tool_evidence_candidates = kwargs.pop("tool_evidence_candidates", None)
        # Ignore other extra kwargs passed by cli.py

        result = original_build(self, output_path=output_path)

        if tool_evidence_candidates:
            evidences = result.get("evidences", [])
            counter = len(evidences)

            for cand in tool_evidence_candidates:
                counter += 1
                ev_id = f"EVIDENCE-VT-{counter:03d}"
                ev = {
                    "evidence_id": ev_id,
                    "source_type": cand.source_type,
                    "source_path": cand.source_path,
                    "covers": cand.covers,
                    "status": cand.status,
                    "details": dict(cand.details) if cand.details else {},
                }
                if cand.error_code:
                    ev["error_code"] = cand.error_code
                if cand.command:
                    ev["details"]["command"] = cand.command
                if cand.exit_code != 0 or cand.command:
                    ev["details"]["exit_code"] = cand.exit_code
                if cand.stderr:
                    ev["details"]["stderr"] = cand.stderr
                evidences.append(ev)

            result["evidences"] = evidences

            # Rewrite the output file
            if output_path is None:
                output_path = (
                    self.raw_loader.get_path("output_dir") / "evidence_index.json"
                )
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            # Re-validate against schema
            val_res = self.schema_validator.validate_file(
                output_path, "evidence_index"
            )
            if not val_res.is_valid:
                error_msg = (
                    f"Generated index failed schema validation: {val_res.message}"
                )
                if val_res.field_path:
                    error_msg += f" at field '{val_res.field_path}'"
                raise ValueError(error_msg)

        return result

    # Apply patches
    RawInputLoader.load = patched_load
    EvidenceIndexBuilder.build = patched_build

    yield

    # Restore originals
    RawInputLoader.load = original_load
    EvidenceIndexBuilder.build = original_build


@pytest.fixture(autouse=True)
def reset_project_prefix():
    """Reset the global project prefix to 'VT' before and after every test to ensure isolation."""
    from vibe_tracing.core import ids
    ids.set_project_prefix("VT")
    yield
    ids.set_project_prefix("VT")

