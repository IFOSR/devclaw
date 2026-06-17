from devclaw.core.workflow_router import (
    WorkflowMode,
    route_from_planner_output,
    route_workflow,
)


def test_route_workflow_uses_full_rd_for_new_build_requests():
    route = route_workflow("Build a customer feedback triage Agent", has_prior_context=False)

    assert route.mode == WorkflowMode.FULL_RD
    assert "product_research" in route.run_role_keys
    assert "implementation" in route.run_role_keys
    assert route.skip_role_keys == []


def test_route_workflow_uses_targeted_change_for_small_follow_up_with_prior_context():
    route = route_workflow("Optimize the CLI display so users do not think Agents are parallel", has_prior_context=True)

    assert route.mode == WorkflowMode.TARGETED_CHANGE
    assert route.run_role_keys == [
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
    assert "product_research" in route.skip_role_keys
    assert "prd" in route.skip_role_keys
    assert "design" in route.skip_role_keys
    assert "architecture_reasoning" in route.skip_role_keys
    assert route.reason


def test_targeted_workflow_places_delivery_after_verification_roles():
    route = route_workflow("Optimize the CLI display", has_prior_context=True)

    assert route.run_role_keys.index("test_execution") < route.run_role_keys.index("delivery_report")
    assert route.run_role_keys.index("qa_verification") < route.run_role_keys.index("delivery_report")
    assert route.run_role_keys.index("code_review") < route.run_role_keys.index("delivery_report")


def test_route_workflow_keeps_bugfix_narrow_with_prior_context():
    route = route_workflow("Fix the Ctrl+V pasted image notice bug", has_prior_context=True)

    assert route.mode == WorkflowMode.BUGFIX
    assert route.run_role_keys == [
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


def test_route_workflow_treats_chinese_page_performance_as_targeted_change():
    route = route_workflow("页面太卡顿了，需要的页面加速。", has_prior_context=True)

    assert route.mode == WorkflowMode.TARGETED_CHANGE
    assert "product_research" in route.skip_role_keys
    assert "implementation" in route.run_role_keys


def test_route_from_planner_output_parses_codex_json_decision():
    route = route_from_planner_output(
        """
        Codex analysis:
        {"mode":"targeted-change","reason":"Existing page needs performance optimization.","confidence":0.92}
        """,
        has_prior_context=True,
    )

    assert route.mode == WorkflowMode.TARGETED_CHANGE
    assert route.reason == "Existing page needs performance optimization."
    assert "implementation" in route.run_role_keys
    assert "product_research" in route.skip_role_keys


def test_route_from_planner_output_rejects_invalid_planner_output():
    try:
        route_from_planner_output('{"mode":"nonsense","reason":"bad"}', has_prior_context=True)
    except ValueError as error:
        assert "Unsupported workflow mode" in str(error)
    else:
        raise AssertionError("expected ValueError")
