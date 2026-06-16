from pathlib import Path

from devclaw.agents.architecture import ArchitectAgent, TechnicalResearchAgent
from devclaw.agents.archivist import ArchivistAgent
from devclaw.agents.delivery import DeliveryAgent
from devclaw.agents.design import DesignerAgent, UXResearchAgent
from devclaw.agents.product import PMAgent, ProductResearchAgent
from devclaw.agents.release import ReleaseAgent
from devclaw.core.contracts import create_acceptance_contract, create_project_brief
from devclaw.core.models import AgentOutput


def _contract():
    brief = create_project_brief("Build a customer feedback triage Agent")
    return brief, create_acceptance_contract(brief)


def test_product_design_architecture_agents_create_required_artifacts():
    brief, contract = _contract()

    outputs = [
        PMAgent().run(brief, contract),
        DesignerAgent().run(brief, contract),
        ArchitectAgent().run(brief, contract),
    ]

    assert [output.agent for output in outputs] == [
        "PM Agent",
        "Designer Agent",
        "Architect Agent",
    ]
    assert outputs[0].artifact == "PRD"
    assert "Acceptance" in outputs[0].content
    assert "Research Traceability" in outputs[0].content
    assert "User Journey" in outputs[1].content
    assert "Modules" in outputs[2].content
    assert "Research Traceability" in outputs[2].content


def test_research_agents_create_required_research_artifacts():
    brief, contract = _contract()

    outputs = [
        ProductResearchAgent().run(brief, contract),
        UXResearchAgent().run(brief, contract),
        TechnicalResearchAgent().run(brief, contract),
    ]

    assert [output.artifact for output in outputs] == [
        "Product Research Report",
        "UX Research Report",
        "Technical Research Report",
    ]
    assert "Research Questions" in outputs[0].content
    assert "Reference Patterns" in outputs[1].content
    assert "Technical Options" in outputs[2].content
    assert all("Implications for DevClaw" in output.content for output in outputs)


def test_release_delivery_and_archivist_agents_create_project_files(tmp_path: Path):
    brief, contract = _contract()
    workspace = tmp_path / brief.project_id
    workspace.mkdir()
    outputs = [
        AgentOutput(
            agent="Engineer Agent",
            artifact="Runnable implementation",
            content="created",
            path="agent.py",
        )
    ]

    release = ReleaseAgent().run(brief, contract, workspace)
    delivery = DeliveryAgent().run(brief, contract, workspace, outputs)
    archive = ArchivistAgent().run(brief, contract, workspace, outputs + [release, delivery])

    assert release.artifact == "Release Plan"
    assert delivery.artifact == "Delivery README"
    assert archive.artifact == "Project Memory"
    assert release.path == ".devclaw/release/latest/release-plan.md"
    assert archive.path == ".devclaw/memory/project-memory.md"
    assert (workspace / ".devclaw" / "delivery" / "latest" / "README.md").exists()
    assert (workspace / ".devclaw" / "release" / "latest" / "release-plan.md").exists()
    assert (workspace / ".devclaw" / "memory" / "project-memory.md").exists()
    assert not (workspace / "release-plan.md").exists()
    assert not (workspace / "project-memory.md").exists()
    assert "Known Limitations" in (
        workspace / ".devclaw" / "delivery" / "latest" / "README.md"
    ).read_text()


def test_delivery_agent_does_not_overwrite_existing_project_readme(tmp_path: Path):
    brief, contract = _contract()
    workspace = tmp_path / "project"
    workspace.mkdir()
    readme = workspace / "README.md"
    readme.write_text("# Existing Product\n", encoding="utf-8")

    delivery = DeliveryAgent().run(brief, contract, workspace, [])

    assert readme.read_text(encoding="utf-8") == "# Existing Product\n"
    assert delivery.path == ".devclaw/delivery/latest/README.md"
