import subprocess
import time
from pathlib import Path

from devclaw.adapters.tool_runner import run_tool_with_idle_monitor


def test_tool_runner_allows_long_running_process_with_continuous_output(tmp_path):
    result = run_tool_with_idle_monitor(
        [
            "python3",
            "-c",
            "import time\nfor i in range(3):\n print(f'tick {i}', flush=True)\n time.sleep(0.2)",
        ],
        cwd=tmp_path,
        idle_timeout_seconds=1,
    )

    assert result.returncode == 0
    assert "tick 2" in result.stdout


def test_tool_runner_kills_process_after_idle_timeout(tmp_path):
    start = time.time()
    try:
        run_tool_with_idle_monitor(
            ["python3", "-c", "import time; time.sleep(5)"],
            cwd=tmp_path,
            idle_timeout_seconds=0.2,
        )
    except TimeoutError as error:
        assert "no output" in str(error).lower()
        assert time.time() - start < 3
    else:
        raise AssertionError("expected TimeoutError")


def test_tool_runner_passes_custom_environment(tmp_path):
    result = run_tool_with_idle_monitor(
        [
            "python3",
            "-c",
            "import os; print(os.environ['DEVCLAW_TEST_ENV'])",
        ],
        cwd=tmp_path,
        idle_timeout_seconds=1,
        env={"DEVCLAW_TEST_ENV": "custom"},
    )

    assert result.stdout.strip() == "custom"


def test_tool_runner_closes_stdin_so_tools_cannot_wait_for_interactive_confirmation(tmp_path):
    result = run_tool_with_idle_monitor(
        [
            "python3",
            "-c",
            "import sys; data = sys.stdin.read(); print('stdin-closed' if data == '' else 'stdin-open')",
        ],
        cwd=tmp_path,
        idle_timeout_seconds=1,
    )

    assert result.stdout.strip() == "stdin-closed"


def test_tool_runner_launches_process_with_devnull_stdin(monkeypatch, tmp_path):
    calls = []
    original_popen = subprocess.Popen

    def recording_popen(*args, **kwargs):
        calls.append(kwargs)
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", recording_popen)

    run_tool_with_idle_monitor(
        ["python3", "-c", "print('ok')"],
        cwd=Path(tmp_path),
        idle_timeout_seconds=1,
    )

    assert calls[0]["stdin"] == subprocess.DEVNULL


def test_tool_runner_streams_stdout_and_stderr_chunks_to_progress_callback(tmp_path):
    chunks: list[tuple[str, str]] = []

    result = run_tool_with_idle_monitor(
        [
            "python3",
            "-c",
            "import sys\nprint('out-1', flush=True)\nprint('err-1', file=sys.stderr, flush=True)",
        ],
        cwd=tmp_path,
        idle_timeout_seconds=1,
        on_output=lambda stream, chunk: chunks.append((stream, chunk)),
    )

    assert result.returncode == 0
    assert ("stdout", "out-1\n") in chunks
    assert ("stderr", "err-1\n") in chunks
