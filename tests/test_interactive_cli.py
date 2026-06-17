import os
import pty
import select
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace


def test_redraw_input_line_uses_display_columns_for_wide_characters(capsys):
    from devclaw.cli import _redraw_input_line

    _redraw_input_line([], list("当前加速"), 2)

    output = capsys.readouterr().out
    assert output.endswith("\033[4D")


def test_default_cli_without_subcommand_runs_interactive_session(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "my-product"
    project.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "devclaw",
        ],
        input="/status\n/exit\n",
        text=True,
        capture_output=True,
        check=False,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
    )

    assert result.returncode == 0, result.stderr
    assert "DevClaw" in result.stdout
    assert "Project" in result.stdout
    assert "Mode" in result.stdout
    assert "Try:" in result.stdout
    assert "Ctrl+V" in result.stdout
    assert "Slash commands:" not in result.stdout
    assert "bye" in result.stdout.lower()


def test_interactive_slash_help_lists_builtin_commands(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "my-product"
    project.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "devclaw"],
        input="/help\n/exit\n",
        text=True,
        capture_output=True,
        check=False,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
    )

    assert result.returncode == 0, result.stderr
    assert "Core" in result.stdout
    assert "Workflow" in result.stdout
    assert "Project Memory" in result.stdout
    assert "Utilities" in result.stdout
    assert "/exit" in result.stdout
    assert "/help" in result.stdout
    assert "/status" in result.stdout
    assert "/report" in result.stdout
    assert "/artifacts" in result.stdout


def test_interactive_report_and_artifacts_commands_show_latest_outputs(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "my-product"
    project.mkdir()
    metadata = project / ".devclaw"
    (metadata / "artifacts").mkdir(parents=True)
    (metadata / "final-delivery-report.json").write_text(
        '{"delivery_status":"delivered"}', encoding="utf-8"
    )
    (metadata / "artifacts" / "product-research-report.md").write_text("research", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "devclaw"],
        input="/report\n/artifacts\n/exit\n",
        text=True,
        capture_output=True,
        check=False,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
    )

    assert result.returncode == 0, result.stderr
    assert "delivery_status" in result.stdout
    assert "product-research-report.md" in result.stdout


def test_slash_exit_is_required_to_exit_without_running_agents(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "my-product"
    project.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "devclaw"],
        input="/status\n/exit\n",
        text=True,
        capture_output=True,
        check=False,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
    )

    assert result.returncode == 0, result.stderr
    assert "Project" in result.stdout
    assert "Root" in result.stdout


def test_cli_runs_single_slash_command_non_interactively(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "my-product"
    project.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "devclaw", "/status"],
        text=True,
        capture_output=True,
        check=False,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "Project" in result.stdout
    assert "Root" in result.stdout


def test_cli_lists_parallel_run_command_in_help(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "my-product"
    project.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "devclaw", "/help"],
        text=True,
        capture_output=True,
        check=False,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "/parallel-run" in result.stdout


