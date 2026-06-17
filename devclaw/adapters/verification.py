from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Protocol

from devclaw.adapters.tool_runner import run_tool_with_idle_monitor
from devclaw.core.context import scan_project_context
from devclaw.core.models import AcceptanceContract, AgentOutput, ProjectBrief, VerificationReport
from devclaw.core.role_assignments import RoleAssignment


class VerificationAdapter(Protocol):
    def verify(
        self,
        brief: ProjectBrief,
        contract: AcceptanceContract,
        workspace: Path,
    ) -> VerificationReport:
        ...


class DeepseekTuiVerificationAdapter:
    """Non-interactive Deepseek TUI verification adapter."""

    def __init__(
        self,
        deepseek_bin: str = "deepseek",
        idle_timeout_seconds: int = 900,
        progress: Callable[[dict[str, str]], None] | None = None,
    ):
        self.deepseek_bin = deepseek_bin
        self.idle_timeout_seconds = idle_timeout_seconds
        self.progress = progress
        self._emitted_milestones: set[str] = set()
        self._active_role: RoleAssignment | None = None

    def verify(
        self,
        brief: ProjectBrief,
        contract: AcceptanceContract,
        workspace: Path,
    ) -> VerificationReport:
        prompt = "\n".join(
            [
                "Verify this DevClaw deliverable against the acceptance contract.",
                f"Workspace: {workspace}",
                f"Goal: {brief.goal}",
                "You are the independent QA Agent. Inspect the real workspace, including hidden .devclaw metadata.",
                "DevClaw stores research evidence in .devclaw/artifacts, release notes in .devclaw/release/latest, and delivery docs in .devclaw/delivery/latest.",
                "Do not fail because final delivery reports are absent before QA; final-delivery-report.json is written only after QA completes.",
                "Do not claim evidence is missing until you have checked the project root and .devclaw directories.",
                "Run or inspect these detected test commands when present:",
                *[f"- {command}" for command in scan_project_context(workspace).test_commands],
                "Then decide whether blocking acceptance passed.",
                "Return exactly one JSON object with these keys:",
                'status: "pass" or "fail"',
                "failed_acceptance: array of failed acceptance IDs",
                "blocking_issues: array of blocking issue strings",
                "non_blocking_issues: array of non-blocking issue strings",
                "evidence: array of concise evidence strings",
                "Acceptance:",
                *[f"- {item.id}: {item.description}" for item in contract.blocking_items()],
            ]
        )
        try:
            result = run_tool_with_idle_monitor(
                [
                    self.deepseek_bin,
                    "exec",
                    "--auto",
                    "--sandbox-mode",
                    "danger-full-access",
                    "--approval-policy",
                    "never",
                    prompt,
                ],
                cwd=workspace,
                idle_timeout_seconds=self.idle_timeout_seconds,
                on_output=self._on_tool_output,
                on_heartbeat=self._on_tool_heartbeat,
                heartbeat_interval_seconds=60,
            )
        except TimeoutError as exc:
            _write_transcript(
                workspace,
                "deepseek-verification.txt",
                prompt,
                "",
                str(exc),
                124,
            )
            return VerificationReport(
                status="fail",
                failed_acceptance=["QA_IDLE_TIMEOUT"],
                blocking_issues=[
                    str(exc)
                ],
                non_blocking_issues=[],
                evidence=[],
            )
        if result.returncode != 0:
            _write_transcript(workspace, "deepseek-verification.txt", prompt, result.stdout, result.stderr, result.returncode)
            return VerificationReport(
                status="fail",
                failed_acceptance=["QA1"],
                blocking_issues=[result.stderr or "Deepseek verification failed."],
                non_blocking_issues=[],
                evidence=[result.stdout],
            )
        output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
        _write_transcript(workspace, "deepseek-verification.txt", prompt, result.stdout, result.stderr, result.returncode)
        return parse_deepseek_verification_output(output)

    def run_role(
        self,
        assignment: RoleAssignment,
        brief: ProjectBrief,
        contract: AcceptanceContract,
        workspace: Path,
        previous_outputs: list[AgentOutput],
    ) -> AgentOutput:
        prompt = _role_prompt(assignment, brief, contract, workspace, previous_outputs)
        try:
            self._active_role = assignment
            result = run_tool_with_idle_monitor(
                [
                    self.deepseek_bin,
                    "exec",
                    "--auto",
                    "--sandbox-mode",
                    "danger-full-access",
                    "--approval-policy",
                    "never",
                    prompt,
                ],
                cwd=workspace,
                idle_timeout_seconds=self.idle_timeout_seconds,
                on_output=self._on_tool_output,
                on_heartbeat=self._on_tool_heartbeat,
                heartbeat_interval_seconds=60,
            )
        except TimeoutError as exc:
            _write_transcript(workspace, f"{assignment.role.lower().replace(' ', '-')}.txt", prompt, "", str(exc), 124)
            raise RuntimeError(str(exc)) from exc
        finally:
            self._active_role = None
        _write_transcript(
            workspace,
            f"{assignment.role.lower().replace(' ', '-')}.txt",
            prompt,
            result.stdout,
            result.stderr,
            result.returncode,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)
        return AgentOutput(
            agent=assignment.role,
            artifact=assignment.artifact,
            content=result.stdout.strip(),
        )

    def select_context(self, intent: str, raw_context_pack: str, workspace: Path) -> str:
        prompt = _context_selector_prompt(intent, raw_context_pack)
        try:
            result = run_tool_with_idle_monitor(
                [
                    self.deepseek_bin,
                    "exec",
                    "--auto",
                    "--sandbox-mode",
                    "danger-full-access",
                    "--approval-policy",
                    "never",
                    prompt,
                ],
                cwd=workspace,
                idle_timeout_seconds=self.idle_timeout_seconds,
                on_output=self._on_tool_output,
                on_heartbeat=self._on_tool_heartbeat,
                heartbeat_interval_seconds=60,
            )
        except TimeoutError as exc:
            _write_transcript(workspace, "deepseek-context-selector.txt", prompt, "", str(exc), 124)
            raise RuntimeError(str(exc)) from exc
        _write_transcript(
            workspace,
            "deepseek-context-selector.txt",
            prompt,
            result.stdout,
            result.stderr,
            result.returncode,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)
        return result.stdout.strip()

    def generate_acceptance_checks(
        self,
        brief: ProjectBrief,
        contract: AcceptanceContract,
        workspace: Path,
        context_summary: str,
    ) -> str:
        prompt = _acceptance_check_prompt(brief, contract, context_summary)
        try:
            result = run_tool_with_idle_monitor(
                [
                    self.deepseek_bin,
                    "exec",
                    "--auto",
                    "--sandbox-mode",
                    "danger-full-access",
                    "--approval-policy",
                    "never",
                    prompt,
                ],
                cwd=workspace,
                idle_timeout_seconds=self.idle_timeout_seconds,
                on_output=self._on_tool_output,
                on_heartbeat=self._on_tool_heartbeat,
                heartbeat_interval_seconds=60,
            )
        except TimeoutError as exc:
            _write_transcript(workspace, "deepseek-acceptance-checks.txt", prompt, "", str(exc), 124)
            raise RuntimeError(str(exc)) from exc
        _write_transcript(
            workspace,
            "deepseek-acceptance-checks.txt",
            prompt,
            result.stdout,
            result.stderr,
            result.returncode,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)
        return _ensure_trailing_newline(_strip_code_fence(result.stdout.strip()))

    def _on_tool_output(self, stream: str, chunk: str) -> None:
        if self.progress is None:
            return
        for line in chunk.splitlines():
            text = line.strip()
            milestone = _verification_milestone(text)
            if milestone:
                self._emit_milestone(milestone)

    def _on_tool_heartbeat(self, elapsed_seconds: float) -> None:
        if self.progress is None:
            return
        role = self._active_role
        self.progress(
            {
                "stage": role.stage if role else "verification",
                "agent": role.role if role else "Deepseek QA Agent",
                "status": "heartbeat",
                "message": "Still running; waiting for the tool to produce the next useful update.",
                "elapsed_seconds": f"{elapsed_seconds:.1f}",
            }
        )

    def _emit_milestone(self, message: str) -> None:
        if self.progress is None or message in self._emitted_milestones:
            return
        self._emitted_milestones.add(message)
        role = self._active_role
        self.progress(
            {
                "stage": role.stage if role else "verification",
                "agent": role.role if role else "Deepseek QA Agent",
                "status": "milestone",
                "message": message,
            }
        )


