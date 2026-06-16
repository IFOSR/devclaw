import json
import os
import subprocess
import sys
from pathlib import Path

from devclaw.core.feedback import add_feedback, list_feedback


def test_add_feedback_persists_classified_feedback(tmp_path: Path):
    item = add_feedback(tmp_path, "bug: export crashes on empty data")

    assert item.feedback_type == "bug"
    saved = list_feedback(tmp_path)
    assert saved[0].description == "bug: export crashes on empty data"


def test_interactive_feedback_commands(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "product"
    project.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "devclaw"],
        input="/feedback bug: login fails\n/feedback-list\n/exit\n",
        text=True,
        capture_output=True,
        check=False,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
    )

    assert result.returncode == 0, result.stderr
    assert "Feedback recorded" in result.stdout
    assert "bug: login fails" in result.stdout
    feedback_files = list((project / ".devclaw" / "feedback").glob("*.json"))
    assert feedback_files
    assert json.loads(feedback_files[0].read_text())["feedback_type"] == "bug"
