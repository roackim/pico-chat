# Pico-Chat — Handoff

**Branch:** `cleanup` · **Suite:** 522 passing · **Last updated:** 2026-09-22
**HEAD:** `43d0ca7 Input completion unification` (C4.2/C4.3 + C5)
**Tree:** C4.1/C6.2 work uncommitted (new `message_view.py`); scratch untracked
(`old_HANDOFF.md`, `plans/cleanup_round2.md`, `test.json`). The user commits
manually; **nothing is staged by the assistant.**

Read this to resume. The big simplification (`R1–R9`) is done and committed.
Cleanup round 2 (`C1–C6`) is **complete** (C6.2 resolved conservatively). Next up
is the optional picker polish, or the deferred items below.

Canonical plans: `SIMPLIFICATION.md` (R1–R11), `plans/message_ui_rework.md`,
`plans/cleanup_round2.md` (C1–C6, with per-item status).

---

## 1. Commands

```bash
.pixi/envs/default/bin/python -m pytest test/ -q            # 522 passing
.pixi/envs/default/bin/python -m compileall -q pico_chat
.pixi/envs/default/bin/python -m vulture pico_chat --min-confidence 80
.pixi/envs/default/bin/python -m pytest test/test_core_ui_boundary.py -q        # R9 guard
.pixi/envs/default/bin/python -m pytest test/test_command_import_graph.py -q    # command graph guard
```

No lint/typecheck beyond these. Keep the suite green and both guards passing.

---

## 2. Architecture (current)

- **Events:** `harness/events.py` is the one harness→UI union (`Start`, `Token`,
  `Reasoning`, `ToolCall`, `PermissionRequest`, `ToolResult`, `Usage`, `Error`,
  `Done`). `chunks.py` is gone.
- **Endpoints:** `harness/endpoint.py` is the one concrete `Endpoint` (config +
  state + dispatch), with server-family code split out: `endpoint_openai.py`
  (SSE transport/adapters), `endpoint_ollama.py` (native chat + context), and
  `endpoint_discovery.py` (`list_models`/`discover_models`/`query_*`).
  `endpoint_local.py` owns `.local` mDNS resolution. `Endpoint` keeps thin
  delegating wrappers so callers/tests are unchanged. `llm_server*.py` /
  `server_service.py` deleted. The Ollama path normalizes outgoing messages
  (`Endpoint._ollama_messages` → `endpoint_ollama.ollama_messages`): `content`
  `None` → `""`, drops `tool_calls: None` (Ollama/proxies reject null content
  with HTTP 422).
- **Config:** user-level only, split per concern under `~/.config/pico-chat/`:
  `ui.toml`, `context.toml`, `subagents.toml`, `debug.toml`, `styles.toml`,
  `servers.toml`, `roles/<name>.toml`, disposable `state.toml`. `/config
  <section>` edits a file and reloads. `pico.toml` is gone.
- **One conversation per process:** no tabs/`ConversationRuntime`. `chatTUI`
  owns agent, panel, queue, task, tool/permission state. Presenter helpers live
  beside it: `ui/generation_presenter.py` (harness event → messages),
  `ui/status_presenter.py` (status-bar values/colors), and
  `ui/shell_command.py` (the `$` escape). `chatTUI` keeps thin method wrappers.
- **Commands:** `ui/commands/registry.py` is the single assembly point. Leaf
  commands are plain `async def` handlers + a `Command(name, description,
  handler=…, params=…)` entry; only real subcommand trees stay as `Command`
  subclasses (`ServerCommand`, `DebugCommand`, `OpenRouterCommand`). `help`'s
  handler is `registry._help` (it needs the whole registry); domain modules import
  **only** `base`. `/import` and `/export` are top-level leaf commands;
  `/model` is a leaf (no args → picker, `<model>` → select).
- **Message selection + action line:** selected message gets `▌`; an `ActionBar`
  above the input shows actions (right-aligned, muted) or input-prefix hints.
  Actions are only COPY/OUTPUT/ALLOW/DENY.
- **Activity surface:** `SysMsg*` routed to an `ActivityPopup` (`/activity`) +
  status-bar toasts, not the transcript.
- **`@` file picker:** `ContextCompletion` trigger `@`, subsequence
  `fuzzy_match` ranking (dirs first), scroll-following full-width menu, `USER`
  accent, `n/m` counter.
- **Clipboard:** `ui/clipboard.py` (`copy_to_clipboard`) is the single owner:
  native `xclip`/`xsel`/`wl-copy` first, then OSC 52 (`harness/clipboard.py`).

