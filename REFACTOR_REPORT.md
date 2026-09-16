# pico-chat — Investigation Report & Refactor Plan

**Date:** 2026-09-16
**Scope:** `pico_chat/` (27.7k LOC) + `test/` (10.2k LOC, 621 tests)
**Goal:** prune heavily and simplify a product that has been refactored/over-built many times.

---

## 0. Executive summary

The codebase is **not broken** — all 621 tests pass — but it is **carrying the sediment of several abandoned refactors**. The damage is structural, not functional:

| Symptom | Evidence |
|---|---|
| Shadowed dead modules | `ui/commands.py` (1,641 lines) is fully overridden by `ui/commands/` package |
| Fake modularization | 6 of 13 files in `ui/commands/` are pure re-export shims; the "real" code lives in one 397-line `builtins.py` that re-imports from 8 siblings |
| Duplicated definitions | `settings_pages()` defined twice (`settings_pages.py:190` and `:194`); `input/__init__.py` has two `__all__` blocks |
| Latent landmines | `RoleEditorModel.ensure_tool` calls undefined `ToolPolicy` → `NameError` if ever invoked |
| Dead files | `ui/tui/example_screen.py` (26 lines) referenced nowhere; `ui/commands/core.py` imports a `PrefillCommand` that no longer exists |
| God objects | `Harness` (1,275 lines, 39 methods), `chatTUI` (1,506 lines, 73 methods), `ChatHistoryPanel` (1,272 lines) |
| Duplicate subsystems | Roles *and* permission-profiles model the same policies two ways; two form-field model systems (`FormField` + `FieldModel`) |

**The single biggest win is deletion, not redesign.** Roughly **3–4k LOC (≈13%) can be removed with near-zero behaviour change** before any architectural work begins.

---

## 1. Critical findings

### 1.1 `ui/commands.py` is dead code (1,641 lines) — HIGH severity

There is both:
- `pico_chat/ui/commands.py` — a 1,641-line module
- `pico_chat/ui/commands/` — a package directory

Python resolves the **package**, so `commands.py` is never imported:

```
$ python -c "import pico_chat.ui.commands as c; print(c.__file__)"
/home/Joackim/projects/pico-chat/pico_chat/ui/commands/__init__.py   # package wins
```

It is still tracked in git, still linted, still read by humans, and **~1,346 lines of it are near-duplicate** of `commands/builtins.py`. It is a 1,641-line footgun: any edit to it silently does nothing.

### 1.2 The `commands/` package is a shim theater — HIGH severity

`commands/builtins.py` (the real 397-line implementation) *is* the package. The rest are thin re-export files:

