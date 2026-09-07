"""Git-owned diff, local delivery, and optional GitHub push/PR/CI checks."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from metacoding.config import default_config
from metacoding.errors import GitDeliveryError
from metacoding.github import GitDeliverer, RealGitClient

# --- real-git helpers -------------------------------------------------------------


def git(root: Path, *args: str, env: dict | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout.strip()


def init_repo(root: Path, *, anonymous: bool = False) -> None:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    if not anonymous:
        git(root, "config", "user.email", "test@example.com")
        git(root, "config", "user.name", "Test")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    if anonymous:
        # stage and commit the base file using one-shot identity flags
        subprocess.run(
            ["git", "-C", str(root), "add", "-A"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.email=a@b.c",
                "-c",
                "user.name=x",
                "commit",
                "-q",
                "-m",
                "init",
            ],
            check=True,
            capture_output=True,
            env=isolated_env(),
        )
    else:
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "init")


def isolated_env() -> dict:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        # forbid git's automatic username/hostname identity guessing
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "user.useConfigOnly",
        "GIT_CONFIG_VALUE_0": "true",
    }
    return env


def deliverer(root: Path, **github_overrides) -> GitDeliverer:
    config = default_config()
    github = replace(config.github, **github_overrides) if github_overrides else config.github
    config = replace(config, github=github)
    return GitDeliverer(root, config)


def committed_files(root: Path, branch: str) -> set[str]:
    return set(git(root, "ls-tree", "-r", "--name-only", branch).splitlines())


# --- local delivery safety ----------------------------------------------------------


def test_delivery_requires_git_repository(tmp_path: Path) -> None:
    with pytest.raises(GitDeliveryError) as excinfo:
        deliverer(tmp_path).deliver("run-1", ["src/a.py"])
    assert "not a git repository" in str(excinfo.value)


def test_local_delivery_creates_dedicated_branch_with_owned_commit(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "feature.py").write_text("print('new')\n", encoding="utf-8")
    summary = deliverer(tmp_path).deliver("run-42", ["src/feature.py"])

    assert summary["branch"] == "metacoding/run-42"
    assert summary["pushed"] is False
    assert summary["committed_files"] == ["src/feature.py"]
    assert committed_files(tmp_path, "metacoding/run-42") >= {"README.md", "src/feature.py"}
    assert git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD") == "metacoding/run-42"
    assert summary["commit"].strip()


def test_unrelated_preexisting_dirty_files_are_never_committed(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "unrelated.txt").write_text("user's own work\n", encoding="utf-8")  # pre-run dirty
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "feature.py").write_text("x = 1\n", encoding="utf-8")

    summary = deliverer(tmp_path).deliver("run-1", ["src/feature.py"])

    assert summary["committed_files"] == ["src/feature.py"]
    assert "unrelated.txt" not in committed_files(tmp_path, summary["branch"])
    # the user's dirty file survives untouched in the working tree
    assert (tmp_path / "unrelated.txt").read_text(encoding="utf-8") == "user's own work\n"
    status = git(tmp_path, "status", "--porcelain")
    assert "unrelated.txt" in status


def test_redelivery_extends_existing_branch_without_rewriting(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a\n", encoding="utf-8")
    first = deliverer(tmp_path).deliver("run-1", ["src/a.py"])
    first_commit = first["commit"]

    (tmp_path / "src" / "b.py").write_text("b\n", encoding="utf-8")
    second = deliverer(tmp_path).deliver("run-1", ["src/a.py", "src/b.py"])

    assert second["branch"] == "metacoding/run-1"
    assert second["commit"] != first_commit
    # the original commit is still an ancestor: no history was rewritten
    merge_base = git(tmp_path, "merge-base", "--is-ancestor", first_commit, "HEAD")
    assert merge_base == ""
    assert {"src/a.py", "src/b.py"} <= committed_files(tmp_path, "metacoding/run-1")


def test_first_delivery_with_no_owned_files_fails_clearly(tmp_path: Path) -> None:
    init_repo(tmp_path)
    with pytest.raises(GitDeliveryError) as excinfo:
        deliverer(tmp_path).deliver("run-1", [])
    assert "nothing to commit" in str(excinfo.value)


def test_commit_failure_is_reported(tmp_path: Path) -> None:
    init_repo(tmp_path, anonymous=True)
    # no repo-local identity and no global/system config: commit must fail
    client = RealGitClient(tmp_path, env=isolated_env())
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a\n", encoding="utf-8")
    deliv = GitDeliverer(tmp_path, default_config(), git_client=client)
    with pytest.raises(GitDeliveryError) as excinfo:
        deliv.deliver("run-1", ["src/a.py"])
    assert "commit" in str(excinfo.value).lower()


def test_staging_never_includes_unexpected_files(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a\n", encoding="utf-8")
    (tmp_path / "rogue").mkdir()
    (tmp_path / "rogue" / "evil.py").write_text("evil\n", encoding="utf-8")
    # a malicious `git add -A` would pick rogue up; deliverer stages explicit paths only
    summary = deliverer(tmp_path).deliver("run-1", ["src/a.py"])
    assert "rogue/evil.py" not in summary["committed_files"]
    assert "rogue/evil.py" not in committed_files(tmp_path, summary["branch"])


# --- fake remote collaborators --------------------------------------------------------


class FakeGitClient(RealGitClient):
    """Records pushes; fakes out everything that touches the worktree."""

    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)
        self.pushes: list = []

    def push(self, remote: str, branch: str, *, force: bool = False) -> str:
        self.pushes.append((remote, branch, force))
        return "pushed"

    def commit(self, message: str) -> str:
        return "fake-commit-sha"

    def staged_files(self) -> list[str]:
        return []

    def branch_exists(self, name: str) -> bool:
        return True

    def checkout(self, name: str) -> None:
        return None

    def add(self, paths) -> None:
        return None

    def head(self) -> str:
        return "fake-head"

    def current_branch(self) -> str:
        return "main"

    def is_repo(self) -> bool:
        return True


@dataclass
class FakeGhClient:
    pr_url: str = "https://github.com/org/repo/pull/7"
    checks_payload: list = field(default_factory=list)
    fail: bool = False
    pr_exists: bool = False
    calls: list = field(default_factory=list)

    def ensure_pr(self, remote: str, branch: str, title: str, body: str) -> dict:
        if self.fail:
            raise GitDeliveryError("gh unavailable")
        self.calls.append(("ensure_pr", remote, branch, title, body))
        if self.pr_exists:
            self.calls.append(("pr_edit", branch, title, body))
            return {"url": self.pr_url, "created": False}
        return {"url": self.pr_url, "created": True}

    def checks(self, remote: str, branch: str) -> list[dict]:
        if self.fail:
            raise GitDeliveryError("gh unavailable")
        self.calls.append(("checks", remote, branch))
        return list(self.checks_payload)

    def wait_for_checks(
        self,
        remote: str,
        branch: str,
        *,
        timeout_seconds: int,
        poll_seconds: int,
        sleeper=None,
    ) -> list[dict]:
        # The fake settles immediately: no PENDING states are returned.
        return self.checks(remote, branch)


def remote_deliverer(
    tmp_path: Path, git_client: FakeGitClient, gh_client: FakeGhClient, **github_overrides
) -> GitDeliverer:
    config = default_config()
    github = replace(config.github, enabled=True, **github_overrides)
    config = replace(config, github=github)
    return GitDeliverer(
        tmp_path, config, git_client=git_client, gh_client=gh_client
    )


def test_push_disabled_by_default_keeps_everything_local(tmp_path: Path) -> None:
    git_client, gh_client = FakeGitClient(tmp_path), FakeGhClient()
    deliv = remote_deliverer(tmp_path, git_client, gh_client, auto_push=False, auto_create_pr=False)
    summary = deliv.deliver("run-1", ["src/a.py"])
    assert summary["pushed"] is False
    assert git_client.pushes == []
    assert gh_client.calls == []


def test_push_uses_dedicated_branch_and_never_forces(tmp_path: Path) -> None:
    git_client, gh_client = FakeGitClient(tmp_path), FakeGhClient()
    deliv = remote_deliverer(tmp_path, git_client, gh_client, auto_push=True)
    summary = deliv.deliver("run-1", ["src/a.py"])
    assert git_client.pushes == [("origin", "metacoding/run-1", False)]
    assert summary["pushed"] is True
    assert summary["branch"] == "metacoding/run-1"


def test_pr_created_when_enabled(tmp_path: Path) -> None:
    git_client, gh_client = FakeGitClient(tmp_path), FakeGhClient()
    deliv = remote_deliverer(
        tmp_path, git_client, gh_client, auto_push=True, auto_create_pr=True
    )
    summary = deliv.deliver("run-1", ["src/a.py"])
    assert summary["pr"] == {"url": FakeGhClient.pr_url, "created": True}
    assert gh_client.calls[0][0] == "ensure_pr"


def test_failed_required_checks_are_reported(tmp_path: Path) -> None:
    git_client = FakeGitClient(tmp_path)
    gh_client = FakeGhClient(checks_payload=[{"name": "ci", "state": "FAILURE"}])
    deliv = remote_deliverer(
        tmp_path,
        git_client,
        gh_client,
        auto_push=True,
        auto_create_pr=True,
        wait_for_checks=True,
    )
    summary = deliv.deliver("run-1", ["src/a.py"])
    assert summary["checks_failed"] is True
    assert ("checks", "origin", "metacoding/run-1") in gh_client.calls


def test_passing_checks(tmp_path: Path) -> None:
    git_client = FakeGitClient(tmp_path)
    gh_client = FakeGhClient(checks_payload=[{"name": "ci", "state": "SUCCESS"}])
    deliv = remote_deliverer(
        tmp_path, git_client, gh_client, auto_push=True, wait_for_checks=True
    )
    summary = deliv.deliver("run-1", ["src/a.py"])
    assert summary["checks_failed"] is False


def test_remote_unavailability_is_a_warning_not_a_local_failure(tmp_path: Path) -> None:
    git_client = FakeGitClient(tmp_path)
    gh_client = FakeGhClient(fail=True)
    deliv = remote_deliverer(
        tmp_path, git_client, gh_client, auto_push=True, auto_create_pr=True, wait_for_checks=True
    )
    summary = deliv.deliver("run-1", ["src/a.py"])
    assert summary["pushed"] is True  # git push itself succeeded
    assert any("pull request" in warning.lower() for warning in summary["warnings"])
    assert any("check" in warning.lower() for warning in summary["warnings"])
    assert summary["checks_failed"] is False


def test_existing_pr_is_updated_not_duplicated(tmp_path: Path) -> None:
    git_client = FakeGitClient(tmp_path)
    gh_client = FakeGhClient(pr_exists=True)
    deliv = remote_deliverer(
        tmp_path, git_client, gh_client, auto_push=True, auto_create_pr=True
    )
    summary = deliv.deliver("run-1", ["src/a.py"])
    assert summary["pr"] == {"url": FakeGhClient.pr_url, "created": False}
    assert any(call[0] == "pr_edit" for call in gh_client.calls)


def test_checks_not_waited_when_disabled(tmp_path: Path) -> None:
    git_client = FakeGitClient(tmp_path)
    gh_client = FakeGhClient(checks_payload=[{"name": "ci", "state": "FAILURE"}])
    deliv = remote_deliverer(
        tmp_path, git_client, gh_client, auto_push=True, wait_for_checks=False
    )
    summary = deliv.deliver("run-1", ["src/a.py"])
    assert ("checks", "origin", "metacoding/run-1") not in gh_client.calls
    assert summary["checks_failed"] is False


# --- CI failure returns the run to tester evidence and planner review ---------------


def _ci_orchestrator(tmp_path: Path, deliverer):
    from dataclasses import replace as _replace

    from metacoding.config import HarnessConfig, default_config
    from metacoding.harnesses.fake import FakeCoder, FakePlanner, FakeTester
    from metacoding.orchestrator import Orchestrator

    config = default_config()
    fake = HarnessConfig(name="x", provider="fake", command="python3", model="", extra_args=[])
    config = _replace(
        config,
        harness={
            "planner": _replace(fake, name="planner"),
            "coder": _replace(fake, name="coder"),
            "tester": _replace(fake, name="tester"),
        },
        github=_replace(config.github, enabled=True, wait_for_checks=True),
    )
    test_steps = [
        {
            "status": "pass",
            "test_commands": [
                {"command": "python3 -m pytest -q", "exit_code": 0, "summary": "ok"}
            ],
            "acceptance_results": [
                {"id": "F-001", "status": "pass", "impact": "high", "evidence": ["t"]}
            ],
            "findings": [],
            "prd_drift": [],
            "regression_risks": [],
            "missing_tests": [],
            "changed_files": [],
        }
    ]
    scenario = {
        "attempts": {
            "plan": [
                {
                    "goal": "g",
                    "scope": [],
                    "non_goals": [],
                    "architecture": {
                        "approach": "a",
                        "modules": [],
                        "data_flow": [],
                        "risks": [],
                    },
                    "acceptance_criteria": [
                        {
                            "id": "F-001",
                            "description": "works",
                            "priority": "blocking",
                            "verification_method": "tests",
                        }
                    ],
                    "coding_tasks": [
                        {
                            "id": "TASK-001",
                            "description": "implement",
                            "expected_files": ["src/a.py"],
                            "required_tests": [],
                            "done_when": "tests pass",
                        }
                    ],
                    "change_policy": {
                        "allowed_paths": ["src/**"],
                        "protected_paths": [],
                        "forbidden_actions": [],
                    },
                }
            ],
            "code": [
                {
                    "files": {"src/a.py": "a\n"},
                    "payload": {
                        "status": "completed",
                        "summary": "done",
                        "completed_tasks": [],
                        "changed_files": ["src/a.py"],
                        "tests_added_or_changed": [],
                        "commands_run": [],
                        "known_limitations": [],
                        "blocked_reason": None,
                    },
                }
            ],
            "test": test_steps,
            "review": [
                {"decision": "accept", "reason": "ok", "blocking_findings": [], "rework_tasks": []}
            ],
        }
    }
    return Orchestrator(
        project_root=tmp_path,
        config=config,
        harnesses={
            "planner": FakePlanner(config.harness["planner"], tmp_path, scenario),
            "coder": FakeCoder(config.harness["coder"], tmp_path, scenario),
            "tester": FakeTester(config.harness["tester"], tmp_path, scenario),
        },
        deliverer=deliverer,
    )


class ChecksFailOnce:
    def __init__(self) -> None:
        self.calls = 0
        self.tester_runs = 0

    def deliver(self, run_id: str, owned_files: list[str]) -> dict:
        self.calls += 1
        return {
            "branch": f"metacoding/{run_id}",
            "commit": "sha",
            "committed_files": list(owned_files),
            "pushed": True,
            "checks": [{"name": "ci", "state": "FAILURE" if self.calls == 1 else "SUCCESS"}],
            "checks_failed": self.calls == 1,
            "warnings": [],
        }


def test_failed_required_checks_return_run_to_review_then_deliver(tmp_path: Path) -> None:
    deliverer = ChecksFailOnce()
    orchestrator = _ci_orchestrator(tmp_path, deliverer)
    tester = orchestrator.harnesses["tester"]
    original_test = tester.test

    def counting_test(ctx):
        deliverer.tester_runs += 1
        return original_test(ctx)

    tester.test = counting_test
    result = orchestrator.start("add audit logging")
    assert result.status.value == "delivered"
    assert deliverer.calls == 2
    assert deliverer.tester_runs == 2
    assert result.final.rounds_used == 1  # stayed on the same round
    assert any("ci" in warning.lower() for warning in result.final.warnings)


def test_checks_ignored_without_wait_for_checks(tmp_path: Path) -> None:
    from dataclasses import replace as _replace

    class AlwaysFailingChecks(ChecksFailOnce):
        def deliver(self, run_id: str, owned_files: list[str]) -> dict:
            summary = super().deliver(run_id, owned_files)
            summary["checks_failed"] = True
            return summary

    deliverer = AlwaysFailingChecks()
    orchestrator = _ci_orchestrator(tmp_path, deliverer)
    config = _replace(orchestrator.config, github=_replace(orchestrator.config.github, wait_for_checks=False))
    orchestrator.config = config
    result = orchestrator.start("add audit logging")
    assert result.status.value == "delivered"
    assert deliverer.calls == 1


# --- check parsing, polling, and delivery modes --------------------------------------


def test_gh_checks_parse_failure_and_pending_states(tmp_path: Path, monkeypatch) -> None:
    from metacoding.github import GhClient

    client = GhClient(tmp_path)
    payload = (
        "ci  fail  1m  https://example.com/ci\n"
        "lint pending 2s https://example.com/lint\n"
        "name state elapsed details\n"
    )

    class FakeResult:
        returncode = 8  # gh exits non-zero when checks fail or are pending
        stdout = payload
        stderr = ""

    monkeypatch.setattr(
        "metacoding.github.subprocess.run", lambda *a, **k: FakeResult()
    )
    checks = client.checks("origin", "metacoding/run-1")
    assert {"name": "ci", "state": "FAILURE"} in checks
    assert {"name": "lint", "state": "PENDING"} in checks
    assert len(checks) == 2  # header line ignored


def test_wait_for_checks_polls_until_settled(tmp_path: Path) -> None:
    from metacoding.github import GhClient

    client = GhClient(tmp_path)
    waves = iter(
        [
            [{"name": "ci", "state": "PENDING"}],
            [{"name": "ci", "state": "PENDING"}],
            [{"name": "ci", "state": "SUCCESS"}],
        ]
    )
    sleeps: list[int] = []
    client.checks = lambda remote, branch: next(waves)
    final = client.wait_for_checks(
        "origin", "b", timeout_seconds=60, poll_seconds=1, sleeper=sleeps.append
    )
    assert final == [{"name": "ci", "state": "SUCCESS"}]
    assert sleeps == [1, 1]


def test_wait_for_checks_times_out_with_pending(tmp_path: Path) -> None:
    from metacoding.github import GhClient

    client = GhClient(tmp_path)
    client.checks = lambda remote, branch: [{"name": "ci", "state": "PENDING"}]
    final = client.wait_for_checks(
        "origin", "b", timeout_seconds=0, poll_seconds=1, sleeper=lambda s: None
    )
    assert final == [{"name": "ci", "state": "PENDING"}]


def test_mode_none_skips_all_delivery_actions(tmp_path: Path) -> None:
    git_client = FakeGitClient(tmp_path)
    gh_client = FakeGhClient()
    deliv = remote_deliverer(
        tmp_path, git_client, gh_client, auto_push=True, auto_create_pr=True, mode="none"
    )
    summary = deliv.deliver("run-1", ["src/a.py"])
    assert summary["mode"] == "none"
    assert summary["branch"] is None
    assert git_client.pushes == [] and gh_client.calls == []


def test_auto_commit_false_skips_branch_commit_and_remote(tmp_path: Path) -> None:
    git_client = FakeGitClient(tmp_path)
    gh_client = FakeGhClient()
    deliv = remote_deliverer(
        tmp_path, git_client, gh_client, auto_push=True, auto_create_pr=True, auto_commit=False
    )
    summary = deliv.deliver("run-1", ["src/a.py"])
    assert summary["branch"] is None and summary["commit"] is None
    assert git_client.pushes == [] and gh_client.calls == []
    assert any("auto_commit" in warning for warning in summary["warnings"])


def test_mode_branch_never_creates_pr(tmp_path: Path) -> None:
    git_client = FakeGitClient(tmp_path)
    gh_client = FakeGhClient()
    deliv = remote_deliverer(
        tmp_path, git_client, gh_client, auto_push=True, auto_create_pr=True, mode="branch"
    )
    summary = deliv.deliver("run-1", ["src/a.py"])
    assert git_client.pushes == [("origin", "metacoding/run-1", False)]
    assert all(call[0] != "ensure_pr" for call in gh_client.calls)
    assert summary["pr"] is None
