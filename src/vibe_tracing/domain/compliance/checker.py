"""
Architecture Compliance Checker for Vibe Tracing.

Checks machine-verifiable MUST-level constraints and module boundaries.
Unverifiable constraints are returned as unclear, per configuration.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from vibe_tracing.infra import validation as ids
from vibe_tracing.infra.compliance.loader import (
    get_python_imports,
    find_python_files,
)
from vibe_tracing.infra.config.hint_loader import load_hints, resolve_hint
from vibe_tracing.infra.logging.logger import OperationalLogger

_compliance_hints = load_hints("compliance")


def _is_stale_acceptance(accepted_at: str, threshold_days: int = 30) -> bool:
    """Return True if the acceptance is older than threshold_days."""
    if not accepted_at:
        return False
    try:
        accepted_time = datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - accepted_time).days > threshold_days
    except (ValueError, TypeError):
        return False


class ArchitectureComplianceChecker:
    """Statically verifies architectural constraints in the Vibe Tracing project."""

    def __init__(
        self,
        project_root: Path,
        constraints_path: Optional[Path] = None,
        constraints_hash: Optional[str] = None,
        config_data: Optional[dict] = None,
    ) -> None:
        """Initialize the checker."""
        self.project_root = Path(project_root)
        if constraints_path:
            self.constraints_path = Path(constraints_path)
        else:
            self.constraints_path = (
                self.project_root / "docs" / "architecture_constraints.json"
            )
        self.constraints_hash = constraints_hash
        self.config_data = config_data

    def _get_python_imports(self, file_path: Path) -> List[Tuple[str, int]]:
        """Statically extract import statement module names and their line numbers from a python file."""
        return get_python_imports(file_path)

    def _get_module_for_path(
        self, file_path: Path, src_dir: Path
    ) -> Tuple[Optional[str], Optional[str]]:
        """Maps a Python file path to its architectural module ID and module name.

        Uses ``owned_files`` from the loaded architecture constraints as the
        single source of truth.
        """
        try:
            rel_path = file_path.relative_to(src_dir)
            parts = rel_path.parts
            if len(parts) < 1:
                return None, None

            filename = parts[-1]
            for boundary in self.constraints.get("module_boundaries", []):
                if filename in boundary.get("owned_files", []):
                    return boundary["module_id"], boundary["name"]
        except Exception:
            pass
        return None, None

    def _get_module_for_import(
        self, imported_module: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Maps an imported Python module name to its architectural module ID and module name.

        Derives the mapping from ``owned_files`` in the loaded architecture
        constraints: each component of the import path is tried from right to
        left, and the first match against an owned filename (with ``.py``
        suffix stripped) determines the module.  Standard-library and
        third-party imports naturally return ``(None, None)`` because they
        never appear in any module's ``owned_files``.
        """
        parts = imported_module.split(".")
        for boundary in self.constraints.get("module_boundaries", []):
            for owned in boundary.get("owned_files", []):
                owned_stem = owned.removesuffix(".py")
                # Try each component from rightmost (deepest) to leftmost
                for part in reversed(parts):
                    if part == owned_stem:
                        return boundary["module_id"], boundary["name"]
        return None, None

    def _find_evidence_id(self, file_path: str, evidences: List[Dict[str, Any]]) -> str:
        """Find the matching evidence_id for a given file path from the evidence index list."""
        norm_path_stripped = file_path.replace("\\", "/").strip("/").lower()
        for ev in evidences:
            ev_path = ev.get("source_path", "").replace("\\", "/").strip("/").lower()
            if not ev_path:
                continue
            if norm_path_stripped == ev_path:
                return ev["evidence_id"]
            # Segment-level suffix match: compare last 3 path segments
            norm_suffix = "/".join(norm_path_stripped.split("/")[-3:])
            ev_suffix = "/".join(ev_path.split("/")[-3:])
            if norm_suffix == ev_suffix:
                return ev["evidence_id"]
        return ids.sentinel_evidence_id()

    def check(
        self,
        evidences: List[Dict[str, Any]],
        constraints_data: Dict[str, Any],
        human_decisions: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """
        Check all must architectural constraints and module boundaries.

        Args:
            evidences: List of evidence entries from evidences/test_results.json
                and evidences/coverage_reports.json.
            constraints_data: Pre-loaded constraints dict (required).
            human_decisions: Optional human decision log for accepted rules.

        Returns:
            A dictionary containing:
                "architecture_compliance_status": List of rule status dictionaries.
                "architecture_violations": List of confirmed violations.
                "unclear_constraints": List of constraints marked as unclear.
        """
        self.constraints = constraints_data
        src_dir = self.project_root / "src"

        # List all Python files
        py_files: List[Path] = find_python_files(src_dir)

        # Map files to modules and parse imports
        file_imports: Dict[Path, List[Tuple[str, int]]] = {}
        for f in py_files:
            file_imports[f] = self._get_python_imports(f)

        # Parse module boundaries
        boundaries_by_id = {}
        for m in constraints_data.get("module_boundaries", []):
            m_id = m.get("module_id")
            boundaries_by_id[m_id] = m

        # Track results
        status_list: List[Dict[str, Any]] = []
        violations: List[Dict[str, Any]] = []
        unclear_list: List[Dict[str, Any]] = []
        accepted_rules: List[Dict[str, Any]] = []

        # ----------------------------------------------------
        # 1. Check Module Boundaries (MOD-xxx)
        # ----------------------------------------------------
        for m_id, m in boundaries_by_id.items():
            m_name = m.get("name", "")
            forbidden_ids = m.get("forbidden_to_call", [])
            allowed_ids = m.get("allowed_to_call")

            m_violations = []

            # Scan files belonging to this module
            for f, ims in file_imports.items():
                f_mod_id, f_mod_name = self._get_module_for_path(f, src_dir)
                if f_mod_id != m_id:
                    continue

                # Check imports from this file
                for imp_name, lineno in ims:
                    imp_mod_id, imp_mod_name = self._get_module_for_import(imp_name)
                    if not imp_mod_id:
                        continue
                    if imp_mod_id == m_id:
                        continue  # self import allowed

                    # Check forbidden list
                    if imp_mod_id in forbidden_ids:
                        hint = resolve_hint(_compliance_hints.get("forbidden_import", {}), "level1")
                        msg = hint.format(
                            module_id=m_id, module_name=m_name,
                            file_name=f.name, line_number=lineno,
                            forbidden_module_name=imp_mod_name, forbidden_module_id=imp_mod_id,
                        ) if hint else f"Forbidden import of '{imp_mod_name}' (module {imp_mod_id}) at line {lineno} in {f.name}"
                        m_violations.append(
                            (f, imp_mod_name, msg)
                        )
                        OperationalLogger.get().debug("compliance_import_violation", "Forbidden import detected",
                            file=str(f.relative_to(self.project_root)) if self.project_root in f.parents else str(f),
                            line=lineno,
                            import_module=imp_name,
                            imported_as_module=imp_mod_name,
                            imported_module_id=imp_mod_id,
                            rule_type="forbidden",
                            module_id=m_id)
                    else:
                        # Log allowed cross-module imports at DEBUG level
                        OperationalLogger.get().debug("compliance_import_allowed", "Cross-module import allowed",
                            file=str(f.relative_to(self.project_root)) if self.project_root in f.parents else str(f),
                            line=lineno,
                            import_module=imp_name,
                            imported_as_module=imp_mod_name,
                            imported_module_id=imp_mod_id,
                            module_id=m_id)

                    # Check allowed list (if defined, enforce whitelist except for core/self/standard library)
                    if allowed_ids is not None and imp_mod_id is not None and imp_mod_id not in allowed_ids:
                        hint = resolve_hint(_compliance_hints.get("not_in_allowed_whitelist", {}), "level1")
                        msg = hint.format(
                            module_id=m_id, module_name=m_name,
                            file_name=f.name, line_number=lineno,
                            imported_module_name=imp_mod_name, imported_module_id=imp_mod_id,
                        ) if hint else f"Import of '{imp_mod_name}' (module {imp_mod_id}) at line {lineno} in {f.name} is not in allowed_to_call whitelist"
                        m_violations.append(
                            (f, imp_mod_name, msg)
                        )
                        OperationalLogger.get().debug("compliance_import_violation", "Import not in allowed whitelist",
                            file=str(f.relative_to(self.project_root)) if self.project_root in f.parents else str(f),
                            line=lineno,
                            import_module=imp_name,
                            imported_as_module=imp_mod_name,
                            imported_module_id=imp_mod_id,
                            rule_type="not_in_whitelist",
                            module_id=m_id,
                            allowed_ids=allowed_ids)

            # Log module boundary check details at DEBUG level
            _files_in_module = [f for f in file_imports if self._get_module_for_path(f, src_dir)[0] == m_id]
            _imports_checked = sum(len(file_imports[f]) for f in _files_in_module)
            OperationalLogger.get().debug("compliance_module_boundary", "Module boundary check",
                module_id=m_id, module_name=m_name,
                files_in_module=len(_files_in_module),
                imports_checked=_imports_checked,
                violations=len(m_violations))

            # Determine compliance status for the module boundary
            if m_violations:
                status_list.append(
                    {
                        "rule_id": m_id,
                        "status": "violated",
                        "severity": "must",
                        "title": f"Module Boundary: {m_name}",
                        "description": m.get("responsibility", ""),
                    }
                )
                # Add to violations list
                for f, imp_mod, msg in m_violations:
                    rel_f = (
                        str(f.relative_to(self.project_root))
                        if self.project_root in f.parents
                        else str(f)
                    )
                    violations.append(
                        {
                            "rule_id": m_id,
                            "evidence_id": self._find_evidence_id(rel_f, evidences),
                            "message": msg,
                        }
                    )
            else:
                status_list.append(
                    {
                        "rule_id": m_id,
                        "status": "compliant",
                        "severity": "must",
                        "title": f"Module Boundary: {m_name}",
                        "description": m.get("responsibility", ""),
                    }
                )

        # ── 处理配置中的手动规则 ──────────────────────────────────
        # 仅处理 verification_method == "manual" 的 must 级规则。
        # 已人工接受 → 记入 accepted_rules。未接受 → 记入 unclear_constraints。
        # machine 规则若无内置检查器则静默跳过（不标记 unclear、不阻断）。
        all_categories = [
            "architecture_principles",
            "dependency_rules",
            "data_flow_rules",
            "storage_rules",
            "error_handling_rules",
            "logging_rules",
            "security_rules",
            "technology_constraints",
            "forbidden_patterns",
            "quality_gates",
            "interface_contracts",
            "performance_constraints",
            "deployment_constraints",
            "test_constraints",
        ]

        already_checked_ids = {st["rule_id"] for st in status_list}

        for cat in all_categories:
            for rule in constraints_data.get(cat, []):
                r_id = (
                    rule.get("rule_id")
                    or rule.get("principle_id")
                    or rule.get("constraint_id")
                    or rule.get("pattern_id")
                    or rule.get("gate_id")
                    or rule.get("contract_id")
                )
                if not r_id or r_id in already_checked_ids:
                    continue

                severity = rule.get("severity", "must")
                if severity != "must":
                    continue

                verification = rule.get("verification_method", "manual")
                if verification != "manual":
                    # 无内置检查器的 machine 规则，静默跳过。
                    # ponytail: 项目自定义 machine 规则需要插件机制，当前无此需求。
                    continue

                # 手动规则：检查 human_decisions
                accepted_by = None
                accepted_at = ""
                if human_decisions:
                    for d in human_decisions.get("decisions", []):
                        if (
                            d.get("category") == "accepted_rule"
                            and d.get("targetId") == r_id
                            and d.get("action") == "accept"
                        ):
                            accepted_by = d.get("decidedBy", "human")
                            accepted_at = d.get("timestamp", "")
                            break

                if accepted_by:
                    is_stale = _is_stale_acceptance(accepted_at, threshold_days=30)
                    accepted_rules.append({
                        "rule_id": r_id,
                        "title": rule.get("title", ""),
                        "severity": severity,
                        "verification_method": "manual",
                        "accepted_by": accepted_by,
                        "accepted_at": accepted_at,
                        "stale_acceptance": is_stale,
                    })
                else:
                    status_list.append({
                        "rule_id": r_id,
                        "status": "unclear",
                        "severity": "must",
                        "title": rule.get("title", ""),
                        "description": rule.get("description", ""),
                        "verification_method": "manual",
                    })
                    unclear_list.append({
                        "rule_id": r_id,
                        "reason": f"Manual verification rule {r_id} requires human acceptance.",
                    })

        return {
            "architecture_compliance_status": status_list,
            "architecture_violations": violations,
            "unclear_constraints": unclear_list,
            "accepted_rules": accepted_rules,
        }
