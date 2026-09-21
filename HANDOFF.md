# Pico-Chat — Session Handoff / Resume Doc

**Purpose:** read this first to resume work. It records the repo state, the
agreed simplification plan, what is already implemented, decisions, gotchas,
and the exact next step.

- **Branch:** `cleanup`
- **Working tree:** dirty — R2 + R4 + R5 are implemented and **not committed**
  (the user commits manually)
- **Last updated:** 2026-09-21
- **Canonical plan:** `SIMPLIFICATION.md` (R1–R11 + decisions)

---

## 1. TL;DR

The simplification plan is well underway. Delivered so far:

1. **R4** — config loader: `pico.toml` (intent) + `state.toml` (disposable) +
   `roles/<name>.toml`; validation with reported errors; `/reload`.
2. **R2** — one `Endpoint` type; deleted the
   `LLMServerConfig` / `llm_server.py` / `server_service.py` split.
3. **File-based config editing** — `/config`, `/edit`, `/roles edit`,
   `/server edit` shell out to `$VISUAL`/`$EDITOR` (TUI suspends/resumes).
4. **Roles folder** — one file per role, with a commented example; the old
   `roles.toml` was migrated into `roles/*.toml`.
5. **Config templates** — missing `pico.toml` / roles example are created with
   fully commented documented templates.
6. **R9 guard test** — no `harness/` → `ui/` imports
   (`test/test_core_ui_boundary.py`).
7. **R5** — deleted the authoring UI: settings tab/screen/pages/panel, role
   editor, `/settings` + `/permissions` commands, `openrouter_settings`, and
   the whole form stack. See §6.

**Suite: 511 passing** (down from 652: ~141 tests removed with the form stack).
`compileall` and `vulture --min-confidence 80` clean. 53 test files.

**Next action:** **R1** (one event protocol) or **R6** (remove tabs). R5 already
removed the settings tab, so R6 only has the debug panel + conversation tabs
left. See §6.

---

## 2. Environment & commands

Pixi env, Python 3.14. Run tests with the env python directly:

```bash
.pixi/envs/default/bin/python -m pytest test/ -q          # 511 passing
.pixi/envs/default/bin/python -m compileall -q pico_chat
.pixi/envs/default/bin/python -m vulture pico_chat --min-confidence 80
```

There is no lint/typecheck configured beyond the above.

---

## 3. Configuration model (R4)

All user-level; **no project-local overrides** (decided P1). Override the
directory with `PICO_CONFIG_DIR`.

| Path | Role |
|---|---|
| `~/.config/pico-chat/pico.toml` | Hand-edited intent (servers, ui, context, subagents, debug, styles). |
| `~/.config/pico-chat/state.toml` | Machine-written, disposable: `last_server`, `active_model`, `[last_model]`, `[model_catalog]`. Safe to delete. |
| `~/.config/pico-chat/roles/<name>.toml` | One role per file. Body is the role, file name is the name. |

**Loader** (`pico_chat/pico_cfg.py`):
- Validates unknown sections/keys and types into `config.load_errors`; invalid
  values keep defaults, valid ones still apply. `reload_config()` re-reads.
- Flat attribute surface kept (`pico_cfg.config.<attr>`), so call sites did
  not move. Nested sections map to flat attrs via `_UI_SPEC`, `_CONTEXT_SPEC`,
  `_SUBAGENTS_SPEC`, `_DEBUG_SPEC`.
- `save_server` → `pico.toml`. `save_active_model` / `save_model_selection` /
  `save_model_catalog` → `state.toml`.
- `remove_server`, `set_active_server`, `ensure_config_file` live here.
- `DEFAULT_PICO_TOML` and `DEFAULT_ROLE_TOML` are the commented templates.
- `test/test_config_commands.py` covers the command-level config flows.
- `test/test_config_loader.py` covers validation/fallback.

**Roles** (`pico_chat/harness/roles.py`):
- `_ROLES_DIR` (module-level, from `pico_cfg.get_roles_dir()`).
- Files whose stem starts with `_` or `.` are ignored (`_example.toml`).
- `disabled = true` hides a role; used as a tombstone when a built-in is
  deleted. A file overrides a built-in of the same name.
- Built-ins: `default`, `reviewer`, `researcher`; plus `scaffolder()` used by
  subagents. `list_roles` / `load_role` / `save_role` / `rename_role` /
  `delete_role` / `duplicate_role`.
