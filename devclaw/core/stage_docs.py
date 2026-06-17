from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from devclaw.core.models import (
    AcceptanceContract,
    AgentOutput,
    FinalDeliveryReport,
    GapReport,
    ProjectBrief,
    VerificationReport,
)
from devclaw.core.role_assignments import RoleAssignment
from devclaw.core.workflow_router import WorkflowRoute


STAGE_DIRS = {
    "intake": "00-intake",
    "research": "01-research",
    "product": "02-product",
    "design": "03-design",
    "architecture": "04-architecture",
    "implementation": "05-implementation",
    "release": "06-release",
    "delivery": "07-delivery",
    "verification": "08-verification",
    "final": "09-final",
}


def stage_run_dir(root: Path, project_id: str, session_id: str) -> Path:
    return root / ".devclaw" / "stages" / project_id / session_id


def write_intake_documents(stage_root: Path, brief: ProjectBrief, contract: AcceptanceContract) -> list[Path]:
    paths = [
        write_stage_document(
            stage_root,
            "intake",
            "project-brief.md",
            _project_brief_markdown(brief),
        ),
        write_stage_document(
            stage_root,
            "intake",
            "acceptance-contract.md",
            _acceptance_contract_markdown(contract),
        ),
    ]
    attachment_markdown = _attachments_markdown(brief.intent)
    if attachment_markdown:
        paths.append(
            write_stage_document(
                stage_root,
                "intake",
                "attachments.md",
                attachment_markdown,
            )
        )
    return paths


def write_workflow_plan_document(
    stage_root: Path,
    assignments: list[RoleAssignment],
    route: WorkflowRoute | None = None,
) -> Path:
    return write_stage_document(stage_root, "", "workflow-plan.md", _workflow_plan_markdown(assignments, route))


def write_stage_reuse_document(
    stage_root: Path,
    stage: str,
    route: WorkflowRoute,
    source_project_ids: list[str],
    reused_assignments: list[RoleAssignment],
) -> Path:
    return write_stage_document(
        stage_root,
        stage,
        "stage-reuse-note.md",
        _stage_reuse_markdown(route, source_project_ids, reused_assignments),
    )


def write_agent_stage_document(
    stage_root: Path,
    stage: str,
    output: AgentOutput,
    filename: str | None = None,
) -> Path:
    return write_stage_document(
        stage_root,
        stage,
        filename or f"{_slug(output.artifact)}.md",
        output.content,
    )


def write_round_agent_stage_document(
    stage_root: Path,
    stage: str,
    round_number: int,
    output: AgentOutput,
) -> Path:
    filename = f"round-{round_number}-{_slug(output.artifact)}.md"
    return write_agent_stage_document(stage_root, stage, output, filename)


def write_verification_document(
    stage_root: Path,
    round_number: int,
    report: VerificationReport,
) -> Path:
    return write_stage_document(
        stage_root,
        "verification",
        f"round-{round_number}-verification-report.md",
        _verification_markdown(round_number, report),
    )


def write_gap_document(stage_root: Path, gap: GapReport) -> Path:
    return write_stage_document(
        stage_root,
        "verification",
        f"round-{gap.round_number}-gap-report.md",
        _gap_markdown(gap),
    )


def write_final_document(stage_root: Path, report: FinalDeliveryReport) -> Path:
    return write_stage_document(
        stage_root,
        "final",
        "final-delivery-report.md",
        _final_report_markdown(report),
    )


def write_stage_index(stage_root: Path) -> Path:
    stages_dir = stage_root
    docs = [
        path
        for path in sorted(stages_dir.rglob("*.md"))
        if path.name != "index.md"
    ]
    lines = [
        "# DevClaw Stage Review Index",
        "",
        "Every DevClaw phase writes a human-reviewable document here so users can inspect the AI team's reasoning and evidence.",
        "",
        "This session uses a sequential workflow: each Agent starts only after the previous step has produced its output. Parallel execution is available only through the explicit `/parallel-run` command, not in the default R&D loop.",
        "",
        "## Stage Documents",
    ]
    if docs:
        lines.extend(f"- [{path.relative_to(stages_dir)}]({path.relative_to(stages_dir)})" for path in docs)
    else:
        lines.append("- No stage documents generated yet.")
    return write_stage_document(stage_root, "", "index.md", "\n".join(lines))


def write_stage_document(stage_root: Path, stage: str, filename: str, content: str) -> Path:
    base = stage_root
    directory = base / STAGE_DIRS[stage] if stage else base
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    text = content if content.startswith("#") else f"# {filename.removesuffix('.md').replace('-', ' ').title()}\n\n{content}"
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path


def _project_brief_markdown(brief: ProjectBrief) -> str:
    return "\n".join(
        [
            f"# Project Brief: {brief.project_id}",
            "",
            "## Intent",
            brief.intent,
            "",
            "## Goal",
            brief.goal,
            "",
            "## Target User",
            brief.target_user,
            "",
            "## Assumptions",
            *_bullets(brief.assumptions),
        ]
    )


