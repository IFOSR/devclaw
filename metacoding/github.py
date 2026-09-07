"""Safe Git/GitHub delivery: dedicated branch, owned-diff-only commits.

Safety rules enforced here:

- Delivery happens on ``<branch_prefix><run-id>`` branches only.
- Only the run's owned files are staged; pre-existing dirty files and
  unrelated changes are never committed.
- No force-push and no rewriting of existing commits: redelivery adds a
  new commit on top of the existing delivery branch.
- Remote actions (push, Pull Request, checks) run only when explicitly
  enabled, and remote unavailability is recorded as a warning rather than
  invalidating an accepted local implementation.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from metacoding.errors import GitDeliveryError

SUCCESS_CHECK_STATES = ("SUCCESS", "success", "PASS", "pass", "SKIPPED", "skipped")


class RealGitClient:
    """Thin subprocess wrapper around the git CLI."""

    def __init__(self, project_root: Path, env: dict[str, str] | None = None) -> None:
        self.project_root = Path(project_root)
        self.env = env

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["git", "-C", str(self.project_root), *args],
            capture_output=True,
            text=True,
            env=self.env,
        )
        if check and result.returncode != 0:
            raise GitDeliveryError(
                f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        return result

    def is_repo(self) -> bool:
        return self.run("rev-parse", "--is-inside-work-tree", check=False).returncode == 0

    def current_branch(self) -> str | None:
        result = self.run("rev-parse", "--abbrev-ref", "HEAD", check=False)
        if result.returncode != 0 or result.stdout.strip() == "HEAD":
            return None
        return result.stdout.strip()

    def head(self) -> str:
        return self.run("rev-parse", "HEAD").stdout.strip()

    def branch_exists(self, name: str) -> bool:
        return (
            self.run(
                "rev-parse", "--verify", "--quiet", f"refs/heads/{name}", check=False
            ).returncode
            == 0
        )

    def checkout_new_branch(self, name: str) -> None:
        self.run("switch", "-c", name)

    def checkout(self, name: str) -> None:
        self.run("switch", name)

    def add(self, paths: list[str]) -> None:
        if paths:
            self.run("add", "--", *paths)

    def staged_files(self) -> list[str]:
        output = self.run("diff", "--cached", "--name-only").stdout
        return [line for line in output.splitlines() if line.strip()]

    def commit(self, message: str) -> str:
        self.run("commit", "-m", message)
        return self.head()

    def push(self, remote: str, branch: str, *, force: bool = False) -> str:
        if force:  # pragma: no cover - hard guard against misuse
            raise GitDeliveryError("force-push is never allowed")
        self.run("push", remote, branch)
        return f"{remote}/{branch}"


class GhClient:
    """GitHub operations through the installed, authenticated ``gh`` CLI."""

    #: ``gh pr checks`` exits non-zero when checks fail or are pending;
    #: those states are data, not errors.
    CHECK_STATE_ALIASES = {
        "pass": "SUCCESS",
        "success": "SUCCESS",
        "fail": "FAILURE",
        "failure": "FAILURE",
        "failed": "FAILURE",
        "error": "FAILURE",
        "pending": "PENDING",
        "queued": "PENDING",
        "cancel": "CANCELLED",
        "cancelled": "CANCELLED",
        "skipping": "SKIPPED",
        "skipped": "SKIPPED",
    }

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        try:
            result = subprocess.run(
                ["gh", *args],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise GitDeliveryError("gh CLI is not installed") from exc
        if check and result.returncode != 0:
            raise GitDeliveryError(
                f"gh {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        return result

    def ensure_pr(self, remote: str, branch: str, title: str, body: str) -> dict:
        try:
            create = self._run(
                "pr",
                "create",
                "--head",
                branch,
                "--title",
                title,
                "--body",
                body,
            )
            for line in create.stdout.splitlines():
                if line.strip().startswith("http"):
                    return {"url": line.strip(), "created": True}
            return {"url": "", "created": True}
        except GitDeliveryError:
            # A pull request for this branch may already exist: update it.
            view = self._run(
                "pr", "view", branch, "--json", "url", check=False
            )
            if view.returncode != 0:
                raise
            url = ""
            try:
                url = json.loads(view.stdout).get("url", "")
            except json.JSONDecodeError:
                url = ""
            self._run("pr", "edit", branch, "--title", title, "--body", body)
            return {"url": url, "created": False}

    def checks(self, remote: str, branch: str) -> list[dict]:
        """Required-check states for the branch's pull request.

        Prefers ``gh pr checks <branch> --required --json bucket,name,state``
        so names containing spaces and the cancel bucket are handled. Falls
        back to parsing the legacy text output. Non-zero exit codes are data
        (failed/pending checks), not errors; only missing output is.
        """
        result = self._run(
            "pr", "checks", branch, "--required", "--json", "bucket,name,state",
            check=False,
        )
        if result.stdout.strip():
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, list):
                checks: list[dict] = []
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    # bucket is authoritative; state is a fallback. Unknown
                    # values fail CLOSED (treated as not-passed) instead of
                    # being dropped.
                    raw_bucket = str(item.get("bucket") or "").lower()
                    raw_state = str(item.get("state") or "").lower()
                    state = (
                        self.CHECK_STATE_ALIASES.get(raw_bucket)
                        or self.CHECK_STATE_ALIASES.get(raw_state)
                        or "UNKNOWN"
                    )
                    checks.append({"name": str(item.get("name", "")), "state": state})
                return checks
        # Legacy text output fallback.
        text_result = self._run("pr", "checks", branch, check=False)
        if not text_result.stdout.strip():
            if text_result.returncode != 0:
                raise GitDeliveryError(
                    f"gh pr checks {branch} failed: "
                    f"{text_result.stderr.strip() or text_result.returncode}"
                )
            return []
        checks = []
        for line in text_result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            name, raw_state = parts[0], parts[1].lower()
            if name.lower() == "name" or raw_state not in self.CHECK_STATE_ALIASES:
                continue
            checks.append(
                {"name": name, "state": self.CHECK_STATE_ALIASES[raw_state]}
            )
        return checks

    def wait_for_checks(
        self,
        remote: str,
        branch: str,
        *,
        timeout_seconds: int,
        poll_seconds: int,
        sleeper=None,
    ) -> list[dict]:
        """Poll required checks until they settle or the timeout expires."""
        sleep = sleeper or time.sleep
        deadline = time.monotonic() + max(timeout_seconds, 0)
        while True:
            checks = self.checks(remote, branch)
            if not any(check["state"] == "PENDING" for check in checks):
                return checks
            if time.monotonic() >= deadline:
                return checks
            sleep(max(poll_seconds, 1))


class GitDeliverer:
    """Host-owned delivery of an accepted run."""

    def __init__(
        self,
        project_root: Path,
        config,
        *,
        git_client: RealGitClient | None = None,
        gh_client: GhClient | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.config = config
        self.git = git_client or RealGitClient(project_root)
        self.gh = gh_client or GhClient(project_root)

    def deliver(self, run_id: str, owned_files: list[str]) -> dict:
        github = self.config.github
        warnings: list[str] = []

        if github.mode == "none":
            return {
                "mode": "none",
                "branch": None,
                "commit": None,
                "committed_files": [],
                "pushed": False,
                "pr": None,
                "checks": None,
                "checks_failed": False,
                "warnings": ["github.mode is 'none'; no delivery actions taken"],
            }

        if not github.auto_commit:
            warnings.append(
                "auto_commit is disabled; the operator commits the owned diff manually"
            )
            if github.auto_push or github.auto_create_pr:
                warnings.append(
                    "auto_push/auto_create_pr require auto_commit; remote actions skipped"
                )
            return {
                "mode": github.mode,
                "branch": None,
                "commit": None,
                "committed_files": [],
                "pushed": False,
                "pr": None,
                "checks": None,
                "checks_failed": False,
                "warnings": warnings,
            }

        if not self.git.is_repo():
            raise GitDeliveryError(
                f"{self.project_root} is not a git repository; "
                "delivery requires git (disable [github] for docs-only delivery)"
            )
        branch = f"{github.branch_prefix}{run_id}"
        created_new_branch = False

        if self.git.branch_exists(branch):
            self.git.checkout(branch)
        else:
            self.git.checkout_new_branch(branch)
            created_new_branch = True

        self.git.add(list(owned_files))
        staged = set(self.git.staged_files())
        unexpected = sorted(staged - set(owned_files))
        if unexpected:
            raise GitDeliveryError(
                f"refusing to commit files outside the owned diff: {', '.join(unexpected)}"
            )

        if not staged:
            if created_new_branch:
                raise GitDeliveryError(
                    "nothing to commit: the run owns no changed files"
                )
            commit = self.git.head()
            warnings.append("no new owned changes to commit; reused existing delivery commit")
        else:
            commit = self.git.commit(f"metacoding: {run_id}")

        summary: dict = {
            "branch": branch,
            "commit": commit,
            "committed_files": sorted(staged),
            "pushed": False,
            "mode": github.mode,
            "remote": github.remote,
            "pr": None,
            "checks": None,
            "checks_failed": False,
            "warnings": warnings,
        }

        if github.auto_push:
            try:
                self.git.push(github.remote, branch)
                summary["pushed"] = True
            except GitDeliveryError as exc:
                summary["pushed"] = False
                warnings.append(f"push failed: {exc}")

        wants_pr = github.auto_create_pr and github.mode == "pull-request"
        if wants_pr:
            try:
                summary["pr"] = self.gh.ensure_pr(
                    github.remote,
                    branch,
                    f"metacoding: {run_id}",
                    "Delivered by MetaCoding; see docs/metacoding/FINAL_REPORT.md",
                )
            except GitDeliveryError as exc:
                warnings.append(f"pull request creation failed: {exc}")

        if github.wait_for_checks and summary["pushed"]:
            try:
                checks = self.gh.wait_for_checks(
                    github.remote,
                    branch,
                    timeout_seconds=github.check_timeout_seconds,
                    poll_seconds=github.check_poll_seconds,
                )
                summary["checks"] = checks
                failed = [
                    check
                    for check in checks
                    if check.get("state") not in SUCCESS_CHECK_STATES
                ]
                summary["checks_failed"] = bool(failed)
            except GitDeliveryError as exc:
                warnings.append(f"check status unavailable: {exc}")

        return summary
