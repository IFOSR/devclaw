"""Project inspection: git baseline, file inventory, and test detection.

All path values produced here are POSIX strings relative to the project
root so persisted records stay portable across machines.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from typing import Mapping
from pathlib import Path

from metacoding.models import ProjectSnapshot, now_utc

#: Directories that never belong to a project's business snapshot.
EXCLUDED_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "node_modules",
}

#: Paths under ``.metacoding`` that are runtime-generated state.
EXCLUDED_METACODING_PARTS = ("runs", "transcripts", "logs", "github")

#: Volatile cache directories that legitimately appear while harnesses run
#: checks; their creation is not treated as a write violation.
VOLATILE_IGNORED_DIRS = (
    ".pytest_cache",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "node_modules",
    ".venv",
    "venv",
    "htmlcov",
)
MAX_INVENTORY_ENTRIES = 2000
MAX_IGNORED_ENTRIES = 2000

#: Pseudo-key prefix for git metadata fingerprints inside workspace_state.
GIT_META_PREFIX = "@git/"


def _git(root: Path, *args: str) -> tuple[int, str]:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True
    )
    return result.returncode, result.stdout


def _is_git_repo(root: Path) -> bool:
    code, _ = _git(root, "rev-parse", "--is-inside-work-tree")
    return code == 0


def git_head(root: Path) -> str | None:
    code, output = _git(root, "rev-parse", "HEAD")
    return output.strip() if code == 0 and output.strip() else None


#: File suffixes that are compiled artifacts, never ownership-relevant.
VOLATILE_FILE_SUFFIXES = (".pyc", ".pyo", ".DS_Store")


def _is_volatile_path(path: str) -> bool:
    """Volatile build/cache artifacts: invisible to change tracking.

    Harnesses legitimately execute the project's test commands, which
    creates __pycache__/.pytest_cache litter; treating those as writes would
    false-positive the stage write guard and pollute owned diffs.
    """
    return any(part in EXCLUDED_DIR_NAMES for part in path.split("/")) or path.endswith(
        VOLATILE_FILE_SUFFIXES
    )


def current_dirty_files(root: Path) -> set[str]:
    """All modified, staged, added, renamed, and untracked paths.

    ``-uall`` expands untracked directories into individual files so the
    workspace state is content-comparable file by file.
    """
    if not _is_git_repo(root):
        return set()
    code, output = _git(root, "status", "--porcelain", "-uall")
    if code != 0:
        return set()
    dirty: set[str] = set()
    for line in output.splitlines():
        if not line.strip():
            continue
        path_part = line[3:] if len(line) > 3 else ""
        if "->" in path_part:
            old, new = path_part.split("->", 1)
            dirty.add(_normalize(old))
            dirty.add(_normalize(new))
        else:
            dirty.add(_normalize(path_part))
    dirty.discard("")
    return {path for path in dirty if not _is_volatile_path(path)}


def owned_changes_since_baseline(root: Path, baseline_dirty: set[str]) -> set[str]:
    """Dirty paths that were not already dirty before the run started."""
    return current_dirty_files(root) - set(baseline_dirty)


def _normalize(raw_path: str) -> str:
    path = raw_path.strip().strip('"')
    return Path(path).as_posix() if path else ""


def _inventory(root: Path) -> list[str]:
    entries: list[str] = []
    for current_dir, dir_names, file_names in os.walk(root):
        current_path = Path(current_dir)
        dir_names[:] = [
            name
            for name in dir_names
            if name not in EXCLUDED_DIR_NAMES
            and not (current_path == root / ".metacoding" and name in EXCLUDED_METACODING_PARTS)
        ]
        for file_name in sorted(file_names):
            if file_name == ".DS_Store":
                continue
            relative = (current_path / file_name).relative_to(root).as_posix()
            entries.append(relative)
            if len(entries) >= MAX_INVENTORY_ENTRIES:
                return entries
    return entries


def detect_test_commands(root: Path) -> list[str]:
    """Best-effort detection of the project's own test entry points."""
    commands: list[str] = []
    root = Path(root)
    pytest_command = f"{sys.executable} -m pytest -q"
    has_pytest_config = (root / "pytest.ini").is_file() or (root / "pyproject.toml").is_file()
    has_test_files = bool(list(root.glob("test_*.py"))) or bool(
        list(root.glob("tests/test_*.py"))
    )
    if has_pytest_config or has_test_files:
        commands.append(pytest_command)

    package_json = root / "package.json"
    if package_json.is_file():
        content = package_json.read_text(encoding="utf-8")
        if '"test"' in content:
            commands.append("npm test")

    makefile = root / "Makefile"
    if makefile.is_file():
        content = makefile.read_text(encoding="utf-8")
        if any(line.startswith("test:") for line in content.splitlines()):
            commands.append("make test")

    if (root / "go.mod").is_file():
        commands.append("go test ./...")
    return commands


