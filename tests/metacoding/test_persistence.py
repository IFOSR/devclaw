"""Atomic run persistence and file layout behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from metacoding.config import default_config
from metacoding.errors import PersistenceError
from metacoding.models import (
    FinalReport,
    ProjectSnapshot,
    RunStatus,
    now_utc,
    validate_coding_result,
    validate_planner_decision,
    validate_tester_report,
)
from metacoding.persistence import RunStore


def make_snapshot() -> ProjectSnapshot:
    return ProjectSnapshot(
        captured_at=now_utc(),
        is_git_repo=True,
        git_head="abc123",
        dirty_files=[],
        file_inventory=["README.md"],
        test_commands=["python3 -m pytest -q"],
    )


def make_coding_payload() -> dict:
    return {
        "status": "completed",
        "summary": "implemented",
        "completed_tasks": ["TASK-001"],
        "changed_files": ["src/app.py"],
        "tests_added_or_changed": [],
        "commands_run": [],
        "known_limitations": [],
        "blocked_reason": None,
    }


def make_tester_payload(status: str = "pass") -> dict:
    return {
        "status": status,
        "test_commands": [
            {"command": "python3 -m pytest -q", "exit_code": 0, "summary": "ok"}
        ],
        "acceptance_results": [
            {"id": "F-001", "status": "pass", "impact": "high", "evidence": ["t"]}
        ],
        "findings": [],
        "prd_drift": [],
        "regression_risks": [],
        "missing_tests": [],
        "changed_files": [],
    }


def make_decision_payload(decision: str = "accept") -> dict:
    payload = {
        "decision": decision,
        "reason": "ok",
        "blocking_findings": [],
        "rework_tasks": [],
    }
    if decision == "rework":
        payload["rework_tasks"] = [
            {
                "id": "REWORK-001",
                "description": "fix the bug",
                "target_area": ["src/app.py"],
                "verification": "rerun tests",
            }
        ]
    return payload


@pytest.fixture()
def store(tmp_path: Path) -> RunStore:
    return RunStore(tmp_path)


def created_record(store: RunStore):
    record = store.create_run(
        requirement="add audit log",
        config=default_config(),
        baseline=make_snapshot(),
    )
    return record


def test_create_run_writes_layout_and_state_pointer(store: RunStore) -> None:
    record = created_record(store)
    run_dir = store.run_dir(record.run_id)
    assert (run_dir / "run.json").is_file()
    assert (run_dir / "request.md").read_text(encoding="utf-8") == "add audit log"
    assert (run_dir / "rounds").is_dir()
    assert (run_dir / "transcripts").is_dir()
    assert (run_dir / "git").is_dir()
    state = store.read_state()
    assert state["active_run_id"] == record.run_id
    assert state["status"] == RunStatus.PLANNING.value


def test_run_record_round_trip_and_config_snapshot(store: RunStore) -> None:
    record = created_record(store)
    loaded = store.load_run(record.run_id)
    assert loaded == record
    assert loaded.config_snapshot["harness"]["planner"]["provider"] == "codex"
    assert loaded.baseline.git_head == "abc123"


def test_status_updates_persist_to_run_and_state(store: RunStore) -> None:
    record = created_record(store)
    record.status = RunStatus.CODING
    record.current_round = 1
    store.save_run(record, active_status=RunStatus.CODING)
    assert store.load_run(record.run_id).status is RunStatus.CODING
    assert store.read_state()["status"] == "coding"


def test_round_artifacts_append_without_overwriting(store: RunStore) -> None:
    record = created_record(store)
    round_one = store.start_round(record.run_id, 1, tasks=[{"id": "TASK-001"}])
    round_one.coding_result = validate_coding_result(make_coding_payload())
    round_one.tester_report = validate_tester_report(make_tester_payload())
    round_one.planner_decision = validate_planner_decision(make_decision_payload("rework"))
    store.save_round(record.run_id, round_one)

    round_two = store.start_round(record.run_id, 2, tasks=[{"id": "REWORK-001"}])
    round_two.coding_result = validate_coding_result(make_coding_payload())
    store.save_round(record.run_id, round_two)

    rounds = store.load_rounds(record.run_id)
    assert sorted(rounds) == [1, 2]
    assert rounds[1].planner_decision is not None
    assert rounds[1].planner_decision.decision == "rework"
    assert rounds[2].tester_report is None
    round_dir = store.round_dir(record.run_id, 1)
    assert (round_dir / "planner-instruction.json").is_file()
    assert (round_dir / "coding-report.json").is_file()
    assert (round_dir / "tester-report.json").is_file()
    assert (round_dir / "planner-decision.json").is_file()


def test_transcripts_are_written_per_harness_and_attempt(store: RunStore) -> None:
    record = created_record(store)
    store.save_transcript(
        record.run_id,
        harness="codex-planner",
        attempt=1,
        metadata={"command": ["codex", "exec"], "exit_code": 0},
        stdout="hello",
        stderr="",
    )
    store.save_transcript(
        record.run_id,
        harness="pi-coder",
        attempt=1,
        metadata={"command": ["pi", "-p"], "exit_code": 0},
        stdout="",
        stderr="",
    )
    transcripts = store.run_dir(record.run_id) / "transcripts"
    assert (transcripts / "codex-planner-1.json").is_file()
    assert (transcripts / "codex-planner-1.stdout").read_text(encoding="utf-8") == "hello"
    meta = json.loads((transcripts / "codex-planner-1.json").read_text(encoding="utf-8"))
    assert meta["command"] == ["codex", "exec"]
    assert (transcripts / "pi-coder-1.json").is_file()


def test_docs_written_atomically_under_docs_metacoding(store: RunStore, tmp_path: Path) -> None:
    store.write_doc("TEST_REPORT.md", "# Report v1\n")
    doc = tmp_path / "docs" / "metacoding" / "TEST_REPORT.md"
    assert doc.read_text(encoding="utf-8") == "# Report v1\n"
    store.write_doc("TEST_REPORT.md", "# Report v2\n")
    assert doc.read_text(encoding="utf-8") == "# Report v2\n"
    assert not list((tmp_path / "docs" / "metacoding").glob("*.tmp"))


def test_git_artifacts_round_trip(store: RunStore) -> None:
    record = created_record(store)
    store.save_git_artifact(record.run_id, "baseline", {"git_head": "abc", "dirty": []})
    assert store.load_git_artifact(record.run_id, "baseline") == {
        "git_head": "abc",
        "dirty": [],
    }
    assert store.load_git_artifact(record.run_id, "delivery") is None


def test_final_report_round_trip(store: RunStore) -> None:
    record = created_record(store)
    report = FinalReport(
        run_id=record.run_id,
        outcome="delivered",
        reason="accepted",
        summary="done",
        rounds_used=1,
        artifacts={"final_report": "docs/metacoding/FINAL_REPORT.md"},
        known_limitations=[],
        warnings=[],
        github=None,
        created_at=now_utc(),
    )
    store.save_final(record.run_id, report)
    assert store.load_final(record.run_id) == report
    store.clear_active_run()
    assert store.read_state() is None
    assert store.latest_run_id() == record.run_id


def test_corrupt_run_json_raises_with_path(store: RunStore) -> None:
    record = created_record(store)
    (store.run_dir(record.run_id) / "run.json").write_text("{oops", encoding="utf-8")
    with pytest.raises(PersistenceError) as excinfo:
        store.load_run(record.run_id)
    assert "run.json" in str(excinfo.value)


def test_corrupt_round_json_raises_with_path(store: RunStore) -> None:
    record = created_record(store)
    round_record = store.start_round(record.run_id, 1, tasks=[])
    store.save_round(record.run_id, round_record)
    (store.round_dir(record.run_id, 1) / "round.json").write_text("nope", encoding="utf-8")
    with pytest.raises(PersistenceError):
        store.load_rounds(record.run_id)


def test_writes_leave_no_temp_files(store: RunStore) -> None:
    record = created_record(store)
    store.write_doc("PRD.md", "x\n")
    store.save_git_artifact(record.run_id, "changes", {"files": []})
    for path in (tmp_path_glob for tmp_path_glob in []):
        pass
    leftovers = [
        path
        for path in store.run_dir(record.run_id).rglob("*")
        if path.name.endswith(".tmp")
    ]
    assert leftovers == []


def test_atomic_replace_survives_rewrites(store: RunStore) -> None:
    record = created_record(store)
    for index in range(5):
        record.updated_at = now_utc()
        store.save_run(record)
        assert store.load_run(record.run_id).run_id == record.run_id
