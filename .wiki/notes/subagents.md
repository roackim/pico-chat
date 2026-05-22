# Subagents

Subagents are lightweight, read-only `Harness` instances spawned by the main agent to parallelise codebase exploration. The LLM calls the `subagent` tool; pico spins up a child harness, runs its conversation to completion, and returns the text.

---

## Architecture

```
Harness (depth=0)          ← main agent, full permissions
    └─ SubagentTool.execute()
           └─ Harness (depth=1)   ← subagent, scaffolder permissions
                  ↳ chat(task) → stream chunks → collect text → return
```

`SubagentTool` and `WaitForSubagentsTool` live in `tool_wrappers.py`.  
The child `Harness` is created inside `_run_subagent()` with `depth=self.depth + 1`.

---

## Permissions

Subagents always use the **`scaffolder`** permission profile (defined in `tool_permissions.py`):

| Operation | Inside repo | Outside repo |
|-----------|-------------|--------------|
| read      | allow       | deny         |
| write     | deny        | deny         |
| patch     | deny        | deny         |
| run       | deny (others=deny, allow=∅) | deny |
| memory    | deny        | —            |

The parent harness detects `depth > 0` at construction time and sets `self._tool_permissions = scaffolder`. This also means no `confirmation_callback` is wired up — subagents never prompt the user.

`subagent` and `wait_for_subagents` tool calls are **always auto-approved** (`_check_tool_permission` returns `"allow"` unconditionally for these two names).

---

## Depth Limit

`pico_cfg.subagent_max_depth` (default: `1`) caps recursive spawning.  
When `self.depth >= subagent_max_depth`, `SubagentTool.execute()` returns the string:

```
[subagent] Depth limit reached (<N>).
```

No child harness is created; no LLM call is made.

---

## Timeout

`pico_cfg.subagent_timeout` (default: `120` seconds) is enforced via `asyncio.wait_for`.  
On expiry the subagent task is cancelled and the tool returns:

```
[subagent timed out after <N>s]
```

---

## Context Limit

`pico_cfg.subagent_max_context` (default: `None` = unlimited).  
Tokens are accumulated per assistant turn via `GenerationMetrics` chunks. When `cumulative_tokens + last_call_tokens > max_context`, a `_ContextLimitError` is raised internally and the tool returns:

```
[subagent aborted: context limit exceeded (<actual> > <max> tokens)]
```

---

## Foreground vs Background

### Foreground (`background=False`, default)

`execute()` awaits `_run_subagent()` and returns the full text response.  
Empty response → `"[subagent returned no response]"`.

### Background (`background=True`)

`execute()` creates an `asyncio.Task` and appends it to `self._pending` (a shared list owned by the parent harness). Returns immediately with:

```
[subagent:<index>] Queued in background.
```

The LLM then calls `wait_for_subagents` to collect all results.

---

## wait_for_subagents

`WaitForSubagentsTool.execute()` calls `asyncio.gather(*futures)`, clears `_pending`, and formats results:

```
[subagent:0] Task: <task text>
<result text>

[subagent:1] Task: <task text>
<result text>
```

Exceptions inside a subagent task are caught by `gather(return_exceptions=True)` and reported as `[subagent:<N>] Error: <message>`.

---

## Server Selection

By default the subagent inherits the parent's active server. If `pico_cfg.subagent_server` is set to a named server, that server is used for all `depth > 0` harnesses. This allows routing subagent calls to a cheaper/faster model.

---

## Abort

`Harness.abort_subagents()` sets `_abort_subagents_event`. The auto-wait path in `_auto_wait_subagents()` (called after the main loop ends) checks this event to cancel remaining tasks early.

---

## Config Reference

| Key | Default | Description |
|-----|---------|-------------|
| `subagent_max_depth` | `1` | Maximum spawn depth (0 = no subagents) |
| `subagent_timeout` | `120` | Seconds before a subagent is killed |
| `subagent_max_context` | `None` | Token cap per subagent (None = unlimited) |
| `subagent_server` | `None` | Named server override (None = inherit active) |
