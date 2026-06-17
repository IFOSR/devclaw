from pathlib import Path

from tests.fakes import TestExecutionAdapter
from tests.fakes import TestVerificationAdapter
from devclaw.core.loop import DevClawLead
from devclaw.core.models import ProjectRunResult, VerificationReport


class FlakyVerificationAdapter:
    def __init__(self):
        self.calls = 0
        self.local = TestVerificationAdapter()

    def run_role(self, assignment, brief, contract, workspace: Path, previous_outputs):
        return self.local.run_role(assignment, brief, contract, workspace, previous_outputs)

    def verify(self, brief, contract, workspace: Path):
        self.calls += 1
        if self.calls == 1:
            return VerificationReport(
                status="fail",
                failed_acceptance=["F1"],
                blocking_issues=["Simulated first-round QA failure."],
                non_blocking_issues=[],
                evidence=["first round failed"],
            )
        return self.local.verify(brief, contract, workspace)


def test_devclaw_loop_reworks_until_acceptance_passes(tmp_path: Path):
    verifier = FlakyVerificationAdapter()
    lead = DevClawLead(
        execution_adapter=TestExecutionAdapter(),
        verification_adapter=verifier,
        max_rounds=3,
    )

    result = lead.run("Build a customer feedback triage Agent", tmp_path)

    assert isinstance(result, ProjectRunResult)
    assert result.final_report.delivery_status == "delivered"
    assert result.workspace == tmp_path
    assert len(result.gap_reports) == 1
    assert result.gap_reports[0].rework_tasks[0]["agent"] == "Engineer Agent"
    assert verifier.calls == 2
    assert (result.workspace / ".devclaw" / "acceptance-contract.json").exists()
    assert (result.workspace / ".devclaw" / "verification-report.json").exists()
    assert (result.workspace / ".devclaw" / "final-delivery-report.json").exists()
    assert (result.workspace / "agent.py").exists()


def test_devclaw_loop_fails_when_max_rounds_are_exhausted(tmp_path: Path):
    class AlwaysFailVerificationAdapter:
        def __init__(self):
            self.local = TestVerificationAdapter()

        def run_role(self, assignment, brief, contract, workspace: Path, previous_outputs):
            return self.local.run_role(assignment, brief, contract, workspace, previous_outputs)

        def verify(self, brief, contract, workspace: Path):
            return VerificationReport(
                status="fail",
                failed_acceptance=["F1"],
                blocking_issues=["Always broken."],
                non_blocking_issues=[],
                evidence=["failed"],
            )

    lead = DevClawLead(
        execution_adapter=TestExecutionAdapter(),
        verification_adapter=AlwaysFailVerificationAdapter(),
        max_rounds=2,
    )

    result = lead.run("Build a customer feedback triage Agent", tmp_path)

    assert result.final_report.delivery_status == "failed"
    assert len(result.gap_reports) == 2
    assert result.final_report.acceptance_result["blocking_passed"] is False


def test_devclaw_loop_returns_failed_report_when_engineer_raises(tmp_path: Path):
    class BrokenExecutionAdapter:
        def run_role(self, assignment, brief, contract, workspace: Path, previous_outputs):
            return TestExecutionAdapter().run_role(assignment, brief, contract, workspace, previous_outputs)

        def execute(self, brief, contract, workspace: Path):
            raise RuntimeError("Codex CLI execution timed out")

    lead = DevClawLead(
        execution_adapter=BrokenExecutionAdapter(),
        verification_adapter=TestVerificationAdapter(),
        max_rounds=1,
    )

    result = lead.run("Build a customer feedback triage Agent", tmp_path)

    assert result.final_report.delivery_status == "failed"
    assert result.final_report.acceptance_result["blocking_passed"] is False
    assert "Codex CLI execution timed out" in result.final_report.test_result["summary"]
    assert (tmp_path / ".devclaw" / "final-delivery-report.json").exists()


def test_devclaw_loop_reports_actual_adapter_modes(tmp_path: Path):
    lead = DevClawLead(
        execution_adapter=TestExecutionAdapter(),
        verification_adapter=TestVerificationAdapter(),
        max_rounds=1,
    )

    result = lead.run("Build a customer feedback triage Agent", tmp_path)

    assert result.final_report.run_instructions["executor"] == "TestExecutionAdapter"
    assert result.final_report.run_instructions["verifier"] == "TestVerificationAdapter"
    assert "local adapter" not in " ".join(result.final_report.known_limits).lower()


