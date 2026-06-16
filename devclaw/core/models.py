from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProjectBrief:
    project_id: str
    intent: str
    goal: str
    target_user: str
    assumptions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AcceptanceItem:
    id: str
    description: str
    category: str
    priority: str
    verification_method: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AcceptanceContract:
    project_id: str
    goal: str
    target_user: str
    background: str
    scope: list[str]
    non_goals: list[str]
    deliverables: list[str]
    research_acceptance: list[AcceptanceItem]
    functional_acceptance: list[AcceptanceItem]
    ux_acceptance: list[AcceptanceItem]
    technical_acceptance: list[AcceptanceItem]
    quality_acceptance: list[AcceptanceItem]
    release_acceptance: list[AcceptanceItem]
    documentation_acceptance: list[AcceptanceItem]
    blocking_criteria: list[str]
    non_blocking_criteria: list[str]
    human_review_required: list[dict[str, str]]
    stop_condition: list[str]

    def all_items(self) -> list[AcceptanceItem]:
        return [
            *self.research_acceptance,
            *self.functional_acceptance,
            *self.ux_acceptance,
            *self.technical_acceptance,
            *self.quality_acceptance,
            *self.release_acceptance,
            *self.documentation_acceptance,
        ]

    def blocking_items(self) -> list[AcceptanceItem]:
        return [item for item in self.all_items() if item.priority == "blocking"]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentOutput:
    agent: str
    artifact: str
    content: str
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationReport:
    status: str
    failed_acceptance: list[str]
    blocking_issues: list[str]
    non_blocking_issues: list[str]
    evidence: list[str]

    def passed(self) -> bool:
        return self.status == "pass" and not self.failed_acceptance and not self.blocking_issues

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GapReport:
    project_id: str
    round_number: int
    status: str
    failed_acceptance: list[dict[str, str]]
    root_cause: list[dict[str, str]]
    rework_tasks: list[dict[str, str]]
    next_verification: list[dict[str, str]]
    human_review_needed: list[dict[str, str]]

    @classmethod
    def from_verification(
        cls,
        project_id: str,
        round_number: int,
        verification: VerificationReport,
    ) -> "GapReport":
        failed_acceptance = [
            {
                "acceptance_id": item,
                "description": f"Acceptance item {item} did not pass verification.",
                "severity": "blocking",
                "evidence": "; ".join(verification.evidence),
            }
            for item in verification.failed_acceptance
        ]
        if not failed_acceptance and verification.blocking_issues:
            failed_acceptance = [
                {
                    "acceptance_id": "UNKNOWN",
                    "description": issue,
                    "severity": "blocking",
                    "evidence": "; ".join(verification.evidence),
                }
                for issue in verification.blocking_issues
            ]

        root_cause = [
            {
                "owner_agent": "Engineer Agent",
                "issue": issue,
                "reason": "Implementation or packaging did not satisfy verification.",
            }
            for issue in verification.blocking_issues
        ]
        rework_tasks = [
            {
                "agent": "Engineer Agent",
                "task": f"Fix failed acceptance: {item['acceptance_id']}",
                "expected_output": "Updated runnable deliverable and supporting files.",
                "verification_required": "QA Agent must rerun failed acceptance checks.",
            }
            for item in failed_acceptance
        ]
        next_verification = [
            {
                "item": item["acceptance_id"],
                "method": "Re-run verification against acceptance contract.",
            }
            for item in failed_acceptance
        ]
        return cls(
            project_id=project_id,
            round_number=round_number,
            status="fail",
            failed_acceptance=failed_acceptance,
            root_cause=root_cause,
            rework_tasks=rework_tasks,
            next_verification=next_verification,
            human_review_needed=[],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FinalDeliveryReport:
    project_id: str
    version: str
    goal: str
    delivery_status: str
    delivered_items: list[AgentOutput]
    acceptance_result: dict[str, Any]
    test_result: dict[str, Any]
    run_instructions: dict[str, Any]
    deployment_notes: dict[str, Any]
    known_limits: list[str]
    next_iteration: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectRunResult:
    project_id: str
    workspace: Path
    brief: ProjectBrief
    contract: AcceptanceContract
    outputs: list[AgentOutput]
    verification_reports: list[VerificationReport]
    gap_reports: list[GapReport]
    final_report: FinalDeliveryReport
