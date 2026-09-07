"""Project lock behavior: mutual exclusion and stale lock handling."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from metacoding.errors import LockError
from metacoding.locking import (
    acquire_lock,
    project_lock,
    read_lock,
    release_lock,
)


def lock_path(root: Path) -> Path:
    return root / ".metacoding" / "active-run.lock"


def write_lock(root: Path, payload: dict) -> None:
    import json

    path = lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def dead_pid() -> int:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        stdout=subprocess.PIPE,
        text=True,
    )
    pid = int(proc.communicate()[0].strip())
    proc.wait()
    return pid


def live_pid() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])


def test_acquire_creates_lock_with_process_metadata(tmp_path: Path) -> None:
    with project_lock(tmp_path, "run-1") as handle:
        assert handle.info.run_id == "run-1"
        assert handle.info.pid == os.getpid()
        assert handle.info.host == socket.gethostname()
        assert handle.stale_replaced is False
        info = read_lock(tmp_path)
        assert info is not None and info.run_id == "run-1"
    assert read_lock(tmp_path) is None


def test_second_run_rejected_while_lock_held(tmp_path: Path) -> None:
    with project_lock(tmp_path, "run-1"):
        with pytest.raises(LockError) as excinfo:
            acquire_lock(tmp_path, "run-2")
        message = str(excinfo.value)
        assert "run-1" in message
        assert str(os.getpid()) in message
        assert excinfo.value.pid == os.getpid()


def test_release_allows_next_run(tmp_path: Path) -> None:
    acquire_lock(tmp_path, "run-1")
    release_lock(tmp_path)
    with project_lock(tmp_path, "run-2"):
        assert read_lock(tmp_path) is not None


def test_stale_lock_from_dead_process_is_replaced(tmp_path: Path) -> None:
    write_lock(
        tmp_path,
        {
            "run_id": "old-run",
            "pid": dead_pid(),
            "host": socket.gethostname(),
            "acquired_at": "2026-09-07T00:00:00Z",
        },
    )
    with project_lock(tmp_path, "new-run") as handle:
        assert handle.stale_replaced is True
        assert handle.info.run_id == "new-run"


def test_stale_replacement_can_be_refused(tmp_path: Path) -> None:
    write_lock(
        tmp_path,
        {
            "run_id": "old-run",
            "pid": dead_pid(),
            "host": socket.gethostname(),
            "acquired_at": "2026-09-07T00:00:00Z",
        },
    )
    with pytest.raises(LockError):
        acquire_lock(tmp_path, "new-run", allow_stale_replacement=False)


def test_live_foreign_process_lock_is_never_overwritten(tmp_path: Path) -> None:
    proc = live_pid()
    try:
        write_lock(
            tmp_path,
            {
                "run_id": "other-run",
                "pid": proc.pid,
                "host": socket.gethostname(),
                "acquired_at": "2026-09-07T00:00:00Z",
            },
        )
        with pytest.raises(LockError):
            acquire_lock(tmp_path, "new-run")
        # even with allow_stale_replacement=True
        with pytest.raises(LockError):
            acquire_lock(tmp_path, "new-run", allow_stale_replacement=True)
    finally:
        proc.kill()
        proc.wait()


def test_lock_error_reports_run_and_host(tmp_path: Path) -> None:
    with project_lock(tmp_path, "run-1"):
        try:
            acquire_lock(tmp_path, "run-2")
        except LockError as exc:
            assert exc.run_id == "run-1"
            assert exc.host == socket.gethostname()
            assert exc.lock_path.endswith("active-run.lock")
        else:  # pragma: no cover
            raise AssertionError("expected LockError")


def test_lock_context_manager_releases_on_exception(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        with project_lock(tmp_path, "run-1"):
            raise RuntimeError("boom")
    assert read_lock(tmp_path) is None


# --- CAS takeover and owner-verified release ------------------------------------------


def test_takeover_fails_while_another_process_holds_the_flock(tmp_path: Path) -> None:
    import json as _json

    path = lock_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A dead pid in the file, but a live process holds the flock on it:
    # the pid check alone would call it stale; the flock CAS must refuse.
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import fcntl, json, sys, time\n"
                f"path = {str(path)!r}\n"
                "with open(path, 'w') as f:\n"
                "    json.dump({'run_id': 'ghost', 'pid': 999999, "
                "'host': 'other-host', 'acquired_at': ''}, f)\n"
                "    f.flush()\n"
                "    fcntl.flock(f, fcntl.LOCK_EX)\n"
                "    print('locked', flush=True)\n"
                "    time.sleep(60)\n"
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        with pytest.raises(LockError):
            acquire_lock(tmp_path, "new-run", allow_stale_replacement=True)
    finally:
        holder.kill()
        holder.wait()


def test_release_never_deletes_a_successors_lock(tmp_path: Path) -> None:
    handle = acquire_lock(tmp_path, "old-run")
    # simulate takeover by someone else rewriting the file
    write_lock(
        tmp_path,
        {
            "run_id": "new-run",
            "pid": os.getpid() + 1,
            "host": socket.gethostname(),
            "acquired_at": "2026-09-07T00:00:00Z",
        },
    )
    assert handle.release() is False  # detected foreign content, kept the file
    assert read_lock(tmp_path) is not None
    assert read_lock(tmp_path).run_id == "new-run"


def test_release_lock_verifies_expected_owner(tmp_path: Path) -> None:
    with project_lock(tmp_path, "run-1"):
        # wrong expected pid: untouched
        assert release_lock(tmp_path, expected_pid=999999) is False
        assert read_lock(tmp_path) is not None
        # matching owner: removed
        assert release_lock(tmp_path, expected_pid=os.getpid()) is True
        assert read_lock(tmp_path) is None
