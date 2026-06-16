from __future__ import annotations

from pathlib import Path


def create_task_plan(project_root: Path, intent: str) -> Path:
    path = project_root / ".devclaw" / "tasks" / "latest-task-plan.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        [
            f"# Task Plan: {intent}",
            "",
            "## DAG",
            "1. Research",
            "2. Acceptance Contract",
            "3. Design",
            "4. Architecture",
            "5. Implementation",
            "6. Verification",
            "7. Delivery",
            "",
            "## Parallelization Notes",
            "- Research, design, and architecture must finish before implementation.",
            "- Implementation and documentation may proceed in parallel after architecture.",
            "- Verification gates delivery.",
        ]
    )
    path.write_text(content, encoding="utf-8")
    return path
