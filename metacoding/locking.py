"""Project-level lock ensuring one active MetaCoding run per project.

The lock file ``.metacoding/active-run.lock`` is created atomically and
stores the owning PID, host, run id, and acquisition time. Locks left by
processes that are no longer alive are detected as stale; locks held by
live processes are never overwritten.
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path

from metacoding.errors import LockError, PersistenceError
from metacoding.models import now_utc

LOCK_FILENAME = ".metacoding/active-run.lock"


@dataclass(frozen=True)
class LockInfo:
    run_id: str
    pid: int
    host: str
    acquired_at: str

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "pid": self.pid,
            "host": self.host,
            "acquired_at": self.acquired_at,
        }


@dataclass
class LockHandle:
    info: LockInfo
    stale_replaced: bool
    path: Path


def lock_path(project_root: Path) -> Path:
    return Path(project_root) / LOCK_FILENAME


def read_lock(project_root: Path) -> LockInfo | None:
    """Return lock metadata, ``None`` when no lock exists.

    A corrupt lock file is reported as :class:`PersistenceError` so callers
    can decide how to surface it; ``read_lock_or_none`` never hides real
    corruption silently.
    """
    path = lock_path(project_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersistenceError(f"cannot read project lock {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PersistenceError(f"project lock {path} is not a JSON object")
    try:
        return LockInfo(
            run_id=str(data["run_id"]),
            pid=int(data["pid"]),
            host=str(data["host"]),
            acquired_at=str(data.get("acquired_at", "")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PersistenceError(f"project lock {path} is malformed: {exc}") from exc


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _write_lock(path: Path, info: LockInfo) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(info.to_dict(), handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def acquire_lock(
    project_root: Path, run_id: str, *, allow_stale_replacement: bool = True
) -> LockHandle:
    """Acquire the project lock or fail with a readable :class:`LockError`."""
    root = Path(project_root)
    path = lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    info = LockInfo(
        run_id=run_id,
        pid=os.getpid(),
        host=socket.gethostname(),
        acquired_at=now_utc(),
    )

    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        existing = read_lock(root)
        stale = existing is None or not _process_alive(existing.pid)
        if stale and allow_stale_replacement:
            _write_lock(path, info)
            return LockHandle(info=info, stale_replaced=True, path=path)
        current_host = socket.gethostname()
        message = (
            f"a MetaCoding run is already active for this project "
            f"(run-id: {existing.run_id if existing else 'unknown'}, "
            f"pid: {existing.pid if existing else '?'}, "
            f"host: {existing.host if existing else '?'}). "
            f"If that process has exited, remove {path} or rerun to replace the stale lock."
        )
        raise LockError(
            message,
            lock_path=str(path),
            run_id=existing.run_id if existing else "",
            pid=existing.pid if existing else None,
            host=existing.host if existing else "",
        )
    else:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(info.to_dict(), handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return LockHandle(info=info, stale_replaced=False, path=path)


def release_lock(project_root: Path) -> None:
    path = lock_path(project_root)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def update_lock_run_id(project_root: Path, run_id: str) -> None:
    """Retarget a lock we already own to the real run id.

    Used because the lock is acquired before the run id exists.
    """
    path = lock_path(project_root)
    existing = read_lock(project_root)
    if existing is None or existing.pid != os.getpid():
        return
    _write_lock(path, LockInfo(run_id=run_id, pid=existing.pid, host=existing.host, acquired_at=existing.acquired_at))


class project_lock:
    """Context manager owning the lock for the duration of a run."""

    def __init__(self, project_root: Path, run_id: str) -> None:
        self._root = Path(project_root)
        self._run_id = run_id
        self.handle: LockHandle | None = None

    def __enter__(self) -> LockHandle:
        self.handle = acquire_lock(self._root, self._run_id)
        return self.handle

    def __exit__(self, exc_type, exc, tb) -> None:
        release_lock(self._root)