def test_interactive_prints_progress_immediately_after_requirement(monkeypatch, capsys, tmp_path: Path):
    from devclaw import cli

    inputs = iter(["Build a dinosaur timeline", "/exit"])

    def fake_input(prompt: str) -> str:
        print(prompt, end="")
        return next(inputs)

    def fake_run(args):
        args.progress(
            {
                "stage": "implementation",
                "agent": "Codex Implementation Agent",
                "status": "started",
                "message": "Round 1",
                "step": "9",
                "total_steps": "15",
                "provider": "codex",
                "depends_on": "8 upstream output(s)",
                "output_stage": "implementation",
                "artifact": "Codex CLI Execution",
            }
        )
        args.progress(
            {
                "stage": "verification",
                "agent": "Deepseek QA Agent",
                "status": "started",
                "message": "Round 1",
            }
        )
        return SimpleNamespace(
            final_report=SimpleNamespace(delivery_status="delivered"),
            workspace=tmp_path,
        )

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(cli, "_run", fake_run)

    code = cli._interactive(
        SimpleNamespace(
            workspace=str(tmp_path),
            executor="codex",
            verifier="deepseek",
            max_rounds=3,
            idle_timeout=900,
        )
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "◇ Requirement  Build a dinosaur timeline" in output
    assert "◇ Sequential workflow" in output
    assert "default R&D loop is not parallel" in output
    assert "Planned order" in output
    assert "Codex Implementation Agent" in output
    assert "Deepseek QA Agent" in output
    assert "09/15 Codex Implementation Agent [codex]" in output
    assert "waits for: 8 upstream output(s)" in output
    assert "→ Implementation" in output
    assert "→ Verification" in output
    assert "delivered" in output


def test_interactive_paste_image_attaches_clipboard_image_to_next_requirement(monkeypatch, capsys, tmp_path: Path):
    from devclaw import cli

    captured: dict[str, str] = {}
    inputs = iter(["/paste-image right panel is clipped", "Fix the page layout", "/exit"])

    def fake_input(prompt: str) -> str:
        print(prompt, end="")
        return next(inputs)

    def fake_paste(workspace: Path, note: str):
        return cli.Attachment(
            path=".devclaw/attachments/pending/clipboard.png",
            media_type="image/png",
            note=note,
            source="clipboard",
        )

    def fake_run(args):
        captured["intent"] = args.intent
        return SimpleNamespace(
            final_report=SimpleNamespace(delivery_status="delivered"),
            workspace=tmp_path,
        )

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(cli, "paste_clipboard_image", fake_paste)
    monkeypatch.setattr(cli, "_run", fake_run)

    code = cli._interactive(
        SimpleNamespace(
            workspace=str(tmp_path),
            executor="codex",
            verifier="deepseek",
            max_rounds=3,
            idle_timeout=900,
        )
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "Image attached" in output
    assert "1 pending" in output
    assert "devclaw [1 image] ›" in output
    assert "Fix the page layout" in captured["intent"]
    assert "Attached screenshots" in captured["intent"]
    assert ".devclaw/attachments/pending/clipboard.png" in captured["intent"]
    assert "right panel is clipped" in captured["intent"]


def test_interactive_persists_requirement_history_before_run_crashes(monkeypatch, tmp_path: Path):
    from devclaw import cli

    inputs = iter(["Fix the archive crash", "/exit"])

    def fake_input(prompt: str) -> str:
        return next(inputs)

    def fake_run(args):
        raise RuntimeError("archive failed")

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(cli, "_run", fake_run)

    code = cli._interactive(
        SimpleNamespace(
            workspace=str(tmp_path),
            executor="codex",
            verifier="deepseek",
            max_rounds=3,
            idle_timeout=900,
        )
    )

    history = tmp_path / ".devclaw" / "history" / "input-history.txt"
    assert code == 0
    assert history.exists()
    assert "Fix the archive crash" in history.read_text(encoding="utf-8")


def test_interactive_run_failure_does_not_exit_session(monkeypatch, capsys, tmp_path: Path):
    from devclaw import cli

    inputs = iter(["Fix a failing workflow", "/exit"])

    def fake_input(prompt: str) -> str:
        print(prompt, end="")
        return next(inputs)

    def fake_run(args):
        raise RuntimeError("TOOL_RETRYABLE: Codex concurrency limit exceeded")

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(cli, "_run", fake_run)

    code = cli._interactive(
        SimpleNamespace(
            workspace=str(tmp_path),
            executor="codex",
            verifier="deepseek",
            max_rounds=3,
            idle_timeout=900,
        )
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "Task failed" in output
    assert "Codex concurrency limit exceeded" in output
    assert "DevClaw is still running" in output
    assert "Retryable tool error" in output
    assert "bye" in output.lower()


def test_interactive_run_command_failure_does_not_clear_pending_attachments(
    monkeypatch, capsys, tmp_path: Path
):
    from devclaw import cli

    inputs = iter(["/paste-image clipped chart", "/run Fix the chart", "/attachments", "/exit"])

    def fake_input(prompt: str) -> str:
        print(prompt, end="")
        return next(inputs)

    def fake_paste(workspace: Path, note: str):
        return cli.Attachment(
            path=".devclaw/attachments/pending/chart.png",
            media_type="image/png",
            note=note,
            source="clipboard",
        )

    def fake_run(args):
        raise RuntimeError("implementation failed")

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(cli, "paste_clipboard_image", fake_paste)
    monkeypatch.setattr(cli, "_run", fake_run)

    code = cli._interactive(
        SimpleNamespace(
            workspace=str(tmp_path),
            executor="codex",
            verifier="deepseek",
            max_rounds=3,
            idle_timeout=900,
        )
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "Task failed" in output
    assert "implementation failed" in output
    assert "Pending attachments" in output
    assert ".devclaw/attachments/pending/chart.png" in output
    assert "bye" in output.lower()


def test_interactive_feedback_run_failure_does_not_exit_session(
    monkeypatch, capsys, tmp_path: Path
):
    from devclaw import cli

    cli.add_feedback(tmp_path, "bug: export crashes")
    inputs = iter(["/feedback-run 1", "/exit"])

    def fake_input(prompt: str) -> str:
        print(prompt, end="")
        return next(inputs)

    def fake_run(args):
        raise RuntimeError("verification failed")

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(cli, "_run", fake_run)

    code = cli._interactive(
        SimpleNamespace(
            workspace=str(tmp_path),
            executor="codex",
            verifier="deepseek",
            max_rounds=3,
            idle_timeout=900,
        )
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "Task failed" in output
    assert "verification failed" in output
    assert "bye" in output.lower()


def test_progress_renderer_shows_only_milestones_not_raw_tool_logs(capsys):
    from devclaw.cli import _print_progress_event

    for message in [
        "stderr: codex",
        "stderr: I am creating tests and then implementing the script.",
        "stderr: exec",
        "stderr: /bin/zsh -lc 'python3 -m pytest -q' in /tmp/project",
        "stderr: succeeded in 221ms:",
        "stderr: # Brainstorming Ideas Into Designs",
        "stderr: +def noisy_diff():",
    ]:
        _print_progress_event(
            {
                "stage": "implementation",
                "agent": "Codex Implementation Agent",
                "status": "output",
                "message": message,
            }
        )
    _print_progress_event(
        {
            "stage": "implementation",
            "agent": "Codex Implementation Agent",
            "status": "milestone",
            "message": "Running implementation checks.",
        }
    )

    output = capsys.readouterr().out
    assert "Codex Implementation Agent" in output
    assert "Running implementation checks." in output
    assert "I am creating tests" not in output
    assert "python3 -m pytest -q" not in output
    assert "succeeded in 221ms" not in output
    assert "stderr:" not in output
    assert "Brainstorming Ideas" not in output
    assert "noisy_diff" not in output


def test_progress_renderer_shows_error_events_without_exposing_stderr(capsys):
    from devclaw.cli import _print_progress_event

    _print_progress_event(
        {
            "stage": "implementation",
            "agent": "Codex Implementation Agent",
            "status": "error",
            "message": "Build failed",
        }
    )

    output = capsys.readouterr().out
    assert "✕ Implementation" in output
    assert "Codex Implementation Agent · error" in output
    assert "Build failed" in output
    assert "stderr:" not in output


def test_progress_renderer_shows_duration_and_agent_mode(capsys):
    from devclaw.cli import _print_progress_event

    _print_progress_event(
        {
            "stage": "research",
            "agent": "Product Research Agent",
            "status": "completed",
            "message": "Product Research Report",
            "duration_seconds": "0.042",
            "mode": "local",
        }
    )
    _print_progress_event(
        {
            "stage": "implementation",
            "agent": "Codex Implementation Agent",
            "status": "completed",
            "message": "Round 1 finished",
            "duration_seconds": "12.4",
            "mode": "external",
        }
    )

    output = capsys.readouterr().out
    assert "local" in output
    assert "external" in output
    assert "in 0.04s" in output
    assert "in 12.40s" in output


def test_progress_renderer_shows_workflow_mode_and_reuse_counts(capsys):
    from devclaw.cli import _print_progress_event

    _print_progress_event(
        {
            "stage": "workflow",
            "agent": "Workflow Router",
            "status": "planned",
            "message": "Prior context exists and the request is a localized improvement.",
            "workflow_mode": "targeted-change",
            "running_roles": "9",
            "reused_roles": "6",
        }
    )

    output = capsys.readouterr().out
    assert "workflow mode: targeted-change" in output
    assert "roles: 9 running, 6 reused" in output


def test_progress_renderer_shows_compact_heartbeat(capsys):
    from devclaw.cli import _print_progress_event

    _print_progress_event(
        {
            "stage": "implementation",
            "agent": "Codex Implementation Agent",
            "status": "heartbeat",
            "message": "Still running; waiting for the tool to produce the next useful update.",
            "elapsed_seconds": "125.4",
        }
    )

    output = capsys.readouterr().out
    assert "still running" in output
    assert "2m 05s" in output
    assert "Codex Implementation Agent" in output


def test_interactive_tty_supports_arrow_key_line_editing(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "my-product"
    project.mkdir()
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "-m", "devclaw"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        close_fds=True,
    )
    os.close(slave_fd)
    try:
        output = _read_pty(master_fd, timeout_seconds=1.0)
        os.write(master_fd, b"/exit")
        os.write(master_fd, b"\x1b[D")
        os.write(master_fd, b"\x1b[C")
        os.write(master_fd, b"\n")
        output += _read_pty(master_fd, timeout_seconds=2.0)
        exited_after_arrow_keys = process.poll() is not None
        if not exited_after_arrow_keys:
            os.write(master_fd, b"/exit\n")
            output += _read_pty(master_fd, timeout_seconds=1.0)
        process.wait(timeout=2)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=2)
        os.close(master_fd)

    text = output.decode("utf-8", "replace")
    assert process.returncode == 0, text
    assert exited_after_arrow_keys, text
    assert "bye" in text.lower()
    assert "^[[D" not in text
    assert "^[[C" not in text
    assert "Unknown command" not in text


def test_interactive_tty_left_arrow_inserts_at_cursor(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "my-product"
    project.mkdir()
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "-m", "devclaw"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        close_fds=True,
    )
    os.close(slave_fd)
    try:
        output = _read_pty(master_fd, timeout_seconds=1.0)
        os.write(master_fd, b"/eit")
        os.write(master_fd, b"\x1b[D")
        os.write(master_fd, b"\x1b[D")
        os.write(master_fd, b"x\n")
        output += _read_pty(master_fd, timeout_seconds=2.0)
        process.wait(timeout=2)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=2)
        os.close(master_fd)

    text = output.decode("utf-8", "replace")
    assert process.returncode == 0, text
    assert "bye" in text.lower()
    assert "Unknown command" not in text


def test_interactive_tty_right_arrow_moves_cursor_before_backspace(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "my-product"
    project.mkdir()
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "-m", "devclaw"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        close_fds=True,
    )
    os.close(slave_fd)
    try:
        output = _read_pty(master_fd, timeout_seconds=1.0)
        os.write(master_fd, b"/exait")
        os.write(master_fd, b"\x1b[D")
        os.write(master_fd, b"\x1b[D")
        os.write(master_fd, b"\x1b[D")
        os.write(master_fd, b"\x1b[C")
        os.write(master_fd, b"\x7f\n")
        output += _read_pty(master_fd, timeout_seconds=2.0)
        process.wait(timeout=2)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=2)
        os.close(master_fd)

    text = output.decode("utf-8", "replace")
    assert process.returncode == 0, text
    assert "bye" in text.lower()
    assert "Unknown command" not in text


def test_interactive_tty_delete_removes_character_at_cursor(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "my-product"
    project.mkdir()
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "-m", "devclaw"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        close_fds=True,
    )
    os.close(slave_fd)
    try:
        output = _read_pty(master_fd, timeout_seconds=1.0)
        os.write(master_fd, b"/exxit")
        os.write(master_fd, b"\x1b[D")
        os.write(master_fd, b"\x1b[D")
        os.write(master_fd, b"\x1b[D")
        os.write(master_fd, b"\x1b[3~")
        os.write(master_fd, b"\n")
        output += _read_pty(master_fd, timeout_seconds=2.0)
        exited_after_delete = process.poll() is not None
        if not exited_after_delete:
            os.write(master_fd, b"/exit\n")
            output += _read_pty(master_fd, timeout_seconds=1.0)
        process.wait(timeout=2)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=2)
        os.close(master_fd)

    text = output.decode("utf-8", "replace")
    assert process.returncode == 0, text
    assert exited_after_delete, text
    assert "bye" in text.lower()
    assert "Unknown command" not in text
    assert "~" not in text


def test_interactive_tty_up_arrow_recalls_persisted_history(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "my-product"
    history_dir = project / ".devclaw" / "history"
    history_dir.mkdir(parents=True)
    (history_dir / "input-history.txt").write_text("/exit\n", encoding="utf-8")
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "-m", "devclaw"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        close_fds=True,
    )
    os.close(slave_fd)
    try:
        output = _read_pty(master_fd, timeout_seconds=1.0)
        os.write(master_fd, b"\x1b[A")
        output += _read_pty(master_fd, timeout_seconds=0.5)
        os.write(master_fd, b"\n")
        output += _read_pty(master_fd, timeout_seconds=2.0)
        process.wait(timeout=2)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=2)
        os.close(master_fd)

    text = output.decode("utf-8", "replace")
    assert process.returncode == 0, text
    assert "/exit" in text
    assert "bye" in text.lower()


