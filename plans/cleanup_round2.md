# Cleanup Round 2 — Plan

**Status:** proposed (no code yet) · **Owner:** Joackim · **Created:** 2026-09-22
**Companion docs:** `SIMPLIFICATION.md` (R1–R11), `plans/message_ui_rework.md`,
`REFACTOR_REPORT.md` (older, mostly executed).

Continue the simplification in the same spirit: **delete before you design**;
each step ends with fewer files / fewer layers / fewer lines. No new
abstractions unless they remove more than they add.

---

## Additions log

> Use this section for items to fold into the plan. Keep one line each; promote
> to a numbered workstream when it is ready.

- _(add here)_

---

## Baseline (2026-09-22)

| Area | LOC |
|---|---|
| `pico_chat/harness` | 5,629 |
| `pico_chat/ui/tui` | 9,389 |
| `pico_chat/ui` (app + commands, excl. `tui`) | 5,176 |
| `pico_chat` total | 21,018 |
| `test` | 8,398 (513 passing) |

Gates after every workstream:

```bash
.pixi/envs/default/bin/python -m pytest test/ -q
.pixi/envs/default/bin/python -m compileall -q pico_chat
.pixi/envs/default/bin/python -m vulture pico_chat --min-confidence 80
.pixi/envs/default/bin/python -m pytest test/test_core_ui_boundary.py -q   # R9
```

---

## C1 — Dead-code sweep *(done 2026-09-22)*

**Goal:** delete handlers/attributes orphaned by the removal of message actions
(PAUSE/RESUME/STEER/DELETE/EDIT/RETRY/STOP) and by earlier refactors.
**Evidence:** `vulture --min-confidence 60` + zero references (including tests).

### C1.1 Action machinery (no longer reachable)

All of these live in `pico_chat/ui/chat_action_handlers.py` and are referenced
**nowhere** (grep of `pico_chat/` + `test/`):

| Symbol | Notes |
|---|---|
| `handle_retry_action` | message actions removed |
| `handle_stop_action` | `/stop` uses `stop_generation` directly |
| `handle_steer_action` | STEER action removed |
| `handle_pause_action` | PAUSE action removed; only writer of pause state |
| `handle_resume_action` | only reads pause state ⇒ always "Nothing to resume." |

Follow-ons:

- Delete `ResumeCommand` (`ui/commands/core.py`) and its registry entry; the
  `/resume` command is unreachable without pause/steer. Update `BASE`/help.
- Delete `app.py` line ~817 `self.handle_resume_action(None)`.
- Delete now-dead state: `_paused_user_input`, `_paused_user_msg`,
  `_requeue_after_cancel` (`app.py`), and `Message.is_steered`
  (`ui/chat_message.py`) + the `is_steered` branch in `app.py`.
- Keep `Message.is_queued` — it is live (queueing while generating).

### C1.2 Orphan methods / constants

| Location | Symbol | Action |
|---|---|---|
| `ui/chat_history_panel.py` | `current_actions` | delete |
| `ui/chat_history_panel.py` | `remove_message` | delete (no callers; `remove_message_by_index` is the live one) |
| `ui/chat_history_panel.py` | `get_messages` | delete |
| `ui/chat_history_panel.py` | `WELCOME_MESSAGE` | delete |
| `ui/chat_message.py` | `set_content_color` | delete |
| `ui/chat_message.py` | `set_text` | delete (verify no dynamic call) |
| `ui/app.py` | `_rgb_to_ansi_fg` | delete |
| `ui/commands/base.py` | `ChatUIProtocol.hide_popup` | delete if unused (verify) |

Keep `restore_messages` / `get_formatted` — used by tests and by copy/export.

### Exit criteria

- No reference to any deleted symbol; suite green; vulture@80 still clean.
- Net deletion expected **~250–300 LOC** and one command from the surface.

---

## C2 — Finish R3: commands as data *(done 2026-09-22)*

