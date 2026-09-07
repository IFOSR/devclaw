"""Codex-powered Tester harness: independent verification with evidence."""

from __future__ import annotations

from metacoding.harnesses.base import TESTER_SCHEMA_HINT, Harness, HarnessContext


class CodexTester(Harness):
    """Tester adapter using ``codex exec`` with the tester's own model."""

    name = "tester"
    provider = "codex"

    def build_command(self, stage: str, ctx: HarnessContext) -> list[str]:
        from metacoding.harnesses.base import HarnessTask

        task: HarnessTask = self.build_task(stage, ctx)
        command = [self.config.command, "exec"]
        if self.config.model:
            command += ["-m", self.config.model]
        command += [
            # The host pins the sandbox level; extra_args cannot override it.
            "-s",
            "workspace-write",
            "--skip-git-repo-check",
            "--json",
            "-o",
            str(task.last_message_path),
        ]
        command += list(self.config.extra_args)
        command += [task.prompt]
        return command

    def build_prompt(self, stage: str, ctx: HarnessContext) -> str:
        if stage != "test":
            raise ValueError(f"tester does not support stage {stage!r}")
        plan = ctx.plan
        assert plan is not None, "tester requires a validated plan in the context"
        criteria = "\n".join(
            f"- {item.id} [{item.priority}] {item.description} "
            f"(verify: {item.verification_method})"
            for item in plan.acceptance_criteria
        )
        commands = "\n".join(f"- {command}" for command in ctx.test_commands) or "- none detected"
        return f"""You are the TESTER harness of MetaCoding reviewing round {ctx.round_number} in {ctx.project_root}.

Requirement:
\"\"\"{ctx.requirement}\"\"\"

Read the development contract:
- {ctx.docs_dir / 'PRD.md'}
- {ctx.docs_dir / 'ARCHITECTURE.md'}
- {ctx.docs_dir / 'IMPLEMENTATION_PLAN.md'}
- {ctx.docs_dir / 'ACCEPTANCE.md'}

Acceptance criteria to verify:
{criteria}

Detected project test commands (run these and record real exit codes):
{commands}

Coder-reported changed files this round: {ctx.changed_files}

Your job:
1. Inspect the real implementation, including the git diff for this round.
2. Run the project's test commands and any acceptance-specific checks. Record the actual commands, exit codes, and output summaries.
3. Judge every acceptance criterion with concrete evidence (file paths, test names, command output).
4. Report defects as findings with severity P0/P1/P2/P3. Every finding must include evidence.
5. Note PRD drift, regression risks, and missing tests.

Constraints:
- Do NOT modify product source code or product tests. You may only create temporary artifacts under .metacoding/.
- Report what you actually observed; never invent passing results.

Write your report as a JSON object to EXACTLY this path: {ctx.report_dir / 'test-payload.json'}
Also write the human-readable report to {ctx.docs_dir / 'TEST_REPORT.md'}.

Shape:
{TESTER_SCHEMA_HINT}

changed_files must list any files you modified yourself (normally empty)."""
