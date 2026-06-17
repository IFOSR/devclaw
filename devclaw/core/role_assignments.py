from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleAssignment:
    role: str
    provider: str
    stage: str
    output_stage: str
    artifact: str
    skills: tuple[str, ...]
    mission: str


ROLE_ASSIGNMENTS: dict[str, RoleAssignment] = {
    "intake": RoleAssignment(
        role="Codex Intake Agent",
        provider="codex",
        stage="intake",
        output_stage="intake",
        artifact="Project Brief and Acceptance Contract",
        skills=("project-context-scan", "requirements-analysis", "acceptance-contract-generation", "attachment-review"),
        mission="Analyze the user request, attached evidence, current project context, and acceptance boundaries.",
    ),
    "product_research": RoleAssignment(
        role="Deepseek Product Research Agent",
        provider="deepseek",
        stage="research",
        output_stage="research",
        artifact="Product Research Report",
        skills=("market-research", "user-goal-analysis", "scope-boundary-analysis", "risk-assessment"),
        mission="Research user goals, alternatives, scope boundaries, assumptions, and product risks.",
    ),
    "ux_research": RoleAssignment(
        role="Codex UX Research Agent",
        provider="codex",
        stage="research",
        output_stage="research",
        artifact="UX Research Report",
        skills=("screenshot-analysis", "browser-qa", "frontend-inspection", "usability-diagnosis"),
        mission="Inspect screenshots, UI context, and frontend implementation constraints for usability issues.",
    ),
    "prd": RoleAssignment(
        role="Deepseek PRD Agent",
        provider="deepseek",
        stage="product",
        output_stage="product",
        artifact="PRD",
        skills=("product-structuring", "acceptance-criteria-writing", "non-goals-definition", "tradeoff-analysis"),
        mission="Turn research into a scoped PRD with acceptance criteria and non-goals.",
    ),
    "design": RoleAssignment(
        role="Codex Design Agent",
        provider="codex",
        stage="design",
        output_stage="design",
        artifact="UX Flow",
        skills=("frontend-inspection", "interaction-flow-design", "screenshot-analysis", "design-implementation-constraints"),
        mission="Create UX flow and implementation-aware design guidance from screenshots and code context.",
    ),
    "architecture_reasoning": RoleAssignment(
        role="Codex Architecture Reasoning Agent",
        provider="codex",
        stage="architecture",
        output_stage="architecture",
        artifact="Architecture Reasoning",
        skills=("repo-reading", "architecture-analysis", "module-boundary-design", "dependency-analysis"),
        mission="Reason about architecture using the actual repository structure and constraints.",
    ),
    "repository_analysis": RoleAssignment(
        role="Codex Repository Analysis Agent",
        provider="codex",
        stage="architecture",
        output_stage="architecture",
        artifact="Repository Analysis",
        skills=("repo-map", "test-command-detection", "dependency-inspection", "existing-pattern-analysis"),
        mission="Read the repository and identify files, patterns, test commands, and integration constraints.",
    ),
    "technical_plan": RoleAssignment(
        role="Codex Technical Plan Agent",
        provider="codex",
        stage="architecture",
        output_stage="architecture",
        artifact="Technical Plan",
        skills=("tdd-planning", "file-level-planning", "risk-analysis", "implementation-sequencing"),
        mission="Produce a concrete implementation plan grounded in repository files and tests.",
    ),
    "implementation": RoleAssignment(
        role="Codex Implementation Agent",
        provider="codex",
        stage="implementation",
        output_stage="implementation",
        artifact="Codex CLI Execution",
        skills=("test-driven-development", "systematic-debugging", "code-editing", "command-execution"),
        mission="Implement the accepted plan in the workspace and run relevant checks.",
    ),
    "test_execution": RoleAssignment(
        role="Deepseek Test Execution Agent",
        provider="deepseek",
        stage="verification",
        output_stage="verification",
        artifact="Test Execution Report",
        skills=("test-strategy", "failure-analysis", "acceptance-evidence-review", "regression-risk-analysis"),
        mission="Execute or analyze tests and produce evidence for acceptance status.",
    ),
    "qa_verification": RoleAssignment(
        role="Codex QA Verification Agent",
        provider="codex",
        stage="verification",
        output_stage="verification",
        artifact="QA Verification Report",
        skills=("command-execution", "artifact-inspection", "screenshot-verification", "acceptance-checking"),
        mission="Verify the integrated result against acceptance using real files, commands, and artifacts.",
    ),
    "fix_loop": RoleAssignment(
        role="Codex Fix Loop Agent",
        provider="codex",
        stage="rework",
        output_stage="implementation",
        artifact="Fix Loop Report",
        skills=("systematic-debugging", "tdd-rework", "diff-analysis", "regression-checking"),
        mission="Fix failed acceptance items and rerun targeted checks.",
    ),
    "code_review": RoleAssignment(
        role="Deepseek Code Review Agent",
        provider="deepseek",
        stage="review",
        output_stage="verification",
        artifact="Code Review Report",
        skills=("diff-review", "logic-risk-review", "acceptance-drift-detection", "security-review"),
        mission="Independently review code changes for bugs, risks, regressions, and missing tests.",
    ),
    "release_review": RoleAssignment(
        role="Deepseek Release Review Agent",
        provider="deepseek",
        stage="release",
        output_stage="release",
        artifact="Release Review",
        skills=("release-checklist", "rollback-planning", "deployment-risk-review", "configuration-review"),
        mission="Review release readiness, rollback, configuration, and known risks.",
    ),
    "delivery_report": RoleAssignment(
        role="Deepseek Delivery Report Agent",
        provider="deepseek",
        stage="delivery",
        output_stage="delivery",
        artifact="Delivery Report",
        skills=("handoff-writing", "user-instructions", "evidence-summary", "known-limits-documentation"),
        mission="Write user-facing delivery instructions, evidence, limitations, and next steps.",
    ),
    "archivist": RoleAssignment(
        role="Deepseek Archivist Agent",
        provider="deepseek",
        stage="archive",
        output_stage="final",
        artifact="Project Memory",
        skills=("artifact-indexing", "memory-update", "lesson-extraction", "reuse-cataloging"),
        mission="Archive stage outputs, decisions, evidence, and reusable learning from the workspace.",
    ),
}


DEFAULT_WORKFLOW_ROLE_KEYS: tuple[str, ...] = (
    "intake",
    "product_research",
    "ux_research",
    "prd",
    "design",
    "architecture_reasoning",
    "repository_analysis",
    "technical_plan",
    "implementation",
    "test_execution",
    "qa_verification",
    "code_review",
    "release_review",
    "delivery_report",
    "archivist",
)


def default_workflow_assignments() -> list[RoleAssignment]:
    return [ROLE_ASSIGNMENTS[key] for key in DEFAULT_WORKFLOW_ROLE_KEYS]
