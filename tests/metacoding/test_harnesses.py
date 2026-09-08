"""Harness adapter behavior: command construction, parsing, classification."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from metacoding.config import HarnessConfig
from metacoding.errors import (
    HarnessNonZeroExit,
    HarnessTimeout,
    MalformedHarnessOutput,
)
from metacoding.harnesses.base import HarnessContext
from metacoding.harnesses.codex_planner import CodexPlanner
from metacoding.harnesses.codex_tester import CodexTester
from metacoding.harnesses.fake import FakeCoder, FakePlanner, fake_scenario_path, write_scenario
from metacoding.harnesses.pi_coder import PiCoder

VALID_PLAN = {
    "goal": "Add audit logging",
    "scope": ["src/admin"],
    "non_goals": [],
    "architecture": {
        "approach": "hook mutations",
        "modules": ["src/admin/audit.py"],
        "data_flow": ["mutation -> audit"],
        "risks": [],
    },
    "acceptance_criteria": [
        {
            "id": "F-001",
            "description": "audit entries appended",
            "priority": "blocking",
            "verification_method": "run tests",
        }
    ],
    "coding_tasks": [
        {
            "id": "TASK-001",
            "description": "implement hook",
            "expected_files": ["src/admin/audit.py"],
            "required_tests": [],
            "done_when": "tests pass",
        }
    ],
    "change_policy": {
        "allowed_paths": ["src/admin/**", "tests/**"],
        "protected_paths": ["docs/metacoding/PRD.md"],
        "forbidden_actions": [],
    },
}


def make_planner_config(**kwargs) -> HarnessConfig:
    defaults = dict(name="planner", provider="codex", command="codex", model="", extra_args=[])
    defaults.update(kwargs)
    return HarnessConfig(**defaults)


def make_coder_config(**kwargs) -> HarnessConfig:
    defaults = dict(name="coder", provider="pi", command="pi", model="", extra_args=[])
    defaults.update(kwargs)
    return HarnessConfig(**defaults)


def make_tester_config(**kwargs) -> HarnessConfig:
    defaults = dict(name="tester", provider="codex", command="codex", model="", extra_args=[])
    defaults.update(kwargs)
    return HarnessConfig(**defaults)


def make_context(tmp_path: Path, **overrides) -> HarnessContext:
    from metacoding.models import validate_planner_plan

    fields = dict(
        requirement="add audit logging",
        run_id="run-1",
        round_number=1,
        attempt=1,
        idle_timeout_seconds=30,
        project_root=tmp_path,
        docs_dir=tmp_path / "docs" / "metacoding",
        report_dir=tmp_path / ".metacoding" / "runs" / "run-1",
        plan=validate_planner_plan(VALID_PLAN),
    )
    fields.update(overrides)
    return HarnessContext(**fields)


# --- command construction ------------------------------------------------------


def test_planner_command_contains_codex_model_and_json_output(tmp_path: Path) -> None:
    planner = CodexPlanner(make_planner_config(model="planner-model"), tmp_path)
    ctx = make_context(tmp_path)
    command = planner.build_command("plan", ctx)
    assert command[0] == "codex"
    assert "exec" in command
    assert "-m" in command and command[command.index("-m") + 1] == "planner-model"
    assert "--json" in command
    output_flag_index = command.index("-o")
    assert str(ctx.report_dir) in command[output_flag_index + 1]
    prompt_argument = command[-1]
    assert "add audit logging" in prompt_argument


def test_coder_command_contains_pi_model_and_prompt(tmp_path: Path) -> None:
    coder = PiCoder(make_coder_config(model="coder-model"), tmp_path)
    ctx = make_context(tmp_path)
    command = coder.build_command("code", ctx)
    assert command[0] == "pi"
    assert "-p" in command
    assert "--model" in command and command[command.index("--model") + 1] == "coder-model"
    prompt_argument = command[-1]
    assert "add audit logging" in prompt_argument


def test_tester_command_contains_tester_model_and_prompt(tmp_path: Path) -> None:
    tester = CodexTester(make_tester_config(model="tester-model"), tmp_path)
    ctx = make_context(tmp_path)
    command = tester.build_command("test", ctx)
    assert command[0] == "codex"
    assert command[command.index("-m") + 1] == "tester-model"


def test_planner_and_tester_models_do_not_leak_between_commands(tmp_path: Path) -> None:
    planner = CodexPlanner(make_planner_config(model="planner-model"), tmp_path)
    tester = CodexTester(make_tester_config(model="tester-model"), tmp_path)
    planner_command = planner.build_command("plan", make_context(tmp_path))
    tester_command = tester.build_command("test", make_context(tmp_path))
    assert "planner-model" in planner_command and "tester-model" not in planner_command
    assert "tester-model" in tester_command and "planner-model" not in tester_command


def test_extra_args_are_included_in_commands(tmp_path: Path) -> None:
    planner = CodexPlanner(
        make_planner_config(model="m", extra_args=["--profile", "fast"]), tmp_path
    )
    command = planner.build_command("plan", make_context(tmp_path))
    assert "--profile" in command and "fast" in command


def test_empty_model_omits_model_flag(tmp_path: Path) -> None:
    planner = CodexPlanner(make_planner_config(model=""), tmp_path)
    command = planner.build_command("plan", make_context(tmp_path))
    assert "-m" not in command
    coder = PiCoder(make_coder_config(model=""), tmp_path)
    coder_command = coder.build_command("code", make_context(tmp_path))
    assert "--model" not in coder_command


# --- prompts point at workspace artifacts, not chat history ---------------------


def test_plan_prompt_points_to_report_path_and_project(tmp_path: Path) -> None:
    planner = CodexPlanner(make_planner_config(), tmp_path)
    ctx = make_context(tmp_path)
    prompt = planner.build_prompt("plan", ctx)
    assert "docs/metacoding" in prompt
    assert str(ctx.report_dir) in prompt
    assert "JSON" in prompt


def test_code_prompt_carries_allowed_scope_and_rework_tasks(tmp_path: Path) -> None:
    from metacoding.models import validate_planner_plan

    coder = PiCoder(make_coder_config(), tmp_path)
    plan = validate_planner_plan(VALID_PLAN)
    ctx = make_context(
        tmp_path,
        plan=plan,
        rework_tasks=[{"id": "REWORK-001", "description": "fix null handling"}],
    )
    prompt = coder.build_prompt("code", ctx)
    assert "src/admin/**" in prompt
    assert "docs/metacoding/PRD.md" in prompt
    assert "REWORK-001" in prompt


def test_test_prompt_lists_acceptance_ids_and_test_commands(tmp_path: Path) -> None:
    from metacoding.models import validate_planner_plan

    tester = CodexTester(make_tester_config(), tmp_path)
    plan = validate_planner_plan(VALID_PLAN)
    ctx = make_context(tmp_path, plan=plan)
    ctx.test_commands = ["python3 -m pytest -q"]
    prompt = tester.build_prompt("test", ctx)
    assert "F-001" in prompt
    assert "python3 -m pytest -q" in prompt


def test_review_prompt_requires_tester_report_paths(tmp_path: Path) -> None:
    planner = CodexPlanner(make_planner_config(), tmp_path)
    ctx = make_context(tmp_path, round_number=2)
    prompt = planner.build_prompt("review", ctx)
    assert "tester-report.json" in prompt
    assert "TEST_REPORT.md" in prompt


# --- fake harness execution through the real subprocess path --------------------


def fake_harness_config(tmp_path: Path, scenario: dict, name: str) -> HarnessConfig:
    scenario_path = write_scenario(tmp_path, scenario)
    return HarnessConfig(
        name=name,
        provider="fake",
        command=sys.executable,
        model="",
        extra_args=["-m", "metacoding.harnesses.fake", "--scenario", str(scenario_path)],
    )


def test_fake_planner_executes_via_subprocess_and_returns_plan(tmp_path: Path) -> None:
    scenario = {"attempts": {"plan": [VALID_PLAN]}}
    planner = FakePlanner(fake_harness_config(tmp_path, scenario, "planner"), tmp_path)
    ctx = make_context(tmp_path)
    ctx.report_dir.mkdir(parents=True, exist_ok=True)
    plan = planner.plan(ctx)
    assert plan.goal == "Add audit logging"
    # raw payload persisted next to the canonical artifacts
    assert (ctx.report_dir / "plan-payload.json").is_file()


def test_fake_planner_malformed_output_is_detected(tmp_path: Path) -> None:
    scenario = {"attempts": {"plan": [{"behavior": "malformed"}]}}
    planner = FakePlanner(fake_harness_config(tmp_path, scenario, "planner"), tmp_path)
    ctx = make_context(tmp_path)
    ctx.report_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(MalformedHarnessOutput):
        planner.plan(ctx)


def test_fake_nonzero_exit_is_classified(tmp_path: Path) -> None:
    scenario = {"attempts": {"plan": [{"behavior": "nonzero"}]}}
    planner = FakePlanner(fake_harness_config(tmp_path, scenario, "planner"), tmp_path)
    ctx = make_context(tmp_path)
    ctx.report_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(HarnessNonZeroExit):
        planner.plan(ctx)


def test_fake_timeout_is_classified(tmp_path: Path) -> None:
    scenario = {"attempts": {"plan": [{"behavior": "timeout"}]}}
    planner = FakePlanner(fake_harness_config(tmp_path, scenario, "planner"), tmp_path)
    ctx = make_context(tmp_path, idle_timeout_seconds=1)
    ctx.report_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(HarnessTimeout):
        planner.plan(ctx)


def test_fake_can_write_workspace_files(tmp_path: Path) -> None:
    scenario = {
        "attempts": {
            "code": [
                {
                    "files": {"src/touched.txt": "from coder"},
                    "payload": {
                        "status": "completed",
                        "summary": "done",
                        "completed_tasks": [],
                        "changed_files": ["src/touched.txt"],
                        "tests_added_or_changed": [],
                        "commands_run": [],
                        "known_limitations": [],
                        "blocked_reason": None,
                    },
                }
            ]
        }
    }
    coder = FakeCoder(fake_harness_config(tmp_path, scenario, "coder"), tmp_path)
    ctx = make_context(tmp_path)
    ctx.report_dir.mkdir(parents=True, exist_ok=True)
    result = coder.code(ctx)
    assert result.status == "completed"
    assert (tmp_path / "src" / "touched.txt").read_text(encoding="utf-8") == "from coder"


def test_missing_report_file_is_malformed(tmp_path: Path) -> None:
    scenario = {"attempts": {"plan": []}}  # exhausted -> nothing written
    planner = FakePlanner(fake_harness_config(tmp_path, scenario, "planner"), tmp_path)
    ctx = make_context(tmp_path)
    ctx.report_dir.mkdir(parents=True, exist_ok=True)
    # remove any payload so read fails
    (ctx.report_dir / "plan-payload.json").unlink(missing_ok=True)
    (ctx.report_dir / "plan-payload.last-message").unlink(missing_ok=True)
    with pytest.raises(MalformedHarnessOutput):
        planner.plan(ctx)


def test_scenario_steps_advance_by_attempt(tmp_path: Path) -> None:
    scenario = {
        "attempts": {
            "review": [
                {
                    "decision": "rework",
                    "reason": "first round fails",
                    "blocking_findings": ["BUG-1"],
                    "rework_tasks": [
                        {
                            "id": "REWORK-001",
                            "description": "fix it",
                            "target_area": ["src"],
                            "verification": "tests",
                        }
                    ],
                },
                {"decision": "accept", "reason": "all good", "blocking_findings": [], "rework_tasks": []},
            ]
        }
    }
    planner = FakePlanner(fake_harness_config(tmp_path, scenario, "planner"), tmp_path)
    ctx = make_context(tmp_path, attempt=1)
    ctx.report_dir.mkdir(parents=True, exist_ok=True)
    first = planner.review(ctx)
    assert first.decision == "rework"
    ctx.attempt = 2
    (ctx.report_dir / "review-payload.json").unlink(missing_ok=True)
    second = planner.review(ctx)
    assert second.decision == "accept"


def test_nonzero_exit_surfaces_output_tail(tmp_path: Path) -> None:
    """The operator must see the harness's actual error inline, not just a
    pointer to transcripts."""
    scenario = {"attempts": {"plan": [{"behavior": "nonzero"}]}}
    planner = FakePlanner(fake_harness_config(tmp_path, scenario, "planner"), tmp_path)
    ctx = make_context(tmp_path)
    ctx.report_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(HarnessNonZeroExit) as excinfo:
        planner.plan(ctx)
    message = str(excinfo.value)
    assert "fake harness failure" in message  # stderr tail inlined
    assert "exit" in message


def test_stream_sink_receives_live_output(tmp_path: Path) -> None:
    scenario = {
        "attempts": {
            "plan": [
                {
                    "stdout_lines": ["analyzing repo...", "reading README.md"],
                    "payload": VALID_PLAN,
                }
            ]
        }
    }
    planner = FakePlanner(fake_harness_config(tmp_path, scenario, "planner"), tmp_path)
    ctx = make_context(tmp_path)
    ctx.report_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[tuple] = []
    ctx.stream_sink = lambda stage, stream, text: chunks.append((stage, stream, text))
    plan = planner.plan(ctx)
    assert plan.goal == "Add audit logging"
    assert chunks and all(stage == "plan" and stream == "stdout" for stage, stream, _ in chunks)
    joined = "".join(text for _, _, text in chunks)
    assert "analyzing repo..." in joined and "reading README.md" in joined
