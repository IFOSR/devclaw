"""Serialization and protocol validation tests for boundary models."""

from __future__ import annotations

import pytest

from metacoding.errors import ProtocolError
from metacoding.models import (
    CodingResult,
    FinalReport,
    PlannerDecision,
    PlannerPlan,
    ProjectSnapshot,
    RoundRecord,
    RunRecord,
    RunStatus,
    TesterReport,
    now_utc,
    validate_coding_result,
    validate_planner_decision,
    validate_planner_plan,
    validate_tester_report,
)


def make_plan_dict() -> dict:
    return {
        "goal": "Add audit logging",
        "scope": ["src/admin"],
        "non_goals": ["log rotation"],
        "architecture": {
            "approach": "hook admin mutations",
            "modules": ["src/admin/audit.py"],
            "data_flow": ["mutation -> audit -> store"],
            "risks": ["write amplification"],
        },
        "acceptance_criteria": [
            {
                "id": "F-001",
                "description": "Admin writes append audit entries",
                "priority": "blocking",
                "verification_method": "run admin audit tests",
            }
        ],
        "coding_tasks": [
            {
                "id": "TASK-001",
                "description": "implement audit hook",
                "expected_files": ["src/admin/audit.py"],
                "required_tests": ["tests/test_audit.py"],
                "done_when": "hook covers all admin mutations",
            }
        ],
        "change_policy": {
            "allowed_paths": ["src/admin/**", "tests/**"],
            "protected_paths": ["docs/metacoding/PRD.md"],
            "forbidden_actions": ["force-push"],
        },
    }


def make_coding_dict() -> dict:
    return {
        "status": "completed",
        "summary": "implemented audit hook",
        "completed_tasks": ["TASK-001"],
        "changed_files": ["src/admin/audit.py"],
        "tests_added_or_changed": ["tests/test_audit.py"],
        "commands_run": ["python3 -m pytest -q tests/test_audit.py"],
        "known_limitations": [],
        "blocked_reason": None,
    }


def make_tester_dict() -> dict:
    return {
        "status": "pass",
        "test_commands": [
            {"command": "python3 -m pytest -q", "exit_code": 0, "summary": "all green"}
        ],
        "acceptance_results": [
            {
                "id": "F-001",
                "status": "pass",
                "impact": "high",
                "evidence": ["tests/test_audit.py::test_append"],
            }
        ],
        "findings": [],
        "prd_drift": [],
        "regression_risks": [],
        "missing_tests": [],
        "changed_files": [],
    }


def make_decision_dict(decision: str = "rework") -> dict:
    payload: dict = {
        "decision": decision,
        "reason": "one blocking finding remains",
        "blocking_findings": ["BUG-001"],
        "rework_tasks": [
            {
                "id": "REWORK-001",
                "description": "fix null handling",
                "target_area": ["src/admin/audit.py"],
                "verification": "rerun audit tests",
            }
        ],
    }
    if decision != "rework":
        payload["rework_tasks"] = []
    return payload


# --- enum and status behavior -------------------------------------------------


def test_run_status_values_and_terminal_states() -> None:
    assert RunStatus.PLANNING.value == "planning"
    assert RunStatus("coding") is RunStatus.CODING
    terminal = {
        RunStatus.DELIVERED,
        RunStatus.BLOCKED,
        RunStatus.FAILED_INFRASTRUCTURE,
        RunStatus.HUMAN_REVIEW_REQUIRED,
        RunStatus.CANCELLED,
    }
    assert terminal <= set(RunStatus)
    assert RunStatus.PLANNING not in terminal
    assert not RunStatus.DELIVERED.resumable
    assert RunStatus.INTERRUPTED.resumable
    assert RunStatus.CODING.resumable


def test_now_utc_is_iso8601_utc() -> None:
    stamp = now_utc()
    assert stamp.endswith("Z") and "T" in stamp


# --- record round trips -------------------------------------------------------


def test_run_record_round_trip() -> None:
    snapshot = ProjectSnapshot(
        captured_at=now_utc(),
        is_git_repo=True,
        git_head="abc123",
        dirty_files=["existing.txt"],
        file_inventory=["README.md", "src/app.py"],
        test_commands=["python3 -m pytest -q"],
    )
    record = RunRecord(
        run_id="20260907-120000-abcdef",
        requirement="add audit log",
        status=RunStatus.PLANNING,
        current_round=0,
        created_at=now_utc(),
        updated_at=now_utc(),
        config_snapshot={"limits": {"max_rounds": 6}},
        baseline=snapshot,
    )
    data = record.to_dict()
    assert data["baseline"]["git_head"] == "abc123"
    restored = RunRecord.from_dict(data)
    assert restored == record


def test_round_record_round_trip() -> None:
    coding = validate_coding_result(make_coding_dict())
    tester = validate_tester_report(make_tester_dict())
    decision = validate_planner_decision(make_decision_dict("accept"))
    record = RoundRecord(
        number=1,
        status="complete",
        started_at=now_utc(),
        updated_at=now_utc(),
        tasks=[{"id": "TASK-001", "description": "implement audit hook"}],
        coding_result=coding,
        tester_report=tester,
        planner_decision=decision,
        changed_files=["src/admin/audit.py"],
    )
    restored = RoundRecord.from_dict(record.to_dict())
    assert restored == record
    assert restored.coding_result is not None
    assert restored.coding_result.changed_files == ["src/admin/audit.py"]


