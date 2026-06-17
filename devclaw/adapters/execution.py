from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Protocol

from devclaw.adapters.tool_runner import ToolExecutionResult, run_tool_with_idle_monitor
from devclaw.core.models import AcceptanceContract, AgentOutput, ProjectBrief
from devclaw.core.role_assignments import RoleAssignment


class ExecutionAdapter(Protocol):
    def execute(
        self,
        brief: ProjectBrief,
        contract: AcceptanceContract,
        workspace: Path,
    ) -> AgentOutput:
        ...


class CodexCliExecutionAdapter:
    """Non-interactive Codex CLI adapter.

    v0.1 keeps this adapter explicit and injectable so test runs do not depend on
    model availability or interactive terminal state.
    """

    def __init__(
        self,
        codex_bin: str = "codex",
        idle_timeout_seconds: int = 900,
        progress: Callable[[dict[str, str]], None] | None = None,
    ):
        self.codex_bin = codex_bin
        self.idle_timeout_seconds = idle_timeout_seconds
        self.progress = progress
        self._emitted_milestones: set[str] = set()
        self._active_role: RoleAssignment | None = None

    def execute(
        self,
        brief: ProjectBrief,
        contract: AcceptanceContract,
        workspace: Path,
    ) -> AgentOutput:
        workspace.mkdir(parents=True, exist_ok=True)
        prompt = "\n".join(
            [
                "Implement this DevClaw R&D deliverable.",
                "Autonomous execution mode: the user has delegated product and technical decisions to DevClaw.",
                "Use available skills when useful, but do not stop to request approval for normal product or implementation choices.",
                "When multiple reasonable approaches exist, choose the best pragmatic option, document the decision, and continue.",
                "Only stop for user confirmation if delivery would require external spending, destructive production actions, or credentials not available in the workspace.",
                "Do not stop at planning, brainstorming, or asking for approval. Deliver working files in the workspace.",
                f"Goal: {brief.goal}",
                "Acceptance:",
                *[f"- {item.id}: {item.description}" for item in contract.blocking_items()],
                "Create runnable code and concise usage documentation in the workspace.",
            ]
        )
        try:
            result = run_tool_with_idle_monitor(
                [
                    self.codex_bin,
                    "exec",
                    "-C",
                    str(workspace),
                    "--skip-git-repo-check",
                    "--dangerously-bypass-approvals-and-sandbox",
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
                "codex-execution.txt",
                prompt,
                "",
                str(exc),
                124,
            )
            raise RuntimeError(str(exc)) from exc
        if result.returncode != 0:
            _write_transcript(workspace, "codex-execution.txt", prompt, result.stdout, result.stderr, result.returncode)
            raise RuntimeError(_tool_error_message(result.stderr or result.stdout))
        _write_transcript(workspace, "codex-execution.txt", prompt, result.stdout, result.stderr, result.returncode)
        if _looks_like_confirmation_request(result.stdout) and not _looks_like_delivery(workspace):
            raise RuntimeError(
                "USER_CONFIRMATION_REQUIRED: Codex requested user confirmation instead of delivering workspace files."
            )
        return AgentOutput(
            agent="Engineer Agent",
            artifact="Codex CLI Execution",
            content=result.stdout,
            path=None,
        )

    def execute_prompt(self, prompt: str, workspace: Path) -> str:
        workspace = workspace.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        try:
            result = run_tool_with_idle_monitor(
                [
                    self.codex_bin,
                    "exec",
                    "-C",
                    str(workspace),
                    "--skip-git-repo-check",
                    "--dangerously-bypass-approvals-and-sandbox",
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
                "codex-execution.txt",
                prompt,
                "",
                str(exc),
                124,
            )
            raise RuntimeError(str(exc)) from exc
        else:
            _write_transcript(workspace, "codex-execution.txt", prompt, result.stdout, result.stderr, result.returncode)
            if result.returncode != 0:
                raise RuntimeError(_tool_error_message(result.stderr or result.stdout))
            return result.stdout

    def plan_workflow(self, intent: str, context_pack: str, workspace: Path) -> str:
        prompt = _workflow_planner_prompt(intent, context_pack)
        workspace = workspace.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        try:
            result = run_tool_with_idle_monitor(
                [
                    self.codex_bin,
                    "exec",
                    "-C",
                    str(workspace),
                    "--skip-git-repo-check",
                    "--dangerously-bypass-approvals-and-sandbox",
                    prompt,
                ],
                cwd=workspace,
                idle_timeout_seconds=self.idle_timeout_seconds,
                on_output=self._on_tool_output,
                on_heartbeat=self._on_tool_heartbeat,
                heartbeat_interval_seconds=60,
            )
        except TimeoutError as exc:
            _write_transcript(workspace, "codex-workflow-planner.txt", prompt, "", str(exc), 124)
            raise RuntimeError(str(exc)) from exc
        _write_transcript(
            workspace,
            "codex-workflow-planner.txt",
            prompt,
            result.stdout,
            result.stderr,
            result.returncode,
        )
        if result.returncode != 0:
            raise RuntimeError(_tool_error_message(result.stderr or result.stdout))
        return result.stdout

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
                    self.codex_bin,
                    "exec",
                    "-C",
                    str(workspace),
                    "--skip-git-repo-check",
                    "--dangerously-bypass-approvals-and-sandbox",
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
            raise RuntimeError(_tool_error_message(result.stderr or result.stdout))
        return AgentOutput(
            agent=assignment.role,
            artifact=assignment.artifact,
            content=result.stdout.strip(),
        )

    def _on_tool_output(self, stream: str, chunk: str) -> None:
        if self.progress is None:
            return
        for line in chunk.splitlines():
            text = line.strip()
            milestone = _implementation_milestone(text)
            if milestone:
                self._emit_milestone(milestone)

    def _on_tool_heartbeat(self, elapsed_seconds: float) -> None:
        if self.progress is None:
            return
        role = self._active_role
        self.progress(
            {
                "stage": role.stage if role else "implementation",
                "agent": role.role if role else "Codex Implementation Agent",
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
                "stage": role.stage if role else "implementation",
                "agent": role.role if role else "Codex Implementation Agent",
                "status": "milestone",
                "message": message,
            }
        )


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


def _workflow_planner_prompt(intent: str, context_pack: str) -> str:
    return "\n".join(
        [
            "You are the DevClaw Workflow Planner.",
            "Classify the user's request into the smallest safe workflow.",
            "Use the context pack to decide whether this is a new project, a targeted follow-up, a bugfix, verification, docs-only, or research-only request.",
            "Return only JSON. Do not include Markdown, prose, or code fences.",
            "",
            "Allowed mode values:",
            "- full-rd: brand-new or broad product work needing research, PRD, design, architecture, implementation, and verification.",
            "- targeted-change: localized implementation or performance/UI improvement using existing context.",
            "- bugfix: localized defect fix.",
            "- verification: tests, QA, review, or acceptance only.",
            "- docs-only: documentation or copy-only change.",
            "- research-only: investigation or research without code changes.",
            "",
            "JSON schema:",
            '{"mode":"targeted-change","reason":"short concrete reason","confidence":0.0}',
            "",
            "Routing guidance:",
            "- If prior context exists and the user asks to optimize, speed up, fix, adjust, improve, or refine an existing page/feature, prefer targeted-change or bugfix.",
            "- Do not choose full-rd for localized page performance work.",
            "- Choose full-rd only when the request creates a new product area or requires end-to-end discovery.",
            "",
            "# User Request",
            intent,
            "",
            "# Context Pack",
            context_pack[:12000],
        ]
    )


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


def _tool_error_message(output: str) -> str:
    text = output.strip() or "Tool failed without output."
    lowered = text.lower()
    if "concurrency limit exceeded" in lowered:
        return f"TOOL_RETRYABLE: Codex concurrency limit exceeded. Retry later or stop other Codex sessions. Detail: {text}"
    if "stream disconnected before completion" in lowered:
        return f"TOOL_RETRYABLE: Codex stream disconnected before completion. Retry later. Detail: {text}"
    return text


def _looks_like_confirmation_request(output: str) -> bool:
    normalized = output.strip().lower()
    if not normalized:
        return False
    patterns = [
        r"请确认",
        r"请选择",
        r"需要你确认",
        r"等待.*确认",
        r"please confirm",
        r"please choose",
        r"waiting for .*approval",
        r"which option",
        r"\boption\s+[abc]\b",
    ]
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in patterns)


def _implementation_milestone(text: str) -> str | None:
    lowered = text.lower()
    if not lowered:
        return None
    if "inspect" in lowered or "rg --files" in lowered or "pwd &&" in lowered:
        return "Inspecting project structure and existing context."
    if "apply patch" in lowered or "patch: completed" in lowered or "code changes" in lowered:
        return "Applying code changes."
    if "pytest" in lowered or "npm test" in lowered or "unittest" in lowered or "acceptance_checks" in lowered:
        return "Running implementation checks."
    if "readme" in lowered or "documentation" in lowered or "delivery" in lowered or "release" in lowered:
        return "Preparing documentation and delivery notes."
    if "succeeded" in lowered and ("test" in lowered or "checks" in lowered):
        return "Implementation checks completed."
    return None


def _looks_like_delivery(workspace: Path) -> bool:
    ignored_parts = {".devclaw", ".git", ".pytest_cache", "__pycache__"}
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ignored_parts for part in path.relative_to(workspace).parts):
            continue
        return True
    return False
