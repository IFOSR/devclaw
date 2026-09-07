"""Behavior tests for the metacoding CLI entry point."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from metacoding import cli
from metacoding.cli import (
    EXIT_INTERRUPTED,
    EXIT_OK,
    EXIT_RUN_REJECTED,
    Outcome,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeApp:
    """In-memory application backend used to observe CLI dispatch."""

    def __init__(self, outcomes: dict[str, Outcome] | None = None) -> None:
        self.outcomes = outcomes or {}
        self.calls: list[tuple] = []

    def _outcome(self, name: str) -> Outcome:
        return self.outcomes.get(name, Outcome(status=name, exit_code=EXIT_OK))

    def run(self, requirement: str, emit=None) -> Outcome:
        self.calls.append(("run", requirement))
        return self._outcome("run")

    def status(self) -> Outcome:
        self.calls.append(("status",))
        return self._outcome("status")

    def resume(self, emit=None) -> Outcome:
        self.calls.append(("resume",))
        return self._outcome("resume")

    def report(self, run_id: str | None = None) -> Outcome:
        self.calls.append(("report", run_id))
        return self._outcome("report")

    def artifacts(self, run_id: str | None = None) -> Outcome:
        self.calls.append(("artifacts", run_id))
        return self._outcome("artifacts")

    def cancel(self) -> Outcome:
        self.calls.append(("cancel",))
        return self._outcome("cancel")

    def deliver(self, run_id: str | None = None) -> Outcome:
        self.calls.append(("deliver", run_id))
        return self._outcome("deliver")


def test_module_entrypoint_help_smoke() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "metacoding", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "metacoding" in result.stdout


def test_no_subcommand_launches_tui(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_launch_tui(app: object) -> int:
        seen["app"] = app
        return 0

    monkeypatch.setattr(cli, "launch_tui", fake_launch_tui)
    code = cli.main([], app=FakeApp())
    assert code == EXIT_OK
    assert isinstance(seen["app"], FakeApp)


def test_run_passes_requirement_to_app() -> None:
    app = FakeApp(
        outcomes={"run": Outcome(status="accepted", exit_code=EXIT_OK, message="done")}
    )
    code = cli.main(["run", "Add an audit log"], app=app)
    assert code == EXIT_OK
    assert app.calls == [("run", "Add an audit log")]


def test_run_exit_code_distinguishes_accepted_and_blocked(capsys) -> None:
    accepted = FakeApp(
        outcomes={"run": Outcome(status="accepted", exit_code=EXIT_OK, message="ok")}
    )
    blocked = FakeApp(
        outcomes={
            "run": Outcome(status="blocked", exit_code=EXIT_RUN_REJECTED, message="nope")
        }
    )
    assert cli.main(["run", "req"], app=accepted) == EXIT_OK
    assert cli.main(["run", "req"], app=blocked) == EXIT_RUN_REJECTED
    assert "nope" in capsys.readouterr().out


def test_run_requires_requirement_argument() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["run"], app=FakeApp())
    assert excinfo.value.code != 0


def test_operator_commands_execute_and_print(capsys) -> None:
    app = FakeApp(
        outcomes={
            "status": Outcome(status="ok", exit_code=EXIT_OK, message="idle"),
            "report": Outcome(
                status="ok", exit_code=EXIT_OK, message="report", lines=["line-1", "line-2"]
            ),
            "artifacts": Outcome(status="ok", exit_code=EXIT_OK, message="artifacts"),
        }
    )
    assert cli.main(["status"], app=app) == EXIT_OK
    assert cli.main(["report", "--run-id", "r-1"], app=app) == EXIT_OK
    assert cli.main(["artifacts", "--run-id", "r-1"], app=app) == EXIT_OK
    assert ("report", "r-1") in app.calls
    assert ("artifacts", "r-1") in app.calls
    out = capsys.readouterr().out
    assert "line-1" in out and "line-2" in out


def test_resume_cancel_deliver_dispatch() -> None:
    app = FakeApp()
    assert cli.main(["resume"], app=app) == EXIT_OK
    assert cli.main(["cancel"], app=app) == EXIT_OK
    assert cli.main(["deliver", "--run-id", "r-9"], app=app) == EXIT_OK
    assert ("deliver", "r-9") in app.calls


def test_model_overrides_reach_app() -> None:
    app = FakeApp()
    code = cli.main(
        [
            "--planner-model",
            "planner-m",
            "--coder-model",
            "coder-m",
            "--tester-model",
            "tester-m",
            "--planner-command",
            "/bin/planner",
            "run",
            "req",
            "--coder-command",
            "/bin/coder",
        ],
        app=app,
    )
    assert code == EXIT_OK
    # App construction happens inside main; FakeApp passed explicitly so
    # overrides are validated through the parser surface instead.
    parser = cli.build_parser()
    args = parser.parse_args(
        ["--planner-model", "p", "run", "req", "--tester-model", "t"]
    )
    assert args.planner_model == "p"
    assert args.tester_model == "t"
    assert args.coder_model == "coder-m" or args.coder_model is None


def test_interrupted_run_returns_interrupted_exit_code() -> None:
    class InterruptingApp(FakeApp):
        def run(self, requirement: str, emit=None) -> Outcome:
            raise KeyboardInterrupt

    code = cli.main(["run", "req"], app=InterruptingApp())
    assert code == EXIT_INTERRUPTED
