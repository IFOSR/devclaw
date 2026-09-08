"""Three-harness lifecycle: state machine, gates, rework, and stop conditions."""

from __future__ import annotations

import json
import os
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
    reason = result.final.reason.lower()
    assert "contaminat" in reason or "permitted scope" in reason
    assert "src/audit.py" in result.final.reason


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
    release_lock(tmp_path, expected_pid=os.getpid(), expected_run_id=record.run_id)
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
    assert result.final.github["branch"] == "metacoding/run-1"
    assert result.final.github["pushed"] is False


# --- delivery failure, delivery resume, and lock/cancel races ------------------------


def test_git_delivery_failure_finalizes_human_review_not_stuck(tmp_path: Path) -> None:
    from metacoding.errors import GitDeliveryError

    class FailingDeliverer:
        def deliver(self, run_id, owned_files):
            raise GitDeliveryError("refusing to commit files outside the owned diff")

    deliverer = FailingDeliverer()
    script = scenario(code=[code_payload(files={"src/audit.py": "log()\n"})])
    orchestrator, _ = make_orchestrator(
        tmp_path, script, replace(make_config(), github=replace(default_config().github, enabled=True)), deliverer=deliverer
    )
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.HUMAN_REVIEW_REQUIRED
    assert "delivery failed" in result.final.reason.lower()
    # the run is terminal, not dangling in github_delivery
    state = json.loads((tmp_path / ".metacoding" / "state.json").read_text("utf-8")) \
        if (tmp_path / ".metacoding" / "state.json").exists() else None
    assert state is None


def test_resume_from_github_delivery_state_completes_delivery(tmp_path: Path) -> None:
    class InterruptingDeliverer:
        def __init__(self):
            self.calls = 0

        def deliver(self, run_id, owned_files):
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt  # crash mid-delivery
            return {"branch": f"metacoding/{run_id}", "pushed": False}

    deliverer = InterruptingDeliverer()
    script = scenario(code=[code_payload(files={"src/audit.py": "log()\n"})])
    orchestrator, _ = make_orchestrator(
        tmp_path, script, replace(make_config(), github=replace(default_config().github, enabled=True)), deliverer=deliverer
    )
    first = orchestrator.start("add audit logging")
    assert first.status is RunStatus.INTERRUPTED

    # simulate a crash that persisted github_delivery as the run state
    record = orchestrator.store.load_run(first.run_id)
    record.status = RunStatus.GITHUB_DELIVERY
    orchestrator.store.save_run(record, active_status=RunStatus.GITHUB_DELIVERY)

    resumed = orchestrator.resume()
    assert resumed.status is RunStatus.DELIVERED
    assert deliverer.calls == 2
    assert resumed.final.github["branch"] == f"metacoding/{first.run_id}"


