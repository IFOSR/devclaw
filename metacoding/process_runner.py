"""Deterministic subprocess execution for harness invocation.

Captures stdout/stderr with a memory cap, monitors idle output, enforces
timeouts, kills the whole process group, and normalizes failures into the
harness error taxonomy.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from metacoding.errors import HarnessCommandMissing
from metacoding.models import now_utc

POLL_INTERVAL_SECONDS = 0.05
#: Grace period after a kill signal before falling back to SIGKILL.
TERMINATE_GRACE_SECONDS = 5.0
#: Rolling per-stream capture cap (bytes). Older output is dropped first.
MAX_STREAM_BYTES = 5_000_000


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
    truncated: bool = False

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
            "truncated": self.truncated,
        }


class _CappedBuffer:
    """Accumulates text chunks while bounding total memory."""

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.chunks: list[str] = []
        self.total = 0
        self.dropped = 0

    def append(self, chunk: str) -> None:
        size = len(chunk.encode("utf-8", errors="replace"))
        self.chunks.append(chunk)
        self.total += size
        while self.total > self.cap and len(self.chunks) > 1:
            removed = self.chunks.pop(0)
            removed_size = len(removed.encode("utf-8", errors="replace"))
            self.total -= removed_size
            self.dropped += removed_size
        if self.total > self.cap and len(self.chunks) == 1:
            # A single oversized chunk: keep only its tail within the cap.
            data = self.chunks[0].encode("utf-8", errors="replace")
            keep = data[-self.cap :]
            self.dropped += len(data) - len(keep)
            self.chunks = [keep.decode("utf-8", errors="replace")]
            self.total = len(keep)

    def text(self) -> str:
        prefix = (
            f"[... {self.dropped} earlier bytes dropped by capture cap ...]\n"
            if self.dropped
            else ""
        )
        return prefix + "".join(self.chunks)


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
        max_stream_bytes: int = MAX_STREAM_BYTES,
    ) -> CommandResult:
        started_at = now_utc()
        started = time.monotonic()
        try:
            # New session/process group so we can kill harness child trees.
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env if env is not None else None,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise HarnessCommandMissing(
                f"harness command not found: {command[0]!r} "
                f"(configure [harness.*] command in .metacoding/config.toml)"
            ) from exc

        stdout_buffer = _CappedBuffer(max_stream_bytes)
        stderr_buffer = _CappedBuffer(max_stream_bytes)
        last_activity = time.monotonic()
        activity_lock = threading.Lock()

        def pump(stream, buffer: _CappedBuffer, name: str) -> None:
            nonlocal last_activity
            try:
                for chunk in stream:
                    buffer.append(chunk)
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
            threading.Thread(
                target=pump, args=(process.stdout, stdout_buffer, "stdout"), daemon=True
            ),
            threading.Thread(
                target=pump, args=(process.stderr, stderr_buffer, "stderr"), daemon=True
            ),
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
                    self._terminate_group(process)
                    break
                time.sleep(POLL_INTERVAL_SECONDS)
        except BaseException:
            # KeyboardInterrupt or other host-side interruption: stop the tree.
            self._terminate_group(process)
            raise
        finally:
            for thread in threads:
                thread.join(timeout=TERMINATE_GRACE_SECONDS)

        exit_code = process.returncode if process.returncode is not None else -9
        truncated = bool(stdout_buffer.dropped or stderr_buffer.dropped)
        return CommandResult(
            command=list(command),
            cwd=str(cwd),
            exit_code=exit_code,
            stdout=stdout_buffer.text(),
            stderr=stderr_buffer.text(),
            started_at=started_at,
            finished_at=now_utc(),
            duration_seconds=time.monotonic() - started,
            timed_out=timed_out,
            idle_timeout_seconds=idle_timeout_seconds,
            truncated=truncated,
        )

    @staticmethod
    def _terminate_group(process: subprocess.Popen) -> None:
        """Terminate the process and everything it spawned."""
        try:
            group = os.getpgid(process.pid)
        except OSError:
            group = None
        try:
            if group is not None and group != os.getpgid(0):
                try:
                    os.killpg(group, signal.SIGTERM)
                except OSError:
                    process.terminate()
            else:
                process.terminate()
            try:
                process.wait(timeout=TERMINATE_GRACE_SECONDS)
            except subprocess.TimeoutExpired:  # pragma: no cover - stubborn child
                if group is not None:
                    try:
                        os.killpg(group, signal.SIGKILL)
                    except OSError:
                        process.kill()
                else:
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
