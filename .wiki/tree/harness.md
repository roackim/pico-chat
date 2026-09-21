# pico_chat/harness/ — LLM Agent Core

The agent backbone. Manages the LLM conversation loop, tool execution, security checks, context construction, and server management.

Key internal modules: `permissions.py` (the single permission decision point), `thinking_parser.py` (thinking-tag state machine), `endpoint.py` (one type for endpoint config + transport), `events.py` (the one harness→UI event protocol). The `Harness` class in `harness.py` delegates to these.

See [notes/architecture.md](../notes/architecture.md), [notes/tools-and-permissions.md](../notes/tools-and-permissions.md), and [notes/reasoning-traces.md](../notes/reasoning-traces.md) for conceptual details.

---

## Files

### `harness.py`
`Harness` — main class. Owns the agent state machine and conversation history.
- `chat(user_input)` — async generator; full agent turn (stream → handle tool calls)
- `_stream_llm_response()` — delegates thinking-tag parsing to `ThinkingTagParser`
- `_execute_tool_calls()` — delegates permission checking to `PermissionGate`
- `_auto_wait_subagents()` — awaits pending background subagents after the main loop ends (no events)
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
- `reasoning_content` API field (DeepSeek/R1 style) — yielded directly as `events.Reasoning`
- Inline `<thinking>`/`</thinking>` and `<think>`/`</think>` tags — state machine splits content into `events.Reasoning`/`events.Token` segments across chunk boundaries
`MetricsState` — periodic `events.Usage` emission helper.

### `events.py`
The one harness→UI event protocol. A single union yielded by `Harness.chat()`:
`Start`, `Token`, `Reasoning`, `ToolCall`, `PermissionRequest`, `ToolResult`
(`outcome` = completed/denied/error), `Usage`, `Error`, `Done`.
The harness yields events; the UI renders them. There is no separate chunk/status type.
The former unused `SubagentsWaiting`/`SubagentResult`/`SubagentsDone` events were removed.

### `endpoint.py`
`Endpoint` — **one concrete type** holding connection config *and* the live
transport (httpx client, caches, selected model, connection state). No ABC or
subclasses; server-family differences are internal branches:
- `llamacpp` — single model from `/models[0]`, context via `/props`, ignores per-request model
- `ollama` — native `/api/tags`, `/api/show`, native `/api/chat` (usage counters)
- `openrouter` — enabled-models allowlist, per-model provider routing
- `openai` — configured model + known context-window table
`Endpoint.from_dict(name, data)` reads a `[servers.<name>]` table and resolves
`api_key_env`; `to_dict()` strips secrets. Also hosts `ModelInfo`,
`ConnectionDiagnosis`, and `.local` hostname resolution helpers. Factories:
`get_active_endpoint()`, `get_endpoint(name)`, `default_endpoint()`.
`Harness.endpoint` is an `Endpoint`. See [notes/local-hostname-resolution.md](../notes/local-hostname-resolution.md).

This one type replaced the former `LLMServerConfig` + `ServerService` +
`LLMServer` ABC/four-subclass split (`llm_server.py`, `llm_server_config.py`,
`server_service.py` are deleted). The UI `commands/` package calls into
`endpoint.py` and `pico_cfg` directly.

### `usage.py`
`TokenUsage` and normalization helpers convert OpenAI-compatible and Ollama
usage counters into provider-neutral prompt/completion/total token data.

### `llm_status.py`
`AgentState` enum: `UNCONNECTED`, `IDLE`, `THINKING`, `ANSWERING`.

### `tools.py`
Low-level tool implementations plus the tool registry.
- `MinimalToolset` (read/list), `FileTools` (+ write/patch), `ShellTool` (run_command).
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
	`subagent` (depth-permitting), `wait_for_subagents`.
- Public factories `RunTool`, `SubagentTool`, `WaitForSubagentsTool` remain
	for direct construction/tests.

Search tools: main agent 3 results/search, unlimited searches. Subagents
10 results/search, max 3 searches. Subagent tool spawns a read-only child
`Harness` (foreground or background) and enforces depth/timeout/context limits;
`wait_for_subagents` gathers and clears the pending queue.

See [notes/tools-and-permissions.md](../notes/tools-and-permissions.md).

### `roles.py`
`Role` — the single source of truth for a conversation's operating mode:
enabled tools, tool policies, and role-specific prompt. Built-in roles include
`default`, `reviewer`, `researcher`, and the read-only `scaffolder` used by
subagents; saved roles use one file per role at `~/.config/pico-chat/roles/<name>.toml`.
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

### `debug.py`
`DebugStream` — structured debug logging to JSON. Used for dev; not active in production builds.
