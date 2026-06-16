from __future__ import annotations

import hashlib
import re

from devclaw.core.models import AcceptanceContract, AcceptanceItem, ProjectBrief


def create_project_brief(intent: str) -> ProjectBrief:
    normalized = " ".join(intent.strip().split())
    if not normalized:
        raise ValueError("intent must not be empty")

    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    target_user = _infer_target_user(normalized)
    return ProjectBrief(
        project_id=f"devclaw_{digest}",
        intent=normalized,
        goal=normalized,
        target_user=target_user,
        assumptions=[
            "Deliver v0.1 as a local runnable artifact first.",
            "Prefer measurable implementation and verification evidence.",
            "Escalate production deployment or external side effects for human review.",
        ],
    )


def create_acceptance_contract(brief: ProjectBrief) -> AcceptanceContract:
    return AcceptanceContract(
        project_id=brief.project_id,
        goal=brief.goal,
        target_user=brief.target_user,
        background=f"User requested: {brief.intent}",
        scope=[
            "Clarify the product requirement.",
            "Design a usable product or Agent flow.",
            "Implement a runnable v0.1 deliverable.",
            "Verify the deliverable against blocking acceptance criteria.",
            "Package delivery documentation.",
        ],
        non_goals=[
            "Automatic production deployment.",
            "Unapproved external side effects.",
            "Non-R&D company functions.",
        ],
        deliverables=[
            "Research reports",
            "Runnable implementation",
            "README",
            "Verification report",
            "Final delivery report",
        ],
        research_acceptance=[
            _item(
                "RES1",
                "Product, UX, and technical research are completed before implementation.",
                "research",
                "Inspect research reports in .devclaw/artifacts.",
            )
        ],
        functional_acceptance=[
            _item(
                "F1",
                "The deliverable implements the core user-requested workflow.",
                "functional",
                "Run the generated deliverable with sample input.",
            )
        ],
        ux_acceptance=[
            _item(
                "UX1",
                "The user can understand how to operate the product or Agent.",
                "ux",
                "Inspect usage guide and example flow.",
            )
        ],
        technical_acceptance=[
            _item(
                "T1",
                "The deliverable is runnable in the target local environment.",
                "technical",
                "Run documented start command.",
            )
        ],
        quality_acceptance=[
            _item(
                "Q1",
                "The deliverable handles invalid or incomplete inputs safely.",
                "quality",
                "Run negative-path checks or inspect fallback behavior.",
            )
        ],
        release_acceptance=[
            _item(
                "R1",
                "Release, configuration, and rollback notes are documented.",
                "release",
                "Inspect release checklist.",
            )
        ],
        documentation_acceptance=[
            _item(
                "D1",
                "README, setup, usage, and known limitations are documented.",
                "documentation",
                "Inspect delivery package.",
            )
        ],
        blocking_criteria=[
            "Core workflow works.",
            "Runnable implementation exists.",
            "Verification report exists.",
            "Final delivery report exists.",
        ],
        non_blocking_criteria=[
            "Future enhancements are recorded.",
            "Known limitations are explicit.",
        ],
        human_review_required=[
            {
                "condition": "Production deployment, paid API usage, or irreversible data change is requested.",
                "reason": "High-risk operations require explicit human authorization.",
            }
        ],
        stop_condition=[
            "all_blocking_acceptance_passed",
            "non_blocking_issues_recorded",
            "final_delivery_report_generated",
        ],
    )


def _item(
    item_id: str,
    description: str,
    category: str,
    verification_method: str,
) -> AcceptanceItem:
    return AcceptanceItem(
        id=item_id,
        description=description,
        category=category,
        priority="blocking",
        verification_method=verification_method,
    )


def _infer_target_user(intent: str) -> str:
    match = re.search(r"\bfor ([a-zA-Z0-9 _-]+)", intent)
    if match:
        return match.group(1).strip()
    return "requesting user"
