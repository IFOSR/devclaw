from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

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


def route_from_planner_output(output: str, has_prior_context: bool) -> WorkflowRoute:
    data = _extract_planner_json(output)
    mode_value = str(data.get("mode", "")).strip()
    try:
        mode = WorkflowMode(mode_value)
    except ValueError as exc:
        raise ValueError(f"Unsupported workflow mode from planner: {mode_value}") from exc
    reason = str(data.get("reason", "")).strip() or "Codex planner selected this workflow."
    if mode == WorkflowMode.FULL_RD:
        return _full_route(reason)
    if not has_prior_context and mode not in {WorkflowMode.RESEARCH_ONLY, WorkflowMode.DOCS_ONLY}:
        return _full_route("No prior DevClaw context exists; planner decision was upgraded to full R&D.")
    run_role_keys = data.get("run_role_keys")
    if isinstance(run_role_keys, list) and run_role_keys:
        keys = [str(key) for key in run_role_keys]
        _validate_role_keys(keys)
        return _route(mode, reason, keys)
    return _route(mode, reason, _default_role_keys_for_mode(mode))


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


def _extract_planner_json(output: str) -> dict[str, Any]:
    text = output.strip()
    if not text:
        raise ValueError("Workflow planner returned no output.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("Workflow planner output did not contain JSON.")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("Workflow planner JSON must be an object.")
    return data


def _default_role_keys_for_mode(mode: WorkflowMode) -> list[str]:
    if mode == WorkflowMode.RESEARCH_ONLY:
        return ["intake", "product_research", "ux_research", "delivery_report", "archivist"]
    if mode == WorkflowMode.DOCS_ONLY:
        return ["intake", "repository_analysis", "technical_plan", "implementation", "qa_verification", "delivery_report", "archivist"]
    if mode == WorkflowMode.VERIFICATION:
        return ["intake", "test_execution", "qa_verification", "code_review", "delivery_report", "archivist"]
    if mode in {WorkflowMode.BUGFIX, WorkflowMode.TARGETED_CHANGE}:
        return TARGETED_ROLE_KEYS
    return list(DEFAULT_WORKFLOW_ROLE_KEYS)


def _validate_role_keys(keys: list[str]) -> None:
    unknown = [key for key in keys if key not in DEFAULT_WORKFLOW_ROLE_KEYS]
    if unknown:
        raise ValueError(f"Workflow planner returned unknown role keys: {', '.join(unknown)}")


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
            "performance",
            "slow",
            "lag",
            "latency",
            "page",
            "优化",
            "改进",
            "调整",
            "展示",
            "页面",
            "卡顿",
            "加速",
            "性能",
        ]
    )


def _looks_like_verification_only(intent: str) -> bool:
    return any(token in intent for token in ["verify", "test only", "retest", "验收", "复测"])


def _looks_like_docs_only(intent: str) -> bool:
    return any(token in intent for token in ["docs", "documentation", "readme", "copy", "文档"])


def _looks_like_research_only(intent: str) -> bool:
    return any(token in intent for token in ["research", "investigate", "调研", "研究"])
