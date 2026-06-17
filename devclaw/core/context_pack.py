from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from devclaw.core.context import scan_project_context
from devclaw.core.memory import load_memory


@dataclass(frozen=True)
class ContextPack:
    path: Path
    markdown: str
    has_prior_context: bool
    recent_project_ids: list[str]


def build_context_pack(project_root: Path, intent: str, max_sessions: int = 5) -> ContextPack:
    context_dir = project_root / ".devclaw" / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    memory = load_memory(project_root)
    sessions = _recent_session_manifests(project_root, max_sessions)
    stage_refs = _stage_references(project_root, sessions)
    project_context = scan_project_context(project_root)
    recent_project_ids = _recent_project_ids(memory, sessions)
    has_prior_context = bool(memory.request_history or sessions or stage_refs)
    lines = [
        "# DevClaw Context Pack",
        "",
        "## Current Request",
        intent,
        "",
        "## Project Snapshot",
        f"- Root: {project_root}",
        f"- Primary language: {project_context.primary_language}",
        f"- Frameworks: {', '.join(project_context.frameworks) or 'unknown'}",
        f"- Test commands: {', '.join(project_context.test_commands) or 'none detected'}",
        "",
        "## Recent Requests",
        *_recent_request_lines(memory.request_history[-max_sessions:]),
        "",
        "## Recent Deliveries",
        *_recent_delivery_lines(memory.delivery_history[-max_sessions:]),
        "",
        "## Decisions",
        *_decision_lines(memory.decisions[-max_sessions:]),
        "",
        "## Recent Sessions",
        *_session_lines(project_root, sessions),
        "",
        "## Related Stage Documents",
        *_stage_reference_lines(project_root, stage_refs),
        "",
        "## Context Strategy",
        "- Use recent summaries and document references as retrieval anchors.",
        "- Prefer targeted workflow when the request is a localized follow-up to prior delivered work.",
        "- Do not paste every historical document into prompts; load full files only when relevant.",
    ]
    markdown = "\n".join(lines).rstrip() + "\n"
    path = context_dir / "current-context-pack.md"
    path.write_text(markdown, encoding="utf-8")
    return ContextPack(
        path=path,
        markdown=markdown,
        has_prior_context=has_prior_context,
        recent_project_ids=recent_project_ids,
    )


def _recent_session_manifests(project_root: Path, max_sessions: int) -> list[dict[str, Any]]:
    sessions_dir = project_root / ".devclaw" / "sessions"
    if not sessions_dir.exists():
        return []
    manifests = sorted(sessions_dir.glob("*/manifest.json"), key=lambda path: path.parent.name)
    result = []
    for path in manifests[-max_sessions:]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        data["_path"] = str(path.relative_to(project_root))
        result.append(data)
    return result


def _stage_references(project_root: Path, sessions: list[dict[str, Any]]) -> list[Path]:
    stages_dir = project_root / ".devclaw" / "stages"
    if not stages_dir.exists():
        return []
    session_ids = {str(session.get("session_id", "")) for session in sessions}
    refs: list[Path] = []
    for path in sorted(stages_dir.glob("*/*/index.md")):
        if session_ids and path.parent.name not in session_ids:
            continue
        refs.append(path)
        final_report = path.parent / "09-final" / "final-delivery-report.md"
        if final_report.exists():
            refs.append(final_report)
    return refs


def _recent_project_ids(memory, sessions: list[dict[str, Any]]) -> list[str]:
    values = [item.get("project_id", "") for item in memory.request_history]
    values.extend(str(session.get("project_id", "")) for session in sessions)
    return [value for value in dict.fromkeys(values) if value]


def _recent_request_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None"]
    return [
        f"- {item.get('timestamp', 'unknown')} [{item.get('project_id', 'unknown')}] {item.get('intent', '')}"
        for item in items
    ]


def _recent_delivery_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None"]
    return [
        f"- {item.get('timestamp', 'unknown')} [{item.get('project_id', 'unknown')}] {item.get('status', 'unknown')}: {item.get('goal', '')}"
        for item in items
    ]


def _decision_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None"]
    return [
        f"- {item.get('timestamp', 'unknown')} [{item.get('project_id', 'unknown')}] {item.get('decision', '')} Reason: {item.get('reason', '')}"
        for item in items
    ]


def _session_lines(project_root: Path, sessions: list[dict[str, Any]]) -> list[str]:
    if not sessions:
        return ["- None"]
    lines = []
    for session in sessions:
        changed = ", ".join(session.get("changed_files") or []) or "none"
        lines.append(
            f"- {session.get('completed_at', 'unknown')} {session.get('intent', '')} Changed: {changed} Manifest: {session.get('_path', '')}"
        )
    return lines


def _stage_reference_lines(project_root: Path, refs: list[Path]) -> list[str]:
    if not refs:
        return ["- None"]
    return [f"- {path.relative_to(project_root)}" for path in refs]