**Goal:** collapse trivial `Command` subclasses into registry entries. Keep a
class only where there is a real subcommand tree and/or state.
**Evidence:** 38 classes, 1,716 LOC in `ui/commands/`.

### Target shape

One registry entry: `(name, description, params, handler)` where `handler` is a
plain `async def (ui, args)`. Classes remain only for:

- `server` (list/use/edit/info/remove/diagnose)
- `model` (list/use)
- `roles`
- `debug`
- `conversation`
- `openrouter`
- `tools` (if it grows subcommands; currently a leaf)

Everything in `core.py` + `HelpCommand`, plus `ResetCommand`/leaf `tools` etc.,
becomes a function. `Command`/`Param` stay as the completion contract, or are
reduced to a small `CommandSpec` dataclass if it removes the subclass layer
entirely.

### Constraints

- Preserve `/help` listing and `get_subcommand_list` behaviour.
- Preserve argument completion (`Param`, `config_section_completions`,
  `server_name_completions`, path scan).
- No change to command output or routing.

### Open question

- Full "spec as data" (no `Command` base at all) vs. "functions + registry"
  (keep `Command` for subcommand dispatch). Recommendation: start with
  functions + registry; only introduce `CommandSpec` if the subcommand classes
  still feel heavy.

### Exit criteria

- `ui/commands/` drops to ~4 modules, **~800 LOC total**; registry is the only
  assembly point; suite green.

**Done (2026-09-22):** leaf commands are now plain handler functions assembled
by `registry.py`; `Command` grew an optional `handler`. Only the 5 real
subcommand trees remain as classes (`ServerCommand`, `ModelCommand`,
`DebugCommand`, `OpenRouterCommand`, `ConversationCommand`). Classes: 38 → 8;
LOC 1716 → 1581. Per-domain module files were **kept** (merging them would add
churn without removing a layer), so the ~4-module goal was intentionally not
chased. The command import-graph guard still passes.

---

## C3 — Split the god files

**Goal:** no product file > ~700 LOC; split along existing seams, not new
layers. Behaviour-preserving.

### C3.1 `harness/endpoint.py` (1,255 LOC)

Natural seams (all currently in one class / module):

| New module | Contents |
|---|---|
| `harness/endpoint.py` | `Endpoint` config + state, `from_dict`/`to_dict`, model selection, `create_completion` dispatch, `ModelInfo`, `ConnectionDiagnosis` |
| `harness/endpoint_openai.py` | `_create_openai_completion`, `_iter_sse_chunks` |
| `harness/endpoint_ollama.py` | `_native_base_url`, `_check_ollama_connection`, `_ollama_messages`, `_create_ollama_completion`, `_native_response`, context-window helpers |
| `harness/endpoint_discovery.py` | `list_models`/`discover_models`/`_discover_*_models`/`query_*` |

Use **free functions taking `endpoint`** (or thin mixins) — prefer functions to
avoid MRO complexity. `endpoint.py` re-exports nothing new; callers unchanged.

### C3.2 `harness/harness.py` (1,166 LOC)

| New module | Contents |
|---|---|
| `harness/streaming.py` | `_stream_llm_response`, `_assemble_tool_calls`, thinking-tag handling |
| `harness/tool_executor.py` | `_execute_tool_calls`, permission prompt plumbing |
| `harness/compaction.py` | `_is_compaction_message`, `_get_last_compaction_index`, `_get_effective_history`, `compact_history` |
| `harness/subagents.py` | `_auto_wait_subagents` + abort/wait plumbing |

`Harness` becomes a coordinator delegating to these. Watch for shared state
(`history`, `tools_map`, `_permission_gate`) — pass the harness in rather than
copying state.

### C3.3 `ui/app.py` (1,192 LOC)

- Extract `_process_generation` (~235 LOC) into a presenter module
  (`ui/generation_presenter.py` or `ui/stream_presenter.py`): maps harness events
  → UI messages. This is the old "StreamPresenter" idea and the single biggest
  readability win.
