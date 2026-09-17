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
| `[servers]` or `[endpoints]` | `config.servers: Dict[str, Dict]` | `config.servers["my-claude"]` |
| `[settings]` | direct attrs on `Config` | `config.active_server`, `config.target_fps` |
| `[ui]` | `ui_`-prefixed attrs | `config.ui_theme`, `config.ui_box_style` |
| `[model_selection]` | `config.model_selection: Dict[server, model]` | `config.model_selection["my-ollama"]` |
| `[model_catalog]` | `config.models_by_server: Dict[server, list]` | `config.models_by_server["my-ollama"]` |

The `ui_` prefix is applied automatically: a TOML key `theme` under `[ui]` maps to `config.ui_theme`.

`[model_selection]` records the **per-server** last-used model — the model you last picked for a given endpoint, independent of the endpoint definition. `[model_catalog]` caches the discovery catalog per server so `/model` fuzzy completion and `ModelInfo` metadata survive a restart without re-querying; it is refreshed by `/model list`, `server add`, and discovery.

### Key settings

**Servers:**
- `config.servers` — dict of named server configs (raw dicts, not typed objects)
- `config.active_server` — name key into `servers`; saved to `[settings] active_server`
- `config.get_active_server_config()` — returns the active server's raw dict, or `None`
- `config.active_model` — legacy global selected model; kept in sync for backward compatibility
- `config.model_selection` — per-server model choice (`server_name -> model id`). Preferred over the legacy global `active_model`.
- `config.models_by_server` — cached discovery catalog (`server_name -> list[ModelInfo-dict]`)
- `config.get_model_for_server(server)` — effective model for a server, preferring `model_selection`, then the legacy per-server `model` default
- `config.save_model_selection(server, model)` — persist a per-server model choice to `[model_selection]`
- `config.save_model_catalog()` — persist the current discovery catalog to `[model_catalog]`

Endpoints and models are separate at runtime. `LLMServerConfig` describes the
connection endpoint, while the server instance owns the selected model and its
model-aware context cache. Existing `[servers]` configs remain supported;
`[endpoints]` is the preferred spelling for new configurations.

`[settings] active_server` reflects the last-used endpoint. Selecting a model
via `/model` also sets that model's serving server as the active endpooint so
the last-used model is restored as the default on the next launch.

**Model selection resolution order** (`get_server_config`):
1. per-server model choice in `config.model_selection`
2. legacy global `config.active_model`
3. per-server `model` default in the server config dict

**OpenRouter model allowlist:** an OpenRouter server config can set
`enabled_models = ["provider/model", ...]`. OpenRouter models are **disabled
by default** — only explicitly-enabled models are surfaced by `/model` and
`discover_models`. `add_openrouter` stores the single model passed at add time
in `enabled_models`. (A future settings page will edit this list.) A server
config without `enabled_models` falls back to its `model` key. For Ollama
endpoints, `model_catalog` entries carry the full `/api/tags` metadata (size,
family, etc.) plus a resolved context window.

**General:**
- `config.preserve_reasoning_traces` — preserve `<think>` tags and `reasoning_content` in history for multi-turn reasoning
- `config.max_file_size`, `config.max_search_results`, `config.command_timeout`
- `config.context_format` — `"tree"` or `"flat"` for context injection
- `config.context_max_files` — max entries listed by the `@` file picker / context tree (default 500)
- `config.context_max_depth` — max directory depth walked when listing files (default 4)
- `config.context_ignore_gitignore` — if `True`, list gitignored files too (default `False`)
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
- `config.ui_status_bar_fields` — ordered status-bar fields; default is `['endpoint_model', 'role', 'context']`

**Markdown styles:**
- `config.markdown_styles` — dict of per-element style dicts (`fg`/`bg`/`bold`/`reverse`) loaded from the `[markdown_styles]` TOML section. Elements: `header1`–`header6`, `bold`, `italic`, `code`, `code_block`, `quote`, `list`, `hr`, `table`, `link`, `paragraph`. See [ui.md](./ui.md#markdown-rendering).

### What can be saved at runtime

Server/endpoint configs have a write-back path through `config.save_server(name, server_dict, set_active=True)`. The selected model can be persisted independently with `config.save_active_model(model)`.
All other settings are read-only at runtime — no save mechanism exists for UI or general settings.

### Known gaps / unplugged settings

- `config.ui_box_style_focused` — defined but not wired up to any renderer

---

## System 2 — roles (tool policies)

**Files:** `pico_chat/harness/roles.py`, `pico_chat/harness/permissions.py`

Tool policies (`ALLOW` / `ASK` / `DENY`) are a separate system, not stored in the main TOML file and not part of `Config`. They live on a `Role` (`roles.py`); the low-level execution primitives and the single decision point live in `permissions.py`.

Permission checking is handled by `PermissionGate` (`harness/permissions.py`), which owns the user-response queue and checks the active role's policies.

In practice this means:
- Permission policies cannot be set via `config.toml`. They are edited through `/permissions` (or the settings tab), and roles persist in `~/.config/pico-chat/roles.toml`.
- The no-argument `/permissions` popup is a live role editor: selecting,
  creating, duplicating, renaming, removing, or changing a policy applies the
  active role immediately through `RoleEditorModel`.
- For permission architecture details, see [notes/security.md](./security.md) and [notes/tools-and-permissions.md](./tools-and-permissions.md)

---

## Summary of the split

| Concern | Where it lives | Configurable via TOML? |
|---------|---------------|----------------------|
| Server definitions | `pico_cfg.Config.servers` | Yes |
| UI settings | `pico_cfg.Config.ui_*` | Yes |
| General settings | `pico_cfg.Config.*` | Yes |
| Tool permissions | `roles.py` / `roles.toml` | Via `/permissions`, not `config.toml` |
