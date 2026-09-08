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


class PiJsonlFormatter:
    """Render pi's ``--mode json`` event stream into readable lines.

    Highlights tool executions (file writes, shell commands) and the final
    answer, keeping the Coder's activity visible instead of a black box.
    """

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
            return _preview(line)
        if not isinstance(event, dict):
            return ""
        kind = event.get("type")

        if kind in ("session", "agent_start", "agent_end", "agent_settled",
                    "turn_start", "message_start", "message_end"):
            return ""
        if kind == "message_update":
            inner = event.get("assistantMessageEvent") or {}
            inner_type = inner.get("type")
            if inner_type == "toolcall_start":
                return f"calling {inner.get('toolName', 'tool')}…"
            if inner_type in ("thinking_start", "thinking_delta", "thinking"):
                return ""
            return ""
        if kind == "tool_execution_start":
            tool = event.get("toolName", "tool")
            args = event.get("args") or {}
            return f"{tool}: {self._args_preview(tool, args)}"
        if kind == "tool_execution_end":
            tool = event.get("toolName", "tool")
            if event.get("isError"):
                return f"{tool}: error"
            text = self._result_preview(event.get("result"))
            return f"✓ {tool}" + (f": {text}" if text else "")
        if kind == "turn_end":
            message = event.get("message") or {}
            text = " ".join(
                str(part.get("text", "")).strip()
                for part in message.get("content", [])
                if isinstance(part, dict) and part.get("type") == "text"
            ).strip()
            usage = message.get("usage") or {}
            if text and usage:
                return f"{_preview(text)}\n  tokens: in {usage.get('input', '?')} out {usage.get('output', '?')}"
            return _preview(text) if text else ""
        if kind in ("text_delta", "thinking_delta", "thinking",
                    "text_start", "text_end", "thinking_end",
                    "toolcall_delta", "toolcall_end"):
            return ""
        return _preview(kind)

    @staticmethod
    def _args_preview(tool: str, args: dict) -> str:
        if tool in ("write", "edit", "read", "apply_patch", "multi_edit"):
            path = args.get("path") or args.get("file_path") or ""
            return _preview(str(path))
        if tool in ("bash", "execute", "run"):
            command = args.get("command") or args.get("cmd") or ""
            return _preview(str(command))
        keys = list(args.keys())[:2]
        return _preview(", ".join(str(args[k])[:60] for k in keys))

    @staticmethod
    def _result_preview(result) -> str:
        if not isinstance(result, dict):
            return ""
        for part in result.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "text":
                return _preview(str(part.get("text", "")))
        return ""


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
            return self._error_label(item.get("message", ""))
        if item_type in ("reasoning", "reasoning_text"):
            return ""
        if item_type == "web_search":
            return f"web search: {_preview(str(item.get('query', '')))}"
        return _preview(f"{item_type}{state}") if item_type else ""

    @staticmethod
    def _error_label(message: str) -> str:
        """codex reuses the 'error' item type for non-fatal notices; label
        the known informational ones 'note' instead of alarming users."""
        lowered = str(message).lower()
        benign_markers = (
            "skill descriptions were shortened",
            "context budget",
            "descriptions are shorter",
        )
        if any(marker in lowered for marker in benign_markers):
            return "note: " + _preview(str(message))
        return "error: " + _preview(str(message))
