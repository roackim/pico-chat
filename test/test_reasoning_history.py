"""Reasoning is persisted in history and only re-sent when configured.

``preserve_reasoning_traces`` used to control whether reasoning was *stored*;
it now controls only whether stored reasoning is folded back into the request
so the model sees its prior chain-of-thought.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from pico_chat import pico_cfg
from pico_chat.harness.endpoint import Endpoint
from pico_chat.harness.harness import Harness


def _chunk(content=None, reasoning=None, finish=None):
    delta = SimpleNamespace(content=content, reasoning_content=reasoning, tool_calls=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish)],
        usage=None,
    )


def _harness():
    # Only ``_to_api_message`` (and its static tag helper) are exercised.
    return Harness.__new__(Harness)


def test_chat_stores_reasoning_verbatim_in_history(tmp_path, monkeypatch):
    monkeypatch.setattr(pico_cfg.config, "preserve_reasoning_traces", False)
    with patch(
        "pico_chat.harness.harness.get_active_endpoint",
        return_value=Endpoint(name="test", type="llamacpp"),
    ):
        harness = Harness(workspace_path=str(tmp_path), depth=0)

    async def fake_completion(messages, tools=None, stream=True):
        yield _chunk(reasoning="let me think")
        yield _chunk(content="the answer")
        yield _chunk(finish="stop")

    harness.endpoint.create_completion = fake_completion

    async def drain():
        return [event async for event in harness.chat("hi")]

    asyncio.run(drain())

    assistant = [m for m in harness.history if m.get("role") == "assistant"]
    assert len(assistant) == 1
    assert assistant[0]["reasoning"] == "let me think"
    assert assistant[0]["content"] == "the answer"


def test_openai_adapter_reads_openrouter_reasoning_field():
    """OpenRouter streams ``reasoning``; DeepSeek streams ``reasoning_content``."""
    from pico_chat.harness.endpoint_openai import _adapt_stream_chunk

    def reason(payload):
        chunk = _adapt_stream_chunk(
            {"choices": [{"index": 0, "delta": payload, "finish_reason": None}]}
        )
        return chunk.choices[0].delta.reasoning_content

    assert reason({"reasoning": "pondering"}) == "pondering"
    assert reason({"reasoning_content": "pondering"}) == "pondering"
    assert reason({"reasoning_details": [{"text": "a"}, {"text": "b"}]}) == "ab"


def test_openrouter_streamed_reasoning_reaches_history(tmp_path, monkeypatch):
    """The whole pipe: adapter → harness → history entry."""
    from pico_chat.harness.endpoint_openai import _adapt_stream_chunk

    monkeypatch.setattr(pico_cfg.config, "preserve_reasoning_traces", False)
    with patch(
        "pico_chat.harness.harness.get_active_endpoint",
        return_value=Endpoint(name="test", type="openrouter"),
    ):
        harness = Harness(workspace_path=str(tmp_path), depth=0)

    raw = [
        {"choices": [{"index": 0, "delta": {"reasoning": "OR THOUGHT"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"content": "answer"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]

    async def fake_completion(messages, tools=None, stream=True):
        for payload in raw:
            yield _adapt_stream_chunk(payload)

    harness.endpoint.create_completion = fake_completion

    async def drain():
        return [event async for event in harness.chat("hi")]

    asyncio.run(drain())

    assistant = [m for m in harness.history if m.get("role") == "assistant"]
    assert assistant[0]["reasoning"] == "OR THOUGHT"
    assert assistant[0]["content"] == "answer"


def test_api_message_drops_reasoning_by_default(monkeypatch):
    monkeypatch.setattr(pico_cfg.config, "preserve_reasoning_traces", False)
    entry = {
        "id": "a1", "role": "assistant", "content": "answer",
        "reasoning": "a deep thought", "reasoning_tag": "<think>",
    }

    api = _harness()._to_api_message(entry)

    assert api["content"] == "answer"
    assert "reasoning" not in api
    assert "reasoning_tag" not in api


def test_api_message_folds_reasoning_when_enabled(monkeypatch):
    monkeypatch.setattr(pico_cfg.config, "preserve_reasoning_traces", True)
    entry = {
        "id": "a1", "role": "assistant", "content": "answer",
        "reasoning": "a deep thought", "reasoning_tag": "<think>",
    }

    api = _harness()._to_api_message(entry)

    assert "<think>\na deep thought\n</think>" in api["content"]
    assert api["content"].rstrip().endswith("answer")
    assert "reasoning" not in api
