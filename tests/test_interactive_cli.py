import os
import pty
import select
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace


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
    assert "DevClaw interactive" in result.stdout
    assert "Project:" in result.stdout
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
    assert "Project:" in result.stdout


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
    assert "Project:" in result.stdout


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
    assert "Accepted requirement." in output
    assert "Codex implementation" in output
    assert "Deepseek QA" in output
    assert "[implementation] Codex Implementation Agent: started" in output
    assert "[verification] Deepseek QA Agent: started" in output
    assert "delivered" in output


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
    assert "[implementation] Codex Implementation Agent: error - Build failed" in output
    assert "stderr:" not in output


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
