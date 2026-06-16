import json
import os
import subprocess
import sys
from pathlib import Path


def test_real_commit_workflow_after_codex_delivery(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "real-commit-project"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "devclaw@example.test"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "DevClaw"], cwd=project, check=True)
    (project / "README.md").write_text("# Real Commit Project\n", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "test_ship.py").write_text(
        "import subprocess\n"
        "import sys\n\n"
        "def test_ship_cli():\n"
        "    result = subprocess.run([sys.executable, 'ship.py'], text=True, capture_output=True, check=True)\n"
        "    assert result.stdout.strip() == 'commit workflow ok'\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=project, check=True, capture_output=True)

    delivery = subprocess.run(
        [
            sys.executable,
            "-m",
            "devclaw",
            "--executor",
            "codex",
            "--verifier",
            "deepseek",
            "--idle-timeout",
            "900",
            "--max-rounds",
            "1",
            "run",
            "Create ship.py so running python3 ship.py prints exactly: commit workflow ok",
        ],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        text=True,
        capture_output=True,
        check=False,
        timeout=1800,
    )
    assert delivery.returncode == 0, delivery.stderr + delivery.stdout

    commit = subprocess.run(
        [sys.executable, "-m", "devclaw", "/commit"],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert commit.returncode == 0, commit.stderr + commit.stdout
    assert "Commit status: committed" in commit.stdout
    report = json.loads((project / ".devclaw" / "reports" / "commit-report.json").read_text())
    assert report["status"] == "committed"
    assert report["commit"]
    subject = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=project,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert subject.startswith("feat: devclaw delivery")
