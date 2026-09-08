"""Live stream formatting for harness output.

codex runs with ``--json`` and streams JSONL events; pi streams plain text.
The formatters here turn machine events into compact human-readable lines
while preserving partial-line buffering across chunk boundaries.
"""

from __future__ import annotations

import json

PREVIEW_LIMIT = 200


def _preview(text: str, limit: int = PREVIEW_LIMIT) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class CodexJsonlFormatter:
    """Buffer chunks, render complete JSONL lines as friendly text."""

    def __init__(self, prefix: str = "│ ") -> None:
        self.prefix = prefix
        self._buffer = ""

    def feed(self, chunk: str) -> str:
        self._buffer += chunk
        rendered: list[str] = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            text = self.render_line(line)
            if text:
                rendered.append(self.prefix + text + "\n")
        return "".join(rendered)

    def flush(self) -> str:
        remainder, self._buffer = self._buffer, ""
        text = self.render_line(remainder)
        return (self.prefix + text + "\n") if text else ""

    def render_line(self, line: str) -> str:
        line = line.strip()
        if not line:
            return ""
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return _preview(line)  # non-JSON passthrough (warnings, etc.)
        if not isinstance(event, dict):
            return ""
        kind = event.get("type")

        if kind in ("thread.started", "turn.started"):
            return ""
        if kind == "turn.completed":
            usage = event.get("usage") or {}
            return "tokens: in {in_tok} (cached {cached}) out {out_tok}".format(
                in_tok=usage.get("input_tokens", "?"),
                cached=usage.get("cached_input_tokens", 0),
                out_tok=usage.get("output_tokens", "?"),
            )
        if kind in ("item.started", "item.completed"):
            item = event.get("item") or {}
            state = "…" if kind == "item.started" else ""
            return self._render_item(item, state)
        if kind == "error":
            return "error: " + _preview(str(event.get("message", "")))
        if kind == "turn.failed":
            error = event.get("error") or {}
            return "turn failed: " + _preview(str(error.get("message", "")))
        return _preview(kind or line)

    def _render_item(self, item: dict, state: str) -> str:
        item_type = item.get("type", "")
        if item_type == "agent_message":
            return f"planner: {_preview(str(item.get('text', '')))}" if state else _preview(
                str(item.get("text", ""))
            )
        if item_type == "file_change":
            changes = item.get("changes") or []
            parts = []
            for change in changes:
                if isinstance(change, dict):
                    mark = {"add": "+", "update": "~", "delete": "-"}.get(
                        str(change.get("kind", "")), "?"
                    )
                    parts.append(f"{mark}{change.get('path', '')}")
            return f"file_change{' ' + state if state else ''}: " + " ".join(parts)
        if item_type == "command_execution":
            command = item.get("command")
            if isinstance(command, list):
                command = " ".join(str(part) for part in command)
            if state:
                return f"cmd: {_preview(str(command or ''))}"
            return f"cmd (exit {item.get('exit_code', '?')}): {_preview(str(command or ''))}"
        if item_type == "error":
            return "error: " + _preview(str(item.get("message", "")))
        if item_type in ("reasoning", "reasoning_text"):
            return ""
        if item_type == "web_search":
            return f"web search: {_preview(str(item.get('query', '')))}"
        return _preview(f"{item_type}{state}") if item_type else ""
