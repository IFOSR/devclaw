import json
import os
import subprocess
import sys
from pathlib import Path


def test_real_codex_git_project_records_diff_and_undo_restores(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "real-git-project"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "devclaw@example.test"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "DevClaw"], cwd=project, check=True)
    (project / "README.md").write_text("# Real Git Project\n", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "test_status.py").write_text(
        "import subprocess\n"
        "import sys\n\n"
        "def test_status_cli():\n"
        "    result = subprocess.run([sys.executable, 'status.py'], text=True, capture_output=True, check=True)\n"
        "    assert result.stdout.strip() == 'git isolation ok'\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=project, check=True, capture_output=True)
    base_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    result = subprocess.run(
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
            "Create status.py so running python3 status.py prints exactly: git isolation ok",
        ],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        text=True,
        capture_output=True,
        check=False,
        timeout=1800,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert (project / "status.py").exists()
    current = (project / ".devclaw" / "sessions" / "current").read_text(encoding="utf-8").strip()
    manifest = json.loads(
        (project / ".devclaw" / "sessions" / current / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["git_isolation"] == "snapshot"
    assert manifest["base_revision"] == base_revision
    assert "status.py" in manifest["changed_files"]
    assert "status.py" in manifest["diff"]

    undo = subprocess.run(
        [sys.executable, "-m", "devclaw", "/undo"],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert undo.returncode == 0, undo.stderr + undo.stdout
    assert not (project / "status.py").exists()