def _acceptance_contract_markdown(contract: AcceptanceContract) -> str:
    lines = [
        f"# Acceptance Contract: {contract.project_id}",
        "",
        "## Goal",
        contract.goal,
        "",
        "## Scope",
        *_bullets(contract.scope),
        "",
        "## Non-goals",
        *_bullets(contract.non_goals),
        "",
        "## Blocking Stop Condition",
        *_bullets(contract.stop_condition),
        "",
        "## Acceptance Criteria",
    ]
    for item in contract.all_items():
        lines.append(
            f"- {item.id} [{item.category}/{item.priority}]: {item.description} Verification: {item.verification_method}"
        )
    return "\n".join(lines)


def _attachments_markdown(intent: str) -> str:
    marker = "Attached screenshots:"
    if marker not in intent:
        return ""
    _, _, attachment_text = intent.partition(marker)
    return "\n".join(
        [
            "# Attachments",
            "",
            "## Attached Screenshots",
            attachment_text.strip(),
        ]
    )


def _workflow_plan_markdown(assignments: list[RoleAssignment], route: WorkflowRoute | None) -> str:
    lines = [
        "# Workflow Plan",
        "",
        "## Execution Model",
        "- Execution: sequential",
        f"- Mode: {route.mode.value if route else 'full-rd'}",
        "- Dependency rule: each step consumes the accumulated outputs from all earlier steps.",
        "- Parallelism: disabled for the default R&D loop; only `/parallel-run` runs independent Codex subtasks in parallel.",
    ]
    if route:
        lines.extend(
            [
                f"- Route reason: {route.reason}",
                f"- Running roles: {', '.join(route.run_role_keys)}",
                f"- Reused roles: {', '.join(route.skip_role_keys) or 'none'}",
            ]
        )
    lines.extend(["", "## Step Order"])
    total = len(assignments)
    for index, assignment in enumerate(assignments, start=1):
        dependency = "User requirement and repository context" if index == 1 else "All previous step outputs"
        lines.extend(
            [
                f"### {index:02d}/{total:02d} {assignment.role}",
                f"- Provider: {assignment.provider}",
                f"- Stage: {assignment.output_stage}",
                f"- Artifact: {assignment.artifact}",
                f"- Depends on: {dependency}",
                f"- Skills: {', '.join(assignment.skills)}",
                f"- Mission: {assignment.mission}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def _stage_reuse_markdown(
    route: WorkflowRoute,
    source_project_ids: list[str],
    reused_assignments: list[RoleAssignment],
) -> str:
    lines = [
        "# Stage Reuse Note",
        "",
        "Status: reused",
        f"Workflow mode: {route.mode.value}",
        f"Reason: {route.reason}",
        f"Source projects: {', '.join(source_project_ids) or 'project memory and recent sessions'}",
        "",
        "## Reused Roles",
    ]
    if reused_assignments:
        lines.extend(
            f"- {assignment.role}: reused prior {assignment.artifact}"
            for assignment in reused_assignments
        )
    else:
        lines.append("- None")
    return "\n".join(lines)


def _verification_markdown(round_number: int, report: VerificationReport) -> str:
    return "\n".join(
        [
            f"# Verification Report: Round {round_number}",
            "",
            "## Status",
            report.status,
            "",
            "## Failed Acceptance",
            *_bullets(report.failed_acceptance),
            "",
            "## Blocking Issues",
            *_bullets(report.blocking_issues),
            "",
            "## Non-blocking Issues",
            *_bullets(report.non_blocking_issues),
            "",
            "## Evidence",
            *_bullets(report.evidence),
        ]
    )


def _gap_markdown(gap: GapReport) -> str:
    lines = [
        f"# Gap Report: Round {gap.round_number}",
        "",
        "## Status",
        gap.status,
        "",
        "## Failed Acceptance",
        *_dict_bullets(gap.failed_acceptance),
        "",
        "## Root Cause",
        *_dict_bullets(gap.root_cause),
        "",
        "## Rework Tasks",
        *_dict_bullets(gap.rework_tasks),
        "",
        "## Next Verification",
        *_dict_bullets(gap.next_verification),
    ]
    return "\n".join(lines)


def _final_report_markdown(report: FinalDeliveryReport) -> str:
    return "\n".join(
        [
            f"# Final Delivery Report: {report.project_id}",
            "",
            "## Delivery Status",
            report.delivery_status,
            "",
            "## Goal",
            report.goal,
            "",
            "## Delivered Items",
            *[
                f"- {item.artifact}: {item.path or item.agent}"
                for item in report.delivered_items
            ],
            "",
            "## Acceptance Result",
            *_dict_bullets([report.acceptance_result]),
            "",
            "## Test Result",
            *_dict_bullets([report.test_result]),
            "",
            "## Run Instructions",
            *_dict_bullets([report.run_instructions]),
            "",
            "## Deployment Notes",
            *_dict_bullets([report.deployment_notes]),
            "",
            "## Known Limits",
            *_bullets(report.known_limits),
            "",
            "## Next Iteration",
            *_bullets(report.next_iteration),
        ]
    )


def _bullets(items: Iterable[str]) -> list[str]:
    values = [str(item) for item in items if str(item)]
    return [f"- {item}" for item in values] or ["- None"]


def _dict_bullets(items: Iterable[dict[str, object]]) -> list[str]:
    values = []
    for item in items:
        parts = [f"{key}: {value}" for key, value in item.items()]
        values.append("- " + "; ".join(parts))
    return values or ["- None"]


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "artifact"
