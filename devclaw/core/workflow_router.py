from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from devclaw.core.role_assignments import DEFAULT_WORKFLOW_ROLE_KEYS


class WorkflowMode(str, Enum):
    FULL_RD = "full-rd"
    TARGETED_CHANGE = "targeted-change"
    BUGFIX = "bugfix"
    VERIFICATION = "verification"
    DOCS_ONLY = "docs-only"
    RESEARCH_ONLY = "research-only"


@dataclass(frozen=True)
class WorkflowRoute:
    mode: WorkflowMode
    reason: str
    run_role_keys: list[str]
    skip_role_keys: list[str]


TARGETED_ROLE_KEYS = [
    "intake",
    "repository_analysis",
    "technical_plan",
    "implementation",
    "test_execution",
    "qa_verification",
    "code_review",
    "release_review",
    "delivery_report",
    "archivist",
]


def route_workflow(intent: str, has_prior_context: bool) -> WorkflowRoute:
    lowered = intent.lower()
    if not has_prior_context:
        return _full_route("No prior DevClaw context exists for this project.")
    if _looks_like_research_only(lowered):
        return _route(
            WorkflowMode.RESEARCH_ONLY,
            "The request asks for research rather than workspace changes.",
            ["intake", "product_research", "ux_research", "delivery_report", "archivist"],
        )
    if _looks_like_docs_only(lowered):
        return _route(
            WorkflowMode.DOCS_ONLY,
            "The request is limited to documentation or copy changes.",
            ["intake", "repository_analysis", "technical_plan", "implementation", "qa_verification", "delivery_report", "archivist"],
        )
    if _looks_like_verification_only(lowered):
        return _route(
            WorkflowMode.VERIFICATION,
            "The request asks to verify existing work.",
            ["intake", "test_execution", "qa_verification", "code_review", "delivery_report", "archivist"],
        )
    if _looks_like_bugfix(lowered):
        return _route(
            WorkflowMode.BUGFIX,
            "Prior context exists and this is a localized fix request.",
            TARGETED_ROLE_KEYS,
        )
    if _looks_like_targeted_change(lowered):
        return _route(
            WorkflowMode.TARGETED_CHANGE,
            "Prior context exists and the request is a localized improvement.",
            TARGETED_ROLE_KEYS,
        )
    return _full_route("The request appears broad enough to require full R&D analysis.")


def _route(mode: WorkflowMode, reason: str, run_role_keys: list[str]) -> WorkflowRoute:
    skipped = [key for key in DEFAULT_WORKFLOW_ROLE_KEYS if key not in run_role_keys]
    return WorkflowRoute(
        mode=mode,
        reason=reason,
        run_role_keys=run_role_keys,
        skip_role_keys=skipped,
    )


def _full_route(reason: str) -> WorkflowRoute:
    return WorkflowRoute(
        mode=WorkflowMode.FULL_RD,
        reason=reason,
        run_role_keys=list(DEFAULT_WORKFLOW_ROLE_KEYS),
        skip_role_keys=[],
    )


def _looks_like_bugfix(intent: str) -> bool:
    return any(token in intent for token in ["bug", "fix", "broken", "error", "failure", "fail", "修复", "问题"])


def _looks_like_targeted_change(intent: str) -> bool:
    return any(
        token in intent
        for token in [
            "optimize",
            "improve",
            "refine",
            "adjust",
            "change",
            "small",
            "localized",
            "display",
            "ui",
            "优化",
            "改进",
            "调整",
            "展示",
        ]
    )


def _looks_like_verification_only(intent: str) -> bool:
    return any(token in intent for token in ["verify", "test only", "retest", "验收", "复测"])


def _looks_like_docs_only(intent: str) -> bool:
    return any(token in intent for token in ["docs", "documentation", "readme", "copy", "文档"])


def _looks_like_research_only(intent: str) -> bool:
    return any(token in intent for token in ["research", "investigate", "调研", "研究"])
