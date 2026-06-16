from devclaw.core.models import (
    AcceptanceContract,
    AcceptanceItem,
    AgentOutput,
    FinalDeliveryReport,
    GapReport,
    ProjectBrief,
    VerificationReport,
)


def test_acceptance_contract_returns_blocking_items():
    contract = AcceptanceContract(
        project_id="proj_1",
        goal="Build a feedback triage agent",
        target_user="ops team",
        background="Reduce manual feedback sorting",
        scope=["triage feedback"],
        non_goals=["send external emails"],
        deliverables=["Runnable agent", "README"],
        research_acceptance=[],
        functional_acceptance=[
            AcceptanceItem(
                id="F1",
                description="Classifies feedback",
                category="functional",
                priority="blocking",
                verification_method="Run sample feedback",
            )
        ],
        ux_acceptance=[],
        technical_acceptance=[],
        quality_acceptance=[
            AcceptanceItem(
                id="Q1",
                description="Records known limitations",
                category="quality",
                priority="non_blocking",
                verification_method="Inspect report",
            )
        ],
        release_acceptance=[],
        documentation_acceptance=[],
        blocking_criteria=["Core classification works"],
        non_blocking_criteria=["Extra categories can be added later"],
        human_review_required=[],
        stop_condition=["all_blocking_acceptance_passed"],
    )

    assert [item.id for item in contract.blocking_items()] == ["F1"]
    assert contract.to_dict()["goal"] == "Build a feedback triage agent"


def test_gap_report_maps_failed_acceptance_to_rework_tasks():
    report = GapReport.from_verification(
        project_id="proj_1",
        round_number=1,
        verification=VerificationReport(
            status="fail",
            failed_acceptance=["F1"],
            blocking_issues=["No runnable deliverable"],
            non_blocking_issues=[],
            evidence=["README missing"],
        ),
    )

    assert report.status == "fail"
    assert report.rework_tasks[0]["agent"] == "Engineer Agent"
    assert "F1" in report.to_dict()["failed_acceptance"][0]["acceptance_id"]


def test_final_delivery_report_serializes_agent_outputs():
    brief = ProjectBrief(
        project_id="proj_1",
        intent="Build a feedback triage agent",
        goal="Classify feedback",
        target_user="ops team",
        assumptions=["Local CLI first"],
    )
    report = FinalDeliveryReport(
        project_id="proj_1",
        version="0.1.0",
        goal=brief.goal,
        delivery_status="delivered",
        delivered_items=[
            AgentOutput(
                agent="Delivery Agent",
                artifact="README",
                content="Run with python",
                path="README.md",
            )
        ],
        acceptance_result={"blocking_passed": True},
        test_result={"summary": "passed"},
        run_instructions={"start": "python3 -m devclaw"},
        deployment_notes={"environment": "local"},
        known_limits=[],
        next_iteration=[],
    )

    data = report.to_dict()

    assert data["delivery_status"] == "delivered"
    assert data["delivered_items"][0]["artifact"] == "README"