def test_start_leaves_no_state_when_lock_is_held_by_live_process(tmp_path: Path) -> None:
    import subprocess as sp
    import sys as _sys

    live = sp.Popen([_sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        write_lock_for(tmp_path, run_id="other", pid=live.pid)
        orchestrator, _ = make_orchestrator(tmp_path, scenario())
        with pytest.raises(MetaCodingError) as excinfo:
            orchestrator.start("req")
        assert "active" in str(excinfo.value).lower() or "lock" in str(excinfo.value).lower()
        assert not (tmp_path / ".metacoding" / "state.json").exists()
        assert not list((tmp_path / ".metacoding" / "runs").glob("*")) \
            if (tmp_path / ".metacoding" / "runs").exists() else True
    finally:
        live.kill()
        live.wait()


def test_cancel_refuses_while_run_is_executing_elsewhere(tmp_path: Path) -> None:
    orchestrator, _ = make_orchestrator(tmp_path, scenario())
    from metacoding.locking import project_lock
    from metacoding.persistence import RunStore
    from metacoding.models import ProjectSnapshot

    store = RunStore(tmp_path)
    store.create_run(
        "pending",
        default_config(),
        ProjectSnapshot(
            captured_at="2026-09-07T00:00:00Z",
            is_git_repo=False,
            git_head=None,
            dirty_files=[],
            file_inventory=[],
            test_commands=[],
        ),
    )
    with project_lock(tmp_path, "someone-else"):
        with pytest.raises(MetaCodingError) as excinfo:
            orchestrator.cancel()
        assert "cannot cancel" in str(excinfo.value)
    # after the holder releases, cancel works
    result = orchestrator.cancel()
    assert result.status is RunStatus.CANCELLED


def test_second_ci_failure_requires_human_review(tmp_path: Path) -> None:
    class AlwaysFailingChecks:
        def __init__(self):
            self.calls = 0

        def deliver(self, run_id, owned_files):
            self.calls += 1
            return {
                "branch": f"metacoding/{run_id}",
                "commit": "sha",
                "committed_files": list(owned_files),
                "pushed": True,
                "checks": [{"name": "ci", "state": "FAILURE"}],
                "checks_failed": True,
                "warnings": [],
            }

    deliverer = AlwaysFailingChecks()
    script = scenario(code=[code_payload(files={"src/audit.py": "log()\n"})])
    orchestrator, _ = make_orchestrator(
        tmp_path,
        script,
        replace(make_config(), github=replace(default_config().github, enabled=True, wait_for_checks=True)),
        deliverer=deliverer,
    )
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.HUMAN_REVIEW_REQUIRED
    assert deliverer.calls == 2  # initial delivery + retry after CI rework round
    assert "checks failed again" in result.final.reason.lower()


def write_lock_for(root, *, run_id, pid):
    import json
    from metacoding.locking import lock_path

    path = lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "pid": pid,
                "host": __import__("socket").gethostname(),
                "acquired_at": "2026-09-07T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )


# --- stage write and git invariants -------------------------------------------------


def test_planner_writing_product_files_is_blocked(tmp_path: Path) -> None:
    hostile_plan = dict(plan_payload())
    scenario_script = {
        "attempts": {
            "plan": [{"files": {"src/planner-write.py": "pwned\n"}, "payload": hostile_plan}],
            "code": [code_payload()],
            "test": [make_test_step()],
            "review": [review_payload()],
        }
    }
    orchestrator, _ = make_orchestrator(tmp_path, scenario_script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.BLOCKED
    assert "permitted scope" in result.final.reason
    assert "src/planner-write.py" in result.final.reason
    # coding never started
    assert not list((tmp_path / ".metacoding" / "runs" / result.run_id / "rounds").glob("round-*"))


def test_coder_touching_metacoding_config_is_blocked(tmp_path: Path) -> None:
    scenario_script = scenario(
        code=[code_payload(files={".metacoding/config.toml": "# hijacked\n"})]
    )
    orchestrator, _ = make_orchestrator(tmp_path, scenario_script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.BLOCKED
    assert ".metacoding/config.toml" in result.final.reason


def test_tester_tampering_contract_docs_is_blocked(tmp_path: Path) -> None:
    scenario_script = scenario(
        test=[make_test_step(files={"docs/metacoding/PRD.md": "# rewritten by tester\n"})]
    )
    orchestrator, _ = make_orchestrator(tmp_path, scenario_script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.BLOCKED
    assert "docs/metacoding/PRD.md" in result.final.reason


def test_harness_git_commit_is_blocked(tmp_path: Path) -> None:
    import subprocess as sp

    sp.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    sp.run(["git", "-C", str(tmp_path), "config", "user.email", "t@e.st"], check=True)
    sp.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], check=True)
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    sp.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    sp.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True)

    scenario_script = scenario(
        code=[
            {
                "behavior": "git_commit",
                "files": {"src/audit.py": "log()\n"},
                "payload": code_payload()["payload"] if "payload" in code_payload() else code_payload(),
            }
        ],
    )
    orchestrator, _ = make_orchestrator(tmp_path, scenario_script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.BLOCKED
    assert "git state" in result.final.reason


# --- runtime evidence tampering and git metadata fingerprints -----------------------


def test_tester_rewriting_round_evidence_is_blocked(tmp_path: Path) -> None:
    tampered_test = dict(make_test_step())
    tampered_test = {"tamper_evidence": "coding-report.json", "payload": tampered_test}
    script = scenario(test=[tampered_test])
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.BLOCKED
    assert "runtime evidence" in result.final.reason
    assert "coding-report.json" in result.final.reason


def test_coder_tampering_state_json_is_blocked(tmp_path: Path) -> None:
    script = scenario(
        code=[code_payload(files={".metacoding/state.json": "{\"active_run_id\": \"fake\"}"})]
    )
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.BLOCKED
    assert "runtime evidence" in result.final.reason or ".metacoding/state.json" in result.final.reason


def test_harness_modifying_git_config_is_blocked(tmp_path: Path) -> None:
    import subprocess as sp

    sp.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    sp.run(["git", "-C", str(tmp_path), "config", "user.email", "t@e.st"], check=True)
    sp.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], check=True)
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    sp.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    sp.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True)

    # the coder overwrites .git/config during its stage
    step = code_payload(files={"src/audit.py": "log()\n"})
    step = {
        "files": {".git/config": "[core]\n\trepositoryformatversion = 0\n"},
        "payload": step["payload"] if "payload" in step else step,
    }
    script = scenario(code=[step])
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.BLOCKED
    assert ".git/config" in result.final.reason or "git" in result.final.reason.lower()


