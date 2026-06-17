from devclaw.core.role_assignments import ROLE_ASSIGNMENTS


def test_role_assignments_match_codex_deepseek_plan():
    expected = {
        "intake": "codex",
        "product_research": "deepseek",
        "ux_research": "codex",
        "prd": "deepseek",
        "design": "codex",
        "architecture_reasoning": "codex",
        "repository_analysis": "codex",
        "technical_plan": "codex",
        "implementation": "codex",
        "test_execution": "deepseek",
        "qa_verification": "codex",
        "fix_loop": "codex",
        "code_review": "deepseek",
        "release_review": "deepseek",
        "delivery_report": "deepseek",
        "archivist": "deepseek",
    }

    assert {key: value.provider for key, value in ROLE_ASSIGNMENTS.items()} == expected


def test_each_role_declares_required_skills_and_output_artifact():
    for role, assignment in ROLE_ASSIGNMENTS.items():
        assert assignment.skills, f"{role} must declare matching skills"
        assert assignment.artifact, f"{role} must declare output artifact"
        assert assignment.output_stage, f"{role} must map to a stage output"
