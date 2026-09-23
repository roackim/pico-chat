# Roles Rework — Plan

**Status:** done (W1–W4 implemented 2026-09-23) · **Owner:** Joackim · **Created:** 2026-09-22
**Companion docs:** `.wiki/notes/principles.md`, `plans/containerization.md`,
`SIMPLIFICATION.md` (R11).

Converged direction: **a role is a prompt plus a per-tool approval setting.**
There is no permission engine and no container code inside pico — isolation is
the user's responsibility (`plans/containerization.md`). In the same spirit:
delete before you design; every step ends with fewer files / layers / lines.

---

## Target model

- `Role` = `name` (file name), `description`, `prompt`, `tools: dict[str, str]`.
- Each tool is one of exactly three values:

  | Value | Meaning |
  |-------|---------|
  | `no`  | disabled — **not put in `tool_schemas`**, so the model never sees it |
  | `ask` | enabled; the harness prompts the user before the call |
  | `yes` | enabled; runs without prompting |

- There is no `deny`: a tool you would always deny is simply `no` (hiding it
  avoids confusing the model).
- No profiles, no `settings`, no `inside_repo`/`outside_repo`, no command
  allow/deny lists, no chain policy, no workspace confinement. The container
  mount (when sandboxed) or the user's `ask` choices (when bare) are the
  boundary.

---

## Role file (user-friendly, server-like)

One file per role, listing every available tool. Comment/uncomment or edit the
value — the "all options visible" style of `servers.toml`.

```toml
# Pico role: reviewer
#   The file name is the role name.
#   Select with: /role reviewer
#   Edit with:   /config role reviewer
#
# Tools: no = disabled (hidden from the model) · ask = confirm · yes = auto

description = "Read-only code review"
prompt = "Review code carefully. Do not modify files. Prioritize defects, regressions, and missing tests."

# All available tools:
read = "yes"
write = "no"
patch = "no"
run_command = "no"
subagent = "yes"
wait_for_subagents = "yes"
```

- `roles.create_role(name)` generates the file from the tool registry, so the
  catalogue always matches the code.
- A new role defaults to all tools `yes` (general assistant); switching to `ask`
  is the restrictive action.
- Run pico in a container → `yes` everywhere. Run it bare → `ask` on the
  mutating tools.

---

## Command surface

| Command | Behavior |
|---------|----------|
| `/role` | list roles, mark the active one |
| `/role <name>` | switch the active role |
| `/config role <id>` | ensure `roles/<id>.toml` exists (via `create_role`), open in `$EDITOR`, reload |
| `/config role delete <id>` | confirm, then unlink the file and fall back to `default` if it was active |

Deletes `/roles` and its `show` / `duplicate` / `rename` / `delete` branches.
Role lifecycle is files + these two surfaces.

---

## API (`harness/roles.py`)

- `create_role(name) -> Role` — write the template (only programmatic writer).
- `delete_role(name)` — unlink; refuse `default`/`scaffolder`.
- `list_roles() -> list[str]`
- `load_role(name) -> Role`
- `default_role()` / `scaffolder_role()` — code fallbacks (`default` for a fresh
  config, `scaffolder` for subagents, never user-editable).

The app never serializes a resolved role to disk — no giant files.

---

## Deletions

### `harness/permissions.py` — shrink to a gate
Keep only the confirmation decision + prompt plumbing (the `ask` path) reading
the role's per-tool value. Delete: `ToolPermissionsProfile`, `FilePermissions`,
`RunPermissions`, all predefined profiles (`strict`/`permissive`/... ), the
global `permissions`, `SecurityChecker`, `parse_operators`, `get_command_name`,
`check_command`, `CMD_DEFAULT_*`, `CMD_DANGEROUS_PATTERNS`, `file_permission`,
`resolve_run_permissions`, `_is_role_policy`, and the profile-fallback branches.

### `harness/tools.py`
- `default_permissions` import (`:23`), `self.permissions` (`:49`, `:319`,
  `:484`), and the `file_permission(...)` blocks in `read`/`write`/`patch`
  (`:129-136`, `:184-191`, `:277-283`) — the `deny` branch is gone; `ask` is
  handled by the gate before the tool runs.
