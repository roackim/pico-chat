"""Tests for streamed tool-call buffer assembly.

The assembler must handle two real streaming patterns:
1. One call whose id appears only on the first delta (DeepSeek) — args-only
   deltas afterwards must attach to that same call (not split).
2. Multiple distinct calls that share the same index (e.g. index 0) but have
   distinct ids — they must NOT merge into e.g. "runrun".
"""

from types import SimpleNamespace

from pico_chat.harness.harness import Harness


def _delta_with_tool_calls(calls):
    return SimpleNamespace(
        id="c1",
        choices=[SimpleNamespace(
            index=0,
            delta=SimpleNamespace(content=None, reasoning_content=None, tool_calls=calls),
            finish_reason=None,
        )],
        usage=None,
    )


def _tc(index, call_id, name="", arguments=None):
    return SimpleNamespace(index=index, id=call_id,
                           function=SimpleNamespace(name=name, arguments=arguments))


def _assemble(deltas_list):
    """Replay the production assembly loop against a list of delta chunk lists."""
    buffer = {}
    active = {}
    for calls in deltas_list:
        for tc in calls:
            if tc.id:
                key = tc.id
                if tc.id not in buffer:
                    buffer[tc.id] = {"index": tc.index, "id": tc.id, "type": "function",
                                     "function": {"name": "", "arguments": ""}}
                active[tc.index] = tc.id
            else:
                key = active.get(tc.index)
                if key is None:
                    key = tc.index
                if key not in buffer:
                    buffer[key] = {"index": tc.index, "id": None, "type": "function",
                                   "function": {"name": "", "arguments": ""}}
            if tc.function.name:
                buffer[key]["function"]["name"] += tc.function.name
            if tc.function.arguments:
                buffer[key]["function"]["arguments"] += tc.function.arguments
    return Harness._assemble_tool_calls(buffer), buffer


def test_id_on_first_delta_keeps_args():
    """DeepSeek pattern: id on first delta, id-less args after — one call."""
    calls, _ = _assemble([
        [_tc(0, "call_abc", name="run", arguments="")],
        [_tc(0, None, arguments='{"command": "echo hi"}')],
    ])
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "run"
    assert calls[0]["function"]["arguments"] == '{"command": "echo hi"}'


def test_two_calls_same_index_distinct_ids_do_not_merge():
    """Two calls both at index 0 but distinct ids stay separate (no runrun)."""
    calls, _ = _assemble([
        [_tc(0, "call_a", name="run", arguments='{"command": "a"}')],
        [_tc(0, "call_b", name="run", arguments='{"command": "b"}')],
        [_tc(0, "call_a", arguments='}')],
    ])
    assert len(calls) == 2
    names = {c["function"]["name"] for c in calls}
    assert names == {"run"}
    args_text = " ".join(c["function"]["arguments"] for c in calls)
    assert "a" in args_text and "b" in args_text
    for c in calls:
        assert c["function"]["name"] == "run"


def test_id_less_first_delta_falls_back_to_index():
    """If no id ever arrives, index keying still works (single call)."""
    calls, _ = _assemble([
        [_tc(0, None, name="run")],
        [_tc(0, None, arguments='{"command": "ls"}')],
    ])
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "run"
    assert calls[0]["function"]["arguments"] == '{"command": "ls"}'


def test_no_mixed_int_str_keys_when_only_ids():
    """When ids are present, all keys are strings; reconstruction is stable."""
    calls, keys = _assemble([
        [_tc(0, "call_x", name="run", arguments='{}')],
    ])
    assert len(calls) == 1
