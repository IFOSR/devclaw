"""End-to-end scenarios through the full stack: config, CLI, service, and
subprocess fake harnesses. No Codex, Pi, GitHub, or network is required."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from metacoding.cli import EXIT_OK, EXIT_RUN_REJECTED, main as cli_main
from metacoding.config import default_config
from metacoding.harnesses.fake import write_scenario
from metacoding.service import MetaCodingService

REPO_ROOT = Path(__file__).resolve().parents[2]

PLAN_STEP = {
    "goal": "Add audit logging",
    "scope": ["src"],
    "non_goals": [],
    "architecture": {
        "approach": "append audit entries on admin mutations",
        "modules": ["src/audit.py"],
        "data_flow": ["mutation -> audit -> store"],
        "risks": [],
    },
    "acceptance_criteria": [
        {
            "id": "F-001",
            "description": "audit entries are appended",
            "priority": "blocking",
            "verification_method": "run the project tests",
        }
    ],
    "coding_tasks": [
        {
            "id": "TASK-001",
            "description": "implement the audit hook",
            "expected_files": ["src/audit.py"],
            "required_tests": [],
            "done_when": "tests pass",
        }
    ],
    "change_policy": {
        "allowed_paths": ["src/**", "tests/**", "docs/metacoding"],
        "protected_paths": ["docs/metacoding/PRD.md"],
        "forbidden_actions": [],
    },
}


def code_step(files: dict | None = None) -> dict:
    payload = {
        "status": "completed",
        "summary": "implemented the audit hook",
        "completed_tasks": ["TASK-001"],
        "changed_files": ["src/audit.py"],
        "tests_added_or_changed": [],
        "commands_run": [],
        "known_limitations": [],
        "blocked_reason": None,
    }
    if files:
        return {"files": files, "payload": payload}
    return payload


def make_test_step(
    *,
    status: str = "pass",
    failing: bool = False,
    findings: list | None = None,
    command_exit: int = 0,
    files: dict | None = None,
) -> dict:
    payload = {
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
        "changed_files": [],
    }
    if files:
        return {"files": files, "payload": payload}
    return payload


def review_step(decision: str = "accept") -> dict:
    payload = {
        "decision": decision,
        "reason": "evidence reviewed",
        "blocking_findings": [],
        "rework_tasks": [],
    }
    if decision == "rework":
        payload["rework_tasks"] = [
            {
                "id": "REWORK-001",
                "description": "fix the failing acceptance check",
                "target_area": ["src/audit.py"],
                "verification": "rerun the tests",
            }
        ]
    return payload


P1_FINDING = {
    "id": "BUG-001",
    "type": "bug",
    "severity": "P1",
    "title": "crash on empty input",
    "impact": "high",
    "reproduction": ["run x"],
    "evidence": ["traceback"],
    "recommended_fix": "guard the input",
}


def make_project(
    tmp_path: Path,
    attempts: dict[str, list],
    *,
    max_rounds: int = 4,
    same_failure_limit: int = 2,
    github: dict | None = None,
    git_init: bool = False,
) -> Path:
    root = tmp_path / "project"
    root.mkdir(parents=True)
    if git_init:
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "t@e.st"], check=True
        )
        subprocess.run(["git", "-C", str(root), "config", "user.name", "T"], check=True)
        (root / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True
        )

    scenario = {"attempts": attempts}
    scenario_path = write_scenario(root, scenario)
    harness_block = (
        "[harness.{name}]\n"
        'provider = "fake"\n'
        'command = "{python}"\n'
        'model = "{name}-model"\n'
        'extra_args = ["-m", "metacoding.harnesses.fake", "--scenario", "{scenario}"]\n'
    ).format(name="{name}", python=sys.executable, scenario=scenario_path)
    github_block = ""
    if github:
        github_block = "\n[github]\n" + "\n".join(
            f"{key} = {json.dumps(value)}" for key, value in github.items()
        )
    config_toml = (
        "[limits]\n"
        f"max_rounds = {max_rounds}\n"
        f"same_failure_limit = {same_failure_limit}\n"
        "idle_timeout_seconds = 30\n"
        "\n" + harness_block.replace("{name}", "planner")
        + "\n" + harness_block.replace("{name}", "coder")
        + "\n" + harness_block.replace("{name}", "tester")
        + github_block
        + "\n"
    )
    config_dir = root / ".metacoding"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(config_toml, encoding="utf-8")
    return root


def default_attempts(**overrides) -> dict[str, list]:
    attempts = {
        "plan": [PLAN_STEP],
        "code": [code_step(files={"src/audit.py": "def log(): pass\n"})],
        "test": [make_test_step()],
        "review": [review_step()],
    }
    attempts.update(overrides)
    return attempts


# --- scenarios -------------------------------------------------------------------


def test_cli_run_accepted_full_stack(tmp_path: Path, capsys) -> None:
    root = make_project(tmp_path, default_attempts())
    code = cli_main(["--project-root", str(root), "run", "add audit logging"])
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "[planning]" in out and "[coding]" in out and "[done]" in out

    runs_dir = root / ".metacoding" / "runs"
    run_id = next(path.name for path in runs_dir.iterdir())
    run_dir = runs_dir / run_id
    assert (run_dir / "initial-plan.json").is_file()
    assert (run_dir / "final.json").is_file()
    assert (run_dir / "rounds" / "round-001" / "coding-report.json").is_file()
    assert (run_dir / "transcripts" / "fake-planner-plan-1.json").is_file()
    assert (root / "docs" / "metacoding" / "PRD.md").is_file()
    assert (root / "docs" / "metacoding" / "FINAL_REPORT.md").is_file()
    assert (root / "src" / "audit.py").read_text(encoding="utf-8").startswith("def log")
    assert not (root / ".metacoding" / "state.json").is_file()
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final["outcome"] == "delivered"


def test_rework_then_accept_e2e(tmp_path: Path) -> None:
    root = make_project(
        tmp_path,
        default_attempts(
            test=[
                make_test_step(status="fail", failing=True, findings=[P1_FINDING]),
                make_test_step(),
            ],
            review=[review_step("rework"), review_step("accept")],
        ),
    )
    result = MetaCodingService(project_root=root).run("add audit logging")
    assert result.exit_code == EXIT_OK
    runs_dir = root / ".metacoding" / "runs"
    run_dir = next(runs_dir.iterdir())
    assert (run_dir / "rounds" / "round-002").is_dir()
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final["rounds_used"] == 2


def test_repeated_failure_blocks_e2e(tmp_path: Path) -> None:
    root = make_project(
        tmp_path,
        default_attempts(
            test=[make_test_step(status="fail", failing=True, findings=[P1_FINDING])],
            review=[review_step("rework")],
        ),
        max_rounds=5,
        same_failure_limit=2,
    )
    result = MetaCodingService(project_root=root).run("add audit logging")
    assert result.exit_code == EXIT_RUN_REJECTED
    run_dir = next((root / ".metacoding" / "runs").iterdir())
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final["outcome"] == "blocked"
    assert "failure" in final["reason"].lower()


def test_max_rounds_blocks_e2e(tmp_path: Path) -> None:
    root = make_project(
        tmp_path,
        default_attempts(review=[review_step("rework")]),
        max_rounds=2,
    )
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_audit.py").write_text(
        "def test_audit():\n    assert False\n", encoding="utf-8"
    )
    result = MetaCodingService(project_root=root).run("add audit logging")
    assert result.exit_code == EXIT_RUN_REJECTED
    run_dir = next((root / ".metacoding" / "runs").iterdir())
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final["outcome"] == "blocked"
    assert "max rounds" in final["reason"].lower()


def test_planner_accept_overridden_by_gates_e2e(tmp_path: Path) -> None:
    root = make_project(
        tmp_path,
        default_attempts(
            test=[
                make_test_step(status="fail", failing=True, command_exit=1, findings=[P1_FINDING]),
                make_test_step(),
            ],
            review=[review_step("accept"), review_step("accept")],
        ),
    )
    result = MetaCodingService(project_root=root).run("add audit logging")
    assert result.exit_code == EXIT_OK
    run_dir = next((root / ".metacoding" / "runs").iterdir())
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final["rounds_used"] == 2
    assert any("gate" in warning.lower() for warning in final["warnings"])


def test_tester_contamination_blocks_e2e(tmp_path: Path) -> None:
    root = make_project(
        tmp_path,
        default_attempts(test=[make_test_step(files={"src/audit.py": "tampered\n"})]),
    )
    result = MetaCodingService(project_root=root).run("add audit logging")
    assert result.exit_code == EXIT_RUN_REJECTED
    run_dir = next((root / ".metacoding" / "runs").iterdir())
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final["outcome"] == "blocked"
    assert "contaminat" in final["reason"].lower()


def test_resume_completes_persisted_run_e2e(tmp_path: Path) -> None:
    from metacoding.config import load_config
    from metacoding.models import ProjectSnapshot, now_utc
    from metacoding.persistence import RunStore

    root = make_project(tmp_path, default_attempts())
    store = RunStore(root)
    # snapshot the project's ACTUAL (fake-harness) configuration so resume
    # rebuilds the same harnesses the run started with
    record = store.create_run(
        "add audit logging",
        load_config(root),
        ProjectSnapshot(
            captured_at=now_utc(),
            is_git_repo=False,
            git_head=None,
            dirty_files=[],
            file_inventory=[],
            test_commands=[],
        ),
    )
    service = MetaCodingService(project_root=root)
    status = service.status()
    assert status.status == "active"

    result = service.resume()
    assert result.exit_code == EXIT_OK
    assert result.run_id == record.run_id
    assert (store.run_dir(record.run_id) / "final.json").is_file()


def test_github_fake_delivery_local_branch_e2e(tmp_path: Path) -> None:
    root = make_project(
        tmp_path,
        default_attempts(),
        git_init=True,
        github={"enabled": True, "auto_push": False, "auto_create_pr": False},
    )
    # a pre-existing dirty file must never be committed
    (root / "user-notes.txt").write_text("user's own work\n", encoding="utf-8")
    result = MetaCodingService(project_root=root).run("add audit logging")
    assert result.exit_code == EXIT_OK
    run_dir = next((root / ".metacoding" / "runs").iterdir())
    delivery = json.loads((run_dir / "git" / "delivery.json").read_text("utf-8"))
    assert delivery["pushed"] is False
    assert "src/audit.py" in delivery["committed_files"]
    assert "user-notes.txt" not in delivery["committed_files"]
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "--name-only", delivery["branch"]],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "src/audit.py" in listed
    assert "user-notes.txt" not in listed
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final["github"]["branch"] == delivery["branch"]


def test_status_report_artifacts_and_help_smoke(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    empty = tmp_path / "empty-project"
    empty.mkdir()

    help_run = subprocess.run(
        [sys.executable, "-m", "metacoding", "--help"],
        cwd=empty,
        env=env,
        capture_output=True,
        text=True,
    )
    assert help_run.returncode == 0
    assert "metacoding" in help_run.stdout

    status_run = subprocess.run(
        [sys.executable, "-m", "metacoding", "--project-root", str(empty), "status"],
        cwd=empty,
        env=env,
        capture_output=True,
        text=True,
    )
    assert status_run.returncode == 0
    assert "no runs recorded" in status_run.stdout
    assert "config.toml" in status_run.stdout  # configuration guidance, no network

    root = make_project(tmp_path, default_attempts())
    assert cli_main(["--project-root", str(root), "run", "add audit logging"]) == EXIT_OK
    assert cli_main(["--project-root", str(root), "status"]) == EXIT_OK
    assert cli_main(["--project-root", str(root), "report"]) == EXIT_OK
    assert cli_main(["--project-root", str(root), "artifacts"]) == EXIT_OK


def test_active_run_lock_blocks_second_start_e2e(tmp_path: Path) -> None:
    root = make_project(tmp_path, default_attempts())
    service = MetaCodingService(project_root=root)
    from metacoding.locking import project_lock

    with project_lock(root, "someone-else"):
        outcome = service.run("another requirement")
        assert outcome.exit_code == 3
        assert "already active" in outcome.message


# --- host-executed deterministic verification ---------------------------------------


def test_host_executed_checks_override_lying_tester(tmp_path: Path) -> None:
    # The project has a real failing pytest suite; the fake tester lies and
    # reports success. The host runs the detected command itself, so the
    # deterministic gate must fail until round 2 actually fixes the test.
    root = make_project(
        tmp_path,
        default_attempts(
            code=[
                # round 1: implement feature but ship a failing test
                code_step(
                    files={
                        "src/audit.py": "def log(): pass\n",
                        "tests/test_audit.py": "def test_audit():\n    assert False\n",
                    }
                ),
                # round 2: fix the test
                code_step(
                    files={
                        "src/audit.py": "def log(): pass\n",
                        "tests/test_audit.py": "def test_audit():\n    assert True\n",
                    }
                ),
            ],
            review=[review_step("accept"), review_step("accept")],
        ),
        max_rounds=3,
    )
    # the failing test exists BEFORE the run starts so the host detects and
    # executes the project's own test command
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_audit.py").write_text(
        "def test_audit():\n    assert False\n", encoding="utf-8"
    )
    result = MetaCodingService(project_root=root).run("add audit logging")
    assert result.exit_code == EXIT_OK
    run_dir = next((root / ".metacoding" / "runs").iterdir())
    host_checks = json.loads(
        (run_dir / "rounds" / "round-001" / "host-checks.json").read_text("utf-8")
    )
    assert host_checks["checks"][0]["exit_code"] != 0  # host really executed it
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final["rounds_used"] == 2
    assert any(
        "deterministic" in warning.lower() or "host" in warning.lower()
        for warning in final["warnings"]
    )


def test_host_check_failure_with_no_fix_blocks(tmp_path: Path) -> None:
    root = make_project(
        tmp_path,
        default_attempts(
            code=[
                code_step(files={"src/audit.py": "def log(): pass\n",
                                 "tests/test_audit.py": "def test_audit():\n    assert False\n"})
            ],
            review=[review_step("accept")],
        ),
        max_rounds=2,
    )
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_audit.py").write_text(
        "def test_audit():\n    assert False\n", encoding="utf-8"
    )
    result = MetaCodingService(project_root=root).run("add audit logging")
    assert result.exit_code == EXIT_RUN_REJECTED
    run_dir = next((root / ".metacoding" / "runs").iterdir())
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final["outcome"] == "blocked"


# --- owned-diff delivery hardening ----------------------------------------------------


def _git_project(tmp_path: Path, attempts: dict, **kwargs) -> Path:
    return make_project(tmp_path, attempts, git_init=True, **kwargs)


def test_mixed_preexisting_dirty_file_is_never_committed(tmp_path: Path) -> None:
    root = _git_project(
        tmp_path,
        default_attempts(
            # the coder edits a file that was already dirty before the run
            code=[code_step(files={"src/audit.py": "def log(): pass\n",
                                   "user-notes.txt": "user edits + coder edits\n"})],
        ),
        github={"enabled": True, "auto_push": False, "auto_create_pr": False},
    )
    # make user-notes.txt dirty BEFORE the run starts
    (root / "user-notes.txt").write_text("user's own work\n", encoding="utf-8")
    result = MetaCodingService(project_root=root).run("add audit logging")
    assert result.exit_code == EXIT_OK
    run_dir = next((root / ".metacoding" / "runs").iterdir())
    delivery = json.loads((run_dir / "git" / "delivery.json").read_text("utf-8"))
    assert "user-notes.txt" not in delivery["committed_files"]
    assert "src/audit.py" in delivery["committed_files"]
    assert any("mixed" in warning.lower() for warning in delivery["warnings"])
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "--name-only", delivery["branch"]],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "user-notes.txt" not in listed


def test_out_of_scope_round1_file_is_not_delivered_after_clean_round2(tmp_path: Path) -> None:
    root = _git_project(
        tmp_path,
        default_attempts(
            code=[
                code_step(files={"src/audit.py": "def log(): pass\n",
                                 "outside/scope.py": "x = 1\n"}),
                code_step(files={"src/audit.py": "def log(): pass\n"}),
            ],
            review=[review_step("rework"), review_step("accept")],
        ),
        github={"enabled": True, "auto_push": False, "auto_create_pr": False},
        max_rounds=3,
    )
    result = MetaCodingService(project_root=root).run("add audit logging")
    assert result.exit_code == EXIT_OK
    run_dir = next((root / ".metacoding" / "runs").iterdir())
    delivery = json.loads((run_dir / "git" / "delivery.json").read_text("utf-8"))
    assert "outside/scope.py" not in delivery["committed_files"]
    assert "src/audit.py" in delivery["committed_files"]
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "--name-only", delivery["branch"]],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "outside/scope.py" not in listed
