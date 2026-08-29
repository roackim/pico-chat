# pico_chat/harness/ — LLM Agent Core

The agent backbone. Manages the LLM conversation loop, tool execution, security checks, context construction, and server management.

Key internal modules: `permission_gate.py` (permission checking), `thinking_parser.py` (thinking-tag state machine), `server_service.py` (server config operations). The `Harness` class in `harness.py` delegates to these.

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
Subagents: instantiated with `depth > 0`; use the `scaffolder` permissions profile automatically.
See [notes/subagents.md](../notes/subagents.md) for the full subagent lifecycle.

### `permission_gate.py`
`PermissionGate` — extracted from `Harness`. Encapsulates:
- File-path inside/outside workspace resolution (deduped from 3 read/write/patch branches)
- Permission checking against the active `ToolPermissionsProfile`
- Direct role-owned enforcement for file inside/outside settings and shell run settings when an active `Role` is present; legacy profile enforcement remains the fallback
- Permission prompt building (`build_prompt()`)
- Async user-response queue for interactive prompts
- Retains the active `Role` so availability and simple/search policies are
	checked from role-owned entries; the converted profile remains for legacy
	file/run enforcement during migration.

### `thinking_parser.py`
`ThinkingTagParser` — extracted from `Harness._stream_llm_response`. Handles two input paths:
- `reasoning_content` API field (DeepSeek/R1 style) — yielded directly
- Inline `<thinking>`/`</thinking>` and `<think>`/`</think>` tags — state machine splits content into thinking/content segments across chunk boundaries
`MetricsState` — periodic `GenerationMetrics` emission helper.

### `server_service.py`
`ServerService` — server management operations extracted from UI commands. Returns structured result dataclasses (`ServerAddResult`, `ServerSwitchResult`, `ServerRemoveResult`, `ServerInfo`, `OpenRouterBalance`). Handles:
- OpenRouter model catalog validation and connection testing
- llama.cpp URL normalisation and connection testing
- TOML config persistence (`set_active_server`, `save_server` dedup)
- OpenRouter credit balance fetching
The UI `commands.py` is now a thin adapter that calls `ServerService` and renders the results.

### `llm_server.py`
`LLMServer` abstract base. Concrete implementations: `LlamaCppServer` (llama.cpp HTTP), `OllamaServer` (Ollama discovery plus OpenAI-compatible chat), `OpenRouterServer` (cloud API), and `OpenAIServer`.

Transport is **raw httpx** (no `openai` SDK): one owned `httpx.AsyncClient` per server, SSE streaming parsed directly, and responses adapted to the previous SDK chunk shape for the harness/UI.
- `stream_chat(messages)` / `create_completion(...)` — yields `Chunk` objects from the LLM stream
- `list_models()` — discovers models exposed by an endpoint via `GET /models`
- `set_model(model_name)` — changes the selected model without replacing the endpoint
- `_resolve_local_hostname(url)` — rewrites `.local` (mDNS) hostnames to a routable IP via `getent` (cached per-host for process lifetime); `invalidate_local_hostname()` drops a stale entry on connect failure so pico retries once against a fresh address. `_resolve_local_hostname_async`/`_resolve_local_hostname_await` are non-blocking variants used by `LLMServer.__init__` and `diagnose_connection()` so an offline `.local` host never blocks the event loop. See [notes/local-hostname-resolution.md](../notes/local-hostname-resolution.md).

### `llm_server_config.py`
`LLMServerConfig` — dataclass for endpoint metadata: name, type, URL, credentials, and legacy/default model selection. `ModelInfo` and `LLMTarget` represent discovered model metadata and an endpoint/model pair.

### `usage.py`
`TokenUsage` and normalization helpers convert OpenAI-compatible and Ollama
usage counters into provider-neutral prompt/completion/total token data.

### `llm_status.py`
`AgentState` enum: `UNCONNECTED`, `IDLE`, `THINKING`, `ANSWERING`.

