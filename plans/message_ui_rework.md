# Message & UI System Rework — Proposal

## Purpose

Rework how messages are focused, how a focused message's actions are surfaced,
remove message-deletion actions, and introduce a proper home for output that is
**not** part of the conversation (shell output, command status, notices, etc.).

This is a design proposal, not an implementation. It documents the current
state, the problems, and a target architecture with a migration path.

---

## 1. Current State (as of this proposal)

### 1.1 Message model

- `Message` (`pico_chat/ui/chat_message.py`) wraps content with a `MsgType`
  (`pico_chat/ui/tui/msg_types.py`). Each `MsgType` declares a static
  `actions: List[MsgAction]`.
- `Message.get_active_actions()` filters the static list by runtime state
  (queued, paused, finalized, streaming, tool terminal state).
- `Message` is composed of a `Box` (border/gutter/action bar) around a
  `TextComponent` or `MarkdownComponent`.
- `Message.harness_message_ids` links a UI message to harness history entries.
  Messages with no harness IDs are **not** part of the conversation.

### 1.2 Focus model

- `ChatHistoryPanel` owns `focused_message_index` (a single focused message).
- Focus is entered via:
  - `Up`/`Down` arrows while the history panel has keyboard focus
    (`move_focus_up` / `move_focus_down`).
  - Mouse click on a message (`_cached_hit_test` → `set_focused_message`).
  - Auto-focus on permission requests (`AskPermissionMsg`).
- The app has a **binary** focus model: `_last_focus_id` is either `"input"`
  or `"history"` (`_set_app_focus`, `_update_focus_states`). There is no
  distinct "message focused" state — message focus is a sub-state of the
  history panel.
- `Esc` moves input → history; `i`/`Enter` moves history → input. `Up` at the
  input's first line moves to history; `Down` at the last message moves back
  to input.

### 1.3 Action surfacing

- Actions render as `[key] label` buttons in the **bottom border** of the
  message `Box`, but **only when the message is focused** (thread mode: the
  action line appears below content only when `focused`).
- Actions are triggered by:
  - Pressing the action's key while the message is focused
    (`ChatHistoryPanel.handle_input`).
  - Clicking the action button (`_hit_test_action_bar`).
- `MsgAction` enum: `DELETE, COPY, RETRY, STOP, ALLOW, DENY, OUTPUT, STEER,
  PAUSE, RESUME`.

### 1.4 Non-conversation output today

Everything is a `Message` in the same `ChatHistoryPanel`:

- **Shell commands** (`$ ...`): `_handle_shell_command` adds a `SysMsg`
  "shell" message + a `SysMsg` "output" message. These have **no** harness IDs
  (not in the conversation) but are interleaved in the same scrollable list.
- **Command status / errors**: `SysMsg`, `SysMsgError`, `SysMsgWarning` added
  by commands (`commands.py`, `commands/*.py`), copy feedback, role-change
  notices, generation-stopped notices, etc.
- **Popups** (`/help`, `/status`, `/tools`, `/permissions`, `/debug`): already
  rendered as overlays, not chat messages — the existing "good" pattern.
- **Debug panel**: a separate tab (`DebugLogPanel`).

The problem: `SysMsg`-family messages are visually and structurally mixed into
the conversation list. They pollute `/conversation export` (which exports
`agent.history`, so they don't actually export — but they *look* like part of
the convo), they can be focused/deleted like real messages, and they consume
the `max_messages` budget.

---

## 2. Problems

1. **Focus is ambiguous.** "History focused" and "a specific message focused"
   are conflated. There's no explicit, discoverable "this message is selected"
   state, and no way to act on a message without first knowing its key
   shortcuts.
2. **Actions are hidden until focus, then appear in the border.** The action
   bar is cramped, only visible on the focused message, and mixes many actions
   (`PicoMsg` can show up to 6). Discoverability is poor.
3. **Deletion is a first-class action** (`DELETE` on most types) yet is
   destructive and rarely the intent; it also couples UI deletion to harness
   history truncation (`delete_messages_after_id`).
4. **Non-conversation output is mixed into the conversation.** Shell output,
   status, and notices are `Message`s in the same list, so they're focusable,
   deletable, and visually indistinguishable from conversation content.

---

## 3. Proposed Design

### 3.1 Focus: a real "selected message" state

Introduce an explicit **selection** concept distinct from the input/history
binary focus, mirroring the project's own principle from
`PROFILE_FORM_REFACTOR.md`: *selection is not focus*.

- `ChatHistoryPanel` keeps `focused_message_index`, but the app gains a third
  focus target: `"message"`. `_last_focus_id ∈ {input, history, message}`.
- Entering message selection:
  - `Up`/`Down` from history, or `Up` from input's first line (as today).
  - Mouse click on a message.
  - A dedicated key (e.g. `Tab` or `Enter` on a message) to "select" the
    currently hovered/focused message.
- The selected message is visually distinct: a **selection gutter/marker**
  (e.g. `▌` in the left margin) plus the existing focus border color change.
- `Esc` from a selected message returns to plain history scroll (not straight
  to input), so selection is a stable, dismissible mode.

**Keybindings (proposal):**