def test_devclaw_loop_prepares_release_and_delivery_artifacts_after_acceptance(tmp_path: Path):
    class ArtifactAwareVerificationAdapter:
        def __init__(self):
            self.local = TestVerificationAdapter()

        def run_role(self, assignment, brief, contract, workspace: Path, previous_outputs):
            return self.local.run_role(assignment, brief, contract, workspace, previous_outputs)

        def verify(self, brief, contract, workspace: Path):
            release_plan = workspace / ".devclaw" / "release" / "latest" / "release-plan.md"
            delivery_readme = workspace / ".devclaw" / "delivery" / "latest" / "README.md"
            premature = [
                str(path.relative_to(workspace))
                for path in [release_plan, delivery_readme]
                if path.exists()
            ]
            return VerificationReport(
                status="pass" if not premature else "fail",
                failed_acceptance=[] if not premature else ["ORDER"],
                blocking_issues=[] if not premature else [f"Final delivery artifacts were created before acceptance: {', '.join(premature)}"],
                non_blocking_issues=[],
                evidence=["release/delivery artifacts are generated after acceptance"] if not premature else [],
            )

    lead = DevClawLead(
        execution_adapter=TestExecutionAdapter(),
        verification_adapter=ArtifactAwareVerificationAdapter(),
        max_rounds=1,
    )

    result = lead.run("Build a customer feedback triage Agent", tmp_path)

    assert result.final_report.delivery_status == "delivered"
    assert (tmp_path / ".devclaw" / "release" / "latest" / "release-plan.md").exists()
    assert (tmp_path / ".devclaw" / "delivery" / "latest" / "README.md").exists()


def test_devclaw_loop_emits_progress_events_for_major_stages(tmp_path: Path):
    events: list[dict[str, str]] = []
    lead = DevClawLead(
        execution_adapter=TestExecutionAdapter(),
        verification_adapter=TestVerificationAdapter(),
        max_rounds=1,
        progress=events.append,
    )

    result = lead.run("Build a customer feedback triage Agent", tmp_path)

    assert result.final_report.delivery_status == "delivered"
    rendered = [f"{event['stage']}:{event['agent']}:{event['status']}" for event in events]
    assert "research:Deepseek Product Research Agent:started" in rendered
    assert "product:Deepseek PRD Agent:started" in rendered
    assert "design:Codex Design Agent:started" in rendered
    assert "architecture:Codex Architecture Reasoning Agent:started" in rendered
    assert "implementation:Codex Implementation Agent:started" in rendered
    assert "release:Release Handoff:started" in rendered
    assert "delivery:Delivery Handoff:started" in rendered
    assert "verification:Deepseek Acceptance Gate:started" in rendered
    assert "archive:Archive Handoff:started" in rendered
    assert "final-report:DevClaw Lead:completed" in rendered
    role_started = [
        event for event in events
        if event["status"] == "started" and event["agent"].endswith("Agent") and "step" in event
    ]
    assert role_started
    assert all("depends_on" in event for event in role_started)
    assert all("output_stage" in event for event in role_started)
    completed = [event for event in events if event["status"] in {"completed", "pass"}]
    assert completed
    assert all("duration_seconds" in event for event in completed)
    assert all(float(event["duration_seconds"]) >= 0 for event in completed)
    completed_roles = [
        event for event in completed
        if event["agent"].endswith("Agent") and "step" in event
    ]
    assert completed_roles
    assert any(float(event["duration_seconds"]) > 0 for event in completed_roles)


def test_devclaw_loop_writes_reviewable_markdown_for_each_stage(tmp_path: Path):
    lead = DevClawLead(
        execution_adapter=TestExecutionAdapter(),
        verification_adapter=TestVerificationAdapter(),
        max_rounds=1,
    )

    result = lead.run("Build a customer feedback triage Agent", tmp_path)

    assert result.final_report.delivery_status == "delivered"
    project_stages_dir = tmp_path / ".devclaw" / "stages" / result.project_id
    session_dirs = list(project_stages_dir.iterdir())
    assert len(session_dirs) == 1
    stages_dir = session_dirs[0]
    expected_docs = [
        stages_dir / "00-intake" / "project-brief.md",
        stages_dir / "00-intake" / "acceptance-contract.md",
        stages_dir / "01-research" / "product-research-report.md",
        stages_dir / "01-research" / "ux-research-report.md",
        stages_dir / "02-product" / "prd.md",
        stages_dir / "03-design" / "ux-flow.md",
        stages_dir / "04-architecture" / "architecture-reasoning.md",
        stages_dir / "04-architecture" / "repository-analysis.md",
        stages_dir / "04-architecture" / "technical-plan.md",
        stages_dir / "05-implementation" / "round-1-implementation.md",
        stages_dir / "06-release" / "round-1-release-plan.md",
        stages_dir / "07-delivery" / "round-1-delivery-readme.md",
        stages_dir / "08-verification" / "round-1-verification-report.md",
        stages_dir / "09-final" / "final-delivery-report.md",
        stages_dir / "index.md",
        stages_dir / "workflow-plan.md",
    ]
    for path in expected_docs:
        assert path.exists(), f"missing stage document: {path.relative_to(tmp_path)}"
        assert path.read_text(encoding="utf-8").startswith("#")

    index = (stages_dir / "index.md").read_text(encoding="utf-8")
    assert "## Stage Documents" in index
    assert "05-implementation/round-1-implementation.md" in index
    assert "08-verification/round-1-verification-report.md" in index
    assert "workflow-plan.md" in index
    workflow_plan = (stages_dir / "workflow-plan.md").read_text(encoding="utf-8")
    assert "Execution: sequential" in workflow_plan
    assert "Mode: full-rd" in workflow_plan
    assert "Parallelism: disabled" in workflow_plan
    assert "Codex QA Verification Agent" in workflow_plan
    assert "Deepseek Code Review Agent" in workflow_plan
    final_doc = (stages_dir / "09-final" / "final-delivery-report.md").read_text(encoding="utf-8")
    assert "Delivery Status" in final_doc
    assert "delivered" in final_doc