def test_interactive_tty_application_cursor_up_arrow_recalls_history(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "my-product"
    history_dir = project / ".devclaw" / "history"
    history_dir.mkdir(parents=True)
    (history_dir / "input-history.txt").write_text("/exit\n", encoding="utf-8")
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "-m", "devclaw"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        close_fds=True,
    )
    os.close(slave_fd)
    try:
        output = _read_pty(master_fd, timeout_seconds=1.0)
        os.write(master_fd, b"\x1bOA")
        output += _read_pty(master_fd, timeout_seconds=0.5)
        os.write(master_fd, b"\n")
        output += _read_pty(master_fd, timeout_seconds=2.0)
        exited_after_up_arrow = process.poll() is not None
        if not exited_after_up_arrow:
            os.write(master_fd, b"/exit\n")
            output += _read_pty(master_fd, timeout_seconds=1.0)
        process.wait(timeout=2)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=2)
        os.close(master_fd)

    text = output.decode("utf-8", "replace")
    assert process.returncode == 0, text
    assert exited_after_up_arrow, text
    assert "/exit" in text
    assert "bye" in text.lower()


def _read_pty(fd: int, timeout_seconds: float) -> bytes:
    deadline = time.time() + timeout_seconds
    output = b""
    while time.time() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            continue
        try:
            output += os.read(fd, 4096)
        except OSError:
            break
    return output
