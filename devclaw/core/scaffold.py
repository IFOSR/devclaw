from __future__ import annotations

import re
from pathlib import Path


def create_scaffold(project_root: Path, scaffold_type: str, name: str) -> Path:
    safe_name = _safe_name(name)
    scaffolds_dir = project_root / ".devclaw" / "scaffolds"
    scaffolds_dir.mkdir(parents=True, exist_ok=True)
    if scaffold_type == "agent":
        path = scaffolds_dir / f"{safe_name}-agent.md"
        if not path.exists():
            path.write_text(_agent_spec(name), encoding="utf-8")
        return path
    if scaffold_type == "cli":
        path = scaffolds_dir / f"{safe_name}-cli.md"
        if not path.exists():
            path.write_text(_cli_spec(name), encoding="utf-8")
        return path
    raise ValueError(f"unsupported scaffold type: {scaffold_type}")


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "devclaw"


def _agent_spec(name: str) -> str:
    return "\n".join(
        [
            f"# Agent Spec: {name}",
            "",
            "## Mission",
            "Describe the concrete job this Agent performs.",
            "",
            "## Inputs",
            "- User request",
            "- Project context",
            "",
            "## Outputs",
            "- Structured result",
            "- Evidence or report",
            "",
            "## Tools",
            "- Define required tools here.",
            "",
            "## Failure Handling",
            "- Return actionable errors and known limitations.",
        ]
    )


def _cli_spec(name: str) -> str:
    return "\n".join(
        [
            f"# CLI Tool Spec: {name}",
            "",
            "## Commands",
            "- help",
            "- run",
            "",
            "## Acceptance",
            "- CLI exits non-zero on failure.",
            "- CLI has tests and usage docs.",
        ]
    )
