"""Deterministic host gates, failure fingerprints, and stop conditions.

Gates return structured results instead of raising so every decision is
recordable evidence. The host always applies these gates; harness output
can never bypass them.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Iterable, Mapping

from metacoding.models import PlannerPlan, TesterReport
from metacoding.project import GIT_META_PREFIX

BLOCKING_SEVERITIES = ("P0", "P1")

#: Paths the host always protects, regardless of what a planner reports.
HOST_PROTECTED_FILES = (
    ".metacoding/config.toml",
    ".metacoding/state.json",
    ".metacoding/active-run.lock",
)
HOST_PROTECTED_PREFIXES = (".git/",)

#: Default write scope a tester may touch during its own stage. The
#: orchestrator narrows this to the run's own directory.
DEFAULT_TESTER_ALLOWED_PREFIXES = (".metacoding/",)
TESTER_ALLOWED_FILES = ("docs/metacoding/TEST_REPORT.md",)


def is_host_protected(path: str) -> bool:
    """True when a path is protected by the host itself, not the planner."""
    return (
        path in HOST_PROTECTED_FILES
        or path.startswith(HOST_PROTECTED_PREFIXES)
        or path.startswith(GIT_META_PREFIX)
    )


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    reason: str = ""
    details: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "reason": self.reason,
            "details": list(self.details),
        }


def path_matches(path: str, pattern: str) -> bool:
    """fnmatch-style match where plain paths also match their subtree."""
    pattern = pattern.rstrip("/")
    if any(char in pattern for char in "*?["):
        return fnmatch(path, pattern)
    return path == pattern or path.startswith(pattern + "/")


def plan_gate(plan: PlannerPlan | None) -> GateResult:
    if plan is None or not plan.coding_tasks or not plan.acceptance_criteria:
        return GateResult(
            "plan", False, "no valid planner plan with tasks and acceptance criteria"
        )
    return GateResult("plan", True)


def scope_gate(changed_files: Iterable[str], policy) -> GateResult:
    violations = sorted(
        path
        for path in changed_files
        if is_host_protected(path)
        or not any(path_matches(path, pattern) for pattern in policy.allowed_paths)
    )
    if violations:
        return GateResult(
            "scope", False, "changes outside the planner's allowed paths", tuple(violations)
        )
    return GateResult("scope", True)


def protected_path_gate(changed_files: Iterable[str], policy) -> GateResult:
    violations = sorted(
        path
        for path in changed_files
        if is_host_protected(path)
        or any(path_matches(path, pattern) for pattern in policy.protected_paths)
    )
    if violations:
        return GateResult(
            "protected_paths", False, "protected paths were modified", tuple(violations)
        )
    return GateResult("protected_paths", True)


def severity_gate(report: TesterReport) -> GateResult:
    blocking = tuple(
        f"{finding.id} {finding.severity} {finding.title}"
        for finding in report.findings
        if finding.severity in BLOCKING_SEVERITIES
    )
    if blocking:
        return GateResult(
            "severity", False, "P0/P1 findings remain open", blocking
        )
    return GateResult("severity", True)


def _command_matches(report_command: str, required_command: str) -> bool:
    """True when a tester-reported command is an invocation of a required
    project test command (exact match or with extra arguments)."""
    report_command = report_command.strip()
    required_command = required_command.strip()
    return report_command == required_command or report_command.startswith(
        required_command + " "
    )


def deterministic_checks_gate(
    report: TesterReport,
    host_checks: list[dict] | None = None,
    required_commands: list[str] | None = None,
) -> GateResult:
    """Gate over host-executed deterministic checks.

    Only the host-detected *required* project test commands can fail this
    gate. Diagnostic commands the tester happened to run (``git diff
    --no-index``, ``grep``, ...) may legitimately exit non-zero as data and
    never fail the gate. A tester report claiming success for a required
    command the host saw fail is rejected as inconsistent evidence.
    """
    required = [command.strip() for command in (required_commands or [])]
    failures: list[str] = []

    host_by_command: dict[str, int] = {}
    for check in host_checks or []:
        command_text = str(check.get("command", "")).strip()
        exit_code = int(check.get("exit_code", 0))
        host_by_command[command_text] = exit_code
        if exit_code != 0:
            failures.append(f"host: {command_text} (exit {exit_code})")

    for command in report.test_commands:
        is_required = any(_command_matches(command.command, req) for req in required)
        if not is_required:
            continue  # diagnostic command: exit code is evidence, not a gate
        host_exit = next(
            (
                host_by_command[host_command]
                for host_command in host_by_command
                if _command_matches(command.command, host_command)
            ),
            None,
        )
        if command.exit_code != 0:
            failures.append(f"{command.command} (exit {command.exit_code})")
        elif host_exit is not None and host_exit != 0:
            failures.append(
                f"tester reported success for '{command.command}' but host "
                f"execution failed (exit {host_exit})"
            )

    if failures:
        return GateResult(
            "deterministic_checks", False, "required test commands failed", tuple(failures)
        )
    return GateResult("deterministic_checks", True)


def blocking_acceptance_gate(plan: PlannerPlan, report: TesterReport) -> GateResult:
    results = {item.id: item for item in report.acceptance_results}
    failed = tuple(
        criterion.id
        for criterion in plan.acceptance_criteria
        if criterion.priority == "blocking"
        and (criterion.id not in results or results[criterion.id].status != "pass")
    )
    if failed:
        return GateResult(
            "blocking_acceptance", False, "blocking acceptance criteria not satisfied", failed
        )
    return GateResult("blocking_acceptance", True)


def evidence_gate(plan: PlannerPlan, report: TesterReport) -> GateResult:
    results = {item.id: item for item in report.acceptance_results}
    missing = tuple(
        criterion.id
        for criterion in plan.acceptance_criteria
        if criterion.priority == "blocking" and criterion.id not in results
    )
    if missing:
        return GateResult(
            "evidence", False, "tester evidence missing for blocking criteria", missing
        )
    return GateResult("evidence", True)


#: Paths a Tester may legitimately touch during its own stage.
TESTER_ALLOWED_PREFIXES = (".metacoding/",)
TESTER_ALLOWED_FILES = ("docs/metacoding/TEST_REPORT.md",)


def contamination_gate(
    pre_state: Mapping[str, str] | set[str],
    post_state: Mapping[str, str] | set[str],
    *,
    tester_can_modify_source: bool,
    allowed_prefixes: tuple[str, ...] = DEFAULT_TESTER_ALLOWED_PREFIXES,
    allowed_files: tuple[str, ...] = TESTER_ALLOWED_FILES,
) -> GateResult:
    pre = dict.fromkeys(pre_state, "") if isinstance(pre_state, set) else dict(pre_state)
    post = dict.fromkeys(post_state, "") if isinstance(post_state, set) else dict(post_state)
    changed = sorted(
        path
        for path in set(pre) | set(post)
        if pre.get(path) != post.get(path)
    )
    violations = tuple(
        path
        for path in changed
        if path not in allowed_files and not path.startswith(allowed_prefixes)
    )
    if violations and not tester_can_modify_source:
        return GateResult(
            "tester_contamination", False, "tester modified project files", violations
        )
    return GateResult("tester_contamination", True)


def evaluate_acceptance(
    plan: PlannerPlan,
    report: TesterReport,
    changed_files: Iterable[str],
    host_checks: list[dict] | None = None,
    required_commands: list[str] | None = None,
) -> list[GateResult]:
    """All gates that must pass before a run may be delivered."""
    changed = list(changed_files)
    return [
        plan_gate(plan),
        evidence_gate(plan, report),
        blocking_acceptance_gate(plan, report),
        severity_gate(report),
        deterministic_checks_gate(report, host_checks, required_commands),
        scope_gate(changed, plan.change_policy),
        protected_path_gate(changed, plan.change_policy),
    ]


def write_scope_gate(
    changed: Iterable[str],
    *,
    allowed_files: set[str] = frozenset(),
    allowed_prefixes: tuple[str, ...] = (),
    allowed_patterns: tuple[str, ...] = (),
) -> GateResult:
    """Check that only permitted paths were written during a harness stage.

    ``allowed_files`` are exact paths (harness payload files),
    ``allowed_prefixes`` directory prefixes (run/transcript directories), and
    ``allowed_patterns`` planner-granted fnmatch patterns for product files.
    Host-protected paths are never allowed.
    """
    violations = []
    for path in sorted(set(changed)):
        if path in allowed_files:
            continue
        if any(path.startswith(prefix) for prefix in allowed_prefixes):
            continue
        if not is_host_protected(path) and any(
            path_matches(path, pattern) for pattern in allowed_patterns
        ):
            continue
        violations.append(path)
    if violations:
        return GateResult(
            "write_scope", False, "harness wrote outside its permitted scope", tuple(violations)
        )
    return GateResult("write_scope", True)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def failure_fingerprint(report: TesterReport) -> str:
    """Stable identity of a round's failure mode (empty when all is well)."""
    failing_acceptance = sorted(
        item.id for item in report.acceptance_results if item.status != "pass"
    )
    finding_keys = sorted(
        f"{finding.type}:{finding.severity}:{_normalize(finding.title)}"
        for finding in report.findings
    )
    failing_commands = sorted(
        command.command
        for command in report.test_commands
        if command.exit_code != 0
    )
    if not failing_acceptance and not finding_keys and not failing_commands:
        return ""
    payload = "||".join(
        [
            ",".join(failing_acceptance),
            ";".join(finding_keys),
            ";".join(failing_commands),
        ]
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def repeated_failure_reached(history: list[str], fingerprint: str, *, limit: int) -> bool:
    """True when the same fingerprint fills the last ``limit`` rounds."""
    if not fingerprint or limit <= 0 or len(history) < limit:
        return False
    return all(entry == fingerprint for entry in history[-limit:])
