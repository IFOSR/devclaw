from __future__ import annotations

import fcntl
import os
import select
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class ToolExecutionResult:
    returncode: int
    stdout: str
    stderr: str


def run_tool_with_idle_monitor(
    cmd: list[str],
    cwd: Path,
    idle_timeout_seconds: float,
    env: dict[str, str] | None = None,
    on_output: Callable[[str, str], None] | None = None,
) -> ToolExecutionResult:
    process_env = None
    if env is not None:
        process_env = {**os.environ, **env}
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=process_env,
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    _set_nonblocking(process.stdout.fileno())
    _set_nonblocking(process.stderr.fileno())

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    last_output = time.monotonic()

    while True:
        ready, _, _ = select.select(
            [process.stdout, process.stderr],
            [],
            [],
            0.1,
        )
        saw_output = False
        for stream in ready:
            chunk = stream.read()
            if not chunk:
                continue
            saw_output = True
            if stream is process.stdout:
                stdout_parts.append(chunk)
                if on_output is not None:
                    on_output("stdout", chunk)
            else:
                stderr_parts.append(chunk)
                if on_output is not None:
                    on_output("stderr", chunk)
        if saw_output:
            last_output = time.monotonic()

        returncode = process.poll()
        if returncode is not None:
            stdout_parts.append(process.stdout.read() or "")
            stderr_parts.append(process.stderr.read() or "")
            return ToolExecutionResult(
                returncode=returncode,
                stdout="".join(stdout_parts),
                stderr="".join(stderr_parts),
            )

        if time.monotonic() - last_output > idle_timeout_seconds:
            process.kill()
            process.wait()
            raise TimeoutError(
                f"Tool produced no output for {idle_timeout_seconds} seconds."
            )


def _set_nonblocking(fd: int) -> None:
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
