"""Boundary models and structured protocol validation.

Records persisted under ``.metacoding/`` and payloads exchanged with the
three harnesses are represented here. Timestamps are ISO 8601 UTC strings
and file paths are stored as POSIX strings relative to the project root.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from metacoding.errors import ProtocolError

SEVERITIES = ("P0", "P1", "P2", "P3")
PRIORITIES = ("blocking", "non_blocking")
DECISIONS = ("accept", "rework", "blocked", "human_review_required")
ACCEPTANCE_STATUSES = ("pass", "fail")
IMPACTS = ("high", "medium", "low")


def now_utc() -> str:
    """Current time as an ISO 8601 UTC string ending in ``Z``."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class RunStatus(str, Enum):
    """Persisted lifecycle states of a run."""

    IDLE = "idle"
    PLANNING = "planning"
    CODING = "coding"
    TESTING = "testing"
    PLANNER_REVIEW = "planner_review"
    ACCEPTED = "accepted"
    GITHUB_DELIVERY = "github_delivery"
    DELIVERED = "delivered"
    BLOCKED = "blocked"
    FAILED_INFRASTRUCTURE = "failed_infrastructure"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"

    @property
    def resumable(self) -> bool:
        return self in {
            RunStatus.PLANNING,
            RunStatus.CODING,
            RunStatus.TESTING,
            RunStatus.PLANNER_REVIEW,
            RunStatus.INTERRUPTED,
        }

    @property
    def terminal(self) -> bool:
        return self in {
            RunStatus.DELIVERED,
            RunStatus.BLOCKED,
            RunStatus.FAILED_INFRASTRUCTURE,
            RunStatus.HUMAN_REVIEW_REQUIRED,
            RunStatus.CANCELLED,
        }


# --- internal payload helpers -------------------------------------------------


def _require_mapping(value: Any, what: str) -> dict:
    if not isinstance(value, dict):
        raise ProtocolError(f"{what} must be an object, got {type(value).__name__}")
    return value


def _require_str(mapping: dict, key: str, what: str, *, allow_empty: bool = True) -> str:
    if key not in mapping:
        raise ProtocolError(f"{what} is missing required field '{key}'")
    value = mapping[key]
    if not isinstance(value, str):
        raise ProtocolError(f"{what} field '{key}' must be a string")
    if not allow_empty and not value.strip():
        raise ProtocolError(f"{what} field '{key}' must not be empty")
    return value


def _require_optional_str(mapping: dict, key: str, what: str) -> str | None:
    if key not in mapping:
        raise ProtocolError(f"{what} is missing required field '{key}'")
    value = mapping[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProtocolError(f"{what} field '{key}' must be a string or null")
    return value


def _require_str_list(mapping: dict, key: str, what: str, *, allow_empty: bool = True) -> list[str]:
    if key not in mapping:
        raise ProtocolError(f"{what} is missing required field '{key}'")
    value = mapping[key]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ProtocolError(f"{what} field '{key}' must be a list of strings")
    if not allow_empty and not value:
        raise ProtocolError(f"{what} field '{key}' must not be empty")
    return list(value)


def _require_list(
    mapping: dict, key: str, what: str, *, allow_empty: bool = True
) -> list[Any]:
    if key not in mapping:
        raise ProtocolError(f"{what} is missing required field '{key}'")
    value = mapping[key]
    if not isinstance(value, list):
        raise ProtocolError(f"{what} field '{key}' must be a list")
    if not allow_empty and not value:
        raise ProtocolError(f"{what} field '{key}' must not be empty")
    return list(value)


def _require_int(mapping: dict, key: str, what: str) -> int:
    if key not in mapping:
        raise ProtocolError(f"{what} is missing required field '{key}'")
    value = mapping[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProtocolError(f"{what} field '{key}' must be an integer")
    return value


# --- planner plan -------------------------------------------------------------


@dataclass(frozen=True)
class ChangePolicy:
    allowed_paths: list[str]
    protected_paths: list[str]
    forbidden_actions: list[str]

    def to_dict(self) -> dict:
        return {
            "allowed_paths": list(self.allowed_paths),
            "protected_paths": list(self.protected_paths),
            "forbidden_actions": list(self.forbidden_actions),
        }


@dataclass(frozen=True)
class AcceptanceCriterion:
    id: str
    description: str
    priority: str
    verification_method: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "priority": self.priority,
            "verification_method": self.verification_method,
        }


@dataclass(frozen=True)
class CodingTask:
    id: str
    description: str
    expected_files: list[str]
    required_tests: list[str]
    done_when: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "expected_files": list(self.expected_files),
            "required_tests": list(self.required_tests),
            "done_when": self.done_when,
        }