| File | Real (non-import) lines | Role |
|---|---|---|
| `builtins.py` | 278 | **actual implementation** |
| `registry.py` | 5 | re-exports from `builtins` |
| `__init__.py` | 14 | re-exports from `builtins` |
| `core.py` | 13 | re-exports from `builtins`, **broken** (imports `PrefillCommand`, which doesn't exist in the package) |
| `settings.py` | 9 | re-export shim |

`builtins.py` itself imports from `roles`, `models`, `server`, `debug`, `permissions`, `settings`, `conversation`, `tabs` — while those modules in turn import **back** into `builtins` (`debug.py:117`, `builtins.py:175-338`). This is a circular import web held together by mid-file imports, purely to preserve a fake file layout.

### 1.3 Latent crashes / drift

- `ui/role_editor_model.py:73` — `ensure_tool()` references `ToolPolicy`, which is **never imported**. Confirmed: calling it raises `NameError`. Never called today, but it is a trap.
- `ui/commands/core.py` — `from .builtins import (... PrefillCommand ...)` would fail; the `prefill` command no longer exists in the live registry (19 commands, no `prefill`).
- `ui/settings_pages.py:190 & 194` — `settings_pages()` defined twice; first definition is dead.
- `ui/tui/components/input/__init__.py` — two `__all__` assignments concatenated (leftover merge artifact).
- `ui/tui/focus.py:150` — unreachable code after `return` (vulture, 100%).
- `chat_history_panel.py:768` — unused `box_w`/`box_h`; `app.py:1402` — unused `force_full`.

### 1.4 Dead files & repo cruft

| Item | Notes |
|---|---|
| `ui/tui/example_screen.py` | 26 lines, **zero** references in `pico_chat/` or `test/` |
| `ui/commands.py` | see 1.1 |
| `build/` | stale packaged copy of the whole tree (gitignored, but present) |
| `convo.json` | 207 KB session dump in repo root, untracked, ungitignored |
| `hello.txt`, `.memories/`, `tmp/mini-swe-agent/` | scratch/experiment leftovers |
| `docs/` | empty directory (0 tracked files) |
| 5 overlapping TODO files | `TODO.todo`, `todo.todo`, `new.TODO`, `ai.TODO`, `old.TODO.todo` (+ `PROFILE_FORM_REFACTOR.md`) — all tracked, contradicting each other |
| `.wiki/` | 16 tracked files duplicating `notes/` guidance |

---

## 2. Architectural problems (why it keeps getting refactored)

### 2.1 Duplicate policy models: Roles vs Permission Profiles

The same concepts exist twice:

```
harness/tool_permissions.py   ToolPermissionsProfile / RunPermissions / FilePermissions
harness/roles.py              Role / ToolPolicy  ←→  Role.from_permission_profile()
```

`Role.to_permission_profile()` and `Role.from_permission_profile()` exist **only to translate between the two representations**. The editor layer repeats the split: `ui/profile_editor_model.py` (151 lines) and `ui/role_editor_model.py` (73 lines) implement the same lifecycle (select/create/duplicate/rename/remove/update) against two different stores. The settings pages then paper over it:

> *"a role carries every policy the old standalone permissions page offered"* — `settings_pages.py`

This dual model is the root of the recurring confusion noted in the TODOs: *"role / permission is unclear"*, *"when changing permission role: status bar not updated"*, *"deleting permission role not updated till input"*.

**Recommendation:** one model — `Role` — with permissions as a field. Delete `tool_permissions` profile persistence (or demote it to a serializer `Role ↔ TOML`).

### 2.2 Two form-field systems

- `ui/tui/components/form.py` — `FormField` widget hierarchy (1,330 lines: `ToggleField`, `TextField`, `TextAreaField`, `CheckboxListField`, `RadioListField`, `ProfileListField`, `ProfileList`, `InlineChoiceField`, `FormActionField`).
- `ui/tui/components/field_models.py` — `FieldModel[T]` value/validation layer.
- `ui/tui/components/form_schema.py` — `FormFieldSpec` declarative builder that constructs the widgets.

Three layers for one job, with `ProfileList` / `ProfileListField` (≈400 lines) implementing list navigation, rename editing, mouse hit-testing *and* profile lifecycle inline — exactly the coupling `PROFILE_FORM_REFACTOR.md` set out to remove (that plan is **Tracked but unfinished**).

### 2.3 God objects / missing seams

| Object | LOC | Methods | Problem |
|---|---|---|---|
| `Harness` | 1,275 | 39 | owns history, LLM streaming, tool exec, permissions, compaction, subagents, workspace, roles, file listing, status |
| `chatTUI` | 1,506 | 73 | owns tabs, input, rendering, streaming-chunk→message mapping, popups, settings, debug, shell commands |
| `ChatHistoryPanel` | 1,272 | — | rendering + mouse hit-testing + selection + actions + markdown |
| `commands.py`/`builtins.py` | — | — | 35 command classes in one/two files |

`app.py` contains a **240-line streaming `elif`/`else` chain** (`_process_generation`, lines 380–620) mapping `chunks.*` to UI messages, plus a `legacy_runtime` shim (`_process_generation` reinterprets its own positional args, lines 380–394) — a backwards-compat layer for a call signature that has already changed.

### 2.4 UI reaches into harness internals

```
ui → server._original_base_url     (4 sites)
ui → agent._add_message_to_history
ui → server._cached_context_window, _cached_model_name, _model_name_pending, _connection_state
```
Status-bar rendering depends on private attributes. Any harness refactor breaks the UI silently.

### 2.5 Global mutable config

`pico_cfg.config` is a module-level singleton mutated from ~27 files (harness, UI, commands, tools). `llm_server_config.py:197` keeps a global "current config" with a legacy `active_model` kept "in sync for backward compat" (`server_service.py:384`). This makes tab isolation, testing, and concurrency fragile — matching the TODO *"Do not let one tab's workspace change affect another tab."*

### 2.6 Layering violation

`ui/tui/*` (generic TUI toolkit) and `ui/*` (app-specific) are interleaved: `settings_pages.py` (app) is imported by `commands/` and the settings tab; `commands/base.py` defines `ChatUIProtocol` while `commands/` also imports concrete TUI widgets. There is no clean "toolkit vs. app" boundary, so a widget change ripples into command logic.

---

## 3. Pruning opportunity (do this first)

Estimated **≈3,500–4,000 LOC removable with no behaviour change**:

| Action | LOC saved | Risk |
|---|---|---|
| Delete `ui/commands.py` (shadowed) | ~1,641 | none if package verified; **keep a test asserting no `commands.py` exists** |
| Collapse `commands/` shims into `builtins.py` + `base.py` | ~250 (10 files → 2) | low |
| Delete `ui/tui/example_screen.py` | 26 | none |
| Delete `settings_pages()` duplicate + dead `input/__init__` block | ~15 | none |
| Delete `RoleEditorModel.ensure_tool` (NameError) or fix import | 2 | none |
| Delete `build/`, `convo.json`, `hello.txt`, `.memories/`, empty `docs/` | repo hygiene | none |
| Consolidate 5 TODO files + `PROFILE_FORM_REFACTOR.md` + `.wiki/` + `notes/` → `docs/` | n/a | none |
| Merge Roles + permission profiles into one model | ~500 | **medium — the real refactor** |
| Reduce form layers (`FormField` + `FieldModel` + `FormFieldSpec`) | ~300 | medium |
| Collapse 7 command-completion modules in `input/` | ~200 | low |

---

## 4. Proposed refactor plan

### Phase 0 — Stop the bleeding (1 session, zero-risk)
1. Delete `ui/commands.py`; run tests; add a guard test.
2. Fix the `NameError` in `role_editor_model.py`; remove `commands/core.py` or fix it.
3. Remove `example_screen.py`, duplicate `settings_pages()`, duplicate `__all__`.
4. Sweep `vulture --min-confidence 80` findings.
5. Prune repo: `build/`, `convo.json`, `.memories/`, `hello.txt`, empty `docs/`; gitignore scratch.
6. Consolidate docs/TODOs into `docs/` with one `ROADMAP.md`.

**Exit criteria:** `pytest` green, `vulture` clean at 80%, no shadowed modules.

### Phase 1 — Module surgery (prune, no redesign)
7. Collapse `ui/commands/` to `builtins.py` + `base.py` (keep the package `__init__` as the only public API). Kill the circular mid-file imports.
8. Split `builtins.py` by *domain* along its real seams (conversation / server / model / debug / permissions) — the files already exist; stop re-exporting through `builtins`.
9. Merge command-completion modules in `input/` (`argument_`, `command_`, `subcommand_`, `server_`, `path_`, `context_completion`) into one completion engine.

**Exit criteria:** no file > 700 LOC in `ui/commands/`; import graph acyclic (enforce with a test or `import-linter`).

### Phase 2 — Unify the domain model (the core simplification)
10. Make `Role` the single source of truth (tools + policies + prompt). Turn `tool_permissions` into serialization/validation helpers only.
11. Delete `profile_editor_model.py`; keep `role_editor_model.py` as the one lifecycle model.
12. Update `settings_pages.py` + `/permissions` to operate on roles only. Collapse the two settings surfaces.

**Exit criteria:** one policy model, one editor model, one settings surface; no `from_permission_profile` translation layer.

### Phase 3 — Break the god objects
13. Extract from `Harness`: `StreamAssembler` (LLM streaming + tool-call buffer), `ToolExecutor`, `Compactor`, `SessionState` (history/IDs/usage). `Harness` becomes a thin coordinator.
14. Extract from `chatTUI`: `TabManager`, `StreamPresenter` (the 240-line chunk dispatch), `PermissionPresenter`, `SettingsPresenter`.
15. Introduce an explicit `AgentView` protocol so the UI stops touching `server._*` / `agent._*` privates.

**Exit criteria:** no class > 400 LOC; UI has zero private-attribute access into harness.

### Phase 4 — Rebuild the form layer (finish `PROFILE_FORM_REFACTOR.md`)
16. Adopt the documented `InputResult` protocol; make containers own navigation and leaves own activation.
17. Delete `ProfileListField`/`ProfileList` special-casing; express profiles as a generic list + buttons.

**Exit criteria:** one field abstraction; no widget writes another's private cursor state.

---

## 5. Concrete next steps (recommended order)

1. **Approve Phase 0** — it is pure deletion and unblocks everything.
2. Add a `tests/test_no_shadowed_modules.py` guard so `commands.py` can never return.
3. Add `import-linter` (or a small AST test) to forbid `ui/commands/*` → `builtins` cycles and `ui` → `harness` private access.
4. Only then start Phase 2 (the role/permission unification) — it is the change that actually "simplifies the product".

> **Guiding principle:** delete before you design. This codebase's problem is not missing abstractions — it has too many competing ones. Each phase should end with *fewer* files and *fewer* layers than it started with.