### `tools.py`
Tool classes: `MinimalToolset` (read/list), `FileTools` (+ write/patch), `ShellTool` (run_command), `SearchTools` (search_web/search_wiki).
`SearchTools` — web search via DuckDuckGo HTML and Wikipedia MediaWiki API. Returns formatted results (title/URL/snippet). Supports time range filtering for DDG.
Pure functions — no internal state. See [notes/tools-and-permissions.md](../notes/tools-and-permissions.md).

`FileTools.read()` supports optional 1-based inclusive line ranges, character
limits with an explicit truncation marker, and source line-number prefixes.

### `tool_wrappers.py`
`*ToolWrapper` classes — adapt tool functions to the OpenAI function-calling JSON schema.

- Each wrapper owns `ToolPolicySpec` metadata describing its policy category,
	default permission, and default settings; `registered_tool_specs()` is the canonical registry view
	consumed when role policy entries are created.
- `get_schema()` — returns function schema for the LLM
- `execute(args)` — parses LLM args and calls the underlying tool

Individual wrappers: `ReadTool`, `WriteTool`, `PatchTool`, `RunTool`, `SearchWebTool`, `SearchWikiTool`, `SubagentTool`, `WaitForSubagentsTool`.

`create_toolset(depth)` — factory that builds the active tool dict. Only registers: `read`, `write`, `patch`, `run_command`, `search_web`, `search_wiki`, `subagent`, `wait_for_subagents`. (Iteration/memory tools are no longer registered here.)

Search wrappers:
- `SearchWebTool` — DuckDuckGo web search with rate limiting
- `SearchWikiTool` — Wikipedia search with rate limiting
Main agent: 3 results/search, unlimited searches. Subagents: 10 results/search, max 3 searches.

Subagent wrappers:
- `SubagentTool` — spawns a read-only child `Harness`; foreground or background mode; enforces depth limit, timeout, and context cap
- `WaitForSubagentsTool` — `asyncio.gather` over all pending background tasks; clears the list on completion
The main permission gate prompts before starting or waiting for delegated work when the active profile requires approval.

### `tool_permissions.py`
`ToolPermissionsProfile` — per-tool policy configuration (`ALLOW` / `ASK` / `DENY`).
`Permission` Literal type; `FilePermissions` and `RunPermissions` dataclasses.
`CMD_DEFAULT_ALLOW` / `CMD_DEFAULT_ASK` / `CMD_DEFAULT_DENY` — command classification sets.
Predefined profiles: `strict`, `permissive`, `unrestricted`, `locked`, `TESTING`, `scaffolder`.
Global `permissions` singleton (defaults to `permissive`).
`get_search_permission()` — returns search operation policy (default: `ALLOW` in permissive/scaffolder profiles).

### `roles.py`
`Role` — conversation-owned operating mode combining enabled tools, tool policies,
and role-specific prompt instructions. Built-in roles include `default`,
`reviewer`, and `researcher`; saved roles use `~/.config/pico-chat/roles.toml`.
- Consecutive role changes are represented by one system history notice; a new
	role notice replaces the previous one until another conversation message is added.
- Role policy entries are derived from registered tool metadata rather than a
	hard-coded `ALL_TOOLS` list; newly registered tools receive a disabled policy
	entry with metadata-owned default settings when loading or constructing a role.
Saved definitions with a built-in name override that built-in in place, while
rename and delete operations still reject built-in names.
`ToolPolicy` describes one tool's availability, default permission, and
tool-specific settings. Roles adapt to the existing `ToolPermissionsProfile`
while the permission system is migrated.

### `security.py`
`SecurityChecker` — evaluates shell commands before execution.
`CommandCheck` result: `ALLOW`, `ASK`, `DENY`.
`CommandAction` — the enum behind `CommandCheck.action`.
`parse_operators(command)` — quote-aware command chain splitting (`|`, `&&`, `||`, `;`).
`check_command(command, permissions)` — single-command check with dangerous-pattern escalation.
`SecurityChecker.check_chain(command)` — uses quote-aware `parse_operators` to detect chains; respects `chain_policy`.
See [notes/security.md](../notes/security.md).

### `context_builder.py`
`build_harness_context()` — constructs the context injected alongside the system prompt.
- Detects git repo root
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
