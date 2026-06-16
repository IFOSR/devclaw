from __future__ import annotations

from devclaw.core.models import AcceptanceContract, AgentOutput, ProjectBrief


class ProductResearchAgent:
    name = "Product Research Agent"

    def run(self, brief: ProjectBrief, contract: AcceptanceContract) -> AgentOutput:
        content = "\n".join(
            [
                f"# Product Research Report: {brief.goal}",
                "",
                "## Research Questions",
                "- Who is the target user and what job are they trying to complete?",
                "- What alternatives or manual workflows exist today?",
                "- What is the smallest useful deliverable for this project?",
                "",
                "## Initial Findings",
                f"- Target user: {contract.target_user}.",
                "- v0.1 should prefer a narrow, runnable workflow over a broad incomplete product.",
                "- The acceptance contract must make completion measurable before implementation.",
                "",
                "## Implications for DevClaw",
                "- PRD must include scope, non-goals, and acceptance criteria.",
                "- Ambiguous or risky requirements should be escalated before implementation.",
            ]
        )
        return AgentOutput(
            agent=self.name,
            artifact="Product Research Report",
            content=content,
        )


class PMAgent:
    name = "PM Agent"

    def run(self, brief: ProjectBrief, contract: AcceptanceContract) -> AgentOutput:
        content = "\n".join(
            [
                f"# PRD: {brief.goal}",
                "",
                "## User",
                contract.target_user,
                "",
                "## Scope",
                *[f"- {item}" for item in contract.scope],
                "",
                "## Non-goals",
                *[f"- {item}" for item in contract.non_goals],
                "",
                "## Research Traceability",
                "- Source report: .devclaw/research/latest-research.md when external research is run.",
                "- Product scope should be adjusted by sourced ecosystem references and current project context.",
                "",
                "## Acceptance",
                *[
                    f"- {item.id}: {item.description}"
                    for item in contract.functional_acceptance
                ],
            ]
        )
        return AgentOutput(agent=self.name, artifact="PRD", content=content)
