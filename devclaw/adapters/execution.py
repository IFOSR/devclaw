from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Protocol

from devclaw.adapters.tool_runner import ToolExecutionResult, run_tool_with_idle_monitor
from devclaw.core.models import AcceptanceContract, AgentOutput, ProjectBrief


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
            raise RuntimeError(result.stderr or result.stdout)
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
                raise RuntimeError(result.stderr or result.stdout)
            return result.stdout

    def _on_tool_output(self, stream: str, chunk: str) -> None:
        if self.progress is None:
            return
        for line in chunk.splitlines():
            text = line.strip()
            milestone = _implementation_milestone(text)
            if milestone:
                self._emit_milestone(milestone)

    def _emit_milestone(self, message: str) -> None:
        if self.progress is None or message in self._emitted_milestones:
            return
        self._emitted_milestones.add(message)
        self.progress(
            {
                "stage": "implementation",
                "agent": "Codex Implementation Agent",
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
