from __future__ import annotations

import argparse
import termios
import tty
import json
import subprocess
import sys
import unicodedata
from pathlib import Path

from devclaw.adapters.execution import CodexCliExecutionAdapter
from devclaw.adapters.verification import DeepseekTuiVerificationAdapter
from devclaw.core.attachments import (
    Attachment,
    append_attachments_to_intent,
    attach_image_file,
    paste_clipboard_image,
)
from devclaw.core.commit import create_commit
from devclaw.core.assets import extract_reusable_assets, find_reusable_assets
from devclaw.core.context import scan_project_context
from devclaw.core.feedback import add_feedback, get_feedback, list_feedback
from devclaw.core.loop import DevClawLead
from devclaw.core.memory import load_memory
from devclaw.core.parallel import ParallelCodexRunner, create_subtask_dag
from devclaw.core.quality import run_quality_checks
from devclaw.core.research import create_research_report
from devclaw.core.risk import create_risk_report
from devclaw.core.role_assignments import default_workflow_assignments
from devclaw.core.scaffold import create_scaffold
from devclaw.core.sessions import SessionManager
from devclaw.core.stage_docs import STAGE_DIRS
from devclaw.core.tasks import create_task_plan


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(prog="devclaw")
    parser.add_argument(
        "--workspace",
        default=".",
        help="Directory where DevClaw writes project outputs",
    )
    parser.add_argument(
        "--executor",
        choices=["codex"],
        default="codex",
        help="Implementation Agent adapter.",
    )
    parser.add_argument(
        "--verifier",
        choices=["deepseek"],
        default="deepseek",
        help="Verification Agent adapter.",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=3,
        help="Maximum DevClaw rework rounds",
    )
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=900,
        help="Seconds without tool output before treating a real Agent as stalled",
    )
    parser.add_argument("--tool-timeout", type=int, dest="idle_timeout", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run a DevClaw v0.1 R&D loop")
    run_parser.add_argument("intent", help="Natural-language product or Agent request")
    run_parser.add_argument("--workspace", default=argparse.SUPPRESS)
    run_parser.add_argument("--executor", choices=["codex"], default=argparse.SUPPRESS)
    run_parser.add_argument("--verifier", choices=["deepseek"], default=argparse.SUPPRESS)
    run_parser.add_argument("--max-rounds", type=int, default=argparse.SUPPRESS)
    run_parser.add_argument("--idle-timeout", type=int, default=argparse.SUPPRESS)
    run_parser.add_argument("--tool-timeout", type=int, dest="idle_timeout", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    slash_index = next(
        (index for index, value in enumerate(raw_argv) if _is_slash_command_token(value)),
        None,
    )
    if slash_index is not None:
        args = parser.parse_args(raw_argv[:slash_index])
        _handle_slash_command(" ".join(raw_argv[slash_index:]), args)
        return 0

    args = parser.parse_args(raw_argv)
    if args.command is None:
        return _interactive(args)
    if args.command == "run":
        result = _run(args)
        print(f"{result.final_report.delivery_status}: {result.workspace}")
        return 0 if result.final_report.delivery_status == "delivered" else 1
    return 2


def _run(args: argparse.Namespace):
    progress = getattr(args, "progress", None)
    execution_adapter = CodexCliExecutionAdapter(
        idle_timeout_seconds=args.idle_timeout,
        progress=progress,
    )
    verification_adapter = DeepseekTuiVerificationAdapter(
        idle_timeout_seconds=args.idle_timeout,
        progress=progress,
    )
    lead = DevClawLead(
        execution_adapter=execution_adapter,
        verification_adapter=verification_adapter,
        max_rounds=args.max_rounds,
        progress=progress,
    )
    return lead.run(args.intent, Path(args.workspace))


def _run_and_report(args: argparse.Namespace) -> bool:
    try:
        result = _run(args)
    except Exception as error:
        _print_run_failure(error)
        return False
    _print_run_result(result)
    return True


def _interactive(args: argparse.Namespace) -> int:
    _enable_line_editing()
    _print_welcome(args)
    pending_attachments: list[Attachment] = []
    input_history = _load_input_history(Path(args.workspace))
    while True:
        try:
            intent = _read_interactive_line(args, pending_attachments, input_history).strip()
        except EOFError:
            print()
            print("bye")
            return 0

        if not intent:
            continue
        if intent.startswith("/"):
            should_exit = _handle_slash_command(intent, args, pending_attachments)
            if should_exit:
                return 0
            continue

        run_intent = append_attachments_to_intent(intent, pending_attachments)
        _append_input_history(Path(args.workspace), intent, input_history)
        run_args = argparse.Namespace(
            intent=run_intent,
            workspace=args.workspace,
            executor=args.executor,
            verifier=args.verifier,
            max_rounds=args.max_rounds,
            idle_timeout=args.idle_timeout,
            progress=_print_progress_event,
        )
        _print_run_start(intent, run_args)
        if _run_and_report(run_args):
            pending_attachments.clear()


def _print_welcome(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    print("DevClaw")
    print(f"Project  {workspace}")
    print(f"Mode     R&D loop · {args.executor} -> {args.verifier}")
    print("Output   .devclaw/stages/<project_id>/<session_id>/")
    print()
    print("Ask DevClaw to build, fix, research, or review this project.")
    print()
    print("Try:")
    print("  Build a customer feedback triage Agent")
    print("  Ctrl+V       attach image from clipboard")
    print("  /status      show project and session state")
    print("  /help        show commands")
    print("  /sessions    inspect past runs")
    print()


def _read_interactive_line(
    args: argparse.Namespace,
    pending_attachments: list[Attachment],
    input_history: list[str] | None = None,
) -> str:
    if not sys.stdin.isatty():
        return input(_prompt(pending_attachments))
    print(_prompt(pending_attachments), end="", flush=True)
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    buffer: list[str] = []
    cursor = 0
    history = input_history or []
    history_index = len(history)
    try:
        tty.setcbreak(fd)
        while True:
            char = sys.stdin.read(1)
            if char in {"\n", "\r"}:
                print()
                return "".join(buffer)
            if char == "\x04":
                raise EOFError
            if char == "\x03":
                print("^C")
                return ""
            if char == "\x16":
                _paste_image_from_keybinding(args, pending_attachments)
                _redraw_input_line(pending_attachments, buffer, cursor)
                continue
            if char in {"\x7f", "\b"}:
                if cursor > 0:
                    del buffer[cursor - 1]
                    cursor -= 1
                    _redraw_input_line(pending_attachments, buffer, cursor)
                continue
            if char == "\x1b":
                sequence = _consume_escape_sequence()
                if sequence in {"[A", "OA"} and history:
                    history_index = max(0, history_index - 1)
                    buffer = list(history[history_index])
                    cursor = len(buffer)
                    _redraw_input_line(pending_attachments, buffer, cursor)
                elif sequence in {"[B", "OB"} and history:
                    history_index = min(len(history), history_index + 1)
                    buffer = list(history[history_index]) if history_index < len(history) else []
                    cursor = len(buffer)
                    _redraw_input_line(pending_attachments, buffer, cursor)
                elif sequence in {"[D", "OD"}:
                    cursor = max(0, cursor - 1)
                    _redraw_input_line(pending_attachments, buffer, cursor)
                elif sequence in {"[C", "OC"}:
                    cursor = min(len(buffer), cursor + 1)
                    _redraw_input_line(pending_attachments, buffer, cursor)
                elif sequence == "[3~":
                    if cursor < len(buffer):
                        del buffer[cursor]
                        _redraw_input_line(pending_attachments, buffer, cursor)
                continue
            buffer.insert(cursor, char)
            cursor += 1
            _redraw_input_line(pending_attachments, buffer, cursor)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _paste_image_from_keybinding(args: argparse.Namespace, pending_attachments: list[Attachment]) -> None:
    print()
    try:
        attachment = paste_clipboard_image(Path(args.workspace), "")
    except ValueError as error:
        print(f"Paste image unavailable: {error}")
        return
    pending_attachments.append(attachment)
    _print_attachment_notice(attachment, pending_attachments)


def _prompt(pending_attachments: list[Attachment]) -> str:
    if not pending_attachments:
        return "devclaw › "
    count = len(pending_attachments)
    label = "image" if count == 1 else "images"
    return f"devclaw [{count} {label}] › "


def _print_attachment_notice(attachment: Attachment, pending_attachments: list[Attachment]) -> None:
    count = len(pending_attachments)
    label = "image" if count == 1 else "images"
    print(f"✓ Image attached ({count} pending {label})")
    print(f"  Path: {attachment.path}")
    if attachment.note:
        print(f"  Note: {attachment.note}")


def _redraw_input_line(
    pending_attachments: list[Attachment],
    buffer: list[str],
    cursor: int | None = None,
) -> None:
    cursor = len(buffer) if cursor is None else max(0, min(cursor, len(buffer)))
    suffix = _display_width("".join(buffer[cursor:]))
    line = _prompt(pending_attachments) + "".join(buffer)
    move_left = f"\033[{suffix}D" if suffix else ""
    print("\r\033[2K" + line + move_left, end="", flush=True)


def _display_width(value: str) -> int:
    width = 0
    for char in value:
        if unicodedata.combining(char):
            continue
        category = unicodedata.category(char)
        if category.startswith("C"):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
    return width


def _consume_escape_sequence() -> str:
    # Arrow keys and other terminal escapes should not become command text.
    if not sys.stdin.isatty():
        return ""
    first = sys.stdin.read(1)
    if first == "[":
        sequence = first + sys.stdin.read(1)
        while sequence[-1].isdigit() or sequence[-1] == ";":
            sequence += sys.stdin.read(1)
        return sequence
    if first == "O":
        return first + sys.stdin.read(1)
    return first


def _load_input_history(workspace: Path) -> list[str]:
    path = _input_history_path(workspace)
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if line.strip()
    ][-200:]


def _append_input_history(workspace: Path, intent: str, history: list[str]) -> None:
    value = intent.strip()
    if not value:
        return
    if history and history[-1] == value:
        return
    history.append(value)
    del history[:-200]
    path = _input_history_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(history) + "\n", encoding="utf-8")


def _input_history_path(workspace: Path) -> Path:
    return workspace / ".devclaw" / "history" / "input-history.txt"


def _enable_line_editing() -> None:
    if not sys.stdin.isatty():
        return
    try:
        import readline
    except ImportError:
        return
    if "libedit" in (readline.__doc__ or ""):
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")


def _print_run_start(intent: str, args: argparse.Namespace) -> None:
    print()
    print(f"◇ Requirement  {intent}")
    print(f"  Project      {Path(args.workspace).resolve()}")
    print(f"  Agents       {args.executor} -> {args.verifier}")
    print(f"  Timeout      {args.idle_timeout}s idle")
    print()
    print("◇ Sequential workflow")
    print("  default R&D loop is not parallel: every Agent waits for upstream output before starting")
    print("  outputs are appended as the next Agent's input and written under .devclaw/stages/<project_id>/<session_id>/")
    print("  DevClaw may reuse prior stage outputs for small follow-up changes; the workflow mode event will state what runs")
    print("  /parallel-run is the only command that runs independent Codex subtasks in parallel")
    print()
    print("  Planned order")
    for index, assignment in enumerate(default_workflow_assignments(), start=1):
        print(f"  {index:02d}. {assignment.role} [{assignment.provider}] -> {assignment.output_stage}/{assignment.artifact}")
    sys.stdout.flush()


def _print_progress_event(event: dict[str, str]) -> None:
    status = event.get("status", "unknown")
    stage = event.get("stage", "unknown")
    agent = event.get("agent", "unknown")
    message = event.get("message", "")
    if status == "output":
        return
    if status == "heartbeat":
        print(_format_heartbeat_event(stage, agent, event))
        sys.stdout.flush()
        return
    marker = _status_marker(status)
    label = _stage_label(stage)
    meta = _progress_meta(event)
    detail = f"  {message}" if message else ""
    prefix = _step_prefix(event)
    provider = event.get("provider")
    provider_label = f" [{provider}]" if provider else ""
    print(f"{marker} {label:<16} {prefix}{agent}{provider_label} · {status}{meta}{detail}")
    if stage == "workflow" and status == "planned":
        workflow_mode = event.get("workflow_mode")
        running_roles = event.get("running_roles")
        reused_roles = event.get("reused_roles")
        if workflow_mode:
            print(f"  workflow mode: {workflow_mode}")
        if running_roles and reused_roles:
            print(f"  roles: {running_roles} running, {reused_roles} reused")
    if status == "started":
        dependency = event.get("depends_on")
        if dependency:
            print(f"  waits for: {dependency}")
    if status in {"completed", "pass", "fail", "failed"}:
        output_stage = event.get("output_stage")
        artifact = event.get("artifact")
        if output_stage or artifact:
            stage_dir = STAGE_DIRS.get(output_stage or "", output_stage or "")
            target = f".devclaw/stages/<project_id>/<session_id>/{stage_dir}"
            print(f"  writes: {target} ({artifact})")
    sys.stdout.flush()


def _print_run_result(result) -> None:
    status = result.final_report.delivery_status
    marker = "✓" if status == "delivered" else "✕"
    print()
    print(f"{marker} {status}: {result.workspace}")


def _print_run_failure(error: Exception) -> None:
    message = str(error).strip() or error.__class__.__name__
    message = message.removeprefix("TOOL_RETRYABLE:").strip()
    print()
    print(f"✕ Task failed: {message}")
    if "TOOL_RETRYABLE" in str(error):
        print("  Retryable tool error. Wait or stop other Agent sessions, then retry.")
    print("  DevClaw is still running. Fix the issue or use ↑ to recall and retry.")
    sys.stdout.flush()


def _status_marker(status: str) -> str:
    if status in {"completed", "pass", "delivered"}:
        return "✓"
    if status in {"failed", "fail", "error"}:
        return "✕"
    if status in {"started", "planned", "milestone"}:
        return "→"
    return "•"


def _stage_label(stage: str) -> str:
    return stage.replace("-", " ").title()


def _progress_meta(event: dict[str, str]) -> str:
    parts: list[str] = []
    mode = event.get("mode")
    if mode:
        parts.append(mode)
    duration = event.get("duration_seconds")
    if duration:
        parts.append(f"in {float(duration):.2f}s")
    return f" ({', '.join(parts)})" if parts else ""


def _format_heartbeat_event(stage: str, agent: str, event: dict[str, str]) -> str:
    elapsed = event.get("elapsed_seconds")
    elapsed_label = _format_elapsed(elapsed) if elapsed else "still running"
    message = event.get("message") or "Still running."
    return f"… {_stage_label(stage):<16} {agent} · still running ({elapsed_label})  {message}"


def _format_elapsed(value: str) -> str:
    seconds = float(value)
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    remaining = int(seconds % 60)
    return f"{minutes}m {remaining:02d}s"


def _step_prefix(event: dict[str, str]) -> str:
    step = event.get("step")
    total = event.get("total_steps")
    if not step or not total:
        return ""
    return f"{int(step):02d}/{int(total):02d} "


def _print_help() -> None:
    print("Commands")
    print()
    _print_command_group(
        "Core",
        [
            ("/help", "Show this help."),
            ("/status", "Show project, agents, and output paths."),
            ("/config", "Show runtime configuration."),
            ("/paste-image [note]", "Attach the image currently in the clipboard."),
            ("/attach <path> [note]", "Attach an image file to the next request."),
            ("/attachments", "List pending image attachments."),
            ("/clear", "Separate the current conversation."),
            ("/exit", "Quit DevClaw."),
        ],
    )
    _print_command_group(
        "Workflow",
        [
            ("/run <requirement>", "Run one requirement explicitly."),
            ("/research <topic>", "Create a project-aware research report."),
            ("/tasks <requirement>", "Create a task DAG plan."),
            ("/parallel-run <requirement>", "Split work across parallel Codex subtasks."),
            ("/test", "Run detected project checks."),
            ("/quality", "Run checks and show quality status."),
            ("/commit", "Create a non-interactive git commit."),
        ],
    )
    _print_command_group(
        "Project Memory",
        [
            ("/context", "Show latest project context summary."),
            ("/refresh-context", "Rescan and persist project context."),
            ("/memory", "Show project memory summary."),
            ("/history", "Show request history."),
            ("/decisions", "Show architecture decisions."),
            ("/sessions", "Show previous DevClaw requests."),
        ],
    )
    _print_command_group(
        "Utilities",
        [
            ("/report", "Print the latest final delivery report."),
            ("/artifacts", "List generated artifacts."),
            ("/diff", "Show current git diff summary."),
            ("/undo", "Restore files from the latest session snapshot."),
            ("/scaffold <type> <name>", "Create an agent or CLI scaffold spec."),
            ("/risk", "Create a risk review report."),
            ("/assets-extract <intent>", "Extract reusable assets."),
            ("/assets-search <query>", "Search reusable assets."),
            ("/feedback <content>", "Record user feedback."),
            ("/feedback-list", "List recorded feedback."),
            ("/feedback-run <id>", "Run feedback as a DevClaw task."),
        ],
    )
    print("Natural language without '/' is treated as a project requirement.")


def _print_command_group(title: str, commands: list[tuple[str, str]]) -> None:
    print(title)
    for command, description in commands:
        print(f"  {command:<28} {description}")
    print()


def _format_tool_output(message: str) -> str | None:
    stream, separator, text = message.partition(": ")
    if not separator:
        stream = "tool"
        text = message
    stripped = text.strip()
    if not stripped:
        return None
    if _is_noisy_tool_line(stripped):
        return None
    if stripped in {"codex", "deepseek", "exec", "apply patch"}:
        return f"{stripped}"
    if stripped.startswith("/bin/") or stripped.startswith("python") or stripped.startswith("pytest"):
        return f"running: {stripped}"
    if stripped.startswith("succeeded ") or stripped.startswith("exited "):
        return stripped
    if _looks_like_error_line(stripped):
        return f"error: {stripped}"
    if stream == "stdout":
        return f"output: {stripped}"
    return f"log: {stripped}"


def _looks_like_error_line(text: str) -> bool:
    lowered = text.lower()
    return (
        lowered.startswith("error:")
        or lowered.startswith("fatal:")
        or lowered.startswith("traceback ")
        or "exception" in lowered
        or "failed" in lowered
    )


def _is_noisy_tool_line(text: str) -> bool:
    prefixes = (
        "---",
        "+++",
        "@@",
        "+",
        "-",
        "index ",
        "diff --git ",
        "new file mode ",
        "deleted file mode ",
        "```",
    )
    if text.startswith(prefixes):
        return True
    noisy_exact = {
        "# Brainstorming Ideas Into Designs",
        "# Test-Driven Development (TDD)",
        "# Writing Plans",
    }
    if text in noisy_exact:
        return True
    noisy_contains = (
        "REQUIRED SUB-SKILL",
        "Do NOT invoke",
        "NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST",
    )
    return any(item in text for item in noisy_contains)


def _handle_slash_command(
    command: str,
    args: argparse.Namespace,
    pending_attachments: list[Attachment] | None = None,
) -> bool:
    pending_attachments = pending_attachments if pending_attachments is not None else []
    name, _, rest = command.partition(" ")
    name = name.lower()
    payload = rest.strip()

    if name in {"/exit", "/quit", "/q"}:
        print("bye")
        return True
    if name in {"/help", "/?"}:
        _print_help()
        return False
    if name == "/status":
        workspace = Path(args.workspace).resolve()
        print("Project")
        print(f"  Root      {workspace}")
        print(f"  Metadata  {(Path(args.workspace) / '.devclaw').resolve()}")
        print(f"  Agents    {args.executor} -> {args.verifier}")
        print(f"  Output    .devclaw/stages/<project_id>/<session_id>/")
        return False
    if name == "/config":
        print(f"workspace={args.workspace}")
        print(f"executor={args.executor}")
        print(f"verifier={args.verifier}")
        print(f"max_rounds={args.max_rounds}")
        print(f"idle_timeout={args.idle_timeout}")
        return False
    if name == "/paste-image":
        try:
            attachment = paste_clipboard_image(Path(args.workspace), payload)
        except ValueError as error:
            print(f"Paste image unavailable: {error}")
            return False
        pending_attachments.append(attachment)
        _print_attachment_notice(attachment, pending_attachments)
        return False
    if name == "/attach":
        parts = payload.split(maxsplit=1)
        if not parts:
            print("Usage: /attach <image-path> [note]")
            return False
        note = parts[1] if len(parts) > 1 else ""
        try:
            attachment = attach_image_file(Path(args.workspace), Path(parts[0]), note)
        except ValueError as error:
            print(f"Attach failed: {error}")
            return False
        pending_attachments.append(attachment)
        _print_attachment_notice(attachment, pending_attachments)
        return False
    if name == "/attachments":
        if not pending_attachments:
            print("No pending attachments.")
            return False
        print("Pending attachments")
        for index, attachment in enumerate(pending_attachments, start=1):
            note = f" - {attachment.note}" if attachment.note else ""
            print(f"  {index}. {attachment.path} ({attachment.media_type}){note}")
        return False
    if name == "/refresh-context":
        context = scan_project_context(Path(args.workspace))
        context_dir = Path(args.workspace) / ".devclaw" / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        (context_dir / "project-context.json").write_text(
            json.dumps(context.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(context.summary())
        return False
    if name == "/context":
        context_path = Path(args.workspace) / ".devclaw" / "context" / "project-context.json"
        if not context_path.exists():
            context = scan_project_context(Path(args.workspace))
            print(context.summary())
            return False
        data = json.loads(context_path.read_text(encoding="utf-8"))
        print("# Project Context")
        print(f"Root: {data['project_root']}")
        print(f"Primary language: {data['primary_language']}")
        print(f"Frameworks: {', '.join(data['frameworks']) or 'unknown'}")
        print(f"Test commands: {', '.join(data['test_commands']) or 'none detected'}")
        print(f"Docs: {', '.join(data['docs']) or 'none detected'}")
        return False
    if name == "/report":
        report_path = Path(args.workspace) / ".devclaw" / "final-delivery-report.json"
        if not report_path.exists():
            print("No final delivery report found.")
            return False
        print(json.dumps(json.loads(report_path.read_text(encoding="utf-8")), indent=2))
        return False
    if name == "/research":
        if not payload:
            print("Usage: /research <topic>")
            return False
        path = create_research_report(Path(args.workspace), payload)
        print(f"Research report: {path.relative_to(Path(args.workspace))}")
        return False
    if name == "/scaffold":
        parts = payload.split(maxsplit=1)
        if len(parts) != 2:
            print("Usage: /scaffold <agent|cli> <name>")
            return False
        path = create_scaffold(Path(args.workspace), parts[0], parts[1])
        print(f"Scaffold created: {path.relative_to(Path(args.workspace))}")
        return False
    if name == "/risk":
        path = create_risk_report(Path(args.workspace))
        print(f"Risk review: {path.relative_to(Path(args.workspace))}")
        return False
    if name == "/tasks":
        if not payload:
            print("Usage: /tasks <requirement>")
            return False
        path = create_task_plan(Path(args.workspace), payload)
        print(f"Task plan: {path.relative_to(Path(args.workspace))}")
        return False
    if name == "/parallel-run":
        if not payload:
            print("Usage: /parallel-run <requirement>")
            return False
        runner = ParallelCodexRunner(
            executor=CodexCliExecutionAdapter(idle_timeout_seconds=args.idle_timeout),
            max_workers=2,
        )
        report = runner.run(create_subtask_dag(payload), Path(args.workspace))
        print(f"Parallel status: {report.status}")
        for item in report.integrated_files:
            print(f"- {item}")
        return False
    if name in {"/test", "/quality"}:
        report = run_quality_checks(Path(args.workspace))
        print(f"Quality status: {report.status}")
        for check in report.checks:
            print(f"- {check['command']}: {check['status']}")
        return False
    if name == "/commit":
        report = create_commit(Path(args.workspace))
        print(f"Commit status: {report.status}")
        if report.commit:
            print(f"Commit: {report.commit}")
        return False
    if name == "/assets-extract":
        if not payload:
            print("Usage: /assets-extract <intent>")
            return False
        report = extract_reusable_assets(Path(args.workspace), payload)
        print(f"Assets status: {report.status}")
        for item in report.assets:
            print(f"- {item['path']} from {item['source']}")
        return False
    if name == "/assets-search":
        if not payload:
            print("Usage: /assets-search <query>")
            return False
        results = find_reusable_assets(Path(args.workspace), payload)
        if not results:
            print("No reusable assets found.")
            return False
        for item in results:
            print(f"- {item['intent']} -> .devclaw/assets/{item['path']}")
        return False
    if name == "/feedback":
        if not payload:
            print("Usage: /feedback <content>")
            return False
        item = add_feedback(Path(args.workspace), payload)
        print(f"Feedback recorded: #{item.id} {item.feedback_type} {item.severity}")
        return False
    if name == "/feedback-list":
        items = list_feedback(Path(args.workspace))
        if not items:
            print("No feedback found.")
            return False
        for item in items:
            print(f"#{item.id} [{item.feedback_type}/{item.severity}] {item.description}")
        return False
    if name == "/feedback-run":
        if not payload.isdigit():
            print("Usage: /feedback-run <id>")
            return False
        item = get_feedback(Path(args.workspace), int(payload))
        if item is None:
            print(f"Feedback not found: {payload}")
            return False
        run_args = argparse.Namespace(
            intent=append_attachments_to_intent(
                f"Address feedback #{item.id}: {item.description}",
                pending_attachments,
            ),
            workspace=args.workspace,
            executor=args.executor,
            verifier=args.verifier,
            max_rounds=args.max_rounds,
            idle_timeout=args.idle_timeout,
            progress=_print_progress_event,
        )
        _print_run_start(run_args.intent, run_args)
        if _run_and_report(run_args):
            pending_attachments.clear()
        return False
    if name == "/memory":
        memory = load_memory(Path(args.workspace))
        print("# Project Memory")
        print(f"Requests: {len(memory.request_history)}")
        print(f"Deliveries: {len(memory.delivery_history)}")
        print(f"Decisions: {len(memory.decisions)}")
        return False
    if name == "/history":
        memory = load_memory(Path(args.workspace))
        if not memory.request_history:
            print("No request history found.")
            return False
        for item in memory.request_history:
            print(f"- {item['timestamp']} {item['intent']}")
        return False
    if name == "/decisions":
        memory = load_memory(Path(args.workspace))
        print("# Architecture decisions")
        if not memory.decisions:
            print("No decisions recorded.")
            return False
        for item in memory.decisions:
            print(f"- {item['decision']} Reason: {item['reason']}")
        return False
    if name == "/sessions":
        print("# Sessions")
        sessions_dir = Path(args.workspace) / ".devclaw" / "sessions"
        manifests = sorted(sessions_dir.glob("*/manifest.json")) if sessions_dir.exists() else []
        if not manifests:
            print("No sessions found.")
            return False
        for manifest in manifests:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            print(f"- {data.get('completed_at', 'unknown')} {data.get('intent', manifest.parent.name)}")
        return False
    if name == "/diff":
        print("# Diff")
        result = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=Path(args.workspace),
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            print("Git diff unavailable for this project.")
            return False
        print(result.stdout.strip() or "No git diff.")
        return False
    if name == "/undo":
        manager = SessionManager(Path(args.workspace))
        try:
            manager.restore()
        except ValueError as error:
            print(f"Undo unavailable: {error}")
            return False
        print("Undo complete.")
        return False
    if name == "/artifacts":
        artifacts_dir = Path(args.workspace) / ".devclaw" / "artifacts"
        delivery_dir = Path(args.workspace) / ".devclaw" / "delivery"
        if not artifacts_dir.exists() and not delivery_dir.exists():
            print("No artifacts found.")
            return False
        for base in [artifacts_dir, delivery_dir]:
            if not base.exists():
                continue
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    print(path.relative_to(Path(args.workspace)))
        return False
    if name == "/clear":
        print("-" * 48)
        return False
    if name == "/run":
        if not payload:
            print("Usage: /run <product or Agent requirement>")
            return False
        run_args = argparse.Namespace(
            intent=append_attachments_to_intent(payload, pending_attachments),
            workspace=args.workspace,
            executor=args.executor,
            verifier=args.verifier,
            max_rounds=args.max_rounds,
            idle_timeout=args.idle_timeout,
            progress=_print_progress_event,
        )
        _print_run_start(payload, run_args)
        if _run_and_report(run_args):
            pending_attachments.clear()
        return False

    print(f"Unknown command: {name}")
    print("Type /help for available commands.")
    return False


def _is_slash_command_token(value: str) -> bool:
    return value in {
        "/exit",
        "/quit",
        "/q",
        "/help",
        "/?",
        "/status",
        "/config",
        "/paste-image",
        "/attach",
        "/attachments",
        "/refresh-context",
        "/context",
        "/report",
        "/research",
        "/scaffold",
        "/risk",
        "/tasks",
        "/parallel-run",
        "/test",
        "/quality",
        "/commit",
        "/assets-extract",
        "/assets-search",
        "/feedback",
        "/feedback-list",
        "/feedback-run",
        "/memory",
        "/history",
        "/decisions",
        "/sessions",
        "/diff",
        "/undo",
        "/artifacts",
        "/clear",
        "/run",
    }