def git_invariant(project_root: Path) -> tuple[str | None, str | None]:
    """(HEAD, branch) as an invariant guard; (None, None) outside git."""
    root = Path(project_root)
    if not _is_git_repo(root):
        return (None, None)
    code, output = _git(root, "rev-parse", "HEAD", "--abbrev-ref")
    if code != 0:
        return (None, None)
    head, _, branch = output.strip().partition("\n")
    return (head or None, branch or None)


def _git_meta_state(root: Path) -> dict[str, str]:
    """Fingerprints of git internals a harness must never touch.

    Covers .git/config, every hook, and the branch/ref layout. The index is
    deliberately excluded: read-only commands like ``git status`` may
    opportunistically refresh it, so hashing it would false-positive.
    """
    git_dir = root / ".git"
    if not git_dir.is_dir():
        return {}
    state: dict[str, str] = {}

    def digest(path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return "<unreadable>"

    config = git_dir / "config"
    if config.is_file():
        state[f"{GIT_META_PREFIX}config"] = digest(config)
    hooks_dir = git_dir / "hooks"
    if hooks_dir.is_dir():
        for hook in sorted(hooks_dir.iterdir()):
            if hook.is_file() and not hook.name.endswith(".sample"):
                state[f"{GIT_META_PREFIX}hooks/{hook.name}"] = digest(hook)
    code, output = _git(root, "for-each-ref", "refs/heads", "--format=%(refname) %(objectname)")
    if code == 0:
        state[f"{GIT_META_PREFIX}refs"] = hashlib.sha256(
            output.strip().encode("utf-8")
        ).hexdigest()
    return state


def _ignored_presence(root: Path) -> dict[str, str]:
    """Presence markers for gitignored product files (name-level only).

    Content changes inside ignored files remain a documented limitation;
    creating or deleting one (e.g. a leaked secret file) is detected.
    """
    code, output = _git(
        root, "ls-files", "--others", "--ignored", "--exclude-standard"
    )
    if code != 0:
        return {}
    markers: dict[str, str] = {}
    for line in output.splitlines():
        path = _normalize(line)
        if not path or path.startswith(".metacoding/"):
            continue
        if any(part in VOLATILE_IGNORED_DIRS for part in path.split("/")):
            continue
        markers[path] = ""
        if len(markers) >= MAX_IGNORED_ENTRIES:
            break
    return markers


def runtime_evidence_state(project_root: Path, run_id: str) -> dict[str, str]:
    """Hash every runtime evidence file of a run plus host state files.

    Covers ``.metacoding/runs/<run-id>/**`` (run.json, plan, rounds, git
    artifacts, final), ``.metacoding/state.json``, and the lock file — none
    of which appear in git status or the business inventory.
    """
    root = Path(project_root)
    state: dict[str, str] = {}
    run_root = root / ".metacoding" / "runs" / run_id
    for base, names in ((run_root, None), (root / ".metacoding", ("state.json", "active-run.lock"))):
        if names is not None:
            paths = [base / name for name in names if (base / name).is_file()]
        else:
            if not base.is_dir():
                continue
            paths = [p for p in sorted(base.rglob("*")) if p.is_file()]
        for path in paths:
            relative = path.relative_to(root).as_posix()
            try:
                state[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                state[relative] = "<unreadable>"
    return state


def workspace_state(project_root: Path) -> dict[str, str]:
    """Ground-truth workspace state as ``path -> content hash``.

    For git repositories only the dirty files are hashed (a file that was
    already dirty at baseline keeps a comparable hash so later edits are
    detectable). For plain directories the whole inventory is hashed.
    Deleted paths are recorded as ``<deleted>``.
    """
    root = Path(project_root)
    if _is_git_repo(root):
        state: dict[str, str] = {}
        for path in current_dirty_files(root):
            state[path] = _file_hash(root / path)
        state.update(_git_meta_state(root))
        state.update(_ignored_presence(root))
        return state
    return {path: _file_hash(root / path) for path in _inventory(root)}


def _file_hash(path: Path) -> str:
    try:
        data = path.read_bytes()
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return "<deleted>"
    return hashlib.sha256(data).hexdigest()


def detect_workspace_changes(
    pre_state: Mapping[str, str],
    post_state: Mapping[str, str],
    *,
    ignore_prefixes: tuple[str, ...] = (".metacoding/",),
) -> set[str]:
    """Paths created, deleted, or modified between two workspace states."""
    changed = {
        path
        for path in set(pre_state) | set(post_state)
        if pre_state.get(path) != post_state.get(path)
    }
    return {
        path for path in changed if not path.startswith(ignore_prefixes)
    }


def capture_snapshot(project_root: Path) -> ProjectSnapshot:
    """Record the deterministic starting state of a project."""
    root = Path(project_root)
    is_repo = _is_git_repo(root)
    return ProjectSnapshot(
        captured_at=now_utc(),
        is_git_repo=is_repo,
        git_head=git_head(root) if is_repo else None,
        dirty_files=sorted(current_dirty_files(root)),
        file_inventory=_inventory(root),
        test_commands=detect_test_commands(root),
    )
