import json
import os
import subprocess
import sys
from pathlib import Path

from devclaw.core.context import scan_project_context


def test_scan_project_context_detects_python_project(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Sample App\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\npythonpath = [\".\"]\n",
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_ok(): assert True\n")

    context = scan_project_context(tmp_path)

    assert context.project_root == tmp_path
    assert context.primary_language == "python"
    assert any("pytest" in command for command in context.test_commands)
    assert "README.md" in context.docs
    assert "app.py" in context.files


def test_refresh_context_persists_project_context(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "product"
    project.mkdir()
    (project / "README.md").write_text("# Product\n", encoding="utf-8")
    (project / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "devclaw", "/refresh-context"],
        text=True,
        capture_output=True,
        check=False,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
    )

    assert result.returncode == 0, result.stderr
    data = json.loads((project / ".devclaw" / "context" / "project-context.json").read_text())
    assert data["primary_language"] == "python"
    assert any("pytest" in command for command in data["test_commands"])


def test_interactive_context_commands_show_and_refresh_context(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "product"
    project.mkdir()
    (project / "README.md").write_text("# Product\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "devclaw"],
        input="/refresh-context\n/context\n/exit\n",
        text=True,
        capture_output=True,
        check=False,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
    )

    assert result.returncode == 0, result.stderr
    assert "Project Context" in result.stdout
    assert "README.md" in result.stdout
