from __future__ import annotations

import filecmp
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


IGNORED = {".devclaw", "__pycache__", ".pytest_cache", ".git", "node_modules"}


@dataclass(frozen=True)
class Session:
    session_id: str
    intent: str
    session_dir: Path
    snapshot_dir: Path
    base_revision: str | None = None


@dataclass(frozen=True)
class CompletedSession(Session):
    changed_files: list[str] | None = None
    manifest_path: Path | None = None


class SessionManager:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.sessions_dir = project_root / ".devclaw" / "sessions"

    def begin(self, intent: str) -> Session:
        session_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        session_dir = self.sessions_dir / session_id
        snapshot_dir = session_dir / "snapshot"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        _copy_project(self.project_root, snapshot_dir)
        session = Session(
            session_id=session_id,
            intent=intent,
            session_dir=session_dir,
            snapshot_dir=snapshot_dir,
            base_revision=_git_output(self.project_root, ["rev-parse", "HEAD"]),
        )
        self._write_current(session_id)
        return session

    def complete(self, session: Session) -> CompletedSession:
        changed_files = _changed_files(session.snapshot_dir, self.project_root)
        manifest = {
            "session_id": session.session_id,
            "intent": session.intent,
            "changed_files": changed_files,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "git_isolation": "snapshot" if session.base_revision else "none",
            "base_revision": session.base_revision,
            "diff_stat": _git_output(self.project_root, ["diff", "--stat"]),
            "diff": _git_output(self.project_root, ["diff", "--"]),
        }
        manifest_path = session.session_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return CompletedSession(
            session_id=session.session_id,
            intent=session.intent,
            session_dir=session.session_dir,
            snapshot_dir=session.snapshot_dir,
            changed_files=changed_files,
            manifest_path=manifest_path,
        )

    def restore(self, session_id: str | None = None) -> None:
        target = session_id or self.current_session_id()
        if not target:
            raise ValueError("no session available to restore")
        snapshot_dir = self.sessions_dir / target / "snapshot"
        if not snapshot_dir.exists():
            raise ValueError(f"snapshot not found for session {target}")
        _restore_project(snapshot_dir, self.project_root)

    def current_session_id(self) -> str | None:
        path = self.sessions_dir / "current"
        if not path.exists():
            return None
        value = path.read_text(encoding="utf-8").strip()
        return value or None

    def write_transcript(self, session_id: str, name: str, content: str) -> Path:
        path = self.sessions_dir / session_id / "transcripts" / f"{name}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _write_current(self, session_id: str) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        (self.sessions_dir / "current").write_text(session_id, encoding="utf-8")


def _copy_project(source: Path, dest: Path) -> None:
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if _ignored(relative):
            continue
        target = dest / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _restore_project(snapshot: Path, project_root: Path) -> None:
    for path in list(project_root.rglob("*")):
        relative = path.relative_to(project_root)
        if _ignored(relative):
            continue
        if path.is_file() and not (snapshot / relative).exists():
            path.unlink()
    for path in snapshot.rglob("*"):
        relative = path.relative_to(snapshot)
        target = project_root / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _changed_files(before: Path, after: Path) -> list[str]:
    files = set(_files(before)) | set(_files(after))
    changed: list[str] = []
    for relative in sorted(files):
        before_path = before / relative
        after_path = after / relative
        if not before_path.exists() or not after_path.exists():
            changed.append(relative)
        elif not filecmp.cmp(before_path, after_path, shallow=False):
            changed.append(relative)
    return changed


def _files(root: Path) -> list[str]:
    result: list[str] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if _ignored(relative):
            continue
        if path.is_file():
            result.append(str(relative))
    return result


def _ignored(relative: Path) -> bool:
    return any(part in IGNORED for part in relative.parts)


def _git_output(project_root: Path, args: list[str]) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()
