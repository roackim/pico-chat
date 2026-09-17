# pico_chat/harness/ — LLM Agent Core

The agent backbone. Manages the LLM conversation loop, tool execution, security checks, context construction, and server management.

Key internal modules: `permissions.py` (the single permission decision point), `thinking_parser.py` (thinking-tag state machine), `server_service.py` (server config operations). The `Harness` class in `harness.py` delegates to these.

See [notes/architecture.md](../notes/architecture.md), [notes/tools-and-permissions.md](../notes/tools-and-permissions.md), and [notes/reasoning-traces.md](../notes/reasoning-traces.md) for conceptual details.

---

## Files

### `harness.py`
`Harness` — main class. Owns the agent state machine and conversation history.
- `chat(user_input)` — async generator; full agent turn (stream → handle tool calls)
- `_stream_llm_response()` — delegates thinking-tag parsing to `ThinkingTagParser`
- `_execute_tool_calls()` — delegates permission checking to `PermissionGate`
- `_auto_wait_subagents()` — drains pending background subagents after the main loop ends
Key state: `AgentState` enum, message history list, active server, tool profile, `_pending_subagents` list, `_abort_subagents_event`, and thinking steering state (`_current_reasoning`, `_pending_thinking_prefill`, `_last_detected_thinking_tag`) initialized during construction.
Subagents: instantiated with `depth > 0`; use the `scaffolder` built-in role automatically.
See [notes/subagents.md](../notes/subagents.md) for the full subagent lifecycle.

### `permissions.py`
The single "may I run this?" decision point. Merges the former `security.py`,
`tool_permissions.py` and `permission_gate.py`.
- `PermissionGate` — extracted from `Harness`. Resolves file-path inside/outside
  workspace, checks the active `Role` (or a low-level `ToolPermissionsProfile`
  fallback), builds permission prompts (`build_prompt()`), and owns the async
  user-response queue. The active `Role` is authoritative; no Role↔profile
  translation layer exists.
- `SecurityChecker` — quote-aware command-chain parsing and allowlist checks.
  `classify(command)` returns a typed `CommandAction` (used by the gate), while
  `check_chain()` keeps the interactive-confirmation path for direct execution.
- Policy primitives: `Permission`, `FilePermissions`, `RunPermissions`,
  `ToolPermissionsProfile`, command lists (`CMD_DEFAULT_*`,
  `CMD_DANGEROUS_PATTERNS`) and predefined low-level profiles (`strict`,
  `permissive`, `unrestricted`, `locked`, `TESTING`, `scaffolder`).
- Adapters (`file_permission`, `resolve_run_permissions`, `search_permission`)
  let tools and the gate consume either a `Role` or a profile without a
  Role↔profile conversion method.
See [notes/security.md](../notes/security.md) and
[notes/tools-and-permissions.md](../notes/tools-and-permissions.md).

### `thinking_parser.py`
`ThinkingTagParser` — extracted from `Harness._stream_llm_response`. Handles two input paths:
- `reasoning_content` API field (DeepSeek/R1 style) — yielded directly
- Inline `<thinking>`/`</thinking>` and `<think>`/`</think>` tags — state machine splits content into thinking/content segments across chunk boundaries
`MetricsState` — periodic `GenerationMetrics` emission helper.

### `server_service.py`
`ServerService` — server management operations extracted from UI commands. Returns structured result dataclasses (`ServerAddResult`, `ServerSwitchResult`, `ServerRemoveResult`, `ServerInfo`, `OpenRouterBalance`). Handles:
- OpenRouter model catalog validation, connection testing, and balance fetching
- Model discovery: `discover_models()` (per endpoint), `discover_all_models()` (live, every reachable server), `list_models()` (cache the catalog)
- Per-server model selection: `select_model(model, server)` persists the choice to `config.model_selection` and makes that server the active one
- Catalog helpers for the UI: `all_models()` (server-annotated `ModelInfo`), `model_completions()` (fuzzy completion ids), `resolve_model_servers(model)` (which servers serve a model). These ignore servers no longer present in `config.servers`, and `remove_server`/`discover_all_models` prune their stale catalog entries.
- `set_enabled_models()` invalidates the server's cached catalog so a changed OpenRouter allowlist is re-discovered (previously the old catalog lingered).
- llama.cpp URL normalisation and connection testing
- TOML config persistence (`_set_active_server_in_toml`, `save_server` dedup)
- `add_ollama` discovers and caches the full catalog instead of hardcoding the first model
The UI `commands/` package is now a thin adapter that calls `ServerService` and renders the results.