@dataclass(frozen=True)
class Architecture:
    approach: str
    modules: list[str]
    data_flow: list[str]
    risks: list[str]

    def to_dict(self) -> dict:
        return {
            "approach": self.approach,
            "modules": list(self.modules),
            "data_flow": list(self.data_flow),
            "risks": list(self.risks),
        }


@dataclass(frozen=True)
class PlannerPlan:
    goal: str
    scope: list[str]
    non_goals: list[str]
    architecture: Architecture
    acceptance_criteria: list[AcceptanceCriterion]
    coding_tasks: list[CodingTask]
    change_policy: ChangePolicy

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "scope": list(self.scope),
            "non_goals": list(self.non_goals),
            "architecture": self.architecture.to_dict(),
            "acceptance_criteria": [item.to_dict() for item in self.acceptance_criteria],
            "coding_tasks": [item.to_dict() for item in self.coding_tasks],
            "change_policy": self.change_policy.to_dict(),
        }


def validate_planner_plan(value: Any) -> PlannerPlan:
    """Validate a raw planner plan payload and return the typed plan."""
    data = _require_mapping(value, "planner plan")
    goal = _require_str(data, "goal", "planner plan", allow_empty=False)
    scope = _require_str_list(data, "scope", "planner plan")
    non_goals = _require_str_list(data, "non_goals", "planner plan")

    arch_raw = _require_mapping(data.get("architecture"), "planner plan architecture")
    architecture = Architecture(
        approach=_require_str(arch_raw, "approach", "architecture", allow_empty=False),
        modules=_require_str_list(arch_raw, "modules", "architecture"),
        data_flow=_require_str_list(arch_raw, "data_flow", "architecture"),
        risks=_require_str_list(arch_raw, "risks", "architecture"),
    )

    criteria_raw = _require_list(
        data, "acceptance_criteria", "planner plan", allow_empty=False
    )
    criteria: list[AcceptanceCriterion] = []
    seen_criteria: set[str] = set()
    for index, item in enumerate(criteria_raw):
        item_map = _require_mapping(item, f"acceptance criterion #{index + 1}")
        criterion = AcceptanceCriterion(
            id=_require_str(item_map, "id", f"acceptance criterion #{index + 1}", allow_empty=False),
            description=_require_str(
                item_map, "description", f"acceptance criterion #{index + 1}", allow_empty=False
            ),
            priority=_require_str(item_map, "priority", f"acceptance criterion #{index + 1}"),
            verification_method=_require_str(
                item_map, "verification_method", f"acceptance criterion #{index + 1}"
            ),
        )
        if criterion.priority not in PRIORITIES:
            raise ProtocolError(
                f"acceptance criterion priority must be one of {PRIORITIES}, "
                f"got '{criterion.priority}'"
            )
        if criterion.id in seen_criteria:
            raise ProtocolError(f"duplicate acceptance criterion id '{criterion.id}'")
        seen_criteria.add(criterion.id)
        criteria.append(criterion)

    tasks_raw = _require_list(data, "coding_tasks", "planner plan", allow_empty=False)
    tasks: list[CodingTask] = []
    seen_tasks: set[str] = set()
    for index, item in enumerate(tasks_raw):
        item_map = _require_mapping(item, f"coding task #{index + 1}")
        task = CodingTask(
            id=_require_str(item_map, "id", f"coding task #{index + 1}", allow_empty=False),
            description=_require_str(
                item_map, "description", f"coding task #{index + 1}", allow_empty=False
            ),
            expected_files=_require_str_list(item_map, "expected_files", f"coding task #{index + 1}"),
            required_tests=_require_str_list(item_map, "required_tests", f"coding task #{index + 1}"),
            done_when=_require_str(item_map, "done_when", f"coding task #{index + 1}"),
        )
        if task.id in seen_tasks:
            raise ProtocolError(f"duplicate coding task id '{task.id}'")
        seen_tasks.add(task.id)
        tasks.append(task)

    policy_raw = _require_mapping(data.get("change_policy"), "planner plan change_policy")
    policy = ChangePolicy(
        allowed_paths=_require_str_list(
            policy_raw, "allowed_paths", "change_policy", allow_empty=False
        ),
        protected_paths=_require_str_list(policy_raw, "protected_paths", "change_policy"),
        forbidden_actions=_require_str_list(policy_raw, "forbidden_actions", "change_policy"),
    )

    return PlannerPlan(
        goal=goal,
        scope=scope,
        non_goals=non_goals,
        architecture=architecture,
        acceptance_criteria=criteria,
        coding_tasks=tasks,
        change_policy=policy,
    )


