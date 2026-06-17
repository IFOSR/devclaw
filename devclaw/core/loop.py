from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable

from devclaw.adapters.execution import ExecutionAdapter
from devclaw.adapters.verification import VerificationAdapter
from devclaw.agents.engineering import EngineerAgent
from devclaw.agents.qa import QAAgent
from devclaw.agents.roles import write_role_specs
from devclaw.core.checks import generate_acceptance_checks
from devclaw.core.contracts import create_acceptance_contract, create_project_brief
from devclaw.core.context import scan_project_context
from devclaw.core.context_pack import build_context_pack
from devclaw.core.memory import update_memory_after_run
from devclaw.core.models import (
    AgentOutput,
    FinalDeliveryReport,
    GapReport,
    ProjectRunResult,
    VerificationReport,
)
from devclaw.core.role_assignments import ROLE_ASSIGNMENTS, RoleAssignment, default_workflow_assignments
from devclaw.core.sessions import SessionManager
from devclaw.core.stage_docs import (
    stage_run_dir,
    write_agent_stage_document,
    write_final_document,
    write_gap_document,
    write_intake_documents,
    write_stage_index,
    write_stage_reuse_document,
    write_workflow_plan_document,
    write_verification_document,
)
from devclaw.core.workflow_router import WorkflowRoute, route_workflow


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
        self._stage_starts: dict[tuple[str, str], float] = {}
        self._workflow_steps: dict[str, tuple[int, int]] = {}

    def run(self, intent: str, workspace_root: Path) -> ProjectRunResult:
        self._emit("intake", "DevClaw Lead", "started", "Creating project brief and acceptance contract.", mode="local")
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
        stage_root = stage_run_dir(workspace, brief.project_id, session.session_id)
        context_pack = build_context_pack(workspace, intent)
        route = route_workflow(intent, context_pack.has_prior_context)
        workflow_assignments = [ROLE_ASSIGNMENTS[key] for key in route.run_role_keys]
        self._workflow_steps = {
            assignment.role: (index, len(workflow_assignments))
            for index, assignment in enumerate(workflow_assignments, start=1)
        }
        write_workflow_plan_document(stage_root, workflow_assignments, route)
        self._emit(
            "workflow",
            "Workflow Router",
            "planned",
            route.reason,
            mode="local",
            workflow_mode=route.mode.value,
            running_roles=str(len(route.run_role_keys)),
            reused_roles=str(len(route.skip_role_keys)),
        )
        write_role_specs(metadata_dir)
        project_context = scan_project_context(workspace)
        _write_json(context_dir / "project-context.json", project_context.to_dict())

        _write_json(metadata_dir / "project-brief.json", brief.to_dict())
        _write_json(metadata_dir / "acceptance-contract.json", contract.to_dict())
        write_intake_documents(stage_root, brief, contract)
        generate_acceptance_checks(workspace, brief, contract)
        intake_output = self._run_role(ROLE_ASSIGNMENTS["intake"], brief, contract, workspace, [])
        write_agent_stage_document(stage_root, "intake", intake_output, "codex-intake.md")
        self._emit("intake", "DevClaw Lead", "completed", "Acceptance contract generated.", mode="local")

        outputs: list[AgentOutput] = [intake_output]
        self._write_reuse_notes(stage_root, route, context_pack.recent_project_ids)
        for role_key in route.run_role_keys:
            if role_key in {"intake", "implementation", "release_review", "delivery_report", "test_execution", "qa_verification", "code_review", "archivist"}:
                continue
            assignment = ROLE_ASSIGNMENTS[role_key]
            output = self._run_role(assignment, brief, contract, workspace, outputs)
            outputs.append(output)
            write_agent_stage_document(stage_root, assignment.output_stage, output)
        _write_agent_outputs(artifacts_dir, outputs)

        engineer = EngineerAgent(self.execution_adapter)
        qa = QAAgent(self.verification_adapter)
        verification_reports: list[VerificationReport] = []
        gap_reports: list[GapReport] = []

        final_verification: VerificationReport | None = None
        execution_error: str | None = None
        for round_number in range(1, self.max_rounds + 1):
            implementation_assignment = ROLE_ASSIGNMENTS["implementation"]
            self._emit_role(
                implementation_assignment,
                "started",
                f"Round {round_number}: implementing deliverable after technical plan.",
                previous_outputs=outputs,
            )
            try:
                implementation = engineer.run(brief, contract, workspace)
                outputs.append(implementation)
                write_agent_stage_document(
                    stage_root,
                    "implementation",
                    implementation,
                    f"round-{round_number}-implementation.md",
                )
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
                write_verification_document(stage_root, round_number, verification)
                gap = GapReport.from_verification(
                    project_id=brief.project_id,
                    round_number=round_number,
                    verification=verification,
                )
                gap_reports.append(gap)
                _write_json(reports_dir / f"gap-report-round-{round_number}.json", gap.to_dict())
                write_gap_document(stage_root, gap)
                self._emit_role(
                    implementation_assignment,
                    "failed",
                    execution_error,
                    previous_outputs=outputs,
                )
                break
            self._emit_role(
                implementation_assignment,
                "completed",
                f"Round {round_number}: implementation finished.",
                previous_outputs=outputs,
            )
            self._emit("verification", "Deepseek Acceptance Gate", "started", f"Round {round_number}: final acceptance check after QA and review roles.", mode="external")
            for role_key in ["test_execution", "qa_verification", "code_review"]:
                assignment = ROLE_ASSIGNMENTS[role_key]
                output = self._run_role(assignment, brief, contract, workspace, outputs)
                outputs.append(output)
                write_agent_stage_document(
                    stage_root,
                    assignment.output_stage,
                    output,
                    f"round-{round_number}-{_slug(assignment.artifact)}.md",
                )
            verification = qa.run(brief, contract, workspace)
            verification_reports.append(verification)
            _write_json(metadata_dir / "verification-report.json", verification.to_dict())
            _write_json(
                reports_dir / f"verification-report-round-{round_number}.json",
                verification.to_dict(),
            )
            write_verification_document(stage_root, round_number, verification)
            final_verification = verification
            self._emit("verification", "Deepseek Acceptance Gate", verification.status, f"Round {round_number}: {len(verification.blocking_issues)} blocking issue(s).", mode="external")

            if verification.passed():
                if "release_review" in route.run_role_keys:
                    self._emit("release", "Release Handoff", "started", "Preparing release notes and rollback guidance after acceptance passed.", mode="handoff")
                    release = self._run_role(ROLE_ASSIGNMENTS["release_review"], brief, contract, workspace, outputs)
                    outputs.append(release)
                    _write_text(workspace / ".devclaw" / "release" / "latest" / "release-plan.md", release.content)
                    write_agent_stage_document(stage_root, "release", release, f"round-{round_number}-release-plan.md")
                    self._emit("release", "Release Handoff", "completed", release.path or "Release plan generated.", mode="handoff")
                self._emit("delivery", "Delivery Handoff", "started", "Preparing final delivery README and handoff notes after acceptance passed.", mode="handoff")
                delivery = self._run_role(ROLE_ASSIGNMENTS["delivery_report"], brief, contract, workspace, outputs)
                outputs.append(delivery)
                _write_text(workspace / ".devclaw" / "delivery" / "latest" / "README.md", delivery.content)
                write_agent_stage_document(stage_root, "delivery", delivery, f"round-{round_number}-delivery-readme.md")
                self._emit("delivery", "Delivery Handoff", "completed", delivery.path or "Delivery docs generated.", mode="handoff")
                break

            gap = GapReport.from_verification(
                project_id=brief.project_id,
                round_number=round_number,
                verification=verification,
            )
            gap_reports.append(gap)
            _write_json(reports_dir / f"gap-report-round-{round_number}.json", gap.to_dict())
            write_gap_document(stage_root, gap)
            self._emit("rework", "DevClaw Lead", "planned", f"Round {round_number}: gap report generated.", mode="local")

        self._emit("archive", "Archive Handoff", "started", "Updating project memory after all upstream outputs are complete.", mode="handoff")
        archive_warning: str | None = None
        try:
            archive = self._run_role(ROLE_ASSIGNMENTS["archivist"], brief, contract, workspace, outputs)
            outputs.append(archive)
            self._emit("archive", "Archive Handoff", "completed", archive.path or "Project memory updated.", mode="handoff")
        except RuntimeError as error:
            archive_warning = f"Archivist failed after delivery: {error}"
            write_agent_stage_document(
                stage_root,
                "final",
                AgentOutput(
                    agent=ROLE_ASSIGNMENTS["archivist"].role,
                    artifact="Archive Warning",
                    content="\n".join(
                        [
                            "# Archive Warning",
                            "",
                            "Delivery and verification completed, but the archive role failed.",
                            "",
                            "## Error",
                            str(error),
                        ]
                    ),
                ),
                "archive-warning.md",
            )
            self._emit("archive", "Archive Handoff", "failed", archive_warning, mode="handoff")

        passed = bool(final_verification and final_verification.passed())
        known_limits = [
            "Production deployment is not automatic.",
        ]
        if archive_warning:
            known_limits.append(archive_warning)
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
            known_limits=known_limits,
            next_iteration=[
                "Strengthen acceptance-to-test generation for broader project types.",
                "Add isolated integration workflow for complex multi-agent changes.",
            ],
        )
        _write_json(metadata_dir / "final-delivery-report.json", final_report.to_dict())
        write_final_document(stage_root, final_report)
        write_stage_index(stage_root)
        update_memory_after_run(workspace, brief, contract, final_report)
        session_manager.complete(session)
        self._emit("final-report", "DevClaw Lead", "completed", final_report.delivery_status, mode="local")

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
        self._emit(stage, agent, "started", "Running.", mode="local")
        output = fn(*args)
        self._emit(stage, agent, "completed", output.path or output.artifact, mode="local")
        return output

    def _run_role(
        self,
        assignment: RoleAssignment,
        brief,
        contract,
        workspace: Path,
        previous_outputs: list[AgentOutput],
    ) -> AgentOutput:
        self._emit_role(
            assignment,
            "started",
            "Running with role-matched skills after required upstream output is available.",
            previous_outputs=previous_outputs,
        )
        runner = self.execution_adapter if assignment.provider == "codex" else self.verification_adapter
        output = runner.run_role(assignment, brief, contract, workspace, previous_outputs)
        self._emit_role(
            assignment,
            "completed",
            output.artifact,
            previous_outputs=previous_outputs,
            output_stage=assignment.output_stage,
        )
        return output

    def _emit_role(
        self,
        assignment: RoleAssignment,
        status: str,
        message: str,
        previous_outputs: list[AgentOutput],
        output_stage: str | None = None,
    ) -> None:
        step_index, step_total = self._workflow_steps.get(assignment.role, (0, 0))
        self._emit(
            assignment.stage,
            assignment.role,
            status,
            message,
            mode="external",
            step=str(step_index) if step_index else "",
            total_steps=str(step_total) if step_total else "",
            provider=assignment.provider,
            depends_on="user requirement" if not previous_outputs else f"{len(previous_outputs)} upstream output(s)",
            output_stage=output_stage or assignment.output_stage,
            artifact=assignment.artifact,
        )

    def _emit(self, stage: str, agent: str, status: str, message: str = "", mode: str = "", **metadata: str) -> None:
        if self.progress is None:
            return
        timer_key = (stage, agent)
        event = {
            "stage": stage,
            "agent": agent,
            "status": status,
            "message": message,
        }
        if mode:
            event["mode"] = mode
        for metadata_key, value in metadata.items():
            if value:
                event[metadata_key] = value
        if status == "started":
            self._stage_starts[timer_key] = time.monotonic()
        elif timer_key in self._stage_starts:
            event["duration_seconds"] = f"{time.monotonic() - self._stage_starts.pop(timer_key):.6f}"
        elif status in {"completed", "pass", "fail", "failed"}:
            event["duration_seconds"] = "0.000000"
        self.progress(event)

    def _write_reuse_notes(
        self,
        stage_root: Path,
        route: WorkflowRoute,
        source_project_ids: list[str],
    ) -> None:
        if not route.skip_role_keys:
            return
        by_stage: dict[str, list[RoleAssignment]] = {}
        for role_key in route.skip_role_keys:
            assignment = ROLE_ASSIGNMENTS[role_key]
            by_stage.setdefault(assignment.output_stage, []).append(assignment)
        for stage, assignments in by_stage.items():
            write_stage_reuse_document(stage_root, stage, route, source_project_ids, assignments)


def _write_agent_outputs(artifact_dir: Path, outputs: list[AgentOutput]) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for output in outputs:
        filename = output.artifact.lower().replace(" ", "-") + ".md"
        (artifact_dir / filename).write_text(output.content, encoding="utf-8")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "artifact"
