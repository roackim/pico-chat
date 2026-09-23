# Security

Pico runs shell commands and reads/writes files on behalf of an LLM agent.
There is **no security layer inside pico**: no command parsing, no allowlist,
no path confinement, no container runtime. The safety model is deliberately
minimal and explicit.

---

## Threat model

- The LLM may generate tool calls that read, write, or delete anything the
  process can reach, and shell commands with any operators it likes.
- pico does not try to tell safe commands from dangerous ones. Chained-command
  splitting cannot be done reliably (command substitution, `bash -c`, `xargs`,
  interpreters, obfuscation), so allowlists are a security illusion and
  deny-lists fail open to obfuscation.
- The boundary belongs to the environment: a container, VM, `bubblewrap`, or
  the user watching the prompt.

## Two modes, declared by the user

The whole safety story is the per-tool approval setting (`roles.py`): each tool
is `no` / `ask` / `yes`, and the user picks it explicitly — nothing is inferred.

| Situation | Boundary | Tool settings |
|---|---|---|
| pico run inside the user's container | the container | `yes` (the mount is the wall) |
| pico run bare on the host | none | `ask` on `write` / `patch` / `run_command` |

See `plans/containerization.md` for the full decision record and the
recommended (not shipped) `podman run` posture.

## Permission gate (`permissions.py`)

`PermissionGate` is the single decision point. It reads the active role's
per-tool value and returns the harness decision:

- `no` → `deny` — blocked, no prompt. The tool is not exposed to the model.
- `ask` → `ask` — the UI pauses and prompts the user before executing.
- `yes` → `allow` — executes without prompting.

It also builds the prompt text (`build_prompt()`) and owns the async
user-response queue. There is no `SecurityChecker`, no dangerous-pattern list,
and no chain policy.

## Path restrictions

None. File tools resolve relative paths against the workspace and otherwise
operate wherever the process can. Running bare, the user relies on `ask`.
Running in a container, the mount is the boundary.

## Tests

| Test | Coverage |
|------|----------|
| `test_permissions.py` | Gate decisions, prompt text, ask/deny/allow harness flow |
| `test_roles.py` | Role model, files, seeding, validation |
| `test_subagents.py` | Scaffolder role, depth/timeout/context limits |
