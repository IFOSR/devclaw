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


# --- bug regressions: robustness, case-insensitivity, trailing args -----------------


class ExplodingApp(FakeApp):
    """Every operator command raises; the TUI must survive all of them."""

    def status(self):
        raise RuntimeError("corrupt state boom")

    def report(self, run_id=None):
        raise KeyError("corrupt final.json")

    def artifacts(self, run_id=None):
        raise ValueError("corrupt artifacts")

    def resume(self, emit=None):
        raise OSError("resume exploded")

    def cancel(self):
        raise ZeroDivisionError("cancel exploded")

    def config_list(self):
        raise RuntimeError("config exploded")


def test_operator_command_exceptions_do_not_kill_the_tui() -> None:
    app = ExplodingApp()
    output = drive(
        app,
        "/status\n/report\n/artifacts\n/resume\n/cancel\n/config\n/help\n/exit\n",
    )
    for fragment in (
        "/status failed: RuntimeError: corrupt state boom",
        "/report failed: KeyError",
        "/artifacts failed: ValueError",
        "/resume failed: OSError",
        "/cancel failed: ZeroDivisionError",
        "/config failed: RuntimeError",
    ):
        assert fragment in output
    # the loop kept working afterwards
    assert "Commands:" in output


def test_command_names_are_case_insensitive() -> None:
    app = FakeApp()
    output = drive(app, "/STATUS\n/Help\n/EXIT\n")
    assert ("status",) in app.calls
    assert "Commands:" in output


def test_exit_with_trailing_arguments_still_exits() -> None:
    app = FakeApp()
    stdout = io.StringIO()
    code = run_tui(app, stdin=io.StringIO("/exit now please\n"), stdout=stdout)
    assert code == EXIT_OK
    assert "unknown command" not in stdout.getvalue()
    # /quit alias also ignores trailing text
    code = run_tui(app, stdin=io.StringIO("/QUIT\n/status\n/exit\n"), stdout=io.StringIO())
    assert code == EXIT_OK


def test_persistence_errors_surface_as_readable_outcomes() -> None:
    from metacoding.cli import EXIT_USAGE
    from metacoding.errors import PersistenceError
    from metacoding.service import MetaCodingService

    class ExplodingStore:
        def read_state(self):
            raise PersistenceError("cannot read JSON artifact state.json: bad")

    service = MetaCodingService(project_root=Path("/tmp/never-used"))
    service.store = ExplodingStore()
    outcome = service.status()
    assert outcome.exit_code == EXIT_USAGE
    assert "state.json" in outcome.message

    class NoFinalStore(ExplodingStore):
        def latest_run_id(self):
            return "r-1"

        def load_final(self, run_id):
            raise PersistenceError("cannot read final.json: bad")

        def read_state(self):
            return None

    service.store = NoFinalStore()
    assert "final.json" in service.report().message


def test_cli_main_converts_exceptions_to_concise_errors() -> None:
    from metacoding.cli import EXIT_USAGE

    class BrokenApp(FakeApp):
        def status(self):
            raise RuntimeError("kaboom")

    stdout_err = io.StringIO()
    import contextlib

    with contextlib.redirect_stderr(stdout_err):
        code = run_cli_main_with(BrokenApp())
    assert code == EXIT_USAGE
    assert "RuntimeError: kaboom" in stdout_err.getvalue()
    assert "Traceback" not in stdout_err.getvalue()


def run_cli_main_with(app):
    from metacoding import cli

    return cli.main(["status"], app=app)


def test_plain_rendering_fallback_without_rich() -> None:
    import metacoding.tui as tui_module

    app = FakeApp()
    stdout = io.StringIO()
    had_rich, tui_module._HAVE_RICH = tui_module._HAVE_RICH, False
    try:
        renderer = tui_module._Renderer(stdout)
        renderer.banner(["Project  /tmp/demo"])
        renderer.phase("planning", "Planner is analyzing.")
        renderer.error("boom")
    finally:
        tui_module._HAVE_RICH = had_rich
    output = stdout.getvalue()
    assert "MetaCoding" in output and "Project  /tmp/demo" in output
    assert "[planning] Planner is analyzing." in output
    assert "boom" in output
    assert "─" not in output  # no rich rule borders in plain mode
