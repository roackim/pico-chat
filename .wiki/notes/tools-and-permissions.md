# Tools and Permissions

The tool system exposes file and shell operations to the LLM agent. Every tool call goes through a permission gate before execution.

---

## Tool Classes (`tools.py`)

| Class | Operations |
|-------|-----------|
| `MinimalToolset` | Base; read file, list directory |
| `FileTools` | Extends minimal; write file, patch file |
| `ShellTool` | Run shell command |

Tools are pure functions — no internal state. The `Harness` owns all state and passes it in.

## Tool Wrappers (`tool_wrappers.py`)

Each tool class has a corresponding `*ToolWrapper` that adapts it to the OpenAI function-calling schema:
- Generates the JSON schema for the LLM to invoke
- Parses the LLM's tool call arguments
- Calls the underlying tool function
- Returns a formatted result string

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

Dangerous pattern detection can upgrade `ALLOW` → `ASK`. It never downgrades `DENY`.

See [notes/security.md](./security.md) for the security layer details.

## Memory Tools (`memory_tools.py`)

`MemoryTools` provides `memorize` and `forget` operations. Memories persist across turns in the conversation by being injected into the system prompt context. Not file-backed by default — stored in the `Harness` instance.

## Iteration Tools (`iteration_tools.py`)

`IterationTools` provides `loop`, `loop_next`, and `loop_itr_done` — used for multi-step processing over a list of items (e.g., processing multiple files). The LLM drives the loop by calling `loop_next` to advance and `loop_itr_done` to signal completion.

## Subagent Tools (`tool_wrappers.py`)

`SubagentTool` spawns a read-only child `Harness` to explore the codebase and return findings.
`WaitForSubagentsTool` collects results from all queued background subagents.

Subagents always run under the **`scaffolder`** profile: read-only inside the repo, deny everything else. The main agent's permission profile is not inherited.

See [notes/subagents.md](./subagents.md) for the full lifecycle, depth limit, timeout, and config reference.

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