# --- coding result ------------------------------------------------------------


@dataclass(frozen=True)
class CodingResult:
    status: str
    summary: str
    completed_tasks: list[str]
    changed_files: list[str]
    tests_added_or_changed: list[str]
    commands_run: list[str]
    known_limitations: list[str]
    blocked_reason: str | None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "summary": self.summary,
            "completed_tasks": list(self.completed_tasks),
            "changed_files": list(self.changed_files),
            "tests_added_or_changed": list(self.tests_added_or_changed),
            "commands_run": list(self.commands_run),
            "known_limitations": list(self.known_limitations),
            "blocked_reason": self.blocked_reason,
        }


def validate_coding_result(value: Any) -> CodingResult:
    data = _require_mapping(value, "coding result")
    status = _require_str(data, "status", "coding result")
    if status not in ("completed", "blocked"):
        raise ProtocolError(f"coding result status must be 'completed' or 'blocked', got '{status}'")
    summary = _require_str(data, "summary", "coding result")
    blocked_reason = _require_optional_str(data, "blocked_reason", "coding result")
    if status == "completed" and not summary.strip():
        raise ProtocolError("coding result 'summary' must not be empty when completed")
    if status == "blocked" and not (blocked_reason or "").strip():
        raise ProtocolError("coding result 'blocked_reason' is required when status is blocked")
    return CodingResult(
        status=status,
        summary=summary,
        completed_tasks=_require_str_list(data, "completed_tasks", "coding result"),
        changed_files=_require_str_list(data, "changed_files", "coding result"),
        tests_added_or_changed=_require_str_list(data, "tests_added_or_changed", "coding result"),
        commands_run=_require_str_list(data, "commands_run", "coding result"),
        known_limitations=_require_str_list(data, "known_limitations", "coding result"),
        blocked_reason=blocked_reason,
    )


# --- tester report ------------------------------------------------------------


@dataclass(frozen=True)
class TestCommand:
    __test__ = False

    command: str
    exit_code: int
    summary: str

    def to_dict(self) -> dict:
        return {"command": self.command, "exit_code": self.exit_code, "summary": self.summary}


@dataclass(frozen=True)
class AcceptanceResult:
    id: str
    status: str
    impact: str
    evidence: list[str]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "impact": self.impact,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class Finding:
    id: str
    type: str
    severity: str
    title: str
    impact: str
    reproduction: list[str]
    evidence: list[str]
    recommended_fix: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "severity": self.severity,
            "title": self.title,
            "impact": self.impact,
            "reproduction": list(self.reproduction),
            "evidence": list(self.evidence),
            "recommended_fix": self.recommended_fix,
        }


