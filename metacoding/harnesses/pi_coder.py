"""Pi-powered Coding harness: implements the Planner contract in-place."""

from __future__ import annotations

from metacoding.harnesses.base import CODING_SCHEMA_HINT, Harness, HarnessContext


class PiCoder(Harness):
    """Coder adapter running ``pi -p`` with the coder's own model."""

    name = "coder"
    provider = "pi"

    def build_command(self, stage: str, ctx: HarnessContext) -> list[str]:
        from metacoding.harnesses.base import HarnessTask

        task: HarnessTask = self.build_task(stage, ctx)
        command = [self.config.command, "-p"]
        if self.config.model:
            command += ["--model", self.config.model]
        command += ["--no-session"]
        command += list(self.config.extra_args)
        command += ["--", task.prompt]
        return command

    def build_prompt(self, stage: str, ctx: HarnessContext) -> str:
        if stage != "code":
            raise ValueError(f"coder does not support stage {stage!r}")
        plan = ctx.plan
        assert plan is not None, "coder requires a validated plan in the context"
        policy = plan.change_policy
        if ctx.rework_tasks:
            task_lines = "\n".join(
                f"- {task.get('id', 'REWORK')}: {task.get('description', '')}"
                f" (areas: {', '.join(task.get('target_area', [])) or 'any'};"
                f" verify: {task.get('verification', 'tests pass')})"
                for task in ctx.rework_tasks
            )
            task_header = "Rework tasks for this round (from the Planner review):"
        else:
            task_lines = "\n".join(
                f"- {task.id}: {task.description} "
                f"(expected files: {', '.join(task.expected_files) or 'n/a'}; "
                f"required tests: {', '.join(task.required_tests) or 'n/a'}; "
                f"done when: {task.done_when})"
                for task in plan.coding_tasks
            )
            task_header = "Coding tasks from the implementation plan:"

        return f"""You are the CODER harness of MetaCoding working in {ctx.project_root}.

Requirement:
\"\"\"{ctx.requirement}\"\"\"

Read the development contract first:
- {ctx.docs_dir / 'PRD.md'}
- {ctx.docs_dir / 'ARCHITECTURE.md'}
- {ctx.docs_dir / 'IMPLEMENTATION_PLAN.md'}
- {ctx.docs_dir / 'ACCEPTANCE.md'}

{task_header}
{task_lines}

Change policy (STRICT):
- Allowed paths (fnmatch patterns): {policy.allowed_paths}
- Protected paths you must never modify: {policy.protected_paths}
- Forbidden actions: {policy.forbidden_actions}

Rules:
- Implement only the tasks above inside the project directory. Add or update product tests when the plan requires them.
- Do NOT rewrite the PRD, acceptance criteria, or any Planner/Tester document.
- Do NOT mark the product accepted and do NOT perform git commits or GitHub actions.
- Run focused checks for the files you touched when practical.

When finished, write your report as a JSON object to EXACTLY this path: {ctx.report_dir / 'code-payload.json'}

Shape:
{CODING_SCHEMA_HINT}

changed_files must list the paths you created or modified relative to the project root."""
