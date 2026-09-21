# Tools and Permissions

The tool system exposes file and shell operations to the LLM agent. Every tool call goes through a permission gate before execution.

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

Tools are pure functions — no internal state. The `Harness` owns all state and passes it in.

## Tool Registry (`tools.py`)

Each tool is declared once with the `@tool` decorator, which carries its name,
OpenAI function schema, `ToolPolicySpec` metadata (policy category, default
permission, default settings) and its handler:

- `ToolDefinition` / `ToolContext` / `RegisteredTool` — registry record and the
  bound instance returned to the harness.
- `get_schema()` — returns the function schema for the LLM.
- `execute()` / `execute_async()` — dispatch to the handler (async tools expose
  a coroutine `execute`; cancellable tools add `execute_async`).

`registered_tool_specs()` is the canonical policy registry view consumed when
role policy entries are created.

`create_toolset(depth)` — factory that binds registered tools to a context.
Registers: `read`, `write`, `patch`, `run_command` (LLM name `run`),
`subagent` (depth permitting), `wait_for_subagents`. Public factories `RunTool`,
`SubagentTool`, `WaitForSubagentsTool` remain for direct construction.

## Permission Flow

```
LLM generates tool call
        ↓
Harness._execute_tool_calls()
        ↓
PermissionGate.check(tool, args)          ← the single decision point
        ↓
  role policy (or profile fallback); shell commands via SecurityChecker.classify()
        ↓
  DENY → blocked, error returned to LLM
  ASK  → UI shows permission prompt, awaits user response
  ALLOW→ RegisteredTool.execute(args)
        ↓
result appended to conversation history
```

## Roles and policy (`roles.py`, `permissions.py`)

`Role` is the single source of truth for a conversation's enabled tools, tool
policies, and prompt. Policies: `ALLOW`, `ASK`, `DENY`.

Low-level `ToolPermissionsProfile` / `FilePermissions` / `RunPermissions`
remain in `permissions.py` as execution helpers and defaults, with predefined
profiles: `strict`, `permissive` (default global singleton), `unrestricted`,
`locked`, `TESTING`, `scaffolder`.

### Role editor

`RoleEditorModel` (`pico_chat/ui/role_editor_model.py`) is the UI-safe boundary
for role lifecycle changes, and `RoleEditorForm`
(`pico_chat/ui/role_editor_form.py`) wires it to the form fields. The settings
tab (`settings_pages.build_roles_fields`) and the `/permissions` popup command
build the *same* fields, so the two surfaces cannot drift. The old
permission-profile editor (`ProfileEditorModel`) and the
`permission-profiles.toml` store have been removed — roles are the only model.

Dangerous pattern detection can upgrade `ALLOW` → `ASK`. It never downgrades `DENY`.

See [notes/security.md](./security.md) for the security layer details.

## Iteration Tools (`iteration_tools.py`)

**Removed.** Previously provided `loop`, `loop_next`, `loop_itr_done` — was dead code and has been deleted.

## Subagent Tools (`tools.py`)

The `subagent` registry tool spawns a read-only child `Harness` to explore the
codebase and return findings.
`wait_for_subagents` collects results from all queued background subagents.

Subagents always run under the **`scaffolder`** built-in role: read-only inside
the repo, deny everything else. The main agent's role is not inherited.

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
