"""Resume decision behavior based on persisted state."""

from __future__ import annotations

from pathlib import Path

import pytest

from metacoding.config import default_config
from metacoding.models import ProjectSnapshot, RunStatus, now_utc, validate_coding_result
from metacoding.persistence import RunStore, resolve_resume


def make_snapshot() -> ProjectSnapshot:
    return ProjectSnapshot(
        captured_at=now_utc(),
        is_git_repo=False,
        git_head=None,
        dirty_files=[],
        file_inventory=[],
        test_commands=[],
    )


def make_coding_payload() -> dict:
    return {
        "status": "completed",
        "summary": "implemented",
        "completed_tasks": [],
        "changed_files": [],
        "tests_added_or_changed": [],
        "commands_run": [],
        "known_limitations": [],
        "blocked_reason": None,
    }


@pytest.fixture()
def store(tmp_path: Path) -> RunStore:
    return RunStore(tmp_path)


def start_run(store: RunStore) -> str:
    record = store.create_run(
        requirement="req", config=default_config(), baseline=make_snapshot()
    )
    return record.run_id


def set_state(store: RunStore, run_id: str, status: RunStatus, round_number: int = 0) -> None:
    record = store.load_run(run_id)
    record.status = status
    record.current_round = round_number
    store.save_run(record, active_status=status)


def test_no_active_run_means_nothing_to_resume(store: RunStore) -> None:
    plan = resolve_resume(store)
    assert plan.action == "nothing_to_resume"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (RunStatus.PLANNING, "rerun_planner"),
        (RunStatus.CODING, "rerun_coder"),
        (RunStatus.TESTING, "rerun_tester"),
        (RunStatus.PLANNER_REVIEW, "rerun_planner_review"),
    ],
)
def test_resume_action_by_status(store: RunStore, status: RunStatus, expected: str) -> None:
    run_id = start_run(store)
    round_record = store.start_round(run_id, 1, tasks=[])
    round_record.coding_result = validate_coding_result(make_coding_payload())
    store.save_round(run_id, round_record)
    set_state(store, run_id, status, round_number=1)
    plan = resolve_resume(store)
    assert plan.action == expected
    assert plan.run_id == run_id
    expected_round = 0 if status is RunStatus.PLANNING else 1
    assert plan.round_number == expected_round


def test_interrupted_run_resumes_from_missing_stage(store: RunStore) -> None:
    run_id = start_run(store)
    round_record = store.start_round(run_id, 1, tasks=[])
    set_state(store, run_id, RunStatus.INTERRUPTED, round_number=1)
    assert resolve_resume(store).action == "rerun_coder"

    round_record.coding_result = validate_coding_result(make_coding_payload())
    store.save_round(run_id, round_record)
    assert resolve_resume(store).action == "rerun_tester"


def test_terminal_runs_cannot_resume(store: RunStore) -> None:
    run_id = start_run(store)
    for status in (RunStatus.DELIVERED, RunStatus.BLOCKED, RunStatus.CANCELLED):
        set_state(store, run_id, status)
        assert resolve_resume(store).action == "cannot_resume_terminal"


def test_corrupt_round_artifact_treated_as_missing(store: RunStore) -> None:
    run_id = start_run(store)
    store.start_round(run_id, 1, tasks=[])
    set_state(store, run_id, RunStatus.TESTING, round_number=1)
    # simulate a partially written coding report
    (store.round_dir(run_id, 1) / "coding-report.json").write_text("{bad", encoding="utf-8")
    plan = resolve_resume(store)
    assert plan.action == "rerun_coder"


def test_resume_reports_missing_current_round_for_coding(store: RunStore) -> None:
    run_id = start_run(store)
    set_state(store, run_id, RunStatus.CODING, round_number=1)
    plan = resolve_resume(store)
    # round 1 was never started; resume replans the round from scratch
    assert plan.action == "rerun_coder"
    assert plan.round_number == 1


def test_resume_rejects_tampered_snapshot_without_fallback(tmp_path: Path, store: RunStore) -> None:
    """A corrupted snapshot blocks the resume; no fallback to config.toml."""
    from metacoding.cli import EXIT_USAGE
    from metacoding.config import default_config
    from metacoding.service import MetaCodingService

    record = store.create_run(
        requirement="req",
        config=default_config(),
        baseline=make_snapshot(),
    )
    # tamper: drop a required snapshot field
    corrupted = record.config_snapshot
    corrupted["harness"].pop("coder")
    record.config_snapshot = corrupted
    store.save_run(record)

    service = MetaCodingService(project_root=tmp_path)
    outcome = service.resume()
    assert outcome.exit_code == EXIT_USAGE
    assert "missing" in outcome.message