def test_final_report_round_trip_keeps_relative_posix_paths() -> None:
    report = FinalReport(
        run_id="run-1",
        outcome="delivered",
        reason="planner accepted",
        summary="audit log delivered",
        rounds_used=2,
        artifacts={"final_report": "docs/metacoding/FINAL_REPORT.md"},
        known_limitations=["no rotation"],
        warnings=[],
        github=None,
        created_at=now_utc(),
    )
    restored = FinalReport.from_dict(report.to_dict())
    assert restored == report
    assert "\\" not in restored.artifacts["final_report"]


def test_run_record_from_dict_rejects_corrupt_payload() -> None:
    with pytest.raises(ProtocolError):
        RunRecord.from_dict({"run_id": 123})


# --- protocol validators ------------------------------------------------------


def test_validate_planner_plan_accepts_valid_payload() -> None:
    plan = validate_planner_plan(make_plan_dict())
    assert isinstance(plan, PlannerPlan)
    assert plan.acceptance_criteria[0].id == "F-001"
    assert plan.change_policy.allowed_paths == ["src/admin/**", "tests/**"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("goal"),
        lambda p: p["architecture"].pop("approach"),
        lambda p: p.__setitem__("acceptance_criteria", []),
        lambda p: p["acceptance_criteria"][0].__setitem__("priority", "kinda-important"),
        lambda p: p["coding_tasks"].clear(),
        lambda p: p["change_policy"].__setitem__("allowed_paths", []),
        lambda p: p["change_policy"].pop("protected_paths"),
    ],
)
def test_validate_planner_plan_rejects_invalid_payloads(mutate) -> None:
    payload = make_plan_dict()
    mutate(payload)
    with pytest.raises(ProtocolError):
        validate_planner_plan(payload)


def test_validate_coding_result_completed_and_blocked() -> None:
    completed = validate_coding_result(make_coding_dict())
    assert completed.status == "completed"
    blocked_payload = make_coding_dict()
    blocked_payload.update({"status": "blocked", "blocked_reason": "missing dependency"})
    blocked = validate_coding_result(blocked_payload)
    assert blocked.blocked_reason == "missing dependency"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.__setitem__("status", "finished"),
        lambda p: p.__setitem__("summary", ""),
        lambda p: (p.__setitem__("status", "blocked"), p.__setitem__("blocked_reason", None)),
        lambda p: p.pop("changed_files"),
    ],
)
def test_validate_coding_result_rejects_invalid_payloads(mutate) -> None:
    payload = make_coding_dict()
    mutate(payload)
    with pytest.raises(ProtocolError):
        validate_coding_result(payload)


def test_validate_tester_report_requires_core_sections() -> None:
    report = validate_tester_report(make_tester_dict())
    assert report.test_commands[0].exit_code == 0
    assert isinstance(report, TesterReport)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.__setitem__("status", "unknown"),
        lambda p: p.pop("test_commands"),
        lambda p: p.pop("acceptance_results"),
        lambda p: p.pop("findings"),
        lambda p: p.pop("changed_files"),
        lambda p: p["acceptance_results"][0].__setitem__("status", "maybe"),
        lambda p: p.__setitem__(
            "findings",
            [
                {
                    "id": "BUG-1",
                    "type": "bug",
                    "severity": "P9",
                    "title": "x",
                    "impact": "y",
                    "reproduction": [],
                    "evidence": [],
                    "recommended_fix": "",
                }
            ],
        ),
    ],
)
def test_validate_tester_report_rejects_invalid_payloads(mutate) -> None:
    payload = make_tester_dict()
    mutate(payload)
    with pytest.raises(ProtocolError):
        validate_tester_report(payload)


def test_validate_tester_report_finding_evidence_required() -> None:
    payload = make_tester_dict()
    payload["findings"] = [
        {
            "id": "BUG-001",
            "type": "bug",
            "severity": "P1",
            "title": "crash",
            "impact": "high",
            "reproduction": ["run x"],
            "evidence": [],
            "recommended_fix": "guard input",
        }
    ]
    with pytest.raises(ProtocolError):
        validate_tester_report(payload)


def test_validate_planner_decision_variants() -> None:
    for decision in ("accept", "rework", "blocked", "human_review_required"):
        parsed = validate_planner_decision(make_decision_dict(decision))
        assert parsed.decision == decision
    with pytest.raises(ProtocolError):
        validate_planner_decision(make_decision_dict("ship-it"))
    with pytest.raises(ProtocolError):
        payload = make_decision_dict("rework")
        payload["rework_tasks"] = []
        validate_planner_decision(payload)


def test_validators_never_fill_defaults_silently() -> None:
    payload = make_plan_dict()
    del payload["non_goals"]
    with pytest.raises(ProtocolError) as excinfo:
        validate_planner_plan(payload)
    assert "non_goals" in str(excinfo.value)
