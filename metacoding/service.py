"""Application service layer used by the CLI and TUI.

Wires configuration, harnesses, the orchestrator, and delivery behind the
small command surface the CLI dispatches to. Every command returns an
:class:`metacoding.cli.Outcome` with an operator-readable message and a
process exit code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from metacoding.cli import (
    EXIT_INFRASTRUCTURE,
    EXIT_OK,
    EXIT_RUN_REJECTED,
    EXIT_USAGE,
    Outcome,
)
from metacoding.config import CliOverrides, load_config
from metacoding.errors import MetaCodingError, PersistenceError
from metacoding.harnesses import create_harness
from metacoding.locking import read_lock
from metacoding.models import RunStatus
from metacoding.orchestrator import EXIT_BY_STATUS, Orchestrator, OrchestratorResult
from metacoding.persistence import RunStore

EVENT = Callable[[dict], None]


def default_emitter() -> EVENT:
    """Print concise lifecycle lines for non-interactive commands."""

    def emit(event: dict) -> None:
        if event.get("kind") == "phase":
            print(f"[{event.get('phase')}] {event.get('message', '')}")
        elif event.get("kind") == "info":
            print(event.get("message", ""))

    return emit


class MetaCodingService:
    """Application entry points for start, run, resume, and reporting."""

    def __init__(
        self,
        project_root: Path | None = None,
        overrides: CliOverrides | None = None,
    ) -> None:
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.overrides = overrides
        self.store = RunStore(self.project_root)

    # --- collaborators -----------------------------------------------------------

    def _config(self):
        return load_config(self.project_root, self.overrides)

    def _orchestrator(self, config, emit: EVENT | None = None) -> Orchestrator:
        harnesses = {
            name: create_harness(name, harness_config, self.project_root)
            for name, harness_config in config.harness.items()
        }
        deliverer = None
        if config.github.enabled:
            from metacoding.github import GitDeliverer

            deliverer = GitDeliverer(self.project_root, config)
        return Orchestrator(
            self.project_root,
            config,
            harnesses,
            emit=emit,
            deliverer=deliverer,
            store=self.store,
        )

    # --- run lifecycle -------------------------------------------------------------

    def run(self, requirement: str, emit: EVENT | None = None) -> Outcome:
        try:
            config = self._config()
            orchestrator = self._orchestrator(
                config, emit=emit if emit is not None else default_emitter()
            )
            result = orchestrator.start(requirement)
        except MetaCodingError as exc:
            return Outcome("error", EXIT_USAGE, str(exc))
        return self._outcome(result)

    def resume(self, emit: EVENT | None = None) -> Outcome:
        try:
            from metacoding.persistence import resolve_resume

            plan = resolve_resume(self.store)
            if plan.action == "nothing_to_resume":
                raise MetaCodingError("no active run to resume")
            if plan.action == "cannot_resume_terminal":
                raise MetaCodingError(
                    f"run {plan.run_id} already finished and cannot be resumed"
                )
            record = self.store.load_run(plan.run_id)
            config = self._resume_config(record)
            orchestrator = self._orchestrator(
                config, emit=emit if emit is not None else default_emitter()
            )
            result = orchestrator.resume()
        except MetaCodingError as exc:
            return Outcome("error", EXIT_USAGE, str(exc))
        return self._outcome(result)

    def _resume_config(self, record):
        """Resume with the run's persisted configuration snapshot.

        Models, commands, and policy must not silently change mid-run when
        the project config file is edited; explicit CLI overrides still win.
        A corrupt or tampered snapshot blocks the resume instead of falling
        back to the current config file.
        """
        from metacoding.config import ProjectConfig, apply_cli_overrides

        config = ProjectConfig.from_dict(record.config_snapshot)
        return apply_cli_overrides(config, self.overrides)

    def cancel(self) -> Outcome:
        try:
            config = self._config()
            orchestrator = Orchestrator(
                self.project_root, config, {}, store=self.store
            )
            result = orchestrator.cancel()
        except MetaCodingError as exc:
            return Outcome("error", EXIT_USAGE, str(exc))
        return self._outcome(result)

    def deliver(self, run_id: str | None = None) -> Outcome:
        target = run_id or self.store.latest_run_id()
        if target is None:
            return Outcome("error", EXIT_USAGE, "no runs found; nothing to deliver")
        final = self.store.load_final(target)
        if final is None:
            record = self.store.load_run(target)
            return Outcome(
                "error",
                EXIT_USAGE,
                f"run {target} has not finished (status: {record.status.value}); "
                "only accepted runs can be delivered",
            )
        if final.outcome not in ("delivered", "accepted"):
            return Outcome(
                "error",
                EXIT_RUN_REJECTED,
                f"run {target} ended as {final.outcome}; nothing to deliver",
            )
        try:
            from metacoding.config import ProjectConfig, apply_cli_overrides
            from metacoding.github import GitDeliverer
            from metacoding.orchestrator import compute_owned_delivery_files

            record = self.store.load_run(target)
            plan = self.store.load_plan(target)
            if plan is None:
                raise MetaCodingError(f"run {target} has no planner plan to derive scope from")
            # Manual delivery follows the SAME owned-diff rules as the
            # automatic path: baseline content diff, mixed-file exclusion,
            # planner scope, and host-protected paths.
            config = apply_cli_overrides(
                ProjectConfig.from_dict(record.config_snapshot), self.overrides
            )
            deliverer = GitDeliverer(self.project_root, config)
            owned, warnings = compute_owned_delivery_files(
                self.project_root, self.store, record, plan
            )
            if not owned:
                return Outcome(
                    "delivered",
                    EXIT_OK,
                    f"nothing deliverable for run {target}",
                    list(warnings) or ["no deliverable owned files"],
                    run_id=target,
                )
            summary = deliverer.deliver(target, owned_files=owned)
            summary.setdefault("warnings", []).extend(warnings)
            self.store.save_git_artifact(target, "delivery", summary)
        except MetaCodingError as exc:
            return Outcome("error", EXIT_USAGE, f"delivery failed: {exc}", run_id=target)
        lines = [f"- {key}: {value}" for key, value in summary.items()]
        return Outcome("delivered", EXIT_OK, f"delivered run {target}", lines, run_id=target)

    # --- persistent configuration management ----------------------------------

    def config_set(self, key: str, value: str) -> Outcome:
        from metacoding.config import resolve_config_key, set_config_value

        try:
            section, leaf = resolve_config_key(key)
            set_config_value(self.project_root, key, value)
        except MetaCodingError as exc:
            return Outcome("error", EXIT_USAGE, str(exc))
        lines: list[str] = []
        if leaf == "model" and section.startswith("harness."):
            lines.extend(self._model_catalog_warnings(section, value))
        return Outcome(
            "set", EXIT_OK, f"{key} written to .metacoding/config.toml", lines
        )

    def _model_catalog_warnings(self, harness_section: str, model: str) -> list[str]:
        """Best-effort hint when a model is not in the CLI's catalog."""
        if not model:
            return []
        from metacoding.catalog import list_models

        name = harness_section.split(".", 1)[1]
        try:
            config = self._config()
            harness_config = config.harness.get(name)
        except MetaCodingError:
            return []
        if harness_config is None:
            return []
        entries = list_models(harness_config, current_model=model)
        if not entries:
            return []  # catalog unavailable — never block or scare the user
        if not any(entry.current for entry in entries):
            return [
                f"note: '{model}' is not in the {harness_config.command} model "
                f"list; if the harness fails, run `metacoding models {name}` "
                f"and pick a listed model"
            ]
        return []

    def models_outcome(self, harness: str) -> Outcome:
        """List the models one harness can use, marking the current one."""
        from metacoding.catalog import list_models

        harness = harness.strip().lower()
        try:
            config = self._config()
            if harness not in config.harness:
                raise MetaCodingError(
                    f"unknown harness {harness!r}; expected planner, coder, or tester"
                )
            harness_config = config.harness[harness]
        except MetaCodingError as exc:
            return Outcome("error", EXIT_USAGE, str(exc))
        current = harness_config.model
        entries = list_models(harness_config, current_model=current)
        if not entries:
            return Outcome(
                "empty",
                EXIT_OK,
                f"no model list available for {harness_config.command!r}; "
                f"current model: {current or '(cli default)'}",
            )
        width = max(len(f"{e.provider}/{e.model}" if e.provider != "codex" else e.model) for e in entries)
        lines = [
            f"{index:>3}. "
            + (entry.model if entry.provider == "codex" else entry.model).ljust(width)
            + (f"  ctx {entry.context}" if entry.context else "")
            + ("  ← current" if entry.current else "")
            for index, entry in enumerate(entries, start=1)
        ]
        lines.append("")
        lines.append(
            f"select with: metacoding config set {harness}.model <name> "
            f"(or run `metacoding config set {harness}.model` to pick interactively)"
        )
        return Outcome(
            "models", EXIT_OK, f"models available to {harness} ({harness_config.command}):", lines
        )

    def pick_model(
        self,
        harness: str,
        *,
        stdin=None,
        stdout=None,
    ) -> Outcome:
        """Interactively choose a model for a harness and persist it.

        Numbered selection; Enter keeps the current model, 0 clears it back
        to the CLI default. Only usable with an interactive stdin.
        """
        import sys

        stdin = stdin if stdin is not None else sys.stdin
        stdout = stdout if stdout is not None else sys.stdout
        harness = harness.strip().lower()
        listing = self.models_outcome(harness)
        if listing.exit_code != EXIT_OK:
            return listing
        try:
            interactive = stdin.isatty()
        except Exception:
            interactive = False
        if not interactive:
            stdout.write(listing.message + "\n")
            for line in listing.lines:
                stdout.write(line + "\n")
            stdout.write(
                "non-interactive input: provide a value, e.g. "
                f"`metacoding config set {harness}.model <name>`\n"
            )
            stdout.flush()
            return Outcome(
                "error", EXIT_USAGE, "no value provided and stdin is not interactive"
            )

        def out(text: str) -> None:
            stdout.write(text + "\n")
            stdout.flush()

        out(listing.message)
        for line in listing.lines:
            out(line)
        try:
            config = self._config()
            current = config.harness[harness].model or "(cli default)"
        except MetaCodingError as exc:
            return Outcome("error", EXIT_USAGE, str(exc))
        from metacoding.catalog import list_models

        entries = list_models(config.harness[harness], current_model=current)
        for _ in range(3):
            out("")
            stdout.write(
                f"select model for {harness} "
                f"[number | Enter=keep ({current}) | 0=cli default]: "
            )
            stdout.flush()
            line = stdin.readline()
            if line == "":
                return Outcome("cancelled", EXIT_USAGE, "selection cancelled")
            answer = line.strip()
            if not answer:
                return Outcome("kept", EXIT_OK, f"kept current model for {harness}")
            if answer == "0":
                from metacoding.config import set_config_value

                set_config_value(self.project_root, f"{harness}.model", '""')
                return Outcome(
                    "cleared", EXIT_OK, f"{harness}.model cleared; the CLI default is used"
                )
            if answer.isdigit() and 1 <= int(answer) <= len(entries):
                chosen = entries[int(answer) - 1].model
                return self.config_set(f"{harness}.model", chosen)
            out(
                f"invalid choice {answer!r}; enter a number between 1 and {len(entries)}"
            )
        return Outcome("error", EXIT_USAGE, "too many invalid selections; cancelled")

    def _settings(self) -> dict:
        from metacoding.config import effective_config_settings, read_raw_config

        return effective_config_settings(self._config(), read_raw_config(self.project_root))

    def config_get(self, key: str) -> Outcome:
        from metacoding.config import format_config_value, resolve_config_key

        try:
            section, leaf = resolve_config_key(key)
        except MetaCodingError as exc:
            return Outcome("error", EXIT_USAGE, str(exc))
        dotted = f"{section}.{leaf}"
        entry = self._settings().get(dotted)
        if entry is None:
            return Outcome("error", EXIT_USAGE, f"unknown config key {key!r}")
        value, source = entry
        return Outcome(
            "get",
            EXIT_OK,
            f"{key.strip()} = {format_config_value(value)}",
            [f"source: {source}"],
        )

    def config_list(self) -> Outcome:
        from metacoding.config import format_config_value

        settings = self._settings()
        width = max(len(key) for key in settings)
        lines = [
            f"{key.ljust(width)}  {format_config_value(value)}  [{source}]"
            for key, (value, source) in sorted(settings.items())
        ]
        return Outcome("list", EXIT_OK, "effective project configuration", lines)

    # --- inspection ------------------------------------------------------------------

    def overview(self) -> list[str]:
        try:
            config = self._config()
            lines = [f"Project  {self.project_root}"]
            for name, title in (("planner", "Planner"), ("coder", "Coder"), ("tester", "Tester")):
                harness = config.harness[name]
                model = harness.model or "(cli default)"
                lines.append(f"{title:<8} {harness.provider} / {model}")
            lock = read_lock(self.project_root)
            if lock is not None:
                lines.append(f"Active   run {lock.run_id} (pid {lock.pid})")
            return lines
        except MetaCodingError as exc:
            return [f"Project  {self.project_root}", f"Config   {exc}"]

    def status(self) -> Outcome:
        try:
            state = self.store.read_state()
        except PersistenceError as exc:
            return Outcome("error", EXIT_USAGE, str(exc))
        if state and state.get("active_run_id"):
            run_id = str(state["active_run_id"])
            try:
                record = self.store.load_run(run_id)
                lock = read_lock(self.project_root)
            except PersistenceError as exc:
                return Outcome("error", EXIT_USAGE, str(exc))
            lines = [
                f"run id:    {run_id}",
                f"status:    {record.status.value}",
                f"round:     {record.current_round}",
                f"requirement: {record.requirement}",
            ]
            if lock is not None:
                lines.append(f"owner:     pid {lock.pid} on {lock.host}")
            return Outcome("active", EXIT_OK, "an unfinished run is active", lines)

        latest = self.store.latest_run_id()
        if latest is None:
            return Outcome(
                "idle",
                EXIT_OK,
                "no runs recorded for this project",
                [
                    "start with: metacoding run \"<requirement>\"",
                    "harnesses are configured in .metacoding/config.toml "
                    "(see docs/metacoding/config.example.toml)",
                ],
            )
        try:
            final = self.store.load_final(latest)
            if final is not None:
                return Outcome(
                    "finished",
                    EXIT_OK,
                    f"last run {latest} finished as {final.outcome}",
                    [f"reason: {final.reason}", f"rounds: {final.rounds_used}"],
                )
            record = self.store.load_run(latest)
        except PersistenceError as exc:
            return Outcome(
                "error",
                EXIT_USAGE,
                f"last run {latest} has unreadable records: {exc}",
            )
        return Outcome(
            "finished",
            EXIT_OK,
            f"last run {latest} has status {record.status.value}",
        )

    def report(self, run_id: str | None = None) -> Outcome:
        target = run_id or self.store.latest_run_id()
        if target is None:
            return Outcome("error", EXIT_USAGE, "no runs found")
        try:
            final = self.store.load_final(target)
            if final is None:
                record = self.store.load_run(target)
                return Outcome(
                    "unfinished",
                    EXIT_OK,
                    f"run {target} has not finished (status: {record.status.value})",
                    [f"requirement: {record.requirement}"],
                )
        except PersistenceError as exc:
            return Outcome("error", EXIT_USAGE, str(exc))
        lines = [
            f"outcome: {final.outcome}",
            f"reason:  {final.reason}",
            f"summary: {final.summary}",
            f"rounds:  {final.rounds_used}",
        ]
        if final.warnings:
            lines.append("warnings:")
            lines.extend(f"  - {warning}" for warning in final.warnings)
        if final.github:
            lines.append("github:")
            lines.extend(f"  - {key}: {value}" for key, value in final.github.items())
        lines.append("artifacts:")
        lines.extend(f"  - {name}: {path}" for name, path in final.artifacts.items())
        return Outcome("report", EXIT_OK, f"final report for run {target}", lines)

    def artifacts(self, run_id: str | None = None) -> Outcome:
        target = run_id or self.store.latest_run_id()
        if target is None:
            return Outcome("error", EXIT_USAGE, "no runs found")
        try:
            final = self.store.load_final(target)
        except PersistenceError as exc:
            return Outcome("error", EXIT_USAGE, str(exc))
        run_dir = self.store.run_dir(target)
        lines = [
            f"run dir: {run_dir}",
            f"request: {run_dir / 'request.md'}",
            f"plan:    {run_dir / 'initial-plan.json'}",
            f"final:   {run_dir / 'final.json'}",
            f"docs:    {self.store.docs_dir()}",
        ]
        if final is not None:
            lines.extend(f"{name}: {path}" for name, path in final.artifacts.items())
        else:
            lines.append("(run unfinished; round and transcript files under run dir)")
        return Outcome("artifacts", EXIT_OK, f"artifacts for run {target}", lines)

    # --- helpers ------------------------------------------------------------------------

    @staticmethod
    def _outcome(result: OrchestratorResult) -> Outcome:
        lines = [
            f"status:  {result.status.value}",
            f"run id:  {result.run_id}",
            f"rounds:  {result.final.rounds_used}",
            f"report:  docs/metacoding/FINAL_REPORT.md",
        ]
        if result.final.warnings:
            lines.append(f"warnings: {len(result.final.warnings)} (see final report)")
        return Outcome(
            result.status.value,
            result.exit_code,
            result.message or result.final.reason,
            lines,
            run_id=result.run_id,
        )


def _owned_files(store: RunStore, run_id: str) -> set[str]:
    owned: set[str] = set()
    for round_record in store.load_rounds(run_id).values():
        owned.update(round_record.changed_files)
    return owned
