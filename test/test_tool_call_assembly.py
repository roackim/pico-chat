"""Tests for streamed tool-call buffer assembly (runrun / merged-args bug)."""

from types import SimpleNamespace
import asyncio

import pytest

from pico_chat.harness.harness import Harness


async def _collect_tool_drafts(helper, chunks_iter):
    """Run the tool-call handling section against a fake server stream."""
    drafts = []
    used = []
    for chunk in chunks_iter:
        if hasattr(chunk, "tool_name"):
            drafts.append((getattr(chunk, "tool_call_id", None), chunk.tool_name, chunk.tool_args))
        if chunk in used:
            pass
    return drafts


class _FakeServer:
    def __init__(self, stream):
        self._stream = stream
    async def create_completion(self, messages, tools=None, stream=True):
        for chunk in self._stream:
            yield chunk


def _delta_with_tool_calls(calls):
    """Build an SDK-like chunk with the given tool-call deltas."""
    return SimpleNamespace(
        id="c1",
        choices=[SimpleNamespace(
            index=0,
            delta=SimpleNamespace(
                content=None,
                reasoning_content=None,
                tool_calls=calls,
            ),
            finish_reason=None,
        )],
        usage=None,
    )


def test_two_tool_calls_same_index_distinct_ids_do_not_merge():
    """Two tool calls sharing index 0 but differing ids stay separate."""
    stream = [
        # call A: id=call_a, index 0, name fragment, args fragment
        _delta_with_tool_calls([
            SimpleNamespace(index=0, id="call_a", function=SimpleNamespace(name="run", arguments="{\"command\": \"echo hello\"}")),
        ]),
        # call B: id=call_b, index 0 (reuses same index!) — must NOT merge with A
        _delta_with_tool_calls([
            SimpleNamespace(index=0, id="call_b", function=SimpleNamespace(name="run", arguments="{\"command\": \"date\"}")),
        ]),
        # continuation of A: args only
        _delta_with_tool_calls([
            SimpleNamespace(index=0, id="call_a", function=SimpleNamespace(name="", arguments="}")),
        ]),
    ]

    h = Harness.__new__(Harness)
    h.state = None
    h._current_reasoning = ""
    h.debug_stream = SimpleNamespace(log=lambda *a, **k: None)
    h.server = _FakeServer(stream)
    h._last_full_content = ""
    h._last_full_reasoning = ""
    h._last_tool_calls = None
    h._last_detected_thinking_tag = None
    h._tool_permissions = None

    from pico_chat.harness.thinking_parser import ThinkingTagParser, MetricsState
    from pico_chat import pico_cfg

    metrics = MetricsState()
    parser = ThinkingTagParser()
    tool_calls_buffer = {}
    h._current_reasoning = ""

    async def run():
        chunks = []
        h.state = object()
        # Drive the same loop body manually for determinism.
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    key = tc.id or tc.index
                    if key not in tool_calls_buffer:
                        tool_calls_buffer[key] = {
                            "index": tc.index, "id": tc.id,
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    else:
                        tool_calls_buffer[key]["index"] = tool_calls_buffer[key].get("index", tc.index)
                    if tc.id:
                        tool_calls_buffer[key]["id"] = tc.id
                    if getattr(tc.function, "name", None):
                        tool_calls_buffer[key]["function"]["name"] += tc.function.name
                    if getattr(tc.function, "arguments", None):
                        tool_calls_buffer[key]["function"]["arguments"] += tc.function.arguments

        # Reconstruction via the shared production helper.
        return Harness._assemble_tool_calls(tool_calls_buffer)

    calls = asyncio.run(run())

    # Two separate calls, not merged into runrun / doubled args.
    assert len(calls) == 2
    names = {c["function"]["name"] for c in calls}
    assert names == {"run"}
    args_text = " ".join(c["function"]["arguments"] for c in calls)
    assert "echo hello" in args_text
    assert "date" in args_text
    # No concatenated name like "runrun".
    for c in calls:
        assert c["function"]["name"] == "run"
        assert c["function"]["arguments"].startswith("{")


def test_assemble_tool_calls_mixed_int_str_keys_do_not_crash():
    """Buffer with int (index) and str (id) keys reconstructs type-safely."""
    from pico_chat.harness.harness import Harness

    # One call keyed by id (str), another fell back to index (int).
    stream = [
        _delta_with_tool_calls([
            SimpleNamespace(index=0, id="call_a", function=SimpleNamespace(name="run", arguments="{\"command\": \"a\"}")),
        ]),
        _delta_with_tool_calls([
            SimpleNamespace(index=1, id=None, function=SimpleNamespace(name="run", arguments="{\"command\": \"b\"}")),
        ]),
    ]

    def collect():
        tool_calls_buffer = {}
        for chunk in stream:
            for tc in chunk.choices[0].delta.tool_calls:
                key = tc.id or tc.index
                if key not in tool_calls_buffer:
                    tool_calls_buffer[key] = {
                        "index": tc.index, "id": tc.id,
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                else:
                    tool_calls_buffer[key]["index"] = tool_calls_buffer[key].get("index", tc.index)
                if tc.id:
                    tool_calls_buffer[key]["id"] = tc.id
                if getattr(tc.function, "name", None):
                    tool_calls_buffer[key]["function"]["name"] += tc.function.name
                if getattr(tc.function, "arguments", None):
                    tool_calls_buffer[key]["function"]["arguments"] += tc.function.arguments
        # Must not raise '<' not supported between 'int' and 'str'.
        calls = Harness._assemble_tool_calls(tool_calls_buffer)
        return calls, set(type(k).__name__ for k in tool_calls_buffer)

    calls, key_types = collect()
    assert len(calls) == 2
    assert key_types == {"str", "int"}
    assert calls[0]["function"]["arguments"] == '{"command": "a"}'
    assert calls[1]["function"]["arguments"] == '{"command": "b"}'