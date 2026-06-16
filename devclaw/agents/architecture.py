from __future__ import annotations

from devclaw.core.models import AcceptanceContract, AgentOutput, ProjectBrief


class TechnicalResearchAgent:
    name = "Technical Research Agent"

    def run(self, brief: ProjectBrief, contract: AcceptanceContract) -> AgentOutput:
        content = "\n".join(
            [
                f"# Technical Research Report: {brief.goal}",
                "",
                "## Technical Options",
                "- Codex CLI adapter for real implementation work.",
                "- Deepseek TUI adapter for independent verification.",
                "",
                "## Risks",
                "- Real AI tool output may be non-deterministic.",
                "- Direct project edits need clear metadata and rollback guidance.",
                "",
                "## Implications for DevClaw",
                "- Keep core loop acceptance-driven and adapter-based.",
                "- Store DevClaw metadata under .devclaw/ inside the current project.",
            ]
        )
        return AgentOutput(
            agent=self.name,
            artifact="Technical Research Report",
            content=content,
        )


class ArchitectAgent:
    name = "Architect Agent"

    def run(self, brief: ProjectBrief, contract: AcceptanceContract) -> AgentOutput:
        content = "\n".join(
            [
                f"# Architecture: {brief.goal}",
                "",
                "## Modules",
                "- Intake: receives user input.",
                "- Processor: coordinates real implementation and verification Agents.",
                "- Output: writes result and reports.",
                "- Verification: checks required artifacts and acceptance items.",
                "",
                "## Data Flow",
                "Intent -> Project Brief -> Acceptance Contract -> Implementation -> Verification -> Delivery Report",
                "",
                "## Research Traceability",
                "- Source report: .devclaw/research/latest-research.md when external research is run.",
                "- Architecture choices should cite sourced project and ecosystem constraints.",
                "",
                "## Technical Acceptance",
                *[
                    f"- {item.id}: {item.description}"
                    for item in contract.technical_acceptance
                ],
            ]
        )
        return AgentOutput(agent=self.name, artifact="Architecture Spec", content=content)