def parse_deepseek_verification_output(output: str) -> VerificationReport:
    parsed = _extract_json_object(output)
    if parsed is None:
        return VerificationReport(
            status="fail",
            failed_acceptance=["QA_PARSE"],
            blocking_issues=[
                "Deepseek output did not contain a structured verification report."
            ],
            non_blocking_issues=[],
            evidence=[output.strip()],
        )

    status = parsed.get("status")
    if status not in {"pass", "fail"}:
        status = "fail"
    failed_acceptance = _string_list(parsed.get("failed_acceptance"))
    blocking_issues = _string_list(parsed.get("blocking_issues"))
    non_blocking_issues = _string_list(parsed.get("non_blocking_issues"))
    evidence = _string_list(parsed.get("evidence"))

    if status == "pass" and (failed_acceptance or blocking_issues):
        status = "fail"
    if status == "fail" and not failed_acceptance and not blocking_issues:
        failed_acceptance = ["QA1"]
        blocking_issues = ["Deepseek reported failure without specific blocking issues."]

    return VerificationReport(
        status=status,
        failed_acceptance=failed_acceptance,
        blocking_issues=blocking_issues,
        non_blocking_issues=non_blocking_issues,
        evidence=evidence or [output.strip()],
    )


def _verification_milestone(text: str) -> str | None:
    lowered = text.lower()
    if not lowered:
        return None
    if '"status"' in lowered or "verdict" in lowered:
        return "Parsing QA verdict."
    if "inspect" in lowered or ".devclaw" in lowered or "delivered files" in lowered:
        return "Inspecting delivered files and DevClaw artifacts."
    if "pytest" in lowered or "npm test" in lowered or "unittest" in lowered or "acceptance" in lowered:
        return "Running QA checks."
    return None