---

## 3. Done recently

- **Clipboard / SSH:** native helpers then OSC 52. `handle_copy_action`,
  `_auto_copy_selection`, and `/debug get_context` all use `ui/clipboard.py`.
  OSC 52 payload truncates on a 4-byte base64 boundary so it stays decodable.
  Feedback distinguishes verified copies (`copied ✓`) from OSC 52
  (`sent via OSC 52`). **VTE terminals (Ptyxis/GNOME Terminal) ignore OSC 52** —
  use `ssh -X` (X11 forwarding, `xclip`) or an OSC 52 terminal.
- **Ollama 422 fix:** `Endpoint._ollama_messages` (see §2). Root cause was
  `content=None` on tool-call-only assistant turns.
- **C1 dead-code sweep (R3-adjacent):** removed orphaned message-action handlers
  (`handle_retry/stop/steer/pause/resume`), the `/resume` command, `_paused_*` /
  `_requeue_after_cancel` / `is_steered`, `editing_prefill_for_resume`, plus
  orphan methods (`ChatHistoryPanel.current_actions/remove_message/get_messages`,
  `WELCOME_MESSAGE`, `Message.set_content_color/set_text`, `app._rgb_to_ansi_fg`,
  `hide_popup`).
- **C6.1 `ui/tui` dead code:** deleted `input_result.py`, `VerticalDivider`, and
  ~14 zero-reference methods/attributes.
- **C2 / R3 commands as data:** 30 leaf classes → functions; classes 38 → 8,
  commands LOC 1716 → 1581. Tests updated to call handlers
  (`cmd_config`, `conversation_import`, …).
- **C3 god-file split:** `endpoint.py` 1,255 → 619 LOC via `endpoint_openai.py`,
  `endpoint_ollama.py`, `endpoint_discovery.py`, `endpoint_local.py` (free
  functions + thin `Endpoint` wrappers). `app.py` 1,192 → 745 LOC via
  `ui/generation_presenter.py` (event→UI), `ui/status_presenter.py`, and
  `ui/shell_command.py`. `harness.py` intentionally not split (murky seams).
  Only test change: `.local` test patches retargeted to
  `pico_chat.harness.endpoint_local._getent_host`.
- **C5 completion unification:** the 4 provider modules
  (`command_/subcommand_/argument_/context_completion.py`) merged into one
  `completion.py`. Uniform `accept_selection(text, cursor) -> (text, cursor)` and
  `trigger_pos(...)`; `input.py` 700 → 602 LOC (priority loop + one
  `_position_menu` replacing 4 branches/factories/positioners). `@` picker
  behaviour unchanged.
- **C4 message UI:** new `ui/message_selection.py` (`SelectionState` +
  `MessageSelection`); `chat_history_panel.py` 1,126 → 843 LOC. `Box` now owns
  the content-wrap width (`Box.thread_content_width`) and the panel/selection
  derive the content origin from the laid-out child (fixes a hit-test/highlight
  mismatch). New `ui/tui/components/message_view.py` (`MessageView(Box)`) owns
  thread rendering, the lifecycle gutter, and collapsed lines; `Box` 719 → 479
  LOC is message-agnostic, and its unreachable compact mode was removed.
  Collapsed-line rendering + inline-action decision live on `Message`.
- **C6.2 toolkit pruning (conservative):** deleted superseded
  `components/input/basic.py` (`LineInput`/`BoxInput`) and `example_screen.py`
  (+ their tests). Kept the generic `choice`/`table_view`/layout/list/container
  primitives. Barrels pruned: `components/__init__` exports only
  `Component, TextComponent, Box, MessageView, InputComponent`; `tui/__init__` is
  a docstring; `input/__init__` exports only `InputComponent`. Suite 515 → 505.
- **Command interface rework:** `/conversation import|export` replaced by
  top-level `/import` / `/export`; `/model list` removed and `ModelCommand`
  collapsed into a leaf `/model` (no args → picker, `<model>` → select). The
  picker is now a centered, searchable overlay (`ui/tui/components/search_modal.py`,
  `SearchModal` over `SelectionMenu`): anchored directly above the input like
  the `/` and `@` menus (same `InputComponent` positioning primitive,
  full-width), accent frame, model id primary with muted aligned
  server/context and a trailing `active` tag on the current model, query shown
  in the title (`Models: qwe `), type-to-filter. It opens instantly
  from the cached catalog and refreshes discovery in the background (bounded by
  `_DISCOVERY_TIMEOUT`), so an unreachable server no longer stalls it.
  The `/` suggestion popup carries per-command descriptions (muted, aligned)
  via `SelectionMenu.item_descriptions`, with the same mechanism wired for
  subcommands. The popup is styled like the `@` file picker (full-width, USER
  frame) and fills its rectangle so it overwrites the action bar behind it.
  Suite 505 → 522.
