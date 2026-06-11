"""
Analyze command sub-package.

Re-exports ``run_analyze`` so that ``from vibe_tracing.commands.analyze import run_analyze``
works as expected.
"""

from vibe_tracing.commands.analyze.pipeline import run_analyze

__all__ = ["run_analyze"]