@dataclass(frozen=True)
class TesterReport:
    __test__ = False

    status: str
    test_commands: list[TestCommand]
    acceptance_results: list[AcceptanceResult]
    findings: list[Finding]
    prd_drift: list[str]
    regression_risks: list[str]
    missing_tests: list[str]
    changed_files: list[str]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "test_commands": [item.to_dict() for item in self.test_commands],
            "acceptance_results": [item.to_dict() for item in self.acceptance_results],
            "findings": [item.to_dict() for item in self.findings],
            "prd_drift": list(self.prd_drift),
            "regression_risks": list(self.regression_risks),
            "missing_tests": list(self.missing_tests),
            "changed_files": list(self.changed_files),
        }


def validate_tester_report(value: Any) -> TesterReport:
    data = _require_mapping(value, "tester report")
    status = _require_str(data, "status", "tester report")
    if status not in ACCEPTANCE_STATUSES:
        raise ProtocolError(f"tester report status must be one of {ACCEPTANCE_STATUSES}, got '{status}'")

    commands: list[TestCommand] = []
    for index, item in enumerate(_require_list(data, "test_commands", "tester report")):
        item_map = _require_mapping(item, f"test command #{index + 1}")
        commands.append(
            TestCommand(
                command=_require_str(
                    item_map, "command", f"test command #{index + 1}", allow_empty=False
                ),
                exit_code=_require_int(item_map, "exit_code", f"test command #{index + 1}"),
                summary=_require_str(item_map, "summary", f"test command #{index + 1}"),
            )
        )

    results: list[AcceptanceResult] = []
    for index, item in enumerate(_require_list(data, "acceptance_results", "tester report")):
        item_map = _require_mapping(item, f"acceptance result #{index + 1}")
        result = AcceptanceResult(
            id=_require_str(item_map, "id", f"acceptance result #{index + 1}", allow_empty=False),
            status=_require_str(item_map, "status", f"acceptance result #{index + 1}"),
            impact=_require_str(item_map, "impact", f"acceptance result #{index + 1}"),
            evidence=_require_str_list(item_map, "evidence", f"acceptance result #{index + 1}"),
        )
        if result.status not in ACCEPTANCE_STATUSES:
            raise ProtocolError(
                f"acceptance result status must be one of {ACCEPTANCE_STATUSES}, "
                f"got '{result.status}'"
            )
        if result.impact not in IMPACTS:
            raise ProtocolError(f"acceptance result impact must be one of {IMPACTS}")
        results.append(result)

    findings: list[Finding] = []
    for index, item in enumerate(_require_list(data, "findings", "tester report")):
        item_map = _require_mapping(item, f"finding #{index + 1}")
        finding = Finding(
            id=_require_str(item_map, "id", f"finding #{index + 1}", allow_empty=False),
            type=_require_str(item_map, "type", f"finding #{index + 1}", allow_empty=False),
            severity=_require_str(item_map, "severity", f"finding #{index + 1}"),
            title=_require_str(item_map, "title", f"finding #{index + 1}", allow_empty=False),
            impact=_require_str(item_map, "impact", f"finding #{index + 1}"),
            reproduction=_require_str_list(item_map, "reproduction", f"finding #{index + 1}"),
            evidence=_require_str_list(item_map, "evidence", f"finding #{index + 1}"),
            recommended_fix=_require_str(item_map, "recommended_fix", f"finding #{index + 1}"),
        )
        if finding.severity not in SEVERITIES:
            raise ProtocolError(
                f"finding severity must be one of {SEVERITIES}, got '{finding.severity}'"
            )
        if not finding.evidence:
            raise ProtocolError(f"finding '{finding.id}' must include at least one evidence entry")
        findings.append(finding)

    return TesterReport(
        status=status,
        test_commands=commands,
        acceptance_results=results,
        findings=findings,
        prd_drift=_require_str_list(data, "prd_drift", "tester report"),
        regression_risks=_require_str_list(data, "regression_risks", "tester report"),
        missing_tests=_require_str_list(data, "missing_tests", "tester report"),
        changed_files=_require_str_list(data, "changed_files", "tester report"),
    )


