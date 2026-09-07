"""Project snapshot, git baseline, and test command detection behavior."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from metacoding.models import ProjectSnapshot
from metacoding.project import (
    capture_snapshot,
    current_dirty_files,
    detect_test_commands,
    owned_changes_since_baseline,
)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def init_repo(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return git(root, "rev-parse", "HEAD")


def test_snapshot_of_directory_without_git(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('x')\n", encoding="utf-8")
    snapshot = capture_snapshot(tmp_path)
    assert isinstance(snapshot, ProjectSnapshot)
    assert snapshot.is_git_repo is False
    assert snapshot.git_head is None
    assert snapshot.dirty_files == []
    assert "src/app.py" in snapshot.file_inventory
    assert snapshot.captured_at.endswith("Z")


def test_snapshot_of_git_repo_records_head_and_dirty(tmp_path: Path) -> None:
    head = init_repo(tmp_path)
    (tmp_path / "README.md").write_text("changed\n", encoding="utf-8")
    (tmp_path / "untracked.txt").write_text("new\n", encoding="utf-8")
    snapshot = capture_snapshot(tmp_path)
    assert snapshot.is_git_repo is True
    assert snapshot.git_head == head
    assert "README.md" in snapshot.dirty_files
    assert "untracked.txt" in snapshot.dirty_files


def test_snapshot_excludes_metacoding_runtime_records(tmp_path: Path) -> None:
    init_repo(tmp_path)
    for runtime in ("runs/abc/run.json", "transcripts/x.stdout", "logs/host.log", "github/pr.json"):
        path = tmp_path / ".metacoding" / runtime
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    (tmp_path / ".metacoding" / "config.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    snapshot = capture_snapshot(tmp_path)
    joined = "\n".join(snapshot.file_inventory)
    assert ".metacoding/runs" not in joined
    assert ".metacoding/transcripts" not in joined
    assert ".metacoding/logs" not in joined
    assert ".metacoding/github" not in joined
    assert ".metacoding/config.toml" in snapshot.file_inventory
    assert "src/app.py" in snapshot.file_inventory


def test_detect_test_commands_by_project_type(tmp_path: Path) -> None:
    assert detect_test_commands(tmp_path) == []

    pytest_command = f"{sys.executable} -m pytest -q"
    pytest_dir = tmp_path / "pytest-project"
    tests_dir = pytest_dir / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    assert detect_test_commands(pytest_dir) == [pytest_command]

    npm_dir = tmp_path / "npm-project"
    npm_dir.mkdir()
    (npm_dir / "package.json").write_text(
        '{"name": "x", "scripts": {"test": "jest"}}', encoding="utf-8"
    )
    assert detect_test_commands(npm_dir) == ["npm test"]

    make_dir = tmp_path / "make-project"
    make_dir.mkdir()
    (make_dir / "Makefile").write_text("test:\n\techo ok\n", encoding="utf-8")
    assert detect_test_commands(make_dir) == ["make test"]

    go_dir = tmp_path / "go-project"
    go_dir.mkdir()
    (go_dir / "go.mod").write_text("module example.com/x\n\ngo 1.21\n", encoding="utf-8")
    assert detect_test_commands(go_dir) == ["go test ./..."]


def test_owned_changes_exclude_preexisting_dirty_files(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "preexisting.txt").write_text("dirty before run\n", encoding="utf-8")
    baseline = current_dirty_files(tmp_path)
    assert baseline == {"preexisting.txt"}

    (tmp_path / "new-feature.txt").write_text("created by coder\n", encoding="utf-8")
    (tmp_path / "preexisting.txt").write_text("edited again\n", encoding="utf-8")
    owned = owned_changes_since_baseline(tmp_path, baseline)
    assert owned == {"new-feature.txt"}


def test_current_dirty_files_handles_renames(tmp_path: Path) -> None:
    init_repo(tmp_path)
    git(tmp_path, "mv", "README.md", "RENAMED.md")
    dirty = current_dirty_files(tmp_path)
    assert "README.md" in dirty
    assert "RENAMED.md" in dirty