- The old `~/.config/pico-chat/roles.toml` is **no longer read**; its roles
  were migrated into `roles/*.toml`. The file is left on disk.

**Apply changes with `/reload`** (or `/config`, which reloads on editor exit).

---

## 4. Endpoint model (R2)

`pico_chat/harness/endpoint.py`:

- `Endpoint` — **one concrete type** holding connection config *and* live
  transport (httpx client, caches, selected model, connection state).
  No ABC/subclasses. Differences handled by internal branches:
  - `llamacpp` — `/models[0]`, context via `/props`, single model (cannot honor
    a per-request model; `supports_model_selection` is False).
  - `ollama` — native `/api/tags`, `/api/show`, native `/api/chat` (retains
    usage counters).
  - `openrouter` — enabled-models allowlist, per-model provider routing.
  - `openai` — configured model + known context window table.
- `Endpoint.from_dict(name, data)` reads a `[servers.<name>]` table and resolves
  `api_key_env`. `to_dict()` strips secrets.
- `ModelInfo`, `ConnectionDiagnosis`, `.local`/proxy helpers also live here.
- Factories: `get_active_endpoint()`, `get_endpoint(name)`, `default_endpoint()`.
- `Harness.endpoint` is an `Endpoint` (`self.server` no longer exists).
  `Harness.switch_server(endpoint)` / `switch_model(model)`.

**Deleted:** `harness/llm_server.py`, `harness/llm_server_config.py`,
`harness/server_service.py`.

Model selection is **live discovery**; `state.toml`'s `model_catalog` is only a
completion/offline cache.

---

## 5. Commands & editing

Registered in `ui/commands/registry.py` (20 commands):

```
/help /clear /compact /reload /config /edit
/server list|use|edit|info|remove|diagnose
/model list|<id>|<server>:<id>
/roles list|show|use|edit|duplicate|rename|delete
/openrouter balance /conversation /tab
/debug /tools /status /pwd /cd /stop /resume /exit
```

- **Editor**: `ui/external_editor.py` resolves `$VISUAL` → `$EDITOR` →
  nano/vim/vi, and `open_editor(ui, path)` suspends the TUI
  (`Terminal.suspend`/`resume` in `ui/tui/terminal.py`) then restores it.
- `/config` opens `pico.toml` and reloads; `/edit [file]` opens any file;
  `/server edit` opens `pico.toml`; `/roles edit [name]` opens
  `roles/<name>.toml` (materializing the current policy if absent) or
  `_example.toml` with no name.
- `/server` and `/model` no longer use forms or `ServerService`.

---

## 6. What remains

Ordered roughly by the plan; each phase should end with fewer files.

- **R1 — one event protocol.** Replace `harness/chunks.py` +
  `_process_generation` dispatch + thinking/usage plumbing with one event
  union: `Token`, `Reasoning`, `ToolCall`, `ToolResult`, `PermissionRequest`,
  `Usage`, `Error`, `Done`. Harness yields; UI renders.
- **R6 — remove tabs.** One conversation per process. Collapses `_tabs`,
  `ConversationState`, `_active_runtime`, `_initial_agent`, and "which agent is
  active" bugs. The settings tab is already gone (R5). Touches `ui/app.py`,
  `ui/conversation_runtime.py`, `ui/commands/tabs.py`,
  `ui/tui/components/tab_view.py`, `tab_bar.py`. The debug panel can stay as an
  overlay/toggle or go with the tab bar.
- **R3 — commands as data.** One registry of
  `(name, description, params, handler)`; classes only where a subcommand tree
  plus state is real.
- **R7** — remove conversation autosave (`pico_chat/conversation_autosave.py`);
  keep `/export`.
- **R8** — delete features outright (no plugin layer). Per P4: **keep
  compaction + subagents**; **delete search tools (`search_web`/`search_wiki`),
  containerization, token estimation**. Note the examples in `DEFAULT_ROLE_TOML`
  still mention `search_web`/`search_wiki`/`use_container` — update them when
  those are removed.
- **Deferred:** replacing the bespoke TUI toolkit (keep it for now), deriving
  tool schemas from signatures, built-in nano-style editor.

---

## 7. Decisions (resolved 2026-09-21)

