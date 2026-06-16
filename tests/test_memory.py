import json
import os
import subprocess
import sys
from pathlib import Path

from devclaw.core.memory import ProjectMemory, load_memory, update_memory_after_run
from devclaw.core.contracts import create_acceptance_contract, create_project_brief
from devclaw.core.models import FinalDeliveryReport


def test_memory_update_persists_request_and_delivery(tmp_path: Path):
    brief = create_project_brief("Add search")
    contract = create_acceptance_contract(brief)
    report = FinalDeliveryReport(
        project_id=brief.project_id,
        version="0.1.0",
        goal=brief.goal,
        delivery_status="delivered",
        delivered_items=[],
        acceptance_result={"blocking_passed": True},
        test_result={"summary": "passed"},
        run_instructions={},
        deployment_notes={},
        known_limits=[],
        next_iteration=[],
    )

    memory = update_memory_after_run(tmp_path, brief, contract, report)

    assert isinstance(memory, ProjectMemory)
    assert memory.request_history[0]["intent"] == "Add search"
    assert memory.delivery_history[0]["status"] == "delivered"
    assert (tmp_path / ".devclaw" / "memory" / "project.json").exists()


def test_load_memory_returns_empty_memory_when_missing(tmp_path: Path):
    memory = load_memory(tmp_path)

    assert memory.project_root == str(tmp_path)
    assert memory.request_history == []


def test_cli_memory_history_and_decisions_commands(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "product"
    project.mkdir()
    brief = create_project_brief("Add a search box")
    contract = create_acceptance_contract(brief)
    report = FinalDeliveryReport(
        project_id=brief.project_id,
        version="0.1.0",
        goal=brief.goal,
        delivery_status="delivered",
        delivered_items=[],
        acceptance_result={"blocking_passed": True},
        test_result={"summary": "passed"},
        run_instructions={},
        deployment_notes={},
        known_limits=[],
        next_iteration=[],
    )
    update_memory_after_run(project, brief, contract, report)

    result = subprocess.run(
        [sys.executable, "-m", "devclaw"],
        input="/memory\n/history\n/decisions\n/exit\n",
        text=True,
        capture_output=True,
        check=False,
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
    )

    assert result.returncode == 0, result.stderr
    assert "Project Memory" in result.stdout
    assert "Add a search box" in result.stdout
    assert "Architecture decisions" in result.stdout

    data = json.loads((project / ".devclaw" / "memory" / "project.json").read_text())
    assert data["request_history"]
