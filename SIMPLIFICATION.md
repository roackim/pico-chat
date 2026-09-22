# Pico-Chat Simplification — Plan

> **The design principles that emerged from this work now live canonically in
> [`.wiki/notes/principles.md`](./.wiki/notes/principles.md).** This file is the
> historical record of the simplification rounds (R1–R11), not the principles
> reference.

**Status:** R1,R2,R3,R4,R4b,R5,R6,R7,R8,R9 done.
See `HANDOFF.md` for current state and the remaining work (OSC 52 clipboard,
optional picker polish / structural refactor). A round of UI/UX polish
(message prefix bar, selection + action line, activity surface, `@` picker) is
also done.
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

### R1 — One event protocol *(done 2026-09-21)*
Replace `chunks.py` + the `_process_generation` dispatch + thinking/usage
plumbing with one event union: `Token`, `Reasoning`, `ToolCall`, `ToolResult`,
`PermissionRequest`, `Usage`, `Error`, `Done`. The harness yields events; the UI
renders them. No `StreamPresenter` extraction needed.

### R2 — One endpoint type *(done 2026-09-21)*
`Endpoint` (in `harness/endpoint.py`) is one concrete type: connection config
plus live transport. Collapsed `LLMServerConfig` + `get_server_config*` +
`ServerService` + the `LLMServer` ABC/four subclasses. Server-family
differences are internal branches (Ollama native usage counters, OpenRouter
provider routing). `server_service.py`, `llm_server.py` and
`llm_server_config.py` are deleted. Model selection is live discovery; the
`state.toml` catalog is only a convenience cache/fallback.

### R3 (partial) — file-based config editing
Commands no longer build config with forms: `/config`, `/edit` and
`/roles edit` open `$VISUAL`/`$EDITOR` (fallback nano/vim/vi) and reload. The
TUI terminal suspends/resumes around the editor (`ui/tui/terminal.py`,
`ui/external_editor.py`). `/server` is list/use/edit/info/remove/diagnose;
`/model` discovers live. Full command-registry-as-data cleanup still pending.

### R3 — Commands as data *(done 2026-09-22)*
One registry of `(name, description, params, handler)`. Leaf commands are plain
handler functions; `Command` classes are reserved for real subcommand trees
(server/model/debug/openrouter/conversation).

### R4b — Split intent into per-section files *(done 2026-09-21)*
`pico.toml` was replaced by single-concern files (`ui.toml`, `context.toml`,
`subagents.toml`, `debug.toml`, `styles.toml`, `servers.toml`) so `/config
<section>` edits a small focused file. `servers.toml` is still one file for all
servers. No back-compat with `pico.toml` (P6).

### R4 — Config: `pico.toml` + `roles/<name>.toml` (user-level only)
- User: `~/.config/pico-chat/pico.toml` and `~/.config/pico-chat/roles/<name>.toml`.
  `PICO_CONFIG_DIR` overrides the directory.
- **No project-local overrides** (decided 2026-09-21): avoids the trust
  problem of a cloned repo changing permissions/endpoints. May return later
  behind an explicit trust step.
- `/reload` reloads explicitly (startup also loads). No file watcher.
- Loader must **validate and report** errors (the current loader silently
  swallows malformed files). Invalid entries keep their defaults; the rest of
  the file still applies.
- Separate intent (`pico.toml`, hand-edited) from state (`state.toml`,
  machine-written, disposable).

### R5 — Settings move to files; delete the authoring UI *(done 2026-09-21)*
Delete: `form.py`, `form_popup.py`, `settings_panel.py`, `settings_screen.py`,
`settings_pages.py`, `openrouter_settings.py`, `role_editor_form.py`,
`role_editor_model.py`, `config_overlay`, the settings tab, profile editors.
The `/settings` and `/permissions` commands were removed with it; the only
interactive UI left is the text popup and the permission `[a]`/`[x]` prompt.
`show_form_popup`/`show_confirmation` were removed from `app.py` and
`commands/base.py` (the latter had no callers).
Keep interactive **only** for permission approval and destructive confirmation.

