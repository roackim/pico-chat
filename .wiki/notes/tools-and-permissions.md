# Tools and Permissions

The tool system exposes file and shell operations to the LLM agent. Every tool
call goes through the approval gate before execution.

pico implements **no sandbox** — there is no permission engine, no command
allowlist, no path confinement, and no container code. A tool is either disabled,
asks, or auto-approves. Isolation (a container, VM, `bubblewrap`, …) is the
user's responsibility; see `.wiki/notes/principles.md` and
`plans/containerization.md`.

---

## Tool Classes (`tools.py`)

| Class | Operations |
|-------|-----------|
| `MinimalToolset` | Base; read file, list directory |
| `FileTools` | Extends minimal; write file, patch file |
| `ShellTool` | Run shell command |

`ToolError` — exception raised by tool functions on failure.

`read` accepts optional `offset` (zero-based first line) and `limit` (number
of lines) values for targeted reads, `max_chars` for bounded output, and
`include_line_numbers` for stable source references when preparing patches.
The default call remains a complete, unnumbered file read for compatibility.

Tools are pure functions — no internal state. The `Harness` owns all state and
passes it in. The tool layer never checks permissions itself; the gate decides
before a tool runs.

## Tool Registry (`tools.py`)

Each tool is declared once with the `@tool` decorator, which carries its name,
OpenAI function schema, and handler:

- `ToolDefinition` / `ToolContext` / `RegisteredTool` — registry record and the
  bound instance returned to the harness.
- `get_schema()` — returns the function schema for the LLM.
- `execute()` / `execute_async()` — dispatch to the handler (async tools expose
  a coroutine `execute`; cancellable tools add `execute_async`).

`registered_tool_names()` is the canonical registry view: the list of tool
names a role file lists.

`create_toolset(workspace_path, depth, pending_subagents)` — factory that binds
registered tools to a context. Registers: `read`, `write`, `patch`,
`run_command` (LLM name `run`), `subagent` (depth permitting),
`wait_for_subagents`. Public factories `RunTool`, `SubagentTool`,
`WaitForSubagentsTool` remain for direct construction.

## Approval Flow

```
LLM generates tool call
        ↓
Harness._execute_tool_calls()
        ↓
PermissionGate.check(tool, args)          ← the single decision point
        ↓
  role's per-tool value: no → deny · ask → prompt · yes → allow
        ↓
  deny → blocked, error returned to LLM
  ask  → UI shows permission prompt, awaits user response
  allow→ RegisteredTool.execute(args)
        ↓
result appended to conversation history
```

## Roles (`roles.py`, `permissions.py`)

`Role` is the single source of truth for a conversation's enabled tools and
per-tool approval setting:

- Each tool is exactly one of `no` / `ask` / `yes`:
  - `no` — disabled; **not put in `tool_schemas`**, so the model never sees it.
  - `ask` — enabled; the harness prompts before the call.
  - `yes` — enabled; runs without prompting.
- There is no `deny`: a tool you would always deny is simply `no`.
- `enabled_tool_names()` returns every value except `no`; `permission_for(name)`
  returns the raw value.

`PermissionGate` (`permissions.py`) maps the value to the harness decision
(`allow` / `ask` / `deny`), builds the prompt (`build_prompt()`), and owns the
async queue the UI uses to deliver the user's answer on the `ask` path.

### Role files

One file per role at `<config>/roles/<name>.toml`. The file name is the role
name; the body is `description` / `prompt` plus one `<tool> = "no" | "ask" |
"yes"` entry per registered tool. The file lists every available tool so the
user can comment/uncomment or edit values — the "all options visible" style of
`servers.toml`.

Built-in roles (`agent`, `chat`) are seeded as files on first run by
`ensure_roles_dir()`; a code fallback exists for `agent` and `chat`. `scaffolder`
is a read-only built-in used by subagents and is not user-selectable.
`create_role(name)` writes a template from the registry (all tools `no`);
`delete_role(name)` unlinks the file, refusing to remove the last role.

Unknown tool names and values other than `no`/`ask`/`yes` are reported as
`roles/<name>.toml: ...` by `validate_roles()`, surfaced by `/reload` and
`/config role`.

### Command surface

| Command | Behavior |
|---------|----------|
| `/role` | list roles, mark the active one |
| `/role <name>` | switch the active role |
| `/config role <id>` | ensure the file exists, open in `$EDITOR`, reload |
| `/config role delete <id> [confirm]` | confirm, then unlink |

## Subagent Tools (`tools.py`)

The `subagent` registry tool spawns a read-only child `Harness` to explore the
codebase and return findings.
`wait_for_subagents` collects results from all queued background subagents.

Subagents always run under the **`scaffolder`** role: `read`/`subagent`/
`wait_for_subagents` enabled, everything else `no`. The main agent's role is
not inherited.

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