- Extract shell command handling (`_handle_shell_command`) and the popup/list
  modal helpers if they remain bulky.
- Keep focus management in `app.py` for now (it is the coordinator).

### Exit criteria

- No file > ~700 LOC in `harness/` or `ui/app.py`.
- No new global mutable state; import graph acyclic.
- Suite green; R9 guard green.

**Done (2026-09-22):** `harness/endpoint.py` 1,255 → 619 LOC via
`endpoint_openai.py` (SSE transport + adapters), `endpoint_ollama.py` (native
chat + context), `endpoint_discovery.py` (`list_models`/`discover_models`/
`query_*`), `endpoint_local.py` (`.local` resolver). Free functions take the
endpoint; `Endpoint` keeps thin delegating wrappers so callers/tests are
unchanged (only the `.local` test patch path moved to `endpoint_local`).
`ui/app.py` 1,192 → 745 LOC via `ui/generation_presenter.py` (event→UI),
`ui/status_presenter.py`, and `ui/shell_command.py`, each with a thin `chatTUI`
wrapper. `harness.py` was intentionally **not** split. Remaining over-700 files
are `app.py` (745) and `endpoint.py` (619 is under; `app.py` retains focus
management by design).

---

## C4 — `MessageView` extraction + `ChatHistoryPanel` split

**Goal:** remove message-specific modes from the generic `Box`, make padding
single-owner end-to-end, and separate layout/scroll from message selection.
Bound to `plans/message_ui_rework.md` §3.2–3.3.

### C4.1 `Box` sheds message concerns

`Box` currently carries message-specific behaviour:

- modes: normal / `compact_when_unfocused` / `lines_only` / `thread_mode` /
  collapsed (`_render_compact_to_subbuffer`, `_render_lines_only_to_subbuffer`,
  `_render_thread_to_subbuffer`, `_render_collapsed_line`);
- action rendering + hit regions + flash (`_visible_actions`, action-bar hit
  testing).

Target: `Box` keeps **borders, gutter, padding, clipping** only. Message
decoration (status glyph, done label, metrics, action line) moves into a
`MessageView` (new `ui/message_view.py`) or onto `Message` directly.

### C4.2 Padding single owner

`Message` currently composes `Box(content_pad_left/right)` around an unpadded
content component, with width math duplicated in `chat_history_panel`
(`_screen_to_display_col`, `_get_message_height`). Make `Box` the only owner of
content padding and expose the content rect so the panel stops recomputing it.

### C4.3 Split `ChatHistoryPanel` (1,153 LOC)

| New unit | Responsibility |
|---|---|
| `ChatHistoryPanel` | message list, layout, scroll, render |
| `MessageSelection` | `SelectionState`, hit-test, column resolution, `get_selection_text`, drag handling |
| caches | `_row_index` / virtual-Y ranges, invalidated explicitly |

### Exit criteria

- `Box` has no message-type knowledge (message decoration lives in
  `MessageView`/`Message`). Generic popup actions stay in `Box`.
- One padding computation; panel cell math shares it.
- No file > ~700 LOC; suite green.

**Done (2026-09-22):**
- **C4.2** — `Box.thread_content_width(box_width, pad_l, pad_r)` is now the one
  owner of the `gutter(1) + padding` wrap math; used by `Box` layout and by the
  panel's `on_width_change`/`new_message`. `MessageSelection` derives the
  content origin from the laid-out inner component (`child.x + left_pad`) instead
  of recomputing gutter/padding/margins — this also fixed an inconsistency where
  hit-testing and the highlight overlay disagreed by the padding width.
- **C4.3** — new `ui/message_selection.py` (`SelectionState` + `MessageSelection`)
  owns drag state, column resolution, text extraction, and the highlight
  overlay. `chat_history_panel.py` 1,126 → 843 LOC and keeps only the message
  list / layout / scroll / render glue.
