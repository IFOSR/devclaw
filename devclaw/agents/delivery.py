from __future__ import annotations

from pathlib import Path

from devclaw.core.models import AcceptanceContract, AgentOutput, ProjectBrief


class DeliveryAgent:
    name = "Delivery Agent"

    def run(
        self,
        brief: ProjectBrief,
        contract: AcceptanceContract,
        workspace: Path,
        outputs: list[AgentOutput],
    ) -> AgentOutput:
        delivered = "\n".join(
            f"- {output.artifact}: {output.path or 'in-memory'}" for output in outputs
        )
        content = "\n".join(
            [
                f"# DevClaw Delivery: {brief.goal}",
                "",
                "## Setup",
                "Use Python 3.10+ in the generated project workspace.",
                "",
                "## Usage",
                "Run the generated deliverable according to its local instructions.",
                "",
                "## Delivered Items",
                delivered,
                "",
                "## Known Limitations",
                "- v0.1 does not perform automatic production deployment.",
                "- v0.1 requires configured Codex and Deepseek CLI credentials for real Agent execution.",
            ]
        )
        path = workspace / ".devclaw" / "delivery" / "latest" / "README.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return AgentOutput(
            agent=self.name,
            artifact="Delivery README",
            content=content,
            path=".devclaw/delivery/latest/README.md",
        )
