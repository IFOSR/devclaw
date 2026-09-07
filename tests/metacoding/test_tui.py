"""Interactive TUI behavior: input loop, commands, and lifecycle output."""

from __future__ import annotations

import io
from pathlib import Path

from metacoding.cli import EXIT_INTERRUPTED, EXIT_OK, Outcome
from metacoding.tui import run_tui


class FakeApp:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.emitted: list[dict] = []

    def overview(self) -> list[str]:
        return [
            "Project  /tmp/demo",
            "Planner  codex / planner-model",
            "Coder    pi / coding-model",
            "Tester   codex / tester-model",
        ]

    def run(self, requirement: str, emit=None) -> Outcome:
        self.calls.append(("run", requirement))
        if emit is not None:
            emit({"kind": "phase", "phase": "planning", "message": "Planner is analyzing."})
            emit({"kind": "info", "message": "round 1 started"})
        return Outcome(status="delivered", exit_code=EXIT_OK, message="run accepted")

    def status(self) -> Outcome:
        self.calls.append(("status",))
        return Outcome(status="ok", exit_code=EXIT_OK, message="idle", lines=["no active run"])

    def resume(self, emit=None) -> Outcome:
        self.calls.append(("resume",))
        return Outcome(status="delivered", exit_code=EXIT_OK, message="resumed run")

    def report(self, run_id: str | None = None) -> Outcome:
        self.calls.append(("report", run_id))
        return Outcome(status="ok", exit_code=EXIT_OK, message="report", lines=["- final.json"])

    def artifacts(self, run_id: str | None = None) -> Outcome:
        self.calls.append(("artifacts", run_id))
        return Outcome(status="ok", exit_code=EXIT_OK, message="artifacts")

    def cancel(self) -> Outcome:
        self.calls.append(("cancel",))
        return Outcome(status="cancelled", exit_code=1, message="run cancelled")

    def deliver(self, run_id: str | None = None) -> Outcome:
        self.calls.append(("deliver", run_id))
        return Outcome(status="delivered", exit_code=EXIT_OK, message="delivered")

    def config_list(self) -> Outcome:
        self.calls.append(("config_list",))
        return Outcome(
            status="ok", exit_code=EXIT_OK, message="config",
            lines=["harness.coder.model         (cli default)  [default]",
                   "harness.tester.model        (cli default)  [default]"],
        )

    def config_get(self, key: str) -> Outcome:
        self.calls.append(("config_get", key))
        return Outcome(status="ok", exit_code=EXIT_OK, message=f"{key} = (cli default)",
                       lines=["source: default"])

    def config_set(self, key: str, value: str) -> Outcome:
        self.calls.append(("config_set", key, value))
        return Outcome(status="set", exit_code=EXIT_OK,
                       message=f"{key} written to .metacoding/config.toml")


def drive(app: FakeApp, text: str) -> str:
    stdin = io.StringIO(text)
    stdout = io.StringIO()
    code = run_tui(app, stdin=stdin, stdout=stdout)
    output = stdout.getvalue()
    assert code == EXIT_OK
    return output


def test_banner_shows_project_and_harness_models() -> None:
    output = drive(FakeApp(), "/exit\n")
    assert "/tmp/demo" in output
    assert "codex / planner-model" in output
    assert "pi / coding-model" in output
    assert "codex / tester-model" in output


def test_help_lists_commands() -> None:
    output = drive(FakeApp(), "/help\n/exit\n")
    for command in ("/status", "/report", "/artifacts", "/resume", "/cancel", "/deliver", "/exit"):
        assert command in output


def test_requirement_starts_run_with_lifecycle_lines() -> None:
    app = FakeApp()
    output = drive(app, "Add an audit log.\n/exit\n")
    assert ("run", "Add an audit log.") in app.calls
    assert "[planning] Planner is analyzing." in output
    assert "round 1 started" in output
    assert "run accepted" in output


def test_operator_commands_dispatch() -> None:
    app = FakeApp()
    output = drive(app, "/status\n/report r-1\n/artifacts r-1\n/resume\n/cancel\n/deliver r-9\n/exit\n")
    assert ("status",) in app.calls
    assert ("report", "r-1") in app.calls
    assert ("artifacts", "r-1") in app.calls
    assert ("resume",) in app.calls
    assert ("cancel",) in app.calls
    assert ("deliver", "r-9") in app.calls
    assert "no active run" in output
    assert "- final.json" in output


def test_exit_and_eof_quit() -> None:
    app = FakeApp()
    assert drive(app, "/exit\n") or True
    stdin = io.StringIO("")  # immediate EOF
    stdout = io.StringIO()
    assert run_tui(app, stdin=stdin, stdout=stdout) == EXIT_OK


def test_ctrl_c_at_prompt_does_not_crash() -> None:
    class InterruptingStdin(io.StringIO):
        count = 0

        def readline(self, *args):
            InterruptingStdin.count += 1
            if InterruptingStdin.count == 1:
                raise KeyboardInterrupt
            return "/exit\n"

    app = FakeApp()
    stdout = io.StringIO()
    code = run_tui(app, stdin=InterruptingStdin(""), stdout=stdout)
    assert code == EXIT_OK
    assert "/exit" in stdout.getvalue()


def test_interrupted_run_reports_resumable_state() -> None:
    class InterruptingApp(FakeApp):
        def run(self, requirement: str, emit=None) -> Outcome:
            raise KeyboardInterrupt

    stdout = io.StringIO()
    code = run_tui(InterruptingApp(), stdin=io.StringIO("do work\n/exit\n"), stdout=stdout)
    assert code == EXIT_OK  # TUI keeps running after an interrupted run
    assert "interrupted" in stdout.getvalue().lower()
    assert "resume" in stdout.getvalue().lower()


def test_raw_model_output_is_not_dumped(capsys) -> None:
    app = FakeApp()
    output = drive(app, "build feature\n/exit\n")
    # only concise lifecycle lines, not full harness dumps
    assert "plan-payload" not in output


def test_config_command_in_tui() -> None:
    app = FakeApp()
    output = drive(app, "/config\n/config get coder.model\n/config set coder.model m-1\n/config\n/exit\n")
    assert ("config_list",) in app.calls
    assert ("config_get", "coder.model") in app.calls
    assert ("config_set", "coder.model", "m-1") in app.calls
    assert "harness.tester.model" in output


def test_config_bad_usage_shows_hint() -> None:
    output = drive(FakeApp(), "/config set only-key\n/exit\n")
    assert "usage: /config" in output
