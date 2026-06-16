import subprocess
import sys
from pathlib import Path
import os

from devclaw.core.loop import DevClawLead
from tests.fakes import TestExecutionAdapter, TestVerificationAdapter


def test_core_run_updates_current_project_directory(tmp_path: Path):
    project = tmp_path / "my-product"
    project.mkdir()
    (project / "README.md").write_text("# My Product\n", encoding="utf-8")

    result = DevClawLead(
        execution_adapter=TestExecutionAdapter(),
        verification_adapter=TestVerificationAdapter(),
        max_rounds=1,
    ).run("Build a customer feedback triage Agent", project)

    assert result.final_report.delivery_status == "delivered"
    metadata_dir = project / ".devclaw"
    assert (metadata_dir / "acceptance-contract.json").exists()
    assert (metadata_dir / "verification-report.json").exists()
    assert (metadata_dir / "final-delivery-report.json").exists()
    assert (metadata_dir / "checks" / "acceptance_checks.py").exists()
    assert (metadata_dir / "agents" / "pm-agent.md").exists()
    assert (metadata_dir / "agents" / "architect-agent.md").exists()
    assert (metadata_dir / "artifacts" / "product-research-report.md").exists()
    assert (metadata_dir / "delivery" / "latest" / "README.md").exists()
    assert (project / "README.md").read_text(encoding="utf-8") == "# My Product\n"
    assert (project / "agent.py").exists()


def test_cli_accepts_idle_timeout_option_and_legacy_tool_timeout_alias_without_running_agents(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "my-product"
    project.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "devclaw", "--tool-timeout", "3", "/config"],
        text=True,
        capture_output=True,
        check=False,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "idle_timeout=3" in result.stdout
