"""Deterministic subprocess execution for harness invocations.

Captures stdout/stderr, monitors idle output, enforces timeouts, and
normalizes failures into the harness error taxonomy.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from metacoding.errors import HarnessCommandMissing
from metacoding.models import now_utc

POLL_INTERVAL_SECONDS = 0.05
#: Grace period after a kill signal before falling back to kill -9.
TERMINATE_GRACE_SECONDS = 5.0


@dataclass(frozen=True)
class CommandResult:
    """Everything the host knows about one harness invocation."""

    command: list[str]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    started_at: str
    finished_at: str
    duration_seconds: float
    timed_out: bool
    idle_timeout_seconds: float

    def metadata(self) -> dict:
        """Serializable command metadata for transcripts."""
        return {
            "command": list(self.command),
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "timed_out": self.timed_out,
            "idle_timeout_seconds": self.idle_timeout_seconds,
        }


class ProcessRunner:
    """Runs one harness command at a time with idle-output monitoring."""

    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        idle_timeout_seconds: float = 900.0,
        env: dict[str, str] | None = None,
        on_output: Callable[[str, str], None] | None = None,
    ) -> CommandResult:
        started_at = now_utc()
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env if env is not None else None,
            )
        except FileNotFoundError as exc:
            raise HarnessCommandMissing(
                f"harness command not found: {command[0]!r} "
                f"(configure [harness.*] command in .metacoding/config.toml)"
            ) from exc

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        last_activity = time.monotonic()
        activity_lock = threading.Lock()

        def pump(stream, chunks: list[str], name: str) -> None:
            nonlocal last_activity
            try:
                for chunk in stream:
                    chunks.append(chunk)
                    with activity_lock:
                        last_activity = time.monotonic()
                    if on_output is not None:
                        try:
                            on_output(chunk, name)
                        except Exception:  # pragma: no cover - observer errors must not kill the run
                            pass
            finally:
                stream.close()

        threads = [
            threading.Thread(target=pump, args=(process.stdout, stdout_chunks, "stdout"), daemon=True),
            threading.Thread(target=pump, args=(process.stderr, stderr_chunks, "stderr"), daemon=True),
        ]
        for thread in threads:
            thread.start()

        timed_out = False
        try:
            while process.poll() is None:
                with activity_lock:
                    idle_for = time.monotonic() - last_activity
                if idle_for > idle_timeout_seconds:
                    timed_out = True
                    self._terminate(process)
                    break
                time.sleep(POLL_INTERVAL_SECONDS)
        except BaseException:
            # KeyboardInterrupt or other host-side interruption: stop the child.
            self._terminate(process)
            raise
        finally:
            for thread in threads:
                thread.join(timeout=TERMINATE_GRACE_SECONDS)

        exit_code = process.returncode if process.returncode is not None else -9
        return CommandResult(
            command=list(command),
            cwd=str(cwd),
            exit_code=exit_code,
            stdout="".join(stdout_chunks),
            stderr="".join(stderr_chunks),
            started_at=started_at,
            finished_at=now_utc(),
            duration_seconds=time.monotonic() - started,
            timed_out=timed_out,
            idle_timeout_seconds=idle_timeout_seconds,
        )

    @staticmethod
    def _terminate(process: subprocess.Popen) -> None:
        try:
            process.terminate()
            try:
                process.wait(timeout=TERMINATE_GRACE_SECONDS)
            except subprocess.TimeoutExpired:  # pragma: no cover - stubborn child
                process.kill()
                process.wait(timeout=TERMINATE_GRACE_SECONDS)
        except OSError:  # pragma: no cover - process already gone
            pass


def kill_process_tree(pid: int) -> None:  # pragma: no cover - helper for operators
    """Best-effort termination of a stray harness process."""
    try:
        os.kill(pid, 15)
    except OSError:
        pass
