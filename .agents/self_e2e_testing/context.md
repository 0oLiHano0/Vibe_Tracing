# E2E Testing Context — Vibe Tracing DB Refactoring

## Paths
- Project Workspace: `/Users/lihan/Project/Vibe_Tracing`
- Working Directory: `/Users/lihan/Project/Vibe_Tracing/.agents/self_e2e_testing/`
- Project Scope: `/Users/lihan/Project/Vibe_Tracing/.agents/orchestrator/PROJECT.md`

## 7 Core Features (F1 to F7)
We map the 7 features to the database query and checker functions:
- **F1: Acceptance Criteria Coverage Check (`check_ac_coverage`)**
  - Verify MUST AC coverage starting the LEFT JOIN from `acceptance_criteria`.
- **F2: Requirement Coverage Check (`check_requirement_coverage`)**
  - Verify requirement-to-task coverage metrics and gaps.
- **F3: Claim Evidence Verification (`check_claim_evidence`)**
  - Validate that claims have proper evidence and flag any mismatch/evidence gap.
- **F4: Full Traceability Chain Query (`get_full_chain`)**
  - Query the complete traceability chain: Requirement -> AC -> Task -> Claim -> Code/Test -> Result.
- **F5: Ghost Code Detection (`check_ghost_code`)**
  - Identify staged files that are not covered by any claim.
- **F6: Dangling Claims Detection (`check_dangling_claims`)**
  - Detect claims associated with non-existent tasks.
- **F7: Test Dead Links Detection (`check_test_dead_links`)**
  - Identify tests referenced by claims but not run or failed.

## Testing Guidelines
- All tests should be requirement-driven.
- Testing should be structured into the 4-tier model (Tier 1 Feature Coverage, Tier 2 Boundary/Corner cases, Tier 3 Cross-feature combinations, Tier 4 Real-world scenarios).
- Implement tests in `tests/test_db_query_functions.py` or new test files under `tests/`.
