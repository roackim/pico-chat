# Reasoning Trace Handling in pico-chat

*Investigates whether pico-chat preserves model reasoning/thinking traces across multi-turn conversations.*

> **Status**: Reasoning traces are now preserved via the `preserve_reasoning_traces` config flag (default: `off`).
> When enabled, thinking content accumulated during streaming is folded back into the assistant message
> as `  thinking...  response` blocks before saving to history.

---

## How Reasoning is Streamed

The streaming entry point is `Harness._stream_llm_response()` in `harness.py`. Two code paths handle reasoning:

### 1. `reasoning_content` API field

```python
reasoning = getattr(delta, "reasoning_content", None)
if reasoning:
    full_reasoning += reasoning
    yield chunks.Thinking(content=reasoning)
    continue
```

This handles the non-standard `reasoning_content` field that local inference servers (llama.cpp, vLLM) and some cloud APIs (DeepSeek) use to deliver chain-of-thought traces. The reasoning is accumulated into `full_reasoning` **and** yielded to the UI.

### 2. Inline thinking tags in `content` field

The code parses content for embedded thinking tags:

```python
THINKING_TAGS = [
    ("  thinking", "  response"),
    ("<thinking>", "</thinking>"),
]
```

When an opening tag is found in the content stream, content before the tag goes to `chunks.Content` (and is accumulated into `full_content`), while content *between* the tags goes to `chunks.Thinking` **and** is accumulated into `full_reasoning`. The tag delimiters themselves are consumed and discarded.

---

## How the Assistant Message is Saved (with `preserve_reasoning_traces`)

After the stream ends, the assistant message is saved to history. When the flag is enabled:

```python
if pico_cfg.config.preserve_reasoning_traces and full_reasoning:
    reconstructed = f"  thinking\n{full_reasoning}\n  \n\n{full_content}"
    full_content_for_history = reconstructed
else:
    full_content_for_history = full_content if full_content else None

msg = {
    "id": assistant_msg_id,
    "role": "assistant",
    "content": full_content_for_history
}
```

The reasoning content is folded back into the `content` field using DeepSeek-R1-style `  thinking...  response` tags — the de facto standard format understood by most reasoning models. This reconstructed message is what gets saved to `self.history` and re-sent on subsequent turns.

---

## How History is Re-sent to the LLM

On subsequent turns, `_build_messages()` builds the API request:

```python
messages = [system_msg]
messages.extend(self._get_effective_history())  # returns self.history[...]
```

With the flag enabled, each assistant message in history contains its reasoning traces inline, so the model sees its full prior chain-of-thought.

---

## Configuration

Enable via `~/.config/pico-chat/config.toml`:

```toml
[settings]
preserve_reasoning_traces = true
```

The flag defaults to `false` for backward compatibility. Existing users are not affected.

---

## Impact Assessment

| Scenario | Flag Off | Flag On |
|---|---|---|
| **Single-turn interactions** | No issue | No issue |
| **Multi-turn, non-reasoning model** | No issue | No issue (no reasoning to preserve) |
| **Multi-turn, reasoning model (e.g. DeepSeek-R1)** | ❌ Degraded — prior CoT lost | ✅ Reasoning preserved |
| **Tool-calling multi-step** | ⚠️ Moderate — reasoning between calls lost | ✅ Reasoning between calls preserved |

---

## Related

- [architecture.md](../notes/architecture.md) — High-level data flow
- [config.md](../notes/config.md) — Configuration reference
- `chunks.py` — Defines `Thinking` and `Content` chunk types
- `harness.py` — `_stream_llm_response()` and `chat()` methods