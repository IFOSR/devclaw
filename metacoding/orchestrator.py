"""The deterministic host: explicit state machine for the three harnesses.

Transitions always persist state before the next harness starts. Harness
return values never skip states: coding requires a valid plan, testing
always follows coding, review always reads the current tester report,
and delivery requires every host gate to pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
import hashlib
import os
import shlex

from metacoding.config import ProjectConfig
from metacoding.errors import (
    GitDeliveryError,
    HarnessCommandMissing,
    HarnessNonZeroExit,
    HarnessTimeout,
    MalformedHarnessOutput,
    MetaCodingError,
    ProtocolError,
)
from metacoding.harnesses.base import Harness, HarnessContext
from metacoding.locking import acquire_lock
from metacoding.models import (
    FinalReport,
    PlannerPlan,
    RoundRecord,
    RunRecord,
    RunStatus,
    TesterReport,
    now_utc,
)
from metacoding.policies import (
    contamination_gate,
    evaluate_acceptance,
    failure_fingerprint,
    is_host_protected,
    path_matches,
    protected_path_gate,
    repeated_failure_reached,
    scope_gate,
    write_scope_gate,
)
from metacoding.persistence import RunStore, ResumePlan, atomic_write_json, resolve_resume
from metacoding.process_runner import ProcessRunner
from metacoding.project import (
    capture_snapshot,
    detect_test_commands,
    detect_workspace_changes,
    git_invariant,
    runtime_evidence_state,
    workspace_state,
)

EXIT_BY_STATUS = {
    RunStatus.DELIVERED: 0,
    RunStatus.BLOCKED: 1,
    RunStatus.HUMAN_REVIEW_REQUIRED: 1,
    RunStatus.CANCELLED: 1,
    RunStatus.FAILED_INFRASTRUCTURE: 2,
    RunStatus.INTERRUPTED: 130,
}

RETRYABLE_ERRORS = (MalformedHarnessOutput, ProtocolError, HarnessTimeout, HarnessNonZeroExit)


class InfrastructureFailure(MetaCodingError):
    """A harness could not be invoked successfully twice in a row."""


class StageViolation(MetaCodingError):
    """A harness violated its stage write or git invariants.

    Raised by the stage guards and converted into a blocked final state by
    :meth:`Orchestrator._execute`.
    """


@dataclass
class OrchestratorResult:
    run_id: str
    status: RunStatus
    final: FinalReport
    exit_code: int
    message: str = ""


@dataclass
class _RoundOutcome:
    round_record: RoundRecord
    stop: OrchestratorResult | None = None


class Orchestrator:
    """Runs the planning -> coding -> testing -> review loop for one project."""

    def __init__(
        self,
        project_root: Path,
        config: ProjectConfig,
        harnesses: dict[str, Harness],
        *,
        emit: Callable[[dict], None] | None = None,
        deliverer=None,
        store: RunStore | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.config = config
        self.harnesses = harnesses
        self.store = store or RunStore(self.project_root)
        self.emit = emit or (lambda event: None)
        self.deliverer = deliverer
        self._stage_attempts: dict[str, int] = {}

    # --- event helpers ---------------------------------------------------------

    def _phase(self, phase: str, message: str) -> None:
        self.emit({"kind": "phase", "phase": phase, "message": message})

    def _info(self, message: str) -> None:
        self.emit({"kind": "info", "message": message})

    # --- public entry points ---------------------------------------------------

    def start(self, requirement: str) -> OrchestratorResult:
        state = self.store.read_state()
        if state and state.get("active_run_id"):
            raise MetaCodingError(
                "an unfinished run is already active for this project; "
                "use `metacoding resume` to continue it or `metacoding cancel` "
                "to abandon it before starting a new run"
            )
        # Acquire the lock BEFORE creating any run record so a lock failure
        # never leaves an orphaned active-run pointer behind.
        handle = acquire_lock(self.project_root, f"pending-{os.getpid()}")
        try:
            baseline = capture_snapshot(self.project_root)
            record = self.store.create_run(requirement, self.config, baseline)
            handle.retarget(record.run_id)
            self.store.save_git_artifact(
                record.run_id,
                "baseline",
                {
                    "git_head": baseline.git_head,
                    "is_git_repo": baseline.is_git_repo,
                    "dirty_files": baseline.dirty_files,
                    "captured_at": baseline.captured_at,
                    "workspace_state": workspace_state(self.project_root),
                },
            )
        except BaseException:
            handle.release()
            raise
        try:
            return self._execute(record)
        finally:
            handle.release()

    def resume(self) -> OrchestratorResult:
        plan = resolve_resume(self.store)
        if plan.action == "nothing_to_resume":
            raise MetaCodingError("no active run to resume")
        if plan.action == "cannot_resume_terminal":
            raise MetaCodingError(f"run {plan.run_id} already finished and cannot be resumed")
        record = self.store.load_run(plan.run_id)
        self._info(f"resuming run {record.run_id} from state {record.status.value}")
        handle = acquire_lock(self.project_root, record.run_id)
        try:
            return self._execute(record)
        finally:
            handle.release()

    def cancel(self) -> OrchestratorResult:
        state = self.store.read_state()
        if not state or not state.get("active_run_id"):
            raise MetaCodingError("no active run to cancel")
        record = self.store.load_run(str(state["active_run_id"]))
        # A live lock holder means the run is executing somewhere else:
        # refuse to clean up state underneath a running harness.
        try:
            handle = acquire_lock(self.project_root, record.run_id)
        except MetaCodingError as exc:
            raise MetaCodingError(
                f"cannot cancel: {exc} Stop that process first, then cancel."
            ) from exc
        try:
            return self._finalize(
                record,
                RunStatus.CANCELLED,
                "cancelled by operator",
                "The run was cancelled; all evidence is preserved.",
            )
        finally:
            handle.release()

    # --- main loop ---------------------------------------------------------------

    def _execute(self, record: RunRecord) -> OrchestratorResult:
        try:
            return self._execute_inner(record)
        except KeyboardInterrupt:
            record.status = RunStatus.INTERRUPTED
            self.store.save_run(record, active_status=RunStatus.INTERRUPTED)
            self._info("interrupted; the run stays resumable via `metacoding resume`")
            final = self._build_final(
                record, "interrupted", "run interrupted by the operator", "", []
            )
            return OrchestratorResult(
                record.run_id,
                RunStatus.INTERRUPTED,
                final,
                EXIT_BY_STATUS[RunStatus.INTERRUPTED],
                "interrupted",
            )
        except InfrastructureFailure as exc:
            return self._finalize(
                record,
                RunStatus.FAILED_INFRASTRUCTURE,
                str(exc),
                "The harness infrastructure failed before the product could be judged.",
            )
        except StageViolation as exc:
            return self._finalize(
                record,
                RunStatus.BLOCKED,
                str(exc),
                "A harness violated the deterministic write or git invariants; "
                "all evidence is preserved.",
            )
        except GitDeliveryError as exc:
            # Delivery is host-owned; a git safety failure needs an operator.
            # Never leave the run dangling in the github_delivery state.
            return self._finalize(
                record,
                RunStatus.HUMAN_REVIEW_REQUIRED,
                f"git delivery failed: {exc}",
                "The implementation was accepted locally but delivery failed; "
                "resolve the git issue and start a new run or deliver manually.",
            )

    def _execute_inner(self, record: RunRecord) -> OrchestratorResult:
        plan = self._ensure_plan(record)

        while True:
            if record.status is RunStatus.INTERRUPTED:
                record.status = self._stage_after_interruption(record)
                self.store.save_run(record, active_status=record.status)

            if record.status in (RunStatus.ACCEPTED, RunStatus.GITHUB_DELIVERY):
                outcome = self._run_delivery_stage(record, plan)
                if outcome.stop is not None:
                    return outcome.stop
                continue

            if record.status is RunStatus.CODING:
                outcome = self._run_coding_stage(record, plan)
                if outcome.stop is not None:
                    return outcome.stop
                record.status = RunStatus.TESTING
                self.store.save_run(record, active_status=RunStatus.TESTING)

            if record.status is RunStatus.TESTING:
                outcome = self._run_testing_stage(record, plan)
                if outcome.stop is not None:
                    return outcome.stop
                record.status = RunStatus.PLANNER_REVIEW
                self.store.save_run(record, active_status=RunStatus.PLANNER_REVIEW)

            if record.status is RunStatus.PLANNER_REVIEW:
                outcome = self._run_review_stage(record, plan)
                if outcome.stop is not None:
                    return outcome.stop
                continue

            break  # pragma: no cover - loop always returns or continues

        raise MetaCodingError(f"run {record.run_id} reached an impossible state")  # pragma: no cover

    def _stage_after_interruption(self, record: RunRecord) -> RunStatus:
        """Re-derive the pending stage from persisted round artifacts."""
        if record.status in (RunStatus.ACCEPTED, RunStatus.GITHUB_DELIVERY):
            return RunStatus.GITHUB_DELIVERY
        if record.current_round <= 0:
            return RunStatus.PLANNING
        round_record = self.store.load_rounds(record.run_id).get(record.current_round)
        if round_record is None:
            return RunStatus.CODING
        if round_record.coding_result is None:
            return RunStatus.CODING
        if round_record.tester_report is None:
            return RunStatus.TESTING
        return RunStatus.PLANNER_REVIEW

    # --- stages -------------------------------------------------------------------

    def _guard_stage_writes(
        self,
        record: RunRecord,
        harness_label: str,
        pre_state: dict[str, str],
        pre_git: tuple[str | None, str | None],
        pre_evidence: dict[str, str],
        *,
        stage_payload_files: set[str],
        stage_prefixes: tuple[str, ...],
        allowed_patterns: tuple[str, ...],
    ) -> None:
        """Enforce per-stage write, git, and evidence invariants.

        Raises :class:`StageViolation` when the harness wrote outside its
        permitted scope, performed git operations, or modified runtime
        evidence (run.json, round records, plan, git artifacts) that only
        the host may write. Git history and the branch may only be changed
        by the host's delivery stage.
        """
        post_git = git_invariant(self.project_root)
        if post_git != pre_git:
            raise StageViolation(
                f"{harness_label} changed git state during its stage "
                f"(head/branch {pre_git} -> {post_git}); harnesses must not "
                f"commit, merge, or switch branches"
            )
        post_state = workspace_state(self.project_root)
        raw_changes = detect_workspace_changes(
            pre_state, post_state, ignore_prefixes=()
        )
        gate = write_scope_gate(
            raw_changes,
            allowed_files=set(stage_payload_files),
            allowed_prefixes=stage_prefixes,
            allowed_patterns=allowed_patterns,
        )
        if not gate.passed:
            raise StageViolation(
                f"{harness_label} wrote outside its permitted scope: "
                f"{', '.join(gate.details)}"
            )
        # Runtime evidence (run.json, rounds, plan, git/, final.json,
        # state.json, lock) is invisible to git status and the inventory;
        # verify it with an independent hash snapshot.
        evidence_changed = detect_workspace_changes(
            pre_evidence,
            runtime_evidence_state(self.project_root, record.run_id),
            ignore_prefixes=(),
        )
        transcripts_prefix = f".metacoding/runs/{record.run_id}/transcripts/"
        tampered = sorted(
            path
            for path in evidence_changed
            if path not in stage_payload_files
            and not path.startswith(transcripts_prefix)
        )
        if tampered:
            raise StageViolation(
                f"{harness_label} modified runtime evidence: {', '.join(tampered)}"
            )

    def _ensure_plan(self, record: RunRecord, force: bool = False) -> PlannerPlan:
        existing = self.store.load_plan(record.run_id)
        if existing is not None and not force and record.status is not RunStatus.PLANNING:
            return existing
        if existing is not None and record.status is not RunStatus.PLANNING:
            return existing
        self._phase("planning", "Planner is analyzing the project and requirement.")
        report_dir = self.store.run_dir(record.run_id)
        pre_state = workspace_state(self.project_root)
        pre_git = git_invariant(self.project_root)
        pre_evidence = runtime_evidence_state(self.project_root, record.run_id)
        plan = self._invoke(
            "planner",
            "plan",
            record,
            lambda ctx: self.harnesses["planner"].plan(ctx),
            report_dir=report_dir,
        )
        self._guard_stage_writes(
            record,
            "planner",
            pre_state,
            pre_git,
            pre_evidence,
            stage_payload_files={
                f".metacoding/runs/{record.run_id}/plan-payload.json",
                f".metacoding/runs/{record.run_id}/plan-payload.last-message",
            },
            stage_prefixes=(f".metacoding/runs/{record.run_id}/transcripts/",),
            allowed_patterns=(),
        )
        self.store.save_plan(record.run_id, plan)
        self._render_contract_docs(record.run_id, record.requirement, plan)
        record.status = RunStatus.CODING
        record.current_round = 0
        self.store.save_run(record, active_status=RunStatus.CODING)
        return plan

    def _round_tasks(self, record: RunRecord, plan: PlannerPlan, round_number: int) -> list[dict]:
        rounds = self.store.load_rounds(record.run_id)
        if round_number in rounds and rounds[round_number].tasks:
            return rounds[round_number].tasks
        if record.pending_tasks:
            return [dict(task) for task in record.pending_tasks]
        if round_number == 1:
            return [task.to_dict() for task in plan.coding_tasks]
        previous = rounds.get(round_number - 1)
        if previous is not None and previous.planner_decision is not None:
            return [task.to_dict() for task in previous.planner_decision.rework_tasks]
        return [task.to_dict() for task in plan.coding_tasks]

    def _run_coding_stage(self, record: RunRecord, plan: PlannerPlan) -> _RoundOutcome:
        round_number = record.current_round + 1
        max_rounds = self.config.limits.max_rounds
        if round_number > max_rounds:
            stop = self._finalize(
                record,
                RunStatus.BLOCKED,
                f"max rounds ({max_rounds}) reached without acceptance",
                "The rework loop reached the configured round limit.",
            )
            return _RoundOutcome(None, stop)

        tasks = self._round_tasks(record, plan, round_number)
        round_record = self.store.start_round(record.run_id, round_number, tasks)
        record.pending_tasks = []
        record.current_round = round_number
        record.status = RunStatus.CODING
        self.store.save_run(record, active_status=RunStatus.CODING)
        self._phase("coding", f"Pi is implementing round {round_number}.")

        round_dir = self.store.round_dir(record.run_id, round_number)
        pre_state = workspace_state(self.project_root)
        pre_git = git_invariant(self.project_root)
        pre_evidence = runtime_evidence_state(self.project_root, record.run_id)
        coding = self._invoke(
            "coder",
            "code",
            record,
            lambda ctx: self.harnesses["coder"].code(ctx),
            report_dir=round_dir,
            extra={"plan": plan, "rework_tasks": tasks if round_number > 1 else []},
        )
        # Per-stage write guard: the coder may only touch its payload files,
        # transcripts, and planner-allowed product paths (never host
        # protected paths such as .metacoding/config.toml).
        self._guard_stage_writes(
            record,
            "coder",
            pre_state,
            pre_git,
            pre_evidence,
            stage_payload_files={
                f".metacoding/runs/{record.run_id}/rounds/round-{round_number:03d}/code-payload.json",
                f".metacoding/runs/{record.run_id}/rounds/round-{round_number:03d}/code-payload.last-message",
            },
            stage_prefixes=(f".metacoding/runs/{record.run_id}/transcripts/",),
            allowed_patterns=tuple(plan.change_policy.allowed_paths),
        )
        post_state = workspace_state(self.project_root)
        changed = sorted(detect_workspace_changes(pre_state, post_state))
        # Ground truth first, but the coder's self-reported paths also feed the
        # scope/protected gates: a run must never deliver an unreviewed path.
        policy_files = sorted(set(changed) | set(coding.changed_files))
        round_record.coding_result = coding
        round_record.changed_files = policy_files
        self.store.save_round(record.run_id, round_record)
        self.store.save_git_artifact(
            record.run_id,
            "changes",
            {
                "round": round_number,
                "changed_files": policy_files,
                "detected": changed,
                "reported_by_coder": list(coding.changed_files),
            },
        )

        protected = protected_path_gate(policy_files, plan.change_policy)
        if not protected.passed:
            stop = self._finalize(
                record,
                RunStatus.BLOCKED,
                f"protected paths were modified: {', '.join(protected.details)}",
                "The coder touched paths the planner declared protected.",
                warnings=[protected.reason],
            )
            return _RoundOutcome(round_record, stop)

        scope = scope_gate(policy_files, plan.change_policy)
        if not scope.passed:
            scope_violation_note = f"scope violation: {', '.join(scope.details)}"
            round_record.notes.append(scope_violation_note)
            self.store.save_round(record.run_id, round_record)
            record.failure_history.append(fingerprint_scope_violation(scope.details))
            limit = self.config.limits.same_failure_limit
            if repeated_failure_reached(record.failure_history, record.failure_history[-1], limit=limit):
                stop = self._finalize(
                    record,
                    RunStatus.BLOCKED,
                    f"changes repeatedly expanded outside the allowed scope: {', '.join(scope.details)}",
                    "Out-of-scope modifications persisted across rounds.",
                    warnings=[scope.reason],
                )
                return _RoundOutcome(round_record, stop)
        else:
            # A clean round resets the scope-violation streak.
            record.failure_history = [
                entry for entry in record.failure_history
                if not entry.startswith("scope:")
            ]
        self.store.save_run(record, active_status=RunStatus.TESTING)
        return _RoundOutcome(round_record)

    def _run_testing_stage(self, record: RunRecord, plan: PlannerPlan) -> _RoundOutcome:
        round_number = record.current_round
        round_record = self.store.load_rounds(record.run_id).get(round_number)
        if round_record is None:  # pragma: no cover - coding always creates it
            raise MetaCodingError(f"round {round_number} record missing before testing")
        self._phase("testing", "Tester is running review and acceptance checks.")
        round_dir = self.store.round_dir(record.run_id, round_number)
        pre_state = workspace_state(self.project_root)
        pre_git = git_invariant(self.project_root)
        pre_evidence = runtime_evidence_state(self.project_root, record.run_id)
        report = self._invoke(
            "tester",
            "test",
            record,
            lambda ctx: self.harnesses["tester"].test(ctx),
            report_dir=round_dir,
            extra={
                "plan": plan,
                "changed_files": round_record.changed_files,
                "test_commands": detect_test_commands(self.project_root),
            },
        )
        post_state = workspace_state(self.project_root)
        post_git = git_invariant(self.project_root)
        if post_git != pre_git:
            raise StageViolation(
                f"tester changed git state during its stage "
                f"(head/branch {pre_git} -> {post_git}); harnesses must not "
                f"commit, merge, or switch branches"
            )
        # Runtime evidence check: the tester may only add its own payload
        # files and transcripts; touching run.json, the plan, coding reports,
        # decisions, earlier rounds, or git/ artifacts is tampering.
        tester_payload_files = {
            f".metacoding/runs/{record.run_id}/rounds/round-{round_number:03d}/test-payload.json",
            f".metacoding/runs/{record.run_id}/rounds/round-{round_number:03d}/test-payload.last-message",
        }
        self._guard_stage_writes(
            record,
            "tester",
            pre_state,
            pre_git,
            pre_evidence,
            stage_payload_files=set(tester_payload_files),
            stage_prefixes=(f".metacoding/runs/{record.run_id}/transcripts/",),
            allowed_patterns=(),
        )
        round_record.tester_report = report
        self.store.save_round(record.run_id, round_record)
        self._render_test_report(record.run_id, report, round_number)

        # Workspace check: the tester may only write its own payload files,
        # the transcripts, and TEST_REPORT.md — never product source.
        contamination = contamination_gate(
            pre_state,
            post_state,
            tester_can_modify_source=self.config.policy.tester_can_modify_source,
            allowed_prefixes=(f".metacoding/runs/{record.run_id}/transcripts/",),
            allowed_files=tuple(tester_payload_files) + ("docs/metacoding/TEST_REPORT.md",),
        )
        if not contamination.passed:
            stop = self._finalize(
                record,
                RunStatus.BLOCKED,
                f"tester contaminated the workspace: {', '.join(contamination.details)}",
                "The tester must not modify product source; the run is blocked with evidence.",
                warnings=[contamination.reason],
            )
            return _RoundOutcome(round_record, stop)

        # The host executes the detected project test commands itself:
        # deterministic gates must not trust tester self-reported results.
        round_record.host_checks = self._run_host_checks(record, round_number)
        self.store.save_round(record.run_id, round_record)
        atomic_write_json(
            self.store.round_dir(record.run_id, round_number) / "host-checks.json",
            {"round": round_number, "checks": round_record.host_checks},
        )

        fingerprint = failure_fingerprint(report)
        if fingerprint:
            record.failure_history.append(fingerprint)
            self.store.save_run(record, active_status=RunStatus.PLANNER_REVIEW)
        return _RoundOutcome(round_record)

    def _run_host_checks(self, record: RunRecord, round_number: int) -> list[dict]:
        """Execute the project's test commands host-side.

        Commands are re-detected every round so tests added by the coder in
        this or earlier rounds are executed, not only the ones that existed
        when the run started.
        """
        commands = detect_test_commands(self.project_root)
        results: list[dict] = []
        runner = ProcessRunner()
        for command_text in commands:
            command = shlex.split(command_text)
            try:
                result = runner.run(
                    command,
                    cwd=self.project_root,
                    idle_timeout_seconds=self.config.limits.idle_timeout_seconds,
                    max_execution_seconds=self.config.limits.max_execution_seconds,
                )
            except HarnessCommandMissing as exc:
                results.append(
                    {"command": command_text, "exit_code": 127, "error": str(exc)}
                )
                continue
            self.store.save_transcript(
                record.run_id,
                harness=f"host-checks-round-{round_number:03d}",
                attempt=len(results) + 1,
                metadata=result.metadata(),
                stdout=result.stdout,
                stderr=result.stderr,
            )
            results.append(
                {
                    "command": command_text,
                    "exit_code": result.exit_code,
                    "timed_out": result.timed_out,
                }
            )
        if results:
            failed = [item for item in results if item["exit_code"] != 0]
            self._info(
                f"host checks: {len(results) - len(failed)} passed, "
                f"{len(failed)} failed"
            )
        return results

    def _run_review_stage(self, record: RunRecord, plan: PlannerPlan) -> _RoundOutcome:
        round_number = record.current_round
        round_record = self.store.load_rounds(record.run_id).get(round_number)
        if round_record is None or round_record.tester_report is None:  # pragma: no cover
            raise MetaCodingError(f"round {round_number} has no tester report to review")
        self._phase("planner_review", f"Planner is reviewing round {round_number} evidence.")
        round_dir = self.store.round_dir(record.run_id, round_number)
        pre_state = workspace_state(self.project_root)
        pre_git = git_invariant(self.project_root)
        pre_evidence = runtime_evidence_state(self.project_root, record.run_id)
        decision = self._invoke(
            "planner",
            "review",
            record,
            lambda ctx: self.harnesses["planner"].review(ctx),
            report_dir=round_dir,
            extra={
                "plan": plan,
                "tester_report": round_record.tester_report,
                "changed_files": round_record.changed_files,
                "host_checks": round_record.host_checks,
            },
        )
        self._guard_stage_writes(
            record,
            "planner review",
            pre_state,
            pre_git,
            pre_evidence,
            stage_payload_files={
                f".metacoding/runs/{record.run_id}/rounds/round-{round_number:03d}/review-payload.json",
                f".metacoding/runs/{record.run_id}/rounds/round-{round_number:03d}/review-payload.last-message",
            },
            stage_prefixes=(f".metacoding/runs/{record.run_id}/transcripts/",),
            allowed_patterns=(),
        )
        round_record.planner_decision = decision
        self.store.save_round(record.run_id, round_record)

        if decision.decision == "blocked":
            stop = self._finalize(
                record,
                RunStatus.BLOCKED,
                decision.reason,
                "The planner declared the requirement blocked.",
            )
            return _RoundOutcome(round_record, stop)

        if decision.decision == "human_review_required":
            stop = self._finalize(
                record,
                RunStatus.HUMAN_REVIEW_REQUIRED,
                decision.reason,
                "The planner requested human review before continuing.",
            )
            return _RoundOutcome(round_record, stop)

        history = record.failure_history
        if history and repeated_failure_reached(
            history, history[-1], limit=self.config.limits.same_failure_limit
        ):
            stop = self._finalize(
                record,
                RunStatus.BLOCKED,
                f"the same failure fingerprint remained unresolved for "
                f"{self.config.limits.same_failure_limit} consecutive rounds "
                f"({history[-1]})",
                "The rework loop stopped making progress.",
            )
            return _RoundOutcome(round_record, stop)

        if decision.decision == "accept":
            gates = evaluate_acceptance(
                plan,
                round_record.tester_report,
                round_record.changed_files,
                host_checks=round_record.host_checks,
                required_commands=[
                    check["command"] for check in round_record.host_checks
                ],
            )
            failed = [gate for gate in gates if not gate.passed]
            if not failed:
                delivered = self._deliver(record, plan, round_record, decision.reason)
                if isinstance(delivered, OrchestratorResult):
                    return _RoundOutcome(round_record, delivered)
                return delivered  # CI rework: continue the loop on the same round
            reasons = "; ".join(
                f"{gate.name}: {gate.reason} ({', '.join(gate.details)})" for gate in failed
            )
            override_note = f"planner acceptance overridden by host gates: {reasons}"
            self._info(override_note)
            round_record.notes.append(override_note)
            self.store.save_round(record.run_id, round_record)
            record.pending_tasks = [
                {
                    "id": f"GATE-{index + 1}",
                    "description": f"{gate.name}: {gate.reason} ({', '.join(gate.details)})",
                    "target_area": list(gate.details),
                    "verification": f"make host gate '{gate.name}' pass",
                }
                for index, gate in enumerate(failed)
            ]
            record.status = RunStatus.CODING
            self.store.save_run(record, active_status=RunStatus.CODING)
            return _RoundOutcome(round_record)

        # rework
        if record.current_round + 1 > self.config.limits.max_rounds:
            stop = self._finalize(
                record,
                RunStatus.BLOCKED,
                f"max rounds ({self.config.limits.max_rounds}) reached without acceptance",
                "The planner requested rework but the round limit is exhausted.",
            )
            return _RoundOutcome(round_record, stop)
        self._info(
            f"planner requested rework for "
            f"{len(decision.blocking_findings)} blocking finding(s); "
            f"{len(decision.rework_tasks)} rework task(s) issued."
        )
        record.pending_tasks = [task.to_dict() for task in decision.rework_tasks]
        record.status = RunStatus.CODING
        self.store.save_run(record, active_status=RunStatus.CODING)
        return _RoundOutcome(round_record)

    # --- delivery -----------------------------------------------------------------

    def _run_delivery_stage(self, record: RunRecord, plan: PlannerPlan) -> _RoundOutcome:
        """Resume path: delivery was interrupted after local acceptance."""
        round_number = max(record.current_round, 1)
        round_record = self.store.load_rounds(record.run_id).get(round_number)
        if round_record is None or round_record.tester_report is None:
            raise MetaCodingError(
                f"run {record.run_id} is in state {record.status.value} but round "
                f"{round_number} has no accepted evidence; cancel and restart"
            )
        gates = evaluate_acceptance(
            plan,
            round_record.tester_report,
            round_record.changed_files,
            host_checks=round_record.host_checks,
            required_commands=[check["command"] for check in round_record.host_checks],
        )
        failed = [gate for gate in gates if not gate.passed]
        if failed:
            record.status = RunStatus.CODING
            self.store.save_run(record, active_status=RunStatus.CODING)
            return _RoundOutcome(round_record)
        reason = (
            round_record.planner_decision.reason
            if round_record.planner_decision is not None
            else "resumed delivery"
        )
        delivered = self._deliver(record, plan, round_record, reason)
        if isinstance(delivered, OrchestratorResult):
            return _RoundOutcome(round_record, delivered)
        return delivered

    def _owned_delivery_files(self, record: RunRecord, plan: PlannerPlan) -> tuple[list[str], list[str]]:
        return compute_owned_delivery_files(self.project_root, self.store, record, plan)

    def _record_contract_hashes(self, run_id: str, updates: dict[str, str]) -> None:
        artifact = self.store.load_git_artifact(run_id, "contract-hashes") or {}
        artifact.update(updates)
        self.store.save_git_artifact(run_id, "contract-hashes", artifact)

    def _deliver(
        self, record: RunRecord, plan: PlannerPlan, round_record: RoundRecord, reason: str
    ) -> OrchestratorResult:
        record.status = RunStatus.ACCEPTED
        self.store.save_run(record, active_status=RunStatus.ACCEPTED)
        # Render FINAL_REPORT.md (github section pending) BEFORE computing the
        # owned diff so the delivery branch commit includes the final report
        # the PR body points at.
        preliminary = self._build_final(
            record,
            RunStatus.DELIVERED.value,
            reason or "planner accepted the implementation",
            f"All gates passed after {record.current_round} round(s).",
            [],
            github=None,
        )
        self._render_final_report(preliminary)
        owned, ownership_warnings = compute_owned_delivery_files(
            self.project_root, self.store, record, plan
        )
        for warning in ownership_warnings:
            self._info(f"delivery: {warning}")
        github_result = None
        if self.config.github.enabled:
            if self.deliverer is None:
                self._info("github delivery is enabled but no deliverer is configured")
            elif not owned:
                github_result = {
                    "skipped": True,
                    "reason": "no deliverable owned files",
                    "warnings": list(ownership_warnings),
                }
                self.store.save_git_artifact(record.run_id, "delivery", github_result)
            else:
                self._phase("github_delivery", "Delivering accepted work to git/GitHub.")
                record.status = RunStatus.GITHUB_DELIVERY
                self.store.save_run(record, active_status=RunStatus.GITHUB_DELIVERY)
                github_result = dict(self.deliverer.deliver(record.run_id, owned) or {})
                github_result.setdefault("warnings", []).extend(ownership_warnings)
                self.store.save_git_artifact(record.run_id, "delivery", github_result)
                if (
                    github_result.get("checks_failed")
                    and self.config.github.wait_for_checks
                ):
                    if not any(note.startswith("ci-rework") for note in round_record.notes):
                        # Required remote checks failed: return to tester
                        # evidence and planner review exactly once.
                        round_record.notes.append(
                            "ci-rework: remote required checks failed; "
                            "rerunning tester evidence and planner review"
                        )
                        self.store.save_round(record.run_id, round_record)
                        record.status = RunStatus.TESTING
                        self.store.save_run(record, active_status=RunStatus.TESTING)
                        self._info(
                            "remote required checks failed; returning to tester "
                            "evidence and planner review"
                        )
                        return _RoundOutcome(round_record)
                    # The rework loop already ran once: an operator decides.
                    return self._finalize(
                        record,
                        RunStatus.HUMAN_REVIEW_REQUIRED,
                        "remote required checks failed again after rework; "
                        "the local implementation stays accepted but needs an "
                        "operator decision on delivery",
                        "Remote CI failed twice; nothing was invalidated locally.",
                        warnings=["ci checks failed after the CI rework round"],
                        github=github_result,
                    )
        warnings: list[str] = list(ownership_warnings)
        if round_record.coding_result is not None:
            warnings.extend(
                f"known limitation: {item}"
                for item in round_record.coding_result.known_limitations
            )
        final = self._build_final(
            record,
            RunStatus.DELIVERED.value,
            reason or "planner accepted the implementation",
            f"All gates passed after {record.current_round} round(s).",
            warnings,
            github_result,
        )
        final.warnings.extend(
            note for note in self._collect_round_notes() if note not in final.warnings
        )
        # Commit the COMPLETE final report to the delivery branch before the
        # run is finalized, so a failure here is recorded in final.json and
        # the rendered report instead of being lost after "delivered".
        self._commit_final_report_to_branch(record, github_result, final)
        return self._finish(record, RunStatus.DELIVERED, final)

    def _commit_final_report_to_branch(
        self, record: RunRecord, github_result: dict | None, final: FinalReport
    ) -> None:
        """Render the complete FINAL_REPORT.md and commit it to the branch.

        The first delivery commit carries the placeholder version; this adds
        the complete report (with the real github section) as a follow-up
        commit so the PR body link always resolves. Outcome is recorded in
        the delivery artifact and as a final-report warning on failure.
        """
        if not github_result or not github_result.get("commit") or self.deliverer is None:
            return
        self._render_final_report(final)
        outcome = {"committed": False, "commit": None}
        try:
            update = self.deliverer.deliver(
                record.run_id, ["docs/metacoding/FINAL_REPORT.md"]
            ) or {}
            outcome = {
                "committed": bool(update.get("commit")),
                "commit": update.get("commit"),
            }
        except MetaCodingError as exc:
            outcome = {"committed": False, "commit": None, "error": str(exc)}
        if not outcome["committed"]:
            warning = (
                "final report could not be committed to the delivery branch; "
                f"the branch may hold the placeholder version ({outcome.get('error', 'no new commit')})"
            )
            final.warnings.append(warning)
            github_result["final_report"] = outcome
        else:
            github_result["final_report"] = outcome
        artifact = self.store.load_git_artifact(record.run_id, "delivery") or {}
        artifact["final_report"] = outcome
        self.store.save_git_artifact(record.run_id, "delivery", artifact)
        # final.json is written by _finish after this call, so the outcome
        # above is reflected in both the artifact and the report.

    # --- harness invocation with retry ----------------------------------------------

    def _invoke(
        self,
        harness_name: str,
        stage: str,
        record: RunRecord,
        invoke: Callable[[HarnessContext], object],
        *,
        report_dir: Path,
        extra: dict | None = None,
    ):
        harness = self.harnesses[harness_name]
        last_error: Exception | None = None
        for _ in range(2):  # one automatic retry for malformed output / transient failures
            self._stage_attempts[stage] = self._stage_attempts.get(stage, 0) + 1
            attempt = self._stage_attempts[stage]
            context_fields = dict(extra or {})
            context_fields.setdefault("policy", self.config.policy)
            context_fields.setdefault(
                "max_execution_seconds", self.config.limits.max_execution_seconds
            )
            context = HarnessContext(
                requirement=record.requirement,
                run_id=record.run_id,
                round_number=record.current_round,
                attempt=attempt,
                idle_timeout_seconds=self.config.limits.idle_timeout_seconds,
                project_root=self.project_root,
                docs_dir=self.store.docs_dir(),
                report_dir=report_dir,
                transcript_sink=self._make_transcript_sink(harness, stage, record.run_id, attempt),
                **context_fields,
            )
            try:
                return invoke(context)
            except RETRYABLE_ERRORS as exc:
                last_error = exc
                self._info(f"{stage} attempt {attempt} failed: {exc}; retrying once")
            except HarnessCommandMissing as exc:
                raise InfrastructureFailure(
                    f"harness command unavailable: {exc}"
                ) from exc
        raise InfrastructureFailure(f"{stage} failed after retry: {last_error}")

    def _make_transcript_sink(self, harness: Harness, stage: str, run_id: str, attempt: int):
        def sink(stage_name: str, result) -> None:
            self.store.save_transcript(
                run_id,
                harness=f"{harness.provider}-{harness.name}-{stage_name}",
                attempt=attempt,
                metadata=result.metadata(),
                stdout=result.stdout,
                stderr=result.stderr,
            )

        return sink

    # --- finalization ----------------------------------------------------------------

    def _build_final(
        self,
        record: RunRecord,
        outcome: str,
        reason: str,
        summary: str,
        warnings: list[str],
        github: dict | None = None,
    ) -> FinalReport:
        run_dir = self.store.run_dir(record.run_id)
        docs = self.store.docs_dir()
        return FinalReport(
            run_id=record.run_id,
            outcome=outcome,
            reason=reason,
            summary=summary,
            rounds_used=record.current_round,
            artifacts={
                "request": f".metacoding/runs/{record.run_id}/request.md",
                "plan": f".metacoding/runs/{record.run_id}/initial-plan.json",
                "final": f".metacoding/runs/{record.run_id}/final.json",
                "prd": "docs/metacoding/PRD.md",
                "test_report": "docs/metacoding/TEST_REPORT.md",
                "final_report": "docs/metacoding/FINAL_REPORT.md",
            },
            known_limitations=[],
            warnings=warnings,
            github=github,
            created_at=now_utc(),
        )

    def _collect_round_notes(self) -> list[str]:
        """Host warnings recorded in round records become final-report warnings."""
        state = self.store.read_state()
        run_id = state.get("active_run_id") if state else None
        if not run_id:
            return []
        notes: list[str] = []
        for round_record in sorted(self.store.load_rounds(str(run_id)).values(), key=lambda r: r.number):
            notes.extend(round_record.notes)
        return notes

    def _finalize(
        self,
        record: RunRecord,
        status: RunStatus,
        reason: str,
        summary: str,
        *,
        warnings: list[str] | None = None,
        github: dict | None = None,
    ) -> OrchestratorResult:
        final = self._build_final(
            record, status.value, reason, summary, list(warnings or []), github
        )
        final.warnings.extend(
            note for note in self._collect_round_notes() if note not in final.warnings
        )
        return self._finish(record, status, final)

    def _finish(self, record: RunRecord, status: RunStatus, final: FinalReport) -> OrchestratorResult:
        """Persist the final report, terminal status, and done event."""
        self.store.save_final(record.run_id, final)
        self._render_final_report(final)
        record.status = status
        self.store.save_run(record)
        self.store.clear_active_run()
        self._phase("done", f"Run finished as {status.value}: {final.reason}")
        return OrchestratorResult(
            record.run_id, status, final, EXIT_BY_STATUS.get(status, 1), final.reason
        )

    # --- human-readable documents -------------------------------------------------------

    def _render_contract_docs(self, run_id: str, requirement: str, plan: PlannerPlan) -> None:
        criteria = "\n".join(
            f"- **{c.id}** ({c.priority}): {c.description} — verify by: {c.verification_method}"
            for c in plan.acceptance_criteria
        )
        self.store.write_doc(
            "PRD.md",
            f"# PRD\n\n## Goal\n\n{plan.goal}\n\n## Requirement\n\n{requirement}\n\n"
            f"## Scope\n\n" + ("\n".join(f"- {item}" for item in plan.scope) or "- (none)")
            + "\n\n## Non-goals\n\n"
            + ("\n".join(f"- {item}" for item in plan.non_goals) or "- (none)")
            + f"\n\n## Acceptance criteria\n\n{criteria}\n",
        )
        self.store.write_doc(
            "ARCHITECTURE.md",
            f"# Architecture\n\n## Approach\n\n{plan.architecture.approach}\n\n"
            "## Modules\n\n"
            + ("\n".join(f"- {item}" for item in plan.architecture.modules) or "- (none)")
            + "\n\n## Data flow\n\n"
            + ("\n".join(f"- {item}" for item in plan.architecture.data_flow) or "- (none)")
            + "\n\n## Risks\n\n"
            + ("\n".join(f"- {item}" for item in plan.architecture.risks) or "- (none)")
            + "\n",
        )
        tasks = "\n".join(
            f"- **{t.id}**: {t.description}\n  - Expected files: {', '.join(t.expected_files) or 'n/a'}\n"
            f"  - Required tests: {', '.join(t.required_tests) or 'n/a'}\n  - Done when: {t.done_when}"
            for t in plan.coding_tasks
        )
        self.store.write_doc(
            "IMPLEMENTATION_PLAN.md",
            f"# Implementation Plan\n\n## Change policy\n\n"
            f"- Allowed paths: {', '.join(plan.change_policy.allowed_paths)}\n"
            f"- Protected paths: {', '.join(plan.change_policy.protected_paths) or 'none'}\n"
            f"- Forbidden actions: {', '.join(plan.change_policy.forbidden_actions) or 'none'}\n\n"
            f"## Tasks\n\n{tasks}\n",
        )
        self.store.write_doc("ACCEPTANCE.md", f"# Acceptance Criteria\n\n{criteria}\n")
        docs_relative = "docs/metacoding"
        self._record_contract_hashes(
            run_id,
            {
                f"{docs_relative}/{name}": _file_digest(
                    self.project_root / docs_relative / name
                )
                for name in (
                    "PRD.md",
                    "ARCHITECTURE.md",
                    "IMPLEMENTATION_PLAN.md",
                    "ACCEPTANCE.md",
                )
            },
        )

    def _render_test_report(self, run_id: str, report: TesterReport, round_number: int) -> None:
        commands = "\n".join(
            f"- `{command.command}` -> exit {command.exit_code}: {command.summary}"
            for command in report.test_commands
        ) or "- (no commands recorded)"
        results = "\n".join(
            f"- {item.id}: **{item.status}** (impact {item.impact}) — "
            f"{', '.join(item.evidence) or 'no evidence'}"
            for item in report.acceptance_results
        ) or "- (none)"
        findings = "\n".join(
            f"- **{finding.id}** [{finding.severity}] {finding.title}: {finding.impact}\n"
            f"  - Evidence: {'; '.join(finding.evidence)}\n  - Fix: {finding.recommended_fix}"
            for finding in report.findings
        ) or "- (none)"
        self.store.write_doc(
            "TEST_REPORT.md",
            f"# Test Report\n\nRound {round_number} — overall status: **{report.status}**\n\n"
            f"## Test commands\n\n{commands}\n\n## Acceptance results\n\n{results}\n\n"
            f"## Findings\n\n{findings}\n\n## PRD drift\n\n"
            + ("\n".join(f"- {item}" for item in report.prd_drift) or "- (none)")
            + "\n\n## Regression risks\n\n"
            + ("\n".join(f"- {item}" for item in report.regression_risks) or "- (none)")
            + "\n\n## Missing tests\n\n"
            + ("\n".join(f"- {item}" for item in report.missing_tests) or "- (none)")
            + "\n",
        )
        self._record_contract_hashes(
            run_id,
            {
                "docs/metacoding/TEST_REPORT.md": _file_digest(
                    self.project_root / "docs" / "metacoding" / "TEST_REPORT.md"
                )
            },
        )

    def _render_final_report(self, final: FinalReport) -> None:
        artifacts = "\n".join(f"- {name}: `{path}`" for name, path in final.artifacts.items())
        warnings = "\n".join(f"- {item}" for item in final.warnings) or "- (none)"
        github = (
            "\n".join(f"- {key}: {value}" for key, value in (final.github or {}).items())
            or "- (not configured)"
        )
        self.store.write_doc(
            "FINAL_REPORT.md",
            f"# Final Report\n\nRun `{final.run_id}` finished as **{final.outcome}**.\n\n"
            f"## Reason\n\n{final.reason}\n\n## Summary\n\n{final.summary}\n\n"
            f"## Rounds used\n\n{final.rounds_used}\n\n## Artifacts\n\n{artifacts}\n\n"
            f"## Warnings\n\n{warnings}\n\n## GitHub\n\n{github}\n",
        )


def compute_owned_delivery_files(
    project_root: Path, store: RunStore, record: RunRecord, plan: PlannerPlan
) -> tuple[list[str], list[str]]:
    """Compute the run's deliverable files against the persisted baseline.

    Returns ``(deliverable, warnings)``. Files that were already dirty before
    the run and were edited again cannot be separated from the user's own
    edits, so they are never staged automatically. Files outside the
    planner's allowed scope are excluded as well. Planner-protected contract
    documents are only deliverable when their content still matches what the
    host rendered (no harness tampering).
    """
    baseline_artifact = store.load_git_artifact(record.run_id, "baseline") or {}
    baseline_state = baseline_artifact.get("workspace_state") or {}
    current_state = workspace_state(project_root)
    changed = detect_workspace_changes(baseline_state, current_state)
    contract_hashes = store.load_git_artifact(record.run_id, "contract-hashes") or {}
    baseline_dirty = set(record.baseline.dirty_files)
    mixed = sorted(path for path in changed if path in baseline_dirty)

    def content_matches_host_render(path: str) -> bool:
        return (
            path in contract_hashes
            and current_state.get(path) == contract_hashes.get(path)
        )

    def deliverable(path: str) -> bool:
        if is_host_protected(path):
            return False
        if any(path_matches(path, pattern) for pattern in plan.change_policy.allowed_paths):
            return True
        # Not in allowed scope: still fine when it is a host-rendered
        # contract document with unmodified content.
        return content_matches_host_render(path)

    deliverable_files = sorted(
        path
        for path in changed - set(mixed)
        if deliverable(path)
        and not any(
            path_matches(path, pattern)
            for pattern in plan.change_policy.protected_paths
            if not content_matches_host_render(path)
        )
    )
    excluded = sorted((changed - set(mixed)) - set(deliverable_files))
    warnings = [
        f"not staged (mixed with pre-existing user edits): {path}" for path in mixed
    ] + [f"not staged (outside the allowed scope): {path}" for path in excluded]
    return deliverable_files, warnings


def _file_digest(path: Path) -> str:
    """Content hash used to prove a host-rendered document was not tampered with."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint_scope_violation(details) -> str:
    """Stable fingerprint for repeated scope violations."""
    return "scope:" + ",".join(sorted(details))
