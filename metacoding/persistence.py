"""Run persistence: atomic writes, run layout, and resume decisions.

Layout per run::

    .metacoding/runs/<run-id>/
        run.json
        request.md
        initial-plan.json
        rounds/round-001/{planner-instruction,coding-report,tester-report,
                          planner-decision,round}.json
        transcripts/<harness>-<attempt>.{json,stdout,stderr}
        git/{baseline,changes,delivery}.json
        final.json

Human-readable documents live under ``docs/metacoding/``. Every write is
atomic: temporary file in the same directory, ``fsync``, then
``os.replace``.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from metacoding.errors import PersistenceError
from metacoding.models import (
    FinalReport,
    PlannerPlan,
    ProjectSnapshot,
    RoundRecord,
    RunRecord,
    RunStatus,
    now_utc,
    validate_coding_result,
    validate_planner_decision,
    validate_planner_plan,
    validate_tester_report,
)

RUNS_DIRNAME = ".metacoding/runs"
STATE_FILENAME = ".metacoding/state.json"
DOCS_DIRNAME = "docs/metacoding"

PLAN_ARTIFACT = "initial-plan.json"
INSTRUCTION_ARTIFACT = "planner-instruction.json"
CODING_ARTIFACT = "coding-report.json"
TESTER_ARTIFACT = "tester-report.json"
DECISION_ARTIFACT = "planner-decision.json"
ROUND_ARTIFACT = "round.json"


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (tmp file + fsync + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2) + "\n")


def read_json(path: Path) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise PersistenceError(f"cannot read JSON artifact {path}: {exc}") from exc


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{secrets.token_hex(3)}"


@dataclass(frozen=True)
class ResumePlan:
    """What the host should do next for the active run."""

    action: str
    run_id: str | None = None
    round_number: int = 0
    reason: str = ""


class RunStore:
    """Persistence facade for one project root."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.runs_root = self.project_root / RUNS_DIRNAME

    # --- paths -----------------------------------------------------------------

    def run_dir(self, run_id: str) -> Path:
        return self.runs_root / run_id

    def round_dir(self, run_id: str, number: int) -> Path:
        return self.run_dir(run_id) / "rounds" / f"round-{number:03d}"

    def docs_dir(self) -> Path:
        return self.project_root / DOCS_DIRNAME

    def doc_path(self, name: str) -> Path:
        return self.docs_dir() / name

    # --- state pointer ---------------------------------------------------------

    def state_path(self) -> Path:
        return self.project_root / STATE_FILENAME

    def read_state(self) -> dict | None:
        data = read_json(self.state_path())
        return data if isinstance(data, dict) else None

    def set_active_run(self, run_id: str, status: RunStatus) -> None:
        atomic_write_json(
            self.state_path(),
            {"active_run_id": run_id, "status": status.value, "updated_at": now_utc()},
        )

    def clear_active_run(self) -> None:
        try:
            self.state_path().unlink()
        except FileNotFoundError:
            pass

    def latest_run_id(self) -> str | None:
        if not self.runs_root.is_dir():
            return None
        candidates = [path.name for path in self.runs_root.iterdir() if path.is_dir()]
        return max(candidates) if candidates else None

    # --- run lifecycle ---------------------------------------------------------

    def create_run(
        self,
        requirement: str,
        config: Any,
        baseline: ProjectSnapshot,
    ) -> RunRecord:
        run_id = new_run_id()
        run_dir = self.run_dir(run_id)
        for sub in ("rounds", "transcripts", "git"):
            (run_dir / sub).mkdir(parents=True, exist_ok=True)
        record = RunRecord(
            run_id=run_id,
            requirement=requirement,
            status=RunStatus.PLANNING,
            current_round=0,
            created_at=now_utc(),
            updated_at=now_utc(),
            config_snapshot=config.to_dict(),
            baseline=baseline,
        )
        atomic_write_text(run_dir / "request.md", requirement)
        atomic_write_json(run_dir / "run.json", record.to_dict())
        self.set_active_run(run_id, RunStatus.PLANNING)
        return record

    def load_run(self, run_id: str) -> RunRecord:
        path = self.run_dir(run_id) / "run.json"
        if not path.is_file():
            raise PersistenceError(f"run record not found: {path}")
        data = read_json(path)
        try:
            return RunRecord.from_dict(data)
        except Exception as exc:
            raise PersistenceError(f"corrupt run record {path}: {exc}") from exc

    def save_run(self, record: RunRecord, active_status: RunStatus | None = None) -> None:
        record.updated_at = now_utc()
        atomic_write_json(self.run_dir(record.run_id) / "run.json", record.to_dict())
        if active_status is not None:
            self.set_active_run(record.run_id, active_status)
        elif self.read_state() and self.read_state()["active_run_id"] == record.run_id:
            self.set_active_run(record.run_id, record.status)

    # --- rounds ----------------------------------------------------------------

    def start_round(self, run_id: str, number: int, tasks: list[dict]) -> RoundRecord:
        round_dir = self.round_dir(run_id, number)
        round_dir.mkdir(parents=True, exist_ok=True)
        record = RoundRecord(
            number=number,
            status="coding",
            started_at=now_utc(),
            updated_at=now_utc(),
            tasks=[dict(task) for task in tasks],
        )
        atomic_write_json(round_dir / INSTRUCTION_ARTIFACT, {"tasks": record.tasks})
        atomic_write_json(round_dir / ROUND_ARTIFACT, record.to_dict())
        return record

    def save_round(self, run_id: str, record: RoundRecord) -> None:
        record.updated_at = now_utc()
        round_dir = self.round_dir(run_id, record.number)
        round_dir.mkdir(parents=True, exist_ok=True)
        if record.coding_result is not None:
            atomic_write_json(round_dir / CODING_ARTIFACT, record.coding_result.to_dict())
        if record.tester_report is not None:
            atomic_write_json(round_dir / TESTER_ARTIFACT, record.tester_report.to_dict())
        if record.planner_decision is not None:
            atomic_write_json(round_dir / DECISION_ARTIFACT, record.planner_decision.to_dict())
        atomic_write_json(round_dir / ROUND_ARTIFACT, record.to_dict())

    def load_rounds(self, run_id: str) -> dict[int, RoundRecord]:
        rounds_root = self.run_dir(run_id) / "rounds"
        rounds: dict[int, RoundRecord] = {}
        if not rounds_root.is_dir():
            return rounds
        for round_dir in sorted(rounds_root.iterdir()):
            if not round_dir.is_dir():
                continue
            payload = read_json(round_dir / ROUND_ARTIFACT)
            if payload is None:
                continue
            try:
                record = RoundRecord.from_dict(payload)
            except Exception as exc:
                raise PersistenceError(
                    f"corrupt round record {round_dir / ROUND_ARTIFACT}: {exc}"
                ) from exc
            rounds[record.number] = record
        return rounds

    def round_has_artifact(self, run_id: str, number: int, name: str) -> bool:
        return (self.round_dir(run_id, number) / name).is_file()

    # --- plan and documents ----------------------------------------------------

    def save_plan(self, run_id: str, plan: PlannerPlan) -> None:
        atomic_write_json(self.run_dir(run_id) / PLAN_ARTIFACT, plan.to_dict())

    def load_plan(self, run_id: str) -> PlannerPlan | None:
        data = read_json(self.run_dir(run_id) / PLAN_ARTIFACT)
        if data is None:
            return None
        try:
            return validate_planner_plan(data)
        except Exception as exc:
            raise PersistenceError(
                f"corrupt planner plan {self.run_dir(run_id) / PLAN_ARTIFACT}: {exc}"
            ) from exc

    def write_doc(self, name: str, text: str) -> Path:
        path = self.doc_path(name)
        atomic_write_text(path, text)
        return path

    # --- git artifacts ---------------------------------------------------------

    def save_git_artifact(self, run_id: str, name: str, payload: dict) -> None:
        atomic_write_json(self.run_dir(run_id) / "git" / f"{name}.json", payload)

    def load_git_artifact(self, run_id: str, name: str) -> dict | None:
        data = read_json(self.run_dir(run_id) / "git" / f"{name}.json")
        return data if isinstance(data, dict) else None

    # --- transcripts -----------------------------------------------------------

    def save_transcript(
        self,
        run_id: str,
        *,
        harness: str,
        attempt: int,
        metadata: dict,
        stdout: str = "",
        stderr: str = "",
    ) -> Path:
        transcripts = self.run_dir(run_id) / "transcripts"
        transcripts.mkdir(parents=True, exist_ok=True)
        base = f"{harness}-{attempt}"
        atomic_write_json(transcripts / f"{base}.json", metadata)
        if stdout:
            atomic_write_text(transcripts / f"{base}.stdout", stdout)
        if stderr:
            atomic_write_text(transcripts / f"{base}.stderr", stderr)
        return transcripts / f"{base}.json"

    # --- final -----------------------------------------------------------------

    def save_final(self, run_id: str, report: FinalReport) -> None:
        atomic_write_json(self.run_dir(run_id) / "final.json", report.to_dict())

    def load_final(self, run_id: str) -> FinalReport | None:
        data = read_json(self.run_dir(run_id) / "final.json")
        if data is None:
            return None
        try:
            return FinalReport.from_dict(data)
        except Exception as exc:
            raise PersistenceError(
                f"corrupt final report {self.run_dir(run_id) / 'final.json'}: {exc}"
            ) from exc


