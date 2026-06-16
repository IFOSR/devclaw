from devclaw.core.contracts import create_acceptance_contract, create_project_brief


def test_create_project_brief_from_user_intent():
    brief = create_project_brief(
        "Build a customer feedback triage Agent for support teams"
    )

    assert brief.project_id.startswith("devclaw_")
    assert "feedback triage" in brief.goal.lower()
    assert brief.target_user
    assert brief.assumptions


def test_create_acceptance_contract_covers_required_categories():
    brief = create_project_brief(
        "Build a customer feedback triage Agent for support teams"
    )
    contract = create_acceptance_contract(brief)

    assert contract.project_id == brief.project_id
    assert contract.deliverables == [
        "Research reports",
        "Runnable implementation",
        "README",
        "Verification report",
        "Final delivery report",
    ]
    assert contract.functional_acceptance
    assert contract.research_acceptance
    assert contract.ux_acceptance
    assert contract.technical_acceptance
    assert contract.quality_acceptance
    assert contract.release_acceptance
    assert contract.documentation_acceptance
    assert all(item.priority == "blocking" for item in contract.blocking_items())
    assert "final_delivery_report_generated" in contract.stop_condition
