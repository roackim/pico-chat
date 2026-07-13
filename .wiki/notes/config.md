# Configuration

Configuration is split across two separate systems that do not share a base class or interface. This is the current state — it is not fully clean.

---

## System 1 — `pico_cfg.Config` (runtime settings)

**File:** `pico_chat/pico_cfg.py`

`Config` is a plain class (not a dataclass) with flat attributes. It is instantiated once at module load time as a global singleton:

```python
config: Config = Config(config_path=None)
```

Everything in the codebase accesses it as:
```python
from pico_chat import pico_cfg
pico_cfg.config.some_setting
```

### TOML file location

`~/.config/pico-chat/config.toml`

Loaded at startup. **No live-reload** — changes require a restart. If the file is missing or malformed, loading silently fails and all defaults are used (no error, no warning).

### TOML structure vs in-memory layout

The TOML file has three top-level sections; the in-memory `Config` object collapses them flat:

| TOML section | In-memory | Example |
|---|---|---|
| `[servers]` | `config.servers: Dict[str, Dict]` | `config.servers["my-claude"]` |
| `[settings]` | direct attrs on `Config` | `config.active_server`, `config.target_fps` |
| `[ui]` | `ui_`-prefixed attrs | `config.ui_theme`, `config.ui_box_style` |

The `ui_` prefix is applied automatically: a TOML key `theme` under `[ui]` maps to `config.ui_theme`.

### Key settings

**Servers:**
- `config.servers` — dict of named server configs (raw dicts, not typed objects)
- `config.active_server` — name key into `servers`
- `config.get_active_server_config()` — returns the active server's raw dict, or `None`

**General:**
- `config.render_thinking` — whether to show `<think>` blocks- `config.preserve_reasoning_traces` — preserve `  thinking...  response` in history for multi-turn reasoning- `config.max_file_size`, `config.max_search_results`, `config.command_timeout`
- `config.context_format` — `"tree"` or `"flat"` for context injection
- `config.target_fps` — compositor render rate
- `config.subagent_max_depth`, `config.subagent_timeout`, `config.subagent_max_context`, `config.subagent_server` — subagent limits (see [subagents.md](./subagents.md))

**UI:**
- `config.ui_theme` — `"default"` or `"terminal"`
- `config.ui_use_bg_color` — use theme background color (false = terminal default)
- `config.ui_box_style` — border style: `"square"`, `"double"`, `"rounded"`, `"ascii"`
- `config.ui_max_input_height`, `config.ui_debug_console_height`
- `config.ui_msg_h_padding`, `config.ui_msg_v_margin`
- `config.ui_cursor_frequency`, `config.ui_cursor_pulse_delay`
- `config.ui_show_metrics`, `config.ui_metrics_show_speed`, etc.

**Markdown styles:**
- `config.markdown_styles` — dict of per-element style dicts (`fg`/`bg`/`bold`/`reverse`) loaded from the `[markdown_styles]` TOML section. Elements: `header1`–`header6`, `bold`, `italic`, `code`, `code_block`, `quote`, `list`, `hr`, `table`, `link`, `paragraph`. See [ui.md](./ui.md#markdown-rendering).

### What can be saved at runtime

Only server configs have a write-back path: `config.save_server(name, server_dict, set_active=True)`.
All other settings are read-only at runtime — no save mechanism exists for UI or general settings.

### Known gaps / unplugged settings

- `config.log_file` — defined but not used (`TODO PLUG` in source)
- `config.ui_box_style_focused` — defined but not wired up to any renderer

---

## System 2 — `tool_permissions` (permission policies)

**File:** `pico_chat/harness/tool_permissions.py`

Permission policies (`ALLOW` / `ASK` / `DENY`) for tool operations are a separate system, not stored in the TOML file and not part of `Config`. They live in `tool_permissions.py` as a standalone `permissions` object.

`Config.get_permission(tool, is_inside_repo)` acts as a **bridge**: it dynamically imports `tool_permissions` and delegates to it. The dynamic import exists to avoid a circular import between `pico_cfg` and `harness`.

In practice this means:
- Permission policies cannot be set via `config.toml`
- `pico_cfg.config.get_permission()` is the only public API for querying permissions from outside the harness
- For permission architecture details, see [notes/security.md](./security.md) and [notes/tools-and-permissions.md](./tools-and-permissions.md)

---

## Summary of the split

| Concern | Where it lives | Configurable via TOML? |
|---------|---------------|----------------------|
| Server definitions | `pico_cfg.Config.servers` | Yes |
| UI settings | `pico_cfg.Config.ui_*` | Yes |
| General settings | `pico_cfg.Config.*` | Yes |
| Tool permissions | `tool_permissions.py` | No |