# --- resume decisions -----------------------------------------------------------


def _load_optional_round_artifact(
    store: RunStore, run_id: str, number: int, name: str
) -> Any:
    """Load a round artifact, treating corrupt content as missing."""
    path = store.round_dir(run_id, number) / name
    if not path.is_file():
        return None
    try:
        return read_json(path)
    except PersistenceError:
        return None


def resolve_resume(store: RunStore) -> ResumePlan:
    """Decide the next action for the active run from persisted state."""
    state = store.read_state()
    if not state or not state.get("active_run_id"):
        return ResumePlan(action="nothing_to_resume")
    run_id = str(state["active_run_id"])
    record = store.load_run(run_id)

    if record.status.terminal:
        return ResumePlan(
            action="cannot_resume_terminal",
            run_id=run_id,
            round_number=record.current_round,
            reason=f"run already ended as {record.status.value}",
        )

    round_number = max(record.current_round, 1)
    status = record.status

    if status is RunStatus.PLANNING:
        return ResumePlan(action="rerun_planner", run_id=run_id, round_number=0)

    coding = _load_optional_round_artifact(store, run_id, round_number, CODING_ARTIFACT)
    tester = _load_optional_round_artifact(store, run_id, round_number, TESTER_ARTIFACT)

    if status is RunStatus.INTERRUPTED:
        if coding is None:
            return ResumePlan(
                action="rerun_coder", run_id=run_id, round_number=round_number,
                reason="interrupted before the coding report was written",
            )
        if tester is None:
            return ResumePlan(
                action="rerun_tester", run_id=run_id, round_number=round_number,
                reason="interrupted before the tester report was written",
            )
        return ResumePlan(
            action="rerun_planner_review", run_id=run_id, round_number=round_number,
            reason="interrupted before the planner decision was written",
        )

    action_by_status = {
        RunStatus.CODING: "rerun_coder",
        RunStatus.TESTING: "rerun_tester",
        RunStatus.PLANNER_REVIEW: "rerun_planner_review",
    }
    action = action_by_status.get(status, "rerun_coder")
    if status is RunStatus.TESTING and coding is None:
        action = "rerun_coder"
    return ResumePlan(
        action=action,
        run_id=run_id,
        round_number=round_number,
        reason=f"run was persisted in state {status.value}",
    )