### `llm_server.py`
`LLMServer` abstract base. Concrete implementations: `LlamaCppServer` (llama.cpp HTTP), `OllamaServer` (Ollama discovery plus OpenAI-compatible chat), `OpenRouterServer` (cloud API), and `OpenAIServer`.

Transport is **raw httpx** (no `openai` SDK): one owned `httpx.AsyncClient` per server, SSE streaming parsed directly, and responses adapted to the previous SDK chunk shape for the harness/UI.
- `stream_chat(messages)` / `create_completion(...)` — yields `Chunk` objects from the LLM stream
- `list_models()` — discovers models exposed by an endpoint via `GET /models`
- `discover_models()` — like `list_models` but optionally enriches metadata. `OllamaServer.discover_models()` enriches each model with its context window via `/api/show`; `OpenRouterServer.discover_models()` returns **only explicitly-enabled models** (see `enabled_models`).
- `supports_model_selection` — class flag. `False` for `LlamaCppServer` because llama.cpp loads one model and ignores the request's `model` field.
- `set_model(model_name)` — changes the selected model without replacing the endpoint. On a single-model endpoint this drops the cached claim so the next probe resolves the actually-served model instead of displaying a selection that is ignored.
- `prewarm_model_name()` — probes the connection via `diagnose_connection()` so the status bar turns green, then caches model name/context. It no longer early-returns when a model is already cached; it always probes the endpoint so selecting a model marks it online. For single-model endpoints it reconciles the displayed/requested model with the model the server actually serves.
- `_resolve_local_hostname(url)` — rewrites `.local` (mDNS) hostnames to a routable IP via `getent` (cached per-host for process lifetime); `invalidate_local_hostname()` drops a stale entry on connect failure so pico retries once against a fresh address. `_resolve_local_hostname_async`/`_resolve_local_hostname_await` are non-blocking variants used by `LLMServer.__init__` and `diagnose_connection()` so an offline `.local` host never blocks the event loop. See [notes/local-hostname-resolution.md](../notes/local-hostname-resolution.md).

### `llm_server_config.py`
`LLMServerConfig` — dataclass for endpoint metadata: name, type, URL, credentials, legacy/default model selection, and `enabled_models` (OpenRouter allowlist — all models disabled unless explicitly listed). `ModelInfo` represents discovered model metadata (with `size`/`family`/`modified_at` accessors and `to_dict`/`from_dict` for the catalog), `ModelRef` is a `(server, model)` pair addressable for selection, and `LLMTarget` represents an endpoint/model pair. `get_server_config()` and `get_server_config_by_name()` both resolve the per-server model selection, so switching to a server restores the model last selected on it.

### `usage.py`
`TokenUsage` and normalization helpers convert OpenAI-compatible and Ollama
usage counters into provider-neutral prompt/completion/total token data.

### `llm_status.py`
`AgentState` enum: `UNCONNECTED`, `IDLE`, `THINKING`, `ANSWERING`.

### `tools.py`
Low-level tool implementations plus the tool registry.
- `MinimalToolset` (read/list), `FileTools` (+ write/patch), `ShellTool` (run_command), `SearchTools` (search_web/search_wiki).
- `SearchTools` — web search via DuckDuckGo HTML and Wikipedia MediaWiki API. Returns formatted results (title/URL/snippet). Supports time range filtering for DDG.
- `ToolError` — raised by tool functions on failure.

