# pico_chat/ — Root Package

Entry point, config loading, and public API exports.

See [notes/architecture.md](../notes/architecture.md) for the full system overview.

---

## Files

### `main.py`
Launcher. Seeds role files (`roles.ensure_roles_dir()`), builds the `Harness`
via `get_harness()`, applies the configured theme, and runs `chatTUI`.

### `pico_cfg.py`
`Config` — plain class instantiating the split, user-level config under
`~/.config/pico-chat/` (`ui.toml`, `context.toml`, `subagents.toml`,
`debug.toml`, `styles.toml`, `servers.toml`, `roles/<name>.toml`, disposable
`state.toml`). Loaded at import as the module-level singleton `pico_cfg.config`.
`/reload` mutates it in place. See [notes/config.md](../notes/config.md).

### `__init__.py`
Exports `pico_cfg`, `Harness`, `get_harness`, and `__version__`.

---

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| [harness/](./harness.md) | LLM agent core — loop, tools, endpoints, context |
| [ui/](./ui.md) | Terminal user interface — chat display, input, commands |
