import json
import os
import subprocess
import sys
from pathlib import Path


def test_real_codex_engineer_e2e(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "real-codex-project"
    project.mkdir()
    (project / "README.md").write_text("# Real Codex Project\n", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "test_hello.py").write_text(
        "import subprocess\n"
        "import sys\n\n"
        "def test_hello_cli():\n"
        "    result = subprocess.run([sys.executable, 'hello.py'], text=True, capture_output=True, check=True)\n"
        "    assert result.stdout.strip() == 'hello from DevClaw'\n",
        encoding="utf-8",
    )

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
            "Create hello.py so running python3 hello.py prints exactly: hello from DevClaw",
        ],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        text=True,
        capture_output=True,
        check=False,
        timeout=1800,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert (project / "hello.py").exists()
    pytest_result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
    )
    assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr
    transcript = project / ".devclaw" / "reports" / "tool-transcripts" / "codex-execution.txt"
    assert transcript.exists()
    assert (project / ".devclaw" / "checks" / "acceptance_checks.py").exists()
    report = json.loads((project / ".devclaw" / "final-delivery-report.json").read_text())
    assert report["delivery_status"] == "delivered"
