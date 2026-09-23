# Configuration

Configuration is files. Everything hand-edited lives under
`~/.config/pico-chat/` (override the directory with `PICO_CONFIG_DIR`), split
into small single-concern files so each stays easy to edit. There is **no
project-local config** and no trust model.

## Files

| File | Contents | Shape |
|------|----------|-------|
| `ui.toml` | theme, padding, metrics, fps | flat keys |
| `context.toml` | context building | flat keys |
| `subagents.toml` | subagent limits | flat keys |
| `debug.toml` | debug logging | flat keys |
| `styles.toml` | `[markdown_styles.*]` / `[syntax_highlight.*]` | tables |
| `servers.toml` | one `[servers.<name>]` table per server | tables |
| `roles/<name>.toml` | one role per file; file name is the role name | role body |
| `state.toml` | last server/model, discovery catalog | machine-written |

`state.toml` is disposable: deleting it only loses cached selections.
`roles/` mirrors the same one-thing-per-file idea (see
[tools-and-permissions.md](./tools-and-permissions.md)).

Missing files are created from fully commented templates
(`pico_cfg.DEFAULT_CONFIG_TEMPLATES`) by `Config.ensure_section_file()` /
`ensure_config_files()`. The built-in role files (`agent.toml`, `chat.toml`)
are seeded by `roles.ensure_roles_dir()` on startup.

## Loader (`pico_cfg.py`)

`Config` is a plain class with a flat attribute surface (`pico_cfg.config.<attr>`),
instantiated once at module load as `config`. The split files map onto flat
attributes via per-section specs (`_UI_SPEC`, `_CONTEXT_SPEC`,
`_SUBAGENT_SPEC`, `_DEBUG_SPEC`); `styles.toml` and `servers.toml` are merged
into the `markdown_styles` / `syntax_highlight_styles` / `servers` tables.

- `reload()` re-reads every section file plus `state.toml` and returns a list of
  validation errors. Invalid entries keep their defaults; valid ones still
  apply. Errors are prefixed with the file name (`ui.toml: ...`).
- Unknown keys/sections/servers/types are reported rather than swallowed.
- After editing with `/config <section>`, the command reloads; `/reload` also
  reloads explicitly. Nothing is watched. `/reload` additionally runs
  `roles.validate_roles()` and reports role-file errors.

### Intent vs state

- **Intent** (hand-edited): the section files above. `save_server()` writes
  `servers.toml`; `remove_server()` deletes from it.
- **State** (machine-written, disposable): `state.toml` holds `last_server`,
  `active_model`, `[last_model]` (per-server selection) and `[model_catalog]`
  (discovery cache). Written by `save_active_model` / `save_model_selection` /
  `save_model_catalog`. The catalog is only a completion/offline cache — model
  selection is live discovery.

## Editing

- `/config <section>` opens the section file in `$VISUAL`/`$EDITOR` and reloads
  on exit; no argument lists the sections. `section` is one of `ui`, `context`,
  `subagents`, `debug`, `styles`, `servers`.
- `/edit <path>` opens any file. `/server edit` opens `servers.toml`.
- `/config role <name>` opens (creating if needed) `roles/<name>.toml`;
  `/config role delete <name> confirm` removes it.
- The TUI suspends/resumes around the editor (`ui/external_editor.py`,
  `ui/tui/terminal.py`).

## Roles

A `Role` is a prompt plus a per-tool approval setting (`no` / `ask` / `yes`),
stored one file per role under `roles/<name>.toml`. `PermissionGate`
(`harness/permissions.py`) is the single decision point. See
[security.md](./security.md) and [tools-and-permissions.md](./tools-and-permissions.md).

## Key settings

**Servers:** `config.servers`, `config.active_server`, `config.active_model`,
`config.model_selection` (`server -> model`), `config.models_by_server`
(catalog), `config.get_model_for_server(server)`,
`config.get_active_server_config()`.

**Context / subagents / ui:** `context_format`, `context_max_files`,
`context_max_depth`, `context_ignore_gitignore`, `preserve_reasoning_traces`;
`subagent_max_depth`, `subagent_server`, `subagent_timeout`,
`subagent_max_context`; `ui_theme`, `ui_box_style`, `ui_show_metrics`,
`ui_status_bar_fields`, `ui_max_input_height` (input box caps + scrolls past
this many wrapped lines), `target_fps`, and the rest of the `ui_*` attrs.

**Styles:** `config.markdown_styles`, `config.syntax_highlight_styles`.
