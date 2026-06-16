from pathlib import Path

from tests.fakes import TestExecutionAdapter
from tests.fakes import TestVerificationAdapter
from devclaw.core.loop import DevClawLead
from devclaw.core.models import ProjectRunResult, VerificationReport


class FlakyVerificationAdapter:
    def __init__(self):
        self.calls = 0
        self.local = TestVerificationAdapter()

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


def test_devclaw_loop_prepares_release_and_delivery_artifacts_before_qa(tmp_path: Path):
    class ArtifactAwareVerificationAdapter:
        def verify(self, brief, contract, workspace: Path):
            release_plan = workspace / ".devclaw" / "release" / "latest" / "release-plan.md"
            delivery_readme = workspace / ".devclaw" / "delivery" / "latest" / "README.md"
            missing = [
                str(path.relative_to(workspace))
                for path in [release_plan, delivery_readme]
                if not path.exists()
            ]
            return VerificationReport(
                status="pass" if not missing else "fail",
                failed_acceptance=[] if not missing else ["R1", "D1"],
                blocking_issues=[] if not missing else [f"Missing before QA: {', '.join(missing)}"],
                non_blocking_issues=[],
                evidence=["release/delivery artifacts were present before QA"] if not missing else [],
            )

    lead = DevClawLead(
        execution_adapter=TestExecutionAdapter(),
        verification_adapter=ArtifactAwareVerificationAdapter(),
        max_rounds=1,
    )

    result = lead.run("Build a customer feedback triage Agent", tmp_path)

    assert result.final_report.delivery_status == "delivered"


def test_devclaw_loop_emits_progress_events_for_major_stages(tmp_path: Path):
    events: list[str] = []
    lead = DevClawLead(
        execution_adapter=TestExecutionAdapter(),
        verification_adapter=TestVerificationAdapter(),
        max_rounds=1,
        progress=lambda event: events.append(f"{event['stage']}:{event['agent']}:{event['status']}"),
    )

    result = lead.run("Build a customer feedback triage Agent", tmp_path)

    assert result.final_report.delivery_status == "delivered"
    assert "research:Product Research Agent:started" in events
    assert "product:PM Agent:started" in events
    assert "design:Designer Agent:started" in events
    assert "architecture:Architect Agent:started" in events
    assert "implementation:Codex Implementation Agent:started" in events
    assert "release:Release Agent:started" in events
    assert "delivery:Delivery Agent:started" in events
    assert "verification:Deepseek QA Agent:started" in events
    assert "final-report:DevClaw Lead:completed" in events
