"""Project-level lock ensuring one active MetaCoding run per project.

The lock file ``.metacoding/active-run.lock`` is created atomically
(O_CREAT|O_EXCL) and stores the owning PID, host, run id, and acquisition
time. Mutations of an existing lock compare-and-swap through ``flock``:

- a live owner holds an exclusive ``flock`` for the whole run, so a
  concurrent stale-takeover attempt fails the non-blocking ``flock`` and
  never stomps a freshly created lock;
- takeover of a lock whose owner is dead happens under the ``flock``, so
  two racing takeovers cannot both win;
- release verifies the file still belongs to us before unlinking, so a
  former owner can never delete a successor's lock.
"""

from __future__ import annotations

import fcntl
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


class LockHandle:
    """An owned lock: open fd plus exclusive flock for the run's lifetime."""

    def __init__(self, info: LockInfo, path: Path, fd: int, stale_replaced: bool) -> None:
        self.info = info
        self.path = path
        self.fd = fd
        self.stale_replaced = stale_replaced
        self._released = False

    def retarget(self, run_id: str) -> None:
        """Re-label the lock we own with the real run id."""
        if self._released:
            raise LockError("cannot retarget a released lock")
        self.info = LockInfo(
            run_id=run_id,
            pid=self.info.pid,
            host=self.info.host,
            acquired_at=self.info.acquired_at,
        )
        _rewrite_fd(self.fd, self.info)

    def release(self) -> bool:
        """Unlink the lock if it is still ours; drop the flock either way."""
        if self._released:
            return False
        self._released = True
        try:
            current = _read_path(self.path)
            if current is None or current.pid != self.info.pid or (
                self.info.run_id and current.run_id != self.info.run_id
            ):
                # Someone else owns the file now; never delete their lock.
                return False
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError:
            return False
        finally:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            except OSError:  # pragma: no cover - fd already closed
                pass
            os.close(self.fd)


def lock_path(project_root: Path) -> Path:
    return Path(project_root) / LOCK_FILENAME


def _read_path(path: Path) -> LockInfo | None:
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


def read_lock(project_root: Path) -> LockInfo | None:
    """Return lock metadata, ``None`` when no lock exists."""
    return _read_path(lock_path(project_root))


def _rewrite_fd(fd: int, info: LockInfo) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    payload = json.dumps(info.to_dict(), indent=2) + "\n"
    os.write(fd, payload.encode("utf-8"))
    os.fsync(fd)


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o644)
    except FileExistsError:
        # Existing lock: mutate only under an exclusive flock (CAS).
        try:
            fd = os.open(path, os.O_RDWR)
        except FileNotFoundError:
            # Lost a race with a releasing owner: retry creation once.
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o644)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _rewrite_fd(fd, info)
            return LockHandle(info, path, fd, stale_replaced=False)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            current = read_lock(root)
            _raise_busy(root, path, current, note="another process is locking it")
        current = read_lock(root)
        stale = current is None or not _process_alive(current.pid)
        if stale and allow_stale_replacement:
            _rewrite_fd(fd, info)
            return LockHandle(info, path, fd, stale_replaced=True)
        os.close(fd)
        _raise_busy(root, path, current)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    _rewrite_fd(fd, info)
    return LockHandle(info, path, fd, stale_replaced=False)


def _raise_busy(root: Path, path: Path, current: LockInfo | None, note: str = "") -> None:
    detail = f" ({note})" if note else ""
    message = (
        f"a MetaCoding run is already active for this project "
        f"(run-id: {current.run_id if current else 'unknown'}, "
        f"pid: {current.pid if current else '?'}, "
        f"host: {current.host if current else '?'}){detail}. "
        f"If that process has exited, remove {path} or rerun to replace the stale lock."
    )
    raise LockError(
        message,
        lock_path=str(path),
        run_id=current.run_id if current else "",
        pid=current.pid if current else None,
        host=current.host if current else "",
    )


def release_lock(
    project_root: Path,
    *,
    expected_pid: int,
    expected_run_id: str,
) -> bool:
    """Unlink the lock only when it still belongs to ``expected_*``.

    CAS semantics: the file is opened, exclusively flocked, re-read, and
    verified before unlinking, so a racing owner change can never cause the
    wrong lock to be deleted. Both owner fields are required on purpose —
    there is no safe unconditional release.
    """
    path = lock_path(project_root)
    try:
        fd = os.open(path, os.O_RDWR)
    except FileNotFoundError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False  # someone else is mutating or owning it
        current = _read_path(path)
        if current is None or current.pid != expected_pid or current.run_id != expected_run_id:
            return False
        try:
            path.unlink()
            return True
        except FileNotFoundError:  # pragma: no cover - racing release
            return False
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:  # pragma: no cover
            pass
        os.close(fd)


def update_lock_run_id(project_root: Path, run_id: str) -> None:
    """Retarget a lock we already own (legacy helper for direct callers)."""
    path = lock_path(project_root)
    existing = read_lock(project_root)
    if existing is None or existing.pid != os.getpid():
        return
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:  # pragma: no cover
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _rewrite_fd(fd, LockInfo(run_id=run_id, pid=existing.pid, host=existing.host,
                                 acquired_at=existing.acquired_at))
    finally:
        os.close(fd)


# Kept for import compatibility; callers must migrate to LockHandle.release.
_ = update_lock_run_id


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
        if self.handle is not None:
            self.handle.release()
