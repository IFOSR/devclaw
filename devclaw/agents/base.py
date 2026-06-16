from __future__ import annotations

from pathlib import Path

from devclaw.core.models import AgentOutput


def write_artifact(workspace: Path, relative_path: str, content: str) -> AgentOutput:
    path = workspace / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return AgentOutput(
        agent="System",
        artifact=relative_path,
        content=content,
        path=relative_path,
    )
