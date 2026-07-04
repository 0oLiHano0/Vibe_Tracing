"""Task session manager — task_sessions.json 读写、状态机、immutability、closed task 检测。

基于 docs/design_channel_separation.md §3.1 / §3.3.2。

状态机：
    OPEN (首次 seen，隐式，不持久化) → IN_PROGRESS (创建即进入) → CLOSED (gate=PASS 且 task 在当前 commit set)

CLOSED 为终态，任何写入尝试被忽略（immutability）。

issue_counts key 格式：
    - 非架构类 issue：issue_type（如 'no_claim'）
    - 架构合规类：issue_type:rule_id（如 'chain_broken:GATE-VT-006'）
    - 子分类：issue_type:subtype（如 'substandard:coverage'）

task 归属：
    按 IssueSignal.task_id 匹配 current_commit_task_set 中的 task；
    为空或不在 set 中时，归入 sorted(current_commit_task_set) 的首个 task。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from vibe_tracing.domain.gate.types import (
    DetectedIssue,
    IssueSignal,
    OutputState,
    Severity,
)

SCHEMA_VERSION = "1.0.0"
_FILENAME = "task_sessions.json"

Clock = Callable[[], str]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class AcceptanceSummary:
    """Task CLOSED 时写入的验收摘要快照。

    字段：
        recommendation: 'accept' | 'reject'，由 severe_risks 是否为空决定
        delivery: task 标题（来自 pipeline 传入的 task_name_lookup）
        severe_risks: business_impact == 'high' 的 remaining WARNING issue 描述列表
        resolved_block: CLOSED 时 RESOLVED 且 severity==BLOCK 的累计数
        resolved_warning: CLOSED 时 RESOLVED 且 severity==WARNING 的累计数
        remaining_warning: CLOSED 时仍为 CURRENT_WARNING 的累计数
    """

    recommendation: str = "accept"
    delivery: str = ""
    severe_risks: List[str] = field(default_factory=list)
    resolved_block: int = 0
    resolved_warning: int = 0
    remaining_warning: int = 0


@dataclass
class TaskSession:
    """单 task 的会话记录。

    字段严格匹配 docs/design_channel_separation.md §3.3.2 schema：
        task_id, phase_id, status, first_seen, closed_at, iterations,
        issue_counts, model, acceptance_summary
    """

    task_id: str
    phase_id: str
    status: str = "IN_PROGRESS"
    first_seen: str = ""
    closed_at: str = ""
    iterations: int = 0
    issue_counts: Dict[str, Dict[str, int]] = field(default_factory=dict)
    model: str = "unknown"
    acceptance_summary: Optional[AcceptanceSummary] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if self.acceptance_summary is None:
            data["acceptance_summary"] = None
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskSession":
        summary_data = data.get("acceptance_summary")
        summary = AcceptanceSummary(**summary_data) if summary_data else None
        return cls(
            task_id=data["task_id"],
            phase_id=data["phase_id"],
            status=data.get("status", "IN_PROGRESS"),
            first_seen=data.get("first_seen", ""),
            closed_at=data.get("closed_at", ""),
            iterations=data.get("iterations", 0),
            issue_counts=data.get("issue_counts", {}),
            model=data.get("model", "unknown"),
            acceptance_summary=summary,
        )


class TaskSessionManager:
    """task_sessions.json 的读写、状态机、immutability、closed task 检测。

    加载规则：文件不存在时视为 {"schema_version": "1.0.0", "tasks": {}}；
    首次 update_sessions 时创建文件。

    并发写入：单进程模型，无需锁。
    """

    def __init__(
        self,
        project_root: Path,
        clock: Optional[Clock] = None,
    ) -> None:
        self._path = Path(project_root) / ".vibetracing" / _FILENAME
        self._clock = clock or _utcnow_iso
        self._data: Dict[str, Any] = {"schema_version": SCHEMA_VERSION, "tasks": {}}
        self._load()

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def load(self) -> Dict[str, Any]:
        """显式重新加载文件；构造时已自动加载，通常无需调用。"""
        self._load()
        return self._data

    @property
    def sessions(self) -> Dict[str, TaskSession]:
        return {tid: TaskSession.from_dict(raw) for tid, raw in self._data["tasks"].items()}

    def get_session(self, task_id: str) -> Optional[TaskSession]:
        raw = self._data["tasks"].get(task_id)
        return TaskSession.from_dict(raw) if raw else None

    def is_closed(self, task_id: str) -> bool:
        raw = self._data["tasks"].get(task_id)
        return bool(raw and raw.get("status") == "CLOSED")

    def find_closed_references(self, current_commit_task_set: Set[str]) -> List[str]:
        """返回 current_commit_task_set 中已 CLOSED 的 task_id 列表。

        调用方在 _run_gate_evaluation 之前调用；非空则 sys.exit(3) 短路，
        与常规 gate BLOCKED 的 exit 2 隔离（§2.3.1）。
        """
        return sorted(
            tid for tid in current_commit_task_set
            if self._data["tasks"].get(tid, {}).get("status") == "CLOSED"
        )

    def update_sessions(
        self,
        current_commit_task_set: Set[str],
        states_and_signals: List[Tuple[OutputState, IssueSignal, DetectedIssue]],
        gate_decision: str,
        task_name_lookup: Dict[str, str],
        phase_id_lookup: Dict[str, str],
        model: str,
    ) -> None:
        """按 4 步编排中第 3 步更新 task_sessions.json（§3.2.1）。

        对 current_commit_task_set 中的每个 task：
            - 不存在 → 创建 IN_PROGRESS（首次 seen）
            - 已 CLOSED → 跳过（immutability）
            - IN_PROGRESS → 累加 iterations、issue_counts；
              若 gate_decision == 'pass' 则 CLOSED，写入 closed_at + acceptance_summary.delivery

        issue 归属按 IssueSignal.task_id 匹配；为空或不在 set 中时
        归入 sorted(current_commit_task_set) 的首个 task。
        """
        if not current_commit_task_set:
            return

        sorted_tasks = sorted(current_commit_task_set)
        default_task = sorted_tasks[0]

        for task_id in sorted_tasks:
            self._ensure_session(task_id, phase_id_lookup.get(task_id, ""), model)
            session_raw = self._data["tasks"][task_id]
            if session_raw["status"] == "CLOSED":
                continue
            session_raw["iterations"] += 1

        self._accumulate_issues(states_and_signals, current_commit_task_set, default_task)

        if gate_decision == "pass":
            for task_id in sorted_tasks:
                session_raw = self._data["tasks"][task_id]
                if session_raw["status"] == "CLOSED":
                    continue
                session_raw["status"] = "CLOSED"
                session_raw["closed_at"] = self._clock()
                session_raw["acceptance_summary"] = asdict(
                    AcceptanceSummary(
                        delivery=task_name_lookup.get(task_id, ""),
                    )
                )

        self._save()

    # ------------------------------------------------------------------ #
    # 私有方法
    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._data = {"schema_version": SCHEMA_VERSION, "tasks": {}}
            return
        try:
            self._data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            self._data = {"schema_version": SCHEMA_VERSION, "tasks": {}}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _ensure_session(self, task_id: str, phase_id: str, model: str) -> None:
        if task_id in self._data["tasks"]:
            return
        self._data["tasks"][task_id] = asdict(
            TaskSession(
                task_id=task_id,
                phase_id=phase_id,
                status="IN_PROGRESS",
                first_seen=self._clock(),
                model=model,
            )
        )

    def _accumulate_issues(
        self,
        states_and_signals: List[Tuple[OutputState, IssueSignal, DetectedIssue]],
        current_commit_task_set: Set[str],
        default_task: str,
    ) -> None:
        for state, signal, _issue in states_and_signals:
            target = signal.task_id
            if not target or target not in current_commit_task_set:
                target = default_task
            session_raw = self._data["tasks"].get(target)
            if session_raw is None or session_raw["status"] == "CLOSED":
                continue

            key = self._issue_counts_key(_issue)
            bucket = session_raw["issue_counts"].setdefault(key, {"BLOCK": 0, "WARNING": 0})
            if state == OutputState.CURRENT_BLOCK:
                bucket["BLOCK"] += 1
            elif state == OutputState.CURRENT_WARNING:
                bucket["WARNING"] += 1

    @staticmethod
    def _issue_counts_key(issue: DetectedIssue) -> str:
        """构造 issue_counts 的复合 key。

        架构合规类 issue（chain_broken / substandard / chain_misaligned）用 issue_type:item_id 作为 rule_id 粒度；
        其余用纯 issue_type。
        """
        arch_types = {"chain_broken", "chain_misaligned", "substandard"}
        if issue.issue_type in arch_types and issue.item_id:
            return f"{issue.issue_type}:{issue.item_id}"
        return issue.issue_type