- **C4.1** — new `ui/tui/components/message_view.py` (`MessageView(Box)`) owns all
  chat-transcript presentation: thread layout, lifecycle-aware gutter, collapsed
  thinking lines, and the (currently always-empty) inline action row. `Box`
  **479 LOC** (was 719) is now message-agnostic: borders, gutter, padding,
  clipping, generic popup actions, `lines_only`, and `inline_editor`. Removed the
  unreachable `compact_when_unfocused` render mode from `Box` and the
  `parent_msg`/metrics branches. `Message.box` is a `MessageView`. Added
  thread-render smoke tests (`test_chat_message.py`); popup action hit-region
  tests already covered the generic action line.
  Box's action rendering stays because it is *generic* and load-bearing for
  popups (`debug_popup`/`popup`/`list_modal`), not message inline actions.

---

## C5 — Input completion unification

**Goal:** one completion engine instead of six overlapping modules.
**Evidence:** `ui/tui/components/input/` holds `completion.py` (91),
`command_completion.py` (72), `subcommand_completion.py` (106),
`argument_completion.py` (168), `context_completion.py` (227) — plus
`input.py` (700) / `basic.py` (348) / `input_handlers.py` (194).

Target: a single `completion.py` with trigger-based providers (`/` command,
`/cmd ` sub-command, `@` context, generic argument via `Param.completions`).
Keep the `@` picker behaviour intact (fuzzy ranking, dirs first, scroll-follow)
and the `Command.params` contract.

### Exit criteria

- One completion module + `input.py`; no duplicated fuzzy/menu logic.
- Suite green, including the fuzzy/menu tests.

**Done (2026-09-22):** the four provider modules
(`command_completion.py`, `subcommand_completion.py`, `argument_completion.py`,
`context_completion.py`) merged into `completion.py` (675 LOC) alongside the
`Completer` base. Providers now share a uniform interface:
`accept_selection(text, cursor) -> (text, cursor)` and
`trigger_pos(text, cursor)` (menu anchoring moves out of `input.py`).
`input.py` 700 → 602 LOC: the four hand-written priority branches, four lazy
menu factories, and four positioning methods collapse into
`_completion_providers()` + one loop + `_position_menu()`. One test import path
updated; `@` picker behaviour (fuzzy ranking, dirs-first, `../`, scroll-follow)
unchanged.

---

## C6 — `ui/tui` dead-code / toolkit pruning

**Goal:** remove sedimentary toolkit code without gutting the toolkit. The
toolkit is intentionally kept for the deferred TUI replacement, so this is split
into **C6.1 (unambiguous dead)** and **C6.2 (policy call)**.

**Method:** AST reference map over `pico_chat/` + `test/`, excluding the barrel
re-exports (`ui/tui/__init__.py`, `ui/tui/components/__init__.py`,
`ui/tui/components/input/__init__.py`). `vulture@80` is clean but `@60` is
unreliable here (it flags `self._x` calls), so lists below come from the AST
count, not vulture.

### C6.1 Unambiguous dead (zero refs in product **and** tests) *(done 2026-09-22)*

- **Module** `ui/tui/input_result.py` (29 LOC) — `InputResult`, `from_legacy`.
  Nothing imports it; drop the module.
- **Symbol** `components/layout.py::VerticalDivider` — zero refs; drop it and its
  barrel export.
- **Methods** (zero AST refs anywhere):

| File | Method |
|---|---|
| `terminal.py` | `color_rgb_fg`, `color_rgb_bg` |
| `components/box.py` | `current_fg_color` |
| `focus.py` | `focus_previous` |
| `compositor.py` | `get_actual_fps`, `update_component` |
| `components/menu.py` | `set_highlight_color`, `set_position_at`, `get_selection` |
| `actions.py` | `has` |
| `components/input/input.py` | `hide_completions` |
| `buffer.py` | `set_cursor` |
| `components/bars.py` | `set_text` |
| `layout_utils.py` | `split_word_at_width` |

