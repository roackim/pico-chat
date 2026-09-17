# Pico-Chat — Session Handoff / Resume Doc

**Purpose:** read this first to resume work after the previous conversation is
gone. It records where the repo is, what was already done, the agreed
simplification plan, open questions, and the exact next step.

**Branch:** `cleanup`  •  **Working tree:** clean except this file and
`SIMPLIFICATION.md` (both untracked)  •  **Date written:** 2026-09-17

**Canonical plan:** `SIMPLIFICATION.md` (untracked — commit it). This file
summarizes it and adds session state.

---

## 1. TL;DR

Two bodies of work:

1. **Committed refactor** (Sections B & C of `refactor.todo`) + a `/model`
   correctness fix. All done, all tests green.
2. **In-progress simplification plan** (this doc + `SIMPLIFICATION.md`):
   move all configuration into files, delete the settings/form/tab UI, collapse
   the endpoint model, unify the streaming event protocol. **Agreed in
   principle; not started.** Blocked on the user answering P1–P6 (section 6).

**Next action:** get P1–P6 answers, then start **R4 (config loader +
validation + project overrides + `/reload`)**.

---

## 2. How to run things

```bash
# tests (632 passing)
.pixi/envs/default/bin/python -m pytest test/ -q
# or: pixi run tests

# dead-code check (currently clean at 80 confidence)
.pixi/envs/default/bin/python -m vulture pico_chat --min-confidence 80

# compile check
.pixi/envs/default/bin/python -m compileall -q pico_chat
```

Environment is pixi (`pixi.lock`, `.pixi/envs/default`), Python 3.14.

---

## 3. Repo state after the committed refactor

Relevant commits on `cleanup`:

```
bdce55f fixup! Fixed model server issue
6385214 Fixed model server issue
549083d Section B and C
bc7007a Phase A and ~B of refactor / cleanup
```

### Section C — unified domain model
- **New `pico_chat/harness/permissions.py`** is the single "may I run this?"
  decision point. Deleted `security.py`, `tool_permissions.py`,
  `permission_gate.py` (merged into it).
- `Role` (`harness/roles.py`) is the single source of truth. Removed
  `Role.from_permission_profile` / `to_permission_profile`.
- Deleted `ui/profile_editor_model.py`, `test_profile_editor_model.py`, and the
  `permission-profiles.toml` store.
- `/permissions` and the settings tab now share
  `ui/settings_pages.build_roles_fields`.

### Section B — unified tool registry
- **Deleted `harness/tool_wrappers.py`.** `harness/tools.py` now has a `@tool`
  decorator registry (`ToolDefinition` / `ToolContext` / `RegisteredTool`).
  `run` is registered under key `run_command` with LLM name `run`.
- Public factories kept for tests: `RunTool`, `SearchWebTool`, `SearchWikiTool`,
  `SubagentTool`, `WaitForSubagentsTool`.
- Input modules (`coordinate_mapper`, `cursor_renderer`, `scroll_manager`,
  `input_handlers`) audited and confirmed live.

### `/model` fixes
- Status bar (`ui/app.py`) shows `_cached_model_name` (the model actually sent).
- `/model <model>` (`ui/commands/models.py`) refreshes discovery live and
  refuses to switch to a server that does not list the model.
- `get_server_config_by_name` applies the per-server model selection
  (`harness/llm_server_config.py`).
- Stale catalogs pruned (server removal, `all_models`, `resolve_model_servers`,
  OpenRouter `set_enabled_models` invalidation) in `harness/server_service.py`.
- OpenRouter settings page now actually persists and rebuilds the live server
  (`ui/openrouter_settings.py`; the save callback was previously discarded).
- Single-model endpoints (llama.cpp) reconcile requested vs served model
  (`harness/llm_server.py`, `supports_model_selection`).
- Regression tests: `test/test_model_selection.py` (6 tests).

### `refactor.todo` status
- Sections A and B: done.
- Section C: done except "retire the command allowlist" (deferred by decision —
  keeps current allowlist behavior). Section D's typed-permission-result item is
  done.
- Section G has a checked sub-item for the `/model` fixes; the larger
  server/model redesign is open but is **superseded by this simplification plan**.

---

## 4. Codebase shape (why simplification is the ask)

LOC by area (25.5k total):

| Area | LOC | Share |
|---|---:|---:|
| `ui/tui/` core + components + input | 11,425 | 44.7% |
| `harness/` | 7,274 | 28.5% |
| `ui/` app | 4,702 | 18.4% |
| `ui/commands/` | 1,650 | 6.5% |
| root | 488 | 1.9% |

Largest files: `ui/app.py` 1511, `harness/tools.py` 1477,
`ui/tui/components/form.py` 1330, `ui/chat_history_panel.py` 1272,
`harness/harness.py` 1264, `harness/llm_server.py` 1195,
`ui/tui/components/markdown.py` 942, `harness/server_service.py` 809,
`harness/permissions.py` 807.

