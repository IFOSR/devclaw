from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from devclaw.adapters.execution import CodexCliExecutionAdapter
from devclaw.adapters.verification import DeepseekTuiVerificationAdapter
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
from devclaw.core.scaffold import create_scaffold
from devclaw.core.sessions import SessionManager
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


def _interactive(args: argparse.Namespace) -> int:
    _enable_line_editing()
    print("DevClaw interactive")
    print("Type a product/Agent requirement and press Enter.")
    print("Slash commands: /help, /status, /config, /context, /refresh-context, /memory, /history, /decisions, /research, /scaffold, /risk, /tasks, /parallel-run, /test, /quality, /commit, /assets-extract, /assets-search, /feedback, /feedback-list, /feedback-run, /report, /artifacts, /clear, /exit")
    while True:
        try:
            intent = input("devclaw> ").strip()
        except EOFError:
            print()
            print("bye")
            return 0

        if not intent:
            continue
        if intent.startswith("/"):
            should_exit = _handle_slash_command(intent, args)
            if should_exit:
                return 0
            continue

        run_args = argparse.Namespace(
            intent=intent,
            workspace=args.workspace,
            executor=args.executor,
            verifier=args.verifier,
            max_rounds=args.max_rounds,
            idle_timeout=args.idle_timeout,
            progress=_print_progress_event,
        )
        _print_run_start(intent, run_args)
        result = _run(run_args)
        print(f"{result.final_report.delivery_status}: {result.workspace}")


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
    print("Accepted requirement.")
    print(f"Workspace: {Path(args.workspace).resolve()}")
    print(f"Executor: Codex implementation ({args.executor})")
    print(f"Verifier: Deepseek QA ({args.verifier})")
    print(f"Idle timeout: {args.idle_timeout}s without Agent output")
    print(f"Requirement: {intent}")
    print("Running DevClaw loop: research -> product/design/architecture -> Codex implementation -> release/delivery -> Deepseek QA.")
    sys.stdout.flush()


def _print_progress_event(event: dict[str, str]) -> None:
    status = event.get("status", "unknown")
    stage = event.get("stage", "unknown")
    agent = event.get("agent", "unknown")
    message = event.get("message", "")
    if status == "output":
        return
    else:
        suffix = f" - {message}" if message else ""
        print(f"[{stage}] {agent}: {status}{suffix}")
    sys.stdout.flush()


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


def _handle_slash_command(command: str, args: argparse.Namespace) -> bool:
    name, _, rest = command.partition(" ")
    name = name.lower()
    payload = rest.strip()

    if name in {"/exit", "/quit", "/q"}:
        print("bye")
        return True
    if name in {"/help", "/?"}:
        print("Built-in slash commands:")
        print("  /help                 Show this help.")
        print("  /status               Show current project and adapter status.")
        print("  /config               Show runtime configuration.")
        print("  /context              Show latest project context summary.")
        print("  /refresh-context      Rescan and persist project context.")
        print("  /memory               Show project memory summary.")
        print("  /history              Show request history.")
        print("  /decisions            Show architecture decisions.")
        print("  /research <topic>     Create a project-aware research report.")
        print("  /scaffold <type> <name> Create an agent or CLI scaffold spec.")
        print("  /risk                 Create a risk review report.")
        print("  /tasks <requirement>  Create a task DAG plan.")
        print("  /parallel-run <requirement> Split a requirement and run parallel Codex subtasks.")
        print("  /test                 Run detected project tests.")
        print("  /quality              Show latest quality report, running checks if needed.")
        print("  /commit               Create a non-interactive git commit for current DevClaw delivery.")
        print("  /assets-extract <intent> Extract reusable assets from current project.")
        print("  /assets-search <query> Search reusable assets for a similar request.")
        print("  /feedback <content>   Record user feedback.")
        print("  /feedback-list        List recorded feedback.")
        print("  /feedback-run <id>    Run a feedback item as a DevClaw task.")
        print("  /sessions             Show previous DevClaw requests.")
        print("  /diff                 Show current git diff if available.")
        print("  /undo                 Restore project files from the latest DevClaw session snapshot.")
        print("  /report               Print the latest final delivery report.")
        print("  /artifacts            List latest Agent artifacts.")
        print("  /clear                Visually separate the current conversation.")
        print("  /run <requirement>    Run one requirement explicitly.")
        print("  /exit                 Exit DevClaw.")
        print("Natural language without '/' is always treated as a project requirement.")
        return False
    if name == "/status":
        print(f"Project: {Path(args.workspace).resolve()}")
        print(f"Metadata: {(Path(args.workspace) / '.devclaw').resolve()}")
        return False
    if name == "/config":
        print(f"workspace={args.workspace}")
        print(f"executor={args.executor}")
        print(f"verifier={args.verifier}")
        print(f"max_rounds={args.max_rounds}")
        print(f"idle_timeout={args.idle_timeout}")
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
            intent=f"Address feedback #{item.id}: {item.description}",
            workspace=args.workspace,
            executor=args.executor,
            verifier=args.verifier,
            max_rounds=args.max_rounds,
            idle_timeout=args.idle_timeout,
        )
        result = _run(run_args)
        print(f"{result.final_report.delivery_status}: {result.workspace}")
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
            intent=payload,
            workspace=args.workspace,
            executor=args.executor,
            verifier=args.verifier,
            max_rounds=args.max_rounds,
            idle_timeout=args.idle_timeout,
        )
        result = _run(run_args)
        print(f"{result.final_report.delivery_status}: {result.workspace}")
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
