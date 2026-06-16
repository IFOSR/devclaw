import os
import subprocess
import sys
from pathlib import Path


def test_real_parallel_codex_e2e_runs_two_subtasks_and_integrates(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "real-parallel-project"
    project.mkdir()
    (project / "README.md").write_text("# Real Parallel Project\n", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "test_parallel_outputs.py").write_text(
        "import subprocess\n"
        "import sys\n\n"
        "def test_alpha_cli():\n"
        "    result = subprocess.run([sys.executable, 'alpha.py'], text=True, capture_output=True, check=True)\n"
        "    assert result.stdout.strip() == 'alpha parallel ok'\n\n"
        "def test_beta_cli():\n"
        "    result = subprocess.run([sys.executable, 'beta.py'], text=True, capture_output=True, check=True)\n"
        "    assert result.stdout.strip() == 'beta parallel ok'\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "devclaw",
            "--idle-timeout",
            "900",
            "/parallel-run",
            "Create alpha.py so running python3 alpha.py prints exactly alpha parallel ok and Create beta.py so running python3 beta.py prints exactly beta parallel ok",
        ],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        text=True,
        capture_output=True,
        check=False,
        timeout=2400,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert (project / "alpha.py").exists()
    assert (project / "beta.py").exists()
    transcripts = list((project / ".devclaw" / "reports" / "tool-transcripts").glob("parallel-*.txt"))
    assert len(transcripts) >= 2
    pytest_result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
    )
    assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr
