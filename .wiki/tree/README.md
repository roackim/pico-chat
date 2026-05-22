# pico_chat/ — Root Package

Entry point, config loading, and public API exports.

See [notes/architecture.md](../notes/architecture.md) for the full system overview.

---

## Files

### `main.py`
Async launcher. Instantiates `Config`, `Harness`, and `chatTUI`, then starts the TUI event loop.

### `pico_cfg.py`
`Config` — plain class (not a dataclass) loaded from `~/.config/pico-chat/config.toml` at startup via a module-level global singleton (`pico_cfg.config`). Holds server definitions, UI settings, and general settings. Permission policies are a separate system — see [notes/config.md](../notes/config.md) for the full split.

### `__init__.py`
Package exports: `Harness`, `get_harness()`, package version.

---

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| [harness/](./harness.md) | LLM agent core — loop, tools, security, context |
| [ui/](./ui.md) | Terminal user interface — chat display, input, commands |
