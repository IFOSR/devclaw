from __future__ import annotations

from pathlib import Path

from devclaw.core.models import AcceptanceContract, AgentOutput, ProjectBrief


class ArchivistAgent:
    name = "Archivist Agent"

    def run(
        self,
        brief: ProjectBrief,
        contract: AcceptanceContract,
        workspace: Path,
        outputs: list[AgentOutput],
    ) -> AgentOutput:
        content = "\n".join(
            [
                f"# Project Memory: {brief.project_id}",
                "",
                "## Intent",
                brief.intent,
                "",
                "## Acceptance Items",
                *[f"- {item.id}: {item.description}" for item in contract.all_items()],
                "",
                "## Artifacts",
                *[f"- {output.agent}: {output.artifact}" for output in outputs],
            ]
        )
        path = workspace / ".devclaw" / "memory" / "project-memory.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return AgentOutput(
            agent=self.name,
            artifact="Project Memory",
            content=content,
            path=".devclaw/memory/project-memory.md",
        )
