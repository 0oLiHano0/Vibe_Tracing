"""Shared test fixtures for Vibe Tracing tests."""

import pytest


@pytest.fixture(autouse=True)
def reset_project_prefix():
    """Reset the global project prefix to 'VT' before and after every test to ensure isolation."""
    from vibe_tracing.infra import validation as ids
    ids.set_project_prefix("VT")
    yield
    ids.set_project_prefix("VT")
