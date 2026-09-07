"""Fake harnesses for deterministic offline tests.

Two modes share one scenario format:

- **Subprocess mode** (provider = "fake"): runs
  ``python3 -m metacoding.harnesses.fake`` so the full process runner,
  transcript, and parsing pipeline is exercised without codex/pi.
- **In-process mode** (``scenario`` dict passed to the constructor): used
  by orchestrator unit tests to drive the state machine directly.

Scenario file::

    {
      "attempts": {
        "plan":   [step, ...],
        "code":   [step, ...],
        "test":   [step, ...],
        "review": [step, ...]
      }
    }

Each *step* is either the structured payload itself or an object with:

- ``behavior``: ``"malformed"``, ``"timeout"``, or ``"nonzero"``
- ``payload``: the structured payload to emit
- ``files``: mapping of project-relative paths to contents to create

When attempts exceed the scripted list, the last step repeats.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from metacoding.errors import (
    HarnessNonZeroExit,
    HarnessTimeout,
    MalformedHarnessOutput,
)
from metacoding.harnesses.base import Harness, HarnessContext
from metacoding.harnesses.codex_planner import CodexPlanner
from metacoding.harnesses.codex_tester import CodexTester
from metacoding.harnesses.pi_coder import PiCoder
from metacoding.process_runner import CommandResult

SCENARIO_FILENAME = ".metacoding/fake-scenario.json"


def fake_scenario_path(project_root: Path) -> Path:
    return Path(project_root) / SCENARIO_FILENAME


def write_scenario(project_root: Path, scenario: dict) -> Path:
    path = fake_scenario_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scenario, indent=2) + "\n", encoding="utf-8")
    return path


def select_step(scenario: dict, stage: str, attempt: int) -> dict | None:
    steps = scenario.get("attempts", {}).get(stage, [])
    if not steps:
        return None
    index = min(max(attempt - 1, 0), len(steps) - 1)
    step = steps[index]
    return step if isinstance(step, dict) else {"payload": step}


def apply_step_to_project(project_root: Path, step: dict) -> None:
    for relative_path, content in (step.get("files") or {}).items():
        target = Path(project_root) / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")


def run_subprocess_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="metacoding.harnesses.fake")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--attempt", type=int, default=1)
    args = parser.parse_args(argv)

    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    step = select_step(scenario, args.stage, args.attempt)
    if step is None:
        return 0

    project_root = Path.cwd()
    apply_step_to_project(project_root, step)

    behavior = step.get("behavior")
    if behavior == "malformed":
        Path(args.report).write_text("{this is not json", encoding="utf-8")
        return 0
    if behavior == "timeout":
        time.sleep(3600)
        return 0
    if behavior == "nonzero":
        print("fake harness failure", file=sys.stderr)
        return 7

    payload = step.get("payload", {k: v for k, v in step.items() if k != "files"})
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


class _FakeHarnessMixin(Harness):
    """Adds in-process scripted invocation on top of a real adapter."""

    def __init__(self, harness_config, project_root: Path, scenario: dict | None) -> None:
        super().__init__(harness_config, project_root)
        self.scenario = scenario

    def invocation_env(self) -> dict[str, str] | None:
        """Ensure the in-repo fake CLI stays importable from any cwd."""
        import os

        env = dict(os.environ)
        package_root = str(Path(__file__).resolve().parents[2])
        existing = env.get("PYTHONPATH", "")
        if package_root not in existing.split(os.pathsep):
            env["PYTHONPATH"] = package_root + (os.pathsep + existing if existing else "")
        return env

    def build_command(self, stage: str, ctx: HarnessContext) -> list[str]:
        task = self.build_task(stage, ctx)
        return [
            self.config.command,
            *self.config.extra_args,
            "--stage",
            stage,
            "--report",
            str(task.report_path),
            "--attempt",
            str(ctx.attempt),
        ]

    def _invoke(self, stage: str, ctx: HarnessContext) -> dict:
        if self.scenario is None:
            return super()._invoke(stage, ctx)

        step = select_step(self.scenario, stage, ctx.attempt)
        if step is None:
            raise MalformedHarnessOutput(
                f"fake harness wrote no structured report for stage {stage!r}"
            )
        apply_step_to_project(self.project_root, step)
        if ctx.transcript_sink is not None:
            stub = CommandResult(
                command=["<fake>", stage],
                cwd=str(self.project_root),
                exit_code=0,
                stdout="",
                stderr="",
                started_at="",
                finished_at="",
                duration_seconds=0.0,
                timed_out=False,
                idle_timeout_seconds=ctx.idle_timeout_seconds,
            )
            ctx.transcript_sink(stage, stub)

        behavior = step.get("behavior")
        if behavior == "malformed":
            raise MalformedHarnessOutput(f"fake harness produced malformed output for {stage}")
        if behavior == "timeout":
            raise HarnessTimeout(
                f"fake harness timed out on {stage}",
                command=["<fake>", stage],
                idle_seconds=ctx.idle_timeout_seconds,
            )
        if behavior == "nonzero":
            raise HarnessNonZeroExit(
                f"fake harness exited non-zero on {stage}",
                command=["<fake>", stage],
                exit_code=7,
            )
        return step.get("payload", {k: v for k, v in step.items() if k != "files"})


class FakePlanner(_FakeHarnessMixin, CodexPlanner):
    """Fake planner: scripted plans and decisions, codex-style interface."""

    provider = "fake"

    def __init__(self, harness_config, project_root: Path, scenario: dict | None = None):
        super().__init__(harness_config, project_root, scenario)


class FakeCoder(_FakeHarnessMixin, PiCoder):
    """Fake coder: scripted coding reports, pi-style interface."""

    provider = "fake"

    def __init__(self, harness_config, project_root: Path, scenario: dict | None = None):
        super().__init__(harness_config, project_root, scenario)


class FakeTester(_FakeHarnessMixin, CodexTester):
    """Fake tester: scripted tester reports, codex-style interface."""

    provider = "fake"


if __name__ == "__main__":
    sys.exit(run_subprocess_main())
