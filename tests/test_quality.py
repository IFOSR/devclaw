import os
import subprocess
import sys
from pathlib import Path

from devclaw.core.quality import run_quality_checks


def test_run_quality_checks_executes_detected_pytest_command(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok(): assert True\n")

    report = run_quality_checks(tmp_path)

    assert report.status == "pass"
    assert any("pytest" in item["command"] for item in report.checks)


def test_interactive_test_and_quality_commands(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "product"
    project.mkdir()
    (project / "tests").mkdir()
    (project / "tests" / "test_ok.py").write_text("def test_ok(): assert True\n")

    result = subprocess.run(
        [sys.executable, "-m", "devclaw"],
        input="/test\n/quality\n/exit\n",
        text=True,
        capture_output=True,
        check=False,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
    )

    assert result.returncode == 0, result.stderr
    assert "Quality status: pass" in result.stdout
    assert (project / ".devclaw" / "reports" / "quality-report.json").exists()
