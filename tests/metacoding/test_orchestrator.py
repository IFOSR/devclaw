"""Three-harness lifecycle: state machine, gates, rework, and stop conditions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from metacoding.config import HarnessConfig, ProjectConfig, default_config
from metacoding.errors import MetaCodingError, ProtocolError
from metacoding.harnesses.base import HarnessContext
from metacoding.harnesses.fake import FakeCoder, FakePlanner, FakeTester
from metacoding.models import RunStatus
from metacoding.orchestrator import Orchestrator, OrchestratorResult

# --- scenario payload builders ---------------------------------------------------


def plan_payload(allowed: list[str] | None = None, protected: list[str] | None = None) -> dict:
    return {
        "goal": "Add audit logging",
        "scope": ["src"],
        "non_goals": [],
        "architecture": {
            "approach": "hook mutations",
            "modules": ["src/audit.py"],
            "data_flow": ["mutation -> audit"],
            "risks": [],
        },
        "acceptance_criteria": [
            {
                "id": "F-001",
                "description": "entries appended",
                "priority": "blocking",
                "verification_method": "run tests",
            }
        ],
        "coding_tasks": [
            {
                "id": "TASK-001",
                "description": "implement hook",
                "expected_files": ["src/audit.py"],
                "required_tests": ["tests/test_audit.py"],
                "done_when": "tests pass",
            }
        ],
        "change_policy": {
            "allowed_paths": allowed if allowed is not None else ["src/**", "tests/**", "docs/metacoding"],
            "protected_paths": protected
            if protected is not None
            else ["docs/metacoding/PRD.md", ".metacoding/config.toml"],
            "forbidden_actions": [],
        },
    }


def code_payload(changed: list[str] | None = None, files: dict | None = None) -> dict:
    step: dict = {
        "status": "completed",
        "summary": "implemented audit hook",
        "completed_tasks": ["TASK-001"],
        "changed_files": changed if changed is not None else ["src/audit.py"],
        "tests_added_or_changed": ["tests/test_audit.py"],
        "commands_run": ["python3 -m pytest -q"],
        "known_limitations": [],
        "blocked_reason": None,
    }
    if files:
        step = {"files": files, "payload": step}
    return step


def make_test_step(
    *,
    status: str = "pass",
    failing: list[str] | None = None,
    findings: list[dict] | None = None,
    command_exit: int = 0,
    files: dict | None = None,
    changed_files: list[str] | None = None,
) -> dict:
    step: dict = {
        "status": status,
        "test_commands": [
            {"command": "python3 -m pytest -q", "exit_code": command_exit, "summary": "run"}
        ],
        "acceptance_results": [
            {
                "id": "F-001",
                "status": "fail" if failing else "pass",
                "impact": "high",
                "evidence": ["tests/test_audit.py"],
            }
        ],
        "findings": findings or [],
        "prd_drift": [],
        "regression_risks": [],
        "missing_tests": [],
        "changed_files": changed_files or [],
    }
    if files:
        step = {"files": files, "payload": step}
    return step


def review_payload(decision: str = "accept", tasks: list[dict] | None = None) -> dict:
    return {
        "decision": decision,
        "reason": "reviewed round evidence",
        "blocking_findings": [],
        "rework_tasks": tasks
        if tasks is not None
        else [
            {
                "id": "REWORK-001",
                "description": "fix the failing check",
                "target_area": ["src/audit.py"],
                "verification": "rerun tests",
            }
        ]
        if decision == "rework"
        else [],
    }


def p1_finding(title: str = "crash on empty input") -> dict:
    return {
        "id": "BUG-001",
        "type": "bug",
        "severity": "P1",
        "title": title,
        "impact": "high",
        "reproduction": ["run x"],
        "evidence": ["traceback"],
        "recommended_fix": "guard input",
    }


def scenario(
    *,
    plan: list | None = None,
    code: list | None = None,
    test: list | None = None,
    review: list | None = None,
) -> dict:
    return {
        "attempts": {
            "plan": plan if plan is not None else [plan_payload()],
            "code": code if code is not None else [code_payload()],
            "test": test if test is not None else [make_test_step()],
            "review": review if review is not None else [review_payload()],
        }
    }


@dataclass
class RecordingDeliverer:
    calls: list = field(default_factory=list)
    result: dict = field(default_factory=lambda: {"branch": "metacoding/run-1", "pushed": False})

    def deliver(self, run_id: str, owned_files: list[str]) -> dict:
        self.calls.append((run_id, sorted(owned_files)))
        return dict(self.result)


def make_config(**overrides) -> ProjectConfig:
    config = default_config()
    fake_harness = HarnessConfig(
        name="x", provider="fake", command="python3", model="", extra_args=[]
    )
    harness = {
        "planner": replace(fake_harness, name="planner"),
        "coder": replace(fake_harness, name="coder"),
        "tester": replace(fake_harness, name="tester"),
    }
    config = replace(config, harness=harness)
    if "max_rounds" in overrides:
        config = replace(
            config, limits=replace(config.limits, max_rounds=overrides.pop("max_rounds"))
        )
    if "same_failure_limit" in overrides:
        config = replace(
            config,
            limits=replace(config.limits, same_failure_limit=overrides.pop("same_failure_limit")),
        )
    if overrides:
        config = replace(config, **overrides)
    return config


def make_orchestrator(
    tmp_path: Path,
    script: dict,
    config: ProjectConfig | None = None,
    deliverer=None,
) -> tuple[Orchestrator, list[dict]]:
    config = config or make_config()
    events: list[dict] = []
    orchestrator = Orchestrator(
        project_root=tmp_path,
        config=config,
        harnesses={
            "planner": FakePlanner(config.harness["planner"], tmp_path, script),
            "coder": FakeCoder(config.harness["coder"], tmp_path, script),
            "tester": FakeTester(config.harness["tester"], tmp_path, script),
        },
        emit=events.append,
        deliverer=deliverer,
    )
    return orchestrator, events


# --- happy path ------------------------------------------------------------------


def test_accepted_run_reaches_delivered_with_all_artifacts(tmp_path: Path) -> None:
    orchestrator, events = make_orchestrator(tmp_path, scenario())
    result = orchestrator.start("add audit logging")

    assert isinstance(result, OrchestratorResult)
    assert result.status is RunStatus.DELIVERED
    assert result.exit_code == 0
    docs = tmp_path / "docs" / "metacoding"
    for name in (
        "PRD.md",
        "ARCHITECTURE.md",
        "IMPLEMENTATION_PLAN.md",
        "ACCEPTANCE.md",
        "TEST_REPORT.md",
        "FINAL_REPORT.md",
    ):
        assert (docs / name).is_file(), name

    run_dir = tmp_path / ".metacoding" / "runs" / result.run_id
    assert (run_dir / "initial-plan.json").is_file()
    assert (run_dir / "git" / "baseline.json").is_file()
    assert (run_dir / "final.json").is_file()
    round_dir = run_dir / "rounds" / "round-001"
    for name in (
        "planner-instruction.json",
        "coding-report.json",
        "tester-report.json",
        "planner-decision.json",
    ):
        assert (round_dir / name).is_file(), name
    assert not (tmp_path / ".metacoding" / "state.json").is_file()

    phases = [event["phase"] for event in events if event.get("kind") == "phase"]
    assert phases == ["planning", "coding", "testing", "planner_review", "done"]


def test_coder_writes_files_in_project(tmp_path: Path) -> None:
    script = scenario(code=[code_payload(files={"src/audit.py": "log()\n"})])
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.DELIVERED
    assert (tmp_path / "src" / "audit.py").read_text(encoding="utf-8") == "log()\n"


def test_planner_review_receives_tester_report(tmp_path: Path) -> None:
    captured: list[HarnessContext] = []
    orchestrator, _ = make_orchestrator(tmp_path, scenario())
    original_review = orchestrator.harnesses["planner"].review

    def spy_review(ctx: HarnessContext):
        captured.append(ctx)
        return original_review(ctx)

    orchestrator.harnesses["planner"].review = spy_review
    orchestrator.start("add audit logging")
    assert len(captured) == 1
    assert captured[0].tester_report is not None
    assert captured[0].tester_report.status == "pass"


# --- rework loop -----------------------------------------------------------------


def test_rework_round_then_accept(tmp_path: Path) -> None:
    script = scenario(
        test=[make_test_step(finding=lambda: None) if False else make_test_step(
            status="fail", failing=["F-001"], findings=[p1_finding()]
        ), make_test_step()],
        review=[review_payload("rework"), review_payload("accept")],
    )
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.DELIVERED
    run_dir = tmp_path / ".metacoding" / "runs" / result.run_id
    assert (run_dir / "rounds" / "round-002").is_dir()
    instruction = json.loads(
        (run_dir / "rounds" / "round-002" / "planner-instruction.json").read_text("utf-8")
    )
    assert instruction["tasks"][0]["id"] == "REWORK-001"
    assert result.final.rounds_used == 2


def test_planner_blocked_ends_run_as_blocked(tmp_path: Path) -> None:
    script = scenario(review=[review_payload("blocked", tasks=[])])
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.BLOCKED
    assert result.exit_code == 1
    assert "reviewed round evidence" in result.final.reason


def test_human_review_required_ends_run(tmp_path: Path) -> None:
    script = scenario(review=[review_payload("human_review_required", tasks=[])])
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.HUMAN_REVIEW_REQUIRED
    assert result.exit_code == 1


def test_max_rounds_exhaustion_blocks(tmp_path: Path) -> None:
    script = scenario(review=[review_payload("rework")])
    orchestrator, _ = make_orchestrator(
        tmp_path, script, make_config(max_rounds=2)
    )
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.BLOCKED
    assert result.final.rounds_used == 2
    assert "max" in result.final.reason.lower()


def test_repeated_failure_fingerprint_blocks(tmp_path: Path) -> None:
    failing = make_test_step(status="fail", failing=["F-001"], findings=[p1_finding()])
    script = scenario(test=[failing], review=[review_payload("rework")])
    orchestrator, _ = make_orchestrator(
        tmp_path, script, make_config(max_rounds=5, same_failure_limit=2)
    )
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.BLOCKED
    assert "failure" in result.final.reason.lower()
    assert result.final.rounds_used == 2


def test_planner_accept_overridden_by_failing_gates(tmp_path: Path) -> None:
    # Planner says accept while a P1 finding and failed checks remain.
    script = scenario(
        test=[
            make_test_step(status="fail", failing=["F-001"], findings=[p1_finding()]),
            make_test_step(),
        ],
        review=[review_payload("accept"), review_payload("accept")],
    )
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.DELIVERED
    assert result.final.rounds_used == 2
    assert any("gate" in warning.lower() for warning in result.final.warnings)


def test_planner_accept_with_persistent_gate_failures_blocks(tmp_path: Path) -> None:
    failing = make_test_step(status="fail", failing=["F-001"], findings=[p1_finding()])
    script = scenario(test=[failing], review=[review_payload("accept")])
    orchestrator, _ = make_orchestrator(tmp_path, script, make_config(max_rounds=2))
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.BLOCKED


# --- policy violations -------------------------------------------------------------


def test_tester_contamination_blocks(tmp_path: Path) -> None:
    script = scenario(
        test=[make_test_step(files={"src/audit.py": "tampered\n"})]
    )
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.BLOCKED
    assert "contaminat" in result.final.reason.lower()


def test_protected_path_modification_blocks(tmp_path: Path) -> None:
    script = scenario(
        code=[code_payload(files={"docs/metacoding/PRD.md": "hijacked\n"})]
    )
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.BLOCKED
    assert "protected" in result.final.reason.lower()


def test_repeated_scope_violations_block(tmp_path: Path) -> None:
    script = scenario(
        code=[
            code_payload(
                changed=["src/audit.py", "outside/scope.py"],
                files={"outside/scope.py": "x\n"},
            )
        ],
        review=[review_payload("rework")],
    )
    orchestrator, _ = make_orchestrator(
        tmp_path, script, make_config(max_rounds=6, same_failure_limit=2)
    )
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.BLOCKED
    assert "scope" in result.final.reason.lower()


# --- infrastructure failures --------------------------------------------------------


def test_missing_plan_blocks_coding_entirely(tmp_path: Path) -> None:
    script = {"attempts": {"plan": [{"behavior": "malformed"}], "code": [], "test": [], "review": []}}
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.FAILED_INFRASTRUCTURE
    assert result.exit_code == 2
    run_dir = tmp_path / ".metacoding" / "runs" / result.run_id
    assert not (run_dir / "rounds" / "round-001").is_dir()


def test_malformed_output_retries_once_then_infra_failure(tmp_path: Path) -> None:
    script = scenario(
        review=[
            {"behavior": "malformed"},
            {"behavior": "malformed"},
            review_payload("accept"),
        ]
    )
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.FAILED_INFRASTRUCTURE


def test_malformed_then_valid_output_recovers(tmp_path: Path) -> None:
    script = scenario(review=[{"behavior": "malformed"}, review_payload("accept")])
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.DELIVERED


def test_timeout_retried_once_then_infra_failure(tmp_path: Path) -> None:
    script = scenario(test=[{"behavior": "timeout"}, {"behavior": "timeout"}])
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.FAILED_INFRASTRUCTURE


def test_invalid_rework_decision_is_retried(tmp_path: Path) -> None:
    invalid = review_payload("rework", tasks=[])  # rework without tasks
    script = scenario(review=[invalid, review_payload("rework"), review_payload("accept")])
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.DELIVERED


# --- interruption and resume ---------------------------------------------------------


def test_interrupted_run_persists_and_resumes(tmp_path: Path) -> None:
    orchestrator, _ = make_orchestrator(tmp_path, scenario())
    original_code = orchestrator.harnesses["coder"].code

    def interrupting_code(ctx: HarnessContext):
        if ctx.attempt == 1:
            raise KeyboardInterrupt
        return original_code(ctx)

    orchestrator.harnesses["coder"].code = interrupting_code
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.INTERRUPTED
    state = json.loads(
        (tmp_path / ".metacoding" / "state.json").read_text(encoding="utf-8")
    )
    assert state["status"] == "interrupted"

    orchestrator.harnesses["coder"].code = original_code
    resumed = orchestrator.resume()
    assert resumed.status is RunStatus.DELIVERED
    assert resumed.run_id == result.run_id


def test_resume_without_active_run_fails(tmp_path: Path) -> None:
    orchestrator, _ = make_orchestrator(tmp_path, scenario())
    with pytest.raises(MetaCodingError):
        orchestrator.resume()


def test_new_run_rejected_while_active_run_exists(tmp_path: Path) -> None:
    orchestrator, _ = make_orchestrator(tmp_path, scenario())
    # simulate an active run pointer
    from metacoding.locking import release_lock
    from metacoding.persistence import RunStore

    store = RunStore(tmp_path)
    record = store.create_run("pending", default_config(), __import__(
        "metacoding.models", fromlist=["ProjectSnapshot"]
    ).ProjectSnapshot(
        captured_at="2026-09-07T00:00:00Z",
        is_git_repo=False,
        git_head=None,
        dirty_files=[],
        file_inventory=[],
        test_commands=[],
    ))
    with pytest.raises(MetaCodingError) as excinfo:
        orchestrator.start("another requirement")
    assert "resume" in str(excinfo.value).lower()
    release_lock(tmp_path)
    store.clear_active_run()


def test_coder_blocked_result_leads_to_planner_review(tmp_path: Path) -> None:
    blocked_code = {
        "status": "blocked",
        "summary": "",
        "completed_tasks": [],
        "changed_files": [],
        "tests_added_or_changed": [],
        "commands_run": [],
        "known_limitations": [],
        "blocked_reason": "missing dependency",
    }
    script = scenario(code=[blocked_code], review=[review_payload("blocked", tasks=[])])
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.BLOCKED


# --- delivery hook --------------------------------------------------------------------


def test_deliverer_invoked_when_github_enabled(tmp_path: Path) -> None:
    deliverer = RecordingDeliverer()
    github = replace(default_config().github, enabled=True)
    config = replace(make_config(), github=github)
    script = scenario(code=[code_payload(files={"src/audit.py": "log()\n"})])
    orchestrator, _ = make_orchestrator(tmp_path, script, config, deliverer=deliverer)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.DELIVERED
    assert deliverer.calls
    run_id, files = deliverer.calls[0]
    assert run_id == result.run_id
    assert "src/audit.py" in files
    assert result.final.github == {"branch": "metacoding/run-1", "pushed": False}