# --- planner decision ---------------------------------------------------------


@dataclass(frozen=True)
class ReworkTask:
    id: str
    description: str
    target_area: list[str]
    verification: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "target_area": list(self.target_area),
            "verification": self.verification,
        }


@dataclass(frozen=True)
class PlannerDecision:
    decision: str
    reason: str
    blocking_findings: list[str]
    rework_tasks: list[ReworkTask]

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "blocking_findings": list(self.blocking_findings),
            "rework_tasks": [item.to_dict() for item in self.rework_tasks],
        }


def validate_planner_decision(value: Any) -> PlannerDecision:
    data = _require_mapping(value, "planner decision")
    decision = _require_str(data, "decision", "planner decision")
    if decision not in DECISIONS:
        raise ProtocolError(f"planner decision must be one of {DECISIONS}, got '{decision}'")
    reason = _require_str(data, "reason", "planner decision", allow_empty=False)
    blocking = _require_str_list(data, "blocking_findings", "planner decision")

    tasks: list[ReworkTask] = []
    raw_tasks = _require_list(data, "rework_tasks", "planner decision")
    for index, item in enumerate(raw_tasks):
        item_map = _require_mapping(item, f"rework task #{index + 1}")
        tasks.append(
            ReworkTask(
                id=_require_str(item_map, "id", f"rework task #{index + 1}", allow_empty=False),
                description=_require_str(
                    item_map, "description", f"rework task #{index + 1}", allow_empty=False
                ),
                target_area=_require_str_list(item_map, "target_area", f"rework task #{index + 1}"),
                verification=_require_str(item_map, "verification", f"rework task #{index + 1}"),
            )
        )
    if decision == "rework" and not tasks:
        raise ProtocolError("planner decision 'rework' requires concrete rework tasks")
    return PlannerDecision(
        decision=decision, reason=reason, blocking_findings=blocking, rework_tasks=tasks
    )


# --- project snapshot ---------------------------------------------------------


