from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from devclaw.core.context import scan_project_context


@dataclass(frozen=True)
class ResearchSource:
    title: str
    url: str
    summary: str
    retrieved_at: str


def create_research_report(project_root: Path, topic: str) -> Path:
    context = scan_project_context(project_root)
    sources = _github_sources(topic)
    path = project_root / ".devclaw" / "research" / "latest-research.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        [
            f"# Research Report: {topic}",
            "",
            "## Research Questions",
            "- What problem is this request trying to solve?",
            "- What existing project context affects the solution?",
            "- What implementation options should be compared before building?",
            "",
            "## Current Project Context",
            f"- Primary language: {context.primary_language}",
            f"- Frameworks: {', '.join(context.frameworks) or 'unknown'}",
            f"- Test commands: {', '.join(context.test_commands) or 'none detected'}",
            "",
            "## Sources",
            *[
                f"- {source.title}: {source.url} | Retrieved: {source.retrieved_at} | {source.summary}"
                for source in sources
            ],
            "",
            "## Initial Options",
            "- Minimal patch inside the current project.",
            "- New module or Agent scaffold under project-local files.",
            "- Defer risky or ambiguous changes until the Acceptance Contract is clearer.",
            "",
            "## Research-Driven Decisions",
            "- Prefer approaches that match the current project language and detected test commands.",
            "- Use sourced ecosystem references to avoid designing from a blank template.",
            "",
            "## Implications for DevClaw",
            "- Update Acceptance Contract before implementation.",
            "- Run project quality checks after implementation.",
            "- Store decisions and delivery notes under .devclaw/.",
        ]
    )
    path.write_text(content, encoding="utf-8")
    return path


def _github_sources(topic: str) -> list[ResearchSource]:
    query = urllib.parse.urlencode({"q": topic, "per_page": "3"})
    request = urllib.request.Request(
        f"https://api.github.com/search/repositories?{query}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "DevClaw-Research-Agent",
        },
    )
    retrieved_at = datetime.now(timezone.utc).date().isoformat()
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    sources: list[ResearchSource] = []
    for item in data.get("items", [])[:3]:
        sources.append(
            ResearchSource(
                title=str(item.get("full_name") or item.get("name") or "GitHub repository"),
                url=str(item.get("html_url")),
                summary=str(item.get("description") or "No description provided."),
                retrieved_at=retrieved_at,
            )
        )
    return sources
