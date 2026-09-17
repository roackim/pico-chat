# Pico-Chat Simplification — Plan

**Status:** in refinement (resolved decisions below; definition-needed items at the end)
**Scope:** independent of `refactor.todo`.

---

## North star

Pico is a thin runtime over hand-editable configuration:

> Stream from one endpoint, run approved tools, render a transcript.
> Configuration is files. The UI is the transcript, one input line, and one
> approval prompt.

## Principles

1. **Config files are the settings UI.** No forms, no settings pages, no
   editors for servers/models/roles/permissions.
2. **Explicit over implicit.** `/reload` applies changes; nothing is watched or
   auto-applied silently.
3. **Delete UI complexity; keep headless features.** Tabs, forms, settings
   surfaces, and debug panels go. Features that need no UI (subagents,
   compaction, search, containerization) may stay configured from files.
4. **Hard core/UI boundary.** `core` imports no `ui`; `ui` consumes events.
   This keeps the door open for a future TUI replacement.

---

## Resolved decisions

### R1 — One event protocol
Replace `chunks.py` + the `_process_generation` dispatch + thinking/usage
plumbing with one event union: `Token`, `Reasoning`, `ToolCall`, `ToolResult`,
`PermissionRequest`, `Usage`, `Error`, `Done`. The harness yields events; the UI
renders them. No `StreamPresenter` extraction needed.

### R2 — One endpoint type
`Endpoint` = `base_url` + `api_key` + optional discovery/routing. Collapse
`LLMServerConfig` + `get_server_config*` + `ServerService` + the `LLMServer`
ABC/four subclasses. Keep thin adapters only where genuinely different (Ollama
native usage counters, OpenRouter provider routing). Deletes the
`active_model`/`model_selection`/catalog sync.

### R3 — Commands as data
One registry of `(name, description, params, handler)`. Classes only where a
subcommand tree plus state is real.

### R4 — Config: `pico.toml` + `roles.toml`, project-local overrides
- User: `~/.config/pico-chat/pico.toml` and `~/.config/pico-chat/roles.toml`.
- Project-local `pico.toml` / `roles.toml` override the user files, discovered
  by walking up from the working directory.
- `/reload` reloads explicitly (startup also loads). No file watcher, no
  automatic project reload.
- Loader must **validate and report** errors (the current loader silently
  swallows malformed files).
- Separate intent (hand-edited) from state (machine cache). State is disposable.

### R5 — Settings move to files; delete the authoring UI
Delete: `form.py`, `form_popup.py`, `settings_panel.py`, `settings_screen.py`,
`settings_pages.py`, `openrouter_settings.py`, `role_editor_form.py`,
`role_editor_model.py`, `config_overlay`, the settings tab, profile editors.
Keep interactive **only** for permission approval and destructive confirmation.

### R6 — Remove tabs entirely
One conversation per process. Collapses `_tabs`, `ConversationState`,
`_active_runtime`, `_initial_agent`, the settings tab, and the
"which agent is active" bug class. Parallelism is another process (or a
subagent).

### R7 — Remove conversation persistence
Drop autosave for now. Keep `/export`. Re-add later if missed.

### R8 — Features are deleted outright
No plugin layer. UI-only features are removed; headless features are kept or
deleted per R7-style judgment (see "Definition needed", P4).

### R9 — No `core` → `ui` imports
Enforced by a guard test. Enables the future middle-ground TUI.

### R10 — Quick-change ergonomics trade accepted
Editing a file plus `/reload` replaces the old forms. A future bare-bones
in-terminal editor (nano-style) is a nice-to-have, not core; until then use
`$EDITOR`.

### R11 — Roles stay named; `/role use` remains
`roles.toml` keeps multiple named roles; the active one is selected at runtime
via `/role use`. (Re-explained O4.)

---

## Deferred

- Replacing the bespoke TUI toolkit (author has a middle-ground idea; R9 is
  the seam that makes it swappable).
- Deriving tool schemas from type signatures.
- Built-in mini editor.

---

## Definition needed

| # | Item | Options / recommendation |
|---|------|--------------------------|
| P1 | **Project-local config trust.** A cloned repo's `pico.toml`/`roles.toml` can change permissions (auto-allow `run`) or point at a malicious endpoint. | **T1 (rec):** trust-on-first-use keyed by config hash in `state.toml`; prompt on new/changed file. T2: project config may not touch servers/permissions. T3: always confirm. |
| P2 | **Exact schema** for `pico.toml`, `roles.toml`, `state.toml`. | See sketch below; confirm keys/sections. |
| P3 | **Surviving command surface.** | `/help /clear /reload /config /edit /model /server /role /export /quit` (+ maybe `/tools`). Confirm. |
| P4 | **Headless features to keep vs delete.** | Keep: roles, model/server discovery+selection, context file tree, debug-to-file. Decide: compaction, subagents, search tools, containerization, token estimation. |
| P5 | **Editor.** | `/edit [file]` opens `$VISUAL`/`$EDITOR` (rec); built-in editor later. |
| P6 | **Migration** from current `config.toml`/`roles.toml`. | M1 back-compat keys; M2 `/migrate-config`; **M3 (rec, early project):** rename + document. |

### Config sketch (P2)

```toml
# pico.toml
[ui]
theme = "terminal"

[servers.local]
type = "llamacpp"
base_url = "http://localhost:8080/v1"

[servers.or]
type = "openrouter"
api_key_env = "OPENROUTER_API_KEY"
enabled_models = ["anthropic/claude-3.5-sonnet"]
# per-model provider routing
[servers.or.providers."anthropic/claude-3.5-sonnet"]
mode = "whitelist"
providers = ["Anthropic"]
```

```toml
# roles.toml
[roles.default]
description = "General coding assistant"
prompt = ""
tools = ["read", "write", "patch", "run", "search_web", "search_wiki"]
read   = { inside = "allow", outside = "ask" }
write  = { inside = "allow", outside = "deny" }
patch  = { inside = "allow", outside = "deny" }
run    = { others = "deny", chain = "ask", allow = ["ls", "cat"], container = true }
```

```toml
# state.toml  (machine-written, disposable)
last_server = "local"
last_model  = { local = "qwen..." }
[model_catalog]
local = [{ id = "qwen...", context_window = 32768 }]
[trusted_projects]
"/path/to/repo" = "sha256:..."
```

---

## Rough impact

Current distribution (25.5k LOC): `ui/tui` 44.7%, `harness` 28.5%, `ui` app
18.4%, `ui/commands` 6.5%, root 1.9%.

R1–R8 target roughly 8–10k LOC of deletion/rewrite in the harness, config,
commands, and app-level UI. The TUI toolkit itself remains until the deferred
item.

## Proposed sequencing

1. **R4** config schema + loader + validation + project overrides + `/reload`.
2. **R2** `Endpoint`; delete the server/service/llm-config split.
3. **R1** event union; harness yields, UI consumes.
4. **R3** command registry as data; prune command classes.
5. **R5/R6** delete forms/settings/tabs; single-conversation app.
6. Revisit deferred items.

Each phase ends with fewer files and fewer layers.
