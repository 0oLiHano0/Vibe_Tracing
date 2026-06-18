"""
Tests for PRD draft state and zero-prompt guidance loop (TASK-VT-039).
"""

import json
from pathlib import Path
from vibe_tracing.cli import main


# NOTE: test_analyze_draft_phase_guidance has been removed.
# The `prd_status` parameter was removed from MergeGateEngine.evaluate().
# Draft-phase gating is now handled at the pipeline output layer
# (output.py prints guidance text), but gate_decision is no longer
# "draft_approved". The early-return draft behavior was deprecated.
