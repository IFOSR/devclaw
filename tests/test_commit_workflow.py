import json
import subprocess
from pathlib import Path

from devclaw.core.commit import create_commit


def _init_repo(path: Path):
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "devclaw@example.test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "DevClaw"], cwd=path, check=True)
    (path / "README.md").write_text("# Project\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True)


def test_create_commit_commits_dirty_worktree_and_writes_report(tmp_path: Path):
    _init_repo(tmp_path)
    (tmp_path / "feature.py").write_text("print('feature')\n", encoding="utf-8")

    report = create_commit(tmp_path)

    assert report.status == "committed"
    assert report.commit
    latest = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert latest.startswith("feat: devclaw delivery")
    saved = json.loads((tmp_path / ".devclaw" / "reports" / "commit-report.json").read_text())
    assert saved["status"] == "committed"
    assert "feature.py" in saved["changed_files"]


def test_create_commit_reports_noop_for_clean_worktree(tmp_path: Path):
    _init_repo(tmp_path)

    report = create_commit(tmp_path)

    assert report.status == "no_changes"
    assert report.commit is None
