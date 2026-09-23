# Architecture

Pico is a terminal-based AI agent that connects to local (llama.cpp) or cloud (OpenRouter, OpenAI) LLMs, exposes file and shell tools to the agent, and presents a custom TUI chat interface.

---

## High-Level Layers

```
┌─────────────────────────────┐
│         pico_chat/ui/       │  TUI — user input, chat display, commands
│  app.py  ← commands/        │
│  chat_history_panel.py      │
│  chat_action_handlers.py    │
└────────────┬────────────────┘
             │ async messages / callbacks
┌────────────▼────────────────┐
│      pico_chat/harness/     │  Agent core — LLM loop, tools, security
│  harness.py (main loop)     │
│  llm_server.py              │
│  tools.py (registry)        │
│  permissions.py             │
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
2. Send to the active `Endpoint` (`endpoint.py`)
3. Stream response events (`events.py`): `Token`/`Reasoning`/`ToolCall`/`Usage`
4. If tool calls present → `PermissionRequest` → check permissions → execute tools → `ToolResult`
5. Append tool results to history → repeat from step 2 until no more tool calls → `Done`

## Data Flow: User Message → Response

```
User types → InputComponent
           → chatTUI.handle_submit()
           → Harness.chat()
           → Endpoint.create_completion()
           → events yielded → UI renders streaming tokens
           → tool call detected → PermissionGate checks the active role's per-tool setting
           → tool executed → result appended to history
           → next iteration until IDLE
```

## Config

`~/.config/pico-chat/` — single-concern files (`ui.toml`, `context.toml`,
`subagents.toml`, `debug.toml`, `styles.toml`, `servers.toml`), one role per
file at `roles/<name>.toml`, and a disposable `state.toml`; loaded by
`pico_cfg.py`. See [notes/config.md](./config.md).

## Key Design Decisions

- **Custom TUI** — no curses or third-party TUI library; full control over rendering pipeline
- **Streaming-first** — LLM output streams token-by-token to the buffer; no waiting for full response
- **Approval gate** — every tool call goes through `PermissionGate` (`permissions.py`), which maps the active role's per-tool setting (`no`/`ask`/`yes`) to a decision before execution; the UI can pause to ask the user
- **Stateless tools** — tools are pure functions; harness owns all state
- **Service layer** — server management and OpenRouter API calls are in `harness/server_service.py`; UI commands are thin adapters- **Model selection is `(server, model)`** — the unit of selection is a server/model pair. `/model <model>` refreshes discovery live, resolves a model across all servers, verifies the chosen server serves it, then switches the harness and selects it. Per-server model choices persist in `[model_selection]` and are reapplied by `get_server_config_by_name`, so switching back restores the last model used on that server. The discovery catalog persists in `[model_catalog]` and is pruned when a server is removed. OpenRouter models are disabled by default unless listed in `enabled_models`. The status bar shows the model that will actually be sent (`_cached_model_name`, reconciled with single-model endpoints such as llama.cpp), not merely the requested selection.- **Thinking-tag parsing** — the thinking-tag state machine is in `harness/thinking_parser.py` for testability; handles both `<think>`/`</think>` and `<thinking>`/`</thinking>` across chunk boundaries;

## Module Relationships

```
pico_chat/
  harness/
    harness.py           ← Orchestrator (delegates to modules below)
    permissions.py       ← Single decision point: PermissionGate (role no/ask/yes → deny/ask/allow)
    thinking_parser.py   ← Thinking-tag state machine + metrics emission
    server_service.py    ← Server config CRUD + model discovery/selection + OpenRouter API (used by commands/)
    tools.py             ← Tool implementations + @tool registry (read/write/patch/run/subagent)
    roles.py             ← Role (prompt + per-tool no/ask/yes; single source of truth)
    llm_server.py        ← LLMServer ABC + concrete impls (llama.cpp, OpenRouter, OpenAI)
    llm_server_config.py ← LLMServerConfig dataclass + config loading
    ...

  ui/
    commands/            ← Slash commands package (builtins.py registry, server.py, models.py, ...)
    chat_action_handlers.py
    app.py               ← Main TUI class
    tui/
      ...
```
