import os
import subprocess
import sys
from pathlib import Path


def test_interactive_sessions_and_diff_commands(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "product"
    project.mkdir()
    from devclaw.core.sessions import SessionManager

    manager = SessionManager(project)
    session = manager.begin("Add a reporting helper")
    (project / "created.txt").write_text("created", encoding="utf-8")
    manager.complete(session)

    result = subprocess.run(
        [sys.executable, "-m", "devclaw"],
        input="/sessions\n/diff\n/undo\n/exit\n",
        text=True,
        capture_output=True,
        check=False,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
    )

    assert result.returncode == 0, result.stderr
    assert "Sessions" in result.stdout
    assert "Add a reporting helper" in result.stdout
    assert "Diff" in result.stdout
    assert "Undo" in result.stdout