def test_devclaw_loop_keeps_stage_documents_isolated_by_project_and_session(tmp_path: Path):
    lead = DevClawLead(
        execution_adapter=TestExecutionAdapter(),
        verification_adapter=TestVerificationAdapter(),
        max_rounds=1,
    )

    first = lead.run("Build a customer feedback triage Agent", tmp_path)
    second = lead.run("Build an invoice analysis Agent", tmp_path)

    assert first.project_id != second.project_id
    stages_root = tmp_path / ".devclaw" / "stages"
    first_sessions = list((stages_root / first.project_id).iterdir())
    second_sessions = list((stages_root / second.project_id).iterdir())
    assert len(first_sessions) == 1
    assert len(second_sessions) == 1
    assert first_sessions[0] != second_sessions[0]
    assert (first_sessions[0] / "09-final" / "final-delivery-report.md").exists()
    assert (second_sessions[0] / "09-final" / "final-delivery-report.md").exists()
    assert first.brief.goal in (first_sessions[0] / "00-intake" / "project-brief.md").read_text(encoding="utf-8")
    assert second.brief.goal in (second_sessions[0] / "00-intake" / "project-brief.md").read_text(encoding="utf-8")


def test_devclaw_loop_writes_attached_screenshots_to_intake_stage(tmp_path: Path):
    lead = DevClawLead(
        execution_adapter=TestExecutionAdapter(),
        verification_adapter=TestVerificationAdapter(),
        max_rounds=1,
    )

    result = lead.run(
        "Fix the page layout issue\n\nAttached screenshots:\n- .devclaw/attachments/pending/screen.png\n  Note: right panel is clipped",
        tmp_path,
    )

    project_stages_dir = tmp_path / ".devclaw" / "stages" / result.project_id
    stages_dir = next(project_stages_dir.iterdir())
    attachments_doc = stages_dir / "00-intake" / "attachments.md"
    assert attachments_doc.exists()
    content = attachments_doc.read_text(encoding="utf-8")
    assert ".devclaw/attachments/pending/screen.png" in content
    assert "right panel is clipped" in content


def test_devclaw_loop_routes_role_outputs_to_codex_and_deepseek_with_skills(tmp_path: Path):
    executor = TestExecutionAdapter()
    verifier = TestVerificationAdapter()
    lead = DevClawLead(
        execution_adapter=executor,
        verification_adapter=verifier,
        max_rounds=1,
    )

    result = lead.run("Build a customer feedback triage Agent", tmp_path)

    assert "Codex Intake Agent" in executor.role_calls
    assert "Codex UX Research Agent" in executor.role_calls
    assert "Codex Architecture Reasoning Agent" in executor.role_calls
    assert "Codex Technical Plan Agent" in executor.role_calls
    assert "Codex QA Verification Agent" in executor.role_calls
    assert "Deepseek Product Research Agent" in verifier.role_calls
    assert "Deepseek PRD Agent" in verifier.role_calls
    assert "Deepseek Test Execution Agent" in verifier.role_calls
    assert "Deepseek Code Review Agent" in verifier.role_calls
    assert "Deepseek Release Review Agent" in verifier.role_calls
    assert "Deepseek Delivery Report Agent" in verifier.role_calls
    assert "Deepseek Archivist Agent" in verifier.role_calls

    project_stages_dir = tmp_path / ".devclaw" / "stages" / result.project_id
    stages_dir = next(project_stages_dir.iterdir())
    ux_doc = (stages_dir / "01-research" / "ux-research-report.md").read_text(encoding="utf-8")
    prd_doc = (stages_dir / "02-product" / "prd.md").read_text(encoding="utf-8")
    assert "## Skills Used" in ux_doc
    assert "screenshot-analysis" in ux_doc
    assert "## Skills Used" in prd_doc
    assert "product-structuring" in prd_doc


