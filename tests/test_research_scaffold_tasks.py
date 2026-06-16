import os
import subprocess
import sys
from pathlib import Path

from devclaw.core.scaffold import create_scaffold
from devclaw.core.tasks import create_task_plan
from devclaw.core.research import create_research_report


def test_create_scaffold_adds_agent_spec_without_overwriting(tmp_path: Path):
    output = create_scaffold(tmp_path, "agent", "lead-triage")
    output_again = create_scaffold(tmp_path, "agent", "lead-triage")

    assert output.exists()
    assert output.name == "lead-triage-agent.md"
    assert output_again == output
    assert "Agent Spec" in output.read_text()


def test_create_task_plan_persists_task_dag(tmp_path: Path):
    path = create_task_plan(tmp_path, "Add CSV export")

    assert path.exists()
    content = path.read_text()
    assert "Research" in content
    assert "Implementation" in content
    assert "Verification" in content


def test_create_research_report_includes_real_external_sources(tmp_path: Path):
    path = create_research_report(tmp_path, "agent framework")

    content = path.read_text(encoding="utf-8")
    assert "## Sources" in content
    assert "Retrieved:" in content
    assert "https://github.com/" in content
    assert "## Research-Driven Decisions" in content


def test_interactive_research_scaffold_risk_and_tasks_commands(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "product"
    project.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "devclaw"],
        input="/research Add CSV export\n/scaffold agent lead-triage\n/risk\n/tasks Add CSV export\n/exit\n",
        text=True,
        capture_output=True,
        check=False,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
    )

    assert result.returncode == 0, result.stderr
    assert "Research report" in result.stdout
    assert "Scaffold created" in result.stdout
    assert "Risk review" in result.stdout
    assert "Task plan" in result.stdout
    assert (project / ".devclaw" / "research" / "latest-research.md").exists()
    assert (project / ".devclaw" / "scaffolds" / "lead-triage-agent.md").exists()
    assert (project / ".devclaw" / "tasks" / "latest-task-plan.md").exists()
