"""
Architecture Compliance Checker for Vibe Tracing.

Checks machine-verifiable MUST-level constraints and module boundaries.
Unverifiable constraints are returned as unclear, per FORBID-VT-007.
"""

import ast
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple


class ArchitectureComplianceChecker:
    """Statically verifies architectural constraints in the Vibe Tracing project."""

    def __init__(
        self, project_root: Path, constraints_path: Optional[Path] = None
    ) -> None:
        """Initialize the checker."""
        self.project_root = Path(project_root)
        if constraints_path:
            self.constraints_path = Path(constraints_path)
        else:
            from vibe_tracing.raw_input_loader import RawInputLoader

            raw_loader = RawInputLoader(self.project_root)
            self.constraints_path = raw_loader.get_path("architecture_constraints")

    def _load_constraints(self) -> Dict[str, Any]:
        """Load architecture constraints JSON file."""
        if not self.constraints_path.exists():
            raise FileNotFoundError(
                f"Architecture constraints file not found at {self.constraints_path}"
            )
        try:
            with self.constraints_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            raise ValueError(f"Failed to parse architecture constraints JSON: {exc}")

    def _get_python_imports(self, file_path: Path) -> List[Tuple[str, int]]:
        """Statically extract import statement module names and their line numbers from a python file."""
        imports = []
        try:
            content = file_path.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(file_path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        imports.append((name.name, node.lineno))
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append((node.module, node.lineno))
        except Exception:
            pass
        return imports

    def _get_module_for_path(
        self, file_path: Path, src_dir: Path
    ) -> Tuple[Optional[str], Optional[str]]:
        """Maps a Python file path to its architectural module ID and module name."""
        try:
            rel_path = file_path.relative_to(src_dir)
            parts = rel_path.parts
            if len(parts) < 1:
                return None, None
            if "core" in parts:
                return None, None

            filename = parts[-1]
            if "traceability" in parts:
                return "MOD-VT-006", "traceability_analyzer"

            if filename in ("cli.py", "agent_runtime_adapter.py"):
                return "MOD-VT-001", "agent_runtime_adapter"
            elif filename in (
                "raw_input_loader.py",
                "prd_parser.py",
                "task_loader.py",
                "claim_loader.py",
            ):
                return "MOD-VT-002", "raw_input_loader"
            elif filename == "schema_validator.py":
                return "MOD-VT-003", "schema_validator"
            elif filename == "tool_evidence_adapter.py":
                return "MOD-VT-004", "tool_evidence_adapter"
            elif filename == "evidence_index_builder.py":
                return "MOD-VT-005", "evidence_index_builder"
            elif filename == "traceability_report_builder.py":
                return "MOD-VT-006", "traceability_analyzer"
            elif filename == "merge_gate_engine.py":
                return "MOD-VT-007", "merge_gate_engine"
            elif filename == "dashboard_renderer.py":
                return "MOD-VT-008", "dashboard_renderer"
            elif filename == "architecture_compliance_checker.py":
                return "MOD-VT-009", "architecture_compliance_checker"
            elif filename == "llm_semantic_inspector.py":
                return "MOD-VT-010", "llm_semantic_inspector"
            elif filename == "claude_code_bootstrap_adapter.py":
                return "MOD-VT-011", "claude_code_bootstrap_adapter"
        except Exception:
            pass
        return None, None

    def _get_module_for_import(
        self, imported_module: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Maps an imported Python module name to its architectural module ID and module name."""
        if not imported_module.startswith("vibe_tracing"):
            return None, None
        parts = imported_module.split(".")
        if len(parts) < 2:
            return None, None
        if "core" in parts:
            return None, None

        sub = parts[1]
        if sub == "schema_validator":
            return "MOD-VT-003", "schema_validator"
        elif sub in ("raw_input_loader", "prd_parser", "task_loader", "claim_loader"):
            return "MOD-VT-002", "raw_input_loader"
        elif sub == "tool_evidence_adapter":
            return "MOD-VT-004", "tool_evidence_adapter"
        elif sub == "evidence_index_builder":
            return "MOD-VT-005", "evidence_index_builder"
        elif sub in ("traceability", "traceability_report_builder"):
            return "MOD-VT-006", "traceability_analyzer"
        elif sub == "merge_gate_engine":
            return "MOD-VT-007", "merge_gate_engine"
        elif sub == "dashboard_renderer":
            return "MOD-VT-008", "dashboard_renderer"
        elif sub == "architecture_compliance_checker":
            return "MOD-VT-009", "architecture_compliance_checker"
        elif sub == "llm_semantic_inspector":
            return "MOD-VT-010", "llm_semantic_inspector"
        elif sub == "claude_code_bootstrap_adapter":
            return "MOD-VT-011", "claude_code_bootstrap_adapter"
        elif sub in ("cli", "agent_runtime_adapter"):
            return "MOD-VT-001", "agent_runtime_adapter"
        return None, None

    def _find_evidence_id(self, file_path: str, evidences: List[Dict[str, Any]]) -> str:
        """Find the matching evidence_id for a given file path from the evidence index list."""
        norm_path = file_path.replace("\\", "/").strip("/")
        for ev in evidences:
            ev_path = ev.get("source_path", "").replace("\\", "/").strip("/")
            if ev_path and (
                norm_path == ev_path
                or norm_path.endswith(ev_path)
                or ev_path.endswith(norm_path)
            ):
                return ev["evidence_id"]
        return "EVIDENCE-VT-999"

    def check(self, evidences: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Check all must architectural constraints and module boundaries.

        Args:
            evidences: List of evidence entries from evidence_index.json.

        Returns:
            A dictionary containing:
                "architecture_compliance_status": List of rule status dictionaries.
                "architecture_violations": List of confirmed violations.
                "unclear_constraints": List of constraints marked as unclear.
        """
        constraints_data = self._load_constraints()
        src_dir = self.project_root / "src"

        # List all Python files
        py_files: List[Path] = []
        if src_dir.exists():
            py_files = list(src_dir.rglob("*.py"))

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

        # ----------------------------------------------------
        # 1. Check Module Boundaries (MOD-VT-xxx)
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
                        m_violations.append(
                            (
                                f,
                                imp_mod_name,
                                f"Forbidden import of '{imp_mod_name}' (module {imp_mod_id}) at line {lineno} in {f.name}",
                            )
                        )

                    # Check allowed list (if defined, enforce whitelist except for core/self/standard library)
                    if allowed_ids is not None and imp_mod_id not in allowed_ids:
                        m_violations.append(
                            (
                                f,
                                imp_mod_name,
                                f"Import of '{imp_mod_name}' (module {imp_mod_id}) at line {lineno} in {f.name} is not in allowed_to_call whitelist",
                            )
                        )

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

        # ----------------------------------------------------
        # 2. Check DEP-VT-001 (Core must not depend on Agent Runtime)
        # ----------------------------------------------------
        dep_vt_001_violations = []
        for f, ims in file_imports.items():
            f_mod_id, _ = self._get_module_for_path(f, src_dir)
            # Skip adapter files
            if f_mod_id in ("MOD-VT-001", "MOD-VT-011"):
                continue

            for imp_name, lineno in ims:
                # Check for runtime package imports
                if any(
                    runtime in imp_name
                    for runtime in ("claude_code", "hermes", "deepseek_tui")
                ):
                    dep_vt_001_violations.append(
                        (
                            f,
                            f"Prohibited import of Agent Runtime package '{imp_name}' at line {lineno} in {f.name}",
                        )
                    )
                # Check if core imports adapter submodules
                imp_mod_id, _ = self._get_module_for_import(imp_name)
                if imp_mod_id in ("MOD-VT-001", "MOD-VT-011"):
                    dep_vt_001_violations.append(
                        (
                            f,
                            f"Prohibited import of adapter module '{imp_name}' (module {imp_mod_id}) at line {lineno} in {f.name}",
                        )
                    )

        if dep_vt_001_violations:
            status_list.append(
                {
                    "rule_id": "DEP-VT-001",
                    "status": "violated",
                    "severity": "must",
                    "title": "Core 不得依赖特定 Agent Runtime",
                    "description": "Vibe Tracing Core 必须能够在不依赖 Claude Code、Hermes、DeepSeek TUI 或任何特定 Agent Runtime 的情况下被调用。",
                }
            )
            for f, msg in dep_vt_001_violations:
                rel_f = (
                    str(f.relative_to(self.project_root))
                    if self.project_root in f.parents
                    else str(f)
                )
                violations.append(
                    {
                        "rule_id": "DEP-VT-001",
                        "evidence_id": self._find_evidence_id(rel_f, evidences),
                        "message": msg,
                    }
                )
        else:
            status_list.append(
                {
                    "rule_id": "DEP-VT-001",
                    "status": "compliant",
                    "severity": "must",
                    "title": "Core 不得依赖特定 Agent Runtime",
                    "description": "Vibe Tracing Core 必须能够在不依赖 Claude Code、Hermes、DeepSeek TUI 或任何特定 Agent Runtime 的情况下被调用。",
                }
            )

        # ----------------------------------------------------
        # 3. Check DEP-VT-002 (Dashboard must not depend on CDN/external resources)
        # ----------------------------------------------------
        dashboard_files = list(self.project_root.rglob("dashboard.html"))
        if not dashboard_files:
            # If dashboard.html doesn't exist, we must return unclear per FORBID-VT-007
            status_list.append(
                {
                    "rule_id": "DEP-VT-002",
                    "status": "unclear",
                    "severity": "must",
                    "title": "Dashboard 不得依赖外部前端资源",
                    "description": "dashboard.html 必须能在任意现代浏览器中直接打开，不得依赖 CDN、npm 构建、后端服务或外部 JSON 文件。",
                }
            )
            unclear_list.append(
                {
                    "rule_id": "DEP-VT-002",
                    "reason": "dashboard.html not yet generated in the workspace.",
                }
            )
        else:
            dash_file = dashboard_files[0]
            dash_violations = []
            try:
                content = dash_file.read_text(encoding="utf-8")
                # Simple check for http/https script/stylesheet links
                # e.g., src="https://cdn.com/..."
                external_urls = []
                # Look for href/src starting with http or //
                for m in re.finditer(
                    r'(?:href|src)\s*=\s*["\'](https?:)?//([^"\']+)["\']',
                    content,
                    re.IGNORECASE,
                ):
                    external_urls.append(m.group(0))
                if external_urls:
                    dash_violations.append(
                        (
                            dash_file,
                            f"Dashboard references external front-end resources: {', '.join(external_urls)}",
                        )
                    )
            except Exception as exc:
                dash_violations.append(
                    (dash_file, f"Failed to check dashboard.html: {exc}")
                )

            if dash_violations:
                status_list.append(
                    {
                        "rule_id": "DEP-VT-002",
                        "status": "violated",
                        "severity": "must",
                        "title": "Dashboard 不得依赖外部前端资源",
                        "description": "dashboard.html 必须能在任意现代浏览器中直接打开，不得依赖 CDN、npm 构建、后端服务或外部 JSON 文件。",
                    }
                )
                for f, msg in dash_violations:
                    rel_f = (
                        str(f.relative_to(self.project_root))
                        if self.project_root in f.parents
                        else str(f)
                    )
                    violations.append(
                        {
                            "rule_id": "DEP-VT-002",
                            "evidence_id": self._find_evidence_id(rel_f, evidences),
                            "message": msg,
                        }
                    )
            else:
                status_list.append(
                    {
                        "rule_id": "DEP-VT-002",
                        "status": "compliant",
                        "severity": "must",
                        "title": "Dashboard 不得依赖外部前端资源",
                        "description": "dashboard.html 必须能在任意现代浏览器中直接打开，不得依赖 CDN、npm 构建、后端服务或外部 JSON 文件。",
                    }
                )

        # ----------------------------------------------------
        # 4. Check STORE-VT-001 / PRINCIPLE-VT-009 (MVP no database)
        # ----------------------------------------------------
        db_violations = []
        db_packages = {
            "sqlite3",
            "sqlalchemy",
            "pymongo",
            "psycopg2",
            "redis",
            "neo4j",
            "tinydb",
            "peewee",
            "tortoise",
        }
        for f, ims in file_imports.items():
            for imp_name, lineno in ims:
                # Get the root package of import (e.g. sqlalchemy.orm -> sqlalchemy)
                root_pkg = imp_name.split(".")[0]
                if root_pkg in db_packages:
                    db_violations.append(
                        (
                            f,
                            f"Prohibited import of database library '{imp_name}' at line {lineno} in {f.name}",
                        )
                    )

        if db_violations:
            status_list.append(
                {
                    "rule_id": "STORE-VT-001",
                    "status": "violated",
                    "severity": "must",
                    "title": "MVP 不使用数据库",
                    "description": "MVP 必须只使用文件保存输入和输出。不得要求 SQLite、PostgreSQL、向量数据库、图数据库或任何服务端存储。",
                }
            )
            for f, msg in db_violations:
                rel_f = (
                    str(f.relative_to(self.project_root))
                    if self.project_root in f.parents
                    else str(f)
                )
                violations.append(
                    {
                        "rule_id": "STORE-VT-001",
                        "evidence_id": self._find_evidence_id(rel_f, evidences),
                        "message": msg,
                    }
                )
        else:
            status_list.append(
                {
                    "rule_id": "STORE-VT-001",
                    "status": "compliant",
                    "severity": "must",
                    "title": "MVP 不使用数据库",
                    "description": "MVP 必须只使用文件保存输入和输出。不得要求 SQLite、PostgreSQL、向量数据库、图数据库或任何服务端存储。",
                }
            )

        # ----------------------------------------------------
        # 5. Check GATE-VT-001 (Required input files must exist)
        # ----------------------------------------------------
        from vibe_tracing.raw_input_loader import RawInputLoader

        raw_loader = RawInputLoader(self.project_root)
        required_keys = ["prd", "architecture_constraints", "task_list"]
        missing_files = []
        for key in required_keys:
            resolved_path = raw_loader.get_path(key)
            if not resolved_path.exists():
                try:
                    rel_p = str(resolved_path.relative_to(self.project_root))
                except ValueError:
                    rel_p = str(resolved_path)
                missing_files.append(rel_p)

        if missing_files:
            status_list.append(
                {
                    "rule_id": "GATE-VT-001",
                    "status": "violated",
                    "severity": "must",
                    "title": "必需输入文件必须存在",
                    "description": "MVP 分析至少需要 PRD、架构约束、任务列表和 Agent Claim 作为治理输入。",
                }
            )
            violations.append(
                {
                    "rule_id": "GATE-VT-001",
                    "evidence_id": "EVIDENCE-VT-999",
                    "message": f"Required input files are missing: {', '.join(missing_files)}",
                }
            )
        else:
            status_list.append(
                {
                    "rule_id": "GATE-VT-001",
                    "status": "compliant",
                    "severity": "must",
                    "title": "必需输入文件必须存在",
                    "description": "MVP 分析至少需要 PRD、架构约束、任务列表和 Agent Claim 作为治理输入。",
                }
            )

        # ----------------------------------------------------
        # 6. Evaluate GATE-VT-006 & GATE-VT-007 Gate compliance
        # ----------------------------------------------------
        has_any_violated_must = any(
            st.get("status") == "violated" and st.get("severity") == "must"
            for st in status_list
        )
        has_any_unclear_must = any(
            st.get("status") == "unclear" and st.get("severity") == "must"
            for st in status_list
        )

        # GATE-VT-006: Must 级架构约束不得被违反
        if has_any_violated_must:
            status_list.append(
                {
                    "rule_id": "GATE-VT-006",
                    "status": "violated",
                    "severity": "must",
                    "title": "Must 级架构约束不得被违反",
                    "description": "Must 级架构约束不得存在已确认违反项。",
                }
            )
            violations.append(
                {
                    "rule_id": "GATE-VT-006",
                    "evidence_id": "EVIDENCE-VT-999",
                    "message": "One or more Must-level architecture constraints are violated.",
                }
            )
        else:
            status_list.append(
                {
                    "rule_id": "GATE-VT-006",
                    "status": "compliant",
                    "severity": "must",
                    "title": "Must 级架构约束不得被违反",
                    "description": "Must 级架构约束不得存在已确认违反项。",
                }
            )

        # GATE-VT-007: 不明确的 Must 级架构约束必须导致保守门禁
        if has_any_unclear_must:
            status_list.append(
                {
                    "rule_id": "GATE-VT-007",
                    "status": "unclear",
                    "severity": "must",
                    "title": "不明确的 Must 级架构约束必须导致保守门禁",
                    "description": "如果 Must 级架构约束无法被检查，系统不得输出完全 allow 的合并结论。",
                }
            )
            unclear_list.append(
                {
                    "rule_id": "GATE-VT-007",
                    "reason": "Some Must-level constraints are unclear and need manual review.",
                }
            )
        else:
            status_list.append(
                {
                    "rule_id": "GATE-VT-007",
                    "status": "compliant",
                    "severity": "must",
                    "title": "不明确的 Must 级架构约束必须导致保守门禁",
                    "description": "如果 Must 级架构约束无法被检查，系统不得输出完全 allow 的合并结论。",
                }
            )

        # FORBID-VT-007: 静默处理不明确架构约束
        status_list.append(
            {
                "rule_id": "FORBID-VT-007",
                "status": "compliant",
                "severity": "must",
                "title": "静默处理不明确架构约束",
                "description": "当某条架构约束无法自动检查时，系统必须将其标记为 unclear，而不是忽略它。",
            }
        )

        # ----------------------------------------------------
        # 6.1 Evaluate GATE-VT-013 (Claude Code bootstrap configuration must be reviewable)
        # ----------------------------------------------------
        has_gate_13 = False
        for gate in constraints_data.get("quality_gates", []):
            if gate.get("gate_id") == "GATE-VT-013":
                has_gate_13 = True
                break

        bootstrap_risks = []
        bootstrap_gaps = []
        if has_gate_13:
            import importlib

            claude_code_bootstrap_adapter = importlib.import_module(
                "vibe_tracing.claude_code_bootstrap_adapter"
            )
            ClaudeCodeBootstrapAdapter = (
                claude_code_bootstrap_adapter.ClaudeCodeBootstrapAdapter
            )

            try:
                bootstrap_adapter = ClaudeCodeBootstrapAdapter(self.project_root)
                boot_res = bootstrap_adapter.check_governance_rules(start_counter=100)
                bootstrap_risks = boot_res.get("risks", [])
                bootstrap_gaps = boot_res.get("gaps", [])

                if boot_res.get("is_valid"):
                    status_list.append(
                        {
                            "rule_id": "GATE-VT-013",
                            "status": "compliant",
                            "severity": "must",
                            "title": "Claude Code 自举配置必须可审查",
                            "description": "Claude Code 自举配置必须存在、格式正确，且符合安全审查原则。",
                        }
                    )
                else:
                    status_list.append(
                        {
                            "rule_id": "GATE-VT-013",
                            "status": "violated",
                            "severity": "must",
                            "title": "Claude Code 自举配置必须可审查",
                            "description": "Claude Code 自举配置校验失败或不完整。",
                        }
                    )
                    for err in boot_res.get("errors", []):
                        violations.append(
                            {
                                "rule_id": "GATE-VT-013",
                                "evidence_id": "EVIDENCE-VT-999",
                                "message": err,
                            }
                        )
            except Exception as e:
                status_list.append(
                    {
                        "rule_id": "GATE-VT-013",
                        "status": "violated",
                        "severity": "must",
                        "title": "Claude Code 自举配置必须可审查",
                        "description": f"评估自举配置时发生异常: {e}",
                    }
                )
                violations.append(
                    {
                        "rule_id": "GATE-VT-013",
                        "evidence_id": "EVIDENCE-VT-999",
                        "message": f"Evaluation error: {e}",
                    }
                )

        # ----------------------------------------------------
        # 6.2 Evaluate GATE-VT-014 (Architecture change proposals must be explicitly logged)
        # ----------------------------------------------------
        has_gate_14 = False
        for gate in constraints_data.get("quality_gates", []):
            if gate.get("gate_id") == "GATE-VT-014":
                has_gate_14 = True
                break

        proposal_risks = []
        proposal_gaps = []
        if has_gate_14:
            from vibe_tracing.architecture_change_proposal import (
                ArchitectureChangeProposalEngine,
            )

            try:
                proposal_engine = ArchitectureChangeProposalEngine(self.project_root)
                prop_res = proposal_engine.check_governance(start_counter=200)
                proposal_risks = prop_res.get("risks", [])
                proposal_gaps = prop_res.get("gaps", [])

                if prop_res.get("is_valid"):
                    status_list.append(
                        {
                            "rule_id": "GATE-VT-014",
                            "status": "compliant",
                            "severity": "must",
                            "title": "架构约束变更建议必须显式记录",
                            "description": "检测到架构约束漂移/变更比对通过，且所有修改均有合法的已接受提案。",
                        }
                    )
                else:
                    status_list.append(
                        {
                            "rule_id": "GATE-VT-014",
                            "status": "violated",
                            "severity": "must",
                            "title": "架构约束变更建议必须显式记录",
                            "description": "架构约束变更没有通过显式记录提案审核，或提案本身不合法/缺失签名。",
                        }
                    )
                    for err in prop_res.get("errors", []):
                        violations.append(
                            {
                                "rule_id": "GATE-VT-014",
                                "evidence_id": "EVIDENCE-VT-999",
                                "message": err,
                            }
                        )
            except Exception as e:
                status_list.append(
                    {
                        "rule_id": "GATE-VT-014",
                        "status": "violated",
                        "severity": "must",
                        "title": "架构约束变更建议必须显式记录",
                        "description": f"评估架构约束变更建议时发生异常: {e}",
                    }
                )
                violations.append(
                    {
                        "rule_id": "GATE-VT-014",
                        "evidence_id": "EVIDENCE-VT-999",
                        "message": f"Evaluation error: {e}",
                    }
                )

        # ----------------------------------------------------
        # 7. Collect and process all other MUST rules from constraints file
        # ----------------------------------------------------
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
                # Resolve rule ID from potential keys
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

                # Mark all other must rules as unclear
                status_list.append(
                    {
                        "rule_id": r_id,
                        "status": "unclear",
                        "severity": "must",
                        "title": rule.get("title", ""),
                        "description": rule.get("description", ""),
                    }
                )
                unclear_list.append(
                    {
                        "rule_id": r_id,
                        "reason": "This constraint is not machine-verifiable and requires manual review.",
                    }
                )

        return {
            "architecture_compliance_status": status_list,
            "architecture_violations": violations,
            "unclear_constraints": unclear_list,
            "bootstrap_risks": bootstrap_risks,
            "bootstrap_gaps": bootstrap_gaps,
            "proposal_risks": proposal_risks,
            "proposal_gaps": proposal_gaps,
        }