`FileTools.read()` supports optional 1-based inclusive line ranges, character
limits with an explicit truncation marker, and source line-number prefixes.

**Tool registry** — each tool is declared once with the `@tool` decorator,
which carries its name, LLM-facing schema, `ToolPolicySpec` (permission +
settings) and handler. There is no separate `tool_wrappers.py`.
- `ToolDefinition` / `ToolContext` / `RegisteredTool` — registry records and
	bound instances. `get_schema()` returns the OpenAI function schema;
	`execute()` / `execute_async()` dispatch to the handler.
- `registered_tool_specs()` — canonical policy registry view consumed when role
	policy entries are created.
- `create_toolset(depth)` — factory that binds registered tools to a context.
	Registers: `read`, `write`, `patch`, `run_command` (LLM name `run`),
	`search_web`, `search_wiki`, `subagent` (depth-permitting),
	`wait_for_subagents`.
- Public factories `RunTool`, `SearchWebTool`, `SearchWikiTool`,
	`SubagentTool`, `WaitForSubagentsTool` remain for direct construction/tests.

Search tools: main agent 3 results/search, unlimited searches. Subagents
10 results/search, max 3 searches. Subagent tool spawns a read-only child
`Harness` (foreground or background) and enforces depth/timeout/context limits;
`wait_for_subagents` gathers and clears the pending queue.

See [notes/tools-and-permissions.md](../notes/tools-and-permissions.md).

### `roles.py`
`Role` — the single source of truth for a conversation's operating mode:
enabled tools, tool policies, and role-specific prompt. Built-in roles include
`default`, `reviewer`, `researcher`, and the read-only `scaffolder` used by
subagents; saved roles use `~/.config/pico-chat/roles.toml`.
- Consecutive role changes are represented by one system history notice; a new
	role notice replaces the previous one until another conversation message is added.
- Role policy entries are derived from registered tool metadata rather than a
	hard-coded list; newly registered tools receive a disabled policy entry with
	metadata-owned default settings.
- No `from_permission_profile` / `to_permission_profile` translation layer
	exists; the permission primitives adapt to a `Role` directly.
Saved definitions with a built-in name override that built-in in place, while
rename and delete operations still reject built-in names.
`ToolPolicy` describes one tool's availability, default permission, and
tool-specific settings.

### `context_builder.py`
`build_harness_context()` — constructs the context injected alongside the system prompt.
- Builds the file tree regardless of git status (outside a git repo there is no `.gitignore`, so the whole directory is listed — this keeps the `@` file picker working everywhere)
- `list_files_bounded()` — breadth-first, depth/max-files-bounded walk used by the `@` file picker so it stays responsive on huge trees (e.g. `$HOME`); respects `.gitignore` unless `ignore_gitignore` is set
- Builds file tree (with guardrails to avoid huge trees)
- Injects current date and time
- Returns structured context string

### `system_prompt.py`
`get_system_message()` — returns the agent's system prompt string. Defines agent behavior, tool usage instructions, and output format rules.

### `patch_parser.py`
`PatchBlock` — parsed representation of a search/replace block.
`parse_patch(text)` — extracts filename, search/replace text from aider-style markers.
`apply_patch(content, patch)` — applies a patch with 3-mode cascade: exact → whitespace-normalized → indentation-normalized.
`PatchParseError` — raised on invalid patch format.

### `chunks.py`
`Chunk` base class and subtypes for streaming: `MessageStart`, `TextChunk`, `ToolCallChunk`, `MessageEnd`.
`ToolStatus` enum for tool execution state.

### `token_estimation.py`
`estimate_tokens(text)` — fast heuristic (no tokenizer dependency).
`_calculate_code_ratio(text)` — detects code-heavy content for adjusted estimates.

### `debug.py`
`DebugStream` — structured debug logging to JSON. Used for dev; not active in production builds.
