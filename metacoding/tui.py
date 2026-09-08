"""Interactive terminal interface for MetaCoding.

Renders concise lifecycle updates (phase, round, findings, artifact paths)
and never dumps raw harness output; that lives in ``.metacoding/``.

The interface borrows from established open-source TUI building blocks when
they are available and degrades gracefully to plain stdio when they are not:

- ``rich`` for rendering (banner, colored lifecycle lines, errors),
- ``prompt_toolkit`` for the input loop on real terminals (history with
  arrow keys, slash-command completion, clean Ctrl-C/Ctrl-D handling).
"""

from __future__ import annotations

import os
import sys
from typing import IO, Protocol

from metacoding.cli import App, EXIT_OK, Outcome

#: Slash commands offered by the completer, in help order.
COMMANDS = (
    "/status",
    "/report",
    "/artifacts",
    "/resume",
    "/cancel",
    "/deliver",
    "/config",
    "/help",
    "/exit",
)

HELP = """Commands:
  /status              show the active or most recent run
  /report [run-id]     print the final report
  /artifacts [run-id]  list artifact paths
  /resume              resume the interrupted run
  /cancel              cancel the active run
  /deliver [run-id]    deliver an accepted run
  /config [get KEY|set KEY VALUE]  manage persistent configuration
  /help                show this help
  /exit                leave MetaCoding"""

#: Operator commands accepted with an optional run id argument.
RUN_ID_COMMANDS = ("report", "artifacts", "deliver")

try:  # pragma: no cover - exercised implicitly via rendering
    from rich.console import Console as _RichConsole

    _HAVE_RICH = True
except ImportError:  # pragma: no cover - depends on environment
    _HAVE_RICH = False

try:  # pragma: no cover - exercised implicitly via the input loop
    from prompt_toolkit.completion import WordCompleter as _WordCompleter
    from prompt_toolkit.input import create_input as _create_input
    from prompt_toolkit.output import create_output as _create_output
    from prompt_toolkit.shortcuts import PromptSession as _PromptSession

    _HAVE_PROMPT_TOOLKIT = True
except ImportError:  # pragma: no cover - depends on environment
    _HAVE_PROMPT_TOOLKIT = False


class _Renderer:
    """All terminal output goes through here.

    Uses rich when available; otherwise falls back to plain writes with the
    exact same text so scripted environments behave identically.
    """

    def __init__(self, stdout: IO[str]) -> None:
        self.stdout = stdout
        self.console = None
        if _HAVE_RICH:
            try:
                # markup/highlight off: lifecycle text must stay literal;
                # colors follow rich's own tty/TERM/NO_COLOR detection so
                # piped output stays plain while terminals get styled text.
                self.console = _RichConsole(file=stdout, markup=False, highlight=False)
            except Exception:  # pragma: no cover - defensive
                self.console = None

    def text(self, text: str, *, style: str | None = None) -> None:
        if self.console is not None:
            self.console.print(text, style=style or "")
        else:
            self.stdout.write(text + "\n")
        self.stdout.flush()

    def banner(self, overview: list[str]) -> None:
        if self.console is not None:
            self.console.rule("MetaCoding", style="bold")
            for line in overview:
                self.console.print(line, style="bold")
            self.console.print(
                "Type a requirement to start a run, or /help for commands.",
                style="dim",
            )
            self.console.rule(style="dim")
        else:
            self.stdout.write("MetaCoding\n" + "\n".join(overview) + "\n")
            self.stdout.write(
                "Type a requirement to start a run, or /help for commands.\n\n"
            )
        self.stdout.flush()

    def phase(self, phase_name: str, message: str) -> None:
        self.text(f"[{phase_name}] {message}", style="bold cyan")

    def error(self, message: str) -> None:
        self.text(message, style="bold red")

    def outcome(self, outcome: Outcome) -> None:
        style = None if outcome.exit_code == 0 else "bold red"
        if outcome.message:
            self.text(outcome.message, style=style)
        for line in outcome.lines:
            self.text(line)


class TuiApp(Protocol):  # structural superset of cli.App
    def overview(self) -> list[str]: ...


def _print_outcome(renderer: _Renderer, outcome: Outcome) -> None:
    renderer.outcome(outcome)


def _safe_call(renderer: _Renderer, label: str, call):
    """Run an operator command; never let an exception kill the TUI."""
    try:
        return call()
    except KeyboardInterrupt:
        renderer.error(f"{label} interrupted")
    except Exception as exc:  # noqa: BLE001 - the loop must survive
        renderer.error(f"{label} failed: {exc.__class__.__name__}: {exc}")
    return None


