# Vibe Tracing (VT)

Vibe Tracing (VT) is a consistency validation and governance framework for AI Coding lifecycles. It translates technical information (code, tests, claims) into governance indicators (logic flow, state coverage, risks, merge gates) that non-development business stakeholders and project managers can easily understand.

---

## Core Philosophy: "Black-Box Execution, White-Box Auditing"

Vibe Tracing deviates fundamentally from traditional prompt-driven or skill-constrained Agent frameworks:

1. **Result-Oriented, Not Process-Micromanaged**: We do not restrict how the AI Coding Agent implements requirements or what programming techniques it uses. Rather than micromanaging the process (which is brittle and fails as models evolve), VT establishes a rigid **"delivery contract" (JSON Schemas)** and a **"merge gate"** at the endpoint.
2. **Local Feedback Loop (The AI Checker)**: We do not manually prompt or nudge the Agent to submit files. Instead, VT provides a local analyzer CLI (`vibe-tracing analyze`). Because AI Agents excel at reading terminal outputs and debugging issues recursively, they use the VT Checker as a "compiler" to iteratively refine their output structures, docstrings, and tests until they pass.
3. **Evidence-based Trust**: Natural language claims from AI Agents (e.g., "I finished the task") are treated as unverified. VT degrades missing or unproven items to "unclear" or "missing" and blocks the gate unless verified by objective, external tool outputs (tests, linters) and code paths.

---

## Project Structure

The project layout follows a clean separation of project specification documents, source code, tests, and hidden VT governance data:

```text
.
├── pyproject.toml              # Build system, dependencies, and CLI configuration
├── README.md                   # Project overview and structure guide
├── docs/                       # Project Specification and Documentation folder
│   ├── prd.md                  # Project Requirement Document (PRD)
│   ├── architecture_constraints.json # Architecture constraints config
│   ├── task_list.json          # Backlog / Sprint task list
│   ├── architecture_change_log.md # Log explaining architectural changes
│   ├── task_execution_rules.md # AI Coding guidelines and task rules
│   ├── input_output_contracts.md # Schema specs and directory layouts
│   └── claude_code_bootstrap.md # Claude Code bootstrap & isolation rules
├── src/
│   └── vibe_tracing/           # Core Python source package
│       ├── __init__.py         # Package initialization
│       ├── cli.py              # CLI entry point and analyze command
│       ├── schemas/            # JSON Schema draft-07 contract definitions
│       │   ├── task_list.schema.json
│       │   ├── agent_claims.schema.json
│       │   ├── evidence_index.schema.json
│       │   └── traceability_report.schema.json
│       ├── core/               # Shared constants, enums, and ID validators
│       ├── traceability/       # Analyzers for tasks, ACs, and claims
│       └── dashboard_renderer.py # Monolithic HTML Dashboard generator
├── tests/                      # Core test suite
│   ├── test_cli_analyze.py
│   ├── test_quality_gates.py   # Regression tests for all quality gates
│   └── test_e2e_samples.py     # E2E Golden File validation tests
└── .vibetracing/               # Hidden VT Governance Folder
    ├── config.json             # Core configuration mapping docs/ and outputs
    ├── agent_claims.json       # Log of claims made by developer agent(s)
    ├── claude_bootstrap/       # Subagent permissions & proposals
    ├── tool_reports/           # Raw output reports from linters/tests
    └── output/                 # Generated traceability matrices and Dashboard HTML
```

---

## Detailed Documentation

To understand the core concepts and execution models of Vibe Tracing, please refer to the following documents:

1. [Task Execution Rules](file:///Users/lihan/Project/Vibe_Tracing/docs/task_execution_rules.md): Rules for AI Coding agents on managing status, annotating tests, and providing verifiable evidence.
2. [Input and Output Contracts](file:///Users/lihan/Project/Vibe_Tracing/docs/input_output_contracts.md): Specification of directories, schema validation, status semantics, and exit codes.
3. [Claude Code Bootstrap & Isolation](file:///Users/lihan/Project/Vibe_Tracing/docs/claude_code_bootstrap.md): Isolation rules and subagent/skill separation policies when bootstrapping under Claude Code.

---

## Quick Start

### Installation

Install the package in editable mode with development dependencies:

```bash
pip install -e ".[dev]"
```

### Running the Analysis Pipeline

Analyze the project state and quality gates:

```bash
vibe-tracing analyze --project-root /path/to/project
```

This command parses the inputs, checks schemas, evaluates quality gates, and outputs the following files to `.vibetracing/output/` (or your configured output directory):
- `evidence_index.json`
- `traceability_report.json`
- `dashboard.html` (interactive monolithic file)
- `run_metadata.json`

### CLI Exit Codes

- **`0`**: Success (`pass` decision) or conditional validation warning (`fail` decision).
- **`1`**: Invalid inputs, schema violations, or loader errors.
- **`2`**: Quality gate blocked (`blocked` decision due to missing tests, rule violations, or invalid claims).

### Running Tests

Run the full test suite (unit, integration, regression, and E2E):

```bash
pytest
```