| Key | Action |
|-----|--------|
| `Up` / `Down` | move selection between messages |
| `Esc` | leave message selection → history scroll |
| `i` / `Enter` | leave selection → input |
| `Tab` | cycle selection → input → history (optional) |

### 3.2 Actions: a dedicated action bar instead of border buttons

Stop rendering actions in the message's bottom border. Instead, when a message
is selected, show its actions in a **shared, persistent action bar** at the
bottom of the chat workspace (above the input), reusing the existing
`ActionBar` component (`tui/components/bars.py`).

- The action bar lists the selected message's `get_active_actions()` as
  `[key] label` items, always visible while a message is selected.
- Keys still work (press `c` to copy), but the bar makes them discoverable.
- The bar is context-sensitive: it reflects the *selected* message only, so it
  never shows a wall of actions.
- This frees the message `Box` from rendering action buttons entirely, which
  simplifies `Box` (no `_action_hit_regions`, no flash logic) and lets
  messages be more compact.

**Rationale:** the border action bar is the root of the cramped/confusing UX.
A single contextual bar is the standard terminal pattern (vim status line,
fzf, etc.) and matches the existing `StatusBar`/`ActionBar` components.

### 3.3 Remove message deletion actions

- Remove `MsgAction.DELETE` from all `MsgType.actions` lists.
- Remove `handle_delete_action` and the `DELETE` dispatch in
  `_handle_message_action`.
- Keep the underlying capability (`remove_message`, harness truncation) for
  internal use (edit/retry/resume already truncate), but do not expose it as a
  user-facing message action.
- If deletion is still desired, move it behind an explicit, deliberate command
  (e.g. `/delete <n>` or a confirm prompt) rather than a one-key action.

### 3.4 Non-conversation output: a separate "activity" surface

Introduce a clear separation between **conversation messages** (linked to
harness history) and **activity output** (not part of the conversation).

**Principle:** a message is part of the conversation iff it has
`harness_message_ids`. Everything else is activity.

#### Option A (recommended): a dedicated Activity panel/tab

- Add a new panel (like the existing `DebugLogPanel` tab) that owns all
  non-conversation output: shell commands + output, command status/errors,
  notices, copy feedback, role-change notices.
- `ChatHistoryPanel` keeps only conversation messages (user, pico, thinking,
  tool, permission).
- A new `ActivityPanel` (reusing `TextComponent`/`DebugLogPanel` patterns)
  renders a timestamped, scrollable log of activity entries.
- The activity panel is a closeable tab (like debug) or a toggleable overlay;
  it is **never** exported and never counts toward conversation budget.

#### Option B: a status-line / toast channel

- Transient notices (copy feedback, "generation stopped", command status)
  appear as **toasts** in the status bar or a one-line overlay that auto-dismisses.
- Persistent output (shell command results) goes to the activity panel.

**Recommendation:** combine A + B. Use **toasts** for transient one-liners and
an **activity panel** for persistent output (shell results, command logs).
This keeps the conversation clean while preserving access to output.

#### Migration

1. Add `ActivityPanel` and a `notify()`/`activity()` API on the app that routes
   to toasts or the panel.
2. Replace `chat_history_panel.add_message(..., SysMsg*)` calls in commands
   with the activity API (there are ~100 call sites across `commands.py`,
   `commands/*.py`, `settings_pages.py`, `chat_action_handlers.py`).
3. Move `_handle_shell_command` output to the activity panel.
4. Keep `SysMsg`/`SysMsgError`/`SysMsgWarning` types but render them only in
   the activity surface; remove them from the conversation panel's focus/action
   model.

---

## 4. Impacted Files

| File | Change |
|------|--------|
| `pico_chat/ui/tui/msg_types.py` | Remove `DELETE` from action lists; add `ACTIVITY`/`TOAST` marker if needed |
| `pico_chat/ui/chat_message.py` | Drop border action rendering; add selection marker |
| `pico_chat/ui/chat_history_panel.py` | Selection state, action-bar handoff, remove delete path |
| `pico_chat/ui/chat_action_handlers.py` | Remove `handle_delete_action`; route notices to activity |
| `pico_chat/ui/app.py` | Third focus target `"message"`; action bar wiring; activity API |
| `pico_chat/ui/tui/components/bars.py` | Reuse `ActionBar` for message actions |
| `pico_chat/ui/tui/components/box.py` | Remove action-button rendering/hit-regions |
| `pico_chat/ui/commands*.py`, `settings_pages.py` | Route `SysMsg*` to activity/toast API |
| `pico_chat/ui/conversation_runtime.py` | Role-change notice → activity |
| `.wiki/notes/ui.md`, `.wiki/tree/*` | Update docs |

---

## 5. Open Questions

1. Should the activity panel be a tab (like debug) or a toggleable overlay?
   (Tab is more consistent with the existing debug pattern.)
2. Should toasts be clickable/dismissible, or purely transient?
3. Do we keep `SysMsg` in the conversation for *important* errors, or route
   all of them to activity? (Recommend: all to activity; conversation stays
   pure.)
4. Should `/conversation export` gain an option to include activity output?
5. Is `Tab` the right key to enter message selection, or should it be a
   dedicated key to avoid clashing with form navigation?
