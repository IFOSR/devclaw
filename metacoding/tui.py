"""Interactive terminal interface for MetaCoding.

Renders concise lifecycle updates (phase, round, finding counts, final
artifact paths) and never dumps raw harness output; that lives in
``.metacoding/`` transcripts.
"""

from __future__ import annotations

import sys
from typing import IO, Protocol

from metacoding.cli import App, EXIT_OK, Outcome

BANNER = """MetaCoding
{overview}
Type a requirement to start a run, or /help for commands."""

HELP = """Commands:
  /status              show the active or most recent run
  /report [run-id]     print the final report
  /artifacts [run-id]  list artifact paths
  /resume              resume the interrupted run
  /cancel              cancel the active run
  /deliver [run-id]    deliver an accepted run
  /help                show this help
  /exit                leave MetaCoding"""

#: Operator commands accepted with an optional run id argument.
RUN_ID_COMMANDS = ("report", "artifacts", "deliver")


class TuiApp(Protocol):  # structural superset of cli.App
    def overview(self) -> list[str]: ...


def _print(file: IO[str], text: str) -> None:
    file.write(text + "\n")
    file.flush()


def _emit_line(file: IO[str], event: dict) -> None:
    kind = event.get("kind")
    if kind == "phase":
        _print(file, f"[{event.get('phase')}] {event.get('message', '')}")
    elif kind == "info":
        _print(file, str(event.get("message", "")))
    else:  # pragma: no cover - unknown events stay silent
        pass


def _print_outcome(file: IO[str], outcome: Outcome) -> None:
    if outcome.message:
        _print(file, outcome.message)
    for line in outcome.lines:
        _print(file, line)


def run_tui(app: App, *, stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    overview = app.overview() if hasattr(app, "overview") else []
    _print(stdout, BANNER.format(overview="\n".join(overview)))
    if overview:
        _print(stdout, "")

    def emit(event: dict) -> None:
        _emit_line(stdout, event)

    while True:
        try:
            stdout.write("metacoding > ")
            stdout.flush()
            line = stdin.readline()
        except KeyboardInterrupt:
            _print(stdout, "\n(interrupted; use /exit to quit)")
            continue
        if line == "":
            # readline() returning an empty string means EOF (Ctrl-D).
            return EXIT_OK
        command = line.strip()
        if not command:
            continue
        if command in ("/exit", "/quit"):
            return EXIT_OK
        if command == "/help":
            _print(stdout, HELP)
            continue
        if command.startswith("/"):
            parts = command.split(maxsplit=1)
            name = parts[0][1:]
            run_id = parts[1].strip() if len(parts) > 1 else None
            if name == "status":
                _print_outcome(stdout, app.status())
            elif name == "resume":
                _print_outcome(stdout, app.resume(emit=emit))
            elif name == "cancel":
                _print_outcome(stdout, app.cancel())
            elif name in RUN_ID_COMMANDS:
                method = getattr(app, name)
                _print_outcome(stdout, method(run_id))
            else:
                _print(stdout, f"unknown command {command}; /help lists commands")
            continue

        # A natural-language requirement starts or continues a run.
        try:
            outcome = app.run(command, emit=emit)
        except KeyboardInterrupt:
            _print(
                stdout,
                "run interrupted; state is preserved — /resume continues the run.",
            )
            continue
        except Exception as exc:  # keep the TUI alive on unexpected errors
            _print(stdout, f"run failed: {exc}")
            continue
        _print_outcome(stdout, outcome)
