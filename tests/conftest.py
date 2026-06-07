"""Shared test fixtures for Vibe Tracing tests.

Patches RawInputLoader.load() to populate manifest.tool_report_files.
"""

import pytest


@pytest.fixture(autouse=True)
def _patch_loader():
    """Patch load() for test compatibility.

    Patches RawInputLoader.load() to populate manifest.tool_report_files
    by scanning .vibetracing/tool_reports/ (build() expects this attribute
    but RawInputManifest does not define it).
    """
    from vibe_tracing.raw_input_loader import RawInputLoader

    original_load = RawInputLoader.load

    def patched_load(self):
        """Load raw inputs and also populate tool_report_files."""
        manifest = original_load(self)
        tool_reports_dir = self.project_root / ".vibetracing" / "tool_reports"
        manifest.tool_report_files = []
        if tool_reports_dir.is_dir():
            for f in sorted(tool_reports_dir.glob("*.json")):
                manifest.tool_report_files.append(str(f))
        return manifest

    # Apply patch
    RawInputLoader.load = patched_load

    yield

    # Restore original
    RawInputLoader.load = original_load


@pytest.fixture(autouse=True)
def reset_project_prefix():
    """Reset the global project prefix to 'VT' before and after every test to ensure isolation."""
    from vibe_tracing.core import ids
    ids.set_project_prefix("VT")
    yield
    ids.set_project_prefix("VT")