- Earlier UI polish (unchanged): `▌` prefix bar, inter-message `ui_msg_v_margin`,
  centralized `Box` padding, right-aligned action line, fuzzy-menu styling,
  Ctrl+C quits on first press, `/model` modal picker, `ui_max_input_height`.

---

## 4. What needs change (see `plans/cleanup_round2.md`)

- **Optional picker polish:** breadcrumb/header for the drilled directory;
  tail-truncation for deep paths; dir/file styling. (Match highlighting was
  deliberately removed.)

Deferred: replace the bespoke TUI toolkit; derive tool schemas from signatures;
built-in mini editor.

---

## 5. Gotchas

- Tests isolate config by monkeypatching **module functions**
  (`pico_cfg.get_config_dir`, `get_state_path`, `get_roles_dir`,
  `roles._ROLES_DIR`). Same pattern for new tests.
- `Harness.endpoint` (not `.server`). Test fixtures use
  `harness.endpoint = FakeServer()`.
- `harness/` must not import `ui/` (R9 guard); only `main.py` may import both.
- **Command import graph** (`test/test_command_import_graph.py`): domain modules
  under `ui/commands/` may import **only** `base`; `registry.py`/`__init__.py` are
  the assemblers. Don't add a lazy `core → registry` import — inject via the
  registry instead (see `_help`).
- Command tests call handler **functions** now (`cmd_config`, `cmd_edit`,
  `cmd_reload`, `conversation_export`, `conversation_import`), not classes.
- Ollama native API requires string `content`; keep `ollama_messages`
  normalization when touching the chat payload. `Endpoint._ollama_messages` /
  `_native_response` / `_create_ollama_completion` are thin wrappers over
  `harness/endpoint_ollama.py` (tests pin the wrappers).
- `.local` resolution lives in `harness/endpoint_local.py`; tests patch
  `endpoint_local._getent_host`, not `endpoint._getent_host`.
- Input completion is one module (`input/completion.py`); the provider classes
  live there. `ContextCompletion` is imported from `.completion` in tests.
- `SelectionMenu.render` must clear its whole rectangle (bg fill) before drawing
  — overlay cells aren't auto-blanked, so without it the action bar shows
  through. The `/` and `@` menus set `fill_width` + `frame_color=theme.USER`.
- Command surface is `/import` + `/export` (top-level) and a leaf `/model`
  (no args → picker). The `/` popup descriptions come from
  `get_command_descriptions()` passed to `InputComponent.setup_commands`;
  `SelectionMenu.item_descriptions` renders them muted/aligned. Subcommand
  descriptions use `get_subcommand_descriptions`.
- Transcript text selection lives in `ui/message_selection.py`
  (`panel.selection`), not on `ChatHistoryPanel`. Content geometry comes from
  `Box.thread_content_width` / the laid-out child — don't recompute gutter+padding
  in the panel.
- `Message.box` is a `MessageView` (`ui/tui/components/message_view.py`), a
  thread-mode `Box` subclass. `Box` itself is message-agnostic (it keeps generic
  popup actions + `lines_only`); don't add message fields to it.
- Clipboard/X11 code must stay import-safe in headless test runs. VTE terminals
  do not implement OSC 52.
- `pico_cfg.config` is a global loaded at import; `/reload` mutates in place.
- Form stack is gone (`TextField`, `FormPopup`, `ConfigOverlay`, `RoleEditorForm`
  etc.) — use `Button`/`Label` as test stand-ins.
- Untracked scratch: `old_HANDOFF.md`, `plans/cleanup_round2.md`, `test.json`
  (origin unknown — inspect before committing).

---

## 6. Working preferences

- Aggressive simplification toward the essence; explicit over implicit
  (`/reload`, no watchers).
- Config files over UI; edit with `$EDITOR`.
- Keeps the custom TUI aesthetic; do not delete the TUI toolkit.
- Delete before you design; each step ends with fewer files/layers/lines.
- Terse answers; corrections welcome.
- **Do not commit unless asked.** The user commits manually.
