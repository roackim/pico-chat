# Tools and Permissions

The tool system exposes file and shell operations to the LLM agent. Every tool call goes through a permission gate before execution.

---

## Tool Classes (`tools.py`)

| Class | Operations |
|-------|-----------|
| `MinimalToolset` | Base; read file, list directory |
| `FileTools` | Extends minimal; write file, patch file |
| `ShellTool` | Run shell command |
| `SearchTools` | Web search; DuckDuckGo and Wikipedia |

`ToolError` — exception raised by tool functions on failure.

`read` accepts optional `offset` (zero-based first line) and `limit` (number
of lines) values for targeted reads, `max_chars` for bounded output, and
`include_line_numbers` for stable source references when preparing patches.
The default call remains a complete, unnumbered file read for compatibility.

Tools are pure functions — no internal state. The `Harness` owns all state and passes it in.

## Tool Wrappers (`tool_wrappers.py`)

Each tool class has a corresponding `*ToolWrapper` that adapts it to the OpenAI function-calling schema:
- Generates the JSON schema for the LLM to invoke
- Parses the LLM's tool call arguments
- Calls the underlying tool function
- Returns a formatted result string

Individual wrappers: `ReadTool`, `WriteTool`, `PatchTool`, `RunTool`, `SearchWebTool`, `SearchWikiTool`, `SubagentTool`, `WaitForSubagentsTool`.

`create_toolset(depth)` — factory that builds the active tool dict. Only registers: `read`, `write`, `patch`, `run`, `search_web`, `search_wiki`, `subagent`, `wait_for_subagents`. (Iteration/memory tools are no longer registered.)

This adapter layer keeps `tools.py` decoupled from any specific LLM API format.

## Permission Flow

```
LLM generates tool call
        ↓
ToolWrapper.parse_call()
        ↓
ToolPermissionsProfile.check(tool, args)
        ↓
SecurityChecker.check_command()   ← for shell commands
        ↓
  DENY → blocked, error returned to LLM
  ASK  → UI shows permission prompt, awaits user response
  ALLOW→ tool.execute(args)
        ↓
result appended to conversation history
```

## ToolPermissionsProfile (`tool_permissions.py`)

Configuration object specifying the default policy per tool type. Policies: `ALLOW`, `ASK`, `DENY`.

Predefined profiles: `strict`, `permissive` (default global singleton), `unrestricted`, `locked`, `TESTING`, `scaffolder` (used by subagents).

Dangerous pattern detection can upgrade `ALLOW` → `ASK`. It never downgrades `DENY`.

See [notes/security.md](./security.md) for the security layer details.

## Iteration Tools (`iteration_tools.py`)

**Removed.** Previously provided `loop`, `loop_next`, `loop_itr_done` — was dead code and has been deleted.

## Subagent Tools (`tool_wrappers.py`)

`SubagentTool` spawns a read-only child `Harness` to explore the codebase and return findings.
`WaitForSubagentsTool` collects results from all queued background subagents.

Subagents always run under the **`scaffolder`** profile: read-only inside the repo, deny everything else. The main agent's permission profile is not inherited.

See [notes/subagents.md](./subagents.md) for the full lifecycle, depth limit, timeout, and config reference.

## Search Tools (`tools.py`, `tool_wrappers.py`)

`SearchTools` provides two web search operations:

**`search_web(query, max_results, time_range)`** — DuckDuckGo HTML search
- Parses HTML results (title/URL/snippet) via regex
- Optional time range filter: `"day"`, `"week"`, `"month"`, `"year"`
- Use for: library docs, API references, news, troubleshooting, technical queries

**`search_wiki(query, max_results)`** — Wikipedia MediaWiki API
- Returns structured JSON results from Wikipedia search
- Use for: named entities, concepts, algorithms, historical events

**Rate limiting** (enforced in wrappers):
- Main agent (depth=0): 3 results per search, unlimited searches
- Subagents (depth>0): 10 results per search, max 3 searches

Rationale: Subagents return only their final summary to the main context, so they can research deeply (10 results × 3 searches = 30 total results) without polluting the main conversation. Main agent uses smaller result sets to keep context clean.

**Permissions**: Search operations default to `ALLOW` (safe read-only external API calls). Configurable per profile. Subagents (`scaffolder` profile) can search to enable library research.

## Patch Tool (`patch_parser.py`)

File edits use an aider-style search/replace block format:
```
<<<<<<< SEARCH
old content
=======
new content
>>>>>>> REPLACE
```

`parse_patch()` extracts blocks, `apply_patch()` applies them to the file. Strict match — fails if `SEARCH` block does not match exactly.