The product essence: stream from an endpoint, run approved tools, render a
transcript. Everything else is a setting or a plugin.

---

## 5. Agreed simplification plan (R1–R11)

Full detail in `SIMPLIFICATION.md`. Summary:

- **R1** One event protocol: `Token`, `Reasoning`, `ToolCall`, `ToolResult`,
  `PermissionRequest`, `Usage`, `Error`, `Done`. Harness yields; UI renders.
- **R2** One `Endpoint` type (collapse `LLMServerConfig` + `get_server_config*`
  + `ServerService` + `LLMServer` ABC/4 subclasses).
- **R3** Commands as data: `(name, description, params, handler)` registry.
- **R4** Config: user `~/.config/pico-chat/pico.toml` + `roles.toml`, both
  overridable by project-local `pico.toml`/`roles.toml` (walk up from cwd).
  `/reload` only (explicit, no watcher). Validate and report errors. Separate
  intent (hand-edited) from disposable state (`state.toml`).
- **R5** Delete authoring UI: `form.py`, `form_popup.py`, `settings_panel.py`,
  `settings_screen.py`, `settings_pages.py`, `openrouter_settings.py`,
  `role_editor_form.py`, `role_editor_model.py`, `config_overlay`, settings tab.
  Keep interactive only for permission approval + destructive confirmation.
- **R6** Remove tabs entirely. One conversation per process. Collapses
  `_tabs`, `ConversationState`, `_active_runtime`, `_initial_agent`.
- **R7** Remove conversation autosave/persistence for now; keep `/export`.
- **R8** Delete features outright (no plugin layer).
- **R9** No `core` → `ui` imports (guard test). This is the seam for the user's
  future middle-ground TUI.
- **R10** Quick-change regression accepted; future built-in nano-style editor is
  nice-to-have.
- **R11** Roles stay named; `/role use` remains.

**Deferred:** replacing the bespoke TUI toolkit (user has their own
middle-ground idea); deriving tool schemas from signatures; built-in editor.

---

## 6. OPEN QUESTIONS — need user answers before coding

| # | Question | Recommendation |
|---|----------|----------------|
| P1 | **Project-local config trust.** A cloned repo's config can auto-allow `run` or point at a malicious endpoint. | **TOFU** keyed by config hash in `state.toml`; re-prompt when changed. |
| P2 | **Exact config schema** (`pico.toml`, `roles.toml`, `state.toml`). | See sketch in `SIMPLIFICATION.md`. |
| P3 | **Surviving commands.** | `/help /clear /reload /config /edit /model /server /role /export /quit` (+ maybe `/tools`). |
| P4 | **Headless features to keep vs delete.** | Keep: roles, discovery+selection, context file tree, debug-to-file. **My rec:** keep compaction + subagents; delete search tools, containerization, token estimation. |
| P5 | **Editor.** | `/edit [file]` opens `$VISUAL`/`$EDITOR`; built-in editor later. |
| P6 | **Migration** from current `config.toml`/`roles.toml`. | Start fresh + document (early project). |

Also confirm:
- **P1 security interaction:** project `roles.toml` can redefine `default`; trust
  model must cover roles and permissions, not just servers.
- **P4** is the only place the user's "remove UI complexity, not necessarily
  features" distinction matters.

---

## 7. Recommended sequencing (once P1–P6 settled)

1. **R4** config schema + loader + validation + project overrides + `/reload`.
2. **R2** `Endpoint`; delete the server/service/llm-config split.
3. **R1** event union; harness yields, UI consumes.
4. **R3** command registry as data; prune command classes.
5. **R5/R6** delete forms/settings/tabs; single-conversation app.
6. Revisit deferred items.

Rationale: by the time R5/R6 run, `ui` is already a thin event consumer, so the
UI trim is mostly deletion. Keep R9 absolute throughout.

---

## 8. Working preferences observed from the user

- Wants aggressive simplification toward the essence.
- Prefers explicit behavior (`/reload`, no magic/watchers).
- Configs over UI; content to edit files, with `$EDITOR` (built-in editor later).
- Keeps a custom TUI aesthetic; will pursue a middle-ground TUI overhaul
  separately — do **not** delete the TUI toolkit as part of R5/R6.
- Answers are terse; expect corrections and re-framings.
- Do not commit unless asked (the previous commits were the user's).

---

## 9. First thing to do on resume

1. Read `SIMPLIFICATION.md`.
2. Ask the user for **P1–P4** answers (P5/P6 have safe recommendations).
3. Begin **R4**: design `pico.toml`/`roles.toml`/`state.toml` schema, a
   validating loader with project-local merge, and the `/reload` mechanism.
4. Add a guard test for R9 (no `core` → `ui` imports) and keep the suite green.
