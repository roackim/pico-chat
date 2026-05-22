# Architecture

Pico is a terminal-based AI agent that connects to local (llama.cpp) or cloud (OpenRouter, OpenAI) LLMs, exposes file and shell tools to the agent, and presents a custom TUI chat interface.

---

## High-Level Layers

```
┌─────────────────────────────┐
│         pico_chat/ui/       │  TUI — user input, chat display, commands
│  app.py  ← commands.py      │
│  chat_history_panel.py      │
│  chat_action_handlers.py    │
└────────────┬────────────────┘
             │ async messages / callbacks
┌────────────▼────────────────┐
│      pico_chat/harness/     │  Agent core — LLM loop, tools, security
│  harness.py (main loop)     │
│  llm_server.py              │
│  tools.py + tool_permissions│
│  security.py                │
└────────────┬────────────────┘
             │ HTTP / websocket
┌────────────▼────────────────┐
│     LLM Backend             │  llama.cpp server or OpenRouter/OpenAI API
└─────────────────────────────┘
```

## Entry Point

`pico_chat/main.py` — async launcher that:
1. Loads config via `pico_cfg.py`
2. Instantiates `Harness` and `chatTUI`
3. Starts the async TUI event loop

## Agent Loop (`harness.py`)

The core reasoning loop:
1. Build context (system prompt + conversation history + file tree)
2. Send to LLM (`llm_server.py`)
3. Stream response chunks (`chunks.py`)
4. If tool calls present → check permissions → execute tools
5. Append tool results to history → repeat from step 2 until no more tool calls

## Data Flow: User Message → Response

```
User types → InputComponent
           → chatTUI.handle_submit()
           → Harness.run_iteration()
           → LLMServer.stream_chat()
           → chunks yielded → UI renders streaming tokens
           → tool call detected → ToolPermissionsProfile checks policy
           → tool executed → result appended to history
           → next iteration until IDLE
```

## Config

`~/.config/pico-chat/config.toml` loaded by `pico_cfg.py`. Contains server definitions, UI preferences, and permission defaults. See [notes/config.md](./config.md).

## Key Design Decisions

- **Custom TUI** — no curses or third-party TUI library; full control over rendering pipeline
- **Streaming-first** — LLM output streams token-by-token to the buffer; no waiting for full response
- **Permission gate** — every tool call goes through `ToolPermissionsProfile` before execution; the UI can pause to ask the user
- **Stateless tools** — tools are pure functions; harness owns all state
