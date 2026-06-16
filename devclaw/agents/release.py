from __future__ import annotations

from pathlib import Path

from devclaw.core.models import AcceptanceContract, AgentOutput, ProjectBrief


class ReleaseAgent:
    name = "Release Agent"

    def run(
        self,
        brief: ProjectBrief,
        contract: AcceptanceContract,
        workspace: Path,
    ) -> AgentOutput:
        content = "\n".join(
            [
                f"# Release Plan: {brief.project_id}",
                "",
                "## Build Checklist",
                "- Confirm required files exist.",
                "- Run QA verification.",
                "- Confirm README includes setup and usage.",
                "",
                "## Deployment",
                "v0.1 supports local handoff only. Production deployment requires human approval.",
                "",
                "## Rollback",
                "Keep the previous project workspace and restore from it if needed.",
            ]
        )
        path = workspace / ".devclaw" / "release" / "latest" / "release-plan.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return AgentOutput(
            agent=self.name,
            artifact="Release Plan",
            content=content,
            path=".devclaw/release/latest/release-plan.md",
        )