### R6 — Remove tabs entirely *(done 2026-09-21)*
One conversation per process. Collapses `_tabs`, `ConversationState`,
`_active_runtime`, `_initial_agent`, the settings tab, and the
"which agent is active" bug class. Parallelism is another process (or a
subagent).

### R7 — Remove conversation persistence *(done 2026-09-21)*
Drop autosave for now. Keep `/export`. Re-add later if missed.

### R8 — Features are deleted outright *(done 2026-09-21)*
No plugin layer. UI-only features are removed; headless features are kept or
deleted per R7-style judgment (see "Definition needed", P4). Deleted:
`search_web`/`search_wiki`, containerization (bubblewrap), token estimation.
Kept: compaction, subagents.

### R9 — No `core` → `ui` imports
Enforced by a guard test. Enables the future middle-ground TUI.

### R10 — Quick-change ergonomics trade accepted
Editing a file plus `/reload` replaces the old forms. A future bare-bones
in-terminal editor (nano-style) is a nice-to-have, not core; until then use
`$EDITOR`.

### R11 — Roles stay named; `/roles use` remains
`roles/<name>.toml` keeps one role per file; the active one is selected at runtime
via `/roles use`. (Re-explained O4.)

---

## Deferred

- Replacing the bespoke TUI toolkit (author has a middle-ground idea; R9 is
  the seam that makes it swappable).
- Deriving tool schemas from type signatures.
- Built-in mini editor.

---

## Decisions (resolved 2026-09-21)

| # | Decision |
|---|----------|
| P1 | **No project-local config.** User-level `pico.toml` + `roles/` only. No trust model needed now. |
| P2 | Schema: `[ui]`, `[servers.<name>]`, `[context]`, `[subagents]`, `[debug]`, `[markdown_styles]`, `[syntax_highlight]` in `pico.toml`; one role body per file in `roles/<name>.toml`; tiny disposable `state.toml`. |
| P2b | `state.toml` = `last_server`, `active_model`, `last_model`, `model_catalog`. Safe to delete. |
| P3 | Command surface is deferred to a dedicated command refactor. Editing will spawn `$EDITOR` (e.g. `/roles edit architect`). |
| P4 | Keep **compaction** and **subagents**. Delete **search tools**, **containerization**, **token estimation**. |
| P5 | `/edit [file]` and friends open `$VISUAL`/`$EDITOR`; built-in editor later. |
| P6 | Start fresh + document. No back-compat keys. |

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
# roles/architect.toml  (body is the role; file name is the role name)
description = "General coding assistant"
prompt = ""

[tools.read]
enabled = true
permission = "allow"
[tools.read.settings]
inside_repo = "allow"
outside_repo = "ask"

[tools.run_command]
enabled = true
permission = "ask"
[tools.run_command.settings]
others = "deny"
chain_policy = "ask"
allow = ["ls", "cat"]
```

```toml
# state.toml  (machine-written, disposable)
last_server = "local"
active_model = "qwen..."
[last_model]
local = "qwen..."
[model_catalog]
local = [{ id = "qwen...", context_window = 32768 }]
```

---

## Rough impact

Current distribution (25.5k LOC): `ui/tui` 44.7%, `harness` 28.5%, `ui` app
18.4%, `ui/commands` 6.5%, root 1.9%.

R1–R8 target roughly 8–10k LOC of deletion/rewrite in the harness, config,
commands, and app-level UI. The TUI toolkit itself remains until the deferred
item.

## Proposed sequencing

1. **R4** config schema + loader + validation + `/reload`. *(done 2026-09-21)*
2. **R2** `Endpoint`; delete the server/service/llm-config split. *(done 2026-09-21)*
3. **R1** event union; harness yields, UI consumes. *(done 2026-09-21)*
4. **R3** command registry as data; prune command classes. *(done 2026-09-22)*
5. **R5** delete forms/settings. *(done 2026-09-21)*
6. **R6** remove tabs; one conversation per process. *(done 2026-09-21)*
7. **R7/R8** delete autosave, search, containerization, token estimation. *(done 2026-09-21)*
8. Revisit deferred items.

Each phase ends with fewer files and fewer layers.