- **Dead state** (assigned, never read — verified):
  `Box._last_size`, `Box.suppress_focus_marker`,
  `SelectionMenu._manual_x`/`_manual_y`, `CursorRenderer.last_blink_time`,
  `InputHandlers.menus`; in `app.py`: `self.chat_screen`, `self.navigator`,
  `self._list_modal_screen` (keep constructing `ChatScreen`/`Navigator` for their
  side effects: `chat_screen.root`, `event_router` action map — just stop storing
  them).

### C6.2 Policy call — toolkit widgets with no product consumer

These are **tested library widgets** used nowhere in product code. They are
candidates for deletion under "delete before you design", but they are also the
kind of generic primitive a future toolkit would want. Git history keeps them.

| Module | LOC | Symbols | Tests to drop |
|---|---|---|---|
| `components/choice.py` | 148 | `Checkbox`, `RadioGroup`, `set_value`, `_select_cursor` | `test_choice_widgets.py` |
| `components/table_view.py` | 136 | `TableView` (+ helpers) | `test_table_view_widget.py` |
| `components/input/basic.py` | 348 | `LineInput`, `BoxInput`, `_CursorBlink` (superseded by `input.py`) | `test_basic_inputs.py` |
| `container.py` | — | `Vsplit`, `Align`, `Overlay`, `ScrollView` only; keep `Content/Fill/Hsplit/Padding/Stack/Fixed/Percent/Split/Container` (used by `chat_screen.py`) | `test_layout_primitives.py` (partial) |
| `components/list_view.py` | — | `Select` only; keep `ListView`/`SelectionModel` | `test_list_view_widget.py` (partial) |
| `components/layout.py` | — | `SeparatorLine` only; keep `EmptyLine` (used by markdown) | `test_layout_primitives.py` (partial) |
| `events.py` | — | `CommandEvent` only (barrel/test) | `test_tui_foundations.py` (partial) |
| `example_screen.py` | 26 | `ExampleScreen` | `test_example_screen.py` |

**Recommendation:** do **C6.1 now**; for C6.2, delete the clearly superseded
ones (`basic.py`, `VerticalDivider` already in C6.1, `example_screen.py`) and
keep the generic layout/list/choice widgets unless the toolkit replacement is
actual work. Barrels (`tui/__init__`, `components/__init__`) get pruned to the
used set either way, which shrinks the public surface without deleting code.

### Exit criteria

- No zero-reference module/symbol remains in `ui/tui`.
- Barrel exports match real usage.
- Suite green after dropping the tests for anything deleted.

**Done (2026-09-22, conservative branch):** deleted the superseded
`components/input/basic.py` (`LineInput`/`BoxInput`) and `example_screen.py`,
with their tests. Kept the generic `choice`/`table_view`/layout/list/container/
events primitives (per the recommendation; git history retains the alternative).
Pruned both barrels to the used set: `components/__init__` now exports only
`Component`, `TextComponent`, `Box`, `MessageView`, `InputComponent`;
`tui/__init__` is a docstring (nothing imported symbols from it).
`input/__init__` exports only `InputComponent`. Suite 515 → **505 passing**
(10 widget tests dropped with the two deleted modules).

---

## Deferred (unchanged)

- **TUI toolkit replacement** — keep the bespoke toolkit and aesthetic; R9 is
  the seam that makes it swappable.
- **Tool schemas from signatures** — replace manual wrappers in
  `harness/tool_wrappers.py` once the rest settles.
- **Built-in mini editor** (R10 nice-to-have).

---

## Suggested sequencing

1. **C1** — pure deletion, de-risks C2 by removing handlers R3 would touch.
2. **C2** — closes the last open item in `SIMPLIFICATION.md`.
3. **C3** — split god files (mechanical, medium risk).
4. **C4** — `MessageView` + panel split (design work; depends on C3.3).
5. **C5** — completion unification.
6. **C6** — `ui/tui` dead-code sweep (independent; can run first, alongside C1).

Each step lands on a green suite and updates `HANDOFF.md` + `.wiki/` at the end.
