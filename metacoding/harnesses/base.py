"""Shared harness interface: task construction, invocation, and parsing.

Harnesses receive only the paths and context they need for the current
stage. They never receive the whole project history inline; prompts point
at workspace documents and at the structured report path each harness
must write.
"""

from __future__ import annotations

import json
from abc import ABC
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from metacoding.config import HarnessConfig
from metacoding.errors import (
    HarnessNonZeroExit,
    HarnessTimeout,
    MalformedHarnessOutput,
)
from metacoding.models import (
    CodingResult,
    PlannerDecision,
    PlannerPlan,
    TesterReport,
    validate_coding_result,
    validate_planner_decision,
    validate_planner_plan,
    validate_tester_report,
)
from metacoding.process_runner import CommandResult, ProcessRunner

STAGES = ("plan", "code", "test", "review")

PLAN_SCHEMA_HINT = """{
  "goal": string,
  "scope": [string], "non_goals": [string],
  "architecture": {"approach": string, "modules": [string], "data_flow": [string], "risks": [string]},
  "acceptance_criteria": [{"id": "F-001", "description": string, "priority": "blocking"|"non_blocking", "verification_method": string}],
  "coding_tasks": [{"id": "TASK-001", "description": string, "expected_files": [string], "required_tests": [string], "done_when": string}],
  "change_policy": {"allowed_paths": [string], "protected_paths": [string], "forbidden_actions": [string]}
}"""

CODING_SCHEMA_HINT = """{
  "status": "completed"|"blocked",
  "summary": string,
  "completed_tasks": [string], "changed_files": [string],
  "tests_added_or_changed": [string], "commands_run": [string],
  "known_limitations": [string], "blocked_reason": string|null
}"""

TESTER_SCHEMA_HINT = """{
  "status": "pass"|"fail",
  "test_commands": [{"command": string, "exit_code": int, "summary": string}],
  "acceptance_results": [{"id": "F-001", "status": "pass"|"fail", "impact": "high"|"medium"|"low", "evidence": [string]}],
  "findings": [{"id": "BUG-001", "type": string, "severity": "P0"|"P1"|"P2"|"P3", "title": string, "impact": string, "reproduction": [string], "evidence": [string], "recommended_fix": string}],
  "prd_drift": [string], "regression_risks": [string], "missing_tests": [string],
  "changed_files": [string]
}"""

DECISION_SCHEMA_HINT = """{
  "decision": "accept"|"rework"|"blocked"|"human_review_required",
  "reason": string,
  "blocking_findings": [string],
  "rework_tasks": [{"id": "REWORK-001", "description": string, "target_area": [string], "verification": string}]
}"""


@dataclass
class HarnessContext:
    """Everything one harness invocation is allowed to know."""

    requirement: str
    run_id: str
    round_number: int
    attempt: int
    idle_timeout_seconds: float
    project_root: Path
    docs_dir: Path
    report_dir: Path
    plan: PlannerPlan | None = None
    rework_tasks: list[dict] = field(default_factory=list)
    tester_report: TesterReport | None = None
    changed_files: list[str] = field(default_factory=list)
    test_commands: list[str] = field(default_factory=list)
    host_checks: list[dict] = field(default_factory=list)
    policy: Any = None
    max_execution_seconds: float | None = None
    transcript_sink: Callable[[str, CommandResult], None] | None = None

    @property
    def round_dir(self) -> Path:
        return self.report_dir


@dataclass(frozen=True)
class HarnessTask:
    """One concrete harness invocation."""

    stage: str
    prompt: str
    report_path: Path
    last_message_path: Path


def _output_tail(*streams: str, max_lines: int = 6, max_chars: int = 600) -> str:
    """Last non-empty lines across the given output streams, for error messages."""
    lines: list[str] = []
    for stream in streams:
        for line in stream.splitlines():
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
    tail = "\n".join(lines[-max_lines:])
    if len(tail) > max_chars:
        tail = "..." + tail[-max_chars:]
    return tail


def strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            return "\n".join(lines)
    return stripped