| # | Decision |
|---|----------|
| P1 | **No project-local config.** User-level `pico.toml` + `roles/` only. No trust model. |
| P2 | `pico.toml`: `[ui]`, `[servers.<name>]`, `[context]`, `[subagents]`, `[debug]`, `[markdown_styles]`, `[syntax_highlight]`; one role body per `roles/<name>.toml`; tiny `state.toml`. |
| P2b | `state.toml` = `last_server`, `active_model`, `last_model`, `model_catalog`. Disposable. |
| P3 | Command surface deferred to a dedicated command refactor; editing via `$EDITOR`. |
| P4 | Keep **compaction** + **subagents**. Delete **search tools**, **containerization**, **token estimation**. |
| P5 | `$EDITOR`/`$VISUAL`; built-in editor later. |
| P6 | Start fresh + document; no back-compat keys. |

---

## 8. Gotchas

- **R5 removed all authoring forms.** The remaining interactive UI is the text
  `Popup` and the `[a]`/`[x]` permission prompt in chat history. There is
  currently **no destructive-confirmation modal**: `show_confirmation` had no
  callers and was deleted with `FormPopup`. `/roles delete`, `/server remove`,
  etc. act immediately — add a small standalone confirm modal if that changes.
- `pico_chat/ui/app.py` is still large (~1400 lines) and owns tabs and the
  debug panel. R6 will shrink it.
- Tests isolate config by monkeypatching **module functions**, not instance
  paths: `pico_cfg.get_config_path`, `get_state_path`, `get_roles_dir`, and
  `roles._ROLES_DIR`. Use the same pattern.
- `Harness` attribute is `endpoint` (not `server`); test fixtures use
  `harness.endpoint = FakeServer()` and `patch(...harness.get_active_endpoint)`.
- `endpoint.py` is under the R9 guard (`test/test_core_ui_boundary.py` scans
  `harness/`), so it must not import `ui`.
- The R9 guard allows `main.py` (composition root) to import both.
- `pico_cfg.config` is a global loaded at import; `/reload` mutates it in place.
- When editing tests, remember the form stack is gone: `TextField`,
  `FormPopup`, `FormContainer`, `ProfileList`, `ConfigOverlay`, `RoleEditorForm`
  and friends no longer exist. Use `Button`/`Label` as focusable/leaf stand-ins.

---

## 9. Commit checklist (the user commits; nothing is staged by the assistant)

Working tree contains the **session's** R2+R4+R5 work plus **pre-existing
unrelated churn**. Review before committing:

**Must include (new files, currently untracked):**
- `pico_chat/harness/endpoint.py`
- `pico_chat/ui/external_editor.py`
- `test/test_config_commands.py`
- `test/test_config_loader.py` / `test/test_core_ui_boundary.py` (already added)

**Session deletions:** `harness/llm_server.py`, `harness/llm_server_config.py`,
`harness/server_service.py`; `ui/settings_pages.py`, `ui/openrouter_settings.py`,
`ui/role_editor_form.py`, `ui/role_editor_model.py`,
`ui/commands/settings.py`, `ui/commands/permissions.py`,
`ui/tui/settings_screen.py`, and the form stack
(`ui/tui/components/{form,form_popup,form_schema,field_models,config_overlay,settings_panel}.py`);
tests `test_settings_tab.py`, `test_forms.py`, `test_form_schema.py`,
`test_field_models.py`, `test_tui_form_actions.py`.

**Pre-existing churn, not from this session (decide separately):**
- `.todo`/`.TODO` files moved into `todos/` (staged renames).
- `PROFILE_FORM_REFACTOR.md` deleted (staged).
- Untracked `xorshift/`, `old_HANDOFF.md`, `old_old_HANDOFF.md` — likely
  scratch/history; probably not wanted in the commit.

---

## 10. Working preferences (observed)

- Wants aggressive simplification toward the essence.
- Explicit over implicit (`/reload`, no watchers/magic).
- Config files over UI; edit with `$EDITOR` (built-in editor later).
- Keeps the custom TUI aesthetic; a middle-ground TUI overhaul is planned
  separately — **do not delete the TUI toolkit** as part of R5/R6.
- Terse answers; expect corrections and re-framings.
- **Do not commit unless asked.** The assistant leaves committing to the user.

---

## 11. First thing to do on resume

1. Read `SIMPLIFICATION.md`.
2. `git status` / `git diff` — review the uncommitted R2+R4+R5 work; commit only
   if the user asks.
3. Pick the next phase with the user: **R1** (event union) or **R6** (remove
   tabs). R5 already removed the settings tab, so R6 only has the debug panel
   and conversation tabs left.
4. Keep the suite green (511) and the R9 guard passing after every change.