@dataclass(frozen=True)
class ProjectSnapshot:
    captured_at: str
    is_git_repo: bool
    git_head: str | None
    dirty_files: list[str]
    file_inventory: list[str]
    test_commands: list[str]

    def to_dict(self) -> dict:
        return {
            "captured_at": self.captured_at,
            "is_git_repo": self.is_git_repo,
            "git_head": self.git_head,
            "dirty_files": list(self.dirty_files),
            "file_inventory": list(self.file_inventory),
            "test_commands": list(self.test_commands),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ProjectSnapshot":
        data = _require_mapping(value, "project snapshot")
        return cls(
            captured_at=_require_str(data, "captured_at", "project snapshot"),
            is_git_repo=bool(data.get("is_git_repo", False)),
            git_head=_require_optional_str(data, "git_head", "project snapshot"),
            dirty_files=_require_str_list(data, "dirty_files", "project snapshot"),
            file_inventory=_require_str_list(data, "file_inventory", "project snapshot"),
            test_commands=_require_str_list(data, "test_commands", "project snapshot"),
        )


# --- run and round records ----------------------------------------------------


@dataclass
class RoundRecord:
    number: int
    status: str
    started_at: str
    updated_at: str
    tasks: list[dict] = field(default_factory=list)
    coding_result: CodingResult | None = None
    tester_report: TesterReport | None = None
    planner_decision: PlannerDecision | None = None
    changed_files: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "status": self.status,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "tasks": [dict(task) for task in self.tasks],
            "coding_result": self.coding_result.to_dict() if self.coding_result else None,
            "tester_report": self.tester_report.to_dict() if self.tester_report else None,
            "planner_decision": self.planner_decision.to_dict() if self.planner_decision else None,
            "changed_files": list(self.changed_files),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "RoundRecord":
        data = _require_mapping(value, "round record")
        coding = data.get("coding_result")
        tester = data.get("tester_report")
        decision = data.get("planner_decision")
        tasks_raw = _require_list(data, "tasks", "round record")
        tasks = [_require_mapping(item, "round task") for item in tasks_raw]
        return cls(
            number=_require_int(data, "number", "round record"),
            status=_require_str(data, "status", "round record"),
            started_at=_require_str(data, "started_at", "round record"),
            updated_at=_require_str(data, "updated_at", "round record"),
            tasks=[dict(task) for task in tasks],
            coding_result=validate_coding_result(coding) if coding else None,
            tester_report=validate_tester_report(tester) if tester else None,
            planner_decision=validate_planner_decision(decision) if decision else None,
            changed_files=_require_str_list(data, "changed_files", "round record"),
            notes=_require_str_list(data, "notes", "round record"),
        )


@dataclass
class RunRecord:
    run_id: str
    requirement: str
    status: RunStatus
    current_round: int
    created_at: str
    updated_at: str
    config_snapshot: dict
    baseline: ProjectSnapshot
    failure_history: list[str] = field(default_factory=list)
    pending_tasks: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "requirement": self.requirement,
            "status": self.status.value,
            "current_round": self.current_round,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "config_snapshot": self.config_snapshot,
            "baseline": self.baseline.to_dict(),
            "failure_history": list(self.failure_history),
            "pending_tasks": [dict(task) for task in self.pending_tasks],
        }

    @classmethod
    def from_dict(cls, value: Any) -> "RunRecord":
        data = _require_mapping(value, "run record")
        status_raw = _require_str(data, "status", "run record")
        try:
            status = RunStatus(status_raw)
        except ValueError as exc:
            raise ProtocolError(f"unknown run status '{status_raw}'") from exc
        snapshot_raw = _require_mapping(data.get("baseline"), "run record baseline")
        config_raw = _require_mapping(data.get("config_snapshot"), "run record config_snapshot")
        return cls(
            run_id=_require_str(data, "run_id", "run record", allow_empty=False),
            requirement=_require_str(data, "requirement", "run record", allow_empty=False),
            status=status,
            current_round=_require_int(data, "current_round", "run record"),
            created_at=_require_str(data, "created_at", "run record"),
            updated_at=_require_str(data, "updated_at", "run record"),
            config_snapshot=dict(config_raw),
            baseline=ProjectSnapshot.from_dict(snapshot_raw),
            failure_history=_require_str_list(data, "failure_history", "run record"),
            pending_tasks=[
                dict(_require_mapping(item, "pending task"))
                for item in _require_list(data, "pending_tasks", "run record")
            ]
            if data.get("pending_tasks") is not None
            else [],
        )


@dataclass(frozen=True)
class FinalReport:
    run_id: str
    outcome: str
    reason: str
    summary: str
    rounds_used: int
    artifacts: dict[str, str]
    known_limitations: list[str]
    warnings: list[str]
    github: dict | None
    created_at: str

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "outcome": self.outcome,
            "reason": self.reason,
            "summary": self.summary,
            "rounds_used": self.rounds_used,
            "artifacts": dict(self.artifacts),
            "known_limitations": list(self.known_limitations),
            "warnings": list(self.warnings),
            "github": self.github,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "FinalReport":
        data = _require_mapping(value, "final report")
        artifacts_raw = data.get("artifacts")
        if not isinstance(artifacts_raw, dict):
            raise ProtocolError("final report field 'artifacts' must be an object")
        github = data.get("github")
        if github is not None and not isinstance(github, dict):
            raise ProtocolError("final report field 'github' must be an object or null")
        return cls(
            run_id=_require_str(data, "run_id", "final report", allow_empty=False),
            outcome=_require_str(data, "outcome", "final report", allow_empty=False),
            reason=_require_str(data, "reason", "final report"),
            summary=_require_str(data, "summary", "final report"),
            rounds_used=_require_int(data, "rounds_used", "final report"),
            artifacts={str(key): str(val) for key, val in artifacts_raw.items()},
            known_limitations=_require_str_list(data, "known_limitations", "final report"),
            warnings=_require_str_list(data, "warnings", "final report"),
            github=dict(github) if github else None,
            created_at=_require_str(data, "created_at", "final report"),
        )
