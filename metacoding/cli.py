"""Command-line parsing and dispatch for MetaCoding.

The CLI layer only parses arguments, resolves the project root, and
dispatches to an application service. Orchestration logic lives elsewhere.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from metacoding import __version__
from metacoding.errors import MetaCodingError


def default_emitter():
    """Live lifecycle lines for non-interactive commands."""
    from metacoding.service import default_emitter as emitter

    return emitter()

EXIT_OK = 0
#: blocked, human review required, or cancelled run.
EXIT_RUN_REJECTED = 1
#: harness infrastructure failure (missing command, timeout, malformed output).
EXIT_INFRASTRUCTURE = 2
#: usage, configuration, or lock errors.
EXIT_USAGE = 3
#: interrupted by the operator (Ctrl-C).
EXIT_INTERRUPTED = 130

EXIT_CODE_NAMES = {
    EXIT_OK: "accepted",
    EXIT_RUN_REJECTED: "run-rejected",
    EXIT_INFRASTRUCTURE: "infrastructure-failure",
    EXIT_USAGE: "usage-or-configuration-error",
    EXIT_INTERRUPTED: "interrupted",
}


@dataclass
class Outcome:
    """Uniform result of an application command."""

    status: str
    exit_code: int
    message: str = ""
    lines: list[str] = field(default_factory=list)
    run_id: str | None = None


class App(Protocol):
    """Application surface invoked by the CLI and TUI."""

    def run(self, requirement: str) -> Outcome: ...

    def status(self) -> Outcome: ...

    def resume(self) -> Outcome: ...

    def report(self, run_id: str | None = None) -> Outcome: ...

    def artifacts(self, run_id: str | None = None) -> Outcome: ...

    def cancel(self) -> Outcome: ...

    def deliver(self, run_id: str | None = None) -> Outcome: ...


def _add_harness_overrides(parser: argparse.ArgumentParser, *, suppress: bool) -> None:
    """Add per-harness model/command overrides.

    ``suppress`` keeps subparser-level copies from clobbering values that
    were provided before the subcommand.
    """

    def option(*flags: str, **kwargs) -> None:
        if suppress:
            kwargs["default"] = argparse.SUPPRESS
        parser.add_argument(*flags, **kwargs)

    option("--planner-model", metavar="MODEL", help="override planner model for this invocation")
    option("--coder-model", metavar="MODEL", help="override coder model for this invocation")
    option("--tester-model", metavar="MODEL", help="override tester model for this invocation")
    option("--planner-command", metavar="PATH", help="override planner command path")
    option("--coder-command", metavar="PATH", help="override coder command path")
    option("--tester-command", metavar="PATH", help="override tester command path")
    option("--max-rounds", type=int, metavar="N", help="override the maximum number of rounds")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="metacoding",
        description=(
            "Project-local AI development orchestration with a Planner, Coder, "
            "and Tester harness sharing the current project directory."
        ),
    )
    parser.add_argument("--version", action="version", version=f"metacoding {__version__}")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="project root directory (default: current working directory)",
    )
    _add_harness_overrides(parser, suppress=False)

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    run_parser = subparsers.add_parser("run", help="run one requirement non-interactively")
    run_parser.add_argument("requirement", metavar="REQUIREMENT")
    _add_harness_overrides(run_parser, suppress=True)

    def add_simple(name: str, help_text: str, run_id: bool = False) -> None:
        sub = subparsers.add_parser(name, help=help_text)
        if run_id:
            sub.add_argument("--run-id", metavar="ID", default=None)
        _add_harness_overrides(sub, suppress=True)

    add_simple("status", "show the active or most recent run status")
    add_simple("resume", "resume an interrupted run")
    add_simple("report", "print the final report of a run", run_id=True)
    add_simple("artifacts", "list artifact paths of a run", run_id=True)
    add_simple("cancel", "cancel the active run")
    add_simple("deliver", "deliver an accepted run to git/GitHub", run_id=True)

    config_parser = subparsers.add_parser(
        "config", help="manage persistent project configuration (.metacoding/config.toml)"
    )
    config_parser.add_argument(
        "action", choices=["list", "get", "set"], help="list / get KEY / set KEY VALUE"
    )
    config_parser.add_argument("key", nargs="?", help="dotted key, e.g. coder.model")
    config_parser.add_argument("value", nargs="?", help="value for `set`")
    _add_harness_overrides(config_parser, suppress=True)

    models_parser = subparsers.add_parser(
        "models", help="list the models a harness CLI can use"
    )
    models_parser.add_argument(
        "harness", choices=["planner", "coder", "tester"],
        help="which harness to list models for",
    )
    _add_harness_overrides(models_parser, suppress=True)
    return parser


def launch_tui(app: App) -> int:
    """Start the interactive terminal interface."""
    from metacoding.tui import run_tui

    return run_tui(app)


def _print_outcome(outcome: Outcome) -> None:
    if outcome.message:
        print(outcome.message)
    for line in outcome.lines:
        print(line)


def dispatch(app: App, args: argparse.Namespace) -> int:
    if args.command is None:
        return launch_tui(app)
    if args.command == "run":
        outcome = app.run(args.requirement, emit=default_emitter())
    elif args.command == "status":
        outcome = app.status()
    elif args.command == "resume":
        outcome = app.resume(emit=default_emitter())
    elif args.command == "report":
        outcome = app.report(getattr(args, "run_id", None))
    elif args.command == "artifacts":
        outcome = app.artifacts(getattr(args, "run_id", None))
    elif args.command == "cancel":
        outcome = app.cancel()
    elif args.command == "deliver":
        outcome = app.deliver(getattr(args, "run_id", None))
    elif args.command == "config":
        if args.action == "list":
            outcome = app.config_list()
        elif args.action == "get":
            if not args.key:
                print("usage: metacoding config get KEY", file=sys.stderr)
                return EXIT_USAGE
            outcome = app.config_get(args.key)
        else:  # set
            if not args.key:
                print("usage: metacoding config set KEY VALUE", file=sys.stderr)
                return EXIT_USAGE
            if args.value is None and args.key.strip().lower().endswith(".model"):
                # Interactive model picker: no typing of model names needed.
                harness = args.key.strip().split(".")[0]
                if harness in ("planner", "coder", "tester"):
                    outcome = app.pick_model(harness)
                    _print_outcome(outcome)
                    return outcome.exit_code
                print("usage: metacoding config set KEY VALUE", file=sys.stderr)
                return EXIT_USAGE
            if args.value is None:
                print("usage: metacoding config set KEY VALUE", file=sys.stderr)
                return EXIT_USAGE
            outcome = app.config_set(args.key, args.value)
    elif args.command == "models":
        outcome = app.models_outcome(args.harness)
    else:  # pragma: no cover - argparse rejects unknown commands first
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return EXIT_USAGE
    _print_outcome(outcome)
    return outcome.exit_code


def load_app(args: argparse.Namespace) -> App:
    """Construct the real application service for the resolved project root."""
    from metacoding.config import CliOverrides
    from metacoding.service import MetaCodingService

    overrides = CliOverrides.from_args(args)
    project_root = Path(args.project_root) if args.project_root else Path.cwd()
    return MetaCodingService(project_root=project_root, overrides=overrides)


def main(argv: list[str] | None = None, app: App | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if app is None:
        app = load_app(args)
    try:
        return dispatch(app, args)
    except KeyboardInterrupt:
        print("\nInterrupted. The run can be resumed with `metacoding resume`.", file=sys.stderr)
        return EXIT_INTERRUPTED
    except MetaCodingError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    except Exception as exc:  # noqa: BLE001 - CLI must fail readably
        print(
            f"unexpected error: {exc.__class__.__name__}: {exc} "
            f"(details: .metacoding/runs/*/ and .metacoding/transcripts/)",
            file=sys.stderr,
        )
        return EXIT_USAGE
