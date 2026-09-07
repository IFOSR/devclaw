"""Codex-powered Planner harness: initial planning and round review."""

from __future__ import annotations

from metacoding.harnesses.base import (
    DECISION_SCHEMA_HINT,
    PLAN_SCHEMA_HINT,
    Harness,
    HarnessContext,
)


class CodexPlanner(Harness):
    """Planner adapter using ``codex exec`` with the planner's own model."""

    name = "planner"
    provider = "codex"

    def build_command(self, stage: str, ctx: HarnessContext) -> list[str]:
        from metacoding.harnesses.base import HarnessTask

        task: HarnessTask = self.build_task(stage, ctx)
        command = [self.config.command, "exec"]
        if self.config.model:
            command += ["-m", self.config.model]
        command += [
            "--skip-git-repo-check",
            "--json",
            "-o",
            str(task.last_message_path),
        ]
        command += list(self.config.extra_args)
        command += [task.prompt]
        return command

    def build_prompt(self, stage: str, ctx: HarnessContext) -> str:
        if stage == "plan":
            return self._plan_prompt(ctx)
        if stage == "review":
            return self._review_prompt(ctx)
        raise ValueError(f"planner does not support stage {stage!r}")

    def _plan_prompt(self, ctx: HarnessContext) -> str:
        return f"""You are the PLANNER harness of MetaCoding running in the project at {ctx.project_root}.

Requirement from the operator:
\"\"\"{ctx.requirement}\"\"\"

Your job for this stage:
1. Inspect the existing project (source, tests, configuration, conventions) before planning.
2. Produce the development contract for the requirement: goal, scope, non-goals, architecture, acceptance criteria, coding tasks, and change policy.
3. Write the structured plan as a JSON object to EXACTLY this path: {ctx.report_dir / 'plan-payload.json'}

The host renders the four contract documents (PRD.md, ARCHITECTURE.md, IMPLEMENTATION_PLAN.md, ACCEPTANCE.md) under {ctx.docs_dir}/ from your plan; those documents under docs/metacoding are the shared contract for the Coder and Tester.

Constraints:
- Do NOT modify product source code or tests. You own planning documents only.
- acceptance_criteria priorities are "blocking" or "non_blocking".
- change_policy.allowed_paths must list the path patterns the Coder may touch (fnmatch patterns such as "src/**").
- change_policy.protected_paths must list paths the Coder and Tester must never modify.

The JSON must match this shape:
{PLAN_SCHEMA_HINT}

Write only files you own plus the JSON payload path above."""

    def _review_prompt(self, ctx: HarnessContext) -> str:
        tester_summary = "no tester report found (this should not happen)"
        if ctx.tester_report is not None:
            report = ctx.tester_report
            failing = [
                item.id for item in report.acceptance_results if item.status != "pass"
            ]
            open_findings = [
                f"{finding.id} {finding.severity} {finding.title}"
                for finding in report.findings
            ]
            tester_summary = (
                f"status={report.status}\n"
                f"test commands: {[f'{c.command} -> exit {c.exit_code}' for c in report.test_commands]}\n"
                f"failing acceptance ids: {failing}\n"
                f"open findings: {open_findings}\n"
                f"PRD drift: {report.prd_drift}\n"
                f"regression risks: {report.regression_risks}"
            )
        return f"""You are the PLANNER harness of MetaCoding reviewing round {ctx.round_number}.

Requirement:
\"\"\"{ctx.requirement}\"\"\"

Read these artifacts from the workspace before deciding:
- {ctx.docs_dir / 'PRD.md'}, {ctx.docs_dir / 'ARCHITECTURE.md'}, {ctx.docs_dir / 'IMPLEMENTATION_PLAN.md'}, {ctx.docs_dir / 'ACCEPTANCE.md'}
- The Tester report for this round: {ctx.report_dir / 'tester-report.json'}
- The human-readable test report: {ctx.docs_dir / 'TEST_REPORT.md'}
- The Coder report for this round: {ctx.report_dir / 'coding-report.json'}

Tester evidence summary:
{tester_summary}

Changed files this round: {ctx.changed_files}

Decide exactly one of: "accept", "rework", "blocked", "human_review_required".
- accept only if all blocking acceptance criteria passed, required test commands passed, and no P0/P1 finding remains.
- rework requires concrete rework_tasks the Coder can execute.
- blocked when the requirement cannot be met (missing dependency, impossible constraint).
- human_review_required for credentials, paid actions, protected operations, or destructive decisions.

Write your decision JSON to EXACTLY this path: {ctx.report_dir / 'review-payload.json'}

Shape:
{DECISION_SCHEMA_HINT}

Do NOT modify product source code, product tests, or Tester reports."""
