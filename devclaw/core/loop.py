from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from devclaw.adapters.execution import ExecutionAdapter
from devclaw.adapters.verification import VerificationAdapter
from devclaw.agents.architecture import ArchitectAgent, TechnicalResearchAgent
from devclaw.agents.archivist import ArchivistAgent
from devclaw.agents.delivery import DeliveryAgent
from devclaw.agents.design import DesignerAgent, UXResearchAgent
from devclaw.agents.engineering import EngineerAgent
from devclaw.agents.product import PMAgent, ProductResearchAgent
from devclaw.agents.qa import QAAgent
from devclaw.agents.release import ReleaseAgent
from devclaw.agents.roles import write_role_specs
from devclaw.core.checks import generate_acceptance_checks
from devclaw.core.contracts import create_acceptance_contract, create_project_brief
from devclaw.core.context import scan_project_context
from devclaw.core.memory import update_memory_after_run
from devclaw.core.models import (
    AgentOutput,
    FinalDeliveryReport,
    GapReport,
    ProjectRunResult,
    VerificationReport,
)
from devclaw.core.sessions import SessionManager


class DevClawLead:
    """Coordinates the acceptance-driven v0.1 R&D loop."""

    def __init__(
        self,
        execution_adapter: ExecutionAdapter,
        verification_adapter: VerificationAdapter,
        max_rounds: int = 3,
        progress: Callable[[dict[str, str]], None] | None = None,
    ):
        if max_rounds < 1:
            raise ValueError("max_rounds must be at least 1")
        self.execution_adapter = execution_adapter
        self.verification_adapter = verification_adapter
        self.max_rounds = max_rounds
        self.progress = progress

    def run(self, intent: str, workspace_root: Path) -> ProjectRunResult:
        self._emit("intake", "DevClaw Lead", "started", "Creating project brief and acceptance contract.")
        session_manager = SessionManager(workspace_root)
        session = session_manager.begin(intent)
        brief = create_project_brief(intent)
        contract = create_acceptance_contract(brief)
        workspace = workspace_root
        metadata_dir = workspace / ".devclaw"
        reports_dir = metadata_dir / "reports"
        artifacts_dir = metadata_dir / "artifacts"
        context_dir = metadata_dir / "context"
        workspace.mkdir(parents=True, exist_ok=True)
        metadata_dir.mkdir(parents=True, exist_ok=True)
        reports_dir.mkdir(parents=True, exist_ok=True)
        context_dir.mkdir(parents=True, exist_ok=True)
        write_role_specs(metadata_dir)
        project_context = scan_project_context(workspace)
        _write_json(context_dir / "project-context.json", project_context.to_dict())

        _write_json(metadata_dir / "project-brief.json", brief.to_dict())
        _write_json(metadata_dir / "acceptance-contract.json", contract.to_dict())
        generate_acceptance_checks(workspace, brief, contract)
        self._emit("intake", "DevClaw Lead", "completed", "Acceptance contract generated.")

        outputs: list[AgentOutput] = []
        outputs.append(self._run_agent("research", "Product Research Agent", ProductResearchAgent().run, brief, contract))
        outputs.append(self._run_agent("product", "PM Agent", PMAgent().run, brief, contract))
        outputs.append(self._run_agent("research", "UX Research Agent", UXResearchAgent().run, brief, contract))
        outputs.append(self._run_agent("design", "Designer Agent", DesignerAgent().run, brief, contract))
        outputs.append(self._run_agent("research", "Technical Research Agent", TechnicalResearchAgent().run, brief, contract))
        outputs.append(self._run_agent("architecture", "Architect Agent", ArchitectAgent().run, brief, contract))
        _write_agent_outputs(artifacts_dir, outputs)

        engineer = EngineerAgent(self.execution_adapter)
        qa = QAAgent(self.verification_adapter)
        verification_reports: list[VerificationReport] = []
        gap_reports: list[GapReport] = []

        final_verification: VerificationReport | None = None
        execution_error: str | None = None
        for round_number in range(1, self.max_rounds + 1):
            self._emit("implementation", "Codex Implementation Agent", "started", f"Round {round_number}: implementing deliverable.")
            try:
                outputs.append(engineer.run(brief, contract, workspace))
            except RuntimeError as error:
                execution_error = str(error)
                verification = VerificationReport(
                    status="fail",
                    failed_acceptance=["EXECUTION"],
                    blocking_issues=[execution_error],
                    non_blocking_issues=[],
                    evidence=[],
                )
                verification_reports.append(verification)
                final_verification = verification
                _write_json(metadata_dir / "verification-report.json", verification.to_dict())
                gap = GapReport.from_verification(
                    project_id=brief.project_id,
                    round_number=round_number,
                    verification=verification,
                )
                gap_reports.append(gap)
                _write_json(reports_dir / f"gap-report-round-{round_number}.json", gap.to_dict())
                self._emit("implementation", "Codex Implementation Agent", "failed", execution_error)
                break
            self._emit("implementation", "Codex Implementation Agent", "completed", f"Round {round_number}: implementation finished.")
            self._emit("release", "Release Agent", "started", "Preparing release notes and rollback guidance.")
            release = ReleaseAgent().run(brief, contract, workspace)
            outputs.append(release)
            self._emit("release", "Release Agent", "completed", release.path or "Release plan generated.")
            self._emit("delivery", "Delivery Agent", "started", "Preparing delivery README and handoff notes.")
            delivery = DeliveryAgent().run(brief, contract, workspace, outputs)
            outputs.append(delivery)
            self._emit("delivery", "Delivery Agent", "completed", delivery.path or "Delivery docs generated.")
            self._emit("verification", "Deepseek QA Agent", "started", f"Round {round_number}: verifying acceptance criteria.")
            verification = qa.run(brief, contract, workspace)
            verification_reports.append(verification)
            _write_json(metadata_dir / "verification-report.json", verification.to_dict())
            _write_json(
                reports_dir / f"verification-report-round-{round_number}.json",
                verification.to_dict(),
            )
            final_verification = verification
            self._emit("verification", "Deepseek QA Agent", verification.status, f"Round {round_number}: {len(verification.blocking_issues)} blocking issue(s).")

            if verification.passed():
                break

            gap = GapReport.from_verification(
                project_id=brief.project_id,
                round_number=round_number,
                verification=verification,
            )
            gap_reports.append(gap)
            _write_json(reports_dir / f"gap-report-round-{round_number}.json", gap.to_dict())
            self._emit("rework", "DevClaw Lead", "planned", f"Round {round_number}: gap report generated.")

        self._emit("archive", "Archivist Agent", "started", "Updating project memory.")
        archive = ArchivistAgent().run(brief, contract, workspace, outputs)
        outputs.append(archive)
        self._emit("archive", "Archivist Agent", "completed", archive.path or "Project memory updated.")

        passed = bool(final_verification and final_verification.passed())
        final_report = FinalDeliveryReport(
            project_id=brief.project_id,
            version="0.1.0",
            goal=brief.goal,
            delivery_status="delivered" if passed else "failed",
            delivered_items=outputs,
            acceptance_result={
                "blocking_passed": passed,
                "gap_report_count": len(gap_reports),
            },
            test_result={
                "summary": "passed" if passed else (execution_error or "failed"),
                "verification_rounds": len(verification_reports),
                "latest_evidence": final_verification.evidence if final_verification else [],
            },
            run_instructions={
                "setup": "Use Python 3.10+.",
                "start": "Follow the delivered project README or generated usage notes.",
                "configure": "Configuration depends on the selected executor and verifier adapters.",
                "executor": type(self.execution_adapter).__name__,
                "verifier": type(self.verification_adapter).__name__,
            },
            deployment_notes={
                "environment": "local",
                "release_steps": "Follow release-plan.md.",
                "rollback_steps": "Restore previous workspace copy.",
            },
            known_limits=[
                "Production deployment is not automatic.",
            ],
            next_iteration=[
                "Strengthen acceptance-to-test generation for broader project types.",
                "Add isolated integration workflow for complex multi-agent changes.",
            ],
        )
        _write_json(metadata_dir / "final-delivery-report.json", final_report.to_dict())
        update_memory_after_run(workspace, brief, contract, final_report)
        session_manager.complete(session)
        self._emit("final-report", "DevClaw Lead", "completed", final_report.delivery_status)

        return ProjectRunResult(
            project_id=brief.project_id,
            workspace=workspace,
            brief=brief,
            contract=contract,
            outputs=outputs,
            verification_reports=verification_reports,
            gap_reports=gap_reports,
            final_report=final_report,
        )

    def _run_agent(self, stage: str, agent: str, fn, *args) -> AgentOutput:
        self._emit(stage, agent, "started", "Running.")
        output = fn(*args)
        self._emit(stage, agent, "completed", output.path or output.artifact)
        return output

    def _emit(self, stage: str, agent: str, status: str, message: str = "") -> None:
        if self.progress is None:
            return
        self.progress(
            {
                "stage": stage,
                "agent": agent,
                "status": status,
                "message": message,
            }
        )


def _write_agent_outputs(artifact_dir: Path, outputs: list[AgentOutput]) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for output in outputs:
        filename = output.artifact.lower().replace(" ", "-") + ".md"
        (artifact_dir / filename).write_text(output.content, encoding="utf-8")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
