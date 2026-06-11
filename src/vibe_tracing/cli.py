"""
CLI Entrypoint for Vibe Tracing.

Provides the ``main()`` function with argparse-based sub-command routing.
All command implementations live in ``vibe_tracing.commands.*`` modules.

This module re-exports public symbols for backward compatibility so that
existing ``from vibe_tracing.cli import X`` imports continue to work.
"""

import argparse
import subprocess  # re-exported so test mocks on vibe_tracing.cli.subprocess work
import sys
from pathlib import Path

from vibe_tracing import __version__

# ---------------------------------------------------------------------------
# Re-export command entry points (backward compatibility)
# ---------------------------------------------------------------------------
from vibe_tracing.commands.init import run_init
from vibe_tracing.commands.finalize import run_finalize
from vibe_tracing.commands.analyze import run_analyze
from vibe_tracing.commands.doctor import run_doctor
from vibe_tracing.commands.accept import run_accept

# ---------------------------------------------------------------------------
# Re-export internal helpers used by tests (backward compatibility)
# ---------------------------------------------------------------------------
from vibe_tracing.commands.common import (
    _GateBlocked,
    _load_context,
    _rel_path_str,
    _get_staged_files,
    _determine_affected_items,
    _file_sha256,
    _compute_claim_hash,
    _get_directly_modified_claims,
)
from vibe_tracing.commands.finalize import (
    _validate_constraints_change,
    _print_post_finalize_guidance,
)
from vibe_tracing.commands.analyze.gates import (
    _gate1_constraints_hash,
    _gate1b_prd_drift,
    _gate1c_mapping,
    _gate2_code_claim_alignment,
    _run_integrity_gates,
)
from vibe_tracing.commands.analyze.tools import (
    _execute_tools,
    _check_staged_extensions,
    _archive_claims,
)
from vibe_tracing.commands.analyze.analysis import (
    _run_analyzers,
    _run_claim_tests,
    _load_human_decisions,
    _result_hash,
)
from vibe_tracing.commands.analyze.helpers import (
    _action_hints,
    _hint_title,
    _hint_context,
    _derive_test_scenarios,
    _get_ac_description,
    _get_req_description,
    _get_related_code,
    _get_existing_tests,
)
from vibe_tracing.commands.analyze.actions import (
    _compute_gap_urgency,
    _collect_gap_actions,
    _compute_risk_urgency,
    _collect_risk_actions,
    _collect_violation_actions,
    _collect_gate_reason_actions,
)
from vibe_tracing.commands.analyze.formatting import (
    _render_actions,
    _format_agent_actions,
)
from vibe_tracing.commands.analyze.reports import (
    _build_report_document,
    _build_metadata,
    _render_dashboard,
)
from vibe_tracing.commands.analyze.output import (
    _print_gate_summary,
    _print_agent_actions,
    _print_reflection_prompts,
    _render_output,
)
from vibe_tracing.commands.analyze.pipeline import (
    _run_analysis_phase,
    _run_gate_evaluation,
    _evaluate_and_output,
)


def main(argv=None):
    """CLI main execution function."""
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        description="Vibe Tracing (VT) - Consistency validation framework for agent coding"
    )
    parser.add_argument(
        "--version", action="version", version=f"vibe-tracing {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="sub-command help")

    analyze_parser = subparsers.add_parser(
        "analyze", help="Analyze project consistency and compliance"
    )
    analyze_parser.add_argument(
        "--project-root",
        default=".",
        help="Path to the project workspace root (default: current working directory)",
    )
    analyze_parser.add_argument(
        "--out", help="Path to the output directory (default: <project-root>/output)"
    )
    analyze_parser.add_argument(
        "--pre-commit", action="store_true", help="Run in Git pre-commit hook mode (enables ghost code reconciliation)"
    )
    analyze_parser.add_argument(
        "--gates-only", action="store_true",
        help="Run only integrity gates (1, 2, 2.5), skip tool execution and analysis (fast mode for pre-commit)"
    )

    init_parser = subparsers.add_parser(
        "init", help="Initialize a new Vibe Tracing project with template files"
    )
    init_parser.add_argument(
        "--project-root",
        default=".",
        help="Path to the project workspace root (default: current working directory)",
    )
    init_parser.add_argument(
        "--name",
        help="Human-readable name of the project",
    )
    init_parser.add_argument(
        "--prefix",
        help="Project prefix abbreviation (e.g. CapL, VT)",
    )

    finalize_parser = subparsers.add_parser(
        "finalize", help="Finalize project config from architecture constraints"
    )
    finalize_parser.add_argument(
        "--project-root",
        default=".",
        help="Path to the project workspace root (default: current working directory)",
    )

    accept_parser = subparsers.add_parser(
        "accept", help="Accept a manual architecture constraint rule"
    )
    accept_parser.add_argument(
        "rule_id",
        help="The rule ID to accept (e.g. PRINCIPLE-VT-001)",
    )
    accept_parser.add_argument(
        "--project-root",
        default=".",
        help="Path to the project workspace root (default: current working directory)",
    )
    accept_parser.add_argument(
        "--by",
        default="human",
        help="Accepter identifier (default: 'human')",
    )

    doctor_parser = subparsers.add_parser(
        "doctor", help="Scan governance data health and report issues"
    )
    doctor_parser.add_argument(
        "--project-root",
        default=".",
        help="Path to the project workspace root (default: current working directory)",
    )

    args = parser.parse_args(argv)

    if args.command == "analyze":
        project_root = Path(args.project_root).resolve()
        if args.out:
            output_dir = Path(args.out)
            if not output_dir.is_absolute():
                output_dir = (project_root / output_dir).resolve()
        else:
            output_dir = None  # Resolved inside run_analyze from config

        return run_analyze(project_root, output_dir, is_pre_commit=args.pre_commit, gates_only=args.gates_only)
    elif args.command == "init":
        project_root = Path(args.project_root).resolve()
        return run_init(project_root, name=args.name, prefix=args.prefix)
    elif args.command == "finalize":
        project_root = Path(args.project_root).resolve()
        return run_finalize(project_root)
    elif args.command == "accept":
        project_root = Path(args.project_root).resolve()
        return run_accept(project_root, args.rule_id, accepted_by=args.by)
    elif args.command == "doctor":
        project_root = Path(args.project_root).resolve()
        return run_doctor(project_root)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