def test_harness_creating_ignored_file_is_blocked(tmp_path: Path) -> None:
    import subprocess as sp

    sp.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / ".gitignore").write_text("secrets/*\n", encoding="utf-8")
    sp.run(["git", "-C", str(tmp_path), "add", "-A"], check=True, capture_output=True)
    sp.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=a@b.c", "-c", "user.name=x",
         "commit", "-q", "-m", "init"],
        check=True, capture_output=True,
    )
    # the tester writes a gitignored secret file
    step = dict(make_test_step())
    step = {"files": {"secrets/leaked.env": "TOKEN=x\n"}, "payload": step}
    script = scenario(test=[step])
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.BLOCKED
    assert "secrets/leaked.env" in result.final.reason or "permitted scope" in result.final.reason


def test_final_report_commit_failure_is_recorded_in_final(tmp_path: Path) -> None:
    from metacoding.errors import GitDeliveryError

    class CommittingThenFailingDeliverer:
        def __init__(self):
            self.calls = 0

        def deliver(self, run_id, owned_files):
            self.calls += 1
            if self.calls == 1:
                return {"branch": f"metacoding/{run_id}", "commit": "sha-1",
                        "committed_files": owned_files, "pushed": False,
                        "checks_failed": False, "warnings": []}
            # the FINAL_REPORT follow-up commit fails
            raise GitDeliveryError("hook rejected the report commit")

    deliverer = CommittingThenFailingDeliverer()
    script = scenario(code=[code_payload(files={"src/audit.py": "log()\n"})])
    orchestrator, _ = make_orchestrator(
        tmp_path, script,
        replace(make_config(), github=replace(default_config().github, enabled=True)),
        deliverer=deliverer,
    )
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.DELIVERED
    assert deliverer.calls == 2
    assert any(
        "final report" in warning.lower() and "could not be committed" in warning.lower()
        for warning in result.final.warnings
    )
    # final.json and the delivery artifact both record the failure
    delivery = orchestrator.store.load_git_artifact(result.run_id, "delivery")
    assert delivery["final_report"]["committed"] is False
    assert "error" in delivery["final_report"]
    import json as _json
    final_json = _json.loads(
        (orchestrator.store.run_dir(result.run_id) / "final.json").read_text("utf-8")
    )
    assert any("could not be committed" in w for w in final_json["warnings"])


def test_coder_running_tests_creating_pycache_is_not_blocked(tmp_path: Path) -> None:
    import subprocess as sp

    sp.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / ".gitignore").write_text("", encoding="utf-8")  # nothing ignored at all
    sp.run(["git", "-C", str(tmp_path), "add", "-A"], check=True, capture_output=True)
    sp.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=a@b.c", "-c", "user.name=x",
         "commit", "-q", "-m", "init"],
        check=True, capture_output=True,
    )
    # the coder writes sources AND the pycache litter a pytest run creates
    script = scenario(
        code=[
            code_payload(
                files={
                    "src/audit.py": "log()\n",
                    "src/__pycache__/audit.cpython-310.pyc": "\x00compiled",
                    ".pytest_cache/v/cache": "x",
                }
            )
        ]
    )
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.DELIVERED


def test_tester_writing_its_own_test_report_is_allowed(tmp_path: Path) -> None:
    """Real testers write docs/metacoding/TEST_REPORT.md per their prompt;
    the stage write guard must allow exactly that file."""
    script = scenario(
        test=[
            make_test_step(
                files={"docs/metacoding/TEST_REPORT.md": "# Test Report\n\nwritten by tester\n"}
            )
        ]
    )
    orchestrator, _ = make_orchestrator(tmp_path, script)
    result = orchestrator.start("add audit logging")
    assert result.status is RunStatus.DELIVERED