def _extract_json_object(output: str) -> dict[str, object] | None:
    try:
        data = json.loads(output)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", output, re.DOTALL)
    if fenced:
        try:
            data = json.loads(fenced.group(1))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            pass

    valid_objects: list[dict[str, object]] = []
    for match in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", output, re.DOTALL):
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and {"status", "failed_acceptance", "blocking_issues"}.issubset(data):
            valid_objects.append(data)
    if valid_objects:
        return valid_objects[-1]

    start = output.find("{")
    end = output.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(output[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _write_transcript(
    workspace: Path,
    filename: str,
    prompt: str,
    stdout: str,
    stderr: str,
    returncode: int,
) -> None:
    path = workspace / ".devclaw" / "reports" / "tool-transcripts" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "# Prompt",
                prompt,
                "",
                "# Return Code",
                str(returncode),
                "",
                "# Stdout",
                stdout,
                "",
                "# Stderr",
                stderr,
            ]
        ),
        encoding="utf-8",
    )


def _context_selector_prompt(intent: str, raw_context_pack: str) -> str:
    return "\n".join(
        [
            "You are the DevClaw Context Selector.",
            "Summarize only the context that is relevant to the current request.",
            "Prefer concise bullets. Include stage document paths that should be consulted.",
            "Do not invent facts. If context is not relevant, say so.",
            "",
            "# Current Request",
            intent,
            "",
            "# Raw Context Pack",
            raw_context_pack[:16000],
            "",
            "Return Markdown with these sections:",
            "# Context Summary",
            "## Relevant Prior Work",
            "## Files And Stage Docs To Inspect",
            "## Risks Or Missing Context",
        ]
    )


def _acceptance_check_prompt(
    brief: ProjectBrief,
    contract: AcceptanceContract,
    context_summary: str,
) -> str:
    return "\n".join(
        [
            "You are the DevClaw Acceptance Check Generator.",
            "Return only Python code for .devclaw/checks/acceptance_checks.py.",
            "The script must be deterministic, runnable with python3, and must not require network access.",
            "It should exit 0 only when blocking acceptance appears satisfied.",
            "Use conservative checks grounded in the workspace and contract.",
            "",
            f"Goal: {brief.goal}",
            "",
            "Acceptance:",
            *[f"- {item.id}: {item.description}" for item in contract.blocking_items()],
            "",
            "Context Summary:",
            context_summary[:8000],
            "",
            "Return only Python code. Do not include Markdown or code fences.",
        ]
    )


def _strip_code_fence(output: str) -> str:
    match = re.fullmatch(r"```(?:python)?\s*(.*?)\s*```", output, flags=re.DOTALL)
    return match.group(1).strip() + "\n" if match else output


def _ensure_trailing_newline(output: str) -> str:
    return output if output.endswith("\n") else output + "\n"


def _role_prompt(
    assignment: RoleAssignment,
    brief: ProjectBrief,
    contract: AcceptanceContract,
    workspace: Path,
    previous_outputs: list[AgentOutput],
) -> str:
    return "\n".join(
        [
            f"You are {assignment.role}.",
            f"Provider: {assignment.provider}.",
            f"Workspace: {workspace}",
            f"Goal: {brief.goal}",
            "",
            "Mission:",
            assignment.mission,
            "",
            "Skills to use:",
            *[f"- {skill}" for skill in assignment.skills],
            "",
            "Acceptance:",
            *[f"- {item.id}: {item.description}" for item in contract.blocking_items()],
            "",
            "Previous stage outputs:",
            *[f"- {output.agent}: {output.artifact}" for output in previous_outputs],
            "",
            "Return Markdown only. Include these sections:",
            "## Skills Used",
            "## Reasoning",
            "## Evidence",
            "## Output",
        ]
    )