class _InputLoop:
    """Input line reading: prompt_toolkit on a tty, plain readline otherwise."""

    def __init__(self, stdout: IO[str], stdin: IO[str]) -> None:
        self.stdout = stdout
        self.stdin = stdin
        self.session = None
        if _HAVE_PROMPT_TOOLKIT and os.environ.get("METACODING_TUI_PLAIN") != "1":
            if _is_tty(stdin) and _is_tty(stdout):
                try:
                    self.session = self._build_session(stdin, stdout)
                except Exception:  # pragma: no cover - terminal lacks support
                    self.session = None

    @staticmethod
    def _build_session(stdin: IO[str], stdout: IO[str]):
        """Create a PromptSession bound to the injected streams.

        prompt_toolkit defaults to the process-level sys.stdin/sys.stdout;
        passing explicit input/output keeps run_tui(stdin=..., stdout=...)
        authoritative for tests, embedding, and redirection.
        """
        input_impl = _create_input(stdin=stdin)
        output_impl = _create_output(stdout=stdout)
        completer = _WordCompleter(list(COMMANDS), sentence=True)
        return _PromptSession(
            "metacoding > ", completer=completer, input=input_impl, output=output_impl
        )

    def read(self) -> str | None:
        """Return the next input line, or None on EOF."""
        if self.session is not None:
            try:
                return self.session.prompt()
            except KeyboardInterrupt:
                # Ctrl-C on an empty prompt line: show a hint, keep going.
                self._after_interrupt()
                return ""
            except EOFError:
                return None
            except Exception:
                # Unsupported terminal or lost tty: degrade permanently to
                # plain readline instead of dying.
                self.session = None
        return self._read_plain()

    def _read_plain(self) -> str | None:
        self.stdout.write("metacoding > ")
        self.stdout.flush()
        try:
            line = self.stdin.readline()
        except KeyboardInterrupt:
            self.stdout.write("\n(interrupted; use /exit to quit)\n")
            self.stdout.flush()
            return ""
        if line == "":
            # readline() returning an empty string means EOF (Ctrl-D).
            return None
        return line

    def _after_interrupt(self) -> None:
        try:
            self.stdout.write("\n(interrupted; use /exit to quit)\n")
            self.stdout.flush()
        except Exception:  # pragma: no cover
            pass


def run_tui(app: App, *, stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    renderer = _Renderer(stdout)
    input_loop = _InputLoop(stdout, stdin)

    overview = _safe_call(renderer, "overview", lambda: app.overview()) if hasattr(
        app, "overview"
    ) else None
    renderer.banner(overview or [f"Project  {_cwd_label()}"])

    def emit(event: dict) -> None:
        kind = event.get("kind")
        if kind == "phase":
            renderer.phase(str(event.get("phase", "")), str(event.get("message", "")))
        elif kind == "info":
            renderer.text(str(event.get("message", "")))

    while True:
        line = input_loop.read()
        if line is None:
            return EXIT_OK
        command = line.strip()
        if not command:
            continue
        name = command.split()[0][1:].lower() if command.startswith("/") else ""
        if not command.startswith("/"):
            # A natural-language requirement starts or continues a run.
            try:
                outcome = app.run(command, emit=emit)
            except KeyboardInterrupt:
                renderer.error(
                    "run interrupted; state is preserved — /resume continues the run."
                )
                continue
            except Exception as exc:  # noqa: BLE001 - the loop must survive
                renderer.error(f"run failed: {exc.__class__.__name__}: {exc}")
                continue
            _print_outcome(renderer, outcome)
            continue
        if name in ("exit", "quit"):
            return EXIT_OK
        if name == "help":
            renderer.text(HELP)
            continue
        if name == "status":
            outcome = _safe_call(renderer, "/status", app.status)
        elif name == "resume":
            outcome = _safe_call(renderer, "/resume", lambda: app.resume(emit=emit))
        elif name == "cancel":
            outcome = _safe_call(renderer, "/cancel", app.cancel)
        elif name == "config":
            outcome = _handle_config(renderer, app, command)
        elif name in RUN_ID_COMMANDS:
            method = getattr(app, name)
            parts = command.split(maxsplit=1)
            run_id = parts[1].strip() if len(parts) > 1 else None
            outcome = _safe_call(
                renderer, f"/{name}", lambda method=method, run_id=run_id: method(run_id)
            )
        else:
            renderer.error(f"unknown command {command.split()[0]}; /help lists commands")
            continue
        if outcome is not None:
            _print_outcome(renderer, outcome)


def _handle_config(renderer: _Renderer, app: App, command: str) -> Outcome | None:
    # /config            -> list
    # /config get KEY    -> show one key
    # /config set K V    -> persist to .metacoding/config.toml
    rest = command.split()[1:]
    if not rest:
        return _safe_call(renderer, "/config", app.config_list)
    action = rest[0].lower()
    if action == "get" and len(rest) == 2:
        return _safe_call(renderer, "/config get", lambda: app.config_get(rest[1]))
    if action == "set" and len(rest) >= 3:
        return _safe_call(
            renderer, "/config set", lambda: app.config_set(rest[1], " ".join(rest[2:]))
        )
    if action == "set" and len(rest) == 2 and rest[1].strip().lower().endswith(".model"):
        harness = rest[1].strip().split(".")[0]
        if harness in ("planner", "coder", "tester"):
            return _safe_call(
                renderer, f"/config set {harness}.model", lambda: app.pick_model(harness)
            )
    renderer.error("usage: /config [get KEY | set KEY VALUE]")
    return None


def _is_tty(stream) -> bool:
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def _cwd_label() -> str:
    try:
        return str(__import__("pathlib").Path.cwd())
    except Exception:  # pragma: no cover
        return "(unknown project)"
