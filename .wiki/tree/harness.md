# pico_chat/harness/ — LLM Agent Core

The agent backbone. Manages the LLM conversation loop, tool execution, security checks, context construction, and memory.

See [notes/architecture.md](../notes/architecture.md) and [notes/tools-and-permissions.md](../notes/tools-and-permissions.md) for conceptual details.

---

## Files

### `harness.py`
`Harness` — main class. Owns the agent state machine and conversation history.
- `chat(user_input)` — async generator; full agent turn (stream → handle tool calls)
- `abort_subagents()` — signals the abort event to cancel waiting background subagents
- `_check_tool_permission(tool, args)` — permission gate; returns `"allow"` / `"ask"` / `"deny"`
- `_auto_wait_subagents()` — drains pending background subagents after the main loop ends
Key state: `AgentState` enum, message history list, active server, tool profile, `_pending_subagents` list, `_abort_subagents_event`.
Subagents: instantiated with `depth > 0`; use the `scaffolder` permissions profile automatically.
See [notes/subagents.md](../notes/subagents.md) for the full subagent lifecycle.

### `llm_server.py`
`LLMServer` abstract base. Concrete implementations: `LlamaServer` (llama.cpp HTTP), `OpenRouterServer` (cloud API).
- `stream_chat(messages)` — yields `Chunk` objects from the LLM stream

### `llm_server_config.py`
`LLMServerConfig` — dataclass for server metadata: name, type, URL, model, context window size.

### `llm_status.py`
`AgentState` enum: `UNCONNECTED`, `IDLE`, `THINKING`, `ANSWERING`.

### `tools.py`
Tool classes: `MinimalToolset` (read/list), `FileTools` (+ write/patch), `ShellTool` (run).
Pure functions — no internal state. See [notes/tools-and-permissions.md](../notes/tools-and-permissions.md).

### `tool_wrappers.py`
`*ToolWrapper` classes — adapt tool functions to the OpenAI function-calling JSON schema.
- `get_schema()` — returns function schema for the LLM
- `execute(args)` — parses LLM args and calls the underlying tool

Subagent wrappers:
- `SubagentTool` — spawns a read-only child `Harness`; foreground or background mode; enforces depth limit, timeout, and context cap
- `WaitForSubagentsTool` — `asyncio.gather` over all pending background tasks; clears the list on completion

### `tool_permissions.py`
`ToolPermissionsProfile` — per-tool policy configuration (`ALLOW` / `ASK` / `DENY`).
Permission constants and chain policy definitions.

### `security.py`
`SecurityChecker` — evaluates shell commands before execution.
`CommandCheck` result enum: `ALLOW`, `ASK`, `DENY`.
Detects: dangerous patterns (find -exec, awk system, sed /e, eval) and chain operators (`;`, `&&`, `||`, `|`).
See [notes/security.md](../notes/security.md).

### `context_builder.py`
`build_harness_context()` — constructs the context injected alongside the system prompt.
- Detects git repo root
- Builds file tree (with guardrails to avoid huge trees)
- Returns structured context string

### `system_prompt.py`
`get_system_message()` — returns the agent's system prompt string. Defines agent behavior, tool usage instructions, and output format rules.

### `memory_tools.py`
`MemoryTools` — `memorize(key, value)` and `forget(key)`.
Memories are stored in the `Harness` instance and injected into the system prompt context on each turn.

### `iteration_tools.py`
`IterationTools` — loop/loop_next/loop_itr_done tools for LLM-driven multi-step iteration over item lists.

### `patch_parser.py`
`PatchBlock` — parsed representation of a search/replace block.
`parse_patch(text)` — extracts all blocks from LLM output.
`apply_patch(filepath, blocks)` — applies blocks to the file; strict match required.
Format: aider-style `<<<<<<< SEARCH / ======= / >>>>>>> REPLACE`.

### `chunks.py`
`Chunk` base class and subtypes for streaming: `MessageStart`, `TextChunk`, `ToolCallChunk`, `MessageEnd`.
`ToolStatus` enum for tool execution state.

### `token_estimation.py`
`estimate_tokens(text)` — fast heuristic (no tokenizer dependency).
`_calculate_code_ratio(text)` — detects code-heavy content for adjusted estimates.

### `debug.py`
`DebugStream` — structured debug logging to JSON. Used for dev; not active in production builds.
