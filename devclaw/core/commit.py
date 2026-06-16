from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommitReport:
    status: str
    message: str
    commit: str | None
    changed_files: list[str]
    diff_stat: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def create_commit(project_root: Path) -> CommitReport:
    if not _git_ok(project_root, ["rev-parse", "--is-inside-work-tree"]):
        report = CommitReport("not_git", "Not a git worktree.", None, [], "")
        _write_report(project_root, report)
        return report

    changed_files = _git_lines(project_root, ["diff", "--name-only"])
    untracked = _git_lines(project_root, ["ls-files", "--others", "--exclude-standard"])
    all_changed = sorted(set(changed_files + untracked))
    if not all_changed:
        report = CommitReport("no_changes", "No changes to commit.", None, [], "")
        _write_report(project_root, report)
        return report

    diff_stat = _git_output(project_root, ["diff", "--stat"]) or "\n".join(untracked)
    message = "feat: devclaw delivery"
    subprocess.run(["git", "add", *all_changed], cwd=project_root, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=project_root, check=True, capture_output=True)
    commit = _git_output(project_root, ["rev-parse", "HEAD"])
    report = CommitReport("committed", message, commit, all_changed, diff_stat)
    _write_report(project_root, report)
    return report


def _write_report(project_root: Path, report: CommitReport) -> None:
    path = project_root / ".devclaw" / "reports" / "commit-report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


def _git_ok(project_root: Path, args: list[str]) -> bool:
    return subprocess.run(
        ["git", *args],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    ).returncode == 0


def _git_output(project_root: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _git_lines(project_root: Path, args: list[str]) -> list[str]:
    output = _git_output(project_root, args)
    return [line for line in output.splitlines() if line.strip()]
