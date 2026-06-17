from __future__ import annotations

import shlex
import sys
from pathlib import Path

from devclaw.adapters.tool_runner import run_tool_with_idle_monitor
from devclaw.core.context import scan_project_context
from devclaw.core.models import AcceptanceContract, AgentOutput, ProjectBrief, VerificationReport
from devclaw.core.role_assignments import RoleAssignment


class TestExecutionAdapter:
    def __init__(self):
        self.role_calls: list[str] = []
        self.planner_outputs: list[str] = []

    def plan_workflow(self, intent: str, context_pack: str, workspace: Path) -> str:
        if not self.planner_outputs:
            raise AttributeError("planner not configured")
        return self.planner_outputs.pop(0)

    def run_role(
        self,
        assignment: RoleAssignment,
        brief: ProjectBrief,
        contract: AcceptanceContract,
        workspace: Path,
        previous_outputs: list[AgentOutput],
    ) -> AgentOutput:
        self.role_calls.append(assignment.role)
        return AgentOutput(
            agent=assignment.role,
            artifact=assignment.artifact,
            content=_role_doc(assignment),
        )

    def execute(
        self,
        brief: ProjectBrief,
        contract: AcceptanceContract,
        workspace: Path,
    ) -> AgentOutput:
        workspace.mkdir(parents=True, exist_ok=True)
        agent_path = workspace / "agent.py"
        usage_path = workspace / "USAGE.md"
        agent_path.write_text(_agent_source(brief.goal), encoding="utf-8")
        usage_path.write_text(_usage_doc(brief, contract), encoding="utf-8")
        return AgentOutput(
            agent="Engineer Agent",
            artifact="Runnable implementation",
            content=f"Created {agent_path.name} and {usage_path.name}",
            path="agent.py",
        )


class TestVerificationAdapter:
    def __init__(self):
        self.role_calls: list[str] = []
        self.context_summaries: list[str] = []
        self.generated_checks: list[str] = []

    def select_context(self, intent: str, raw_context_pack: str, workspace: Path) -> str:
        if self.context_summaries:
            return self.context_summaries.pop(0)
        return "# Deepseek Context Summary\n\n- No extra semantic filtering configured.\n"

    def generate_acceptance_checks(
        self,
        brief: ProjectBrief,
        contract: AcceptanceContract,
        workspace: Path,
        context_summary: str,
    ) -> str:
        if self.generated_checks:
            return self.generated_checks.pop(0)
        return ""

    def run_role(
        self,
        assignment: RoleAssignment,
        brief: ProjectBrief,
        contract: AcceptanceContract,
        workspace: Path,
        previous_outputs: list[AgentOutput],
    ) -> AgentOutput:
        self.role_calls.append(assignment.role)
        return AgentOutput(
            agent=assignment.role,
            artifact=assignment.artifact,
            content=_role_doc(assignment),
        )

    def verify(
        self,
        brief: ProjectBrief,
        contract: AcceptanceContract,
        workspace: Path,
    ) -> VerificationReport:
        context = scan_project_context(workspace)
        if context.test_commands:
            return self._verify_project_tests(context.test_commands, workspace)
        return self._verify_reference_delivery(workspace)

    def _verify_project_tests(
        self,
        test_commands: list[str],
        workspace: Path,
    ) -> VerificationReport:
        failed: list[str] = []
        blocking: list[str] = []
        evidence: list[str] = []
        for command in test_commands:
            result = run_tool_with_idle_monitor(
                shlex.split(command),
                cwd=workspace,
                idle_timeout_seconds=900,
            )
            output = result.stdout.strip() or result.stderr.strip() or "<no output>"
            evidence.append(f"$ {command}\n{output}")
            if result.returncode == 5 and "no tests ran" in output.lower():
                continue
            if result.returncode != 0:
                failed.append("Q1")
                blocking.append(f"Project test command failed: {command}")
        return VerificationReport(
            status="pass" if not failed and not blocking else "fail",
            failed_acceptance=sorted(set(failed)),
            blocking_issues=blocking,
            non_blocking_issues=[],
            evidence=evidence,
        )

    def _verify_reference_delivery(self, workspace: Path) -> VerificationReport:
        failed: list[str] = []
        blocking: list[str] = []
        evidence: list[str] = []
        agent_path = workspace / "agent.py"
        usage_path = workspace / "USAGE.md"
        if not agent_path.exists():
            failed.append("F1")
            blocking.append("Runnable implementation is missing.")
        if not usage_path.exists():
            failed.extend(["UX1", "D1"])
            blocking.append("Usage documentation is missing.")
        if agent_path.exists():
            result = run_tool_with_idle_monitor(
                [sys.executable, str(agent_path), "bug: export is broken"],
                cwd=workspace,
                idle_timeout_seconds=900,
            )
            evidence.append(result.stdout.strip() or result.stderr.strip())
            if result.returncode != 0 or "category=bug" not in result.stdout:
                failed.append("F1")
                blocking.append("Sample bug feedback was not classified correctly.")
            empty_result = run_tool_with_idle_monitor(
                [sys.executable, str(agent_path), ""],
                cwd=workspace,
                idle_timeout_seconds=900,
            )
            evidence.append(empty_result.stdout.strip() or empty_result.stderr.strip())
            if "empty input" not in empty_result.stdout:
                failed.append("Q1")
                blocking.append("Empty input is not handled safely.")
        failed = sorted(set(failed))
        return VerificationReport(
            status="pass" if not failed and not blocking else "fail",
            failed_acceptance=failed,
            blocking_issues=blocking,
            non_blocking_issues=[],
            evidence=evidence,
        )


def _agent_source(goal: str) -> str:
    return f'''"""Generated test runnable Agent."""

import sys


def handle_feedback(text: str) -> str:
    value = text.strip()
    if not value:
        return "error: empty input"
    lowered = value.lower()
    if "bug" in lowered or "broken" in lowered or "fail" in lowered:
        category = "bug"
    elif "feature" in lowered or "request" in lowered or "add" in lowered:
        category = "feature"
    else:
        category = "general"
    return f"goal={goal!r}; category={{category}}; summary={{value}}"


def main() -> int:
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read()
    print(handle_feedback(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _usage_doc(brief: ProjectBrief, contract: AcceptanceContract) -> str:
    return "\n".join(
        [
            f"# Usage: {brief.project_id}",
            "",
            "Run:",
            "",
            "```bash",
            "python3 agent.py \"bug: export is broken\"",
            "```",
            "",
            "Acceptance covered:",
            *[f"- {item.id}: {item.description}" for item in contract.blocking_items()],
        ]
    )


def _role_doc(assignment: RoleAssignment) -> str:
    return "\n".join(
        [
            f"# {assignment.artifact}",
            "",
            "## Skills Used",
            *[f"- {skill}" for skill in assignment.skills],
            "",
            "## Reasoning",
            assignment.mission,
            "",
            "## Evidence",
            f"- Provider: {assignment.provider}",
            "",
            "## Output",
            f"- Stage: {assignment.output_stage}",
        ]
    )
