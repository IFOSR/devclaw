"""Subprocess execution: capture, idle timeout, and error classification."""

from __future__ import annotations

import sys
import time

import pytest

from metacoding.errors import HarnessCommandMissing
from metacoding.process_runner import CommandResult, ProcessRunner


def test_run_captures_stdout_stderr_and_exit_code(tmp_path) -> None:
    runner = ProcessRunner()
    result = runner.run(
        [
            sys.executable,
            "-c",
            "import sys; print('out'); print('err', file=sys.stderr); sys.exit(0)",
        ],
        cwd=tmp_path,
    )
    assert isinstance(result, CommandResult)
    assert result.exit_code == 0
    assert "out" in result.stdout
    assert "err" in result.stderr
    assert result.timed_out is False
    assert result.started_at.endswith("Z") and result.finished_at.endswith("Z")
    assert result.duration_seconds >= 0


def test_run_records_nonzero_exit(tmp_path) -> None:
    result = ProcessRunner().run(
        [sys.executable, "-c", "import sys; sys.exit(3)"], cwd=tmp_path
    )
    assert result.exit_code == 3
    assert result.timed_out is False


def test_missing_command_raises_harness_command_missing(tmp_path) -> None:
    with pytest.raises(HarnessCommandMissing):
        ProcessRunner().run(["/nonexistent/metacoding-harness"], cwd=tmp_path)


def test_idle_timeout_kills_silent_process(tmp_path) -> None:
    started = time.monotonic()
    result = ProcessRunner().run(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        idle_timeout_seconds=0.5,
    )
    elapsed = time.monotonic() - started
    assert result.timed_out is True
    assert result.exit_code != 0
    assert elapsed < 10


def test_ongoing_output_prevents_idle_timeout(tmp_path) -> None:
    result = ProcessRunner().run(
        [
            sys.executable,
            "-c",
            "import time\nfor _ in range(4):\n    print('tick', flush=True)\n    time.sleep(0.2)",
        ],
        cwd=tmp_path,
        idle_timeout_seconds=0.5,
    )
    assert result.timed_out is False
    assert result.exit_code == 0
    assert result.stdout.count("tick") == 4


def test_output_callback_receives_progress(tmp_path) -> None:
    chunks: list[str] = []
    ProcessRunner().run(
        [sys.executable, "-c", "print('alpha'); print('beta')"],
        cwd=tmp_path,
        on_output=lambda text, stream: chunks.append(text) if stream == "stdout" else None,
    )
    joined = "".join(chunks)
    assert "alpha" in joined and "beta" in joined


def test_signal_death_records_negative_exit(tmp_path) -> None:
    result = ProcessRunner().run(
        [sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"],
        cwd=tmp_path,
    )
    assert result.exit_code == -15
    assert result.timed_out is False
