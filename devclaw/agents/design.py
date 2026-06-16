from __future__ import annotations

from devclaw.core.models import AcceptanceContract, AgentOutput, ProjectBrief


class UXResearchAgent:
    name = "UX Research Agent"

    def run(self, brief: ProjectBrief, contract: AcceptanceContract) -> AgentOutput:
        content = "\n".join(
            [
                f"# UX Research Report: {brief.goal}",
                "",
                "## Reference Patterns",
                "- CLI assistants should distinguish system commands from natural language.",
                "- Project-local tools should make output paths explicit after each run.",
                "- Agent products need examples, fallback behavior, and known limitations.",
                "",
                "## User Experience Risks",
                "- Users may confuse built-in commands with natural language requests.",
                "- A successful run is not useful unless the next action is obvious.",
                "",
                "## Implications for DevClaw",
                "- Use slash commands for system actions.",
                "- Delivery docs must include setup, usage, and examples.",
            ]
        )
        return AgentOutput(agent=self.name, artifact="UX Research Report", content=content)


class DesignerAgent:
    name = "Designer Agent"

    def run(self, brief: ProjectBrief, contract: AcceptanceContract) -> AgentOutput:
        content = "\n".join(
            [
                f"# UX Flow: {brief.goal}",
                "",
                "## User Journey",
                "1. User reads setup and usage instructions.",
                "2. User runs the deliverable locally.",
                "3. User provides sample input.",
                "4. Product or Agent returns a useful result.",
                "5. User checks known limitations and next steps.",
                "",
                "## Usability Acceptance",
                *[f"- {item.id}: {item.description}" for item in contract.ux_acceptance],
            ]
        )
        return AgentOutput(agent=self.name, artifact="UX Flow", content=content)