def read_structured_payload(report_path: Path, last_message_path: Path) -> dict:
    """Read the structured JSON payload a harness must produce."""
    for path in (report_path, last_message_path):
        if path.is_file():
            text = strip_code_fences(path.read_text(encoding="utf-8"))
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise MalformedHarnessOutput(
                    f"harness wrote unparseable JSON to {path}: {exc}"
                ) from exc
            if not isinstance(payload, dict):
                raise MalformedHarnessOutput(
                    f"harness output at {path} must be a JSON object"
                )
            return payload
    raise MalformedHarnessOutput(
        f"harness did not write the structured report at {report_path}"
    )


class Harness(ABC):
    """Base class for the three harness adapters."""

    name: str = "harness"
    provider: str = "provider"

    def __init__(self, harness_config: HarnessConfig, project_root: Path) -> None:
        self.config = harness_config
        self.project_root = Path(project_root)
        self.runner = ProcessRunner()

    # --- stage entry points ----------------------------------------------------

    def plan(self, ctx: HarnessContext) -> PlannerPlan:
        payload = self._invoke("plan", ctx)
        return validate_planner_plan(payload)

    def code(self, ctx: HarnessContext) -> CodingResult:
        payload = self._invoke("code", ctx)
        return validate_coding_result(payload)

    def test(self, ctx: HarnessContext) -> TesterReport:
        payload = self._invoke("test", ctx)
        return validate_tester_report(payload)

    def review(self, ctx: HarnessContext) -> PlannerDecision:
        payload = self._invoke("review", ctx)
        return validate_planner_decision(payload)

    # --- invocation plumbing ---------------------------------------------------

    def payload_paths(self, stage: str, ctx: HarnessContext) -> tuple[Path, Path]:
        report_path = ctx.report_dir / f"{stage}-payload.json"
        last_message_path = ctx.report_dir / f"{stage}-payload.last-message"
        return report_path, last_message_path

    def build_task(self, stage: str, ctx: HarnessContext) -> HarnessTask:
        report_path, last_message_path = self.payload_paths(stage, ctx)
        return HarnessTask(
            stage=stage,
            prompt=self.build_prompt(stage, ctx),
            report_path=report_path,
            last_message_path=last_message_path,
        )

    def invocation_env(self) -> dict[str, str] | None:
        """Extra environment for subprocess invocations (None inherits)."""
        return None

    def _invoke(self, stage: str, ctx: HarnessContext) -> dict:
        task = self.build_task(stage, ctx)
        task.report_path.parent.mkdir(parents=True, exist_ok=True)
        command = self.build_command(stage, ctx)
        result = self.runner.run(
            command,
            cwd=self.project_root,
            idle_timeout_seconds=ctx.idle_timeout_seconds,
            max_execution_seconds=ctx.max_execution_seconds,
            env=self.invocation_env(),
        )
        if ctx.transcript_sink is not None:
            ctx.transcript_sink(stage, result)
        if result.timed_out:
            reason = "no output" if result.limit_reason != "total" else "exceeded its total time limit"
            raise HarnessTimeout(
                f"{self.provider}-{self.name} {reason} for "
                f"{result.idle_timeout_seconds:.0f}s idle / "
                f"{ctx.max_execution_seconds or 0:.0f}s total and was terminated",
                command=command,
                idle_seconds=result.idle_timeout_seconds,
            )
        if result.exit_code != 0:
            tail = _output_tail(result.stderr, result.stdout)
            raise HarnessNonZeroExit(
                f"{self.provider}-{self.name} exited with code {result.exit_code}"
                + (f"\nlast output:\n{tail}" if tail else ""),
                command=command,
                exit_code=result.exit_code,
            )
        return read_structured_payload(task.report_path, task.last_message_path)

    # --- provider specific -----------------------------------------------------

    def build_command(self, stage: str, ctx: HarnessContext) -> list[str]:  # pragma: no cover
        raise NotImplementedError

    def build_prompt(self, stage: str, ctx: HarnessContext) -> str:  # pragma: no cover
        raise NotImplementedError