def test_devclaw_loop_uses_targeted_workflow_for_small_follow_up_with_prior_context(tmp_path: Path):
    first_executor = TestExecutionAdapter()
    first_verifier = TestVerificationAdapter()
    first_lead = DevClawLead(
        execution_adapter=first_executor,
        verification_adapter=first_verifier,
        max_rounds=1,
    )
    first = first_lead.run("Build a customer feedback triage Agent", tmp_path)
    assert first.final_report.delivery_status == "delivered"

    second_executor = TestExecutionAdapter()
    second_verifier = TestVerificationAdapter()
    events: list[dict[str, str]] = []
    second_lead = DevClawLead(
        execution_adapter=second_executor,
        verification_adapter=second_verifier,
        max_rounds=1,
        progress=events.append,
    )

    second = second_lead.run(
        "Optimize the CLI display so users do not think Agents are parallel",
        tmp_path,
    )

    assert second.final_report.delivery_status == "delivered"
    assert "Codex Repository Analysis Agent" in second_executor.role_calls
    assert "Codex Technical Plan Agent" in second_executor.role_calls
    assert "Codex UX Research Agent" not in second_executor.role_calls
    assert "Deepseek Product Research Agent" not in second_verifier.role_calls
    assert "Deepseek PRD Agent" not in second_verifier.role_calls

    project_stages_dir = tmp_path / ".devclaw" / "stages" / second.project_id
    stages_dir = sorted(project_stages_dir.iterdir())[-1]
    reuse_note = stages_dir / "01-research" / "stage-reuse-note.md"
    assert reuse_note.exists()
    reuse_content = reuse_note.read_text(encoding="utf-8")
    assert "Status: reused" in reuse_content
    assert first.project_id in reuse_content
    assert "targeted-change" in reuse_content

    context_pack = tmp_path / ".devclaw" / "context" / "current-context-pack.md"
    assert context_pack.exists()
    assert first.project_id in context_pack.read_text(encoding="utf-8")

    route_events = [event for event in events if event["stage"] == "workflow" and event["status"] == "planned"]
    assert route_events
    assert route_events[0]["workflow_mode"] == "targeted-change"


def test_devclaw_loop_runs_delivery_after_acceptance_gate(tmp_path: Path):
    events: list[dict[str, str]] = []
    lead = DevClawLead(
        execution_adapter=TestExecutionAdapter(),
        verification_adapter=TestVerificationAdapter(),
        max_rounds=1,
        progress=events.append,
    )

    result = lead.run("Build a customer feedback triage Agent", tmp_path)

    assert result.final_report.delivery_status == "delivered"
    completed = [f"{event['stage']}:{event['agent']}:{event['status']}" for event in events]
    implementation_done = completed.index("implementation:Codex Implementation Agent:completed")
    test_started = completed.index("verification:Deepseek Test Execution Agent:started")
    qa_started = completed.index("verification:Codex QA Verification Agent:started")
    review_started = completed.index("review:Deepseek Code Review Agent:started")
    acceptance_done = completed.index("verification:Deepseek Acceptance Gate:pass")
    delivery_started = completed.index("delivery:Deepseek Delivery Report Agent:started")

    assert implementation_done < test_started < qa_started < review_started < acceptance_done < delivery_started


def test_devclaw_loop_downgrades_archivist_failure_to_warning(tmp_path: Path):
    class ArchiveFailingVerificationAdapter:
        def __init__(self):
            self.local = TestVerificationAdapter()

        def run_role(self, assignment, brief, contract, workspace: Path, previous_outputs):
            if assignment.role == "Deepseek Archivist Agent":
                raise RuntimeError("WARNING: failed to clean up stale arg0 temp dirs: Permission denied")
            return self.local.run_role(assignment, brief, contract, workspace, previous_outputs)

        def verify(self, brief, contract, workspace: Path):
            return self.local.verify(brief, contract, workspace)

    lead = DevClawLead(
        execution_adapter=TestExecutionAdapter(),
        verification_adapter=ArchiveFailingVerificationAdapter(),
        max_rounds=1,
    )

    result = lead.run("Build a customer feedback triage Agent", tmp_path)

    assert result.final_report.delivery_status == "delivered"
    assert any("Archivist failed" in item for item in result.final_report.known_limits)
    project_stages_dir = tmp_path / ".devclaw" / "stages" / result.project_id
    stages_dir = next(project_stages_dir.iterdir())
    warning = stages_dir / "09-final" / "archive-warning.md"
    assert warning.exists()
    assert "Permission denied" in warning.read_text(encoding="utf-8")
