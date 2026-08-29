"""Tests for streamed tool-call buffer assembly.

Validates that tool-call deltas are keyed by the integer index so that name
and argument fragments accumulate into one call, and that streaming patterns
where the id is present only on the first delta do not split the call or
crash reconstruction.
"""

from types import SimpleNamespace

from pico_chat.harness.harness import Harness


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


def _run_stream():
    """DeepSeek-style stream: id+name on first delta, then id-less args."""
    return [
        # First delta: id + name, no arguments.
        _delta_with_tool_calls([
            SimpleNamespace(index=0, id="call_abc", function=SimpleNamespace(name="run", arguments="")),
        ]),
        # Later deltas: no id (falls back to index), only argument fragments.
        _delta_with_tool_calls([
            SimpleNamespace(index=0, id=None, function=SimpleNamespace(name="", arguments='{"command": "echo hi"}')),
        ]),
    ]


def _collect(stream):
    """Mirror the production assembly loop, keyed by index."""
    tool_calls_buffer = {}
    for chunk in stream:
        delta = chunk.choices[0].delta
        if not delta.tool_calls:
            continue
        for tc in delta.tool_calls:
            key = tc.index  # <-- index-keyed (the fix)
            if key not in tool_calls_buffer:
                tool_calls_buffer[key] = {
                    "index": tc.index, "id": tc.id,
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                }
            if tc.id:
                tool_calls_buffer[key]["id"] = tc.id
            if getattr(tc.function, "name", None):
                tool_calls_buffer[key]["function"]["name"] += tc.function.name
            if getattr(tc.function, "arguments", None):
                tool_calls_buffer[key]["function"]["arguments"] += tc.function.arguments
    return Harness._assemble_tool_calls(tool_calls_buffer), tool_calls_buffer


def test_deltas_name_and_args_accumulate_under_index():
    """A single call streamed across chunks keeps name + args together."""
    calls, _ = _collect(_run_stream())

    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "run"
    assert calls[0]["function"]["arguments"] == '{"command": "echo hi"}'
    # Id captured from the first delta.
    assert calls[0]["id"] == "call_abc"


def test_reconstruction_all_int_keys_does_not_crash():
    """Buffer with only int index keys reconstructs cleanly."""
    stream = [
        _delta_with_tool_calls([
            SimpleNamespace(index=0, id="a", function=SimpleNamespace(name="run", arguments='{"command": "x"}')),
        ]),
        _delta_with_tool_calls([
            SimpleNamespace(index=1, id=None, function=SimpleNamespace(name="run", arguments='{"command": "y"}')),
        ]),
    ]
    calls, keys = _collect(stream)
    assert len(calls) == 2
    assert all(type(k) is int for k in keys)


def test_no_mixed_int_str_keys():
    """Index-keying never produces a str key, so sorted() is type-safe."""
    calls, keys = _collect(_run_stream())
    assert len(calls) == 1
    assert set(type(k) for k in keys) == {int}
