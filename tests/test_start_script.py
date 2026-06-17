import os
import subprocess
from pathlib import Path


SCRIPT = Path("scripts/devclaw")


def test_start_script_help_lists_commands():
    result = subprocess.run(
        ["bash", str(SCRIPT), "help"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "start" in result.stdout
    assert "stop" in result.stdout
    assert "restart" in result.stdout
    assert "chat" in result.stdout


def test_start_script_chat_opens_interactive_cli(tmp_path: Path):
    workspace = tmp_path / "runs"
    env = {
        **os.environ,
        "DEVCLAW_WORKSPACE": str(workspace),
    }

    result = subprocess.run(
        ["bash", str(SCRIPT), "chat"],
        input="/status\n/exit\n",
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "DevClaw" in result.stdout
    assert "Project" in result.stdout
    assert "Mode" in result.stdout
    assert "devclaw ›" in result.stdout


def test_stop_script_is_idempotent_without_running_process(tmp_path: Path):
    env = {
        **os.environ,
        "DEVCLAW_PID_FILE": str(tmp_path / "missing.pid"),
    }

    result = subprocess.run(
        ["bash", str(SCRIPT), "stop"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0
    assert "not running" in result.stdout.lower()


def test_start_script_status_is_user_usable(tmp_path: Path):
    env = {
        **os.environ,
        "DEVCLAW_PID_FILE": str(tmp_path / "missing.pid"),
    }

    result = subprocess.run(
        ["bash", str(SCRIPT), "status"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "not running" in result.stdout.lower()