- `ToolPolicySpec` (`:553`), `ToolDefinition.policy` (`:569`), every `policy=`
  argument, `RegisteredTool.policy_spec` (`:633`).
- `create_toolset` / `MinimalToolset`: drop the `permissions` and
  `confirmation_callback` parameters.
- `registered_tool_specs()` (`:685`) becomes a plain list of tool names (used by
  `create_role`).
- Update the `run` tool description (`tools.py:816-823`): drop "safe commands
  auto-allowed / requires confirmation / blocked".

### `harness/harness.py`
- Construction (`:52-56`) and `set_role` (`:113`) pass the role to a slimmed
  gate; delete the run-permission / profile checks (`:699`, `:724`) and the
  `PermissionGate` policy-profile plumbing.
- Keep `_request_user_confirmation` (the `ask` path).
- `_record_role_change` (`:133`) — the system prompt already carries the active
  role each turn; keep only the UI notice.

### `harness/roles.py`
- `ToolPolicy` (`:26`) → per-tool string value; `Role.tools` becomes
  `dict[str, str]`, `enabled_tool_names()` = values != `"no"`.
- `_policy_to_dict` / policy serialization, `save_role`, `rename_role`,
  `duplicate_role`, and the settings/default-filling in `_build_role` /
  `_role_from_dict`.
- `_validate_name` stays.

### `pico_cfg.py`
- `DEFAULT_ROLE_TOML` (moved into `roles.create_role`), `ensure_roles_dir`
  (moved to `roles.ensure_roles_dir`). Keep `ROLES_DIRNAME`, `get_roles_dir`,
  `get_role_path`.

### UI
- `ui/commands/roles.py` → replaced by a small `role` handler (list/use).
- `ui/commands/tools.py` **deleted** (and its `tools` registry entry).
- Keep the permission prompt plumbing (`app.py` `pending_permission_prompt`,
  `generation_presenter` permission events) — it serves `ask`.
- Naming: `/role` singular; fix `external_editor.py:3`.

### Tests
- `test_permissions.py` mostly deleted / reduced to gate + prompt tests.
- `test_subagents.py` role assertions (`:344`) updated.
- `test_config_loader.py` role-template assertions (`:142`, `:155-165`) moved to
  the new `create_role`.

---

## Validation (item 6)

Role files are validated against the tool registry: unknown tool names and
values other than `no`/`ask`/`yes` are reported as `roles/<name>.toml: ...`,
surfaced by `/reload` and `/config role <id>` (same contract as the section
files).

---

## Sequencing

| # | Workstream | Ends with |
|---|-----------|-----------|
| W1 | `roles.py` model → prompt + `tools: dict[str, str]`; `create_role` | simpler config |
| W2 | Shrink the gate; delete profile/allowlist machinery; simplify `tools.py`, `harness.py` | engine gone |
| W3 | Command surface: `/role`, `/config role [delete]`; delete `/roles` + `/tools` | fewer commands |
| W4 | Validation + tests; wiki updates (`roles`, `tools-and-permissions`) | suite green |

Gates after every workstream (from `HANDOFF.md`):

```bash
.pixi/envs/default/bin/python -m pytest test/ -q
.pixi/envs/default/bin/python -m compileall -q pico_chat
.pixi/envs/default/bin/python -m vulture pico_chat --min-confidence 80
.pixi/envs/default/bin/python -m pytest test/test_core_ui_boundary.py -q
.pixi/envs/default/bin/python -m pytest test/test_command_import_graph.py -q
```

No container prerequisite: pico implements no sandbox (`plans/containerization.md`).
Dropping `inside_repo`/`outside_repo` means bare (unsandboxed) pico has no path
restriction; that is accepted because the user sets `ask` on mutating tools in
that mode.

---

## Open

- Built-ins: seed `default`/`reviewer`/`researcher` as files on first run, or
  keep built-ins in code and ship only `create_role`? (Recommend files, with a
  code fallback for `default`.)
- Default tool set for a newly created role: all `yes` (recommended) vs a
  minimal set (`read=yes`, rest `ask`/`no`).
