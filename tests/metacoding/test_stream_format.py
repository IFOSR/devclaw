"""Live stream formatting: JSONL events to readable lines."""

from __future__ import annotations

import json

from metacoding.stream_format import CodexJsonlFormatter


def feed_all(formatter: CodexJsonlFormatter, chunks: list[str]) -> str:
    return "".join(formatter.feed(chunk) for chunk in chunks)


def test_agent_message_rendered_with_preview():
    f = CodexJsonlFormatter()
    out = feed_all(
        f,
        [
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "i1",
                        "type": "agent_message",
                        "text": "I'll create /tmp/ping.txt with exactly pong.",
                    },
                }
            )
            + "\n"
        ],
    )
    assert out == "│ I'll create /tmp/ping.txt with exactly pong.\n"


def test_line_split_across_chunks_is_buffered():
    f = CodexJsonlFormatter()
    event = json.dumps(
        {
            "type": "item.completed",
            "item": {"id": "i2", "type": "agent_message", "text": "half-way message"},
        }
    )
    out = feed_all(f, [event[:20], event[20:45], event[45:] + "\n"])
    assert out == "│ half-way message\n"


def test_file_change_lists_paths():
    f = CodexJsonlFormatter()
    out = feed_all(
        f,
        [
            json.dumps(
                {
                    "type": "item.started",
                    "item": {
                        "id": "i3",
                        "type": "file_change",
                        "changes": [{"path": "/tmp/a.py", "kind": "add"}],
                    },
                }
            )
            + "\n",
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "i3",
                        "type": "file_change",
                        "changes": [
                            {"path": "/tmp/a.py", "kind": "add"},
                            {"path": "/tmp/b.py", "kind": "update"},
                        ],
                    },
                }
            )
            + "\n",
        ],
    )
    lines = out.strip().splitlines()
    assert lines[0] == "│ file_change …: +/tmp/a.py"
    assert lines[1] == "│ file_change: +/tmp/a.py ~/tmp/b.py"


def test_command_execution_with_exit_code():
    f = CodexJsonlFormatter()
    out = feed_all(
        f,
        [
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "i4",
                        "type": "command_execution",
                        "command": ["python3", "-m", "pytest", "-q"],
                        "exit_code": 1,
                    },
                }
            )
            + "\n"
        ],
    )
    assert out == "│ cmd (exit 1): python3 -m pytest -q\n"


def test_noise_events_dropped_and_usage_rendered():
    f = CodexJsonlFormatter()
    out = feed_all(
        f,
        [
            json.dumps({"type": "thread.started", "thread_id": "t"}) + "\n",
            json.dumps({"type": "turn.started"}) + "\n",
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 31440,
                        "cached_input_tokens": 19200,
                        "output_tokens": 75,
                    },
                }
            )
            + "\n",
        ],
    )
    assert out == "│ tokens: in 31440 (cached 19200) out 75\n"


def test_non_json_passthrough_and_errors():
    f = CodexJsonlFormatter()
    out = feed_all(
        f,
        ["WARNING: something human\n", json.dumps({"type": "error", "message": "boom"}) + "\n"],
    )
    assert "WARNING: something human" in out
    assert "error: boom" in out


def test_flush_emits_trailing_partial_line():
    f = CodexJsonlFormatter()
    event = json.dumps(
        {"type": "error", "message": "trailing"}
    )
    feed_all(f, [event])  # no trailing newline
    assert f.flush() == "│ error: trailing\n"


def test_reasoning_items_are_silent():
    f = CodexJsonlFormatter()
    out = feed_all(
        f,
        [
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "i5", "type": "reasoning", "text": "thinking..."},
                }
            )
            + "\n"
        ],
    )
    assert out == ""


def test_pi_jsonl_formatter_renders_tool_activity():
    from metacoding.stream_format import PiJsonlFormatter

    f = PiJsonlFormatter()
    events = [
        json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "toolcall_start", "toolName": "write"}}),
        json.dumps({"type": "tool_execution_start", "toolName": "write",
                    "args": {"path": "/x/hi.txt", "content": "hello"}}),
        json.dumps({"type": "tool_execution_end", "toolName": "write",
                    "result": {"content": [{"type": "text", "text": "Successfully wrote 5 bytes"}]}, "isError": False}),
        json.dumps({"type": "tool_execution_start", "toolName": "bash",
                    "args": {"command": "python3 -m pytest -q"}}),
        json.dumps({"type": "turn_end", "message": {"role": "assistant",
                    "content": [{"type": "text", "text": "Created hi.txt containing hello."}],
                    "usage": {"input": 10, "output": 5}}}),
    ]
    out = feed_all(f, [e + "\n" for e in events])
    lines = out.strip().splitlines()
    assert lines[0] == "│ calling write…"
    assert lines[1] == "│ write: /x/hi.txt"
    assert lines[2] == "│ ✓ write: Successfully wrote 5 bytes"
    assert lines[3] == "│ bash: python3 -m pytest -q"
    assert "Created hi.txt containing hello." in out
    assert "tokens: in 10 out 5" in out


def test_pi_jsonl_drops_noise_and_errors():
    from metacoding.stream_format import PiJsonlFormatter

    f = PiJsonlFormatter()
    out = feed_all(
        f,
        [
            json.dumps({"type": "session", "version": 3}) + "\n",
            json.dumps({"type": "agent_start"}) + "\n",
            json.dumps({"type": "tool_execution_end", "toolName": "write", "isError": True}) + "\n",
        ],
    )
    assert "│ write: error" in out
    assert "agent_start" not in out
    assert "session" not in out
